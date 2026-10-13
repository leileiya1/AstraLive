"""Operator-owned configuration; never accept paths or commands from user profiles."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .staging_contract import PROFILES, SHORT_PROFILES

REVISION = '9bc03de06bb0de82cd6bc477804512ae06144bf2'
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')


def secret(path):
    p = Path(path)
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 256:
        raise ValueError('token file must be private, regular and <=256 bytes')
    value = p.read_text().strip()
    if len(value) < 32 or any(c.isspace() for c in value):
        raise ValueError('token must contain at least 32 non-space characters')
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


@dataclasses.dataclass(frozen=True)
class Config:
    worker_ref: str
    avatar_ref: str
    asset_path: str
    asset_sha256: str
    lab_root: str
    state_dir: str
    token_file: str
    manifest_sha256: str
    python: str
    management_token_file: str
    port: int = 17087
    management_port: int = 17088
    mode: str = 'gpu'
    warmup_blocks: int = 3
    model_revision: str = REVISION
    startup_timeout_s: float = 300
    stop_timeout_s: float = 40
    inference_timeout_s: float = 5
    retries: int = 3
    retry_initial_s: float = 1
    retry_max_s: float = 15
    minimum_free_disk_bytes: int = 1024 * 1024 * 1024
    log_bytes: int = 10 * 1024 * 1024
    log_backups: int = 5
    staging_enabled: bool = False
    staging_profile: str = 'staging-short-1'
    staging_short_gate_sha256: str | None = None

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        # Explicit whitelist only; no arbitrary env-to-command substitution.
        for key in ('state_dir', 'token_file', 'management_token_file', 'python', 'lab_root'):
            value = os.getenv('ASTRALIVE_GPU_' + key.upper())
            if value:
                data[key] = value
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def validate(self):
        if type(self.staging_enabled) is not bool:
            raise ValueError('invalid staging switch')
        if self.staging_profile not in PROFILES:
            raise ValueError('invalid staging profile')
        if self.mode == 'simulation' and self.staging_profile != 'staging-short-1':
            raise ValueError('selected staging profile requires real GPU execution')
        if self.staging_profile in SHORT_PROFILES:
            if self.staging_short_gate_sha256 is not None:
                raise ValueError('short staging gate must be absent')
        elif self.mode == 'simulation' or not isinstance(self.staging_short_gate_sha256, str) or re.fullmatch(r'sha256:[a-f0-9]{64}', self.staging_short_gate_sha256) is None:
            raise ValueError('long staging requires a real short GPU evidence gate')
        if not IDENTIFIER.fullmatch(self.worker_ref) or not IDENTIFIER.fullmatch(self.avatar_ref):
            raise ValueError('invalid logical reference')
        if self.model_revision != REVISION or self.mode not in {'gpu', 'simulation'}:
            raise ValueError('unsupported model or mode')
        if self.warmup_blocks != 3:
            raise ValueError('validated warmup requires three blocks')
        for value in (self.asset_sha256, self.manifest_sha256):
            if not re.fullmatch('[a-f0-9]{64}', value):
                raise ValueError('pinned SHA256 required')
        for field in ('asset_path', 'lab_root', 'state_dir', 'token_file', 'management_token_file', 'python'):
            if not Path(getattr(self, field)).is_absolute():
                raise ValueError('absolute operator paths required')
        if self.port == self.management_port or any(type(p) is not int or not 1 <= p <= 65535 for p in (self.port, self.management_port)):
            raise ValueError('invalid listener port')
        if type(self.retries) is not int or type(self.log_backups) is not int or not 0 <= self.retries <= 10 or not 1 <= self.log_backups <= 20:
            raise ValueError('invalid retry/log bound')
        for value in (self.startup_timeout_s, self.stop_timeout_s, self.inference_timeout_s, self.retry_initial_s, self.retry_max_s, self.minimum_free_disk_bytes, self.log_bytes):
            if not isinstance(value, (int, float)) or not 0 < value <= 10**12:
                raise ValueError('positive finite resource/time limits required')
        if self.retry_initial_s > self.retry_max_s:
            raise ValueError('invalid retry interval')
        for key, maximum in {'startup_timeout_s': 1800, 'stop_timeout_s': 120,
                             'inference_timeout_s': 30, 'retry_initial_s': 60,
                             'retry_max_s': 300, 'log_bytes': 100*1024*1024}.items():
            if getattr(self, key) > maximum:
                raise ValueError('resource/time limit exceeds service policy')
        if self.mode == 'gpu' and 'experiment' in Path(self.state_dir).parts:
            raise ValueError('production state must be isolated')
        secret(self.token_file)
        if secret(self.management_token_file) == secret(self.token_file):
            raise ValueError('inference and management tokens must differ')

    def verify_assets(self):
        if digest(self.asset_path) != self.asset_sha256:
            raise ValueError('AVATAR_SHA256_MISMATCH')
        manifest = Path(self.lab_root) / 'reports/soulx-weight-manifest.json'
        if self.mode == 'simulation':
            return 'SIMULATION'
        if digest(manifest) != self.manifest_sha256:
            raise ValueError('MANIFEST_SHA256_MISMATCH')
        records = json.loads(manifest.read_text())
        if len(records) != 7:
            raise ValueError('expected seven pinned weights')
        for item in records:
            if item['repo'] not in {'facebook/wav2vec2-base-960h', 'Soul-AILab/SoulX-FlashHead-1_3B'}:
                raise ValueError('unsupported weight repository')
            root = Path(self.lab_root) / 'models/soulx' / ('wav2vec2-base-960h' if item['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B')
            target = (root / item['file']).resolve()
            if not target.is_relative_to(root.resolve()) or digest(target) != item['sha256']:
                raise ValueError('WEIGHT_SHA256_MISMATCH')
        return self.manifest_sha256
