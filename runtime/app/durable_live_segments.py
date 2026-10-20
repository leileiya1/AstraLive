"""Pure exact-text preflight for the durable-live-1 SCRIPT_TEXT wrapper.

No queue, journal, TTS, generation ownership or checkpoint side effects. Agent 4
calls this AFTER journal/fence authorization and before the existing TTS path;
COMMENT_QUESTION continues through the existing fact router/streaming LLM.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re


class SegmentRejected(ValueError):
    """No effect is authorized by this helper."""


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SegmentRejected("INVALID_ARGUMENT")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SegmentRejected("INVALID_ARGUMENT") from exc


def exact_script_text(payload: dict, *, product_id: str, source_version: str,
                      validated_facts: list[dict], now: datetime) -> str:
    """Return the original immutable text, without LLM rewriting or splitting.

    validated_facts must be freshly obtained by the trusted Tool adapter. It may
    refresh timestamps, but cannot substitute values from another product or
    change the assertion hash. This is not an output permit or a START grant.
    """
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise SegmentRejected("INVALID_ARGUMENT")
    if payload.get("mode") != "SCRIPT_TEXT" or payload.get("productId") != product_id:
        raise SegmentRejected("PLAN_CHANGED")
    text = payload.get("text")
    if (not isinstance(text, str) or not text.strip() or len(text) > 2000
            or sha256(text.encode("utf-8")).hexdigest() != payload.get("textHash")):
        raise SegmentRejected("COMMAND_CONFLICT")
    if not payload.get("segmentId") or not payload.get("planId"):
        raise SegmentRejected("INVALID_ARGUMENT")
    if now >= _utc(payload.get("expiresAt")):
        raise SegmentRejected("EXPIRED")
    original = payload.get("factDependencies")
    if not isinstance(original, list) or len(original) != len(validated_facts):
        raise SegmentRejected("PLAN_CHANGED")
    for old, fresh in zip(original, validated_facts):
        if (fresh.get("kind") not in {"PRICE", "STOCK", "AVAILABILITY", "SIZE_OPTIONS"}
                or fresh.get("kind") != old.get("kind")
                or fresh.get("valueHash") != old.get("valueHash")
                or not re.fullmatch(r"[0-9a-f]{64}", fresh.get("valueHash", ""))
                or old.get("productId") != product_id or fresh.get("productId") != product_id
                or old.get("sourceVersion") != source_version
                or fresh.get("sourceVersion") != source_version):
            raise SegmentRejected("PLAN_CHANGED")
        validated, expires = _utc(fresh.get("validatedAt")), _utc(fresh.get("expiresAt"))
        if (validated > now or not now < expires or now - validated >= timedelta(seconds=2)
                or expires > validated + timedelta(seconds=2)):
            raise SegmentRejected("FACT_EXPIRED")
    return text
