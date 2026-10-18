package authority

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// RecordDrainEvidence is a trusted Observer repository seam, never a Runtime
// completion flag. The independent verification callback runs before Begin.
func (s *Store) RecordDrainEvidence(ctx context.Context, p Actor, commandID, artifactID string, evidence Document) error {
	if p.Role != "OBSERVER" || s.Observer == nil {
		return fail("FORBIDDEN")
	}
	c, e := s.resolve(ctx, Document{"commandId": commandID})
	if e != nil {
		return e
	}
	if e = validateScope(p, c); e != nil {
		return e
	}
	a, e := row(s.DB.QueryRow(ctx, "SELECT descriptor FROM dl05_answer_segments WHERE artifact_id=$1 AND command_id=$2", artifactID, commandID))
	if e != nil {
		return e
	}
	if e = s.Observer(ctx, p, clone(a), clone(evidence)); e != nil {
		return e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	st, e := s.lock(ctx, tx, p, c, false)
	if e != nil {
		return e
	}
	if e = st.registered(ctx, tx, p); e != nil {
		return e
	}
	if e = s.verifyRanges(st, evidence); e != nil {
		return e
	}
	var exists bool
	e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM dl05_receiver_consumptions WHERE command_id=$1 AND artifact_id=$2)", commandID, artifactID).Scan(&exists)
	if e != nil {
		return e
	}
	if !exists {
		return fail("EVIDENCE_CONFLICT")
	}
	var previous Document
	previous, e = row(tx.QueryRow(ctx, "SELECT jsonb_build_object('command',command_id,'artifact',artifact_id,'hash',artifact_hash,'observer',observer_id,'evidence',evidence) FROM dl05_v2_observer_evidence WHERE evidence_ref=$1", evidence["evidenceRef"]))
	if e == nil {
		if previous["command"] != commandID || previous["artifact"] != artifactID || previous["hash"] != a["artifactHash"] || previous["observer"] != p.ID || hash(obj(previous, "evidence")) != hash(evidence) {
			return fail("EVIDENCE_CONFLICT")
		}
		return tx.Commit(ctx)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_observer_evidence VALUES($1,$2,$3,$4,$5,$6)`, evidence["evidenceRef"], commandID, artifactID, a["artifactHash"], p.ID, evidence)
	if e != nil {
		return normalize(e)
	}
	return tx.Commit(ctx)
}
func (s *Store) verifyRanges(st *state, ev Document) error {
	if s.Validate == nil {
		return fail("DEPENDENCY_UNAVAILABLE")
	}
	if e := s.Validate("Evidence", ev); e != nil {
		return e
	}
	if ev["evidenceType"] != "ALL_REQUIRED_DRAIN" || hash(ev["requiredSinks"]) != hash(obj(st.c, "payload")["requiredSinks"]) {
		return fail("EVIDENCE_CONFLICT")
	}
	seen := map[string]bool{}
	for _, raw := range list(ev, "sinkProofs") {
		v := raw.(map[string]any)
		key := text(v, "sinkId")
		if seen[key] || number(v, "generationId") != number(st.b, "generationId") || v["terminal"] != true || number(v, "finalAudioSampleExclusive") <= number(v, "firstAudioSample") || number(v, "audioConsumedThroughExclusive") < number(v, "finalAudioSampleExclusive") || number(v, "videoConsumedThroughFrame") < number(v, "finalVideoFrame") {
			return fail("EVIDENCE_CONFLICT")
		}
		seen[key] = true
	}
	if len(seen) != len(list(ev, "requiredSinks")) {
		return fail("EVIDENCE_CONFLICT")
	}
	for _, k := range list(ev, "requiredSinks") {
		if !seen[k.(string)] {
			return fail("EVIDENCE_CONFLICT")
		}
	}
	return nil
}
func (s *Store) drain(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	a, e := s.artifact(ctx, tx, st, text(q, "artifactId"))
	if e != nil {
		return nil, e
	}
	if a["artifactHash"] != q["artifactHash"] || a["answerId"] != q["answerId"] {
		return nil, fail("ANSWER_CONFLICT")
	}
	ev := obj(q, "evidence")
	identity := without(q, "requestId", "expectedAnswerRevision")
	identity["operation"] = "JournalConfirmAnswerSegment"
	var saved string
	var receipt Document
	e = tx.QueryRow(ctx, `SELECT identity_hash FROM dl05_answer_drain_receipts WHERE command_id=$1 AND idempotency_key=$2`, st.c["commandId"], q["idempotencyKey"]).Scan(&saved)
	if e == nil {
		if saved != hash(identity) {
			return nil, fail("ANSWER_CONFLICT")
		}
		receipt, e = row(tx.QueryRow(ctx, `SELECT receipt FROM dl05_answer_drain_receipts WHERE command_id=$1 AND idempotency_key=$2`, st.c["commandId"], q["idempotencyKey"]))
		return answerResponse(q, receipt), e
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	if number(q, "expectedAnswerRevision") != st.answerRev {
		return nil, fail("STATE_CONFLICT")
	}
	var state string
	e = tx.QueryRow(ctx, "SELECT state FROM dl05_answer_segment_execution WHERE artifact_id=$1 FOR UPDATE", a["artifactId"]).Scan(&state)
	if e != nil {
		return nil, e
	}
	if state != "STARTED" {
		return nil, fail("STATE_CONFLICT")
	}
	trusted, e := row(tx.QueryRow(ctx, "SELECT evidence FROM dl05_v2_observer_evidence WHERE evidence_ref=$1 AND command_id=$2 AND artifact_id=$3 AND artifact_hash=$4", ev["evidenceRef"], st.c["commandId"], a["artifactId"], a["artifactHash"]))
	if e != nil {
		return nil, fail("EVIDENCE_CONFLICT")
	}
	if hash(trusted) != hash(ev) {
		return nil, fail("EVIDENCE_CONFLICT")
	}
	if e = s.verifyRanges(st, ev); e != nil {
		return nil, e
	}
	if number(a, "sequence") > 1 {
		previous, e := row(tx.QueryRow(ctx, `SELECT e.drain_evidence FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND a.sequence=$2 AND e.state='DRAINED'`, st.c["commandId"], number(a, "sequence")-1))
		if e != nil {
			return nil, fail("ANSWER_GAP")
		}
		byID := map[string]Document{}
		for _, v := range list(previous, "sinkProofs") {
			proof := v.(map[string]any)
			byID[text(proof, "sinkId")] = proof
		}
		for _, v := range list(ev, "sinkProofs") {
			proof := v.(map[string]any)
			old := byID[text(proof, "sinkId")]
			if old == nil || number(proof, "firstAudioSample") != number(old, "finalAudioSampleExclusive") || number(proof, "finalVideoFrame") < number(old, "finalVideoFrame") {
				return nil, fail("EVIDENCE_CONFLICT")
			}
		}
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_answer_segment_execution SET state='DRAINED',revision=revision+1,drain_evidence=$2 WHERE artifact_id=$1`, a["artifactId"], ev)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_v2_execution_state s SET state='DRAINED' FROM dl05_receiver_consumptions c WHERE s.execution_id=c.execution_id AND c.command_id=$1 AND c.artifact_id=$2 AND s.state='ACTIVE'`, st.c["commandId"], a["artifactId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_answer_streams SET answer_revision=answer_revision+1,drained_prefix=$2 WHERE command_id=$1`, st.c["commandId"], number(a, "sequence"))
	if e != nil {
		return nil, e
	}
	st.answerRev++
	receipt = answerResponse(q, Document{"answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "drainIdentityHash": hash(identity), "state": "DRAINED", "answerRevision": st.answerRev, "receiptId": id("drain")})
	_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_drain_receipts VALUES($1,$2,$3,$4,$5,$6,$7)`, st.c["commandId"], q["idempotencyKey"], a["artifactId"], a["artifactHash"], hash(identity), identity, receipt)
	return receipt, e
}
func (s *Store) seal(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	if q["answerId"] != st.answerID {
		return nil, fail("ANSWER_CONFLICT")
	}
	rows, e := tx.Query(ctx, "SELECT descriptor FROM dl05_answer_segments WHERE command_id=$1 ORDER BY sequence", st.c["commandId"])
	if e != nil {
		return nil, e
	}
	manifest := []any{}
	allText := ""
	previous := any(nil)
	for rows.Next() {
		a, e := row(rows)
		if e != nil {
			rows.Close()
			return nil, e
		}
		if number(a, "sequence") != int64(len(manifest)+1) || a["previousArtifactHash"] != previous || hash(without(a, "artifactHash")) != text(a, "artifactHash") {
			rows.Close()
			return nil, fail("ANSWER_GAP")
		}
		manifest = append(manifest, Document{"artifactId": a["artifactId"], "sequence": a["sequence"], "artifactHash": a["artifactHash"]})
		allText += text(a, "answerText")
		previous = a["artifactHash"]
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	if number(q, "sequenceCount") != int64(len(manifest)) || q["manifestHash"] != hash(manifest) || q["finalAnswerTextHash"] != digest([]byte(allText)) {
		return nil, fail("ANSWER_CONFLICT")
	}
	var status string
	var final, manifestHash *string
	e = tx.QueryRow(ctx, "SELECT state,final_hash,manifest_hash FROM dl05_answer_streams WHERE command_id=$1", st.c["commandId"]).Scan(&status, &final, &manifestHash)
	if e != nil {
		return nil, e
	}
	if status == "SEALED" || status == "COMPLETED" {
		if final == nil || *final != text(q, "finalAnswerTextHash") || manifestHash == nil || *manifestHash != text(q, "manifestHash") {
			return nil, fail("ANSWER_CONFLICT")
		}
		receipt, e := row(tx.QueryRow(ctx, "SELECT receipt FROM dl05_v2_receipts WHERE command_id=$1 AND operation='JournalSealAnswer' LIMIT 1", st.c["commandId"]))
		return answerResponse(q, receipt), e
	}
	if status != "OPEN" {
		return nil, fail("ANSWER_CLOSED")
	}
	if number(q, "expectedAnswerRevision") != st.answerRev {
		return nil, fail("STATE_CONFLICT")
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_answer_streams SET state='SEALED',answer_revision=answer_revision+1,final_hash=$2,manifest_hash=$3 WHERE command_id=$1`, st.c["commandId"], q["finalAnswerTextHash"], q["manifestHash"])
	if e != nil {
		return nil, e
	}
	st.answerRev++
	_, e = tx.Exec(ctx, "UPDATE dl05_attempts SET answer_text_hash=$2 WHERE command_id=$1", st.c["commandId"], q["finalAnswerTextHash"])
	if e != nil {
		return nil, e
	}
	receipt := answerResponse(q, Document{"answerId": st.answerID, "state": "SEALED", "answerRevision": st.answerRev, "receiptId": id("seal"), "finalAnswerTextHash": q["finalAnswerTextHash"], "manifestHash": q["manifestHash"]})
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_receipts VALUES($1,'JournalSealAnswer',$2,$3,$4)`, st.c["commandId"], q["idempotencyKey"], hash(without(q, "requestId", "expectedAnswerRevision")), receipt)
	return receipt, e
}
func (s *Store) answer(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	if st.answerID == "" || q["answerId"] != st.answerID {
		return nil, fail("RESOURCE_NOT_FOUND")
	}
	var status string
	var count, prefix, total int64
	var final, manifest *string
	e := tx.QueryRow(ctx, `SELECT state,prepared_count,drained_prefix,total_characters,final_hash,manifest_hash FROM dl05_answer_streams WHERE command_id=$1`, st.c["commandId"]).Scan(&status, &count, &prefix, &total, &final, &manifest)
	if e != nil {
		return nil, e
	}
	rows, e := tx.Query(ctx, `SELECT a.descriptor,e.state FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 ORDER BY a.sequence`, st.c["commandId"])
	if e != nil {
		return nil, e
	}
	artifacts := []any{}
	defer rows.Close()
	for rows.Next() {
		var raw []byte
		var state string
		if e = rows.Scan(&raw, &state); e != nil {
			return nil, e
		}
		a, e := legacyDecode(raw)
		if e != nil {
			return nil, e
		}
		artifacts = append(artifacts, Document{"artifact": a, "state": state})
	}
	if e = rows.Err(); e != nil {
		return nil, e
	}
	a := identity(st.c)
	delete(a, "artifactId")
	delete(a, "artifactHash")
	a["producerIncarnation"] = st.producer
	a["schemaVersion"] = "0.5"
	a["contractRevision"] = "durable-live-2"
	a["requestHash"] = st.c["requestHash"]
	a["answerId"] = st.answerID
	a["state"] = status
	a["answerRevision"] = st.answerRev
	a["inboxRevision"] = st.inboxRev
	a["preparedCount"] = count
	a["drainedPrefix"] = prefix
	a["totalCharacters"] = total
	a["finalAnswerTextHash"] = nil
	a["manifestHash"] = nil
	if final != nil {
		a["finalAnswerTextHash"] = *final
	}
	if manifest != nil {
		a["manifestHash"] = *manifest
	}
	a["artifacts"] = artifacts
	return answerResponse(q, Document{"answer": a}), nil
}
func (s *Store) execution(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	var receipt, producer string
	var sealed bool
	e := tx.QueryRow(ctx, "SELECT receipt_id,producer_incarnation,executor_sealed_at IS NOT NULL FROM dl05_runtime_inbox WHERE command_id=$1", st.c["commandId"]).Scan(&receipt, &producer, &sealed)
	if errors.Is(e, pgx.ErrNoRows) {
		return Document{"requestId": q["requestId"], "status": Document{"commandId": st.c["commandId"], "requestHash": st.c["requestHash"], "runEpoch": st.c["runEpoch"], "attemptId": st.c["attemptId"], "state": "UNKNOWN", "lastCheckpoint": nil, "receiptId": nil, "executorIncarnation": nil, "executorSealed": false, "revision": int64(1), "evidenceRef": nil}}, nil
	}
	if e != nil {
		return nil, e
	}
	var checkpoint any
	cp, e := row(tx.QueryRow(ctx, "SELECT envelope FROM dl05_checkpoints WHERE command_id=$1 ORDER BY received_at DESC,checkpoint_id DESC LIMIT 1", st.c["commandId"]))
	if e == nil {
		checkpoint = cp
	} else if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	knowledge := st.inbox
	var authorityLive bool
	if e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runs r JOIN dl05_run_leases l USING(run_id) JOIN session_provider_bindings b ON b.session_id=r.current_session_id WHERE r.run_id=$1 AND r.desired_state<>'STOPPED' AND r.stop_revision=0 AND l.phase='ACTIVE' AND l.run_epoch=r.run_epoch AND l.lease_expires_at>clock_timestamp() AND b.released_at IS NULL AND b.expires_at>clock_timestamp())`, st.c["runId"]).Scan(&authorityLive); e != nil {
		return nil, e
	}
	if knowledge != "TERMINAL" && !authorityLive {
		knowledge = "UNKNOWN"
	}
	if knowledge != "TERMINAL" && (number(st.r, "runEpoch") != number(st.c, "runEpoch") || (st.registration != nil && text(st.registration, "state") != "ACTIVE")) {
		knowledge = "UNKNOWN"
	}
	return Document{"requestId": q["requestId"], "status": Document{"commandId": st.c["commandId"], "requestHash": st.c["requestHash"], "runEpoch": st.c["runEpoch"], "attemptId": st.c["attemptId"], "state": knowledge, "lastCheckpoint": checkpoint, "receiptId": receipt, "executorIncarnation": producer, "executorSealed": sealed, "revision": st.inboxRev, "evidenceRef": receipt}}, nil
}

