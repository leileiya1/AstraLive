"""Real CPU encoder/decoder and revocable private process transport.

This is a lossless CPU isolation adapter, NOT an RTMP/AAC/WebRTC completion
adapter. Persistent libav contexts and Session sample/PTS origins survive unit
Finish. It cannot issue registered production evidence on its own.
"""

import asyncio
import hashlib
import json
import multiprocessing
import os
import pickle
import secrets
import select
import socket
import stat
import struct
import threading
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import psutil

from output_guardian.model import Closed

from .clocks import suspend_clock as clock
from .gate import require
from .receiver import ObservedDrain

MAX_RECORD = 9 * 1024 * 1024 + 65536


def _send(sock, value, edge, lineage):
    raw = pickle.dumps(value, protocol=5)
    require(len(raw) <= MAX_RECORD, "OVERLOADED")
    pending = memoryview(struct.pack("!I", len(raw)) + raw)
    end = time.monotonic() + 0.5
    while pending:
        require(time.monotonic() < end, "OVERLOADED")
        # Readiness/backpressure waits are outside the shared short gate.
        select.select([], [sock], [], 0.005)
        with edge.lock:
            edge.check_locked(lineage)
            try:
                count = sock.send(pending[:16384])  # socket is nonblocking
            except BlockingIOError:
                continue
            require(count > 0)
            pending = pending[count:]


def _receive(sock, edge=None, stop=None):
    def read(length):
        chunks = bytearray()
        while len(chunks) < length:
            if stop is not None and stop.is_set():
                raise Closed()
            if edge is not None:
                require(os.getppid() == edge.parent_pid)
            ready, _, _ = select.select([sock], [], [], 0.005)
            if not ready:
                continue
            try:
                chunk = sock.recv(length - len(chunks))
            except BlockingIOError:
                continue
            require(bool(chunk))
            chunks.extend(chunk)
        return chunks

    length = struct.unpack("!I", read(4))[0]
    require(0 < length <= MAX_RECORD, "OVERLOADED")
    # Only dedicated Guardian-owned child/parent has this socket. Untrusted
    # Runtime JSON NEVER reaches pickle or this private process protocol.
    return pickle.loads(read(length))


