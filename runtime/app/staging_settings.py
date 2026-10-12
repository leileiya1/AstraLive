"""Startup configuration copied into the authenticated BEGIN_RUN capture."""
from dataclasses import dataclass
import os

from gpu_worker.staging_contract import validate_capture


@dataclass(frozen=True)
class StagingSettings:
    enabled: bool = False
    limits_revision: str | None = None
    short_gate_sha256: str | None = None

    def capture(self):
        return {"soulxStagingEnabled": self.enabled, "soulxStagingLimitsRevision": self.limits_revision,
                "soulxStagingShortGateSHA256": self.short_gate_sha256}

    @classmethod
    def from_env(cls):
        value=os.getenv("ASTRALIVE_SOULX_STAGING_ENABLED","false").lower()
        if value not in {"true","false","1","0"}:raise ValueError("invalid SoulX staging flag")
        if value in {"false","0"}:return cls()
        value=cls(True,os.getenv("ASTRALIVE_SOULX_STAGING_LIMITS_REVISION","staging-short-1"),
                  os.getenv("ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256") or None)
        validate_capture(value.capture());return value

    def check_capture(self, flags):
        names=tuple(self.capture())
        # Old compatibility runs may lack the new fields, but cannot grant
        # staging. An enabled deployment requires all three captured fields.
        if not self.enabled and not any(name in flags for name in names):return self.capture()
        value={name:flags.get(name) for name in names};validate_capture(value)
        if value!=self.capture():raise ValueError("captured staging mode/profile mismatch")
        return value
