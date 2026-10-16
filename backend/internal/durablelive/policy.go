package durablelive

import (
	"context"
	"errors"
)

// PolicyState is an authorized in-process projection, not an additional wire
// operation. All writers serialize on the run row. Revision mismatch or a
// truncated read is an error, never an empty fairness budget.
type PolicyState struct {
	RunRevision                     int64
	Candidates, History             []Turn
	HistoryComplete                 bool
	ProductSnapshotVersion          string
	ProviderReady, OperatorOverride bool
	GapDecisions                    map[string]string
}

const policyLimit = 1024

func (s *Store) ReadPolicyState(ctx context.Context, p Principal, runID string, expectedRevision int64) (out PolicyState, err error) {
	if p.Role != "CONTROL" {
		return out, fault("FORBIDDEN")
	}
	tx, err := s.begin(ctx)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(context.Background())
	r, err := loadRun(ctx, tx, runID, true)
	if err != nil {
		return out, normErr(err)
	}
	if err = authorize(p, r); err != nil {
		return out, err
	}
	if err = owner(ctx, tx, p, "room", str(r, "roomId")); err != nil {
		return out, err
	}
	if num(r, "revision") != expectedRevision {
		return out, fault("STATE_CONFLICT")
	}
	out = PolicyState{RunRevision: expectedRevision, Candidates: []Turn{}, History: []Turn{}, GapDecisions: map[string]string{}, OperatorOverride: str(r, "desiredState") == "PAUSED"}
	// No plan is an explicit empty projection, not missing history.
	if r["currentPlanId"] == nil {
		out.HistoryComplete = true
		return out, tx.Commit(ctx)
	}
	var productID string
	if err = tx.QueryRow(ctx, `SELECT product_id,product_snapshot_version FROM dl05_plans WHERE plan_id=$1 AND run_id=$2 AND tenant_id=$3 AND owner_id=$4`, r["currentPlanId"], runID, p.TenantID, p.OwnerID).Scan(&productID, &out.ProductSnapshotVersion); err != nil {
		return out, err
	}
	if err = owner(ctx, tx, p, "product", productID); err != nil {
		return out, err
	}
	current, err := productView(ctx, tx, p, r)
	if err != nil {
		return out, err
	}
	out.ProductSnapshotVersion = current.SnapshotVersion
	// Binding and Session readiness are authoritative SQL facts. This does not
	// assert GPU health or physical fencing: Runtime must verify both separately.
	err = s.validateSession(ctx, tx, p, r)
	if err == nil {
		_, err = s.validLease(ctx, tx, p, r, "ACTIVE", false)
		out.ProviderReady = err == nil
	}
	if err != nil {
		var f *Fault
		if !errors.As(err, &f) {
			return out, err
		}
		if f.Code == "FORBIDDEN" {
			return out, err
		}
	}
	// Include the last completed SCRIPT anchor, every later terminal turn and
	// every pending/active turn. This is the entire budget since that anchor,
	// including tied timestamps. A 1025th row fails closed rather than truncating.
	rows, err := tx.Query(ctx, `WITH anchor AS (
	 SELECT max(finished_at) at FROM dl05_turns WHERE run_id=$1 AND plan_id=$2 AND turn_type='SCRIPT' AND state='COMPLETED'
	) SELECT t.document || jsonb_build_object('state',t.state,'revision',t.revision,'startedAt',dl05_stamp(t.started_at),'finishedAt',dl05_stamp(t.finished_at))
	 FROM dl05_turns t CROSS JOIN anchor WHERE t.run_id=$1 AND t.plan_id=$2 AND t.tenant_id=$3 AND t.owner_id=$4
	 AND (anchor.at IS NULL OR t.finished_at IS NULL OR t.finished_at>=anchor.at)
	 ORDER BY t.scheduled_at,t.turn_id LIMIT $5`, runID, r["currentPlanId"], p.TenantID, p.OwnerID, policyLimit+1)
	if err != nil {
		return out, err
	}
	count := 0
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			rows.Close()
			return out, err
		}
		count++
		if count > policyLimit {
			rows.Close()
			return PolicyState{}, fault("OVERLOADED")
		}
		m, e := Decode(raw)
		if e != nil {
			rows.Close()
			return out, e
		}
		if e = validate("Turn", m); e != nil {
			rows.Close()
			return out, e
		}
		var turn Turn
		if err = decodeInto(raw, &turn); err != nil {
			rows.Close()
			return out, err
		}
		out.History = append(out.History, turn)
		if turn.TurnType == "COMMENT" && (turn.State == "READY" || turn.State == "WAITING") {
			out.Candidates = append(out.Candidates, turn)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return out, err
	}
	// Decision-to-segment association comes from stored attempt FKs, never from
	// a browser-supplied map. Interrupted/gapped segments are never COMPLETED.
	rows, err = tx.Query(ctx, `SELECT a.segment_id,d.decision_id FROM dl05_decisions d
	 JOIN dl05_attempts a ON a.attempt_id=d.attempt_id AND a.run_id=d.run_id
	 JOIN dl05_segments s ON s.segment_id=a.segment_id AND s.plan_id=d.plan_id
	 WHERE d.run_id=$1 AND d.plan_id=$2 AND d.tenant_id=$3 AND d.owner_id=$4
	 AND d.action='SKIP_WITH_GAP' AND s.state='INTERRUPTED' ORDER BY d.decision_id LIMIT $5`, runID, r["currentPlanId"], p.TenantID, p.OwnerID, policyLimit+1)
	if err != nil {
		return out, err
	}
	count = 0
	for rows.Next() {
		var segment, decision string
		if err = rows.Scan(&segment, &decision); err != nil {
			rows.Close()
			return out, err
		}
		count++
		if count > policyLimit {
			rows.Close()
			return PolicyState{}, fault("OVERLOADED")
		}
		out.GapDecisions[segment] = decision
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return out, err
	}
	out.HistoryComplete = true
	return out, tx.Commit(ctx)
}