def _child(
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
):
    sock.setblocking(False)
    done = threading.Event()

    def watchdog():
        while not done.wait(0.005):
            if os.getppid() != edge.parent_pid:
                os._exit(70)
            # Expiry closes child even if codec/native work is stalled.
            if any(edge.tag) and (
                time.monotonic() >= edge.deadlines[0] or clock() >= edge.deadlines[1]
            ):
                os._exit(70)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        if startup_barrier is not None:
            startup_barrier[0].set()
            startup_barrier[1].wait()  # initialization wait, never inside gate
        import av
        import numpy as np

        video = av.CodecContext.create("ffv1", "w")
        video.width, video.height, video.pix_fmt = width, height, "bgr0"
        video.time_base, video.thread_count = Fraction(1, 1000000), 1
        video.open()
        video_decoder = av.CodecContext.create("ffv1", "r")
        video_decoder.width, video_decoder.height, video_decoder.pix_fmt = (
            width,
            height,
            "bgr0",
        )
        video_decoder.extradata = video.extradata
        video_decoder.open()
        audio = av.CodecContext.create("pcm_s16le", "w")
        audio.sample_rate, audio.layout, audio.format = sample_rate, "mono", "s16"
        audio.time_base = Fraction(1, sample_rate)
        audio.open()
        audio_decoder = av.CodecContext.create("pcm_s16le", "r")
        audio_decoder.sample_rate, audio_decoder.layout = sample_rate, "mono"
        audio_decoder.open()
        if installed_binding is not None:
            from astralive_contracts import durable_live_v2 as dto

            installed = dto.decode("ReceiverBootstrapBinding", installed_binding)
            binding_hash = hashlib.sha256(installed_binding).hexdigest()
            generation = installed.generationId
        else:
            binding_hash, generation = None, None
        # A private, challenge-bound native child readiness acknowledgement.
        # No frame, Permit, media clock or Credit is consumed during startup.
        with edge.lock:
            require(not any(edge.tag), "OUTPUT_FENCE_UNPROVEN")
        ready.send(
            dict(
                kind="CPU_CODEC_READY",
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
            # Immutable owner travels through queued transport, child, encoder,
            # decoder and decoded output. No read of a 'current execution'.
            edge.check(item.lineage)
            if pauses:
                pauses["at_before_encode"].set()
                pauses["before_encode"].wait()
            edge.check(item.lineage)
            if item.kind == "audio":
                frame = av.AudioFrame.from_ndarray(
                    np.frombuffer(item.payload, dtype="<i2").reshape(1, -1),
                    format="s16",
                    layout="mono",
                )
                frame.sample_rate, frame.pts, frame.time_base = (
                    sample_rate,
                    item.audio_start,
                    Fraction(1, sample_rate),
                )
                packets, decoder = audio.encode(frame), audio_decoder
            else:
                frame = av.VideoFrame.from_ndarray(
                    np.frombuffer(item.payload, dtype=np.uint8).reshape(
                        height, width, 3
                    ),
                    format="rgb24",
                )
                frame.pts, frame.time_base = item.pts_us, Fraction(1, 1000000)
                packets, decoder = video.encode(frame), video_decoder
            decoded = []
            for packet in packets:
                edge.check(item.lineage)  # encoder -> decoder handoff
                if pauses:
                    pauses["at_before_decode"].set()
                    pauses["before_decode"].wait()
                edge.check(item.lineage)
                decoded.extend(decoder.decode(packet))
            # This selected CPU codec profile must produce the entire frame
            # without delayed data; no flush/EOF or PTS reset between units.
            require(len(decoded) == 1, "OUTPUT_FENCE_UNPROVEN")
            result = decoded[0]
            if item.kind == "audio":
                raw = result.to_ndarray().astype("<i2").tobytes()
                require(
                    result.pts == item.audio_start
                    and result.samples == len(item.payload) // 2,
                    "EVIDENCE_CONFLICT",
                )
            else:
                raw = result.to_ndarray(format="rgb24").tobytes()
                require(result.pts == item.pts_us, "EVIDENCE_CONFLICT")
            require(raw == item.payload, "EVIDENCE_CONFLICT")
            if pauses:
                pauses["at_before_output"].set()
                pauses["before_output"].wait()
            _send(sock, replace(item, payload=raw), edge, item.lineage)
    except BaseException:
        # Native errors may carry credentials in other adapters; never log raw.
        os._exit(71)
    finally:
        done.set()
        sock.close()


class CPUMedia:
    """Bounded decoded fanout to explicitly configured required CPU sinks.

    Each sink has its own final revocable acceptance edge and verifies actual
    decoded bytes/sample ranges. evidence_builder is a trusted registered
    Observer adapter (test mocks are labelled as such); absent => UNKNOWN.
    """

    def __init__(
        self,
        gate,
        state_dir,
        required_sinks,
        *,
        sample_rate=16000,
        width=64,
        height=64,
        evidence_builder=None,
        pauses=None,
        startup_barrier=None,
        startup_timeout=2.0,
        installed_binding=None,
    ):
        self.gate, self.edge = gate, gate.edge
        self.state_dir, self.required_sinks = Path(state_dir), frozenset(required_sinks)
        self.rate, self.width, self.height = sample_rate, width, height
        self.evidence_builder, self.pauses = evidence_builder, pauses
        require(0 < startup_timeout <= 5, "INVALID_ARGUMENT")
        self.startup_barrier, self.startup_timeout = startup_barrier, startup_timeout
        self.ready = False
        self.readiness = None
        self.installed_binding = None
        if installed_binding is not None:
            from astralive_contracts import durable_live_v2 as dto

            self.installed_binding = dto.canonical_json(installed_binding)
            dto.decode("ReceiverBootstrapBinding", self.installed_binding)
        self.process, self.socket, self.tasks = None, None, []
        self.stopping = threading.Event()
        self.sink_queues = {name: asyncio.Queue(8) for name in self.required_sinks}
        self.sink_pauses = {}
        self.sinks = {name: {} for name in self.required_sinks}
        self.fault = None
        self.send_lock = asyncio.Lock()

    @property
    def registry(self):
        return self.state_dir / "cpu-child.json"

    def recover(self):
        """Trusted PID creation identity; never kill a PID-only Runtime claim."""
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self.state_dir.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.geteuid()
            and not st.st_mode & 0o077
        )
        if not self.registry.exists():
            return
        require(not self.registry.is_symlink())
        record = json.loads(self.registry.read_text())
        require(set(record) == {"pid", "created", "uid"})
        try:
            process = psutil.Process(record["pid"])
            require(
                process.create_time() == record["created"]
                and process.uids().real == record["uid"] == os.geteuid()
            )
            process.kill()
            process.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        self.registry.unlink()

    async def start(self):
        with self.gate.lock:
            require(
                self.gate.state in {"FENCED", "STAGED_CLOSED"}
                and self.gate.active is None
            )
            captured = self.gate.capture_locked()
            origins = (
                self.gate.audio_end,
                self.gate.video_end,
                self.gate.video_frames,
                self.gate.sequence,
            )
        await asyncio.to_thread(self.recover)
        ctx = multiprocessing.get_context("spawn")
        parent, child = socket.socketpair()
        parent.setblocking(False)
        self.socket = parent
        reader, writer = ctx.Pipe(duplex=False)
        nonce = secrets.token_hex(32)
        self.process = ctx.Process(
            target=_child,
            args=(
                child,
                self.edge,
                self.rate,
                self.width,
                self.height,
                self.pauses,
                writer,
                nonce,
                self.startup_barrier,
                self.installed_binding,
                origins,
            ),
        )
        self.process.start()
        child.close()
        writer.close()
        # No media/config secret is handed to the child before the parent
        # independently records ownership. Gate is closed at this point.
        require(
            self.gate.state in {"FENCED", "STAGED_CLOSED"} and self.gate.active is None
        )
        record = dict(
            pid=self.process.pid,
            created=psutil.Process(self.process.pid).create_time(),
            uid=os.geteuid(),
        )

        def persist():
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            with self.registry.open("x") as stream:
                os.chmod(self.registry, 0o600)
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            fd = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

        try:
            await asyncio.to_thread(persist)

            def receive_ready():
                require(reader.poll(self.startup_timeout), "OUTPUT_FENCE_UNPROVEN")
                return reader.recv()

            observation = await asyncio.to_thread(receive_ready)
            require(
                observation
                == dict(
                    kind="CPU_CODEC_READY",
                    nonce=nonce,
                    pid=self.process.pid,
                    parent=os.getpid(),
                    rate=self.rate,
                    width=self.width,
                    height=self.height,
                    bindingHash=hashlib.sha256(self.installed_binding).hexdigest()
                    if self.installed_binding
                    else None,
                    generation=json.loads(self.installed_binding)["generationId"]
                    if self.installed_binding
                    else None,
                    origins=origins,
                )
            )
            require(self.process.is_alive(), "OUTPUT_FENCE_UNPROVEN")
            with self.gate.lock:
                self.gate.compare_locked(captured)
                require(not any(self.edge.tag), "OUTPUT_FENCE_UNPROVEN")
                self.readiness, self.ready = observation, True
        except BaseException:
            await self.close()
            raise Closed() from None
        finally:
            reader.close()
        self.tasks = [
            asyncio.create_task(self._pump()),
            asyncio.create_task(self._read()),
        ]
        self.tasks += [
            asyncio.create_task(self._sink(name)) for name in self.required_sinks
        ]

    def check_ready(self):
        # Called outside the admission gate. A real initialized child, not its
        # mere spawn/persistent PID, is a precondition before a Consume RPC.
        require(
            self.ready and self.process is not None and self.process.is_alive(),
            "OUTPUT_FENCE_UNPROVEN",
        )

    async def _pump(self):
        try:
            while True:
                with self.gate.lock:
                    item = self.gate.media.popleft() if self.gate.media else None
                if item is None:
                    await asyncio.sleep(0.001)
                    continue
                # Captured item/process/socket before waiting; never retarget a
                # queued operation into a replacement Session publisher.
                sock = self.socket
                async with self.send_lock:
                    await asyncio.to_thread(_send, sock, item, self.edge, item.lineage)
        except asyncio.CancelledError:
            raise
        except BaseException:
            self._fail()

    async def _read(self):
        try:
            while True:
                item = await asyncio.to_thread(
                    _receive, self.socket, None, self.stopping
                )
                self.edge.check(item.lineage)  # decoder receive edge
                for queue in self.sink_queues.values():
                    await queue.put(item)  # bounded wait OUTSIDE gate
                    self.edge.check(item.lineage)
        except asyncio.CancelledError:
            raise
        except BaseException:
            if not self.stopping.is_set():
                self._fail()

    def _fail(self):
        self.fault = "OUTPUT_FENCE_UNPROVEN"
        try:
            with self.gate.lock:
                self.gate.unknown_locked()
        except Closed:
            pass  # poisoned mutex already denies all admission

    async def _sink(self, name):
        try:
            while True:
                item = await self.sink_queues[name].get()
                pause = self.sink_pauses.get(name)
                if pause is not None:
                    await pause.wait()
                # Hash/observe actual decoded bytes outside gate; commit only
                # the bounded metadata at this sink's irreversible edge.
                existing = self.sinks[name].get(item.lineage)
                if existing is None:
                    require(len(self.sinks[name]) < 32, "OVERLOADED")
                    existing = dict(
                        first=item.sequence,
                        last=item.sequence - 1,
                        start=item.audio_start,
                        end=item.audio_start,
                        audio=hashlib.sha256(),
                        video=hashlib.sha256(),
                        pts=[],
                        first_frame=item.video_frame,
                        final_frame=item.video_frame - 1,
                    )
                updated = dict(
                    existing,
                    audio=existing["audio"].copy(),
                    video=existing["video"].copy(),
                    pts=list(existing["pts"]),
                )
                require(item.sequence == existing["last"] + 1, "EVIDENCE_CONFLICT")
                updated["last"] = item.sequence
                if item.kind == "audio":
                    require(item.audio_start == existing["end"], "EVIDENCE_CONFLICT")
                    updated["end"] += len(item.payload) // 2
                    updated["audio"].update(item.payload)
                else:
                    require(
                        item.video_frame == existing["final_frame"] + 1,
                        "EVIDENCE_CONFLICT",
                    )
                    updated["final_frame"] = item.video_frame
                    updated["video"].update(item.payload)
                    updated["pts"].append(item.pts_us)
                with self.gate.lock:
                    self.gate.execution_locked(item.lineage)
                    self.sinks[name][item.lineage] = updated
                self.sink_queues[name].task_done()
        except asyncio.CancelledError:
            raise
        except BaseException:
            self._fail()

    async def observe(self, lineage, tail):
        require(
            tail.audio_end > tail.audio_start and bool(tail.video_pts),
            "EVIDENCE_CONFLICT",
        )
        deadline = time.monotonic() + 0.5
        while True:
            self.edge.check(lineage)
            require(self.fault is None)
            complete = True
            for name in self.required_sinks:
                row = self.sinks[name].get(lineage)
                if row is None or row["last"] != tail.last_sequence:
                    complete = False
                    continue
                require(
                    (
                        row["first"],
                        row["start"],
                        row["end"],
                        tuple(row["pts"]),
                        row["audio"].hexdigest(),
                        row["video"].hexdigest(),
                        row["first_frame"],
                        row["final_frame"],
                    )
                    == (
                        tail.first_sequence,
                        tail.audio_start,
                        tail.audio_end,
                        tail.video_pts,
                        tail.audio_hash,
                        tail.video_hash,
                        tail.first_video_frame,
                        tail.final_video_frame,
                    ),
                    "EVIDENCE_CONFLICT",
                )
            if complete:
                break
            require(time.monotonic() < deadline)
            await asyncio.sleep(0.002)
        require(self.evidence_builder is not None, "OUTPUT_FENCE_UNPROVEN")
        evidence = await self.evidence_builder(lineage, tail, self.required_sinks)
        self.edge.check(lineage)
        return ObservedDrain(tail, self.required_sinks, evidence)

    async def close(self):
        self.ready = False
        self.stopping.set()
        try:
            with self.gate.lock:
                self.edge.close_locked()
        except Closed:
            pass  # independent kill/join still runs after a dead lock owner
        tasks, self.tasks = self.tasks, []
        for task in tasks:
            task.cancel()
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
            self.socket = None
        process, self.process = self.process, None
        proven = True
        if process is not None:
            if process.is_alive():
                process.kill()
            await asyncio.to_thread(process.join, 2)
            proven = not process.is_alive()
            if proven:
                process.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        if proven:
            self.registry.unlink(missing_ok=True)
        return proven
