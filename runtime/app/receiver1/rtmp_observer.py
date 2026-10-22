"""Independent RTMP Observer: a passive tap on the Guardian's RTMP pipe (3b-2).

Runs as its OWN process with its own OBSERVER deployment credential; it shares
no memory, key or socket with the Guardian or the Runtime. The Guardian's
owned publisher connects to this tap instead of the ingest; every byte is
parsed (RTMP chunk stream, client->server direction only) and forwarded
unchanged to the configured upstream ingest (MediaMTX / platform).

Why a tap and not an RTMP reader: libav's RTMP/FLV reader withholds the final
tag until a later one arrives (measured: the last 640-sample packet of a unit
is only surfaced at disconnect), and a reader behind MediaMTX misses the
start (track analysis delay). The tap sees exactly what the publisher wrote
to the pipe, when it wrote it -- the RTMP_PIPE_WRITE fact, nothing more. It
never claims audience delivery.

What the ledger proves for a unit [audio_start, audio_end):
* audio: the PCM bytes at stream offsets [start-origin, end-origin) hash to the
  Guardian tail's audio hash, every audio message is contiguous (timestamp
  matches the running sample count) and the format is 16-bit mono PCM;
* video: one AVC NALU message per tail video PTS, at that PTS (ms resolution),
  in order. Pixels are lossy H.264, so video is proven by frame count/PTS.
Any parse anomaly faults the tap: forwarding stops and no evidence is issued.
"""

import asyncio
import hashlib
import json
import os
import socket
import stat
import struct
import sys

HANDSHAKE = 1 + 1536 + 1536  # C0 + C1 + C2 from the publisher
MAX_MESSAGE = 1 << 20
AUDIO, VIDEO, SET_CHUNK_SIZE, AGGREGATE = 8, 9, 1, 22
FLV_PCM_LE = 3


class TapFault(RuntimeError):
    def __init__(self, code="EVIDENCE_CONFLICT"):
        super().__init__(code)
        self.code = code


