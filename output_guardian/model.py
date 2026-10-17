"""Private guardian IPC v1; does not amend durable-live-1 or GPU wire."""

import math
import re
import time
from dataclasses import asdict, dataclass


class Closed(Exception):
    def __init__(self, code="OUTPUT_FENCE_UNPROVEN"):
        self.code = code
        super().__init__(code)


def clock():
    return time.clock_gettime(
        getattr(
            time,
            "CLOCK_BOOTTIME",
            getattr(time, "CLOCK_MONOTONIC_RAW", time.CLOCK_MONOTONIC),
        )
    )


def integer(value, minimum=0, maximum=9007199254740991):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Closed("INVALID_ARGUMENT")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        raise Closed("INVALID_ARGUMENT")
    return value


@dataclass(frozen=True)
class Binding:
    tenantId: str
    ownerId: str
    roomId: str
    runId: str
    runEpoch: int
    sessionId: str
    outputBindingVersion: int
    producerIncarnation: str

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__annotations__):
            raise Closed("INVALID_ARGUMENT")
        for k, v in data.items():
            integer(v, 1) if k in {"runEpoch", "outputBindingVersion"} else identifier(
                v
            )
        return cls(**data)

    def json(self):
        return asdict(self)


@dataclass(frozen=True)
class Attempt:
    binding: Binding
    attemptId: str
    utteranceId: str
    generation: int
    commandId: str

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__annotations__):
            raise Closed("INVALID_ARGUMENT")
        return cls(
            Binding.parse(data["binding"]),
            identifier(data["attemptId"]),
            identifier(data["utteranceId"]),
            integer(data["generation"], 1),
            identifier(data["commandId"]),
        )

    def json(self):
        return asdict(self)


@dataclass(frozen=True)
class Right:
    permit_id: str
    deadline: float
    monotonic_deadline: float

    @classmethod
    def from_remaining(cls, permit_id, seconds, sent, mono):
        if not math.isfinite(seconds) or seconds <= 0.100 or seconds > 1.001:
            raise Closed("LEASE_LOST")
        right = cls(
            permit_id,
            sent + min(seconds, 1.0) - 0.100,
            mono + min(seconds, 1.0) - 0.100,
        )
        right.check()
        return right

    def check(self):
        if clock() >= self.deadline or time.monotonic() >= self.monotonic_deadline:
            raise Closed("LEASE_LOST")
