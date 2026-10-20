// Package authority owns durable-live-2 SQL. It registers no network routes and
// invokes no external dependency while a database transaction is open.
package authority

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	legacy "astralive/backend/internal/durablelive"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Document is a persistence-domain value, not a second set of wire DTOs.
// Composition must inject the official Agent4 wire validator; no schema is copied.
type Document = map[string]any

// Actor is authenticated composition-root data. Never decode it from request JSON.
type Actor struct{ Role, Tenant, Owner, Room, ID, Incarnation, Producer string }
type Validator func(string, Document) error

// Assertions independently verifies actual answer assertions BEFORE Begin.
// A missing verifier fails closed, even for a claimed empty dependency list.
type Assertions func(context.Context, Actor, Document) error

// InstallationSource reads the CONTROL-owned physical source outside SQL locks.
type InstallationSource func(context.Context, Actor, Document) (Document, error)
type Store struct {
	// CheckpointProof independently verifies physical SINK_ADMITTED/FENCE_BARRIER before Begin.
	CheckpointProof    func(context.Context, Actor, Document) error
	DB                 *pgxpool.Pool
	Validate           Validator
	Assertions         Assertions
	InstallationSource InstallationSource
	Observer           func(context.Context, Actor, Document, Document) error
}
type Error struct{ Code string }

func (e *Error) Error() string          { return e.Code }
func fail(s string) error               { return &Error{s} }
func text(m Document, k string) string  { s, _ := m[k].(string); return s }
func obj(m Document, k string) Document { v, _ := m[k].(map[string]any); return v }
func list(m Document, k string) []any   { v, _ := m[k].([]any); return v }
func number(m Document, k string) int64 {
	switch v := m[k].(type) {
	case int64:
		return v
	case int:
		return int64(v)
	case json.Number:
		n, _ := v.Int64()
		return n
	}
	return 0
}
func canon(v any) []byte {
	b, e := legacy.Canonical(v)
	if e != nil {
		panic(e)
	}
	return b
}
func hash(v any) string      { return digest(canon(v)) }
func digest(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func clone(m Document) Document {
	v, e := legacyDecode(canon(m))
	if e != nil {
		panic(e)
	}
	return v
}
func without(m Document, keys ...string) Document {
	v := clone(m)
	for _, k := range keys {
		delete(v, k)
	}
	return v
}
func id(prefix string) string {
	var b [24]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic(e)
	}
	return prefix + "_" + hex.EncodeToString(b[:])
}
func stamp(t time.Time) string            { return t.UTC().Format("2006-01-02T15:04:05.000000Z") }
func date(m Document, k string) time.Time { v, _ := time.Parse(time.RFC3339Nano, text(m, k)); return v }
func row(r pgx.Row) (Document, error) {
	var b []byte
	if e := r.Scan(&b); e != nil {
		return nil, e
	}
	return legacyDecode(b)
}
func normalize(e error) error {
	if errors.Is(e, pgx.ErrNoRows) {
		return fail("RESOURCE_NOT_FOUND")
	}
	var p *pgconn.PgError
	if errors.As(e, &p) {
		switch p.Code {
		case "23505":
			return fail("COMMAND_CONFLICT")
		case "23503", "23514", "22P02":
			return fail("INVALID_ARGUMENT")
		case "55P03", "57014", "40001", "40P01":
			return fail("OVERLOADED")
		}
	}
	return e
}
func (s *Store) begin(ctx context.Context) (pgx.Tx, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "SET LOCAL lock_timeout='750ms'; SET LOCAL statement_timeout='3s'")
	if e != nil {
		tx.Rollback(ctx)
	}
	return tx, e
}
func validateScope(p Actor, c Document) error {
	if p.ID == "" || p.Incarnation == "" || p.Tenant == "" || p.Owner == "" || p.Room == "" {
		return fail("UNAUTHENTICATED")
	}
	if text(c, "tenantId") != p.Tenant || text(c, "ownerId") != p.Owner {
		return fail("FORBIDDEN")
	}
	return nil
}
func (s *Store) resolve(ctx context.Context, q Document) (Document, error) {
	command := text(q, "commandId")
	if command == "" {
		command = text(obj(q, "checkpoint"), "commandId")
	}
	if command == "" {
		command = text(obj(q, "command"), "commandId")
	}
	if command == "" {
		command = text(obj(q, "binding"), "commandId")
	}
	if command == "" {
		refs := obj(q, "references")
		artifact := text(refs, "artifactId")
		if artifact == "" {
			artifact = text(q, "answerArtifactId")
		}
		if artifact != "" {
			if e := s.DB.QueryRow(ctx, "SELECT command_id FROM dl05_answer_segments WHERE artifact_id=$1", artifact).Scan(&command); e != nil {
				return nil, e
			}
		}
		bootstrap := text(q, "bootstrapId")
		if command == "" && bootstrap != "" {
			if e := s.DB.QueryRow(ctx, "SELECT command_id FROM dl05_receiver_bootstraps WHERE bootstrap_id=$1", bootstrap).Scan(&command); e != nil {
				return nil, e
			}
		}
		if command == "" && text(q, "attemptId") != "" {
			if e := s.DB.QueryRow(ctx, "SELECT command_id FROM dl05_attempts WHERE attempt_id=$1", q["attemptId"]).Scan(&command); e != nil {
				return nil, e
			}
		}
	}
	return row(s.DB.QueryRow(ctx, "SELECT envelope FROM dl05_outbox WHERE command_id=$1", command))
}

