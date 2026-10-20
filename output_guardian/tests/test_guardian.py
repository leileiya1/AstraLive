import asyncio
import dataclasses
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import asyncpg
import numpy as np
import pytest
from aiohttp import ClientSession, UnixConnector, web

from output_guardian.authority import PostgresAuthority
from output_guardian.model import Binding, Closed, Right, clock
from output_guardian.service import ipc_app


async def synthetic(rig, count=15):
    # 600ms of real encoded audio/video. No GPU or external services.
    for n in range(count):
        for half in range(2):
            t = np.arange(320) + (n * 2 + half) * 320
            pcm = (np.sin(t * 2 * np.pi * 440 / 16000) * 8000).astype("<i2").tobytes()
            await rig.guardian.media(
                rig.attempt, {"kind": "audio", "sequence": n * 2 + half, "payload": pcm}
            )
        rgb = bytes([n * 7 % 255, 30, 220]) * 256 * 256
        await rig.guardian.media(
            rig.attempt, {"kind": "video", "pts_us": n * 40000, "payload": rgb}
        )
        await asyncio.sleep(0.04)


@pytest.mark.asyncio
async def test_real_rtmp_full_decode_drain_stop(rig):
    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    try:
        await synthetic(rig, count=100)
        try:
            result = await rig.guardian.finish(rig.attempt)
        except Closed:
            print("DRAIN_DIAGNOSTIC", getattr(rig.guardian, "last_drain_fault", None))
            raise
        assert result["state"] == "LOCAL_MEDIA_DRAINED"
        evidence = result["evidence"][0]
        assert evidence["audioSampleRange"] == [0, 64000]
        assert evidence["decodedVideoFrames"] == 100
        assert len(evidence["videoPTSUS"]) == 100
        print("REAL_RTMP_DRAIN", json.dumps(evidence))
        await rig.guardian.stop("run")
        assert not await rig.guardian.ingest.publishers()
        assert rig.guardian.publisher.process is None
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)


@pytest.mark.asyncio
async def test_old_epoch_identity_and_permit_expiry(rig):
    await rig.activate()
    old = dataclasses.replace(
        rig.attempt, binding=dataclasses.replace(rig.binding, runEpoch=2)
    )
    with pytest.raises(Closed):
        await rig.guardian.media(
            old, {"kind": "video", "pts_us": 0, "payload": bytes(256 * 256 * 3)}
        )
    process = rig.guardian.publisher.process
    await asyncio.sleep(1)
    assert process.poll() is not None
    assert rig.guardian.right is None
    assert not await rig.guardian.ingest.publishers()
    with pytest.raises(Closed):
        await rig.guardian.renew(rig.attempt, await rig.permit())


@pytest.mark.asyncio
async def test_competing_guardian_real_sql_lock(rig):
    other = PostgresAuthority(rig.dsn, "guardian", "t", "o", "room")
    with pytest.raises(Closed):
        await other.start()
    await other.close()


@pytest.mark.asyncio
async def test_pg_connection_loss_retires_publisher(rig):
    await rig.activate()
    process = rig.guardian.publisher.process
    await rig.db.execute(
        "SELECT pg_terminate_backend($1)",
        rig.guardian.authority.connection.get_server_pid(),
    )
    await asyncio.sleep(0.4)
    assert process.poll() is not None
    assert rig.guardian.right is None
    assert not await rig.guardian.ingest.publishers()


@pytest.mark.asyncio
async def test_stop_races_delayed_renew_and_pending_install(rig):
    await rig.activate()
    original = rig.guardian.authority.permit
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        right = await original(*args)
        entered.set()
        await release.wait()
        return right

    rig.guardian.authority.permit = delayed
    renewal = asyncio.create_task(rig.guardian.renew(rig.attempt, await rig.permit()))
    await entered.wait()
    await rig.guardian.stop("run")
    release.set()
    with pytest.raises(Closed):
        await renewal
    assert rig.guardian.right is None
    assert "run" in json.loads((rig.guardian.state_dir / "stopped.json").read_text())
    with pytest.raises(Closed):
        await rig.guardian.install(
            dataclasses.replace(rig.binding, outputBindingVersion=2, runEpoch=2)
        )


