"""Consume Agent 1's machine schema directly, without copying profile DTOs."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class PersonalContract:
    def __init__(self, schema_path: Path | None = None):
        path = schema_path or Path(__file__).resolve().parents[2] / "contracts/personal-assets/schema.json"
        self.document = json.loads(path.read_text())
        if self.document["info"]["version"] != "0.3.1":
            raise ValueError("PERSONAL_CONTRACT_VERSION_UNSUPPORTED")

    def validate(self, name: str, value):
        return self._validate_ref("#/components/schemas/" + name, value)

    def validate_property(self, name: str, field: str, value):
        return self._validate_ref("#/components/schemas/" + name + "/properties/" + field, value)

    def _validate_ref(self, reference, value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("INVALID_ARGUMENT") from None
        # All refs resolve within the trusted checked-in contract; no remote resolver.
        schema = {"components": self.document["components"], "$ref": reference}
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        if not validator.is_valid(value):
            raise ValueError("INVALID_ARGUMENT")
        return value
