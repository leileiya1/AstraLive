package durablelive

import (
	"astralive/backend/db"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestFrozenSchemaAndGoldenVectors(t *testing.T) {
	root := "../../.."
	for _, file := range []string{"schema.json", "protocol.json", "state-machines.json"} {
		want, e := os.ReadFile(filepath.Join(root, "contracts/v0.5/durable-live", file))
		if e != nil {
			t.Fatal(e)
		}
		got, _ := specs.ReadFile("spec/" + file)
		if !bytes.Equal(want, got) {
			t.Fatalf("regenerate frozen closure: %s", file)
		}
	}
	raw, e := os.ReadFile(filepath.Join(root, "contracts/v0.5/durable-live/examples/hash-vectors.json"))
	if e != nil {
		t.Fatal(e)
	}
	vs, e := decodeArray(raw)
	if e != nil {
		t.Fatal(e)
	}
	for _, v := range vs {
		m := v.(map[string]any)
		b, e := Canonical(m["value"])
		if e != nil || string(b) != str(m, "canonicalUtf8") || textHash(string(b)) != str(m, "sha256") {
			t.Fatalf("golden vector mismatch: %v", e)
		}
	}
	raw, e = os.ReadFile(filepath.Join(root, "contracts/v0.5/durable-live/examples/protocol.json"))
	if e != nil {
		t.Fatal(e)
	}
	vs, e = decodeArray(raw)
	if e != nil {
		t.Fatal(e)
	}
	for _, v := range vs {
		m := v.(map[string]any)
		op, e := operation(str(m, "operationId"))
		if e != nil {
			t.Fatal(e)
		}
		if e = validate(strings.TrimPrefix(op.RequestSchema, "#/$defs/"), m["request"]); e != nil {
			t.Fatal(op.OperationID, e)
		}
		if e = validate(strings.TrimPrefix(op.ResponseSchema, "#/$defs/"), m["response"]); e != nil {
			t.Fatal(op.OperationID, e)
		}
	}
}
func TestStrictJSON(t *testing.T) {
	for _, bad := range []string{`{"x":1,"x":2}`, `{"x":1.0}`, `{"x":1e2}`, `{"x":9007199254740992}`, `{"x":true} {}`, `{"x":NaN}`} {
		if _, e := Decode([]byte(bad)); e == nil {
			t.Fatal(bad)
		}
	}
}

type fixture struct {
	t                             *testing.T
	s                             *Store
	ctx                           context.Context
	p, j, g                       Principal
	runID, roomID, sid, productID string
	epoch                         int64
}

func testDB(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DURABLE_LIVE_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required: DURABLE_LIVE_TEST_DATABASE_URL")
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	if !strings.HasPrefix(cfg.ConnConfig.Database, "agent2_") || cfg.ConnConfig.Host != "127.0.0.1" {
		t.Fatal("refuse non-isolated database")
	}
	cfg.MaxConns = 12
	p, e := pgxpool.NewWithConfig(context.Background(), cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(p.Close)
	if e = db.Migrate(context.Background(), p); e != nil {
		t.Fatal(e)
	}
	return p
}
func newFixture(t *testing.T, active bool) *fixture {
	t.Helper()
	pool := testDB(t)
	id := freshID("test")
	f := &fixture{t: t, ctx: context.Background(), s: New(pool, []string{"test-sink"}), runID: id + "run", roomID: id + "room", sid: id + "session", productID: id + "product"}
	f.p = Principal{"CONTROL", id + "tenant", id + "owner", id + "backend"}
	f.j = Principal{"RUNTIME_JOURNAL", f.p.TenantID, f.p.OwnerID, id + "runtime"}
	f.g = Principal{"OUTPUT_GUARDIAN", f.p.TenantID, f.p.OwnerID, id + "guardian"}
	f.exec(`INSERT INTO config_principals VALUES($1,$2)`, f.p.TenantID, f.p.OwnerID)
	f.exec(`INSERT INTO avatars(id,name,engine) VALUES($1,'test','MOCK')`, id+"avatar")
	f.exec(`INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'test','mock','test')`, id+"voice")
	f.exec(`INSERT INTO products(id,name,description,price,currency,stock) VALUES($1,'test','test',1,'CNY',5)`, f.productID)
	f.exec(`INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES($1,'test',$2,$3,'test',$4)`, f.roomID, id+"avatar", id+"voice", f.productID)
	f.exec(`INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')`, f.sid, f.roomID)
	for _, v := range [][2]string{{"room", f.roomID}, {"session", f.sid}, {"product", f.productID}} {
		f.exec(`INSERT INTO resource_owners VALUES($1,$2,$3,$4)`, v[0], v[1], f.p.TenantID, f.p.OwnerID)
	}
	f.exec(`INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,$5,'{}',clock_timestamp()+interval '1 hour')`, f.sid, f.p.TenantID, f.p.OwnerID, id+"binding", Object{"activeProductId": f.productID})
	f.call(f.p, "CreateBroadcastRun", Object{"roomId": f.roomID, "idempotencyKey": "create", "recoveryPolicy": "MANUAL_ON_UNKNOWN"})
	if active {
		f.activate()
	}
	return f
}
func (f *fixture) exec(q string, args ...any) {
	f.t.Helper()
	if _, e := f.s.DB.Exec(f.ctx, q, args...); e != nil {
		f.t.Fatal(e)
	}
}
func (f *fixture) run() Object {
	f.t.Helper()
	tx, e := f.s.begin(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	r, e := loadRun(f.ctx, tx, f.runID, false)
	if e != nil {
		f.t.Fatal(e)
	}
	return r
}
func (f *fixture) req(name string, fields Object) Object {
	q := Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "requestId": freshID("req"), "tenantId": f.p.TenantID, "ownerId": f.p.OwnerID, "runId": f.runID}
	if name != "CreateBroadcastRun" {
		r := f.run()
		switch name {
		case "SaveContentPlan", "AdmitTurn", "ClaimNextTurn", "DispatchTurn", "ResumeBroadcastRun", "StopBroadcastRun", "YieldAtSegmentBoundary", "MarkExecutionUnknown", "ConfirmOutputFence":
			q["expectedRevision"] = r["revision"]
		case "ConfirmCheckpoint":
			q["expectedRevision"] = nil
		}
	}
	for k, v := range fields {
		q[k] = v
	}
	return q
}
func (f *fixture) try(p Principal, name string, fields Object) (Object, error) {
	q := f.req(name, fields)
	b, _ := json.Marshal(q)
	return f.s.Call(f.ctx, p, name, b)
}
func (f *fixture) call(p Principal, name string, fields Object) Object {
	f.t.Helper()
	r, e := f.try(p, name, fields)
	if e != nil {
		f.t.Fatalf("%s: %v", name, e)
	}
	return r
}
func (f *fixture) activate() {
	r := f.run()
	out := f.call(f.p, "ResumeBroadcastRun", Object{"idempotencyKey": freshID("resume"), "expectedPreviousEpoch": r["runEpoch"], "decisionId": freshID("decision")})
	f.epoch = num(obj(out, "run"), "runEpoch")
	if e := f.s.AttachSession(f.ctx, f.p, f.runID, f.epoch, SessionAdmission{f.sid, f.j.InstanceID, true, time.Now()}); e != nil {
		f.t.Fatal(e)
	}
	fence := f.call(f.g, "ConfirmOutputFence", Object{"runEpoch": f.epoch, "guardianId": f.g.InstanceID, "retiredEpoch": f.epoch - 1, "evidenceRef": freshID("physical-close"), "idempotencyKey": freshID("fence")})
	var proof string
	if e := f.s.DB.QueryRow(f.ctx, `SELECT output_fence_proof FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, f.runID, f.epoch).Scan(&proof); e != nil {
		f.t.Fatal(e)
	}
	f.call(f.j, "ConfirmRunFence", Object{"sessionId": f.sid, "runEpoch": f.epoch, "producerIncarnation": f.j.InstanceID, "guardianProofRef": proof, "fenceReceiptId": fence["fenceReceiptId"], "idempotencyKey": freshID("confirm")})
}
func (f *fixture) turn(typ string, seg, plan any) Object {
	id := freshID("turn")
	t := Object{"tenantId": f.p.TenantID, "ownerId": f.p.OwnerID, "runId": f.runID, "turnId": id, "planId": plan, "turnType": typ, "sourceSegmentId": seg, "sourceCommentTraceId": nil, "sourceIdentities": []any{}, "priority": int64(20), "state": "READY", "scheduledAt": stamp(time.Now().Add(-time.Second)), "startedAt": nil, "finishedAt": nil, "expiresAt": nil, "inputText": "隔离测试口播", "idempotencyKey": "turn:" + id, "revision": int64(1)}
	if typ == "COMMENT" {
		t["sourceCommentTraceId"] = freshID("trace")
		t["priority"] = int64(60)
		t["expiresAt"] = stamp(time.Now().Add(time.Minute))
		t["sourceIdentities"] = []any{Object{"sourceReceiptId": freshID("source"), "platform": "test", "platformRoomId": f.roomID, "sourceEventId": freshID("event"), "traceId": t["sourceCommentTraceId"]}}
	}
	return t
}
func (f *fixture) claim(t Object) Object {
	f.t.Helper()
	f.call(f.p, "AdmitTurn", Object{"idempotencyKey": "admit:" + str(t, "turnId"), "turn": t})
	snap := f.call(f.p, "RestoreContentPlan", Object{})
	slot := obj(obj(snap, "snapshot"), "slot")
	return f.call(f.p, "ClaimNextTurn", Object{"runEpoch": f.epoch, "candidateTurnId": t["turnId"], "expectedSlotVersion": slot["slotVersion"], "idempotencyKey": "claim:" + str(t, "turnId")})
}
func (f *fixture) send() Claimed {
	f.t.Helper()
	a, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(a) != 1 {
		f.t.Fatalf("claimbatch %d %v", len(a), e)
	}
	if e = f.s.MarkSendStarted(f.ctx, f.p, a[0]); e != nil {
		f.t.Fatal(e)
	}
	return a[0]
}
func (f *fixture) accept(c Claimed) Object {
	return f.call(f.j, "JournalAccept", Object{"command": c.Command, "producerIncarnation": f.j.InstanceID})
}
func (f *fixture) start(c Claimed, accepted Object) Object {
	permit := f.call(f.j, "AcquireOutputPermit", Object{"sessionId": f.sid, "runEpoch": f.epoch, "producerIncarnation": f.j.InstanceID, "guardianId": f.g.InstanceID})
	return f.call(f.j, "JournalStart", Object{"commandId": c.Command["commandId"], "attemptId": c.Command["attemptId"], "runEpoch": f.epoch, "producerIncarnation": f.j.InstanceID, "permitId": permit["permitId"], "requestHash": c.Command["requestHash"], "expectedInboxRevision": accepted["revision"]})
}
func (f *fixture) tick() {
	f.t.Helper()
	if e := (&Coordinator{f.s, f.p, 32}).Tick(f.ctx); e != nil {
		f.t.Fatal(e)
	}
}
func (f *fixture) count(q string, args ...any) int {
	f.t.Helper()
	var n int
	if e := f.s.DB.QueryRow(f.ctx, q, args...).Scan(&n); e != nil {
		f.t.Fatal(e)
	}
	return n
}
func wantCode(t *testing.T, e error, code string) {
	t.Helper()
	var f *Fault
	if !errors.As(e, &f) || f.Code != code {
		t.Fatalf("want %s, got %v", code, e)
	}
}
func TestPostgresAtomicOutboxCommitAndResponseLoss(t *testing.T) {
	f := newFixture(t, true)
	turn := f.turn("COMMENT", nil, nil)
	out := f.claim(turn)
	if f.count(`SELECT count(*) FROM utterances u JOIN dl05_attempts a ON a.utterance_id=u.id JOIN dl05_outbox o ON o.command_id=a.command_id JOIN dl05_turns t ON t.turn_id=a.turn_id WHERE t.turn_id=$1`, turn["turnId"]) != 1 {
		t.Fatal("not atomic")
	}
	again := f.call(f.p, "ClaimNextTurn", Object{"runEpoch": f.epoch, "candidateTurnId": turn["turnId"], "expectedSlotVersion": int64(1), "idempotencyKey": "claim:" + str(turn, "turnId")})
	if obj(again, "attempt")["attemptId"] != obj(out, "attempt")["attemptId"] {
		t.Fatal("duplicate attempt")
	}
	f.s = New(f.s.DB, []string{"test-sink"})
	c := f.send()
	if c.Command["utteranceId"] != obj(out, "attempt")["utteranceId"] {
		t.Fatal("identity changed")
	}
}
func TestPostgresRollbackNoPartialAttempt(t *testing.T) {
	f := newFixture(t, true)
	turn := f.turn("COMMENT", nil, nil)
	f.call(f.p, "AdmitTurn", Object{"idempotencyKey": "admit", "turn": turn})
	f.exec(`INSERT INTO interaction_receipts(session_id,trace_id,status) VALUES($1,$2,'RESERVED')`, f.sid, turn["sourceCommentTraceId"])
	_, e := f.try(f.p, "ClaimNextTurn", Object{"runEpoch": f.epoch, "candidateTurnId": turn["turnId"], "expectedSlotVersion": int64(1), "idempotencyKey": "claim"})
	wantCode(t, e, "COMMAND_CONFLICT")
	if f.count(`SELECT count(*) FROM utterances WHERE session_id=$1`, f.sid) != 0 || f.count(`SELECT count(*) FROM dl05_attempts WHERE run_id=$1`, f.runID) != 0 {
		t.Fatal("partial transaction")
	}
}
func TestPostgresLost202ReattachNoReplay(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	accepted := f.accept(c)
	f.start(c, accepted)
	if e := f.s.recordSend(f.ctx, f.p, c, nil, context.DeadlineExceeded); e != nil {
		t.Fatal(e)
	}
	f.s = New(f.s.DB, []string{"test-sink"})
	f.tick()
	status := f.call(f.p, "QueryExecutionStatus", Object{"commandId": c.Command["commandId"], "runEpoch": f.epoch})
	if str(obj(status, "status"), "state") != "STARTED" {
		t.Fatal(status)
	}
	if str(f.accept(c), "state") != "STARTED" {
		t.Fatal("lost state")
	}
	if f.start(c, accepted)["startAuthorized"] != false {
		t.Fatal("replayed START authorization")
	}
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 0 {
		t.Fatal("replayed outbox", e)
	}
}
func TestPostgresRuntimeCrashUnknownAndOrphanBusyProjection(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	f.start(c, f.accept(c))
	f.exec(`UPDATE dl05_output_permits SET revoked_at=clock_timestamp() WHERE run_id=$1`, f.runID)
	f.tick()
	status := f.call(f.p, "QueryExecutionStatus", Object{"commandId": c.Command["commandId"], "runEpoch": f.epoch})
	if str(obj(status, "status"), "state") != "UNKNOWN" {
		t.Fatal(status)
	}
	if f.count(`SELECT count(*) FROM utterances WHERE session_id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED')`, f.sid) != 0 {
		t.Fatal("permanent legacy busy orphan")
	}
	snap := f.call(f.p, "RestoreContentPlan", Object{})
	if obj(obj(snap, "snapshot"), "slot")["activeAttemptId"] == nil {
		t.Fatal("UNKNOWN freed slot without fence")
	}
}
func TestPostgresMissingInboxIsUnknown(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	if e := f.s.recordSend(f.ctx, f.p, c, nil, context.DeadlineExceeded); e != nil {
		t.Fatal(e)
	}
	f.tick()
	out := f.call(f.p, "QueryExecutionStatus", Object{"commandId": c.Command["commandId"], "runEpoch": f.epoch})
	if str(obj(out, "status"), "state") != "UNKNOWN" {
		t.Fatal(out)
	}
}
func TestPostgresLeaseCompetitionAndOldEpoch(t *testing.T) {
	f := newFixture(t, false)
	q := f.req("ResumeBroadcastRun", Object{"idempotencyKey": "race", "expectedPreviousEpoch": int64(0), "decisionId": freshID("decision")})
	raw, _ := json.Marshal(q)
	var wg sync.WaitGroup
	for _, id := range []string{"owner-one", "owner-two"} {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			p := f.p
			p.InstanceID = id
			_, _ = f.s.Call(f.ctx, p, "ResumeBroadcastRun", raw)
		}(id)
	}
	wg.Wait()
	var leaseOwner string
	var epoch, version int64
	if e := f.s.DB.QueryRow(f.ctx, `SELECT lease_owner,run_epoch,lease_version FROM dl05_run_leases WHERE run_id=$1`, f.runID).Scan(&leaseOwner, &epoch, &version); e != nil {
		t.Fatal(e)
	}
	loser := f.p
	loser.InstanceID = "owner-one"
	if leaseOwner == loser.InstanceID {
		loser.InstanceID = "owner-two"
	}
	_, e := f.s.RenewLease(f.ctx, loser, f.runID, epoch, version)
	wantCode(t, e, "LEASE_LOST")
	f.exec(`UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1`, f.runID)
	f.tick()
	next := f.call(f.p, "ResumeBroadcastRun", Object{"idempotencyKey": "takeover", "expectedPreviousEpoch": epoch, "decisionId": freshID("decision")})
	if num(obj(next, "run"), "runEpoch") != epoch+1 {
		t.Fatal(next)
	}
	_, e = f.s.RenewLease(f.ctx, loser, f.runID, epoch, version)
	wantCode(t, e, "LEASE_LOST")
	_, e = f.try(f.j, "AcquireOutputPermit", Object{"sessionId": f.sid, "runEpoch": epoch, "producerIncarnation": f.j.InstanceID, "guardianId": f.g.InstanceID})
	wantCode(t, e, "STALE_RUN_EPOCH")
}
func TestPostgresStopWinsRecoveryAndUnsentOrphan(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); _ = (&Coordinator{f.s, f.p, 32}).Tick(f.ctx) }()
	f.call(f.p, "StopBroadcastRun", Object{"idempotencyKey": "stop", "decisionId": freshID("decision"), "reasonCode": "OPERATOR_STOP", "expectedRevision": int64(1)})
	wg.Wait()
	f.tick()
	if str(f.run(), "desiredState") != "STOPPED" {
		t.Fatal("stop lost")
	}
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil {
		t.Fatal(e)
	}
	for _, c := range claims {
		if str(c.Intent, "operation") != "STOP_RUN" {
			t.Fatal("media resurrected")
		}
	}
	if f.count(`SELECT count(*) FROM utterances WHERE session_id=$1 AND status='QUEUED'`, f.sid) != 0 {
		t.Fatal("unsent orphan")
	}
	_, e = f.try(f.p, "ResumeBroadcastRun", Object{"idempotencyKey": "bad-resume", "expectedPreviousEpoch": f.epoch, "decisionId": freshID("decision")})
	wantCode(t, e, "RUN_STOPPED")
}
func TestPostgresBindingExpiryAndWorkerUnavailable(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	f.exec(`UPDATE session_provider_bindings SET expires_at=clock_timestamp()-interval '1 second' WHERE session_id=$1`, f.sid)
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 0 {
		t.Fatal("expired binding sent")
	}
	f.tick()
	if f.count(`SELECT count(*) FROM utterances WHERE session_id=$1 AND status='QUEUED'`, f.sid) != 0 {
		t.Fatal("expired orphan")
	}
	g := newFixture(t, false)
	g.call(g.p, "ResumeBroadcastRun", Object{"idempotencyKey": "resume", "expectedPreviousEpoch": int64(0), "decisionId": freshID("decision")})
	e = g.s.AttachSession(g.ctx, g.p, g.runID, 1, SessionAdmission{g.sid, g.j.InstanceID, false, time.Now()})
	wantCode(t, e, "DEPENDENCY_UNAVAILABLE")
}
func TestPostgresNoCrossSessionOrPayloadConflict(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	cmd := wire(c.Command)
	cmd["sessionId"] = "another-session"
	cmd["requestHash"] = commandHash(cmd)
	_, e := f.try(f.j, "JournalAccept", Object{"command": cmd, "producerIncarnation": f.j.InstanceID})
	wantCode(t, e, "COMMAND_CONFLICT")
	p := f.j
	p.OwnerID = "someone-else"
	_, e = f.try(p, "QueryExecutionStatus", Object{"commandId": c.Command["commandId"], "runEpoch": f.epoch})
	wantCode(t, e, "FORBIDDEN")
}
func TestPostgresSkipLockedAndNoCrossRoomWait(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, `SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE`, f.runID); e != nil {
		t.Fatal(e)
	}
	before := time.Now()
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 0 || time.Since(before) > 500*time.Millisecond {
		t.Fatalf("SKIP LOCKED stalled %s %v", time.Since(before), e)
	}
}