@pytest.mark.asyncio
async def test_late_renew_cannot_resurrect(rig):
    await rig.activate()
    original = rig.guardian.authority.permit

    async def delayed(*args):
        right = await original(*args)
        await asyncio.sleep(0.95)
        return right

    rig.guardian.authority.permit = delayed
    with pytest.raises(Closed):
        await rig.guardian.renew(rig.attempt, await rig.permit())
    assert rig.guardian.right is None


@pytest.mark.asyncio
async def test_authenticated_ipc_scopes_and_no_management_for_runtime(rig, tmp_path):
    async with ClientSession() as unauthenticated:
        response = await unauthenticated.get(
            f"http://127.0.0.1:{rig.api_port}/v3/rtmpconns/list"
        )
        assert response.status == 401
    app = ipc_app(rig.guardian, "c" * 40, {"r" * 40: "producer", "x" * 40: "other"})
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    ipc_dir = tempfile.mkdtemp(prefix="agn-ipc-", dir="/tmp")
    path = ipc_dir + "/ipc.sock"
    await web.UnixSite(runner, path).start()
    try:
        async with ClientSession(connector=UnixConnector(path=path)) as client:
            for token in ("", "r" * 40):
                response = await client.post(
                    "http://guardian/guardian/v1/stop",
                    json={"runId": "run"},
                    headers={"Authorization": "Bearer " + token},
                )
                assert response.status == 403
            response = await client.post(
                "http://guardian/guardian/v1/renew",
                json={"attempt": rig.attempt.json(), "permitId": "p"},
                headers={"Authorization": "Bearer " + "x" * 40},
            )
            assert response.status == 403
            response = await client.post(
                "http://guardian/guardian/v1/stop",
                data='{"runId":"a","runId":"run"}',
                headers={
                    "Authorization": "Bearer " + "c" * 40,
                    "Content-Type": "application/json",
                },
            )
            assert response.status == 422
    finally:
        await runner.cleanup()
        shutil.rmtree(ipc_dir)


@pytest.mark.asyncio
async def test_every_authority_dimension_and_tombstone(rig):
    await rig.activate()
    permit = await rig.permit()
    authority = rig.guardian.authority
    for field in (
        "tenantId",
        "ownerId",
        "roomId",
        "runId",
        "sessionId",
        "producerIncarnation",
    ):
        bad = dataclasses.replace(rig.binding, **{field: "wrong"})
        with pytest.raises(Closed):
            await authority.permit(
                dataclasses.replace(rig.attempt, binding=bad), permit
            )
    for field in ("runEpoch", "outputBindingVersion"):
        with pytest.raises(Closed):
            await authority.permit(
                dataclasses.replace(
                    rig.attempt, binding=dataclasses.replace(rig.binding, **{field: 2})
                ),
                permit,
            )
    for field in ("attemptId", "utteranceId", "commandId"):
        with pytest.raises(Closed):
            await authority.permit(
                dataclasses.replace(rig.attempt, **{field: "wrong"}), permit
            )
    await rig.db.execute(
        "UPDATE dl05_runs SET stop_revision=10,desired_state='STOPPED'"
    )
    with pytest.raises(Closed):
        await authority.permit(rig.attempt, permit)


def test_strict_identity_clock_and_bool_rejection():
    data = Binding("t", "o", "room", "run", 1, "session", 1, "producer").json()
    for bad in (True, 0, 1.0):
        with pytest.raises(Closed):
            Binding.parse(data | {"runEpoch": bad})
    with pytest.raises(Closed):
        Right.from_remaining("p", 0.05, clock(), time.monotonic())


