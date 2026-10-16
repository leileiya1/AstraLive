"""Owned child process for real Go HTTP/Python journal fault injection.

The sink is an append-only local test file. No GPU, RTMP or audience claim.
"""
import asyncio
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime.app.durable_live_journal import ExecutionInbox, JournalClient, OutputGate, common, digest

async def main():
    path = Path(sys.argv[1]); cfg = json.loads(path.read_text()); cmd = cfg["command"]
    producer = cfg["runtime"]["InstanceID"]
    journal = JournalClient(cfg["url"], cfg["runtimeToken"], producer)
    directory = path.parent
    async def close():
        (directory / "sink-closed").write_text(str(time.monotonic()))
    gate = OutputGate(close)
    await gate.install(cfg["roomID"], cmd["runId"], cmd["runEpoch"], cfg["binding"], cmd["sessionId"], producer)
    # Installation closes the old connection; the deadline watchdog must close
    # it again when Backend disappears, even if no new frames arrive.
    (directory / "sink-closed").unlink(missing_ok=True)
    async def readiness(command):
        assert command["sessionId"] == cfg["sessionID"]
    async def execute(command, guard):
        guard.bind_attempt(command, 1)
        with (directory / "effects").open("a") as f:
            f.write(command["utteranceId"] + "\n"); f.flush()
        sink = dict(sinkId="test-sink", kind="RTMP_PIPE_WRITE", generationId=1,
                    firstAudioSample=0, finalAudioSampleExclusive=1, audioConsumedThroughExclusive=1,
                    finalVideoFrame=0, videoConsumedThroughFrame=0, terminal=False)
        async def write():
            with (directory / "sink-bytes").open("ab") as f: f.write(b"test-frame\n")
        await guard.handoff(command, 1, write)
        cp = common(command) | {"checkpointId": "cp_"+uuid.uuid4().hex, "eventId": "event_"+uuid.uuid4().hex,
            "attemptId": command["attemptId"], "sessionId": command["sessionId"],
            "utteranceId": command["utteranceId"], "commandId": command["commandId"], "runEpoch": command["runEpoch"],
            "producerIncarnation": producer, "producerSeq": 1, "state": "PLAYING",
            "lastKnownState": None, "reasonCode": None, "occurredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "evidence": dict(evidenceType="SINK_ADMITTED", evidenceRef="isolated-file-sink", evidenceHash=digest(sink),
                requiredSinks=["test-sink"], sinkProofs=[sink], predecessorCheckpointIds=[], audienceVisibility="UNVERIFIED")}
        del cp["requestId"]
        response = await journal.call("ConfirmCheckpoint", common(command) | {"expectedRevision": None, "checkpoint": cp})
        assert response["applied"]
        (directory / "playing").write_text("SQL checkpoint committed")
        while True:
            await guard.handoff(command, 1, write)
            await asyncio.sleep(.020)
    inbox = ExecutionInbox(journal, gate, execute, guardian_id=cfg["guardian"]["InstanceID"], readiness=readiness)
    server = server_task = None
    if cfg.get("runtimeHTTP"):
        import socket
        import uvicorn
        from fastapi import FastAPI
        from runtime.app.durable_live_journal import router
        app = FastAPI()
        app.include_router(router(inbox, cfg["controlToken"]))
        @app.middleware("http")
        async def lose_202(request, call_next):
            response = await call_next(request)
            if response.status_code == 202:
                await asyncio.sleep(.300)  # effect accepted, sender times out
            return response
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(); sock.setblocking(False)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started:
            await asyncio.sleep(.010)
        (directory / "runtime-url").write_text("http://127.0.0.1:" + str(sock.getsockname()[1]))
    else:
        await inbox.accept(cmd)
    reported = False
    while not (directory / "finish").exists():
        if inbox.last_errors and not reported:
            print("executor failure codes:", list(inbox.last_errors.values()), flush=True)
            reported = True
        if (directory / "duplicate").exists() and not (directory / "duplicate-result").exists():
            response = await inbox.accept(cmd)
            (directory / "duplicate-result").write_text(response["state"])
        await asyncio.sleep(.025)
    await inbox.close(); await journal.close()
    if server is not None:
        server.should_exit = True
        await server_task

asyncio.run(main())
