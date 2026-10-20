"""Actual AF_UNIX HTTP and OS peer credentials; Authority/Registrar mocked."""

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import sys
from dataclasses import replace

import psutil
import pytest

from output_guardian.v2.ipc import OPERATIONS, PrivateIPC, ProcessPin
from output_guardian.v2.receiver import envelope


def pin(d, role, token):
    peer = d.control if role == "CONTROL_REGISTRAR" else d.runtime
    return ProcessPin(
        peer.principal_id,
        peer.role,
        peer.incarnation,
        peer.scope,
        os.getpid(),
        os.geteuid(),
        psutil.Process().create_time(),
        hashlib.sha256(token.encode()).digest(),
    )


async def connect(d, ipc, *, control=False):
    path = ipc.directory / ("control.sock" if control else "runtime.sock")
    return await asyncio.open_unix_connection(str(path))


async def send(d, connection, path, value, token, *, raw=None):
    reader, writer = connection
    body = raw if raw is not None else d.r.wire.canonical(value)
    writer.write(
        f"POST {path} HTTP/1.1\r\nHost: guardian\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    await writer.drain()
    try:
        headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        # Closed without a reply: EOF on Darwin, RST on Linux for an unread body.
        return None
    size = int(
        next(
            line.split(b": ")[1]
            for line in headers.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
    )
    return json.loads(await reader.readexactly(size))


@pytest.mark.asyncio
async def test_real_ipc_ack_channel_media_stop(domain):
    d = domain
    token, control_token = secrets.token_hex(32), secrets.token_hex(32)
    ipc = PrivateIPC(
        d.r,
        d.ipc_dir,
        [
            pin(d, "REGISTERED_RUNTIME", token),
            pin(d, "CONTROL_REGISTRAR", control_token),
        ],
    )
    await ipc.start()
    runtime = await connect(d, ipc)
    control = await connect(d, ipc, control=True)
    try:
        ack = await send(d, runtime, "/guardian/durable-live-2/consume", d.q, token)
        assert ack["consumeAuthorized"]
        assert ack["consumption"]["channelBinding"] != d.runtime.channel_binding
        q = d.execution(ack)
        proof = await send(
            d,
            runtime,
            "/guardian/durable-live-2/renew",
            dict(q, permitId=d.q["references"]["permitId"]),
            token,
        )
        assert proof["state"] == "PROOF_UPDATED" and "consumeAuthorized" not in proof
        accepted = await send(
            d,
            runtime,
            "/guardian/durable-live-2/media",
            dict(
                q,
                permitId=d.q["references"]["permitId"],
                sequence=0,
                ptsUs=None,
                kind="audio",
                payload="AAA=",
            ),
            token,
        )
        assert accepted["accepted"]
        stopped = await send(
            d,
            control,
            "/guardian/durable-live-2/stop",
            envelope(runId=d.r.staged["runId"]),
            control_token,
        )
        assert stopped["state"] == "CLOSED_FENCED"
        assert (
            await send(
                d,
                runtime,
                "/guardian/durable-live-2/renew",
                dict(q, permitId=d.q["references"]["permitId"]),
                token,
            )
        )["code"] == "STALE_EXECUTION"
        assert d.r.gate.state == "FENCED"
    finally:
        for _, writer in (runtime, control):
            writer.close()
            await writer.wait_closed()
        await ipc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "role",
        "token",
        "pid",
        "creation",
        "incarnation",
        "scope",
        "v1",
        "duplicate",
        "unknown",
        "bool",
    ],
)
async def test_real_ipc_denies_unprovisioned_context(domain, fault):
    d = domain
    token = secrets.token_hex(32)
    record = pin(d, "REGISTERED_RUNTIME", token)
    if fault == "pid":
        record = replace(record, pid=record.pid + 99999)
    elif fault == "creation":
        record = replace(record, created=record.created - 1)
    elif fault == "incarnation":
        record = replace(record, incarnation="retired_runtime")
    elif fault == "scope":
        record = replace(record, scope=("another_tenant", "o", "r"))
    ipc = PrivateIPC(d.r, d.ipc_dir, [record])
    await ipc.start()
    connection = await connect(d, ipc, control=fault == "role")
    q, path, raw = dict(d.q), "/guardian/durable-live-2/consume", None
    if fault == "token":
        token = "wrong"
    elif fault == "v1":
        path = "/guardian/v1/bind"
    elif fault == "duplicate":
        raw = (
            b'{"contractRevision":"durable-live-2","contractRevision":"durable-live-2"}'
        )
    elif fault == "unknown":
        q["generation"] = 1
    elif fault == "bool":
        q["expectedGenerationId"] = True
    try:
        rejected = await send(d, connection, path, q, token, raw=raw)
        assert rejected is None or "code" in rejected
        assert not d.x.b.latches and d.r.gate.active is None
    finally:
        connection[1].close()
        # The same reset is stored on the transport and re-raised here.
        with contextlib.suppress(ConnectionResetError):
            await connection[1].wait_closed()
        await ipc.close()


