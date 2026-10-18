package authority

import (
	"context"
	"crypto/subtle"
	"errors"

	"github.com/jackc/pgx/v5"
)

func (s *Store) summary(ctx context.Context, tx pgx.Tx, st *state, grantID string) (Document, error) {
	var receipt, status string
	e := tx.QueryRow(ctx, `SELECT c.receipt_id,s.state FROM dl05_receiver_consumptions c JOIN dl05_v2_execution_state s USING(execution_id) WHERE c.command_id=$1 AND c.grant_id=$2`, st.c["commandId"], grantID).Scan(&receipt, &status)
	if errors.Is(e, pgx.ErrNoRows) {
		return Document{"state": "UNCONSUMED", "receiptId": nil}, nil
	}
	if e != nil {
		return nil, e
	}
	if status == "ACTIVE" {
		status = "CONSUMED"
	}
	return Document{"state": status, "receiptId": receipt}, nil
}
func (s *Store) snapshot(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	refs := obj(q, "references")
	if refs["bootstrapId"] != st.b["bootstrapId"] {
		return nil, fail("BOOTSTRAP_REQUIRED")
	}
	if st.inbox != "STARTED" {
		return nil, fail("RECOVERY_UNKNOWN")
	}
	a, e := s.artifact(ctx, tx, st, text(refs, "artifactId"))
	if e != nil {
		return nil, e
	}
	if a["artifactHash"] != refs["artifactHash"] {
		return nil, fail("ANSWER_CONFLICT")
	}
	g, e := row(tx.QueryRow(ctx, `SELECT grant_body FROM dl05_answer_grants WHERE command_id=$1 AND artifact_id=$2 AND grant_id=$3`, st.c["commandId"], a["artifactId"], refs["grantId"]))
	if e != nil {
		return nil, e
	}
	pm, obs, e := s.currentProof(ctx, tx, p, st, a, text(refs, "permitId"))
	if e != nil {
		return nil, e
	}
	st.limit = minTime(st.limit, date(pm, "expiresAt"))
	var status string
	e = tx.QueryRow(ctx, "SELECT state FROM dl05_v2_grant_state WHERE grant_id=$1", g["grantId"]).Scan(&status)
	if e != nil {
		return nil, e
	}
	var childTime string
	e = tx.QueryRow(ctx, "SELECT dl05_stamp(created_at) FROM dl05_answer_segments WHERE artifact_id=$1", a["artifactId"]).Scan(&childTime)
	if e != nil {
		return nil, e
	}
	child := Document{"bootstrapId": st.b["bootstrapId"], "answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "bindingHash": st.registration["registrationHash"], "sequence": a["sequence"], "createdAt": childTime}
	summary, e := s.summary(ctx, tx, st, text(g, "grantId"))
	if e != nil {
		return nil, e
	}
	if e = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&st.now); e != nil {
		return nil, e
	}
	return Document{"requestId": q["requestId"], "snapshot": Document{"registration": st.registration, "artifactRegistration": child, "artifact": a, "grant": g, "grantState": status, "permit": pm, "observation": obs, "consumption": summary, "authorityTime": stamp(st.now), "validUntil": pm["expiresAt"], "timing": timing(st.now, g, pm)}}, nil
}
func (s *Store) consume(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	// Current authority is checked BEFORE duplicate/nonce lookup.
	snap, e := s.snapshot(ctx, tx, p, st, q)
	if e != nil {
		return nil, e
	}
	v := obj(snap, "snapshot")
	g := obj(v, "grant")
	a := obj(v, "artifact")
	if q["runtimePrincipalId"] != st.b["runtimePrincipalId"] || q["runtimeIncarnation"] != st.b["runtimeIncarnation"] || number(q, "expectedRegistrationRevision") != number(st.registration, "revision") {
		return nil, fail("STATE_CONFLICT")
	}
	var verifier string
	e = tx.QueryRow(ctx, "SELECT ticket_verifier FROM dl05_answer_grants WHERE grant_id=$1", g["grantId"]).Scan(&verifier)
	if e != nil {
		return nil, e
	}
	presented := ticketVerifier(st, text(g, "grantId"), text(q, "consumeTicket"))
	if subtle.ConstantTimeCompare([]byte(verifier), []byte(presented)) != 1 {
		return nil, fail("GRANT_TICKET_INVALID")
	}
	identityHash := hash(Document{"domain": "receiver-consume-identity-1", "guardianPrincipalId": p.ID, "request": without(q, "requestId", "consumeTicket"), "ticketVerifier": verifier})
	var previous string
	e = tx.QueryRow(ctx, "SELECT consume_identity FROM dl05_receiver_consumptions WHERE runtime_principal=$1 AND consume_nonce=$2", q["runtimePrincipalId"], q["consumeRequestId"]).Scan(&previous)
	if e == nil && previous != identityHash {
		return nil, fail("CONSUMPTION_CONFLICT")
	}
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	var existing string
	e = tx.QueryRow(ctx, "SELECT consume_identity FROM dl05_receiver_consumptions WHERE grant_id=$1", g["grantId"]).Scan(&existing)
	if e == nil {
		if existing != identityHash {
			return nil, fail("CONSUMPTION_CONFLICT")
		}
		return Document{"requestId": q["requestId"], "consumeAuthorized": false, "consumption": nil, "consumeTiming": nil, "summary": v["consumption"]}, nil
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	if v["grantState"] != "ISSUED" {
		return nil, fail("CONSUMPTION_UNKNOWN")
	}
	var active bool
	e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM dl05_v2_execution_state WHERE command_id=$1 AND state IN ('ACTIVE','UNKNOWN'))", st.c["commandId"]).Scan(&active)
	if e != nil {
		return nil, e
	}
	if active {
		return nil, fail("ACTIVE_UNIT_CONFLICT")
	}
	if number(a, "sequence") > 1 {
		var drained bool
		e = tx.QueryRow(ctx, `SELECT e.state='DRAINED' AND e.drain_evidence IS NOT NULL FROM dl05_answer_segments a JOIN dl05_answer_segment_execution e USING(artifact_id) WHERE a.command_id=$1 AND a.sequence=$2`, st.c["commandId"], number(a, "sequence")-1).Scan(&drained)
		if e != nil {
			return nil, e
		}
		if !drained {
			return nil, fail("ANSWER_GAP")
		}
	}
	if e = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&st.now); e != nil {
		return nil, e
	}
	if !date(g, "expiresAt").After(st.now) || number(obj(v, "timing"), "remainingGrantMs") <= 100 {
		return nil, fail("GRANT_EXPIRED")
	}
	// Bootstrap proofs are also immutable; renewed proofs cannot rescue unused grants.
	if _, _, e = s.currentProof(ctx, tx, p, st, a, text(g, "permitId")); e != nil {
		return nil, e
	}
	st.limit = minTime(st.limit, date(g, "expiresAt"))
	execution := id("execution")
	binding := identity(a)
	binding["executionId"] = execution
	binding["grantId"] = g["grantId"]
	binding["generationId"] = st.b["generationId"]
	binding["guardianIncarnation"] = st.b["guardianIncarnation"]
	binding["consumedAt"] = stamp(st.now)
	record := Document{"receiptId": id("consumed"), "bootstrapId": st.b["bootstrapId"], "consumeRequestId": q["consumeRequestId"], "runtimePrincipalId": q["runtimePrincipalId"], "runtimeIncarnation": q["runtimeIncarnation"], "guardianPrincipalId": p.ID, "channelBinding": q["channelBinding"], "registrationHash": st.registration["registrationHash"], "registrationRevision": st.registration["revision"], "consumeIdentityHash": identityHash, "binding": binding}
	if e = s.Validate("ReceiverConsumption", record); e != nil {
		return nil, e
	}
	tag, e := tx.Exec(ctx, `UPDATE dl05_v2_grant_state SET state='CONSUMED' WHERE grant_id=$1 AND state='ISSUED'`, g["grantId"])
	if e != nil {
		return nil, e
	}
	if tag.RowsAffected() != 1 {
		return nil, fail("CONSUMPTION_UNKNOWN")
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_receiver_consumptions(execution_id,command_id,artifact_id,grant_id,consume_nonce,runtime_principal,guardian_principal,channel_binding,consume_identity,receipt_id,registration_hash,bootstrap_id,registration_revision,consumption,consumed_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`, execution, st.c["commandId"], a["artifactId"], g["grantId"], q["consumeRequestId"], q["runtimePrincipalId"], p.ID, q["channelBinding"], identityHash, record["receiptId"], st.registration["registrationHash"], st.b["bootstrapId"], number(st.registration, "revision"), record, st.now)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "INSERT INTO dl05_v2_execution_state VALUES($1,$2,'ACTIVE')", execution, st.c["commandId"])
	if e != nil {
		return nil, e
	}
	return Document{"requestId": q["requestId"], "consumeAuthorized": true, "consumption": record, "consumeTiming": timing(st.now, g, obj(v, "permit")), "summary": Document{"state": "CONSUMED", "receiptId": record["receiptId"]}}, nil
}
func (s *Store) metadata(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	if st.b == nil || q["bootstrapId"] != st.b["bootstrapId"] {
		return nil, fail("BOOTSTRAP_REQUIRED")
	}
	summary, e := s.summary(ctx, tx, st, text(q, "grantId"))
	if e != nil {
		return nil, e
	}
	if summary["state"] != "DRAINED" && summary["state"] != "FENCED" && (st.b["guardianIncarnation"] != p.Incarnation || text(st.registration, "state") != "ACTIVE") {
		summary["state"] = "UNKNOWN"
	}
	return Document{"requestId": q["requestId"], "summary": summary}, nil
}
