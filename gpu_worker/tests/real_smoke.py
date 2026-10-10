"""Operator opt-in short real-GPU test. Prerecorded PCM, new live model inference.

Direct Worker test/preview only; does not certify business Session/WebRTC/RTMP.
"""
import argparse
import asyncio
import fractions
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import wave

import av
import numpy as np
from gpu_worker.client import WorkerLink
from gpu_worker.config import Config
from gpu_worker.probe import probe


def pcm_file(path):
    with wave.open(str(path), 'rb') as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (16000, 1, 2)
        return f.readframes(f.getnframes())


def preview(path, frames, pcm):
    # Remux with source timestamps; an exported file is not live A/V sync evidence.
    with av.open(str(path), 'w', options={'movflags': 'faststart'}) as container:
        video = container.add_stream('libx264', rate=25)
        video.width = video.height = 512
        video.pix_fmt = 'yuv420p'
        video.options = {'crf': '20', 'preset': 'fast', 'bf': '0'}
        audio = container.add_stream('aac', rate=16000)
        audio.layout = 'mono'
        audio.bit_rate = 64000
        packets = []
        for seq, rgb in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(np.frombuffer(rgb, np.uint8).reshape(512, 512, 3), format='rgb24')
            frame.pts = seq
            frame.time_base = fractions.Fraction(1, 25)
            packets += list(video.encode(frame))
        packets += list(video.encode())
        samples = np.frombuffer(pcm, '<i2').astype(np.float32)/32768
        for start in range(0, len(samples), 1024):
            frame = av.AudioFrame.from_ndarray(samples[None, start:start+1024], format='fltp', layout='mono')
            frame.sample_rate = 16000
            frame.pts = start
            frame.time_base = fractions.Fraction(1, 16000)
            packets += list(audio.encode(frame))
        packets += list(audio.encode())
        packets.sort(key=lambda p: (p.dts or 0)*p.time_base)
        for packet in packets:
            container.mux(packet)
    decoded = {'video': 0, 'audio': 0}
    with av.open(str(path)) as c:
        for frame in c.decode():
            decoded['video' if isinstance(frame, av.VideoFrame) else 'audio'] += 1
    assert decoded['video'] == len(frames)
    return decoded