type state struct {
	c, r, b             Document
	registration        Document
	now, limit          time.Time
	outputExpiry        time.Time
	inbox               string
	inboxRev, answerRev int64
	answerID            string
	producer            string
}

// lock serializes every v2 mutation, including Stop, on the EXISTING run row.
func (s *Store) lock(ctx context.Context, tx pgx.Tx, p Actor, c Document, historical bool) (*state, error) {
	st := &state{c: c}
	var desired, revision, runStatus string
	var stop, epoch int64
	var room, session string
	e := tx.QueryRow(ctx, `SELECT desired_state,contract_revision,status,stop_revision,run_epoch,room_id,COALESCE(current_session_id,''),clock_timestamp() FROM dl05_runs WHERE run_id=$1 AND tenant_id=$2 AND owner_id=$3 FOR UPDATE`, c["runId"], p.Tenant, p.Owner).Scan(&desired, &revision, &runStatus, &stop, &epoch, &room, &session, &st.now)
	if e != nil {
		return nil, e
	}
	if room != p.Room {
		return nil, fail("FORBIDDEN")
	}
	if revision != "durable-live-2" {
		return nil, fail("CONTRACT_REVISION_MISMATCH")
	}
	if e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, c["runId"], number(c, "runEpoch")).Scan(&st.producer); e != nil {
		return nil, e
	}
	st.r = Document{"roomId": room, "sessionId": session, "runEpoch": epoch}
	if !historical && (stop > 0 || desired == "STOPPED") {
		return nil, fail("RUN_STOPPED")
	}
	if !historical && (desired != "LIVE" || (runStatus != "LIVE" && runStatus != "RECOVERING")) {
		return nil, fail("STATE_CONFLICT")
	}
	if !historical && epoch != number(c, "runEpoch") {
		return nil, fail("STALE_RUN_EPOCH")
	}
	if !historical && session != text(c, "sessionId") {
		return nil, fail("COMMAND_CONFLICT")
	}
	if !historical {
		var phase string
		var le int64
		var until time.Time
		if e = tx.QueryRow(ctx, `SELECT phase,run_epoch,lease_expires_at FROM dl05_run_leases WHERE run_id=$1 FOR UPDATE`, c["runId"]).Scan(&phase, &le, &until); e != nil {
			return nil, e
		}
		if phase != "ACTIVE" || le != epoch || !until.After(st.now) {
			return nil, fail("LEASE_LOST")
		}
		st.limit = until
		var slot string
		if e = tx.QueryRow(ctx, `SELECT COALESCE(active_attempt_id,'') FROM dl05_run_slots WHERE run_id=$1 FOR UPDATE`, c["runId"]).Scan(&slot); e != nil {
			return nil, e
		}
		if slot != text(c, "attemptId") {
			return nil, fail("STATE_CONFLICT")
		}
		if _, e = tx.Exec(ctx, `SELECT turn_id FROM dl05_turns WHERE turn_id=$1 AND run_id=$2 FOR UPDATE`, c["turnId"], c["runId"]); e != nil {
			return nil, e
		}
		var attemptSession, command string
		var ae int64
		e = tx.QueryRow(ctx, `SELECT session_id,command_id,run_epoch FROM dl05_attempts WHERE attempt_id=$1 AND run_id=$2 FOR UPDATE`, c["attemptId"], c["runId"]).Scan(&attemptSession, &command, &ae)
		if e != nil {
			return nil, e
		}
		if attemptSession != session || command != text(c, "commandId") || ae != epoch {
			return nil, fail("COMMAND_CONFLICT")
		}
		var expiry time.Time
		var good bool
		e = tx.QueryRow(ctx, `SELECT b.expires_at,(s.status IN ('LIVE','DEGRADED') AND b.released_at IS NULL AND b.tenant_id=$2 AND b.user_id=$3 AND ro.active_product_id IS NOT DISTINCT FROM NULLIF(b.room_snapshot->>'activeProductId','')) FROM live_sessions s JOIN session_provider_bindings b ON b.session_id=s.id JOIN live_rooms ro ON ro.id=s.room_id WHERE s.id=$1 AND s.room_id=$4 FOR SHARE OF s,b,ro`, session, p.Tenant, p.Owner, room).Scan(&expiry, &good)
		if e != nil {
			return nil, e
		}
		if !good || !expiry.After(st.now) {
			return nil, fail("BINDING_EXPIRED")
		}
		if expiry.Before(st.limit) {
			st.limit = expiry
		}
		deadline := date(obj(c, "payload"), "expiresAt")
		if !deadline.After(st.now) {
			return nil, fail("COMMAND_EXPIRED")
		}
		if deadline.Before(st.limit) {
			st.limit = deadline
		}
	}
	if p.Role == "RUNTIME_JOURNAL" || p.Role == "OUTPUT_GUARDIAN" || p.Role == "OBSERVER" {
		var role, inc, producer string
		var revoked bool
		e = tx.QueryRow(ctx, `SELECT role,incarnation,COALESCE(producer,''),revoked_at IS NOT NULL FROM dl05_v2_processes WHERE principal_id=$1 AND tenant_id=$2 AND owner_id=$3 AND room_id=$4 FOR SHARE`, p.ID, p.Tenant, p.Owner, p.Room).Scan(&role, &inc, &producer, &revoked)
		if e != nil {
			return nil, fail("FORBIDDEN")
		}
		want := "REGISTERED_RUNTIME"
		if p.Role == "OUTPUT_GUARDIAN" || p.Role == "OBSERVER" {
			want = p.Role
		}
		if role != want || inc != p.Incarnation || revoked || (p.Role == "RUNTIME_JOURNAL" && (producer != p.Producer || producer != st.producer)) {
			return nil, fail("FORBIDDEN")
		}
	}
	e = tx.QueryRow(ctx, `SELECT status,revision FROM dl05_runtime_inbox WHERE command_id=$1 FOR UPDATE`, c["commandId"]).Scan(&st.inbox, &st.inboxRev)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	st.registration, e = row(tx.QueryRow(ctx, `SELECT jsonb_build_object('binding',b.binding,'registrationHash',b.registration_hash,'registeredAt',dl05_stamp(b.registered_at),'stageReceiptId',b.receipt->>'stageReceiptId','state',s.state,'revision',s.revision) FROM dl05_receiver_bootstraps b JOIN dl05_v2_registration_state s USING(bootstrap_id) WHERE b.command_id=$1`, c["commandId"]))
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	st.b = obj(st.registration, "binding")
	e = tx.QueryRow(ctx, `SELECT answer_id,answer_revision FROM dl05_answer_streams WHERE command_id=$1 FOR UPDATE`, c["commandId"]).Scan(&st.answerID, &st.answerRev)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	return st, nil
}
func (st *state) registered(ctx context.Context, tx pgx.Tx, p Actor) error {
	if st.b == nil {
		return fail("BOOTSTRAP_REQUIRED")
	}
	if text(st.registration, "state") != "ACTIVE" {
		return fail("REGISTRATION_REVOKED")
	}
	if p.Role == "RUNTIME_JOURNAL" && (text(st.b, "runtimePrincipalId") != p.ID || text(st.b, "runtimeIncarnation") != p.Incarnation || st.producer != p.Producer) {
		return fail("FORBIDDEN")
	}
	e := tx.QueryRow(ctx, `SELECT o.expires_at FROM dl05_v2_installations i JOIN dl05_v2_processes r ON r.principal_id=i.runtime_principal JOIN dl05_v2_processes g ON g.principal_id=i.guardian_principal JOIN dl05_room_outputs o ON o.room_id=$4 WHERE i.proof_id=$1 AND i.command_id=$2 AND i.retired_at IS NULL AND r.revoked_at IS NULL AND g.revoked_at IS NULL AND o.active_run_id=$3 AND o.output_binding_version=$5 AND o.guardian_id=$6 AND o.expires_at>clock_timestamp() AND ($7<>'OUTPUT_GUARDIAN' OR (g.principal_id=$8 AND g.incarnation=$9)) FOR SHARE OF i,r,g,o`, st.b["physicalInstallProofRef"], st.c["commandId"], st.c["runId"], p.Room, number(st.b, "outputBindingVersion"), st.b["guardianId"], p.Role, p.ID, p.Incarnation).Scan(&st.outputExpiry)
	if errors.Is(e, pgx.ErrNoRows) {
		return fail("REGISTRATION_REVOKED")
	}
	if e != nil {
		return e
	}
	// The SHARE lock on o serializes shortening/revocation with this transaction.
	// Time still advances under the lock: retain its actual deadline for the final
	// DB-clock check, never treat the initial validity predicate as a lasting proof.
	st.limit = minTime(st.limit, st.outputExpiry)
	return nil
}

