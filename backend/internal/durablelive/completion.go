package durablelive

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// CommitDrained converts only an already applied all-required drain chain to a
// CONTROL business commit. It performs no media/network work and never promotes
// PLAYING, UNKNOWN, old epochs or stopped runs based on a timer or HTTP ACK.
func (s *Store) CommitDrained(ctx context.Context, p Principal, limit int) error {
	if p.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	if limit < 1 || limit > 64 {
		return fault("INVALID_ARGUMENT")
	}
	rows, err := s.DB.Query(ctx, `SELECT DISTINCT a.run_id FROM dl05_attempts a JOIN dl05_runs r USING(run_id)
	 WHERE a.tenant_id=$1 AND a.owner_id=$2 AND a.last_checkpoint='LOCAL_MEDIA_DRAINED'
	 AND a.run_epoch=r.run_epoch AND r.status='LIVE' AND r.stop_revision=0 AND r.desired_state='LIVE'
	 ORDER BY a.run_id LIMIT $3`, p.TenantID, p.OwnerID, limit)
	if err != nil {
		return err
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, id := range ids {
		if err = s.commitRunDrain(ctx, p, id); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) commitRunDrain(ctx context.Context, p Principal, id string) error {
	tx, err := s.begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background())
	r, err := jsonRow(tx.QueryRow(ctx, "SELECT "+runJSON+" FROM dl05_runs WHERE run_id=$1 FOR UPDATE SKIP LOCKED", id))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	if err = authorize(p, r); err != nil {
		return err
	}
	if err = owner(ctx, tx, p, "room", str(r, "roomId")); err != nil {
		return err
	}
	if notStopped(r) != nil || str(r, "status") != "LIVE" || str(r, "desiredState") != "LIVE" {
		return nil
	}
	// The media may have drained just before lease expiry; no new effect is
	// authorized here. The slot must still refer to exactly this current attempt.
	slot, err := loadSlot(ctx, tx, id)
	if err != nil {
		return err
	}
	if slot["activeAttemptId"] == nil {
		return nil
	}
	a, err := loadAttempt(ctx, tx, str(slot, "activeAttemptId"))
	if err != nil {
		return err
	}
	if str(a, "lastCheckpoint") != "LOCAL_MEDIA_DRAINED" || num(a, "runEpoch") != num(r, "runEpoch") {
		return nil
	}
	drain, err := jsonRow(tx.QueryRow(ctx, `SELECT envelope FROM dl05_checkpoints WHERE attempt_id=$1 AND state='LOCAL_MEDIA_DRAINED' AND projection_status='APPLIED' ORDER BY received_at,checkpoint_id LIMIT 1`, a["attemptId"]))
	if err != nil {
		return err
	}
	cp := systemCheckpoint(a, "COMPLETED", "BUSINESS_COMMIT", p.InstanceID, "drain:"+str(drain, "checkpointId"))
	ev := obj(cp, "evidence")
	ev["sinkProofs"] = arr(obj(drain, "evidence"), "sinkProofs")
	ev["predecessorCheckpointIds"] = []any{drain["checkpointId"]}
	if err = setSystemSequence(ctx, tx, cp); err != nil {
		return err
	}
	q := Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "requestId": freshID("req"), "tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": id, "expectedRevision": r["revision"], "checkpoint": cp}
	if err = validate("ConfirmCheckpointRequest", q); err != nil {
		return err
	}
	if _, err = s.checkpoint(ctx, tx, p, r, q); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Store) RunCompletions(ctx context.Context, p Principal) error {
	return runLoop(ctx, 100*time.Millisecond, func(ctx context.Context) error { return s.CommitDrained(ctx, p, 32) })
}
