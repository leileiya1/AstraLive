package authority

import (
	"context"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
)

func answerResponse(q Document, v Document) Document {
	v["requestId"] = q["requestId"]
	v["schemaVersion"] = "0.5"
	v["contractRevision"] = "durable-live-2"
	return v
}
func (s *Store) artifact(ctx context.Context, tx pgx.Tx, st *state, aid string) (Document, error) {
	return row(tx.QueryRow(ctx, `SELECT descriptor FROM dl05_answer_segments WHERE command_id=$1 AND artifact_id=$2`, st.c["commandId"], aid))
}
func identity(a Document) Document {
	v := Document{}
	for _, k := range []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "producerIncarnation", "answerId", "artifactId", "artifactHash"} {
		v[k] = a[k]
	}
	return v
}

// ProductProjection is a domain Tool read, not a Runtime authority declaration.
func (s *Store) ProductProjection(ctx context.Context, p Actor, commandID string) (Document, error) {
	c, e := s.resolve(ctx, Document{"commandId": commandID})
	if e != nil {
		return nil, e
	}
	if e = validateScope(p, c); e != nil {
		return nil, e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	st, e := s.lock(ctx, tx, p, c, false)
	if e != nil {
		return nil, e
	}
	v, e := product(ctx, tx, p, st)
	if e != nil {
		return nil, e
	}
	return v, tx.Commit(ctx)
}
func product(ctx context.Context, tx pgx.Tx, p Actor, st *state) (Document, error) {
	var pid, name, description, price, currency, updated string
	var stock int64
	var sizes []string
	e := tx.QueryRow(ctx, `SELECT p.id,p.name,p.description,p.price::text,p.currency,p.stock,p.sizes,dl05_stamp(p.updated_at) FROM products p JOIN live_rooms r ON r.active_product_id=p.id JOIN resource_owners o ON o.kind='product' AND o.resource_id=p.id AND o.tenant_id=$2 AND o.user_id=$3 WHERE r.id=$1 FOR SHARE OF p,r`, p.Room, p.Tenant, p.Owner).Scan(&pid, &name, &description, &price, &currency, &stock, &sizes, &updated)
	if e != nil {
		return nil, e
	}
	ss := []any{}
	for _, s := range sizes {
		ss = append(ss, s)
	}
	values := Document{"productId": pid, "name": name, "description": description, "price": price, "currency": currency, "stock": stock, "sizes": ss, "updatedAt": updated}
	source := hash(values)
	snapshot := Document{"productId": pid, "name": name, "description": description, "sizes": ss, "sourceVersion": source}
	return Document{"productId": pid, "snapshot": snapshot, "snapshotVersion": hash(snapshot), "sourceVersion": source, "valueHashes": Document{"PRODUCT_DETAILS": hash(Document{"name": name, "description": description}), "PRICE": hash(Document{"price": price, "currency": currency}), "STOCK": hash(stock), "AVAILABILITY": hash(stock > 0), "SIZE_OPTIONS": digest([]byte(strings.Join(sizes, "、")))}}, nil
}
func (s *Store) facts(ctx context.Context, tx pgx.Tx, p Actor, st *state, a Document) error {
	if a["productId"] == nil {
		if obj(st.c, "payload")["productId"] != nil || len(list(a, "factDependencies")) != 0 || len(list(a, "assertionKinds")) != 0 {
			return fail("PLAN_CHANGED")
		}
		return nil
	}
	v, e := product(ctx, tx, p, st)
	if e != nil {
		return e
	}
	if a["productId"] != v["productId"] || a["productSnapshotVersion"] != v["snapshotVersion"] || obj(st.c, "payload")["productId"] != a["productId"] {
		return fail("PLAN_CHANGED")
	}
	var pinned string
	e = tx.QueryRow(ctx, `SELECT product_snapshot_version FROM dl05_plans WHERE plan_id=$1 AND run_id=$2 AND tenant_id=$3 AND owner_id=$4`, obj(st.c, "payload")["planId"], st.c["runId"], p.Tenant, p.Owner).Scan(&pinned)
	if e != nil {
		return e
	}
	if pinned != text(v, "snapshotVersion") {
		return fail("PLAN_CHANGED")
	}
	seen := map[string]bool{}
	for _, raw := range list(a, "factDependencies") {
		f := raw.(map[string]any)
		kind := text(f, "kind")
		if seen[kind] || f["productId"] != a["productId"] || f["sourceVersion"] != v["sourceVersion"] || obj(v, "valueHashes")[kind] != f["valueHash"] {
			return fail("PLAN_CHANGED")
		}
		seen[kind] = true
	}
	if len(seen) != len(list(a, "assertionKinds")) {
		return fail("PLAN_CHANGED")
	}
	for _, kind := range list(a, "assertionKinds") {
		if !seen[kind.(string)] {
			return fail("PLAN_CHANGED")
		}
	}
	return nil
}
func (s *Store) prepare(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	a := obj(q, "artifact")
	if text(a, "answerTextHash") != digest([]byte(text(a, "answerText"))) || text(a, "artifactHash") != hash(without(a, "artifactHash")) {
		return nil, fail("ANSWER_CONFLICT")
	}
	for _, k := range []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "producerIncarnation", "requestHash"} {
		want := st.c[k]
		if k == "producerIncarnation" {
			want = st.producer
		}
		if a[k] != want {
			return nil, fail("ANSWER_CONFLICT")
		}
	}
	if e := s.facts(ctx, tx, p, st, a); e != nil {
		return nil, e
	}
	var savedID, savedHash string
	var receipt Document
	receipt, e := row(tx.QueryRow(ctx, `SELECT receipt FROM dl05_answer_prepare_keys WHERE tenant_id=$1 AND owner_id=$2 AND run_id=$3 AND command_id=$4 AND operation='JournalPrepareAnswer' AND idempotency_key=$5`, p.Tenant, p.Owner, st.c["runId"], st.c["commandId"], q["idempotencyKey"]))
	if e == nil {
		if receipt["artifactId"] != a["artifactId"] || receipt["artifactHash"] != a["artifactHash"] {
			return nil, fail("ANSWER_CONFLICT")
		}
		return answerResponse(q, receipt), nil
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	e = tx.QueryRow(ctx, `SELECT artifact_id,artifact_hash FROM dl05_answer_segments WHERE command_id=$1 AND (artifact_id=$2 OR (answer_id=$3 AND sequence=$4))`, st.c["commandId"], a["artifactId"], a["answerId"], number(a, "sequence")).Scan(&savedID, &savedHash)
	if e == nil {
		if savedID != text(a, "artifactId") || savedHash != text(a, "artifactHash") {
			return nil, fail("ANSWER_CONFLICT")
		}
		receipt, e = row(tx.QueryRow(ctx, "SELECT prepare_receipt FROM dl05_answer_segments WHERE artifact_id=$1", savedID))
		if e != nil {
			return nil, e
		}
	} else {
		if !errors.Is(e, pgx.ErrNoRows) {
			return nil, e
		}
		if number(q, "expectedInboxRevision") != st.inboxRev || number(q, "expectedAnswerRevision") != st.answerRev {
			return nil, fail("STATE_CONFLICT")
		}
		if st.answerID == "" {
			if st.inbox != "ACCEPTED" || number(a, "sequence") != 1 || a["previousArtifactHash"] != nil {
				return nil, fail("ANSWER_GAP")
			}
			st.inboxRev++
			st.answerRev = 1
			st.answerID = text(a, "answerId")
			limit := minTime(st.limit, st.now.Add(30*time.Second))
			_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_streams(answer_id,command_id,state,prepared_count,total_characters,deadline) VALUES($1,$2,'OPEN',1,$3,$4)`, st.answerID, st.c["commandId"], utf8.RuneCountInString(text(a, "answerText")), limit)
			if e != nil {
				return nil, e
			}
			_, e = tx.Exec(ctx, "UPDATE dl05_runtime_inbox SET revision=revision+1 WHERE command_id=$1", st.c["commandId"])
			if e != nil {
				return nil, e
			}
		} else {
			var state string
			var count, total, undrained int64
			var deadline time.Time
			e = tx.QueryRow(ctx, `SELECT state,prepared_count,total_characters,deadline FROM dl05_answer_streams WHERE command_id=$1`, st.c["commandId"]).Scan(&state, &count, &total, &deadline)
			if e != nil {
				return nil, e
			}
			if state != "OPEN" || !deadline.After(st.now) {
				return nil, fail("ANSWER_CLOSED")
			}
			if st.inbox != "STARTED" || st.answerID != text(a, "answerId") {
				return nil, fail("STATE_CONFLICT")
			}
			var previousHash, previousState string
			var evidence []byte
			e = tx.QueryRow(ctx, `SELECT a.artifact_hash,e.state,e.drain_evidence FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND a.sequence=$2`, st.c["commandId"], count).Scan(&previousHash, &previousState, &evidence)
			if e != nil {
				return nil, e
			}
			if number(a, "sequence") != count+1 || a["previousArtifactHash"] != previousHash || !(previousState == "STARTED" || (previousState == "DRAINED" && len(evidence) > 0)) {
				return nil, fail("ANSWER_GAP")
			}
			e = tx.QueryRow(ctx, `SELECT count(*) FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND e.state<>'DRAINED'`, st.c["commandId"]).Scan(&undrained)
			if e != nil {
				return nil, e
			}
			if undrained >= 2 {
				return nil, fail("ANSWER_WINDOW_FULL")
			}
			if count >= 32 || total+int64(utf8.RuneCountInString(text(a, "answerText"))) > 2000 {
				return nil, fail("ANSWER_LIMIT_EXCEEDED")
			}
			st.answerRev++
			_, e = tx.Exec(ctx, `UPDATE dl05_answer_streams SET answer_revision=answer_revision+1,prepared_count=prepared_count+1,total_characters=total_characters+$2 WHERE command_id=$1`, st.c["commandId"], utf8.RuneCountInString(text(a, "answerText")))
			if e != nil {
				return nil, e
			}
		}
		receipt = answerResponse(q, Document{"commandId": st.c["commandId"], "attemptId": st.c["attemptId"], "answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "sequence": a["sequence"], "prepared": true, "receiptId": id("prepare"), "inboxRevision": st.inboxRev, "answerRevision": st.answerRev})
		_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_segments(artifact_id,command_id,answer_id,sequence,descriptor,artifact_hash,answer_text,text_hash,previous_hash,product_id,snapshot_version,facts,prepare_receipt) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`, a["artifactId"], st.c["commandId"], a["answerId"], number(a, "sequence"), a, a["artifactHash"], a["answerText"], a["answerTextHash"], a["previousArtifactHash"], a["productId"], a["productSnapshotVersion"], a["factDependencies"], receipt)
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_segment_execution(artifact_id,state) VALUES($1,'PREPARED')`, a["artifactId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_receiver_artifacts VALUES($1,$2,$3,$4,$5)`, a["artifactId"], st.c["commandId"], a["artifactHash"], st.b["bootstrapId"], st.registration["registrationHash"])
		if e != nil {
			return nil, e
		}
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_prepare_keys VALUES($1,$2,$3,$4,'JournalPrepareAnswer',$5,$6,$7,$8)`, p.Tenant, p.Owner, st.c["runId"], st.c["commandId"], q["idempotencyKey"], a["artifactId"], a["artifactHash"], receipt)
	return answerResponse(q, receipt), e
}
func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}
func (s *Store) permit(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	a, e := s.artifact(ctx, tx, st, text(q, "answerArtifactId"))
	if e != nil {
		return nil, e
	}
	if q["guardianId"] != st.b["guardianId"] {
		return nil, fail("FORBIDDEN")
	}
	if st.inbox != "ACCEPTED" && st.inbox != "STARTED" {
		return nil, fail("RECOVERY_UNKNOWN")
	}
	var state string
	e = tx.QueryRow(ctx, "SELECT state FROM dl05_answer_segment_execution WHERE artifact_id=$1", a["artifactId"]).Scan(&state)
	if e != nil {
		return nil, e
	}
	if state != "PREPARED" && state != "STARTED" {
		return nil, fail("RECOVERY_UNKNOWN")
	}
	if e = s.facts(ctx, tx, p, st, a); e != nil {
		return nil, e
	}
	if e = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&st.now); e != nil {
		return nil, e
	}
	valid := minTime(st.now.Add(2*time.Second), st.limit)
	observation := identity(a)
	observation["observationId"] = id("observation")
	observation["generationId"] = st.b["generationId"]
	observation["productSnapshotVersion"] = a["productSnapshotVersion"]
	observation["factSetHash"] = hash(a["factDependencies"])
	observation["verifiedAt"] = stamp(st.now)
	observation["validUntil"] = stamp(valid)
	observation["authorityRevision"] = hash(Document{"snapshot": a["productSnapshotVersion"], "facts": a["factDependencies"]})
	expiry := minTime(st.now.Add(800*time.Millisecond), valid)
	st.limit = minTime(st.limit, expiry)
	if !expiry.After(st.now) {
		return nil, fail("FACT_EXPIRED")
	}
	pm := identity(a)
	pm["permitId"] = id("permit")
	pm["generationId"] = st.b["generationId"]
	pm["guardianIncarnation"] = st.b["guardianIncarnation"]
	pm["factObservationId"] = observation["observationId"]
	pm["issuedAt"] = stamp(st.now)
	pm["expiresAt"] = stamp(expiry)
	if e = s.Validate("AnswerFactObservation", observation); e != nil {
		return nil, e
	}
	if e = s.Validate("AnswerPlaybackPermit", pm); e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_fact_observations VALUES($1,$2,$3,$4,$5,$6,$7)`, observation["observationId"], st.c["commandId"], a["artifactId"], a["artifactHash"], observation, st.now, valid)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_permits VALUES($1,$2,$3,$4,$5,$6,$7)`, pm["permitId"], st.c["commandId"], a["artifactId"], observation["observationId"], pm, st.now, expiry)
	if e != nil {
		return nil, e
	}
	var lease int64
	e = tx.QueryRow(ctx, "SELECT lease_version FROM dl05_run_leases WHERE run_id=$1", st.c["runId"]).Scan(&lease)
	if e != nil {
		return nil, e
	}
	return Document{"requestId": q["requestId"], "permitId": pm["permitId"], "runEpoch": st.c["runEpoch"], "leaseVersion": lease, "ttlMs": expiry.Sub(st.now).Milliseconds(), "issuedAt": pm["issuedAt"], "expiresAt": pm["expiresAt"], "roomId": p.Room, "outputBindingVersion": st.b["outputBindingVersion"], "sessionId": st.c["sessionId"], "producerIncarnation": st.producer, "answerArtifactId": a["artifactId"], "factObservationId": observation["observationId"], "factValidUntil": observation["validUntil"]}, nil
}
func (s *Store) currentProof(ctx context.Context, tx pgx.Tx, p Actor, st *state, a Document, permitID string) (Document, Document, error) {
	pm, e := row(tx.QueryRow(ctx, `SELECT permit FROM dl05_v2_permits WHERE command_id=$1 AND artifact_id=$2 AND permit_id=$3 AND expires_at>clock_timestamp()`, st.c["commandId"], a["artifactId"], permitID))
	if e != nil {
		return nil, nil, fail("LEASE_LOST")
	}
	obs, e := row(tx.QueryRow(ctx, `SELECT observation FROM dl05_answer_fact_observations WHERE command_id=$1 AND artifact_id=$2 AND observation_id=$3 AND verified_at<=clock_timestamp() AND valid_until>clock_timestamp()`, st.c["commandId"], a["artifactId"], pm["factObservationId"]))
	if e != nil {
		return nil, nil, fail("FACT_EXPIRED")
	}
	if number(pm, "generationId") != number(st.b, "generationId") || pm["guardianIncarnation"] != st.b["guardianIncarnation"] || obs["artifactHash"] != a["artifactHash"] || obs["factSetHash"] != hash(a["factDependencies"]) {
		return nil, nil, fail("EVIDENCE_CONFLICT")
	}
	if e = s.facts(ctx, tx, p, st, a); e != nil {
		return nil, nil, e
	}
	// The immutable permit may predate a shortened output/Binding/lease. The
	// current proof is the intersection, not a rewrite of that persisted permit.
	st.limit = minTime(st.limit, minTime(date(pm, "expiresAt"), date(obs, "validUntil")))
	return pm, obs, nil
}
func ticketVerifier(st *state, grantID, ticket string) string {
	return hash(Document{"domain": "receiver-consume-ticket-1", "contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "grantId": grantID, "registrationHash": st.registration["registrationHash"], "runtimePrincipalId": st.b["runtimePrincipalId"], "ticket": ticket})
}
func (s *Store) start(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document, continuation bool) (Document, error) {
	aid := text(q, "answerArtifactId")
	if continuation {
		aid = text(q, "artifactId")
	}
	a, e := s.artifact(ctx, tx, st, aid)
	if e != nil {
		return nil, e
	}
	key := "answerArtifactHash"
	if continuation {
		key = "artifactHash"
	}
	if a["artifactHash"] != q[key] {
		return nil, fail("ANSWER_CONFLICT")
	}
	if e = s.facts(ctx, tx, p, st, a); e != nil {
		return nil, e
	}
	var unitState string
	e = tx.QueryRow(ctx, "SELECT state FROM dl05_answer_segment_execution WHERE artifact_id=$1 FOR UPDATE", aid).Scan(&unitState)
	if e != nil {
		return nil, e
	}
	if (!continuation && st.inbox != "ACCEPTED") || (continuation && unitState != "PREPARED") {
		if continuation {
			return answerResponse(q, Document{"commandId": st.c["commandId"], "answerId": a["answerId"], "artifactId": aid, "artifactHash": a["artifactHash"], "segmentStartAuthorized": false, "grant": nil, "state": unitState, "answerRevision": st.answerRev, "consumeTicket": nil, "consumeTiming": nil}), nil
		}
		var receipt string
		if e = tx.QueryRow(ctx, "SELECT receipt_id FROM dl05_runtime_inbox WHERE command_id=$1", st.c["commandId"]).Scan(&receipt); e != nil {
			return nil, e
		}
		return Document{"requestId": q["requestId"], "startAuthorized": false, "answerGrant": nil, "state": st.inbox, "revision": st.inboxRev, "evidenceRef": receipt, "consumeTicket": nil, "consumeTiming": nil}, nil
	}
	if unitState != "PREPARED" {
		return nil, fail("STATE_CONFLICT")
	}
	if number(q, "expectedAnswerRevision") != st.answerRev || (!continuation && number(q, "expectedInboxRevision") != st.inboxRev) {
		return nil, fail("STATE_CONFLICT")
	}
	if continuation {
		if st.inbox != "STARTED" || number(a, "sequence") <= 1 || q["answerId"] != a["answerId"] {
			return nil, fail("STATE_CONFLICT")
		}
		var drained bool
		e = tx.QueryRow(ctx, `SELECT e.state='DRAINED' AND e.drain_evidence IS NOT NULL FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND a.sequence=$2`, st.c["commandId"], number(a, "sequence")-1).Scan(&drained)
		if e != nil {
			return nil, e
		}
		if !drained {
			return nil, fail("ANSWER_GAP")
		}
	} else if number(a, "sequence") != 1 {
		return nil, fail("ANSWER_GAP")
	}
	pm, ob, e := s.currentProof(ctx, tx, p, st, a, text(q, "permitId"))
	if e != nil {
		return nil, e
	}
	if e = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&st.now); e != nil {
		return nil, e
	}
	if !st.limit.After(st.now.Add(100 * time.Millisecond)) {
		return nil, fail("GRANT_EXPIRED")
	}
	st.limit = minTime(st.limit, date(pm, "expiresAt"))
	grant := Document{"grantId": id("grant"), "commandId": st.c["commandId"], "attemptId": st.c["attemptId"], "sessionId": st.c["sessionId"], "runEpoch": st.c["runEpoch"], "producerIncarnation": st.producer, "answerId": a["answerId"], "artifactId": aid, "artifactHash": a["artifactHash"], "sequence": a["sequence"], "permitId": pm["permitId"], "factObservationId": ob["observationId"], "factValidUntil": ob["validUntil"], "issuedAt": stamp(st.now), "expiresAt": stamp(st.limit), "authorizationScope": "UNIT_START_ONCE"}
	ticket := secret()
	_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_grants VALUES($1,$2,$3,$4,$5,$6,$7)`, grant["grantId"], st.c["commandId"], aid, grant, ticketVerifier(st, text(grant, "grantId"), ticket), pm["permitId"], date(grant, "expiresAt"))
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_grant_state VALUES($1,'ISSUED')`, grant["grantId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_answer_segment_execution SET state='STARTED',revision=revision+1 WHERE artifact_id=$1 AND state='PREPARED'`, aid)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "UPDATE dl05_answer_streams SET answer_revision=answer_revision+1 WHERE command_id=$1", st.c["commandId"])
	if e != nil {
		return nil, e
	}
	st.answerRev++
	if continuation {
		return answerResponse(q, Document{"commandId": st.c["commandId"], "answerId": a["answerId"], "artifactId": aid, "artifactHash": a["artifactHash"], "segmentStartAuthorized": true, "grant": grant, "state": "STARTED", "answerRevision": st.answerRev, "consumeTicket": ticket, "consumeTiming": timing(st.now, grant, pm, st.limit)}), nil
	}
	tag, e := tx.Exec(ctx, "UPDATE dl05_runtime_inbox SET status='STARTED',revision=revision+1,started_at=clock_timestamp() WHERE command_id=$1 AND status='ACCEPTED' AND executor_sealed_at IS NULL", st.c["commandId"])
	if e != nil {
		return nil, e
	}
	if tag.RowsAffected() != 1 {
		return nil, fail("STATE_CONFLICT")
	}
	st.inboxRev++
	var receipt string
	e = tx.QueryRow(ctx, "SELECT receipt_id FROM dl05_runtime_inbox WHERE command_id=$1", st.c["commandId"]).Scan(&receipt)
	return Document{"requestId": q["requestId"], "startAuthorized": true, "answerGrant": grant, "state": "STARTED", "revision": st.inboxRev, "evidenceRef": receipt, "consumeTicket": ticket, "consumeTiming": timing(st.now, grant, pm, st.limit)}, e
}