// Call is an unmounted, validated persistence seam. Typed wire adapters are owned
// by Agent4; validation is mandatory and happens before any lookup or mutation.
func (s *Store) Call(ctx context.Context, p Actor, name string, q Document) (out Document, err error) {
	defer func() {
		if r := recover(); r != nil {
			out = nil
			err = fmt.Errorf("invalid domain value")
		}
	}()
	if !allowed(p.Role, name) {
		return nil, fail("FORBIDDEN")
	}
	if s.Validate == nil {
		return nil, fail("DEPENDENCY_UNAVAILABLE")
	}
	if err = s.Validate(name+"Request", q); err != nil {
		return nil, fail("INVALID_ARGUMENT")
	}
	if p.ID == "" || p.Incarnation == "" || p.Tenant == "" || p.Owner == "" || p.Room == "" {
		return nil, fail("UNAUTHENTICATED")
	}
	q = clone(q)
	if name == "StopBroadcastRun" {
		if q["tenantId"] != p.Tenant || q["ownerId"] != p.Owner {
			return nil, fail("FORBIDDEN")
		}
		return s.stopRun(ctx, p, q)
	}
	c, err := s.resolve(ctx, q)
	if err != nil {
		return nil, normalize(err)
	}
	if err = validateScope(p, c); err != nil {
		return nil, err
	}
	if text(c, "contractRevision") != "durable-live-2" {
		return nil, fail("CONTRACT_REVISION_MISMATCH")
	}
	// Preflight before Begin, including on duplicate reads. Never trust Runtime's assertion declarations.
	artifact := obj(q, "artifact")
	if artifact == nil {
		aid := text(q, "artifactId")
		if aid == "" {
			aid = text(obj(q, "references"), "artifactId")
		}
		if aid == "" {
			aid = text(q, "answerArtifactId")
		}
		if aid != "" {
			artifact, _ = row(s.DB.QueryRow(ctx, "SELECT descriptor FROM dl05_answer_segments WHERE artifact_id=$1 AND command_id=$2", aid, c["commandId"]))
		}
	}
	effect := name == "JournalPrepareAnswer" || name == "JournalStart" || name == "JournalStartAnswerSegment" || name == "AcquireOutputPermit" || name == "QueryReceiverAuthority" || name == "CommitReceiverConsume"
	if effect {
		if s.Assertions == nil || artifact == nil {
			return nil, fail("DEPENDENCY_UNAVAILABLE")
		}
		if err = s.Assertions(ctx, p, clone(artifact)); err != nil {
			return nil, err
		}
	}
	if name == "ConfirmCheckpoint" {
		cp := obj(q, "checkpoint")
		if cp["state"] == "PLAYING" || cp["state"] == "INTERRUPTED" {
			if s.CheckpointProof == nil {
				return nil, fail("OUTPUT_FENCE_UNPROVEN")
			}
			if err = s.CheckpointProof(ctx, p, clone(cp)); err != nil {
				return nil, err
			}
		}
	}
	tx, err := s.begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(context.Background())
	historical := name == "ConfirmCheckpoint" || name == "RevokeReceiverBootstrap" || name == "QueryReceiverConsumption" || name == "StopBroadcastRun" || name == "MarkExecutionUnknown" || ((name == "JournalQueryAnswer" || name == "QueryExecutionStatus") && (p.Role == "CONTROL" || p.Role == "CONTROL_REGISTRAR"))
	st, err := s.lock(ctx, tx, p, c, historical)
	if err != nil {
		return nil, normalize(err)
	}
	for _, key := range []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "requestHash", "producerIncarnation"} {
		if v, ok := q[key]; ok {
			want := c[key]
			if key == "producerIncarnation" {
				want = st.producer
			}
			if v != want {
				return nil, fail("COMMAND_CONFLICT")
			}
		}
	}
	if name != "JournalAccept" && name != "RegisterReceiverBootstrap" && name != "StopBroadcastRun" && name != "MarkExecutionUnknown" && name != "QueryReceiverConsumption" && !historical {
		if err = st.registered(ctx, tx, p); err != nil {
			return nil, err
		}
	}
	if effect {
		var sealed bool
		if err = tx.QueryRow(ctx, "SELECT executor_sealed_at IS NOT NULL FROM dl05_runtime_inbox WHERE command_id=$1", c["commandId"]).Scan(&sealed); err != nil {
			return nil, normalize(err)
		}
		if sealed {
			return nil, fail("RECOVERY_UNKNOWN")
		}
		if st.answerID != "" {
			var deadline time.Time
			if err = tx.QueryRow(ctx, "SELECT deadline FROM dl05_answer_streams WHERE command_id=$1", c["commandId"]).Scan(&deadline); err != nil {
				return nil, err
			}
			st.limit = minTime(st.limit, deadline)
			if !deadline.After(st.now) {
				return nil, fail("ANSWER_CLOSED")
			}
		}
	}
	switch name {
	case "JournalAccept":
		out, err = s.accept(ctx, tx, p, st, q)
	case "RegisterReceiverBootstrap":
		out, err = s.register(ctx, tx, p, st, q)
	case "RevokeReceiverBootstrap":
		out, err = s.revoke(ctx, tx, p, st, q)
	case "JournalPrepareAnswer":
		out, err = s.prepare(ctx, tx, p, st, q)
	case "AcquireOutputPermit":
		out, err = s.permit(ctx, tx, p, st, q)
	case "JournalStart", "JournalStartAnswerSegment":
		out, err = s.start(ctx, tx, p, st, q, name == "JournalStartAnswerSegment")
	case "QueryReceiverAuthority":
		out, err = s.snapshot(ctx, tx, p, st, q)
	case "CommitReceiverConsume":
		out, err = s.consume(ctx, tx, p, st, q)
	case "QueryReceiverConsumption":
		out, err = s.metadata(ctx, tx, p, st, q)
	case "JournalConfirmAnswerSegment":
		out, err = s.drain(ctx, tx, p, st, q)
	case "JournalSealAnswer":
		out, err = s.seal(ctx, tx, p, st, q)
	case "JournalQueryAnswer":
		out, err = s.answer(ctx, tx, p, st, q)
	case "ConfirmCheckpoint":
		out, err = s.confirm(ctx, tx, p, st, q)
	case "MarkExecutionUnknown":
		out, err = s.unknown(ctx, tx, p, st, q)
	case "QueryExecutionStatus":
		out, err = s.execution(ctx, tx, p, st, q)
	default:
		err = fail("RESOURCE_NOT_FOUND")
	}
	if err != nil {
		return nil, normalize(err)
	}
	if err = s.Validate(name+"Response", out); err != nil {
		return nil, fail("DEPENDENCY_UNAVAILABLE")
	}
	if !historical {
		var at time.Time
		if err = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&at); err != nil {
			return nil, err
		}
		if err = st.finalizeResponse(name, out, at); err != nil {
			return nil, err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return out, nil
}

