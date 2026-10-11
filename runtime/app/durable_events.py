"""Disk-backed event spool; PostgreSQL ACK is the only deletion boundary.

This local SQLite WAL is a retry journal, not the authoritative command/receipt database.
Use a private persistent volume; losing it leaves STARTED/UNKNOWN proof in PostgreSQL.
"""
import asyncio
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import time
from .durability_client import JournalError, canonical


class DurableEventPublisher:
    def __init__(self, journal, directory, max_pending=10000):
        self.journal = journal
        path = Path(directory)
        if not path.is_absolute():
            raise ValueError("Durability spool must be an absolute private path")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        st = path.lstat()
        if path.is_symlink() or not path.is_dir() or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError("Durability spool directory must be private and owned")
        dbpath = path / "events.sqlite3"
        if dbpath.is_symlink():
            raise ValueError("Durability spool cannot be a symlink")
        if dbpath.exists() and (dbpath.stat().st_uid != os.getuid() or dbpath.stat().st_mode & 0o077):
            raise ValueError("Invalid event journal ownership")
        # Create privately before SQLite opens WAL sidecars (private parent protects them).
        fd = os.open(dbpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(dbpath)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS pending(event_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0, disposition TEXT NOT NULL DEFAULT 'PENDING');
          CREATE TABLE IF NOT EXISTS identities(event_id TEXT PRIMARY KEY, legacy_hash TEXT NOT NULL, metadata TEXT NOT NULL, acked INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS sequence(id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL);
          INSERT OR IGNORE INTO sequence VALUES(1,0);
        """)
        # Upgrade pre-Continuity journals in place; legacy packets retain their route.
        if "endpoint" not in {row[1] for row in self.db.execute("PRAGMA table_info(pending)")}:
            self.db.execute("ALTER TABLE pending ADD COLUMN endpoint TEXT NOT NULL DEFAULT '/events'")
        self.db.commit()
        self.journal.timeline_spool = self
        self.max_pending = max_pending
        self.bindings = {}
        self.utterances = {}
        self.attempts = {}
        self.media_bindings = {}
        self.run_commands = {}
        self.task = None
        self.wake = asyncio.Event()

    def bind(self, command, receipt=None):
        sid, kind = command["sessionId"], command["commandType"]
        self.bindings[(sid, command["traceId"])] = command
        if receipt and receipt.get("attemptId"):
            self.attempts[command["commandId"]] = receipt["attemptId"]
        if kind == "SPEAK":
            self.utterances[(sid, command["payload"]["utteranceId"])] = command
        else:
            self.run_commands[(sid, kind)] = command

    def command_for(self, event):
        sid, kind, uid = event["sessionId"], event["eventType"], event["utteranceId"]
        if uid:
            command = self.utterances.get((sid, uid))
        elif kind in ("SESSION_STOPPING", "SESSION_ENDED"):
            command = self.run_commands.get((sid, "STOP_SESSION")) or self.bindings.get((sid, event["traceId"]))
        elif kind == "SESSION_STARTED":
            command = self.run_commands.get((sid, "START_SESSION"))
        else:
            command = self.bindings.get((sid, event["traceId"]))
        if not command:
            raise JournalError("RECOVERY_UNKNOWN", 409)
        return command

    async def publish(self, event):
        command = self.command_for(event)
        legacy_hash = hashlib.sha256(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        old = self.db.execute("SELECT legacy_hash,metadata,acked FROM identities WHERE event_id=?", (event["eventId"],)).fetchone()
        if old:
            metadata = json.loads(old[1])
            if old[0] != legacy_hash or metadata["commandId"] != command["commandId"] or metadata["runEpoch"] != command["runEpoch"]:
                raise JournalError("COMMAND_CONFLICT", 409)
            if old[2]:
                return
        count = self.db.execute("SELECT count(*) FROM pending").fetchone()[0]
        if not old and count >= self.max_pending:
            raise JournalError("DEPENDENCY_UNAVAILABLE")
        # Commit BEFORE returning to the worker or doing the next physical effect.
        with self.db:
            if not old:
                sequence = self.db.execute("UPDATE sequence SET value=value+1 WHERE id=1 RETURNING value").fetchone()[0]
                metadata = {"schemaVersion": "0.5", "eventId": event["eventId"], "sessionId": event["sessionId"],
                    "runEpoch": command["runEpoch"], "producerIncarnation": self.journal.incarnation, "producerSeq": sequence,
                    "commandId": command["commandId"], "traceId": event["traceId"], "occurredAt": event["occurredAt"],
                    "eventType": event["eventType"], "source": "AI_RUNTIME"}
                if command["commandId"] in self.attempts:
                    metadata["attemptId"] = self.attempts[command["commandId"]]
                metadata.update(self.media_bindings.get(command["commandId"], {}))
                self.db.execute("INSERT INTO identities(event_id,legacy_hash,metadata) VALUES(?,?,?)", (event["eventId"], legacy_hash, json.dumps(metadata, ensure_ascii=False)))
            value = dict(metadata, payload={"legacy": event})
            self.db.execute("INSERT OR IGNORE INTO pending(event_id,envelope) VALUES(?,?)", (event["eventId"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
        self.wake.set()

    async def begin_media(self, sid, item, floor):
        command = self.utterances.get((sid, item.utteranceId))
        if not command:
            raise JournalError("RECOVERY_UNKNOWN", 409)
        result = await self.journal.request("POST", "/media-start", {"sessionId": sid, "commandId": command["commandId"], "producerIncarnation": self.journal.incarnation, "generationFloor": floor})
        self.media_bindings[command["commandId"]] = {"generationId": result["generationId"], "timelineEpoch": result["run"]["timelineEpoch"]}
        return result["generationId"]

    def stage_timeline(self, value):
        """Fsync the immutable observation before HTTP. This never dispatches media."""
        try:
            core = {key: value[key] for key in ("operation", "command", "proof")}
            raw_core = canonical(core)
            event_id = "timeline_" + hashlib.sha256(canonical({"commandId": value["command"]["commandId"], "operation": value["operation"]})).hexdigest()
            digest = hashlib.sha256(raw_core).hexdigest()
        except (KeyError, ValueError, TypeError):
            raise JournalError("COMMAND_CONFLICT", 409) from None
        old = self.db.execute("SELECT legacy_hash,metadata FROM identities WHERE event_id=?", (event_id,)).fetchone()
        if old and old[0] != digest:
            raise JournalError("COMMAND_CONFLICT", 409)
        row = self.db.execute("SELECT envelope,disposition FROM pending WHERE event_id=?", (event_id,)).fetchone()
        if row:
            if row[1] != "PENDING":
                raise JournalError("RECOVERY_UNKNOWN", 409)
            return event_id, json.loads(row[0])
        if self.db.execute("SELECT count(*) FROM pending").fetchone()[0] >= self.max_pending:
            raise JournalError()
        packet = dict(core, producerIncarnation=value["producerIncarnation"])
        # A restarted sender preserves the executor incarnation that produced this proof.
        if old:
            packet["producerIncarnation"] = json.loads(old[1])["producerIncarnation"]
        metadata = {"endpoint": "/timeline-record", "producerIncarnation": packet["producerIncarnation"]}
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO identities(event_id,legacy_hash,metadata) VALUES(?,?,?)", (event_id, digest, json.dumps(metadata)))
            self.db.execute("UPDATE identities SET acked=0 WHERE event_id=?", (event_id,))
            self.db.execute("INSERT INTO pending(event_id,envelope,endpoint) VALUES(?,?,'/timeline-record')", (event_id, canonical(packet).decode("utf-8")))
        # Never return a cached ACK: every explicit record still checks current Go authority.
        return event_id, packet

    def _failed(self, event_id, attempts, exc):
        disposition = "CONFLICT" if exc.code == "COMMAND_CONFLICT" else "PENDING"
        if exc.code in {"LEASE_LOST", "RUN_SEALED", "STALE_RUN_EPOCH"}:
            disposition = "FENCED"
        with self.db:
            self.db.execute("UPDATE pending SET attempts=attempts+1,next_at=?,disposition=? WHERE event_id=?", (time.time() + min(30, .25 * 2 ** min(attempts, 7)), disposition, event_id))

    async def _deliver(self, event_id, endpoint, packet, attempts):
        try:
            result = await self.journal.request("POST", endpoint, packet)
            if endpoint == "/timeline-record" and (not isinstance(result, dict) or result.get("durable") is not True):
                raise JournalError("RECOVERY_UNKNOWN", 409)
        except JournalError as exc:
            self._failed(event_id, attempts, exc)
            raise
        with self.db:
            self.db.execute("DELETE FROM pending WHERE event_id=?", (event_id,))
            self.db.execute("UPDATE identities SET acked=1 WHERE event_id=?", (event_id,))
        return result

    async def record_timeline(self, value):
        event_id, packet = self.stage_timeline(value)
        row = self.db.execute("SELECT attempts FROM pending WHERE event_id=?", (event_id,)).fetchone()
        try:
            return await self._deliver(event_id, "/timeline-record", packet, row[0])
        finally:
            self.wake.set()

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run(), name="durable-event-spool")

    async def flush_once(self):
        row = self.db.execute("SELECT event_id,envelope,attempts,endpoint FROM pending WHERE disposition='PENDING' AND next_at<=? ORDER BY rowid LIMIT 1", (time.time(),)).fetchone()
        if not row:
            return False
        event_id, raw, attempts, endpoint = row
        try:
            await self._deliver(event_id, endpoint, json.loads(raw), attempts)
        except JournalError:
            return False
        return True

    async def run(self):
        while True:
            if await self.flush_once():
                continue
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), .25)
            except asyncio.TimeoutError:
                pass

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if getattr(self.journal, "timeline_spool", None) is self:
            del self.journal.timeline_spool
        self.db.close()
