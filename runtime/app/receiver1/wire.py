"""The only mapping boundary between the official typed SDK and Guardian.

All JSON parsing, validation, canonicalization and artifact equations belong to
the generated SDK. Mapping conversion preserves opaque SecretString values.
"""
import dataclasses

from astralive_contracts import durable_live_v2 as dto
from astralive_contracts.durable_live_v2.codec import SecretString, WireModel


def mapping(value):
    if isinstance(value, WireModel):
        return {f.name: mapping(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [mapping(v) for v in value]
    if isinstance(value, SecretString):
        return value
    return value


class GuardianWire:
    def decode(self, schema, raw):
        limits = [o.max_body_bytes for o in dto.OPERATIONS.values()
                  if schema in (o.request_schema, o.response_schema, o.error_schema)]
        if limits and len(raw) > min(limits):
            raise dto.WireError("BODY_TOO_LARGE")
        return mapping(dto.decode(schema, raw))

    def validate(self, schema, document):
        self.decode(schema, dto.canonical_json(document))

    def canonical(self, document):
        return dto.canonical_json(document)

    def digest(self, document):
        return dto.digest(document)

    def validate_artifact(self, document):
        artifact = dto.decode("AnswerArtifact", dto.canonical_json(document))
        dto.verify_answer_artifact_hashes(artifact)

    def request(self, operation, raw, *, role, target, method, route_template):
        return mapping(dto.decode_request(operation, raw, role=role, target=target,
                                          method=method, route_template=route_template))