// finalizeResponse runs after local validation and immediately before Commit.
// All authority/source rows remain locked. No application callback or external
// work runs between this DB-clock check and Commit. Replacing relative budgets
// does not alter immutable proofs or remove the receiver ACK/deadline checks.
func (st *state) finalizeResponse(name string, out Document, at time.Time) error {
	if !st.limit.After(at) {
		return fail("LEASE_LOST")
	}
	switch name {
	case "QueryReceiverAuthority":
		snap := obj(out, "snapshot")
		snap["authorityTime"] = stamp(at)
		snap["validUntil"] = stamp(st.limit)
		snap["timing"] = timing(at, obj(snap, "grant"), obj(snap, "permit"), st.limit)
	case "JournalStart", "JournalStartAnswerSegment", "CommitReceiverConsume":
		if out["startAuthorized"] == true || out["segmentStartAuthorized"] == true || out["consumeAuthorized"] == true {
			// Original first-response handshakes still require the frozen 100ms margin.
			if st.limit.Sub(at).Milliseconds() <= 100 {
				return fail("GRANT_EXPIRED")
			}
			remaining := st.limit.Sub(at).Milliseconds()
			out["consumeTiming"] = Document{"remainingGrantMs": remaining, "remainingProofMs": remaining, "safetyMarginMs": int64(100)}
		}
	}
	return nil
}

func timing(now time.Time, g, pm Document, limit time.Time) Document {
	grant := max(int64(0), minTime(date(g, "expiresAt"), limit).Sub(now).Milliseconds())
	proof := max(int64(0), minTime(date(pm, "expiresAt"), limit).Sub(now).Milliseconds())
	return Document{"remainingGrantMs": grant, "remainingProofMs": proof, "safetyMarginMs": int64(100)}
}
func secret() string {
	var b [32]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic(e)
	}
	return base64.RawURLEncoding.EncodeToString(b[:])
}

func legacyDecode(b []byte) (Document, error) {
	v, e := legacy.Decode(b)
	if e != nil {
		return nil, e
	}
	var normalize func(any) any
	normalize = func(x any) any {
		switch x := x.(type) {
		case json.Number:
			n, _ := x.Int64()
			return n
		case map[string]any:
			for k, v := range x {
				x[k] = normalize(v)
			}
			return x
		case []any:
			for i, v := range x {
				x[i] = normalize(v)
			}
			return x
		default:
			return x
		}
	}
	return normalize(v).(map[string]any), nil
}