@pytest.mark.asyncio
async def test_two_physical_publishers_and_old_credentials_reconnect(rig, tmp_path):
    from output_guardian.process import Publisher

    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    retained = Publisher(tmp_path / "retained")
    retained.state_dir.mkdir(mode=0o700)
    old_secret = rig.guardian.secret
    try:
        await synthetic(rig, count=60)
        assert len(await rig.guardian.ingest.publishers()) == 1
        config = rig.guardian.media_config | {
            "url": f"rtmp://127.0.0.1:{rig.rtmp_port}/room?user=guardian&pass={old_secret}",
            "deadline": clock() + 0.7,
            "monotonic_deadline": time.monotonic() + 0.7,
        }
        with pytest.raises(Closed):
            await retained.start(config)
            await retained.call(
                {"op": "video", "pts_us": 0, "payload": bytes(256 * 256 * 3)}
            )
        assert len(await rig.guardian.ingest.publishers()) == 1
        await rig.db.execute(
            "UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()"
        )
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        await asyncio.sleep(0.35)
        assert rig.guardian.right is None
        assert not await rig.guardian.ingest.publishers()
        await retained.abort()
        # The same old Runtime/publisher reconnects after SQL lease expiry; DB refusal
        # alone is not the evidence: the real publishing server denies it.
        with pytest.raises(Closed):
            await retained.start(
                config
                | {
                    "deadline": clock() + 0.7,
                    "monotonic_deadline": time.monotonic() + 0.7,
                }
            )
            await retained.call(
                {"op": "video", "pts_us": 0, "payload": bytes(256 * 256 * 3)}
            )
        assert not await rig.guardian.ingest.publishers()
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        await retained.abort()


@pytest.mark.asyncio
async def test_retained_real_ffmpeg_physically_kicked_before_activation(rig):
    # A legacy FFmpeg with no secret is admitted ONLY by the isolated test
    # server before Guardian takeover. The production auth callback is restored
    # before install. No credentials are placed in FFmpeg argv.
    original = rig.guardian.auth

    async def legacy(packet):
        if packet.get("action") == "publish" and packet.get("path") == "room":
            return True
        return await original(packet)

    rig.guardian.auth = legacy
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=256x256:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=sample_rate=16000",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-c:a",
            "aac",
            "-f",
            "flv",
            f"rtmp://127.0.0.1:{rig.rtmp_port}/room",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if await rig.guardian.ingest.publishers():
                break
            await asyncio.sleep(0.05)
        assert await rig.guardian.ingest.publishers()
        process.send_signal(signal.SIGSTOP)
        rig.guardian.auth = original
        await rig.guardian.install(rig.binding)
        assert process.poll() is None  # Still alive; closure is server-proven.
        assert not await rig.guardian.ingest.publishers()
        process.send_signal(signal.SIGCONT)
        await asyncio.sleep(0.1)
        assert not await rig.guardian.ingest.publishers()
    finally:
        rig.guardian.auth = original
        process.kill()
        process.wait(timeout=2)


@pytest.mark.asyncio
async def test_exclusivity_loss_closes_admission(rig):
    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    try:
        await synthetic(rig, count=60)
        connections = await rig.guardian.ingest.publishers()
        assert len(connections) == 1
        await rig.guardian.ingest.request(
            "POST", "/v3/rtmpconns/kick/" + connections[0]["id"]
        )
        await asyncio.sleep(0.25)
        assert rig.guardian.right is None
        assert rig.guardian.publisher.process is None
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)


