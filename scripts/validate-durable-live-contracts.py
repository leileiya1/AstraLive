#!/usr/bin/env python3
"""Offline wire/fixture contract validation; does not implement execution or SQL."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/v0.5/durable-live"
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def valid_datetime(value):
    # jsonschema's optional RFC3339 dependency may be absent. Never silently
    # accept impossible calendar dates in the contract-only test environment.
    if not isinstance(value, str):
        return True  # type is validated separately
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite JSON value: {value}")


def parse(text):
    return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)


def load(name):
    return parse((CONTRACT / name).read_text())


def canonical(value):
    def check(item):
        if isinstance(item, float):
            raise ValueError("floats are forbidden in canonical command JSON")
        if isinstance(item, int) and not isinstance(item, bool) and abs(item) > 9007199254740991:
            raise ValueError("integer outside exact JSON range")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("object keys must be strings")
            for child in item.values():
                check(child)
        if isinstance(item, list):
            for child in item:
                check(child)
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate(schema_ref, value):
    schema = load("schema.json")
    if not schema_ref.startswith("#/$defs/"):
        raise ValueError("external schema resolution is forbidden")
    if schema_ref.removeprefix("#/$defs/") not in schema["$defs"]:
        raise ValueError(f"undefined schema: {schema_ref}")
    Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                           "$ref": schema_ref}, format_checker=FORMATS).validate(value)


def same_scope(parent, child):
    for key in ("tenantId", "ownerId", "runId"):
        if parent[key] != child[key]:
            raise ValueError(f"cross-scope {key}")


def validate_bundle(bundle):
    validate("#/$defs/PlanBundle", bundle)
    plan, segments = bundle["plan"], bundle["segments"]
    if plan["productId"] != plan["snapshot"]["productId"]:
        raise ValueError("product snapshot identity mismatch")
    if digest(plan["snapshot"]) != plan["productSnapshotVersion"]:
        raise ValueError("product snapshot hash mismatch")
    if [s["segmentId"] for s in segments] != plan["segmentOrder"]:
        raise ValueError("segmentOrder must equal ordered segment IDs")
    if [s["sequence"] for s in segments] != list(range(1, len(segments) + 1)):
        raise ValueError("segment sequence must be contiguous from 1")
    for segment in segments:
        same_scope(plan, segment)
        if segment["planId"] != plan["planId"]:
            raise ValueError("cross-plan segment")
        if hashlib.sha256(segment["content"].encode()).hexdigest() != segment["textHash"]:
            raise ValueError("segment text hash mismatch")
        for fact in segment["factDependencies"]:
            if fact["productId"] != plan["productId"]:
                raise ValueError("cross-product fact")
        if segment["state"] == "COMPLETED" and segment["checkpointState"] != "COMPLETED":
            raise ValueError("completed segment requires business commit checkpoint")


def validate_command(command):
    validate("#/$defs/RuntimeCommand", command)
    unhashed = {key: value for key, value in command.items() if key != "requestHash"}
    if digest(unhashed) != command["requestHash"]:
        raise ValueError("immutable command hash mismatch")
    payload = command["payload"]
    if hashlib.sha256(payload["text"].encode()).hexdigest() != payload["textHash"]:
        raise ValueError("command text hash mismatch")
    for fact in payload["factDependencies"]:
        if fact["productId"] != payload["productId"]:
            raise ValueError("command fact belongs to another product")


def validate_control_command(name, command):
    validate("#/$defs/" + name + "Request", command)
    if digest({k: v for k, v in command.items() if k != "requestHash"}) != command["requestHash"]:
        raise ValueError("immutable control command hash mismatch")


def validate_checkpoint(checkpoint):
    validate("#/$defs/PlaybackCheckpoint", checkpoint)
    evidence = checkpoint["evidence"]
    proofs = evidence["sinkProofs"]
    if len({p["sinkId"] for p in proofs}) != len(proofs):
        raise ValueError("duplicate sink proof")
    if checkpoint["state"] in ("LOCAL_MEDIA_DRAINED", "COMPLETED"):
        if not set(evidence["requiredSinks"]).issubset({p["sinkId"] for p in proofs}):
            raise ValueError("missing required sink proof")
        for proof in proofs:
            if (proof["finalAudioSampleExclusive"] <= proof["firstAudioSample"] or
                    proof["audioConsumedThroughExclusive"] < proof["finalAudioSampleExclusive"] or
                    proof["videoConsumedThroughFrame"] < proof["finalVideoFrame"]):
                raise ValueError("incomplete terminal media range")


def check_all():
    schema = load("schema.json")
    Draft202012Validator.check_schema(schema)
    protocol = load("protocol.json")
    assert protocol["contractRevision"] == "durable-live-1"
    operations = {op["operationId"]: op for op in protocol["operations"]}
    assert len(operations) == len(protocol["operations"]), "duplicate operationId"
    routes = {(o["target"], o["method"], o["path"]) for o in operations.values()}
    assert len(routes) == len(operations), "duplicate route"
    for op in operations.values():
        assert op["path"].startswith("/internal/v0.5/"), "unversioned private route"
        assert set(op["roles"]) <= {"CONTROL", "RUNTIME_JOURNAL", "OUTPUT_GUARDIAN"}
        assert op["roles"] and op["successStatus"] in (200, 201, 202)
        for key in ("requestSchema", "responseSchema"):
            assert op[key].removeprefix("#/$defs/") in schema["$defs"]
    fixtures = load("examples/protocol.json")
    assert len(fixtures) == len(operations), "one example per operation required"
    assert {f["operationId"] for f in fixtures} == operations.keys()
    for example in fixtures:
        op = operations[example["operationId"]]
        validate(op["requestSchema"], example["request"])
        validate(op["responseSchema"], example["response"])
        req, resp = example["request"], example["response"]
        if "requestId" in resp:
            assert req["requestId"] == resp["requestId"]
        if "bundle" in req:
            same_scope(req, req["bundle"]["plan"])
            validate_bundle(req["bundle"])
        if "turn" in req:
            same_scope(req, req["turn"])
        if "checkpoint" in req:
            same_scope(req, req["checkpoint"])
            validate_checkpoint(req["checkpoint"])
        if "command" in req:
            same_scope(req, req["command"])
            validate_command(req["command"])
        if example["operationId"] == "RuntimeExecute":
            validate_command(req)
        if example["operationId"] in ("RuntimeStop", "FenceInstall"):
            validate_control_command(example["operationId"], req)
    objects = load("examples/objects.json")
    for example in objects:
        validate(example["schemaRef"], example["value"])
        if example["name"] == "RuntimeCommand":
            validate_command(example["value"])
        if example["name"] == "PlaybackCheckpoint":
            validate_checkpoint(example["value"])
        if example["name"] == "RunLease":
            assert example["value"]["fencingToken"] == example["value"]["runEpoch"]
    for vector in load("examples/hash-vectors.json"):
        assert canonical(vector["value"]).decode() == vector["canonicalUtf8"]
        assert digest(vector["value"]) == vector["sha256"]
    for machine_name, machine in load("state-machines.json")["machines"].items():
        assert set(machine["states"]) == set(schema["$defs"][machine_name]["properties"][
            "status" if machine_name in ("BroadcastRun", "DispatchIntent") else "state"]["enum"])
        pairs = set()
        for edge in machine["transitions"]:
            assert edge["fromState"] in machine["states"] and edge["toState"] in machine["states"]
            assert edge["guard"] and edge["fromState"] != edge["toState"]
            pair = (edge["fromState"], edge["toState"])
            assert pair not in pairs, f"duplicate transition: {machine_name} {pair}"
            pairs.add(pair)
    frozen = load("baseline-sha256.json")
    assert frozen["baseline"] == protocol["baseline"]
    for filename, expected in frozen["files"].items():
        actual = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        assert actual == expected, f"frozen baseline file changed: {filename}"
    return {"operations": len(operations), "object_examples": len(objects),
            "hash_vectors": len(load("examples/hash-vectors.json")),
            "machines": len(load("state-machines.json")["machines"]),
            "frozen_files": len(frozen["files"])}


if __name__ == "__main__":
    try:
        print("PASS " + json.dumps(check_all(), sort_keys=True))
    except (AssertionError, ValueError, KeyError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        sys.exit(1)
