"""Validate the frozen v1.1 OpenAPI, JSON Schema, and example payloads."""

import json
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, Draft7Validator, FormatChecker
from openapi_spec_validator import validate_spec


ROOT = Path(__file__).parent
SPECS = {}
for name in ("control-api.openapi.yaml", "runtime-api.openapi.yaml"):
    spec = yaml.safe_load((ROOT / name).read_text())
    validate_spec(spec)
    assert spec["info"]["version"] == "1.1.0"
    symbols = {}
    for group in ("schemas", "requestBodies", "responses", "parameters"):
        for symbol in spec["components"].get(group, {}):
            assert symbol not in symbols, (name, symbol, symbols[symbol], group)
            symbols[symbol] = group
    SPECS[name] = spec
    print(f"PASS {name}: OpenAPI 3.0.3, unique component symbols")

for name in ("platform-event", "runtime-event", "speech-plan"):
    schema = json.loads((ROOT / "events" / f"{name}.schema.json").read_text())
    example = json.loads((ROOT / "examples" / f"{name}.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    print(f"PASS {name}: JSON Schema and example")

cases = {
    "control-api.openapi.yaml": {
        "webrtc-offer-v1.1": "WebRTCOffer",
        "webrtc-public-answer-v1.1": "WebRTCAnswerResponse",
    },
    "runtime-api.openapi.yaml": {
        "runtime-create-session-v1.1": "CreateRuntimeSessionRequest",
        "runtime-comment-utterance-v1.1": "RuntimeUtteranceRequest",
        "webrtc-offer-v1.1": "WebRTCOffer",
        "webrtc-runtime-answer-v1.1": "WebRTCAnswer",
    },
}
for filename, examples in cases.items():
    spec = SPECS[filename]
    # OpenAPI 3.0 Schema Objects use the JSON Schema Draft 4 family; these
    # selected DTOs use keywords compatible with Draft 7.
    for example_name, schema_name in examples.items():
        example = json.loads((ROOT / "examples" / f"{example_name}.json").read_text())
        # Validate from the OpenAPI document root so local component refs resolve.
        root = {"$schema": "http://json-schema.org/draft-07/schema#", **spec,
                "$ref": f"#/components/schemas/{schema_name}"}
        Draft7Validator(root, format_checker=FormatChecker()).validate(example)
        print(f"PASS {filename}: {example_name} -> {schema_name}")

control = SPECS["control-api.openapi.yaml"]
runtime = SPECS["runtime-api.openapi.yaml"]
assert "/api/v1/live-sessions/{sessionId}/webrtc/offer" in control["paths"]
assert "/internal/v1/sessions/{sessionId}/webrtc/offer" in runtime["paths"]
assert "context" in runtime["components"]["schemas"]["CreateRuntimeSessionRequest"]["required"]
assert "source" in runtime["components"]["schemas"]["RuntimeUtteranceRequest"]["required"]
def valid(spec, component, value):
    root = {"$schema": "http://json-schema.org/draft-07/schema#", **spec,
            "$ref": f"#/components/schemas/{component}"}
    return Draft7Validator(root, format_checker=FormatChecker()).is_valid(value)


session = json.loads((ROOT / "examples" / "runtime-create-session-v1.1.json").read_text())
for field in ("roomId", "systemPrompt"):
    invalid = deepcopy(session)
    del invalid["context"][field]
    assert not valid(runtime, "CreateRuntimeSessionRequest", invalid), field
utterance = json.loads((ROOT / "examples" / "runtime-comment-utterance-v1.1.json").read_text())
invalid = deepcopy(utterance)
del invalid["source"]
assert not valid(runtime, "RuntimeUtteranceRequest", invalid)
invalid = deepcopy(utterance)
invalid["source"] = "DOUYIN"
assert not valid(runtime, "RuntimeUtteranceRequest", invalid)
assert not valid(control, "WebRTCOffer", {"type": "candidate", "sdp": "v=0"})
print("PASS v1.1 route and required-field gates")