@pytest.mark.asyncio
async def test_webrtc_real_peer_closed_on_expiry(rig):
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

    await rig.activate(webrtc=True)
    renewal = asyncio.create_task(rig.renew_forever())
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    peer.addTransceiver("audio", direction="recvonly")
    peer.addTransceiver("video", direction="recvonly")
    tracks, received = {}, {"audio": 0, "video": 0}
    readers = []

    @peer.on("track")
    def on_track(track):
        tracks[track.kind] = track

    try:
        await peer.setLocalDescription(await peer.createOffer())
        answer = await rig.guardian.offer(rig.attempt, peer.localDescription.sdp)
        await peer.setRemoteDescription(RTCSessionDescription(answer["sdp"], "answer"))
        for _ in range(100):
            if peer.connectionState == "connected":
                break
            await asyncio.sleep(0.02)
        assert peer.connectionState == "connected"

        async def receive(track):
            while True:
                await track.recv()
                received[track.kind] += 1

        readers = [asyncio.create_task(receive(t)) for t in tracks.values()]
        await synthetic(rig, count=10)
        await asyncio.sleep(0.15)
        assert received["audio"] > 0 and received["video"] > 0
        output = rig.guardian.web
        old_peers = tuple(output.peers)
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        await asyncio.sleep(1)
        assert rig.guardian.right is None
        assert all(p.connection.connectionState == "closed" for p in old_peers)
        assert not await rig.guardian.ingest.publishers()
        print("REAL_WEBRTC_DECODE", received, "all Guardian peers closed")
    finally:
        renewal.cancel()
        for task in readers:
            task.cancel()
        await asyncio.gather(renewal, *readers, return_exceptions=True)
        await peer.close()


@pytest.mark.asyncio
async def test_short_segment_and_missing_tail_remain_unknown(rig):
    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    try:
        await synthetic(rig, count=10)
        with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
            await rig.guardian.finish(rig.attempt)
        assert rig.guardian.right is None
        assert not await rig.guardian.ingest.publishers()
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kill_round", [0, 1, 2])
async def test_sigkill_supervisor_restart_and_closed_admission(rig, kill_round):
    import httpx
    import psutil
    from conftest import port

    await rig.guardian.close()
    rig.ingest_process.terminate()
    rig.ingest_process.wait(timeout=3)
    home = Path(tempfile.mkdtemp(prefix="agn-crash-", dir="/tmp"))
    state = home / "state"
    state.mkdir(mode=0o700)
    auth_port = port()
    config_mtx = home / "mediamtx.yml"
    config_mtx.write_text(
        rig.mtx_config.read_text().replace(
            str(rig.auth_port) + "/auth", str(auth_port) + "/auth"
        )
    )

    def protected(name, value):
        path = home / name
        path.write_text(value)
        path.chmod(0o600)
        return str(path)

    control, runtime_token = (
        "control_" + uuid.uuid4().hex,
        "runtime_" + uuid.uuid4().hex,
    )
    config = {
        "dsnFile": protected("dsn", rig.dsn),
        "guardianId": "guardian",
        "tenantId": "t",
        "ownerId": "o",
        "roomId": "room",
        "apiURL": f"http://127.0.0.1:{rig.api_port}",
        "rtmpURL": f"rtmp://127.0.0.1:{rig.rtmp_port}",
        "path": "room",
        "authPort": auth_port,
        "stateDir": str(state),
        "recordingDir": str(rig.guardian.recording_dir),
        "socketPath": str(home / "ipc.sock"),
        "controlTokenFile": protected("control", control),
        "producers": [
            {
                "producerIncarnation": "producer",
                "tokenFile": protected("runtime", runtime_token),
            }
        ],
        "mediaMTXBinary": rig.mtx_binary,
        "mediaMTXConfig": str(config_mtx),
    }
    config_path = protected("config.json", json.dumps(config))
    processes = []

    def launch():
        p = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "output_guardian.supervisor",
                "--config",
                config_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        processes.append(p)
        return p

    async def ready(p):
        for _ in range(150):
            assert p.poll() is None, "fail-closed daemon exited before IPC readiness"
            try:
                _, writer = await asyncio.open_unix_connection(config["socketPath"])
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.02)
        raise AssertionError("IPC unavailable")

    supervisor = launch()
    try:
        await ready(supervisor)
        async with httpx.AsyncClient(
            base_url="http://guardian",
            transport=httpx.AsyncHTTPTransport(uds=config["socketPath"]),
            headers={"Authorization": "Bearer " + control},
            timeout=2,
        ) as client:
            response = await client.post(
                "/guardian/v1/install", json={"binding": rig.binding.json()}
            )
            assert response.status_code == 200
            await rig.activate_sql()
            response = await client.post(
                "/guardian/v1/bind",
                json={"attempt": rig.attempt.json(), "permitId": await rig.permit()},
            )
            assert response.status_code == 200, response.json()
            child_record = json.loads((state / "publisher.json").read_text())
            publisher = psutil.Process(child_record["pid"])
            guardian_process = next(
                p
                for p in psutil.Process(supervisor.pid).children()
                if p.name().startswith("python")
            )
            # Real SIGKILL of the Guardian, not a synthetic close callback.
            guardian_process.kill()
            for _ in range(100):
                if supervisor.poll() is not None and (
                    not publisher.is_running()
                    or publisher.status() == psutil.STATUS_ZOMBIE
                ):
                    break
                await asyncio.sleep(0.02)
            if supervisor.poll() != 70:
                print("SUPERVISOR_FAILURE", supervisor.stderr.read().decode())
            assert supervisor.poll() == 70
            assert (
                not publisher.is_running() or publisher.status() == psutil.STATUS_ZOMBIE
            )
            supervisor = launch()
            # The stale socket is not a readiness signal. Wait for the old
            # socket inode to be replaced by the restarted, closed service.
            await asyncio.sleep(0.3)
            await ready(supervisor)
            async with httpx.AsyncClient(
                base_url="http://guardian",
                transport=httpx.AsyncHTTPTransport(uds=config["socketPath"]),
                headers={"Authorization": "Bearer " + runtime_token},
                timeout=2,
            ) as reconnected:
                response = await reconnected.post(
                    "/guardian/v1/renew",
                    json={
                        "attempt": rig.attempt.json(),
                        "permitId": await rig.permit(),
                    },
                )
                assert response.status_code == 409
            assert not (state / "publisher.json").exists()
            assert not (state / "receiver.json").exists()
            print(
                "REAL_SIGKILL_RESTART",
                "supervisor exit=70, owned publisher dead, restart closed, old Runtime rejected",
            )
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            await asyncio.to_thread(process.wait, 3)
        shutil.rmtree(home)


