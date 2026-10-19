import json
import os
import time
from pathlib import Path

rows = []


def log(phase, **kw):
    rows.append(dict(phase=phase, at=time.monotonic(), **kw))


def pytest_configure(config):
    from output_guardian.v2.clocks import suspend_clock
    from output_guardian.v2.cpu import CPUMedia
    from output_guardian.v2.ports import BoundedAuthority
    from output_guardian.v2.receiver import Receiver

    orig = Receiver.consume
    start = CPUMedia.start
    media = Receiver.media
    rpc = BoundedAuthority._call

    async def consume(self, *a, **kw):
        log("consume_start")
        out = await orig(self, *a, **kw)
        log(
            "consume_return",
            mono_left=self.gate.edge.deadlines[0] - time.monotonic(),
            suspend_left=self.gate.edge.deadlines[1] - suspend_clock(),
        )
        return out

    async def startup(self, *a, **kw):
        log("cpu_start")
        out = await start(self, *a, **kw)
        log("cpu_start_return", pid=self.process.pid)
        return out

    async def frame(self, peer, q):
        log(
            "media_entry",
            kind=q["kind"],
            sequence=q["sequence"],
            mono_left=self.gate.edge.deadlines[0] - time.monotonic(),
            suspend_left=self.gate.edge.deadlines[1] - suspend_clock(),
        )
        return await media(self, peer, q)

    async def call(self, method, op, request):
        t = time.monotonic()
        out = await rpc(self, method, op, request)
        log("rpc", operation=op, seconds=time.monotonic() - t)
        return out

    Receiver.consume = consume
    CPUMedia.start = startup
    Receiver.media = frame
    BoundedAuthority._call = call


def pytest_collection_modifyitems(items):
    for it in items:
        mod = it.module
        if hasattr(mod, "av_unit") and not getattr(mod, "_probe_installed", False):
            fn = mod.av_unit

            async def traced(*a, _fn=fn, **kw):
                log("av_unit_entry")
                if os.getenv("AG5_BLOCK_AFTER_ACK") == "1":
                    time.sleep(0.8)
                return await _fn(*a, **kw)

            mod.av_unit = traced
            mod._probe_installed = True


def pytest_sessionfinish(session, exitstatus):
    Path(os.environ["AG5_PROBE"]).write_text(
        json.dumps(dict(exit=int(exitstatus), events=rows), indent=2) + "\n"
    )
