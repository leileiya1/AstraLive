"""Resident, fixed SoulX Lite model; no network downloads or environment installers."""
import fractions
import os
from pathlib import Path
import subprocess
import sys
import time

from .config import digest
from .telemetry import atomic_json
from .validated.adapter import StreamingAdapter, restore_published_pose


class ResidentModel:
    def __init__(self, cfg, metrics):
        self.cfg, self.metrics = cfg, metrics
        self.load_count = 0

    def load(self):
        self.metrics.event('WeightValidationStart')
        self.cfg.verify_assets()
        self.metrics.event('WeightsVerified', manifest_sha256=self.cfg.manifest_sha256, simulation=self.cfg.mode == 'simulation')
        if self.cfg.mode == 'gpu':
            # The pinned deployment provides PyAV in this existing directory.
            sys.path.insert(0, str(Path(self.cfg.lab_root) / 'streaming/worker-deps'))
        import av
        import numpy as np
        import torch
        self.metrics.event('ModelLoadStart')
        if self.cfg.mode == 'simulation':
            # CPU-only test process; StreamingAdapter retains its validated CUDA barriers.
            torch.cuda.synchronize = lambda: None
            class Pipeline:
                device = 'cpu'
                param_dtype = torch.float32
                class VAE:
                    def encode(self, value):
                        return value
                vae = VAE()
                def reset_person_name(self):
                    self.latent_motion_frames = None
            self.pipeline = Pipeline()
            self.embedding = lambda *a: None
            self.inference = lambda *a: torch.zeros((33, 512, 512, 3))
        else:
            from .hardware import validate_gpu
            validate_gpu(torch)
            import flash_attn
            if sys.version_info[:3] != (3, 12, 3) or torch.__version__ != '2.8.0+cu128' or torch.version.cuda != '12.8' or flash_attn.__version__ != '2.8.3':
                raise RuntimeError('PINNED_ENVIRONMENT_MISMATCH')
            root = Path(self.cfg.lab_root) / 'repositories/SoulX-FlashHead'
            revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            if revision != self.cfg.model_revision:
                raise RuntimeError('MODEL_SOURCE_REVISION_MISMATCH')
            if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no']):
                raise RuntimeError('MODEL_SOURCE_DIRTY')
            os.environ['HF_HUB_OFFLINE'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '1'
            os.chdir(root)
            sys.path.insert(0, str(root))
            from flash_head.inference import get_pipeline, get_base_data, get_audio_embedding, run_pipeline
            self.pipeline = get_pipeline(1, str(Path(self.cfg.lab_root) / 'models/soulx/SoulX-FlashHead-1_3B'), 'lite', str(Path(self.cfg.lab_root) / 'models/soulx/wav2vec2-base-960h'))
            get_base_data(self.pipeline, self.cfg.asset_path, 42, False)
            self.embedding, self.inference = get_audio_embedding, run_pipeline
        self.load_count += 1
        # Same warmup blocks, pose policy and encoder gate as pinned worker_final.
        for i in range(3):
            frames = self.inference(self.pipeline, self.embedding(self.pipeline, np.zeros(128000, np.float32), 167, 200)).cpu().numpy().astype(np.uint8)
            restore_published_pose(self.pipeline, list(frames[-9:]))
            if self.cfg.mode == 'gpu':
                torch.cuda.synchronize()
            self.metrics.event('WarmupBlock', block=i)
        codec = self.encoder()
        frame = av.VideoFrame.from_ndarray(frames[-1], format='rgb24')
        frame.pts = 0
        if len(codec.encode(frame)) != 1:
            raise RuntimeError('ENCODER_READY_GATE_FAILED')
        self.pipeline.reset_person_name()
        if self.cfg.mode == 'gpu':
            torch.cuda.synchronize()
        identity = self.cfg.manifest_sha256 + self.cfg.asset_sha256 + self.cfg.model_revision + ':512:33:9:4:seed42'
        import hashlib
        self.cache_id = hashlib.sha256(identity.encode()).hexdigest()
        metadata = dict(cacheId=self.cache_id, avatarRef=self.cfg.avatar_ref, inputAssetSHA256=self.cfg.asset_sha256,
                        modelRevision=self.cfg.model_revision, preprocessingVersion='soulx-lite-512-seed42-v1')
        cache_file = Path(self.cfg.state_dir) / 'avatar-cache.json'
        restored = False
        if cache_file.exists():
            import json
            try:
                restored = json.loads(cache_file.read_text()) == metadata
            except (ValueError, OSError):
                pass
        atomic_json(cache_file, metadata)
        self.metrics.cache = dict(metadata, status='READY', metadataRestored=restored, preprocessingRebuilt=True)
        return dict(status='GPU_WORKER_READY', worker_epoch=self.metrics.epoch, cache_id=self.cache_id,
                    input_asset_sha256=self.cfg.asset_sha256, model_revision=self.cfg.model_revision,
                    model_load_count=self.load_count, codec='h264', av_version=av.__version__,
                    torch_version=torch.__version__, weights_manifest_sha256=self.cfg.manifest_sha256,
                    internal_version='1.1', simulation=self.cfg.mode == 'simulation')

    @staticmethod
    def encoder():
        import av
        c = av.CodecContext.create('libx264', 'w')
        c.width = c.height = 512
        c.pix_fmt = 'yuv420p'
        c.time_base = fractions.Fraction(1, 25)
        c.framerate = fractions.Fraction(25, 1)
        c.thread_count = 2
        c.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'bf': '0', 'g': '25', 'crf': '20', 'x264-params': 'repeat-headers=1:scenecut=0'}
        c.open()
        return c

    def adapter(self):
        return StreamingAdapter(self.pipeline, self.embedding, self.inference, self.metrics.event)

    def gpu(self):
        if self.cfg.mode != 'gpu':
            return {'gpuAllocatedBytes': None, 'gpuReservedBytes': None}
        import torch
        return dict(gpuAllocatedBytes=torch.cuda.memory_allocated(), gpuReservedBytes=torch.cuda.memory_reserved())