const runObject = `jsonb_build_object('tenantId',tenant_id,'ownerId',owner_id,'runId',run_id,'roomId',room_id,'status',status,'runEpoch',run_epoch,'currentSessionId',current_session_id,'currentPlanId',current_plan_id,'startedAt',dl05_stamp(started_at),'updatedAt',dl05_stamp(updated_at),'endedAt',dl05_stamp(ended_at),'desiredState',desired_state,'recoveryPolicy',recovery_policy,'revision',state_revision,'stopRevision',stop_revision)`

func (s *Store) stopRun(ctx context.Context, p Actor, q Document) (Document, error) {
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	var room, revision string
	var stopped int64
	e = tx.QueryRow(ctx, `SELECT room_id,contract_revision,stop_revision FROM dl05_runs WHERE tenant_id=$1 AND owner_id=$2 AND run_id=$3 FOR UPDATE`, p.Tenant, p.Owner, q["runId"]).Scan(&room, &revision, &stopped)
	if e != nil {
		return nil, e
	}
	if room != p.Room {
		return nil, fail("FORBIDDEN")
	}
	if revision != "durable-live-2" {
		return nil, fail("CONTRACT_REVISION_MISMATCH")
	}
	if stopped == 0 {
		_, e = tx.Exec(ctx, `UPDATE dl05_runs SET desired_state='STOPPED',status=CASE WHEN status IN ('FAILED','STOPPED') THEN status ELSE 'STOPPING' END,stop_revision=state_revision+1,state_revision=state_revision+1,stopped_at=clock_timestamp(),updated_at=clock_timestamp() WHERE run_id=$1`, q["runId"])
		if e != nil {
			return nil, e
		}
	}
	if stopped == 0 {
		for _, sql := range []string{
			"UPDATE dl05_run_leases SET phase='SEALED',lease_expires_at=clock_timestamp() WHERE run_id=$1",
			"UPDATE dl05_run_terms SET phase='SEALED',sealed_at=clock_timestamp() WHERE run_id=$1 AND phase<>'SEALED'",
			"UPDATE dl05_turns SET state='INTERRUPTED',revision=revision+1,finished_at=clock_timestamp() WHERE run_id=$1 AND state IN ('READY','WAITING')",
			"UPDATE dl05_outbox SET status=CASE WHEN status='PENDING' AND send_started_at IS NULL THEN 'FAILED' ELSE 'RECONCILING' END,last_error_code='RUN_STOPPED' WHERE run_id=$1 AND operation='EXECUTE_TURN' AND status IN ('PENDING','CLAIMED','ACCEPTED')",
		} {
			if _, e = tx.Exec(ctx, sql, q["runId"]); e != nil {
				return nil, e
			}
		}
		run, e := row(tx.QueryRow(ctx, "SELECT "+runObject+" FROM dl05_runs WHERE run_id=$1", q["runId"]))
		if e != nil {
			return nil, e
		}
		rows, e := tx.Query(ctx, "SELECT session_id FROM dl05_run_sessions WHERE run_id=$1 ORDER BY session_id", q["runId"])
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
		if e = rows.Err(); e != nil {
			rows.Close()
			return nil, e
		}
		rows.Close()
		for _, sid := range sessions {
			command := Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": p.Tenant, "ownerId": p.Owner, "runId": q["runId"], "sessionId": sid, "commandId": id("stopcmd"), "intentId": id("stopintent"), "runEpoch": run["runEpoch"], "idempotencyKey": "stop:" + hash(Document{"decisionId": q["decisionId"], "sessionId": sid}), "traceId": q["requestId"], "createdAt": stamp(time.Now()), "stopRevision": run["stopRevision"], "operation": "STOP_RUN", "reasonCode": q["reasonCode"]}
			command["requestHash"] = hash(command)
			if e = s.Validate("RuntimeStopRequest", command); e != nil {
				return nil, e
			}
			_, e = tx.Exec(ctx, `INSERT INTO dl05_outbox(tenant_id,owner_id,run_id,session_id,command_id,intent_id,run_epoch,idempotency_key,operation,request_hash,envelope,status) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'STOP_RUN',$9,$10,'PENDING')`, p.Tenant, p.Owner, q["runId"], sid, command["commandId"], command["intentId"], command["runEpoch"], command["idempotencyKey"], command["requestHash"], command)
			if e != nil {
				return nil, e
			}
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_decisions(tenant_id,owner_id,run_id,decision_id,operator_id,action,reason,expected_revision,document) VALUES($1,$2,$3,$4,$5,'STOP',$6,$7,$8)`, p.Tenant, p.Owner, q["runId"], q["decisionId"], p.ID, q["reasonCode"], number(q, "expectedRevision"), q)
		if e != nil {
			return nil, e
		}
	}
	r, e := row(tx.QueryRow(ctx, "SELECT "+runObject+" FROM dl05_runs WHERE run_id=$1", q["runId"]))
	if e != nil {
		return nil, e
	}
	out := Document{"requestId": q["requestId"], "run": r, "stopRevision": r["stopRevision"]}
	if e = s.Validate("StopBroadcastRunResponse", out); e != nil {
		return nil, e
	}
	return out, tx.Commit(ctx)
}
func (s *Store) unknown(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	reason := text(q, "reasonCode")
	ref := text(q, "evidenceRef")
	key := text(q, "idempotencyKey")
	if key == "" {
		key = ref
	}
	identityHash := hash(without(q, "requestId", "expectedRevision"))
	var saved string
	e := tx.QueryRow(ctx, "SELECT identity_hash FROM dl05_v2_receipts WHERE command_id=$1 AND operation='MarkExecutionUnknown' AND idempotency_key=$2", st.c["commandId"], key).Scan(&saved)
	if e == nil {
		if saved != identityHash {
			return nil, fail("COMMAND_CONFLICT")
		}
		out, e := row(tx.QueryRow(ctx, "SELECT receipt FROM dl05_v2_receipts WHERE command_id=$1 AND operation='MarkExecutionUnknown' AND idempotency_key=$2", st.c["commandId"], key))
		if e == nil {
			out["requestId"] = q["requestId"]
		}
		return out, e
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	var revision int64
	var last string
	if e = tx.QueryRow(ctx, "SELECT r.state_revision,a.last_checkpoint FROM dl05_runs r JOIN dl05_attempts a USING(run_id) WHERE a.attempt_id=$1 FOR UPDATE OF a", st.c["attemptId"]).Scan(&revision, &last); e != nil {
		return nil, e
	}
	if _, ok := q["expectedRevision"]; ok && number(q, "expectedRevision") != revision {
		return nil, fail("STATE_CONFLICT")
	}
	if last == "COMPLETED" || last == "INTERRUPTED" {
		return nil, fail("STATE_CONFLICT")
	}
	if last != "UNKNOWN" && q["lastKnownState"] != nil && q["lastKnownState"] != last {
		return nil, fail("EVIDENCE_CONFLICT")
	}
	cp := Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": st.c["tenantId"], "ownerId": st.c["ownerId"], "runId": st.c["runId"], "checkpointId": id("unknown"), "eventId": id("event"), "attemptId": st.c["attemptId"], "sessionId": st.c["sessionId"], "utteranceId": st.c["utteranceId"], "commandId": st.c["commandId"], "runEpoch": st.c["runEpoch"], "producerIncarnation": "backend-recovery", "state": "UNKNOWN", "lastKnownState": last, "reasonCode": reason, "occurredAt": stamp(st.now), "evidence": Document{"evidenceType": "KNOWLEDGE_GAP", "evidenceRef": ref, "evidenceHash": digest([]byte(ref)), "requiredSinks": obj(st.c, "payload")["requiredSinks"], "sinkProofs": []any{}, "predecessorCheckpointIds": []any{}, "audienceVisibility": "UNVERIFIED"}}
	if last == "UNKNOWN" {
		old, e := row(tx.QueryRow(ctx, "SELECT envelope FROM dl05_checkpoints WHERE attempt_id=$1 AND state='UNKNOWN' ORDER BY received_at DESC LIMIT 1", st.c["attemptId"]))
		if e != nil {
			return nil, e
		}
		cp["lastKnownState"] = old["lastKnownState"]
	}
	var seq int64
	if e = tx.QueryRow(ctx, "SELECT COALESCE(MAX(producer_seq),0)+1 FROM dl05_checkpoints WHERE attempt_id=$1 AND producer_incarnation='backend-recovery'", st.c["attemptId"]).Scan(&seq); e != nil {
		return nil, e
	}
	cp["producerSeq"] = seq
	if e = s.Validate("PlaybackCheckpoint", cp); e != nil {
		return nil, e
	}
	if e = s.insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "INSERT INTO dl05_notifications(run_id,checkpoint_id) VALUES($1,$2)", st.c["runId"], cp["checkpointId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "INSERT INTO dl05_v2_audit(command_id,reason,evidence_ref) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", st.c["commandId"], reason, ref)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_attempts SET last_checkpoint='UNKNOWN',updated_at=clock_timestamp() WHERE attempt_id=$1", st.c["attemptId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_answer_segment_execution SET state='UNKNOWN',revision=revision+1 WHERE artifact_id IN (SELECT artifact_id FROM dl05_answer_segments WHERE command_id=$1) AND state='STARTED'", st.c["commandId"])
	if e != nil {
		return nil, e
	}
	if st.b != nil {
		if e = invalidate(ctx, tx, st, reason); e != nil {
			return nil, e
		}
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='UNKNOWN',revision=revision+1 WHERE command_id=$1 AND status IN ('ACCEPTED','STARTED')`, st.c["commandId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_answer_streams SET state='UNKNOWN',answer_revision=answer_revision+1 WHERE command_id=$1 AND state IN ('OPEN','SEALED')`, st.c["commandId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='UNKNOWN',revision=revision+1 WHERE turn_id=$1 AND state IN ('DISPATCHING','PLAYING')`, st.c["turnId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='UNKNOWN' WHERE command_id=$1 AND status IN ('CLAIMED','ACCEPTED','RECONCILING')`, st.c["commandId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE utterances SET status='INTERRUPTED',failure_code='RECOVERY_UNKNOWN',completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED')", st.c["utteranceId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_runs SET status=CASE WHEN status IN ('LIVE','PREPARING') THEN 'RECOVERING' ELSE status END WHERE run_id=$1", st.c["runId"])
	if e != nil {
		return nil, e
	}
	checkpoint := cp["checkpointId"]
	_, e = tx.Exec(ctx, `UPDATE dl05_runs SET state_revision=state_revision+1 WHERE run_id=$1`, st.c["runId"])
	if e != nil {
		return nil, e
	}
	var rev int64
	e = tx.QueryRow(ctx, "SELECT state_revision FROM dl05_runs WHERE run_id=$1", st.c["runId"]).Scan(&rev)
	if e != nil {
		return nil, e
	}
	out := Document{"requestId": q["requestId"], "attemptId": st.c["attemptId"], "checkpointId": checkpoint, "runRevision": rev}
	_, e = tx.Exec(ctx, "INSERT INTO dl05_v2_receipts VALUES($1,'MarkExecutionUnknown',$2,$3,$4)", st.c["commandId"], key, identityHash, out)
	return out, e
}

// ReconcileExpired is bounded and uses the existing run-lock domain; it never
// redelivers, reissues tickets, removes latches, or reconstructs a physical Session.
func (s *Store) ReconcileExpired(ctx context.Context, p Actor, limit int) (int, error) {
	if p.Role != "CONTROL" || limit < 1 || limit > 100 {
		return 0, fail("FORBIDDEN")
	}
	rows, e := s.DB.Query(ctx, `SELECT c.command_id FROM dl05_v2_commands c JOIN dl05_runs r USING(run_id) JOIN dl05_run_leases l USING(run_id) WHERE c.tenant_id=$1 AND c.owner_id=$2 AND c.room_id=$3 AND r.desired_state<>'STOPPED' AND NOT EXISTS(SELECT 1 FROM dl05_v2_receipts v WHERE v.command_id=c.command_id AND v.operation='MarkExecutionUnknown' AND v.idempotency_key='lease-expiry:'||c.command_id) AND EXISTS(SELECT 1 FROM dl05_attempts a WHERE a.attempt_id=c.attempt_id AND a.last_checkpoint NOT IN ('COMPLETED','INTERRUPTED')) AND (l.lease_expires_at<=clock_timestamp() OR c.run_epoch<>r.run_epoch OR (c.command->'payload'->>'expiresAt')::timestamptz<=clock_timestamp() OR EXISTS(SELECT 1 FROM dl05_answer_grants g JOIN dl05_v2_grant_state gs USING(grant_id) WHERE g.command_id=c.command_id AND gs.state='ISSUED' AND g.expires_at<=clock_timestamp())) ORDER BY c.command_id LIMIT $4`, p.Tenant, p.Owner, p.Room, limit)
	if e != nil {
		return 0, e
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return 0, e
		}
		ids = append(ids, id)
	}
	if e = rows.Err(); e != nil {
		rows.Close()
		return 0, e
	}
	rows.Close()
	n := 0
	for _, id := range ids {
		c, e := s.resolve(ctx, Document{"commandId": id})
		if e != nil {
			return n, e
		}
		tx, e := s.begin(ctx)
		if e != nil {
			return n, e
		}
		st, e := s.lock(ctx, tx, p, c, true)
		if e == nil {
			var expired bool
			e = tx.QueryRow(ctx, `SELECT r.desired_state<>'STOPPED' AND r.stop_revision=0 AND (l.lease_expires_at<=clock_timestamp() OR r.run_epoch<>$2 OR (SELECT (command->'payload'->>'expiresAt')::timestamptz<=clock_timestamp() FROM dl05_v2_commands WHERE command_id=$3) OR EXISTS(SELECT 1 FROM dl05_answer_grants g JOIN dl05_v2_grant_state gs USING(grant_id) WHERE g.command_id=$3 AND gs.state='ISSUED' AND g.expires_at<=clock_timestamp())) FROM dl05_runs r JOIN dl05_run_leases l USING(run_id) WHERE r.run_id=$1`, c["runId"], number(c, "runEpoch"), c["commandId"]).Scan(&expired)
			if e == nil && expired {
				_, e = s.unknown(ctx, tx, p, st, Document{"requestId": id, "reasonCode": "AUTHORITY_LOST", "evidenceRef": "lease-expiry:" + id})
				n++
			}
		}
		if e != nil {
			tx.Rollback(ctx)
			return n, e
		}
		if e = tx.Commit(ctx); e != nil {
			return n, e
		}
	}
	return n, nil
}
