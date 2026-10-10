"""Bounded, credential-free management snapshots and rotating logs."""
import collections
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import shutil
import threading
import time


def atomic_json(path, value):
    p = Path(path)
    temporary = p.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.chmod(0o600)
    temporary.replace(p)


def logger(cfg, name, secrets=()):
    p = Path(cfg.state_dir)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.propagate = False
    target = str((p / (name + '.log')).resolve())
    if len(log.handlers) == 1 and getattr(log.handlers[0], 'baseFilename', None) == target:
        return log
    for h in log.handlers[:]:
        log.removeHandler(h)
        h.close()
    class Redact(logging.Formatter):
        def format(self, record):
            text = record.getMessage()
            for s in secrets:
                text = text.replace(s, '[REDACTED]')
            text = re.sub(r'(?:https?|rtmps?|ssh)://[^\s"\']+', '[REDACTED_URL]', text)
            text = re.sub(r'(?i)(?:bearer\s+\S+|sk-[\w-]+|token[=:]\s*\S+)', '[REDACTED_SECRET]', text)
            return text[:8192]
    handler = RotatingFileHandler(p / (name + '.log'), maxBytes=cfg.log_bytes, backupCount=cfg.log_backups)
    handler.setFormatter(Redact())
    log.addHandler(handler)
    return log


class Metrics:
    def __init__(self, cfg, epoch):
        self.cfg, self.epoch = cfg, epoch
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.inference_started = None
        self.last_error = None
        self.ready = False
        self.generated = self.published = 0
        self.compute_ms = 0
        self.samples = collections.deque(maxlen=256)
        self.cache = {}
        self.cancel = {'generationId': None, 'status': 'NONE'}
        self.log = logger(cfg, 'worker', ())

    def event(self, event, generation_id=None, **data):
        now = time.monotonic()
        with self.lock:
            if event in {'AudioBlockReady', 'GPUInferenceStart'}:
                self.inference_started = now
            elif event == 'GPUOutput':
                self.inference_started = None
                self.generated += data['generated_frames']
                self.compute_ms += data['elapsed_ms']
                self.samples.append((now, data['generated_frames']))
            elif event == 'VideoPacketPublished':
                self.published += 1
            elif event == 'WorkerError':
                self.last_error = 'INFERENCE_FAILED'
                self.inference_started = None
            # No exception text, traceback, PCM, URLs, tokens, or signed assets.
            safe = {k: v for k, v in data.items() if k not in {'error', 'traceback', 'token', 'pcm', 'rgb'}}
            self.log.info(json.dumps(dict(event=event, generation_id=generation_id, worker_epoch=self.epoch, monotonic_s=now, **safe)))

    def snapshot(self, adapter=None, active=None, gpu=None):
        now = time.monotonic()
        # Lock order is always adapter.cv then metrics.lock (adapter logs inside cv).
        if adapter:
            with adapter.cv:
                pending, frames, failed = adapter.pending_samples, len(adapter.video), adapter.error is not None
        else:
            pending = frames = 0
            failed = False
        with self.lock:
            stalled = self.inference_started is not None and now - self.inference_started > self.cfg.inference_timeout_s
            disk = shutil.disk_usage(self.cfg.state_dir)
            error = 'INFERENCE_STALLED' if stalled else ('INFERENCE_FAILED' if failed else self.last_error)
            if disk.free < self.cfg.minimum_free_disk_bytes:
                error = 'DISK_LOW'
            healthy = error is None
            window = [(t, n) for t, n in self.samples if now - t <= 10]
            result = dict(statusVersion='1.0', workerRef=self.cfg.worker_ref, ready=self.ready and healthy,
                          health='UP' if self.ready and healthy else 'DOWN', modelRevision=self.cfg.model_revision,
                          avatarCacheStatus=dict(self.cache), gpuAllocatedBytes=None, gpuReservedBytes=None,
                          trueGeneratedFPS=sum(n for _, n in window) / min(10, max(.001, now-self.started)),
                          modelComputeFPS=self.generated * 1000 / self.compute_ms if self.compute_ms else 0,
                          generatedFrames=self.generated, publishedFrames=self.published,
                          queueDepth={'audioSamples': pending, 'videoFrames': frames}, lastError=error,
                          workerEpoch=self.epoch, generationCancelStatus=dict(self.cancel),
                          diskFreeBytes=disk.free, diskTotalBytes=disk.total,
                          activeGenerationId=active, mode=self.cfg.mode)
        if gpu:
            result.update(gpu())
        return result
