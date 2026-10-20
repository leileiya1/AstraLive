"""Trusted RTMP decoder. Its packet ledger follows real network reception.

The ingest recorder covers stream startup; this reader covers the tail. Neither
Runtime enqueue nor local encoder submission is a decoded range receipt.
"""

import argparse
import ctypes
import os
import signal
import threading
import time
from multiprocessing.connection import Connection

from .codec import packet_hash


def run(fd):
    parent = os.getppid()
    if os.uname().sysname == "Linux":
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != parent:
            os._exit(70)
    pipe = Connection(fd)
    config = pipe.recv()
    lock = threading.Lock()
    status = {
        "connected": False,
        "manifest": {"audio": [], "video": []},
        "decodedAudioSamples": 0,
        "decodedVideoFrames": 0,
    }

    def count(kind, frames):
        with lock:
            if kind == "audio":
                status["decodedAudioSamples"] += sum(f.samples for f in frames)
            else:
                status["decodedVideoFrames"] += len(frames)

    def receive():
        import av

        try:
            source = None
            # MediaMTX does not expose a path until RTMP track analysis finishes.
            # Before the first connection only, retry without claiming coverage.
            for _ in range(200):
                if os.getppid() != parent:
                    os._exit(70)
                try:
                    source = av.open(
                        config["url"],
                        "r",
                        # Zero analyzeduration means FFmpeg's automatic probe,
                        # which can wait for more source than a finite segment.
                        # Use stream headers and skip FPS estimation; the read-
                        # only observer may wait for one 1s GOP, unlike a frame
                        # handoff. This never extends a publishing Permit.
                        options={
                            "analyzeduration": "1",
                            "probesize": "32",
                            "fpsprobesize": "0",
                        },
                        timeout=(2, 0.5),
                    )
                    break
                except Exception as exc:
                    with lock:
                        status["openErrorType"] = type(exc).__name__
                        status["openErrorNumber"] = getattr(exc, "errno", None)
                    time.sleep(0.01)
            if source is None:
                return
            with source:
                for stream in source.streams:
                    if stream.type in {"audio", "video"}:
                        stream.codec_context.thread_count = 1
                with lock:
                    status["connected"] = True
                video_started = False
                try:
                    for packet in source.demux():
                        if os.getppid() != parent:
                            os._exit(70)
                        kind = packet.stream.type
                        if kind not in ("audio", "video"):
                            continue
                        if kind == "video" and packet.size and not video_started:
                            # Join only at an IDR. Skipped video must be covered
                            # by the independently decoded ingest prefix.
                            if not packet.is_keyframe:
                                continue
                            packet.stream.codec_context.flush_buffers()
                            video_started = True
                        digest = (
                            packet_hash(kind, bytes(packet)) if packet.size else None
                        )
                        try:
                            decoded = list(packet.decode())
                        except BaseException:
                            with lock:
                                status["decodeError"] = True
                            raise
                        count(kind, decoded)
                        with lock:
                            if digest:
                                status["manifest"][kind].append(digest)
                            if sum(map(len, status["manifest"].values())) > 10000:
                                raise ValueError("bounded decoder ledger exceeded")
                finally:
                    # Live network EOF/timeout may omit demux's synthetic flush
                    # packets. Obtain actual delayed frames before final proof.
                    for stream in source.streams:
                        if stream.type not in {"audio", "video"}:
                            continue
                        try:
                            delayed = stream.codec_context.decode(None)
                        except av.error.EOFError:
                            delayed = []
                        except Exception:
                            with lock:
                                status["decodeError"] = True
                            delayed = []
                        count(stream.type, delayed)
        except BaseException:
            # Missing bytes still cannot pass the exact packet/range verifier.
            with lock:
                status["transportEnded"] = True

    threading.Thread(target=receive, daemon=True).start()
    pipe.send({"ready": True})
    while os.getppid() == parent:
        if not pipe.poll(0.005):
            continue
        message = pipe.recv()
        if message["op"] != "status":
            os._exit(71)
        with lock:
            pipe.send(status)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", required=True, type=int)
    raise SystemExit(run(parser.parse_args().fd))
