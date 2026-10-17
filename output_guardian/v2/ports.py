"""Restricted, injected dependencies; no invented Authority transport/DTO.

Agent 4's sole DTO package must implement Wire and TrustedInstallation. Agent 2
must supply Authority using the three frozen operation signatures. Only tests
provide mocks today. Neither interface grants SQL mutation or CONTROL powers.
"""

import asyncio
import copy
from typing import Mapping, Protocol

from output_guardian.model import Closed

from .gate import require


class Wire(Protocol):
    def decode(self, schema: str, raw: bytes) -> dict: ...
    def validate(self, schema: str, document: Mapping) -> None: ...
    def canonical(self, document: Mapping) -> bytes: ...
    def digest(self, document: Mapping) -> str: ...
    def validate_artifact(self, artifact: Mapping) -> None: ...


class Authority(Protocol):
    async def query_receiver_authority(self, request: Mapping) -> Mapping: ...
    async def commit_receiver_consume(self, request: Mapping) -> Mapping: ...
    async def query_receiver_consumption(self, request: Mapping) -> Mapping: ...


class BoundedAuthority:
    """No retries or true-response cache. Transport/auth remain Agent2/4-owned.

    These are exactly the frozen three operations, NOT a replacement protocol.
    Both directions use Agent4's sole strict codec; ambiguity is never retried.
    """

    def __init__(self, wire, transport, timeout=0.200):
        require(0 < timeout <= 0.250, "INVALID_ARGUMENT")
        self.wire, self.transport, self.timeout = wire, transport, timeout

    async def _call(self, method, operation, request):
        self.wire.validate(operation + "Request", request)
        try:
            out = copy.deepcopy(await asyncio.wait_for(method(request), self.timeout))
            self.wire.validate(operation + "Response", out)
            require(out["requestId"] == request["requestId"], "CONSUMPTION_UNKNOWN")
            return out
        except Exception:
            raise Closed("DEPENDENCY_UNAVAILABLE") from None

    async def query_receiver_authority(self, request):
        return await self._call(
            self.transport.query_receiver_authority, "QueryReceiverAuthority", request
        )

    async def commit_receiver_consume(self, request):
        return await self._call(
            self.transport.commit_receiver_consume, "CommitReceiverConsume", request
        )

    async def query_receiver_consumption(self, request):
        return await self._call(
            self.transport.query_receiver_consumption,
            "QueryReceiverConsumption",
            request,
        )


class TrustedInstallation(Protocol):
    async def read(self, request: Mapping) -> Mapping: ...


class Outputs(Protocol):
    async def close(self) -> bool:
        """Independently prove owned publishers/sockets/peers are closed."""
        ...

    async def observe(self, lineage, tail) -> Mapping:
        """Return registered evidence for ALL required decoded sink ranges."""
        ...