class Ledger:
    """Stream-relative record of what the publisher wrote to the pipe."""

    def __init__(self, sample_rate):
        self.rate = sample_rate
        self.pcm = bytearray()
        self.video = []  # (timestamp_ms, sha256 of the tag payload)
        self.fault = None
        self.changed = asyncio.Event()

    def audio(self, timestamp, payload):
        if not payload or payload[0] >> 4 != FLV_PCM_LE or payload[0] & 0x03 != 0x02:
            raise TapFault()  # not 16-bit mono little-endian PCM
        data = payload[1:]
        if len(data) % 2:
            raise TapFault()
        samples = len(self.pcm) // 2
        # flvenc rounds to the nearest millisecond; anything else is a gap/overlap.
        if timestamp != (samples * 1000 + self.rate // 2) // self.rate:
            raise TapFault()
        self.pcm += data

    def video_tag(self, timestamp, payload):
        if len(payload) < 5 or payload[0] & 0x0F != 7:
            raise TapFault()  # AVC only
        if payload[1] == 1:  # NALU: one frame per message (zerolatency, no B)
            if self.video and timestamp <= self.video[-1][0]:
                raise TapFault()
            self.video.append((timestamp, hashlib.sha256(payload).hexdigest()))
        elif payload[1] not in (0, 2):  # sequence header / end of sequence
            raise TapFault()

    def notify(self):
        self.changed.set()


class ChunkParser:
    """Incremental RTMP client->server chunk stream parser (spec 5.3)."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.buffer = bytearray()
        self.skip = HANDSHAKE
        self.chunk_size = 128
        self.streams = {}  # csid -> dict(ts, delta, length, type, ext, body)
        self.commands = []

    def feed(self, data):
        self.buffer += data
        if self.skip:
            taken = min(self.skip, len(self.buffer))
            del self.buffer[:taken]
            self.skip -= taken
        while self._chunk():
            pass

    def _chunk(self):
        b = self.buffer
        if not b:
            return False
        fmt, csid, at = b[0] >> 6, b[0] & 0x3F, 1
        if csid == 0:
            if len(b) < 2:
                return False
            csid, at = b[1] + 64, 2
        elif csid == 1:
            if len(b) < 3:
                return False
            csid, at = b[1] + b[2] * 256 + 64, 3
        state = self.streams.get(csid)
        if fmt != 0 and state is None:
            raise TapFault()
        size = (11, 7, 3, 0)[fmt]
        if len(b) < at + size:
            return False
        header = b[at : at + size]
        at += size
        state = dict(state or {})
        if fmt < 3:
            field = int.from_bytes(header[0:3], "big")
            state["ext"] = field == 0xFFFFFF
        if fmt <= 1:
            state["length"] = int.from_bytes(header[3:6], "big")
            state["type"] = header[6]
            if not 0 < state["length"] <= MAX_MESSAGE:
                raise TapFault()
        if state.get("ext"):
            if len(b) < at + 4:
                return False
            field = int.from_bytes(b[at : at + 4], "big")
            at += 4
        starting = not state.get("body")
        if starting:
            if fmt == 0:
                state["ts"], state["delta"] = field, 0
            elif fmt in (1, 2):
                state["delta"] = field
                state["ts"] = state.get("ts", 0) + field
            else:  # fmt 3 starting a new message repeats the previous delta
                state["ts"] = state.get("ts", 0) + state.get("delta", 0)
            state["body"] = bytearray()
        elif fmt != 3:
            raise TapFault()  # a new header interrupting an unfinished message
        need = min(self.chunk_size, state["length"] - len(state["body"]))
        if len(b) < at + need:
            return False
        state["body"] += b[at : at + need]
        del b[: at + need]
        if len(state["body"]) == state["length"]:
            body, state["body"] = bytes(state["body"]), None
            self.streams[csid] = state
            self._message(state["type"], state["ts"], body)
        else:
            self.streams[csid] = state
        return True

    def _message(self, kind, ts, body):
        if kind == SET_CHUNK_SIZE:
            size = int.from_bytes(body[:4], "big") & 0x7FFFFFFF
            if not 1 <= size <= MAX_MESSAGE:
                raise TapFault()
            self.chunk_size = size
        elif kind == AUDIO:
            self.ledger.audio(ts, body)
        elif kind == VIDEO:
            self.ledger.video_tag(ts, body)
        elif kind == AGGREGATE:
            raise TapFault()  # never produced by the owned publisher
        elif kind == 20 and body[:1] == b"\x02" and len(body) >= 3:
            n = int.from_bytes(body[1:3], "big")
            self.commands.append(body[3 : 3 + n].decode("ascii", "replace"))


def peer_pid(sock):
    if sys.platform.startswith("linux"):
        return struct.unpack(
            "3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )[0]
    if sys.platform == "darwin":
        return struct.unpack("i", sock.getsockopt(0, 2, 4))[0]  # LOCAL_PEERPID
    raise TapFault("OUTPUT_FENCE_UNPROVEN")


class RTMPObserver:
    """One Session: one publisher connection, one upstream, one ledger.

    ``audio_origin`` is the trusted Session sample origin (deployment/session
    configuration, never a Guardian request field); stream offset 0 is that
    sample. ``guardian`` is the pinned Guardian ProcessIdentity allowed to ask
    for evidence; ``recorder`` (optional) is an ObserverClient that records
    the evidence with the Backend before it is handed back.
    """

    def __init__(self, *, sink_id, upstream, audio_origin, sample_rate, guardian,
                 recorder=None, settle=0.5):
        self.sink_id, self.upstream = sink_id, upstream
        self.origin, self.rate = audio_origin, sample_rate
        self.guardian, self.recorder, self.settle = guardian, recorder, settle
        self.ledger = Ledger(sample_rate)
        self.parser = ChunkParser(self.ledger)
        self.connected = False
        self.forwarded = 0
        self.servers = []
        self.issued = {}

    # -- media pipe -------------------------------------------------------
    async def listen(self, host="127.0.0.1", port=0):
        server = await asyncio.start_server(self._publisher, host, port)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def _publisher(self, reader, writer):
        if self.connected or self.ledger.fault is not None:
            writer.close()  # exactly one publisher per Session
            return
        self.connected = True
        try:
            host, port = self.upstream
            up_reader, up_writer = await asyncio.open_connection(host, port)
        except OSError:
            self.ledger.fault = "DEPENDENCY_UNAVAILABLE"
            self.ledger.notify()
            writer.close()
            return

        async def downstream():
            try:
                while data := await up_reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            except OSError:
                pass

        back = asyncio.create_task(downstream())
        try:
            while data := await reader.read(65536):
                try:
                    self.parser.feed(data)
                except TapFault as fault:
                    self.ledger.fault = fault.code
                    break
                finally:
                    self.ledger.notify()
                up_writer.write(data)
                await up_writer.drain()
                self.forwarded += len(data)
        except OSError:
            pass
        finally:
            if self.ledger.fault is None:
                self.ledger.fault = "PUBLISHER_CLOSED"  # no later unit can drain
            self.ledger.notify()
            back.cancel()
            for w in (up_writer, writer):
                w.close()

    # -- evidence ---------------------------------------------------------
    async def prove(self, request):
        """Verify one finished unit against the pipe; return the evidence."""
        start, end = request["audioStart"], request["audioEnd"]
        pts = request["videoPts"]
        if not (
            type(start) is int and type(end) is int and self.origin <= start < end
            and isinstance(pts, list) and pts and all(type(p) is int for p in pts)
            and pts == sorted(set(pts))
        ):
            raise TapFault("INVALID_ARGUMENT")
        lo, hi = (start - self.origin) * 2, (end - self.origin) * 2
        origin_us = self.origin * 1000000 // self.rate
        wanted = [(p - origin_us + 500) // 1000 for p in pts]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settle
        ledger = self.ledger
        while True:
            if len(ledger.pcm) >= hi and ledger.video and ledger.video[-1][0] >= wanted[-1]:
                break
            if ledger.fault is not None and ledger.fault != "PUBLISHER_CLOSED":
                raise TapFault(ledger.fault)
            remaining = deadline - loop.time()
            if remaining <= 0 or ledger.fault == "PUBLISHER_CLOSED":
                raise TapFault("OUTPUT_FENCE_UNPROVEN")  # tail never reached the pipe
            ledger.changed.clear()
            try:
                await asyncio.wait_for(ledger.changed.wait(), remaining)
            except TimeoutError:
                pass
        if ledger.fault is not None and ledger.fault != "PUBLISHER_CLOSED":
            raise TapFault(ledger.fault)
        audio = bytes(ledger.pcm[lo:hi])
        if hashlib.sha256(audio).hexdigest() != request["audioHash"]:
            raise TapFault()
        frames = [i for i, (ts, _) in enumerate(ledger.video) if wanted[0] <= ts <= wanted[-1]]
        if [ledger.video[i][0] for i in frames] != wanted:
            raise TapFault()  # missing, extra or re-timed frame
        wire = hashlib.sha256()
        wire.update(audio)
        for i in frames:
            wire.update(ledger.video[i][1].encode())
        proof = dict(
            sinkId=self.sink_id,
            kind="RTMP_PIPE_WRITE",
            generationId=request["generationId"],
            firstAudioSample=start,
            finalAudioSampleExclusive=end,
            audioConsumedThroughExclusive=end,
            finalVideoFrame=request["finalVideoFrame"],
            videoConsumedThroughFrame=request["finalVideoFrame"],
            terminal=True,
        )
        evidence = dict(
            evidenceType="ALL_REQUIRED_DRAIN",
            evidenceRef=request["evidenceRef"],
            evidenceHash=wire.hexdigest(),
            requiredSinks=[self.sink_id],
            sinkProofs=[proof],
            predecessorCheckpointIds=list(request.get("predecessorCheckpointIds", [])),
            audienceVisibility="UNVERIFIED",
        )
        if self.recorder is not None:
            await self.recorder.record(request["commandId"], request["artifactId"], evidence)
        self.issued[request["evidenceRef"]] = evidence
        return evidence

    async def serve_evidence(self, path):
        """Private evidence channel: 0700 directory, kernel peer pinned."""
        parent = os.path.dirname(path)
        st = os.lstat(parent)
        if not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.geteuid():
            raise TapFault("FORBIDDEN")
        server = await asyncio.start_unix_server(self._evidence, path)
        os.chmod(path, 0o600)
        self.servers.append(server)

    async def _evidence(self, reader, writer):
        from .transport import identity

        try:
            pid = peer_pid(writer.get_extra_info("socket"))
            if pid != self.guardian.pid or identity(pid) != self.guardian:
                raise TapFault("UNAUTHENTICATED")
            line = await asyncio.wait_for(reader.readline(), 1.0)
            if not line.endswith(b"\n") or len(line) > 65536:
                raise TapFault("INVALID_ARGUMENT")
            out = dict(ok=True, evidence=await self.prove(json.loads(line)))
        except TapFault as fault:
            out = dict(ok=False, code=fault.code)
        except Exception:  # noqa: BLE001 - never echo raw errors
            out = dict(ok=False, code="DEPENDENCY_UNAVAILABLE")
        try:
            writer.write(json.dumps(out, separators=(",", ":")).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()

    def close(self):
        for server in self.servers:
            server.close()


class TapEvidence:
    """Guardian-side evidence_builder: asks the pinned RTMP Observer.

    The Guardian supplies only the tail it is about to claim; the Observer
    alone decides whether the pipe carried it and builds the evidence.
    """

    def __init__(self, path, observer, *, timeout=1.5, refs=None):
        self.path, self.observer, self.timeout = str(path), observer, timeout
        self.refs = refs or (lambda lineage, tail: {})

    async def __call__(self, lineage, tail, sinks):
        from .transport import identity

        registration = json.loads(lineage.identity)["registration"]
        request = dict(
            audioStart=tail.audio_start,
            audioEnd=tail.audio_end,
            audioHash=tail.audio_hash,
            videoPts=list(tail.video_pts),
            finalVideoFrame=tail.final_video_frame,
            generationId=registration["generationId"],
            evidenceRef=f"rtmp_{lineage.execution_id}_{tail.last_sequence}",
            **self.refs(lineage, tail),
        )

        async def ask():
            reader, writer = await asyncio.open_unix_connection(self.path)
            try:
                pid = peer_pid(writer.get_extra_info("socket"))
                if pid != self.observer.pid or identity(pid) != self.observer:
                    raise TapFault("UNAUTHENTICATED")
                writer.write(json.dumps(request).encode() + b"\n")
                await writer.drain()
                return json.loads(await reader.readline())
            finally:
                writer.close()

        out = await asyncio.wait_for(ask(), self.timeout)
        if not out.get("ok"):
            raise TapFault(out.get("code", "OUTPUT_FENCE_UNPROVEN"))
        evidence = out["evidence"]
        if sorted(sinks) != evidence["requiredSinks"]:
            raise TapFault()
        return evidence


async def _main():
    """Process entry: one JSON config line on stdin, "READY <port>" on stdout.

    The config carries no secret: sinkId, upstream [host, port], audioOrigin,
    sampleRate, guardianPid, evidencePath. Backend recording (OBSERVER
    credential via load_inherited) is wired by the Host Launcher (stage 4).
    """
    from .transport import identity

    config = json.loads(sys.stdin.readline())
    observer = RTMPObserver(
        sink_id=config["sinkId"],
        upstream=tuple(config["upstream"]),
        audio_origin=config["audioOrigin"],
        sample_rate=config["sampleRate"],
        guardian=identity(config["guardianPid"]),
    )
    port = await observer.listen()
    await observer.serve_evidence(config["evidencePath"])
    print("READY", port, flush=True)
    await asyncio.get_running_loop().run_in_executor(None, sys.stdin.read)  # until EOF
    observer.close()


if __name__ == "__main__":
    asyncio.run(_main())