@pytest.mark.asyncio
async def test_install_stop_concurrency(rig):
    entered, release = asyncio.Event(), asyncio.Event()
    original = rig.guardian.authority.pending

    async def pending(binding):
        await original(binding)
        entered.set()
        await release.wait()

    rig.guardian.authority.pending = pending
    install = asyncio.create_task(rig.guardian.install(rig.binding))
    await entered.wait()
    await rig.guardian.stop("run")
    release.set()
    with pytest.raises(Closed):
        await install
    assert rig.guardian.binding is None
    assert rig.guardian.right is None


@pytest.mark.asyncio
async def test_readonly_database_role_and_startup_db_unavailable(rig):
    role = "guardian_reader_" + uuid.uuid4().hex
    await rig.db.execute("CREATE ROLE " + role + " LOGIN")
    try:
        await rig.db.execute(
            "GRANT SELECT ON dl05_runs,dl05_run_terms,dl05_run_leases,dl05_room_outputs,dl05_output_permits,dl05_attempts,dl05_runtime_inbox,dl05_run_slots TO "
            + role
        )
        await rig.guardian.authority.close()
        authority = PostgresAuthority(
            rig.dsn.replace("guardian_admin@", role + "@"), "guardian", "t", "o", "room"
        )
        await authority.start()
        try:
            await authority.pending(rig.binding)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await authority.connection.execute(
                    "UPDATE dl05_runs SET stop_revision=1"
                )
        finally:
            await authority.close()
        from conftest import port

        broken = PostgresAuthority(
            f"postgresql://nobody@127.0.0.1:{port()}/guardian_test_missing",
            "guardian",
            "t",
            "o",
            "room",
        )
        with pytest.raises(OSError):
            await broken.start()
        assert broken.connection is None
        assert rig.guardian.right is None
    finally:
        await rig.db.execute("REASSIGN OWNED BY " + role + " TO guardian_admin")
        await rig.db.execute("DROP OWNED BY " + role)
        await rig.db.execute("DROP ROLE " + role)


