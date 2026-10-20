package durablelive

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"time"
)

func systemCheckpoint(a Object, state, kind, producer, ref string) Object {
	return Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "tenantId": a["tenantId"], "ownerId": a["ownerId"], "runId": a["runId"], "checkpointId": freshID("cp"), "eventId": freshID("event"), "attemptId": a["attemptId"], "sessionId": a["sessionId"], "utteranceId": a["utteranceId"], "commandId": a["commandId"], "runEpoch": a["runEpoch"], "producerIncarnation": producer, "producerSeq": int64(1), "state": state, "lastKnownState": nil, "reasonCode": nil, "occurredAt": stamp(time.Now()), "evidence": Object{"evidenceType": kind, "evidenceRef": ref, "evidenceHash": textHash(ref), "requiredSinks": a["requiredSinks"], "sinkProofs": []any{}, "predecessorCheckpointIds": []any{}, "audienceVisibility": "UNVERIFIED"}}
}
func setSystemSequence(ctx context.Context, tx pgx.Tx, cp Object) error {
	var seq int64
	e := tx.QueryRow(ctx, `SELECT COALESCE(MAX(producer_seq),0)+1 FROM dl05_checkpoints WHERE attempt_id=$1 AND producer_incarnation=$2`, cp["attemptId"], cp["producerIncarnation"]).Scan(&seq)
	cp["producerSeq"] = seq
	return e
}
func insertCheckpoint(ctx context.Context, tx pgx.Tx, cp Object, disposition string) error {
	if e := validate("PlaybackCheckpoint", cp); e != nil {
		return e
	}
	ev := obj(cp, "evidence")
	_, e := tx.Exec(ctx, `INSERT INTO dl05_checkpoints(tenant_id,owner_id,run_id,checkpoint_id,event_id,attempt_id,session_id,command_id,run_epoch,producer_incarnation,producer_seq,state,last_known_state,evidence_type,evidence_ref,evidence_hash,occurred_at,envelope,content_hash,projection_status) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`, cp["tenantId"], cp["ownerId"], cp["runId"], cp["checkpointId"], cp["eventId"], cp["attemptId"], cp["sessionId"], cp["commandId"], num(cp, "runEpoch"), cp["producerIncarnation"], num(cp, "producerSeq"), cp["state"], cp["lastKnownState"], ev["evidenceType"], ev["evidenceRef"], ev["evidenceHash"], cp["occurredAt"], cp, hash(cp), disposition)
	if e != nil {
		return e
	}
	if disposition == "APPLIED" {
		_, e = tx.Exec(ctx, `INSERT INTO dl05_notifications(run_id,checkpoint_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, cp["runId"], cp["checkpointId"])
	}
	return e
}
func transition(machine, from, to string) bool {
	b, _ := specs.ReadFile("spec/state-machines.json")
	var root struct {
		Machines map[string]struct {
			Transitions []struct {
				From string `json:"fromState"`
				To   string `json:"toState"`
			} `json:"transitions"`
		} `json:"machines"`
	}
	_ = json.Unmarshal(b, &root)
	for _, v := range root.Machines[machine].Transitions {
		if v.From == from && v.To == to {
			return true
		}
	}
	return false
}
func equalArray(a, b []any) bool { return hash(a) == hash(b) }
func validateSinks(cp, a Object, terminal bool) error {
	ev := obj(cp, "evidence")
	if !equalArray(arr(ev, "requiredSinks"), arr(a, "requiredSinks")) {
		return fault("EVIDENCE_CONFLICT")
	}
	seen := map[string]bool{}
	var generation int64
	for _, v := range arr(ev, "sinkProofs") {
		p := v.(map[string]any)
		id := str(p, "sinkId")
		if seen[id] {
			return fault("EVIDENCE_CONFLICT")
		}
		seen[id] = true
		if generation == 0 {
			generation = num(p, "generationId")
		}
		if num(p, "generationId") != generation {
			return fault("EVIDENCE_CONFLICT")
		}
		if terminal {
			if p["terminal"] != true || num(p, "finalAudioSampleExclusive") <= num(p, "firstAudioSample") || num(p, "audioConsumedThroughExclusive") < num(p, "finalAudioSampleExclusive") || num(p, "videoConsumedThroughFrame") < num(p, "finalVideoFrame") {
				return fault("EVIDENCE_CONFLICT")
			}
		}
	}
	if len(seen) == 0 {
		return fault("EVIDENCE_CONFLICT")
	}
	if terminal {
		for _, id := range arr(a, "requiredSinks") {
			if !seen[id.(string)] {
				return fault("EVIDENCE_CONFLICT")
			}
		}
	}
	return nil
}
func (s *Store) checkpoint(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	cp := obj(q, "checkpoint")
	if !scopeMatches(r, cp) {
		return nil, fault("FORBIDDEN")
	}
	a, e := loadAttempt(ctx, tx, str(cp, "attemptId"))
	if e != nil {
		return nil, normErr(e)
	}
	if !scopeMatches(r, a) || a["sessionId"] != cp["sessionId"] || a["utteranceId"] != cp["utteranceId"] || a["commandId"] != cp["commandId"] || num(a, "runEpoch") != num(cp, "runEpoch") {
		return nil, fault("EVIDENCE_CONFLICT")
	}
	if p.Role == "RUNTIME_JOURNAL" {
		if cp["producerIncarnation"] != p.InstanceID || a["executorIncarnation"] != p.InstanceID {
			return nil, fault("FORBIDDEN")
		}
		if str(cp, "state") != "PLAYING" && str(cp, "state") != "LOCAL_MEDIA_DRAINED" && str(cp, "state") != "INTERRUPTED" && str(cp, "state") != "UNKNOWN" {
			return nil, fault("FORBIDDEN")
		}
		if q["expectedRevision"] != nil {
			return nil, fault("INVALID_ARGUMENT")
		}
	} else {
		if e = revision(r, q); e != nil {
			return nil, e
		}
		state := str(cp, "state")
		if (state != "COMPLETED" && state != "UNKNOWN" && state != "INTERRUPTED") || str(cp, "producerIncarnation") != p.InstanceID {
			return nil, fault("FORBIDDEN")
		}
	}
	expectedKind := map[string]string{"PLANNED": "PLAN_COMMIT", "DISPATCHED": "SEND_STARTED", "RUNTIME_ACCEPTED": "INBOX_COMMIT", "PLAYING": "SINK_ADMITTED", "LOCAL_MEDIA_DRAINED": "ALL_REQUIRED_DRAIN", "COMPLETED": "BUSINESS_COMMIT", "INTERRUPTED": "FENCE_BARRIER", "UNKNOWN": "KNOWLEDGE_GAP"}
	ev := obj(cp, "evidence")
	state := str(cp, "state")
	if str(ev, "evidenceType") != expectedKind[state] || !equalArray(arr(ev, "requiredSinks"), arr(a, "requiredSinks")) {
		return nil, fault("EVIDENCE_CONFLICT")
	}
	if state == "PLAYING" || state == "LOCAL_MEDIA_DRAINED" || state == "COMPLETED" {
		if e = validateSinks(cp, a, state != "PLAYING"); e != nil {
			return nil, e
		}
	}
	var oldHash, oldID string
	e = tx.QueryRow(ctx, `SELECT content_hash,checkpoint_id FROM dl05_checkpoints WHERE event_id=$1 OR checkpoint_id=$2 OR (attempt_id=$3 AND producer_incarnation=$4 AND producer_seq=$5) LIMIT 1`, cp["eventId"], cp["checkpointId"], cp["attemptId"], cp["producerIncarnation"], num(cp, "producerSeq")).Scan(&oldHash, &oldID)
	if e == nil {
		if oldHash != hash(cp) {
			return nil, fault("EVIDENCE_CONFLICT")
		}
		return checkpointResponse(ctx, tx, r, q, oldID, "DUPLICATE", false)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	disposition := "PENDING"
	if num(cp, "runEpoch") != num(r, "runEpoch") || num(r, "stopRevision") > 0 || str(r, "status") == "FAILED" || str(r, "status") == "STOPPED" {
		disposition = "HISTORICAL"
	}
	if e = insertCheckpoint(ctx, tx, cp, disposition); e != nil {
		return nil, e
	}
	if disposition == "PENDING" {
		if e = s.projectPending(ctx, tx, p, r, a); e != nil {
			return nil, e
		}
		e = tx.QueryRow(ctx, `SELECT projection_status FROM dl05_checkpoints WHERE checkpoint_id=$1`, cp["checkpointId"]).Scan(&disposition)
		if e != nil {
			return nil, e
		}
	}
	run, e := loadRun(ctx, tx, str(r, "runId"), false)
	if e != nil {
		return nil, e
	}
	return checkpointResponse(ctx, tx, run, q, str(cp, "checkpointId"), disposition, disposition == "APPLIED")
}
func checkpointResponse(ctx context.Context, tx pgx.Tx, r, q Object, id, disposition string, applied bool) (Object, error) {
	var prefix int64
	e := tx.QueryRow(ctx, `SELECT COALESCE((SELECT completed_prefix FROM dl05_plan_progress WHERE plan_id=$1),0)`, r["currentPlanId"]).Scan(&prefix)
	return Object{"requestId": q["requestId"], "checkpointId": id, "applied": applied, "runRevision": r["revision"], "completedPrefix": prefix, "disposition": disposition}, e
}
func (s *Store) projectPending(ctx context.Context, tx pgx.Tx, p Principal, r, a Object) error {
	// Bound each transaction; later coordinator passes can continue long gaps.
	for pass := 0; pass < 32; pass++ {
		rows, e := tx.Query(ctx, `SELECT c.envelope FROM dl05_checkpoints c WHERE c.attempt_id=$1 AND c.projection_status='PENDING' AND (SELECT count(*) FROM dl05_checkpoints prev WHERE prev.attempt_id=c.attempt_id AND prev.producer_incarnation=c.producer_incarnation AND prev.producer_seq<c.producer_seq AND prev.projection_status IN ('APPLIED','HISTORICAL'))=c.producer_seq-1 ORDER BY c.producer_seq,c.received_at LIMIT 32`, a["attemptId"])
		if e != nil {
			return e
		}
		cps := []Object{}
		for rows.Next() {
			c, e := jsonRow(rows)
			if e != nil {
				rows.Close()
				return e
			}
			cps = append(cps, c)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		progress := false
		for _, cp := range cps {
			a, e = loadAttempt(ctx, tx, str(a, "attemptId"))
			if e != nil {
				return e
			}
			from, to := str(a, "lastCheckpoint"), str(cp, "state")
			// Only an explicitly legal transition may mutate a projection. Terminal
			// conflicts are quarantined; harmless late evidence stays historical.
			if !transition("PlaybackCheckpoint", from, to) {
				if from == to || from == "COMPLETED" || from == "INTERRUPTED" {
					d := "HISTORICAL"
					if (to == "COMPLETED" && from == "INTERRUPTED") || (to == "INTERRUPTED" && from == "COMPLETED") {
						d = "QUARANTINED"
					}
					_, e = tx.Exec(ctx, `UPDATE dl05_checkpoints SET projection_status=$2 WHERE checkpoint_id=$1`, cp["checkpointId"], d)
					if e != nil {
						return e
					}
					progress = true
				}
				continue
			}
			ev := obj(cp, "evidence")
			if to == "PLAYING" || to == "LOCAL_MEDIA_DRAINED" {
				var started bool
				e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runtime_inbox WHERE command_id=$1 AND status IN ('STARTED','UNKNOWN') AND started_at IS NOT NULL AND executor_sealed_at IS NULL AND producer_incarnation=$2)`, cp["commandId"], cp["producerIncarnation"]).Scan(&started)
				if e != nil {
					return e
				}
				if !started {
					continue
				}
			}
			if to == "LOCAL_MEDIA_DRAINED" {
				ok := false
				for _, ref := range arr(ev, "predecessorCheckpointIds") {
					prev, err := jsonRow(tx.QueryRow(ctx, `SELECT envelope FROM dl05_checkpoints WHERE checkpoint_id=$1 AND attempt_id=$2 AND state='PLAYING' AND projection_status='APPLIED'`, ref, a["attemptId"]))
					if err != nil {
						if !errors.Is(err, pgx.ErrNoRows) {
							return err
						}
						continue
					}
					compatible := true
					for _, first := range arr(obj(prev, "evidence"), "sinkProofs") {
						found := false
						for _, last := range arr(ev, "sinkProofs") {
							x, y := first.(map[string]any), last.(map[string]any)
							if str(x, "sinkId") == str(y, "sinkId") {
								found = true
								if num(x, "generationId") != num(y, "generationId") || num(x, "firstAudioSample") != num(y, "firstAudioSample") {
									compatible = false
								}
							}
						}
						if !found {
							compatible = false
						}
					}
					if compatible {
						ok = true
					}
				}
				if !ok {
					continue
				}
			}
			if to == "COMPLETED" {
				ok := false
				for _, ref := range arr(ev, "predecessorCheckpointIds") {
					prev, e := jsonRow(tx.QueryRow(ctx, `SELECT envelope FROM dl05_checkpoints WHERE checkpoint_id=$1 AND attempt_id=$2 AND state='LOCAL_MEDIA_DRAINED' AND projection_status='APPLIED'`, ref, a["attemptId"]))
					if e == nil && equalArray(arr(obj(prev, "evidence"), "sinkProofs"), arr(ev, "sinkProofs")) {
						ok = true
					}
					if e != nil && !errors.Is(e, pgx.ErrNoRows) {
						return e
					}
				}
				if !ok {
					continue
				}
			}
			if to == "INTERRUPTED" {
				var proof bool
				e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_terms t JOIN dl05_run_sessions rs ON rs.run_id=t.run_id JOIN dl05_attempts a ON a.session_id=rs.session_id AND a.run_id=rs.run_id WHERE t.run_id=$1 AND t.output_fence_proof=$2 AND a.attempt_id=$3 AND t.run_epoch>=a.run_epoch AND rs.output_fenced_at>=a.created_at)`, r["runId"], ev["evidenceRef"], a["attemptId"]).Scan(&proof)
				if e != nil {
					return e
				}
				if !proof {
					continue
				}
			}
			if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
				return e
			}
			progress = true
		}
		if !progress {
			return nil
		}
	}
	return nil
}
func projectCheckpoint(ctx context.Context, tx pgx.Tx, r, a, cp Object) error {
	state := str(cp, "state")
	ev := obj(cp, "evidence")
	if str(a, "lastCheckpoint") == "UNKNOWN" && state != "UNKNOWN" {
		if _, e := tx.Exec(ctx, `UPDATE dl05_outbox SET status='RECONCILING' WHERE command_id=$1 AND status='UNKNOWN'`, a["commandId"]); e != nil {
			return e
		}
		if state == "PLAYING" || state == "LOCAL_MEDIA_DRAINED" {
			if _, e := tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='STARTED',revision=revision+1 WHERE command_id=$1 AND status='UNKNOWN' AND started_at IS NOT NULL AND executor_sealed_at IS NULL`, a["commandId"]); e != nil {
				return e
			}
		}
	}
	_, e := tx.Exec(ctx, `UPDATE dl05_attempts SET last_checkpoint=$2,range_proof=$3,updated_at=clock_timestamp() WHERE attempt_id=$1`, a["attemptId"], state, ev)
	if e != nil {
		return e
	}
	if a["segmentId"] != nil {
		segState := "ACTIVE"
		switch state {
		case "COMPLETED", "INTERRUPTED", "UNKNOWN":
			segState = state
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_segments SET checkpoint_state=$2,state=$3,updated_at=clock_timestamp() WHERE segment_id=$1`, a["segmentId"], state, segState)
		if e != nil {
			return e
		}
	}
	turnState := ""
	switch state {
	case "PLAYING":
		turnState = "PLAYING"
	case "COMPLETED", "INTERRUPTED", "UNKNOWN":
		turnState = state
	}
	if turnState != "" {
		var from string
		e = tx.QueryRow(ctx, `SELECT state FROM dl05_turns WHERE turn_id=$1`, a["turnId"]).Scan(&from)
		if e != nil {
			return e
		}
		if from != turnState && !transition("Turn", from, turnState) {
			return fault("EVIDENCE_CONFLICT")
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state=$2,revision=revision+1,started_at=CASE WHEN $2='PLAYING' THEN COALESCE(started_at,clock_timestamp()) ELSE started_at END,finished_at=CASE WHEN $2 IN ('COMPLETED','INTERRUPTED') THEN clock_timestamp() ELSE finished_at END WHERE turn_id=$1`, a["turnId"], turnState)
		if e != nil {
			return e
		}
	}
	// UNKNOWN is separate durable knowledge; use the existing v1 terminal projection
	// only to unblock its busy gate, with explicit failure_code instead of new enums.
	legacy := ""
	switch state {
	case "PLAYING":
		legacy = "PLAYING"
	case "COMPLETED", "INTERRUPTED":
		legacy = state
	case "UNKNOWN":
		legacy = "INTERRUPTED"
	}
	if legacy != "" {
		_, e = tx.Exec(ctx, `UPDATE utterances SET status=$2,failure_code=CASE WHEN $3='UNKNOWN' THEN 'RECOVERY_UNKNOWN' ELSE failure_code END,updated_at=clock_timestamp(),completed_at=CASE WHEN $2 IN ('COMPLETED','INTERRUPTED') THEN clock_timestamp() ELSE completed_at END WHERE id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED')`, a["utteranceId"], legacy, state)
		if e != nil {
			return e
		}
	}
	if state == "COMPLETED" || state == "INTERRUPTED" {
		_, e = tx.Exec(ctx, `UPDATE dl05_run_slots SET active_attempt_id=NULL,boundary_checkpoint_id=$2,slot_version=slot_version+1 WHERE run_id=$1 AND active_attempt_id=$3`, r["runId"], cp["checkpointId"], a["attemptId"])
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='TERMINAL',terminal_at=clock_timestamp(),result_hash=$2,revision=revision+1 WHERE command_id=$1`, a["commandId"], hash(cp))
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status=CASE WHEN $2='COMPLETED' THEN 'COMPLETED' ELSE 'FAILED' END,updated_at=clock_timestamp() WHERE command_id=$1`, a["commandId"], state)
		if e != nil {
			return e
		}
	}
	if state == "UNKNOWN" {
		_, e = tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='UNKNOWN',revision=revision+1 WHERE command_id=$1 AND status NOT IN ('TERMINAL','NOT_EXECUTED')`, a["commandId"])
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='UNKNOWN',last_error_code='RECOVERY_UNKNOWN',updated_at=clock_timestamp() WHERE command_id=$1 AND status IN ('RECONCILING','CLAIMED','ACCEPTED')`, a["commandId"])
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_runs SET status=CASE WHEN status IN ('LIVE','PREPARING') THEN 'RECOVERING' ELSE status END WHERE run_id=$1`, r["runId"])
		if e != nil {
			return e
		}
	}
	if state == "COMPLETED" && a["segmentId"] != nil {
		var planID string
		e = tx.QueryRow(ctx, `SELECT plan_id FROM dl05_segments WHERE segment_id=$1`, a["segmentId"]).Scan(&planID)
		if e != nil {
			return e
		}
		if e = advanceProgress(ctx, tx, planID); e != nil {
			return e
		}
	}

	_, e = tx.Exec(ctx, `UPDATE dl05_checkpoints SET projection_status='APPLIED' WHERE checkpoint_id=$1`, cp["checkpointId"])
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_notifications(run_id,checkpoint_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, r["runId"], cp["checkpointId"])
	if e != nil {
		return e
	}
	return bump(ctx, tx, str(r, "runId"))
}
func (s *Store) markUnknown(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := revision(r, q); e != nil {
		return nil, e
	}
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	a, e := loadAttempt(ctx, tx, str(q, "attemptId"))
	if e != nil {
		return nil, e
	}
	if !scopeMatches(r, a) || num(a, "runEpoch") != num(q, "runEpoch") {
		return nil, fault("STALE_RUN_EPOCH")
	}
	if !transition("PlaybackCheckpoint", str(a, "lastCheckpoint"), "UNKNOWN") {
		return nil, fault("STATE_CONFLICT")
	}
	if str(a, "lastCheckpoint") != "UNKNOWN" && str(a, "lastCheckpoint") != str(q, "lastKnownState") {
		return nil, fault("EVIDENCE_CONFLICT")
	}
	cp := systemCheckpoint(a, "UNKNOWN", "KNOWLEDGE_GAP", "backend-recovery", str(q, "evidenceRef"))
	cp["lastKnownState"] = q["lastKnownState"]
	cp["reasonCode"] = q["reasonCode"]
	if e = setSystemSequence(ctx, tx, cp); e != nil {
		return nil, e
	}
	if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return nil, e
	}
	if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "attemptId": a["attemptId"], "checkpointId": cp["checkpointId"], "runRevision": num(r, "revision") + 1}, nil
}

func advanceProgress(ctx context.Context, tx pgx.Tx, planID string) error {
	_, e := tx.Exec(ctx, `UPDATE dl05_plan_progress pp SET completed_prefix=GREATEST(pp.completed_prefix,x.prefix),resume_sequence=GREATEST(pp.resume_sequence,x.resume),revision=pp.revision+1 FROM (SELECT s.plan_id,COALESCE(MIN(s.sequence) FILTER(WHERE s.state<>'COMPLETED')-1,MAX(s.sequence)) prefix,COALESCE(MIN(s.sequence) FILTER(WHERE s.state<>'COMPLETED' AND NOT EXISTS(SELECT 1 FROM dl05_decisions d JOIN dl05_attempts a ON a.attempt_id=d.attempt_id WHERE a.segment_id=s.segment_id AND d.action='SKIP_WITH_GAP')),MAX(s.sequence)+1) resume FROM dl05_segments s WHERE s.plan_id=$1 GROUP BY s.plan_id) x WHERE pp.plan_id=x.plan_id`, planID)
	return e
}
