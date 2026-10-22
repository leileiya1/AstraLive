"""Guardian-owned RTMP publisher sink (RTMP_PIPE_WRITE), stage 3b.

Same owned-child architecture as CPUMedia; only the child's media work
differs: every admitted item is encoded and written as one FLV tag onto ONE
persistent RTMP publish connection for the whole Session, then acknowledged
to the parent. The acknowledgement means "handed to the kernel socket of the
RTMP pipe" (sendall returned), nothing more: it is not audience delivery and
never a drain by itself (the independent Observer and the Backend decide).

The child speaks RTMP itself instead of using libav's FLV/RTMP muxer: libav's
interleaver keeps the last packet of a unit queued until a packet of the
other stream arrives (measured: the unit's final 640 samples reached the pipe
only at disconnect), and PyAV cannot flush it. Writing each tag directly
makes the acknowledgement truthful with no padding or flush between units.

Sample-exact by construction:
* audio is 16-bit mono PCM in FLV (no AAC priming or partial-frame hold-back);
* video is H.264 zerolatency, no B-frames, one keyframe per second, so each
  frame is emitted immediately and a late reader recovers within a second.
Timestamps are stream-relative to the trusted Session origin captured at
start, in RTMP milliseconds (nearest). Platform AAC is a transcode AFTER this
proven sink and is out of scope here.
"""

import hashlib
import json
import os
import socket
import struct
import threading
import time
from fractions import Fraction
from urllib.parse import urlsplit

from .clocks import suspend_clock as clock
from .cpu import CPUMedia, _receive, _send
from .gate import require

CHUNK = 4096


class PublishRefused(RuntimeError):
    pass


def _amf(value):
    if value is None:
        return b"\x05"
    if isinstance(value, bool):
        return b"\x01" + bytes([value])
    if isinstance(value, (int, float)):
        return b"\x00" + struct.pack(">d", value)
    if isinstance(value, str):
        raw = value.encode()
        return b"\x02" + struct.pack(">H", len(raw)) + raw
    if isinstance(value, dict):
        out = b"\x03"
        for key, item in value.items():
            raw = key.encode()
            out += struct.pack(">H", len(raw)) + raw + _amf(item)
        return out + b"\x00\x00\x09"
    raise TypeError(type(value))


def _amf_read(data, at):
    kind = data[at]
    if kind == 0:
        return struct.unpack(">d", data[at + 1 : at + 9])[0], at + 9
    if kind == 1:
        return bool(data[at + 1]), at + 2
    if kind == 2:
        n = struct.unpack(">H", data[at + 1 : at + 3])[0]
        return data[at + 3 : at + 3 + n].decode(), at + 3 + n
    if kind in (5, 6):
        return None, at + 1
    if kind in (3, 8):
        at += 1 if kind == 3 else 5
        out = {}
        while data[at : at + 3] != b"\x00\x00\x09":
            n = struct.unpack(">H", data[at : at + 2])[0]
            key = data[at + 2 : at + 2 + n].decode()
            out[key], at = _amf_read(data, at + 2 + n)
        return out, at + 3
    raise PublishRefused("AMF")


def _annexb_units(data):
    """Split an Annex B byte stream into NAL units (without start codes)."""
    units, i, n = [], 0, len(data)
    starts = []
    while i + 3 <= n:
        if data[i : i + 3] == b"\x00\x00\x01":
            starts.append(i + 3)
            i += 3
        else:
            i += 1
    for k, s in enumerate(starts):
        end = starts[k + 1] - 3 if k + 1 < len(starts) else n
        unit = data[s:end]
        while unit.endswith(b"\x00") and k + 1 < len(starts):
            unit = unit[:-1]  # 4-byte start code's leading zero
        if unit:
            units.append(unit)
    return units


def avc_config(extradata):
    units = _annexb_units(bytes(extradata))
    sps = [u for u in units if u[0] & 0x1F == 7]
    pps = [u for u in units if u[0] & 0x1F == 8]
    require(len(sps) == 1 and len(pps) == 1, "OUTPUT_FENCE_UNPROVEN")
    s, p = sps[0], pps[0]
    return (
        bytes([1, s[1], s[2], s[3], 0xFF, 0xE1])
        + struct.pack(">H", len(s)) + s
        + b"\x01" + struct.pack(">H", len(p)) + p
    )


def avcc(packet):
    return b"".join(
        struct.pack(">I", len(u)) + u
        for u in _annexb_units(packet)
        if u[0] & 0x1F not in (7, 8, 9)  # parameter sets live in the config
    )


