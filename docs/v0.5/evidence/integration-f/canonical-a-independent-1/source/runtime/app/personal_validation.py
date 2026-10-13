"""Linux-only bounded decode launcher with a verified network namespace.

No unsafe in-process fallback on macOS or hosts without usable bubblewrap. A trusted
operator may register a local CPU inspector module:function; never a browser value.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys

from .personal_assets import AssetValidationError
from .personal_contract import PersonalContract
from .personal_processor import ProcessorFault


class IsolatedMediaValidator:
    def __init__(self, face_inspector=None, read_only_model_roots=()):
        if face_inspector is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*", face_inspector):
            raise ValueError("INVALID_ARGUMENT")
        self.face_inspector = face_inspector
        self.model_roots = []
        for item in read_only_model_roots:
            path = Path(item)
            if (not path.is_absolute() or path.resolve() != path or not path.is_dir()
                    or Path.home().resolve().is_relative_to(path)):
                raise ValueError("INVALID_ARGUMENT")
            self.model_roots.append(path)

    def _arguments(self, executable, kind, namespace):
        args = [executable, "--unshare-user", "--unshare-net", "--unshare-pid", "--unshare-ipc",
                "--die-with-parent", "--proc", "/proc", "--dev", "/dev"]
        mounts = [Path("/usr"), Path("/lib"), Path("/lib64"), Path("/etc/ld.so.cache"),
                  Path(sys.prefix), Path(sys.base_prefix), Path(__file__).resolve().parent, *self.model_roots]
        seen = set()
        for path in mounts:
            if path.exists() and path not in seen:
                if Path.home().resolve().is_relative_to(path.resolve()):
                    raise ProcessorFault("PROCESSOR_UNAVAILABLE")
                args.extend(["--ro-bind", str(path), str(path)])
                seen.add(path)
        args.extend(["--size", str(256 * 1024 * 1024), "--tmpfs", "/tmp", "--chdir", "/tmp",
                     "--remount-ro", "/", sys.executable, "-m", "app.personal_validation_worker", kind, namespace])
        if self.face_inspector:
            args.append(self.face_inspector)
        return args

    async def __call__(self, kind, data, reference_text):
        limits = {"VALIDATE_PHOTO": (10 * 1024 * 1024, "PHOTO_SIZE_INVALID"),
                  "VALIDATE_AUDIO": (20 * 1024 * 1024, "REFERENCE_AUDIO_SIZE_INVALID")}
        if kind not in limits:
            raise ProcessorFault("INVALID_ARGUMENT")
        if not data or len(data) > limits[kind][0]:
            raise AssetValidationError(limits[kind][1])
        sandbox = shutil.which("bwrap")
        if sys.platform != "linux" or sandbox is None:
            raise ProcessorFault("PROCESSOR_UNAVAILABLE")
        namespace = os.readlink("/proc/self/ns/net")
        args = self._arguments(sandbox, kind, namespace)
        payload = json.dumps({"data": base64.b64encode(data).decode("ascii"), "referenceText": reference_text}).encode()
        # Do not inherit service secrets, HOME caches, GPU visibility or user proxies.
        environment = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "CUDA_VISIBLE_DEVICES": "-1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        try:
            process = await asyncio.create_subprocess_exec(*args, env=environment, start_new_session=True,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError:
            raise ProcessorFault("PROCESSOR_UNAVAILABLE") from None

        async def write():
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()

        async def read(stream, maximum):
            output = bytearray()
            while True:
                chunk = await stream.read(16384)
                if not chunk:
                    return bytes(output)
                if len(output) + len(chunk) > maximum:
                    raise ProcessorFault("OUTPUT_INVALID")
                output.extend(chunk)

        tasks = [asyncio.create_task(write()), asyncio.create_task(read(process.stdout, 4 * 1024 * 1024)),
                 asyncio.create_task(read(process.stderr, 65536))]
        try:
            async with asyncio.timeout(60):
                _, output, _ = await asyncio.gather(*tasks)
                await process.wait()
            if process.returncode != 0:
                raise ProcessorFault("PROCESSOR_UNAVAILABLE")
            result = json.loads(output)
            if result.get("ok") is False:
                code = result.get("code")
                PersonalContract().validate("ErrorCode", code)
                raise AssetValidationError(code)
            if result.get("ok") is not True or set(result) != {"ok", "data"}:
                raise ProcessorFault("OUTPUT_INVALID")
            return base64.b64decode(result["data"], validate=True)
        except (ProcessorFault, AssetValidationError, asyncio.CancelledError):
            raise
        except TimeoutError:
            raise ProcessorFault("JOB_TIMEOUT") from None
        except Exception:
            raise ProcessorFault("PROCESSOR_UNAVAILABLE") from None
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await process.wait()
