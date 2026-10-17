"""Read-only view of Agent 2's SQL authority. Never accepts a producer's TTL.

One session advisory lock per Room; the connection is never transparently
replaced. Connection loss retires this guardian process. No migration or SQL
business write is made here. All queries are outside frame delivery.
"""

import asyncio
import time

import asyncpg

from .model import Closed, Right, clock


class PostgresAuthority:
    def __init__(self, dsn, guardian_id, tenant, owner, room, timeout=0.2):
        self.dsn, self.guardian_id = dsn, guardian_id
        self.scope = (tenant, owner, room)
        self.timeout = timeout
        self.connection = None
        self.lock = asyncio.Lock()

    async def start(self):
        self.connection = await asyncpg.connect(
            self.dsn, timeout=2, command_timeout=self.timeout
        )
        owned = await self.connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1,50505))", self.scope[2]
        )
        if not owned:
            await self.close()
            raise Closed()

    def scope_check(self, b):
        if (b.tenantId, b.ownerId, b.roomId) != self.scope:
            raise Closed("FORBIDDEN")

    async def query(self, sql, *args):
        async with self.lock:
            if self.connection is None or self.connection.is_closed():
                raise Closed("DEPENDENCY_UNAVAILABLE")
            try:
                return await asyncio.wait_for(
                    self.connection.fetchrow(sql, *args), self.timeout
                )
            except Exception:
                raise Closed("DEPENDENCY_UNAVAILABLE") from None

    async def pending(self, b):
        self.scope_check(b)
        row = await self.query(
            """
          SELECT r.run_id FROM dl05_runs r
          JOIN dl05_run_terms t ON t.run_id=r.run_id AND t.run_epoch=r.run_epoch
          JOIN dl05_run_leases l ON l.run_id=r.run_id AND l.run_epoch=r.run_epoch
          LEFT JOIN dl05_room_outputs o ON o.room_id=r.room_id
          WHERE r.tenant_id=$1 AND r.owner_id=$2 AND r.room_id=$3 AND r.run_id=$4
          AND r.run_epoch=$5 AND r.current_session_id=$6 AND t.producer_incarnation=$7
          AND t.phase='PENDING_INSTALL' AND l.phase='PENDING_INSTALL'
          AND l.lease_expires_at>clock_timestamp() AND r.stop_revision=0
          AND r.desired_state='LIVE' AND COALESCE(o.output_binding_version,0)+1=$8
          AND (o.guardian_id IS NULL OR o.guardian_id=$9)
        """,
            b.tenantId,
            b.ownerId,
            b.roomId,
            b.runId,
            b.runEpoch,
            b.sessionId,
            b.producerIncarnation,
            b.outputBindingVersion,
            self.guardian_id,
        )
        if row is None:
            raise Closed()

    async def permit(self, attempt, permit_id):
        b = attempt.binding
        self.scope_check(b)
        sent, mono = clock(), time.monotonic()
        row = await self.query(
            """
          SELECT EXTRACT(EPOCH FROM LEAST(p.expires_at,l.lease_expires_at,
                         p.issued_at+interval '1 second')-clock_timestamp())::double precision AS remaining
          FROM dl05_output_permits p
          JOIN dl05_runs r ON r.run_id=p.run_id
          JOIN dl05_run_terms t ON t.run_id=r.run_id AND t.run_epoch=p.run_epoch
          JOIN dl05_run_leases l ON l.run_id=r.run_id AND l.run_epoch=p.run_epoch
          JOIN dl05_room_outputs o ON o.room_id=p.room_id
          JOIN dl05_attempts a ON a.run_id=r.run_id AND a.attempt_id=$10
          JOIN dl05_runtime_inbox i ON i.command_id=a.command_id AND i.attempt_id=a.attempt_id
          JOIN dl05_run_slots s ON s.run_id=r.run_id AND s.active_attempt_id=a.attempt_id
          WHERE p.tenant_id=$1 AND p.owner_id=$2 AND p.room_id=$3 AND p.run_id=$4
          AND p.run_epoch=$5 AND r.run_epoch=$5 AND p.session_id=$6 AND r.current_session_id=$6
          AND p.output_binding_version=$7 AND p.producer_incarnation=$8 AND p.permit_id=$9
          AND p.guardian_id=$13 AND t.guardian_id=$13 AND o.guardian_id=$13
          AND o.active_run_id=p.run_id AND o.output_binding_version=p.output_binding_version
          AND o.fence_proof_ref=p.fence_proof_ref AND t.output_fence_proof=p.fence_proof_ref
          AND a.utterance_id=$11 AND a.command_id=$12 AND a.session_id=$6 AND a.run_epoch=$5
          AND a.executor_incarnation=$8 AND i.producer_incarnation=$8 AND t.producer_incarnation=$8
          AND i.status='STARTED' AND i.executor_sealed_at IS NULL
          AND a.last_checkpoint IN ('RUNTIME_ACCEPTED','PLAYING','LOCAL_MEDIA_DRAINED')
          AND r.stop_revision=0 AND r.desired_state='LIVE' AND r.status='LIVE'
          AND l.phase='ACTIVE' AND t.phase='ACTIVE' AND l.lease_owner=t.lease_owner
          AND p.revoked_at IS NULL AND p.expires_at>clock_timestamp()
          AND l.lease_expires_at>clock_timestamp()
        """,
            b.tenantId,
            b.ownerId,
            b.roomId,
            b.runId,
            b.runEpoch,
            b.sessionId,
            b.outputBindingVersion,
            b.producerIncarnation,
            permit_id,
            attempt.attemptId,
            attempt.utteranceId,
            attempt.commandId,
            self.guardian_id,
        )
        if row is None:
            raise Closed("LEASE_LOST")
        return Right.from_remaining(permit_id, row["remaining"], sent, mono)

    async def close(self):
        if self.connection:
            await self.connection.close()
        self.connection = None