@pytest.mark.asyncio
async def test_bearer_stolen_by_actual_other_process_denied(domain):
    d = domain
    token = secrets.token_hex(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [pin(d, "REGISTERED_RUNTIME", token)])
    await ipc.start()
    # Credential/body delivered over stdin; never in process argv or logs.
    script = """import json,socket,sys
v=json.load(sys.stdin);s=socket.socket(socket.AF_UNIX);s.connect(v['path'])
b=json.dumps(v['body']).encode();s.sendall(('POST /guardian/durable-live-2/consume HTTP/1.1\\r\\nHost: guardian\\r\\nAuthorization: Bearer '+v['token']+'\\r\\nContent-Length: '+str(len(b))+'\\r\\n\\r\\n').encode()+b)
assert s.recv(4096)==b''
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            process.communicate(
                json.dumps(
                    dict(
                        path=str(ipc.directory / "runtime.sock"), token=token, body=d.q
                    )
                ).encode()
            ),
            2,
        )
        assert process.returncode == 0, (out, err)
        assert not d.x.b.latches
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await ipc.close()


@pytest.mark.asyncio
async def test_runtime_ack_lost_and_reconnect_unknown(domain):
    d = domain
    token = secrets.token_hex(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [pin(d, "REGISTERED_RUNTIME", token)])
    await ipc.start()
    connection = await connect(d, ipc)
    try:
        # Backend/Guardian commit and ACK enqueue occur; requester abandons its
        # first response rather than reading/reusing it on a new channel.
        body = d.r.wire.canonical(d.q)
        connection[1].write(
            f"POST /guardian/durable-live-2/consume HTTP/1.1\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await connection[1].drain()
        for _ in range(100):
            if d.r.gate.active:
                break
            await asyncio.sleep(0.002)
        assert len(d.x.b.latches) == 1
        connection[1].close()
        await connection[1].wait_closed()
        await asyncio.sleep(0.02)
        assert d.r.gate.state == "UNKNOWN"
        retry = await connect(d, ipc)
        try:
            assert (
                await send(d, retry, "/guardian/durable-live-2/consume", d.q, token)
            )["code"] == "CONSUMPTION_UNKNOWN"
        finally:
            retry[1].close()
            await retry[1].wait_closed()
        assert len(d.x.b.latches) == 1 and not d.r.gate.acks
    finally:
        await ipc.close()


def test_only_frozen_guardian_routes():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "contracts/v0.5/durable-live-2/receiver-protocol.json"
    )
    frozen = {
        op["path"]: (op["operationId"], op["roles"][0])
        for op in json.loads(source.read_text())["operations"]
        if op["target"] == "GUARDIAN"
    }
    assert {path: (op, role) for path, (_, op, role) in OPERATIONS.items()} == frozen
    assert len(OPERATIONS) == 7


@pytest.mark.asyncio
async def test_real_two_channels_cannot_restore_true_ack(domain):
    d = domain
    token = secrets.token_hex(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [pin(d, "REGISTERED_RUNTIME", token)])
    await ipc.start()
    connections = [await connect(d, ipc), await connect(d, ipc)]
    try:
        replies = await asyncio.gather(
            *(
                send(d, c, "/guardian/durable-live-2/consume", d.q, token)
                for c in connections
            )
        )
        assert sum(bool(out and out.get("consumeAuthorized")) for out in replies) == 1
        assert len(d.x.b.latches) == 1
        assert d.r.gate.state == "ACTIVE_UNIT"
    finally:
        for _, writer in connections:
            writer.close()
            await writer.wait_closed()
        await ipc.close()


@pytest.mark.asyncio
async def test_actual_control_stage_signs_only_pinned_closed_install(domain):
    import base64

    d = domain
    token = secrets.token_hex(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [pin(d, "CONTROL_REGISTRAR", token)])
    await ipc.start()
    control = await connect(d, ipc, control=True)
    try:
        out = await send(
            d,
            control,
            "/guardian/durable-live-2/bootstrap/stage",
            d.x.p.transcript[0]["request"],
            token,
        )
        receipt = out["receipt"]
        unsigned = {k: v for k, v in receipt.items() if k != "signature"}
        d.x.g.key.public_key().verify(
            base64.b64decode(receipt["signature"]), d.r.wire.canonical(unsigned)
        )
        assert receipt["state"] == "CLOSED_STAGED"
        assert d.r.gate.state == "STAGED_CLOSED" and d.r.gate.active is None
    finally:
        control[1].close()
        await control[1].wait_closed()
        await ipc.close()


@pytest.mark.asyncio
async def test_real_ipc_through_cpu_decoder_to_required_sink_ranges(domain):
    import base64

    from .test_cpu import setup_cpu

    d = domain
    cpu = await setup_cpu(d)
    token, control_token = secrets.token_hex(32), secrets.token_hex(32)
    ipc = PrivateIPC(
        d.r,
        d.ipc_dir,
        [
            pin(d, "REGISTERED_RUNTIME", token),
            pin(d, "CONTROL_REGISTRAR", control_token),
        ],
    )
    await ipc.start()
    runtime, control = await connect(d, ipc), await connect(d, ipc, control=True)
    try:
        ack = await send(d, runtime, "/guardian/durable-live-2/consume", d.q, token)
        q = d.execution(ack)
        pid = cpu.process.pid
        for sequence in range(4):
            video = sequence % 2 == 1
            body = dict(
                q,
                permitId=d.q["references"]["permitId"],
                sequence=sequence,
                kind="video" if video else "audio",
                ptsUs=(sequence // 2) * 40000 if video else None,
                payload=base64.b64encode(
                    bytes([sequence + 1]) * (64 * 64 * 3 if video else 1280)
                ).decode(),
            )
            assert (
                await send(d, runtime, "/guardian/durable-live-2/media", body, token)
            )["accepted"]
        finished = await send(
            d, runtime, "/guardian/durable-live-2/unit/finish", q, token
        )
        assert finished["state"] == "LOCAL_MEDIA_DRAINED"
        assert cpu.process.pid == pid and cpu.process.is_alive()
        for proof in finished["evidence"]["sinkProofs"]:
            assert proof["audioConsumedThroughExclusive"] == 1280
            assert proof["videoConsumedThroughFrame"] == 1
        stopped = await send(
            d,
            control,
            "/guardian/durable-live-2/stop",
            envelope(runId=d.r.staged["runId"]),
            control_token,
        )
        assert stopped["state"] == "CLOSED_FENCED" and not psutil.pid_exists(pid)
    finally:
        for _, writer in (runtime, control):
            writer.close()
            await writer.wait_closed()
        await ipc.close()
        assert await cpu.close()