class Publisher:
    """Minimal blocking RTMP publish client: one connection, one stream.

    Every message is written with fmt-0 chunk headers via sendall; nothing
    is buffered in user space, so a returned write is on the kernel socket.
    A stalled ingest times the write out and the owned child exits.
    """

    def __init__(self, url, timeout):
        parts = urlsplit(url)
        path = parts.path.strip("/").split("/", 1)
        require(parts.scheme == "rtmp" and len(path) == 2 and all(path), "INVALID_ARGUMENT")
        self.app, self.stream_name = path
        self.tc_url = f"rtmp://{parts.hostname}:{parts.port or 1935}/{self.app}"
        self.sock = socket.create_connection((parts.hostname, parts.port or 1935), timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(timeout)
        self.inbox, self.in_chunk, self.in_streams = bytearray(), 128, {}
        self.stream_id = 0

    def _read(self, n):
        while len(self.inbox) < n:
            data = self.sock.recv(65536)
            if not data:
                raise PublishRefused("closed")
            self.inbox += data
        out = bytes(self.inbox[:n])
        del self.inbox[:n]
        return out

    def _message(self):
        """Read one complete server message: (type, payload)."""
        while True:
            b = self._read(1)[0]
            fmt, csid = b >> 6, b & 0x3F
            if csid == 0:
                csid = self._read(1)[0] + 64
            elif csid == 1:
                lo, hi = self._read(2)
                csid = lo + hi * 256 + 64
            header = self._read((11, 7, 3, 0)[fmt])
            state = self.in_streams.setdefault(csid, dict(length=0, type=0, body=b"", ext=False))
            if fmt < 3:
                state["ext"] = header[0:3] == b"\xff\xff\xff"
            if fmt <= 1:
                state["length"], state["type"] = int.from_bytes(header[3:6], "big"), header[6]
            if state["ext"]:
                self._read(4)
            need = min(self.in_chunk, state["length"] - len(state["body"]))
            state["body"] += self._read(need)
            if len(state["body"]) == state["length"]:
                body, state["body"] = state["body"], b""
                if state["type"] == 1:
                    self.in_chunk = int.from_bytes(body[:4], "big") & 0x7FFFFFFF
                    continue
                return state["type"], body

    def _send(self, csid, kind, timestamp, stream_id, payload):
        ts = min(timestamp, 0xFFFFFF)
        ext = struct.pack(">I", timestamp) if ts == 0xFFFFFF else b""
        header = (
            bytes([csid])
            + ts.to_bytes(3, "big")
            + len(payload).to_bytes(3, "big")
            + bytes([kind])
            + struct.pack("<I", stream_id)
            + ext
        )
        out = [header + payload[:CHUNK]]
        for at in range(CHUNK, len(payload), CHUNK):
            out.append(bytes([0xC0 | csid]) + ext + payload[at : at + CHUNK])
        self.sock.sendall(b"".join(out))

    def _command(self, name, txn, *args, stream=0):
        self._send(3 if stream == 0 else 8, 20, 0, stream, b"".join(_amf(v) for v in (name, txn) + args))

    def _await(self, want):
        while True:
            kind, body = self._message()
            if kind != 20:
                continue
            name, at = _amf_read(body, 0)
            _, at = _amf_read(body, at)
            values = []
            while at < len(body):
                value, at = _amf_read(body, at)
                values.append(value)
            if name == "_error":
                raise PublishRefused("refused")
            if name == want[0] and (len(want) == 1 or any(
                isinstance(v, dict) and v.get("code") == want[1] for v in values
            )):
                return values

    def open(self, metadata):
        c1 = struct.pack(">II", 0, 0) + os.urandom(1528)
        self.sock.sendall(b"\x03" + c1)
        s0s1 = self._read(1537)
        require(s0s1[0] == 3, "OUTPUT_FENCE_UNPROVEN")
        self._read(1536)  # S2
        self.sock.sendall(s0s1[1:])  # C2 echoes S1
        self._send(2, 1, 0, 0, struct.pack(">I", CHUNK))
        self._command("connect", 1, dict(app=self.app, type="nonprivate", flashVer="FMLE/3.0", tcUrl=self.tc_url))
        self._await(("_result",))
        self._command("createStream", 2, None)
        self.stream_id = int(next(v for v in self._await(("_result",)) if isinstance(v, float)))
        self._command("publish", 3, None, self.stream_name, "live", stream=self.stream_id)
        self._await(("onStatus", "NetStream.Publish.Start"))
        meta = _amf("@setDataFrame") + _amf("onMetaData") + _amf(metadata)
        self._send(4, 18, 0, self.stream_id, meta)

    def audio(self, timestamp, pcm):
        self._send(4, 8, timestamp, self.stream_id, b"\x32" + pcm)

    def video(self, timestamp, keyframe, kind, payload):
        head = bytes([(0x10 if keyframe else 0x20) | 7, kind, 0, 0, 0])
        self._send(6, 9, timestamp, self.stream_id, head + payload)


def _hold(pauses):
    if pauses:  # test-only barrier: the item is encoded, not yet written
        pauses["at_before_write"].set()
        pauses["before_write"].wait()


def _rtmp_child(
    sock,
    edge,
    sample_rate,
    width,
    height,
    pauses,
    ready,
    nonce,
    startup_barrier,
    installed_binding,
    origins,
    publish_url,
    fps,
):
    sock.setblocking(False)
    done = threading.Event()

    def watchdog():
        while not done.wait(0.005):
            if os.getppid() != edge.parent_pid:
                os._exit(70)
            if any(edge.tag) and (
                time.monotonic() >= edge.deadlines[0] or clock() >= edge.deadlines[1]
            ):
                os._exit(70)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        if startup_barrier is not None:
            startup_barrier[0].set()
            startup_barrier[1].wait()
        import av
        import numpy as np

        video = av.CodecContext.create("libx264", "w")
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.time_base, video.framerate = Fraction(1, 1000000), fps
        video.flags |= av.codec.context.Flags.global_header
        video.options = {"preset": "ultrafast", "tune": "zerolatency", "bf": "0", "g": str(fps)}
        video.open()
        config = avc_config(video.extradata)
        publisher = Publisher(publish_url, 1.0)
        publisher.open(
            dict(duration=0.0, width=float(width), height=float(height), videocodecid=7.0,
                 framerate=float(fps), audiocodecid=3.0, audiosamplerate=float(sample_rate),
                 audiosamplesize=16.0, stereo=False)
        )
        audio_origin = origins[0]
        audio_origin_us = audio_origin * 1000000 // sample_rate
        configured = False
        if installed_binding is not None:
            from astralive_contracts import durable_live_v2 as dto

            installed = dto.decode("ReceiverBootstrapBinding", installed_binding)
            binding_hash = hashlib.sha256(installed_binding).hexdigest()
            generation = installed.generationId
        else:
            binding_hash, generation = None, None
        with edge.lock:
            require(not any(edge.tag), "OUTPUT_FENCE_UNPROVEN")
        ready.send(
            dict(
                kind="RTMP_PUBLISH_READY",
                nonce=nonce,
                pid=os.getpid(),
                parent=os.getppid(),
                rate=sample_rate,
                width=width,
                height=height,
                bindingHash=binding_hash,
                generation=generation,
                origins=origins,
            )
        )
        ready.close()
        while True:
            item = _receive(sock, edge)
            if installed_binding is not None:
                registration = json.loads(item.lineage.identity)["registration"]
                require(
                    dto.canonical_json(registration) == installed_binding,
                    "STALE_EXECUTION",
                )
            edge.check(item.lineage)
            if item.kind == "audio":
                require(item.audio_start >= audio_origin, "BOUNDARY_CONFLICT")
                require(len(item.payload) % 2 == 0, "INVALID_ARGUMENT")
                offset = item.audio_start - audio_origin
                ts = (offset * 1000 + sample_rate // 2) // sample_rate
                _hold(pauses)
                edge.check(item.lineage)  # revocable edge right before the pipe write
                publisher.audio(ts, item.payload)
            else:
                require(item.pts_us >= audio_origin_us, "BOUNDARY_CONFLICT")
                frame = av.VideoFrame.from_ndarray(
                    np.frombuffer(item.payload, dtype=np.uint8).reshape(height, width, 3),
                    format="rgb24",
                ).reformat(format="yuv420p")
                frame.pts = item.pts_us - audio_origin_us
                frame.time_base = Fraction(1, 1000000)
                packets = video.encode(frame)
                # zerolatency/no B-frames: exactly one packet per frame, now.
                require(len(packets) == 1, "OUTPUT_FENCE_UNPROVEN")
                payload = avcc(bytes(packets[0]))
                require(payload, "OUTPUT_FENCE_UNPROVEN")
                ts = (frame.pts + 500) // 1000
                _hold(pauses)
                edge.check(item.lineage)  # revocable edge right before the pipe write
                if not configured:
                    publisher.video(ts, True, 0, config)
                    configured = True
                publisher.video(ts, packets[0].is_keyframe, 1, payload)
            _send(sock, item, edge, item.lineage)  # acknowledged: on the socket
    except BaseException:  # noqa: BLE001 - every failure ends the owned child
        # Native/network errors may carry the publish URL; never log raw.
        os._exit(71)
    finally:
        done.set()
        sock.close()


class RTMPMedia(CPUMedia):
    """Required sink "rtmp": persistent Guardian-owned RTMP publisher.

    ``publish_url`` (rtmp://host:port/app/stream, with any publishing
    credential) is deployment configuration handed to the owned child in
    memory; never argv/logs. ``evidence_builder`` must be the independent
    Observer adapter.
    """

    child_target = staticmethod(_rtmp_child)
    ready_kind = "RTMP_PUBLISH_READY"

    def __init__(self, gate, state_dir, required_sinks, *, publish_url, fps=25, **kwargs):
        super().__init__(gate, state_dir, required_sinks, **kwargs)
        require(publish_url.startswith("rtmp://"), "INVALID_ARGUMENT")
        require(self.width % 2 == 0 and self.height % 2 == 0, "INVALID_ARGUMENT")
        self._publish_url, self.fps = publish_url, fps

    def child_args(self):
        return (self._publish_url, self.fps)

    def __repr__(self):
        return f"RTMPMedia(<publish url redacted>, sinks={sorted(self.required_sinks)})"