async def run(cfg, source, output, inject_crash):
    assert cfg.mode == 'gpu', 'real_smoke refuses simulation'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = dict(scope='Direct real Worker / prerecorded incremental PCM / no business media chain', modelRevision=cfg.model_revision,
                  inputPCM_SHA256=hashlib.sha256(source).hexdigest(), checks={}, generations=[], statusSamples=[])
    endpoint = dict(port=cfg.port, tokenFile=cfg.token_file, avatarRef=cfg.avatar_ref, assetSHA256=cfg.asset_sha256)
    events = []
    def event(name, *args, **data):
        events.append(dict(event=name, **data))
    link = WorkerLink(endpoint, 'rtx3080-short-smoke', event)
    watcher = None
    async def monitor():
        while True:
            try:
                snap = await asyncio.to_thread(probe, cfg, '/v1/status')
                proc_status = Path(f"/proc/{snap['processPid']}/status")
                if proc_status.exists():
                    memory = {}
                    for line in proc_status.read_text().splitlines():
                        if line.startswith(('VmRSS:', 'VmHWM:')):
                            key, value, _ = line.split()
                            memory[key.rstrip(':')] = int(value)*1024
                    snap['processMemory'] = memory
                result['statusSamples'].append(snap)
                assert snap['queueDepth']['audioSamples'] <= 32000
                assert snap['queueDepth']['videoFrames'] <= 24
            except (OSError, ValueError):
                pass
            await asyncio.sleep(.25)
    async def generation(gid, pcm, *, paced=False, capture=False):
        await link.begin(gid, 0)
        started = time.monotonic()
        count = (len(pcm)//2*25+15999)//16000
        frames, arrivals = [], []
        async def producer():
            for seq, index in enumerate(range(0, len(pcm), 640)):
                if paced:
                    await asyncio.sleep(max(0, started+seq*.02-time.monotonic()))
                await link.send_audio(gid, seq, index//2, pcm[index:index+640], index+640 >= len(pcm))
        task = asyncio.create_task(producer())
        try:
            first = None
            for seq in range(count):
                packet = await asyncio.wait_for(link.receive(gid), 6)
                now = time.monotonic()
                if first is None:
                    first = now
                assert packet['source'] == 'GPU_INFERENCE'
                assert packet['generation_id'] == gid and packet['pts_us'] == seq*40000
                if paced:
                    await asyncio.sleep(max(0, first+seq/25-time.monotonic()))
                if capture:
                    frames.append(packet['rgb'])
                arrivals.append(now-started)
                await link.consumed(packet)
            await task
            await asyncio.wait_for(link.complete(gid), 6)
            await link.cancel(gid)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        elapsed = time.monotonic()-started
        record = dict(generationId=gid, frames=count, inputSeconds=len(pcm)/32000, paced= paced,
                      firstPCMToDecodedFrameMs=(first-started)*1000, elapsedSeconds=elapsed,
                      decodedNewFramesPerWallSecond=count/elapsed, lastArrivalSeconds=arrivals[-1])
        result['generations'].append(record)
        print(json.dumps(record), flush=True)
        return frames
    try:
        await link.connect()
        assert not link.ready.get('simulation') and link.ready['model_load_count'] == 1
        result['initialReady'] = link.ready
        result['checks']['readyModelLoadOnce'] = 'PASS'
        watcher = asyncio.create_task(monitor())
        # One job: source speech then real zero-PCM idle, no cached MP4/frame loop.
        full = source + bytes(4*32000)
        images = await generation(1, full, paced=True, capture=True)
        result['preview'] = dict(file='rtx3080-speech-idle.mp4', seconds=len(full)/32000,
                                 source='New GPU inference, 10s prerecorded speech + 4s zero PCM')
        result['preview']['decoded'] = await asyncio.to_thread(preview, output/'rtx3080-speech-idle.mp4', images, full)
        from PIL import Image
        for sec in (1, 3, 6, 10, 13):
            if sec*25 < len(images):
                Image.fromarray(np.frombuffer(images[sec*25], np.uint8).reshape(512,512,3)).save(output/f'frame-{sec:02}.png')
        del images
        result['checks']['speechIdlePTS'] = 'PASS'
        # Unpaced direct Worker throughput is separate from modelComputeFPS.
        await generation(2, source)
        cache = link.ready['cache_id']
        result['checks']['sameProcessAvatarCacheReuse'] = 'PASS'
        # Wait for an actual in-flight GPU inference before FORCE.
        await link.begin(3, 0)
        await link.send_audio(3, 0, 0, source[:30720], False)
        log_path = Path(cfg.state_dir)/'worker.log'
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            rows = [json.loads(s) for s in log_path.read_text().splitlines() if s.startswith('{')]
            starts = [r for r in rows if r['event']=='GPUInferenceStart' and r.get('generation_id')==3 and r.get('worker_epoch') == link.epoch]
            if starts:
                break
            await asyncio.sleep(.01)
        assert starts, 'FORCE must overlap real inference'
        force = time.monotonic()
        await link.cancel(3)
        result['forceAckMs'] = (time.monotonic()-force)*1000
        await generation(4, source[:6400])
        result['checks']['forceAndNewGeneration'] = 'PASS'
        if inject_crash:
            # Only PID from our own supervisor state, cross-checked with authenticated status.
            state = json.loads((Path(cfg.state_dir)/'supervisor.json').read_text())
            before = await asyncio.to_thread(probe, cfg, '/v1/status')
            assert before['workerRef'] == cfg.worker_ref and before['workerEpoch'] == link.epoch and before['processPid'] == state['childPid']
            old = link.epoch
            await link.close()
            os.kill(state['childPid'], signal.SIGKILL)
            recovery = time.monotonic()
            deadline = recovery+cfg.startup_timeout_s+20
            while time.monotonic() < deadline:
                try:
                    snap = await asyncio.to_thread(probe, cfg)
                    if snap['ready'] and snap['workerEpoch'] != old:
                        break
                except Exception:
                    pass
                await asyncio.sleep(.5)
            else:
                raise AssertionError('CRASH_RECOVERY_TIMEOUT')
            link = WorkerLink(endpoint, 'rtx3080-short-smoke', event)
            await link.connect()
            assert link.ready['model_load_count'] == 1 and link.ready['cache_id'] == cache
            assert snap['avatarCacheStatus']['metadataRestored'] and snap['avatarCacheStatus']['preprocessingRebuilt']
            result['recoverySeconds'] = time.monotonic()-recovery
            result['recoveredReady'] = link.ready
            await generation(5, source[:6400])
            result['checks']['crashRecoveryNewEpochCache'] = 'PASS'
        # A failed background assertion must not be hidden by finally's task cleanup.
        if watcher.done():
            await watcher
        assert result['statusSamples'], 'management sampling must produce evidence'
        assert all(s['queueDepth']['audioSamples'] <= 32000 and s['queueDepth']['videoFrames'] <= 24
                   for s in result['statusSamples'])
        result['checks']['boundedQueues'] = 'PASS'
        result['verdict'] = 'PASS_DIRECT_GPU_SMOKE'
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await link.close()
        result['clientEvents'] = events
        (output/'real-smoke.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--pcm', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--inject-crash', action='store_true')
    a = p.parse_args()
    os.umask(0o077)
    result = asyncio.run(run(Config.load(a.config), pcm_file(a.pcm), Path(a.output), a.inject_crash))
    print(json.dumps(dict(verdict=result['verdict'], checks=result['checks'])))


if __name__ == '__main__':
    main()
