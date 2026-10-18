"""Lifecycle for trusted Agent4 assembly; no Runtime or Authority wiring here."""

import asyncio

from .gate import require


class Supervisor:
    def __init__(self, receiver, ipc):
        self.receiver, self.ipc = receiver, ipc
        self.watchdog = None

    async def start(self):
        require(self.receiver.gate.state == "FENCED", "OUTPUT_FENCE_UNPROVEN")
        try:
            # Adapter startup must reconcile old owned publishers independently
            # while closed. CPU adapter does PID/create-time recovery here.
            await self.receiver.outputs.start()
            self.watchdog = asyncio.create_task(self.receiver.watchdog())
            await self.ipc.start()
        except BaseException:
            await self.close()
            raise

    async def close(self):
        # Revoke under the same gate before waiting for any listener/child.
        failures = []
        for action in (self.receiver.restart, self.ipc.close):
            try:
                await action()
            except BaseException:
                failures.append(True)
        if self.watchdog is not None:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
            self.watchdog = None
        require(not failures, "OUTPUT_FENCE_UNPROVEN")


def main():
    # No option may turn absent DTO/Authority/Registrar/output adapters into an
    # enabled service. Agent4 owns the final trusted launcher/assembly patch.
    print(
        "OUTPUT_FENCE_UNPROVEN: receiver-1 requires trusted physical installation and output isolation"
    )
    return 78
