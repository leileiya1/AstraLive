import asyncio
from datetime import datetime, timezone
import json
import os
import logging
from typing import Protocol
from uuid import uuid4


STREAM = os.getenv("REDIS_RUNTIME_EVENT_STREAM", "dh.runtime.events.v1")
log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def envelope(event_type: str, session_id: str, trace_id: str, utterance_id: str | None = None, payload: dict | None = None) -> dict:
    return {
        "schemaVersion": "1.0", "eventId": f"evt_{uuid4().hex}",
        "eventType": event_type, "sessionId": session_id,
        "utteranceId": utterance_id, "traceId": trace_id,
        "occurredAt": utc_now(), "source": "AI_RUNTIME", "payload": payload or {},
    }


class EventPublisher(Protocol):
    async def publish(self, event: dict) -> None: ...


class MemoryEventPublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class RedisEventPublisher:
    def __init__(self, url: str, retries: int = 3) -> None:
        from redis.asyncio import from_url
        self.client = from_url(url, decode_responses=True)
        self.retries = retries

    async def publish(self, event: dict) -> None:
        for attempt in range(self.retries):
            try:
                await self.client.xadd(STREAM, {"event": json.dumps(event, ensure_ascii=False)})
                return
            except Exception:
                log.exception("event_publish_failed", extra={"traceId": event["traceId"], "sessionId": event["sessionId"], "attempt": attempt + 1})
                if attempt + 1 == self.retries:
                    raise
                await asyncio.sleep(0.1 * 2 ** attempt)

    async def close(self) -> None:
        await self.client.aclose()
