"""Owned child registry: fsync before handing a child any publishing secret."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from multiprocessing import Pipe
from pathlib import Path

import psutil

from .model import Closed


class Publisher:
    def __init__(self, state_dir, module="publisher"):
        self.state_dir = Path(state_dir)
        self.module = module
        self.registry = self.state_dir / (module + ".json")
        self.process = self.pipe = None
        self.identity = None
        self.lock = asyncio.Lock()

    def recover(self):
        if not self.registry.exists():
            return
        try:
            data = json.loads(self.registry.read_text())
            process = psutil.Process(data["pid"])
            if abs(process.create_time() - data["created"]) > 0.001:
                raise Closed()  # PID reuse is uncertainty, never permission to kill.
            if process.status() == psutil.STATUS_ZOMBIE:
                self.registry.unlink()
                return
            if process.environ().get("ASTRALIVE_GUARDIAN_CHILD") != data["marker"]:
                raise Closed()
            process.kill()
            try:
                process.wait(timeout=1)
            except psutil.TimeoutExpired:
                if process.status() != psutil.STATUS_ZOMBIE:
                    raise Closed()
        except psutil.NoSuchProcess:
            pass
        except Closed:
            raise
        except Exception:
            raise Closed() from None
        self.registry.unlink()

    async def start(self, config):
        if self.process:
            raise Closed()
        self.identity = config.get("identity")
        parent, child = Pipe(duplex=True)
        marker = uuid.uuid4().hex
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "output_guardian." + self.module,
                "--fd",
                str(child.fileno()),
            ],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                "PATH": os.defpath,
                "PYTHONNOUSERSITE": "1",
                "ASTRALIVE_GUARDIAN_CHILD": marker,
            },
            close_fds=True,
        )
        child.close()
        self.pipe = parent
        try:
            record = {
                "pid": self.process.pid,
                "created": psutil.Process(self.process.pid).create_time(),
                "marker": marker,
            }
            temp = self.registry.with_suffix(".tmp")
            with temp.open("w") as f:
                os.chmod(temp, 0o600)
                json.dump(record, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.registry)
            fd = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            response = await self.call(config, timeout=0.8)
            if response != {"ready": True}:
                raise Closed()
        except BaseException:
            await self.abort()
            raise

    async def call(self, message, timeout=0.15):
        expected, pipe, identity = self.process, self.pipe, self.identity
        if self.module == "publisher" and "op" in message:
            message = message | {"identity": identity}
        async with self.lock:
            if (
                expected is None
                or self.process is not expected
                or self.pipe is not pipe
                or expected.poll() is not None
            ):
                raise Closed("MEDIA_DELIVERY_FAILED")

            def exchange():
                pipe.send(message)
                if not pipe.poll(timeout):
                    raise Closed("MEDIA_DELIVERY_FAILED")
                return pipe.recv()

            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(exchange), timeout + 0.02
                )
                if (
                    self.process is not expected
                    or self.pipe is not pipe
                    or "error" in response
                ):
                    raise Closed("MEDIA_DELIVERY_FAILED")
                return response
            except BaseException:
                # A timed-out writer thread must not deliver into a future child.
                await self.abort(expected)
                raise Closed("MEDIA_DELIVERY_FAILED") from None

    async def abort(self, expected=None):
        if expected is not None and self.process is not expected:
            return
        process, self.process = self.process, None
        pipe, self.pipe = self.pipe, None
        if process:
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait)
        if pipe:
            pipe.close()
        self.registry.unlink(missing_ok=True)