@pytest.mark.asyncio
async def test_delayed_old_writer_cannot_reach_replacement_child(rig):
    await rig.activate()
    publisher = rig.guardian.publisher
    await publisher.lock.acquire()
    old_process = publisher.process
    old = asyncio.create_task(
        publisher.call({"op": "video", "pts_us": 0, "payload": bytes(256 * 256 * 3)})
    )
    await asyncio.sleep(0.01)
    await publisher.abort()
    # Before releasing the queue, a replacement process is allocated. The
    # pending old writer must compare the actual process/pipe it captured.
    config = rig.guardian.media_config | {
        "url": f"rtmp://127.0.0.1:{rig.rtmp_port}/room?user=guardian&pass={rig.guardian.secret}",
        "deadline": clock() + 0.7,
        "monotonic_deadline": time.monotonic() + 0.7,
        "identity": rig.attempt.json(),
    }
    replacement = asyncio.create_task(publisher.start(config))
    await asyncio.sleep(0.02)
    assert publisher.process is not old_process
    publisher.lock.release()
    with pytest.raises(Closed):
        await old
    try:
        await replacement
    except Closed:
        pass  # Retired room authorization may fail closed; stale input cannot pass.
    assert publisher.process is None or publisher.process is not old_process


@pytest.mark.asyncio
async def test_runtime_adapter_real_unix_ipc_and_decoded_drain(rig):
    from runtime.app.guardian_media import GuardianMediaOutput
    from runtime.app.providers import AudioChunk, VideoFrame

    await rig.activate()
    home = tempfile.mkdtemp(prefix="agn-adapter-", dir="/tmp")
    socket_path = home + "/guardian.sock"
    runner = web.AppRunner(
        ipc_app(rig.guardian, "c" * 40, {"r" * 40: "producer"}), access_log=None
    )
    await runner.setup()
    await web.UnixSite(runner, socket_path).start()
    adapter = GuardianMediaOutput(socket_path, "r" * 40, rig.attempt.json())
    await adapter.start()

    async def renew():
        while True:
            await asyncio.sleep(0.12)
            await adapter.renew(await rig.permit())

    renewal = asyncio.create_task(renew())
    try:
        for n in range(100):
            for half in range(2):
                t = np.arange(320) + (n * 2 + half) * 320
                pcm = (
                    (np.sin(t * 2 * np.pi * 440 / 16000) * 8000).astype("<i2").tobytes()
                )
                await adapter.push_audio(AudioChunk(1, n * 2 + half, pcm))
            await adapter.push_video(
                VideoFrame(
                    1, n * 40000, 256, 256, bytes([n * 7 % 255, 30, 220]) * 256 * 256
                )
            )
            await asyncio.sleep(0.04)
        try:
            await adapter.drain(1)
        except Exception:
            print(
                "ADAPTER_DRAIN_DIAGNOSTIC",
                getattr(rig.guardian, "last_drain_fault", None),
                getattr(rig.guardian, "last_drain_stats", None),
            )
            raise
        assert adapter.last_drain["state"] == "LOCAL_MEDIA_DRAINED"
        assert adapter.last_drain["evidence"][0]["decodedVideoFrames"] == 100
        print(
            "REAL_UNIX_RUNTIME_ADAPTER",
            "PCM/RGB -> IPC -> RTMP -> independent decoded range receipt",
        )
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        await adapter.stop()
        await runner.cleanup()
        shutil.rmtree(home)


@pytest.mark.asyncio
async def test_nonzero_source_pts_and_attempt_replay_fail_closed(rig):
    await rig.activate()
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        await rig.guardian.media(
            rig.attempt,
            {"kind": "video", "pts_us": 40000, "payload": bytes(256 * 256 * 3)},
        )
    with pytest.raises(Closed):
        await rig.guardian.bind(
            dataclasses.replace(rig.attempt, generation=2), await rig.permit()
        )
