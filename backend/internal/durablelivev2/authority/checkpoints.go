package authority

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
)

// insertCheckpoint shares the original durable event/notification tables, not a
// second Journal. Caller already holds the run row and validates the v2 envelope.
func (s *Store) insertCheckpoint(ctx context.Context, tx pgx.Tx, cp Document, disposition string) error {
	if e := s.Validate("PlaybackCheckpoint", cp); e != nil {
		return fail("INVALID_ARGUMENT")
	}
	ev := obj(cp, "evidence")
	_, e := tx.Exec(ctx, `INSERT INTO dl05_checkpoints(tenant_id,owner_id,run_id,checkpoint_id,event_id,attempt_id,session_id,command_id,run_epoch,producer_incarnation,producer_seq,state,last_known_state,evidence_type,evidence_ref,evidence_hash,occurred_at,envelope,content_hash,projection_status) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`, cp["tenantId"], cp["ownerId"], cp["runId"], cp["checkpointId"], cp["eventId"], cp["attemptId"], cp["sessionId"], cp["commandId"], number(cp, "runEpoch"), cp["producerIncarnation"], number(cp, "producerSeq"), cp["state"], cp["lastKnownState"], ev["evidenceType"], ev["evidenceRef"], ev["evidenceHash"], cp["occurredAt"], cp, hash(cp), disposition)
	return e
}
func (s *Store) confirm(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	cp := obj(q, "checkpoint")
	ev := obj(cp, "evidence")
	target := text(cp, "state")
	for _, k := range []string{"tenantId", "ownerId", "runId", "attemptId", "sessionId", "utteranceId", "commandId", "runEpoch"} {
		if cp[k] != st.c[k] {
			return nil, fail("EVIDENCE_CONFLICT")
		}
	}
	if (p.Role == "RUNTIME_JOURNAL" && (cp["producerIncarnation"] != p.Producer || q["expectedRevision"] != nil)) || (p.Role == "CONTROL" && cp["producerIncarnation"] != p.Incarnation) {
		return nil, fail("FORBIDDEN")
	}
	if p.Role == "CONTROL" && target != "COMPLETED" && target != "INTERRUPTED" {
		return nil, fail("FORBIDDEN")
	}
	if p.Role == "RUNTIME_JOURNAL" && target != "PLAYING" && target != "LOCAL_MEDIA_DRAINED" {
		return nil, fail("FORBIDDEN")
	}
	if hash(ev["requiredSinks"]) != hash(obj(st.c, "payload")["requiredSinks"]) {
		return nil, fail("EVIDENCE_CONFLICT")
	}
	var rev int64
	var last string
	if e := tx.QueryRow(ctx, "SELECT r.state_revision,a.last_checkpoint FROM dl05_runs r JOIN dl05_attempts a USING(run_id) WHERE a.attempt_id=$1 FOR UPDATE OF a", st.c["attemptId"]).Scan(&rev, &last); e != nil {
		return nil, e
	}
	response := func(disposition string, applied bool) Document {
		return Document{"requestId": q["requestId"], "checkpointId": cp["checkpointId"], "applied": applied, "runRevision": rev, "completedPrefix": int64(0), "disposition": disposition}
	}
	var old string
	e := tx.QueryRow(ctx, "SELECT content_hash FROM dl05_checkpoints WHERE checkpoint_id=$1 OR event_id=$2 OR (attempt_id=$3 AND producer_incarnation=$4 AND producer_seq=$5)", cp["checkpointId"], cp["eventId"], cp["attemptId"], cp["producerIncarnation"], number(cp, "producerSeq")).Scan(&old)
	if e == nil {
		if old != hash(cp) {
			return nil, fail("EVIDENCE_CONFLICT")
		}
		return response("DUPLICATE", false), nil
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	var stopped bool
	var epoch int64
	if e = tx.QueryRow(ctx, "SELECT desired_state='STOPPED' OR stop_revision>0,run_epoch FROM dl05_runs WHERE run_id=$1", st.c["runId"]).Scan(&stopped, &epoch); e != nil {
		return nil, e
	}
	if (stopped || epoch != number(cp, "runEpoch")) && target != "INTERRUPTED" {
		return nil, fail("RUN_STOPPED")
	}
	if p.Role == "CONTROL" && number(q, "expectedRevision") != rev {
		return nil, fail("STATE_CONFLICT")
	}
	var maxSeq int64
	if e = tx.QueryRow(ctx, "SELECT COALESCE(MAX(producer_seq),0) FROM dl05_checkpoints WHERE attempt_id=$1 AND producer_incarnation=$2", cp["attemptId"], cp["producerIncarnation"]).Scan(&maxSeq); e != nil {
		return nil, e
	}
	// Do not project gaps or resurrect UNKNOWN. Caller reconciles missing evidence.
	if number(cp, "producerSeq") != maxSeq+1 {
		return nil, fail("EVIDENCE_CONFLICT")
	}
	if target == "PLAYING" || target == "LOCAL_MEDIA_DRAINED" {
		current, e := s.lock(ctx, tx, p, st.c, false)
		if e != nil {
			return nil, e
		}
		if e = current.registered(ctx, tx, p); e != nil {
			return nil, e
		}
		if current.inbox != "STARTED" {
			return nil, fail("RECOVERY_UNKNOWN")
		}
	}
	switch target {
	case "PLAYING":
		if last != "DISPATCHED" && last != "RUNTIME_ACCEPTED" {
			return nil, fail("STATE_CONFLICT")
		}
		var consumed bool
		if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM dl05_v2_execution_state WHERE command_id=$1 AND state='ACTIVE')", st.c["commandId"]).Scan(&consumed); e != nil {
			return nil, e
		}
		if !consumed || ev["evidenceType"] != "SINK_ADMITTED" {
			return nil, fail("EVIDENCE_CONFLICT")
		}
	case "LOCAL_MEDIA_DRAINED":
		if last != "PLAYING" {
			return nil, fail("STATE_CONFLICT")
		}
		if e = s.allDrain(ctx, tx, st, ev); e != nil {
			return nil, e
		}
		if e = predecessor(ctx, tx, st, ev, "PLAYING"); e != nil {
			return nil, e
		}
	case "COMPLETED":
		if last != "LOCAL_MEDIA_DRAINED" || ev["evidenceType"] != "BUSINESS_COMMIT" {
			return nil, fail("STATE_CONFLICT")
		}
		if e = s.allDrain(ctx, tx, st, ev); e != nil {
			return nil, e
		}
		if e = predecessor(ctx, tx, st, ev, "LOCAL_MEDIA_DRAINED"); e != nil {
			return nil, e
		}
	case "INTERRUPTED":
		if last == "COMPLETED" || last == "INTERRUPTED" || ev["evidenceType"] != "FENCE_BARRIER" {
			return nil, fail("STATE_CONFLICT")
		}
	default:
		return nil, fail("FORBIDDEN")
	}
	if e = s.insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_attempts SET last_checkpoint=$2,range_proof=$3,updated_at=clock_timestamp() WHERE attempt_id=$1", st.c["attemptId"], target, ev)
	if e != nil {
		return nil, e
	}
	if target == "PLAYING" {
		_, e = tx.Exec(ctx, "UPDATE dl05_turns SET state='PLAYING',revision=revision+1,started_at=COALESCE(started_at,clock_timestamp()) WHERE turn_id=$1", st.c["turnId"])
	}
	if target == "COMPLETED" || target == "INTERRUPTED" {
		_, e = tx.Exec(ctx, "UPDATE dl05_turns SET state=$2,revision=revision+1,finished_at=clock_timestamp() WHERE turn_id=$1", st.c["turnId"], target)
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, "UPDATE dl05_answer_streams SET state=$2,answer_revision=answer_revision+1 WHERE command_id=$1", st.c["commandId"], target)
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, "UPDATE dl05_runtime_inbox SET status='TERMINAL',revision=revision+1,terminal_at=clock_timestamp(),result_hash=$2 WHERE command_id=$1", st.c["commandId"], hash(cp))
		if e != nil {
			return nil, e
		}
		status := "COMPLETED"
		if target == "INTERRUPTED" {
			status = "FAILED"
		}
		_, e = tx.Exec(ctx, "UPDATE dl05_outbox SET status=$2 WHERE command_id=$1", st.c["commandId"], status)
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, "UPDATE dl05_run_slots SET active_attempt_id=NULL,boundary_checkpoint_id=$2,slot_version=slot_version+1 WHERE run_id=$1 AND active_attempt_id=$3", st.c["runId"], cp["checkpointId"], st.c["attemptId"])
		if e != nil {
			return nil, e
		}
		if st.b != nil {
			if e = invalidate(ctx, tx, st, "BUSINESS_"+target); e != nil {
				return nil, e
			}
		}
		if target == "INTERRUPTED" {
			if _, e = tx.Exec(ctx, "UPDATE dl05_v2_execution_state SET state='FENCED' WHERE command_id=$1 AND state IN ('ACTIVE','UNKNOWN')", st.c["commandId"]); e != nil {
				return nil, e
			}
			if _, e = tx.Exec(ctx, "UPDATE dl05_answer_segment_execution SET state='INTERRUPTED',revision=revision+1 WHERE artifact_id IN (SELECT artifact_id FROM dl05_answer_segments WHERE command_id=$1) AND state IN ('PREPARED','STARTED','UNKNOWN')", st.c["commandId"]); e != nil {
				return nil, e
			}
		}
	}
	if e != nil {
		return nil, e
	}
	if target != "LOCAL_MEDIA_DRAINED" {
		_, e = tx.Exec(ctx, "UPDATE utterances SET status=$2,updated_at=clock_timestamp(),completed_at=CASE WHEN $2 IN ('COMPLETED','INTERRUPTED') THEN clock_timestamp() ELSE completed_at END WHERE id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED')", st.c["utteranceId"], target)
		if e != nil {
			return nil, e
		}
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_runs SET state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1", st.c["runId"])
	if e != nil {
		return nil, e
	}
	rev++
	_, e = tx.Exec(ctx, "INSERT INTO dl05_notifications(run_id,checkpoint_id) VALUES($1,$2)", st.c["runId"], cp["checkpointId"])
	return response("APPLIED", true), e
}
func predecessor(ctx context.Context, tx pgx.Tx, st *state, ev Document, want string) error {
	for _, ref := range list(ev, "predecessorCheckpointIds") {
		var ok bool
		e := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM dl05_checkpoints WHERE checkpoint_id=$1 AND command_id=$2 AND state=$3 AND projection_status='APPLIED')", ref, st.c["commandId"], want).Scan(&ok)
		if e != nil {
			return e
		}
		if ok {
			return nil
		}
	}
	return fail("EVIDENCE_CONFLICT")
}
func (s *Store) allDrain(ctx context.Context, tx pgx.Tx, st *state, ev Document) error {
	var sealed bool
	if e := tx.QueryRow(ctx, "SELECT state='SEALED' AND drained_prefix=prepared_count FROM dl05_answer_streams WHERE command_id=$1", st.c["commandId"]).Scan(&sealed); e != nil {
		return e
	}
	if !sealed {
		return fail("STATE_CONFLICT")
	}
	copy := clone(ev)
	copy["evidenceType"] = "ALL_REQUIRED_DRAIN"
	if e := s.verifyRanges(st, copy); e != nil {
		return e
	}
	rows, e := tx.Query(ctx, "SELECT e.drain_evidence FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND e.state='DRAINED' ORDER BY a.sequence", st.c["commandId"])
	if e != nil {
		return e
	}
	defer rows.Close()
	aggregate := map[string]Document{}
	for rows.Next() {
		d, e := row(rows)
		if e != nil {
			return e
		}
		for _, v := range list(d, "sinkProofs") {
			p := clone(v.(map[string]any))
			key := text(p, "sinkId")
			if old := aggregate[key]; old != nil {
				p["firstAudioSample"] = old["firstAudioSample"]
			}
			aggregate[key] = p
		}
	}
	if e = rows.Err(); e != nil {
		return e
	}
	if len(aggregate) != len(list(ev, "sinkProofs")) {
		return fail("EVIDENCE_CONFLICT")
	}
	for _, v := range list(ev, "sinkProofs") {
		p := v.(map[string]any)
		if hash(aggregate[text(p, "sinkId")]) != hash(p) {
			return fail("EVIDENCE_CONFLICT")
		}
	}
	return nil
}
