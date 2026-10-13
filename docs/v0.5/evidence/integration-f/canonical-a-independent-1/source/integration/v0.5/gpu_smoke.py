#!/usr/bin/env python3
"""Short real Worker inference from synthetic PCM; no business/sink acceptance."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

import av
import numpy as np

from gpu_worker.client import WorkerLink
from gpu_worker.config import Config
from gpu_worker.probe import probe


async def run(config, output):
    cfg = Config.load(config)
    assert cfg.mode == "gpu", "simulation cannot pass this gate"
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    endpoint = dict(port=cfg.port, tokenFile=cfg.token_file, avatarRef=cfg.avatar_ref, assetSHA256=cfg.asset_sha256)
    link = WorkerLink(endpoint, "f-compatibility-smoke-20261012")
    result = {"scope": "real GPU TCP1.1 compatibility inference / synthetic tone PCM / direct decoded collector; no SQL, Timeline, narration, Chrome or RTMP", "generations": [], "status": "FAIL"}
    try:
        await link.connect()
        assert not link.ready.get("simulation")
        result["ready"] = link.ready
        result["before"] = await asyncio.to_thread(probe, cfg, "/v1/status")
        gid = time.time_ns() // 1000
        for ordinal, samples in enumerate((30720, 6400)):
            current = gid + ordinal
            pcm = (np.sin(np.arange(samples) * (2*np.pi*440/16000))*3000).astype("<i2").tobytes()
            (output / f"source-{ordinal}.pcm").write_bytes(pcm)
            await link.begin(current, 0)
            started = time.monotonic()

            async def produce():
                for seq, index in enumerate(range(0, len(pcm), 640)):
                    await link.send_audio(current, seq, index//2, pcm[index:index+640], index+640 >= len(pcm))

            sender = asyncio.create_task(produce())
            frames = samples//640
            first_ms = None
            rgb_hash = hashlib.sha256()
            packet_rows = []
            try:
                for sequence in range(frames):
                    packet = await asyncio.wait_for(link.receive(current), 8)
                    now = time.monotonic()
                    assert packet["source"] == "GPU_INFERENCE"
                    assert packet["generation_id"] == current and packet["frame_sequence"] == sequence
                    assert packet["pts_us"] == sequence*40000
                    if first_ms is None:
                        first_ms = (now-started)*1000
                    rgb_hash.update(packet["rgb"])
                    packet_rows.append({"sequence": sequence, "ptsUs": packet["pts_us"], "arrivalMs": round((now-started)*1000,3), "rgbSHA256": hashlib.sha256(packet["rgb"]).hexdigest()})
                    if sequence in (0, frames-1):
                        frame = av.VideoFrame.from_ndarray(np.frombuffer(packet["rgb"], np.uint8).reshape(512,512,3), format="rgb24")
                        frame.to_image().save(output / f"generation-{ordinal}-frame-{sequence}.png")
                    # This is a direct decoded collector consuming legacy media,
                    # not Timeline all-required-sink proof or viewer audibility.
                    await link.consumed(packet)
                await sender
                await asyncio.wait_for(link.complete(current), 8)
                await link.cancel(current)
            finally:
                if not sender.done():
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
            result["generations"].append({"workerGenerationId": current, "sourceSamples": samples, "sourcePCM_SHA256": hashlib.sha256(pcm).hexdigest(), "frames": frames, "firstPCMToDecodedFrameMs": round(first_ms,3), "elapsedSeconds": round(time.monotonic()-started,3), "decodedRGB_SHA256": rgb_hash.hexdigest(), "packets": packet_rows})
        result["after"] = await asyncio.to_thread(probe, cfg, "/v1/status")
        assert result["after"]["workerEpoch"] == result["before"]["workerEpoch"]
        assert result["after"]["queueDepth"]["audioSamples"] <= 32000
        assert result["after"]["queueDepth"]["videoFrames"] <= 24
        result["status"] = "PASS_DIRECT_GPU_COMPATIBILITY"
    except Exception as exc:
        result["errorType"] = type(exc).__name__
        raise
    finally:
        await link.close()
        (output / "result.json").write_text(json.dumps(result, indent=2)+"\n")
        print(json.dumps({"status": result["status"], "generations": len(result["generations"])}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config, args.output))


if __name__ == "__main__":
    main()
