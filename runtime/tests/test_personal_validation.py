import sys
import unittest

from app.personal_assets import AssetValidationError
from app.personal_processor import ProcessorFault
from app.personal_validation import IsolatedMediaValidator


class IsolatedValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_size_and_operator_module_validation_before_subprocess(self):
        with self.assertRaisesRegex(ValueError, "INVALID_ARGUMENT"):
            IsolatedMediaValidator("https://untrusted/detector")
        validator = IsolatedMediaValidator()
        with self.assertRaisesRegex(AssetValidationError, "PHOTO_SIZE_INVALID"):
            await validator("VALIDATE_PHOTO", b"x" * (10 * 1024 * 1024 + 1), "")
        with self.assertRaisesRegex(ProcessorFault, "INVALID_ARGUMENT"):
            await validator("TRAIN_MODEL", b"data", "")

    async def test_unsupported_host_never_falls_back_to_unisolated_decode(self):
        from unittest.mock import patch
        with patch("app.personal_validation.sys.platform", "darwin"):
            with self.assertRaisesRegex(ProcessorFault, "PROCESSOR_UNAVAILABLE"):
                await IsolatedMediaValidator()("VALIDATE_PHOTO", b"private-photo", "")

    def test_sandbox_arguments_do_not_mount_home_or_root_and_bound_temp_storage(self):
        from pathlib import Path
        args = IsolatedMediaValidator()._arguments("/usr/bin/bwrap", "VALIDATE_PHOTO", "net:[fixture]")
        self.assertIn("--unshare-net", args)
        self.assertIn("--unshare-pid", args)
        size = args.index("--size")
        self.assertEqual(args[size + 1:size + 4], [str(256 * 1024 * 1024), "--tmpfs", "/tmp"])
        mounts = [args[i + 1] for i, value in enumerate(args) if value == "--ro-bind"]
        self.assertNotIn("/", mounts)
        self.assertNotIn(str(Path.home()), mounts)
        with self.assertRaisesRegex(ValueError, "INVALID_ARGUMENT"):
            IsolatedMediaValidator(read_only_model_roots=["/"])
        with self.assertRaisesRegex(ValueError, "INVALID_ARGUMENT"):
            IsolatedMediaValidator(read_only_model_roots=[str(Path.home().resolve())])


if __name__ == "__main__":
    unittest.main()
