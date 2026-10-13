"""Linux child entrypoint: media only, no application tokens or profile storage."""
import base64
import importlib
import json
import os
import resource
import sys


def main():
    # The launcher must have established a distinct kernel network namespace.
    if sys.platform != "linux" or os.readlink("/proc/self/ns/net") == sys.argv[2]:
        return 78
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    from .personal_assets import AssetValidationError, validate_photo, validate_reference_audio
    try:
        raw = sys.stdin.buffer.read(28 * 1024 * 1024 + 1)
        if len(raw) > 28 * 1024 * 1024:
            raise AssetValidationError("INVALID_ARGUMENT")
        payload = json.loads(raw)
        if set(payload) != {"data", "referenceText"}:
            raise AssetValidationError("INVALID_ARGUMENT")
        data = base64.b64decode(payload["data"], validate=True)
        if sys.argv[1] == "VALIDATE_PHOTO":
            inspector = None
            if len(sys.argv) > 3:
                module, function = sys.argv[3].split(":", 1)
                inspector = getattr(importlib.import_module(module), function)
            output = validate_photo(data, inspector).png
        elif sys.argv[1] == "VALIDATE_AUDIO":
            output = validate_reference_audio(data, payload["referenceText"]).wav
        else:
            raise AssetValidationError("INVALID_ARGUMENT")
        result = {"ok": True, "data": base64.b64encode(output).decode("ascii")}
    except AssetValidationError as exc:
        result = {"ok": False, "code": str(exc)}
    except Exception:
        result = {"ok": False, "code": "PROCESSOR_UNAVAILABLE"}
    # No stderr, user paths, transcripts or raw error strings are emitted.
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
