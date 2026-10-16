package durablelive

import (
	"context"
	"github.com/jackc/pgx/v5"
	"time"
)

func (s *Store) stop(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	// The caller's revision and any lost/expired lease cannot veto an authorized Stop.
	if num(r, "stopRevision") == 0 {
		_, e := tx.Exec(ctx, `UPDATE dl05_runs SET desired_state='STOPPED',stop_revision=state_revision+1,stopped_at=clock_timestamp(),status=CASE WHEN status IN ('FAILED','STOPPED') THEN status ELSE 'STOPPING' END,state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_run_leases SET phase='SEALED',lease_expires_at=clock_timestamp() WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_run_terms SET phase='SEALED',sealed_at=clock_timestamp() WHERE run_id=$1 AND phase<>'SEALED'`, r["runId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_output_permits SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='INTERRUPTED',finished_at=clock_timestamp(),revision=revision+1 WHERE run_id=$1 AND state IN ('READY','WAITING')`, r["runId"])
		if e != nil {
			return nil, e
		}
		// PENDING has never been claimed, hence cannot have been emitted by this sender.
		_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status=CASE WHEN status='PENDING' AND send_started_at IS NULL THEN 'FAILED' ELSE 'RECONCILING' END,last_error_code='RUN_STOPPED' WHERE run_id=$1 AND operation='EXECUTE_TURN' AND status IN ('PENDING','CLAIMED','ACCEPTED')`, r["runId"])
		if e != nil {
			return nil, e
		}
		r, e = loadRun(ctx, tx, str(r, "runId"), false)
		if e != nil {
			return nil, e
		}
		rows, e := tx.Query(ctx, `SELECT session_id FROM dl05_run_sessions WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
		sessions := []string{}
		for rows.Next() {
			var sid string
			if e = rows.Scan(&sid); e != nil {
				rows.Close()
				return nil, e
			}
			sessions = append(sessions, sid)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return nil, e
		}
		for _, sid := range sessions {
			cmd := Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": r["runId"], "sessionId": sid, "commandId": freshID("cmd"), "intentId": freshID("intent"), "runEpoch": r["runEpoch"], "idempotencyKey": "stop:" + str(q, "decisionId") + ":" + sid, "traceId": q["requestId"], "createdAt": stamp(time.Now()), "stopRevision": r["stopRevision"], "operation": "STOP_RUN", "reasonCode": q["reasonCode"]}
			cmd["requestHash"] = commandHash(cmd)
			if e = validate("RuntimeStopRequest", cmd); e != nil {
				return nil, e
			}
			if e = insertIntent(ctx, tx, p, r, cmd); e != nil {
				return nil, e
			}
		}
		if len(sessions) == 0 {
			_, e = tx.Exec(ctx, `UPDATE dl05_runs SET status=CASE WHEN status='STOPPING' THEN 'STOPPED' ELSE status END,ended_at=clock_timestamp() WHERE run_id=$1`, r["runId"])
			if e != nil {
				return nil, e
			}
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_decisions(tenant_id,owner_id,run_id,decision_id,operator_id,action,reason,expected_revision,document) VALUES($1,$2,$3,$4,$5,'STOP',$6,$7,$8)`, p.TenantID, p.OwnerID, r["runId"], q["decisionId"], p.InstanceID, q["reasonCode"], num(q, "expectedRevision"), q)
		if e != nil {
			return nil, e
		}
	}
	run, e := loadRun(ctx, tx, str(r, "runId"), false)
	return Object{"requestId": q["requestId"], "run": run, "stopRevision": run["stopRevision"]}, e
}
