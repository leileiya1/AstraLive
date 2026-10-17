"""Guardian-owned FFmpeg/libav publisher child. Secrets arrive on inherited FD.

The child is never launched by Runtime and never receives its DB credentials.
It checks both clocks before every encoder/mux operation. An independent thread
exits even if libav or the parent blocks. Linux parent-death signal is additional
protection; the supervisor/cgroup and ingest revocation remain independent.
"""

import argparse
import ctypes
import os
import signal
import threading
import time
from fractions import Fraction
from multiprocessing.connection import Connection

from .codec import packet_hash
from .model import clock


def run(fd):
    parent = os.getppid()
    if os.uname().sysname == "Linux":
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != parent:
            os._exit(70)
    pipe = Connection(fd)
    config = pipe.recv()
    deadline = [config["deadline"], config["monotonic_deadline"]]
    done = threading.Event()

    def check():
        if (
            os.getppid() != parent
            or clock() >= deadline[0]
            or time.monotonic() >= deadline[1]
        ):
            os._exit(70)  # No encoder flush of queued old media on revocation.

    def watchdog():
        while not done.wait(0.005):
            check()

    threading.Thread(target=watchdog, daemon=True).start()
    import av
    import numpy as np

    output = None
    try:
        check()
        output = av.open(
            config["url"],
            "w",
            format="flv",
            options={"flvflags": "no_duration_filesize", "flush_packets": "1"},
            timeout=(0.3, 0.3),
        )
        video = output.add_stream("libx264", rate=config["fps"])
        video.width, video.height, video.pix_fmt = (
            config["width"],
            config["height"],
            "yuv420p",
        )
        video.time_base = Fraction(1, 1000000)
        video.codec_context.time_base = Fraction(1, 1000000)
        video.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "bf": "0",
            "g": str(config["fps"]),
        }
        audio = output.add_stream("aac", rate=config["sample_rate"])
        audio.layout = "mono"
        audio.time_base = Fraction(1, config["sample_rate"])
        resampler = av.AudioResampler(
            format="fltp", layout="mono", rate=config["sample_rate"]
        )
        hashes = {"audio": [], "video": []}
        audio_samples, video_pts = 0, []

        def mux(kind, packets):
            for packet in packets:
                check()
                digest = packet_hash(kind, bytes(packet))
                output.mux(packet)
                if digest:
                    hashes[kind].append(digest)

        output.start_encoding()
        if audio.codec_context.frame_size != 1024:
            raise ValueError("unproven AAC sample-range mapping")
        pipe.send({"ready": True})
        while True:
            check()
            if not pipe.poll(0.005):
                continue
            message = pipe.recv()
            check()
            if message.get("identity") != config.get("identity"):
                raise ValueError("stale child identity")
            if message["op"] == "permit":
                deadline[:] = [message["deadline"], message["monotonic_deadline"]]
                check()
                pipe.send({"ok": True})
            elif message["op"] == "audio":
                pcm = message["payload"]
                frame = av.AudioFrame.from_ndarray(
                    np.frombuffer(pcm, dtype="<i2").reshape(1, -1),
                    format="s16",
                    layout="mono",
                )
                frame.sample_rate, frame.pts, frame.time_base = (
                    config["sample_rate"],
                    audio_samples,
                    Fraction(1, config["sample_rate"]),
                )
                audio_samples += frame.samples
                for converted in resampler.resample(frame):
                    mux("audio", audio.encode(converted))
                pipe.send({"ok": True})
            elif message["op"] == "video":
                frame = av.VideoFrame.from_ndarray(
                    np.frombuffer(message["payload"], dtype=np.uint8).reshape(
                        config["height"], config["width"], 3
                    ),
                    format="rgb24",
                )
                frame.pts, frame.time_base = message["pts_us"], Fraction(1, 1000000)
                mux("video", video.encode(frame))
                video_pts.append(message["pts_us"])
                pipe.send({"ok": True})
            elif message["op"] == "finish":
                for converted in resampler.resample(None):
                    mux("audio", audio.encode(converted))
                mux("audio", audio.encode(None))
                mux("video", video.encode(None))
                check()
                output.close()
                output = None
                pipe.send(
                    {
                        "manifest": hashes,
                        "audioSamples": audio_samples,
                        "videoPTSUS": video_pts,
                    }
                )
                # Keep the identity-bound child for control renewals while the
                # independent receiver finishes decoding the flushed stream. No
                # more audio/video may be submitted after this terminal flush.
                while True:
                    check()
                    if not pipe.poll(0.005):
                        continue
                    control = pipe.recv()
                    if control.get("identity") != config.get("identity"):
                        raise ValueError("stale child identity")
                    if control["op"] != "permit":
                        raise ValueError("sealed publisher")
                    deadline[:] = [control["deadline"], control["monotonic_deadline"]]
                    check()
                    pipe.send({"ok": True})
            else:
                raise ValueError("invalid child operation")
    except BaseException:
        # Never include libav exceptions: they may contain a secret URL.
        try:
            pipe.send({"error": "MEDIA_DELIVERY_FAILED"})
        except Exception:
            pass
        os._exit(71)
    finally:
        done.set()
        pipe.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", type=int, required=True)
    raise SystemExit(run(parser.parse_args().fd))
