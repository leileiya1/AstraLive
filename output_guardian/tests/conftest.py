"""Dedicated loopback PG + MediaMTX. Never connects to workspace services."""

import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from aiohttp import web

from output_guardian.authority import PostgresAuthority
from output_guardian.ingest import Ingest
from output_guardian.model import Attempt, Binding
from output_guardian.service import Guardian, auth_app

ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_url():
    binary = Path(
        os.environ.get("GUARDIAN_TEST_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")
    )
    if not (binary / "initdb").exists():
        pytest.fail("dedicated PostgreSQL binaries required; set GUARDIAN_TEST_PG_BIN")
    home = Path(tempfile.mkdtemp(prefix="agn-pg-", dir="/tmp"))
    listen = port()
    subprocess.run(
        [
            str(binary / "initdb"),
            "-D",
            str(home / "data"),
            "-A",
            "trust",
            "-U",
            "guardian_admin",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    log = (home / "postgres.log").open("w")
    process = subprocess.Popen(
        [
            str(binary / "postgres"),
            "-D",
            str(home / "data"),
            "-h",
            "127.0.0.1",
            "-p",
            str(listen),
            "-k",
            str(home),
        ],
        stdout=log,
        stderr=log,
    )
    try:
        for _ in range(200):
            if (
                subprocess.run(
                    [str(binary / "pg_isready"), "-h", "127.0.0.1", "-p", str(listen)],
                    stdout=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.01)
        yield f"postgresql://guardian_admin@127.0.0.1:{listen}/postgres"
    finally:
        process.send_signal(2)
        process.wait(timeout=5)
        log.close()
        shutil.rmtree(home)


class Rig:
    async def permit(self):
        permit_id = "p_" + uuid.uuid4().hex
        await self.db.execute(
            """INSERT INTO dl05_output_permits
          (tenant_id,owner_id,permit_id,run_id,session_id,run_epoch,lease_version,producer_incarnation,
           guardian_id,issued_at,expires_at,fence_proof_ref,room_id,output_binding_version)
          VALUES ('t','o',$1,'run','session',1,1,'producer','guardian',clock_timestamp(),clock_timestamp()+interval '900 milliseconds','proof','room',1)""",
            permit_id,
        )
        return permit_id

    async def activate(self, webrtc=False):
        self.guardian.webrtc_enabled = webrtc
        proof = await self.guardian.install(self.binding)
        assert proof["state"] == "CLOSED_FENCED"
        await self.activate_sql()
        await self.guardian.bind(self.attempt, await self.permit())

    async def activate_sql(self):
        await self.db.execute("""
          UPDATE dl05_runs SET status='LIVE';
          UPDATE dl05_run_terms SET phase='ACTIVE',guardian_id='guardian',output_fence_proof='proof';
          UPDATE dl05_run_leases SET phase='ACTIVE';
          INSERT INTO dl05_room_outputs (tenant_id,owner_id,room_id,active_run_id,output_binding_version,guardian_id,expires_at,fence_proof_ref)
            VALUES ('t','o','room','run',1,'guardian',clock_timestamp(),'proof');
          INSERT INTO dl05_output_bindings VALUES ('room',1,'t','o','run','guardian','proof');
        """)

    async def renew_forever(self):
        while True:
            await asyncio.sleep(0.12)
            await self.guardian.renew(self.attempt, await self.permit())


@pytest_asyncio.fixture
async def rig(pg_url, tmp_path):
    admin = await asyncpg.connect(pg_url)
    name = "guardian_test_" + uuid.uuid4().hex
    await admin.execute("CREATE DATABASE " + name)
    dsn = pg_url.rsplit("/", 1)[0] + "/" + name
    db = await asyncpg.connect(dsn)
    for migration in sorted((ROOT / "backend/db/migrations").glob("*.sql")):
        await db.execute(migration.read_text())
    await db.execute("""
      INSERT INTO config_principals VALUES ('t','o');
      INSERT INTO avatars(id,name,engine) VALUES ('avatar','test','MOCK');
      INSERT INTO voices(id,name,provider,provider_voice_id) VALUES ('voice','test','mock','test');
      INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES ('room','test','avatar','voice','test');
      INSERT INTO live_sessions(id,room_id,status) VALUES ('session','room','LIVE');
      INSERT INTO resource_owners VALUES ('room','room','t','o'),('session','session','t','o');
      INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at)
       VALUES ('session','t','o','binding','{}','{}',clock_timestamp()+interval '1 hour');
      INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy,run_epoch,current_session_id)
       VALUES ('t','o','run','room','PREPARING','LIVE','MANUAL_ON_UNKNOWN',1,'session');
      INSERT INTO dl05_run_terms(tenant_id,owner_id,run_id,run_epoch,lease_owner,phase,previous_epoch,required_sinks,producer_incarnation)
       VALUES ('t','o','run',1,'backend','PENDING_INSTALL',0,'["rtmp"]','producer');
      INSERT INTO dl05_run_sessions(tenant_id,owner_id,run_session_id,run_id,session_id,binding_id,introduced_epoch)
       VALUES ('t','o','rs','run','session','binding',1);
      INSERT INTO dl05_run_leases(tenant_id,owner_id,run_id,lease_owner,lease_expires_at,fencing_token,run_epoch,lease_version,phase)
       VALUES ('t','o','run','backend',clock_timestamp()+interval '60 seconds',1,1,1,'PENDING_INSTALL');
      INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES ('utterance','session','SCRIPT','test',1,'NONE','trace');
      INSERT INTO dl05_turns(tenant_id,owner_id,turn_id,run_id,turn_type,priority,state,scheduled_at,input_text,idempotency_key,document)
       VALUES ('t','o','turn','run','OPERATOR',1,'PLAYING',clock_timestamp(),'test','key','{}');
      BEGIN;
      SET CONSTRAINTS ALL DEFERRED;
      INSERT INTO dl05_attempts(tenant_id,owner_id,attempt_id,run_id,turn_id,session_id,run_epoch,utterance_id,command_id,attempt_number,executor_incarnation,last_checkpoint,required_sinks,document)
       VALUES ('t','o','attempt','run','turn','session',1,'utterance','command',1,'producer','PLAYING','["rtmp"]','{}');
      INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status)
       VALUES ('t','o','intent','run','session','utterance','command','attempt','turn','key',1,'EXECUTE_TURN',repeat('a',64),jsonb_build_object('tenantId','t','ownerId','o','runId','run','commandId','command','intentId','intent','sessionId','session','operation','EXECUTE_TURN','requestHash',repeat('a',64),'runEpoch',1,'attemptId','attempt','turnId','turn','utteranceId','utterance'),'ACCEPTED');
      INSERT INTO dl05_runtime_inbox(tenant_id,owner_id,command_id,run_id,attempt_id,run_epoch,request_hash,status,receipt_id,producer_incarnation,started_at)
       VALUES ('t','o','command','run','attempt',1,repeat('a',64),'STARTED','receipt','producer',clock_timestamp());
      INSERT INTO dl05_run_slots(tenant_id,owner_id,run_id,active_attempt_id) VALUES ('t','o','run','attempt');
      COMMIT;
    """)
    r = Rig()
    r.db, r.dsn = db, dsn
    r.binding = Binding("t", "o", "room", "run", 1, "session", 1, "producer")
    r.attempt = Attempt(r.binding, "attempt", "utterance", 1, "command")
    r.rtmp_port, r.api_port, r.auth_port = port(), port(), port()
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    r.guardian = Guardian(
        PostgresAuthority(dsn, "guardian", "t", "o", "room"),
        Ingest(f"http://127.0.0.1:{r.api_port}", "room"),
        tmp_path / "state",
        recordings,
        rtmp_url=f"rtmp://127.0.0.1:{r.rtmp_port}",
        path="room",
    )
    runner = web.AppRunner(auth_app(r.guardian), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", r.auth_port).start()
    config = tmp_path / "mediamtx.yml"
    config.write_text(f"""logLevel: error
rtmpAddress: 127.0.0.1:{r.rtmp_port}
api: yes
apiAddress: 127.0.0.1:{r.api_port}
rtsp: no
hls: no
webrtc: no
srt: no
playback: no
moq: no
authMethod: http
authHTTPAddress: http://127.0.0.1:{r.auth_port}/auth
authHTTPExclude: []
pathDefaults:
  overridePublisher: false
  record: true
  recordPath: {recordings}/%path/%Y-%m-%d_%H-%M-%S-%f
  recordFormat: fmp4
  recordPartDuration: 100ms
  recordSegmentDuration: 1h
paths:
  room:
""")
    binary = os.environ.get(
        "GUARDIAN_TEST_MEDIAMTX", "/tmp/astralive-guardian-tools/mediamtx"
    )
    if not Path(binary).exists():
        pytest.fail("set GUARDIAN_TEST_MEDIAMTX to a dedicated MediaMTX v1.21.1 binary")
    r.mtx_config, r.mtx_binary = config, binary
    r.ingest_process = subprocess.Popen(
        [binary, str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    for _ in range(100):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", r.api_port)
            writer.close()
            await writer.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.02)
    try:
        await r.guardian.start()
        yield r
    finally:
        await r.guardian.close()
        r.ingest_process.terminate()
        r.ingest_process.wait(timeout=3)
        await runner.cleanup()
        await db.close()
        await admin.execute("DROP DATABASE " + name + " WITH (FORCE)")
        await admin.close()
