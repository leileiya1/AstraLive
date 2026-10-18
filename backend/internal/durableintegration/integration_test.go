package durableintegration

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"astralive/backend/db"
	"astralive/backend/internal/app"
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	d "astralive/backend/internal/durablelive"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/turnmanager"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"path/filepath"
)

// SQL is real. Session/provider rows, Guardian receipts and media range evidence
// below are controlled fixtures, explicitly not a production/GPU acceptance.
type harness struct {
	t                       *testing.T
	ctx                     context.Context
	s                       *d.Store
	a                       *Adapter
	p, j, g                 d.Principal
	run, room, sid, product string
	bundle                  c.PlanBundle
}

func (h *harness) exec(q string, args ...any) {
	h.t.Helper()
	if _, e := h.s.DB.Exec(h.ctx, q, args...); e != nil {
		h.t.Fatal(e)
	}
}
func obj(v any) d.Object {
	b, _ := json.Marshal(v)
	m, e := d.Decode(b)
	if e != nil {
		panic(e)
	}
	return m
}
func convert[T any](v any) T {
	b, _ := json.Marshal(v)
	var out T
	if e := json.Unmarshal(b, &out); e != nil {
		panic(e)
	}
	return out
}
func (h *harness) snapshot() c.RestoreSnapshot {
	h.t.Helper()
	r, e := h.a.RestoreContentPlan(h.ctx, c.RestoreContentPlanRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: h.p.TenantID, OwnerId: h.p.OwnerID, RunId: h.run})
	if e != nil {
		h.t.Fatal(e)
	}
	return r.Snapshot
}
func (h *harness) try(p d.Principal, op string, fields d.Object) (d.Object, error) {
	q := d.Object{"schemaVersion": "0.5", "contractRevision": d.RevisionName, "requestId": ids.New("req"), "tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": h.run}
	switch op {
	case "ResumeBroadcastRun", "ConfirmOutputFence", "AdmitTurn", "SaveContentPlan", "StopBroadcastRun", "MarkExecutionUnknown":
		q["expectedRevision"] = h.snapshot().Run.Revision
	case "ConfirmCheckpoint":
		q["expectedRevision"] = nil
	}
	for k, v := range fields {
		q[k] = v
	}
	b, _ := json.Marshal(q)
	return h.s.Call(h.ctx, p, op, b)
}
func (h *harness) call(p d.Principal, op string, fields d.Object) d.Object {
	h.t.Helper()
	v, e := h.try(p, op, fields)
	if e != nil {
		h.t.Fatalf("%s: %v", op, e)
	}
	return v
}
func newHarness(t *testing.T) *harness {
	t.Helper()
	dsn := os.Getenv("DURABLE_LIVE_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("dedicated PostgreSQL required")
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	if cfg.ConnConfig.Host != "127.0.0.1" || !strings.HasPrefix(cfg.ConnConfig.Database, "agent2_") {
		t.Fatal("refuse shared database")
	}
	pool, e := pgxpool.NewWithConfig(context.Background(), cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(pool.Close)
	if e = db.Migrate(context.Background(), pool); e != nil {
		t.Fatal(e)
	}
	id := ids.New("integration")
	h := &harness{t: t, ctx: context.Background(), s: d.New(pool, []string{"test-sink"}), run: id + "run", room: id + "room", sid: id + "session", product: id + "product"}
	h.p = d.Principal{Role: "CONTROL", TenantID: id + "tenant", OwnerID: id + "owner", InstanceID: id + "backend"}
	h.j = d.Principal{Role: "RUNTIME_JOURNAL", TenantID: h.p.TenantID, OwnerID: h.p.OwnerID, InstanceID: id + "runtime"}
	h.g = d.Principal{Role: "OUTPUT_GUARDIAN", TenantID: h.p.TenantID, OwnerID: h.p.OwnerID, InstanceID: id + "guardian"}
	h.a = &Adapter{Store: h.s, Principal: h.p}
	h.s.Facts = VerifyPayload(h.s)
	h.exec(`INSERT INTO config_principals VALUES($1,$2)`, h.p.TenantID, h.p.OwnerID)
	h.exec(`INSERT INTO avatars(id,name,engine) VALUES($1,'test','MOCK')`, id+"avatar")
	h.exec(`INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'test','mock','test')`, id+"voice")
	h.exec(`INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES($1,'商品','柔软舒适。适合日常穿着。',99,'CNY',5,ARRAY['XL'])`, h.product)
	h.exec(`INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES($1,'test',$2,$3,'test',$4)`, h.room, id+"avatar", id+"voice", h.product)
	h.exec(`INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')`, h.sid, h.room)
	for _, v := range [][2]string{{"room", h.room}, {"session", h.sid}, {"product", h.product}} {
		h.exec(`INSERT INTO resource_owners VALUES($1,$2,$3,$4)`, v[0], v[1], h.p.TenantID, h.p.OwnerID)
	}
	h.exec(`INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,jsonb_build_object('activeProductId',$5::text),'{}',clock_timestamp()+interval '1 hour')`, h.sid, h.p.TenantID, h.p.OwnerID, id+"binding", h.product)
	h.call(h.p, "CreateBroadcastRun", d.Object{"roomId": h.room, "idempotencyKey": "create", "recoveryPolicy": "MANUAL_ON_UNKNOWN"})
	product, e := h.s.ReadProduct(h.ctx, h.p, h.run)
	if e != nil {
		t.Fatal(e)
	}
	// Old planning timestamps prove that playback revalidates authoritative same-value facts.
	now := time.Now().Add(-3 * time.Second)
	h.bundle, e = contentplan.Build(contentplan.Input{Run: h.snapshot().Run, Snapshot: convert[c.ProductSnapshot](product.Snapshot), PlanID: ids.New("plan"), Revision: 1, Statements: []contentplan.Statement{
		{Text: "这是第一段讲解。"}, {Text: "这是第二段讲解。"}, {Text: "有 XL 尺码。", Facts: []c.FactDependency{{Kind: "SIZE_OPTIONS", ProductId: h.product, SourceVersion: product.Snapshot.SourceVersion, ValueHash: product.ValueHashes["SIZE_OPTIONS"], ValidatedAt: contentplan.Stamp(now), ExpiresAt: contentplan.Stamp(now.Add(2 * time.Second))}}},
	}}, contentplan.DefaultConfig(), now)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = h.manager().SavePlan(h.ctx, h.bundle); e != nil {
		t.Fatal(e)
	}
	out := h.call(h.p, "ResumeBroadcastRun", d.Object{"expectedPreviousEpoch": int64(0), "decisionId": ids.New("decision"), "idempotencyKey": "resume"})
	epoch := convert[c.ResumeBroadcastRunResponse](out).Run.RunEpoch
	if e = h.s.AttachSession(h.ctx, h.p, h.run, epoch, d.SessionAdmission{SessionID: h.sid, ProducerIncarnation: h.j.InstanceID, WorkerReady: true, CheckedAt: time.Now()}); e != nil {
		t.Fatal(e)
	}
	fence := h.call(h.g, "ConfirmOutputFence", d.Object{"runEpoch": epoch, "retiredEpoch": epoch - 1, "guardianId": h.g.InstanceID, "evidenceRef": "test-isolation-proof", "idempotencyKey": "fence"})
	h.call(h.j, "ConfirmRunFence", d.Object{"sessionId": h.sid, "runEpoch": epoch, "producerIncarnation": h.j.InstanceID, "guardianProofRef": "test-isolation-proof", "fenceReceiptId": fence["fenceReceiptId"], "idempotencyKey": "confirm"})
	return h
}
func (h *harness) manager() *turnmanager.Manager {
	h.t.Helper()
	m, e := turnmanager.New(h.a, h.a, Facts{Store: h.s, Principal: h.p, RunID: h.run}, turnmanager.Scope{TenantID: h.p.TenantID, OwnerID: h.p.OwnerID, RunID: h.run}, turnmanager.DefaultConfig(), nil)
	if e != nil {
		h.t.Fatal(e)
	}
	return m
}
func (h *harness) current() d.Object {
	h.t.Helper()
	var b []byte
	e := h.s.DB.QueryRow(h.ctx, `SELECT o.envelope FROM dl05_outbox o JOIN dl05_run_slots s ON s.active_attempt_id=o.attempt_id WHERE s.run_id=$1`, h.run).Scan(&b)
	if e != nil {
		h.t.Fatal(e)
	}
	v, e := d.Decode(b)
	if e != nil {
		h.t.Fatal(e)
	}
	return v
}
func (h *harness) start(cmd d.Object, prepare bool) {
	h.t.Helper()
	claims, e := h.s.ClaimBatch(h.ctx, h.p, 16)
	if e != nil {
		h.t.Fatal(e)
	}
	var selected *d.Claimed
	for i := range claims {
		if claims[i].Command["commandId"] == cmd["commandId"] {
			selected = &claims[i]
		}
	}
	if selected == nil {
		h.t.Fatal("no claim", claims)
	}
	if e = h.s.MarkSendStarted(h.ctx, h.p, *selected); e != nil {
		h.t.Fatal(e)
	}
	receipt := h.call(h.j, "JournalAccept", d.Object{"command": cmd, "producerIncarnation": h.j.InstanceID})
	permit := h.call(h.j, "AcquireOutputPermit", d.Object{"sessionId": h.sid, "runEpoch": cmd["runEpoch"], "producerIncarnation": h.j.InstanceID, "guardianId": h.g.InstanceID})
	request := d.Object{"commandId": cmd["commandId"], "attemptId": cmd["attemptId"], "runEpoch": cmd["runEpoch"], "producerIncarnation": h.j.InstanceID, "permitId": permit["permitId"], "requestHash": cmd["requestHash"], "expectedInboxRevision": receipt["revision"]}
	payload := convert[d.Object](cmd["payload"])
	if payload["mode"] == "COMMENT_QUESTION" {
		if _, e = h.try(h.j, "JournalStart", request); e == nil || e.Error() != "DEPENDENCY_UNAVAILABLE" {
			h.t.Fatal("unprepared comment must fail closed", e)
		}
		if !prepare {
			return
		}
		// Test-only in-process seam. No production Python operation exists until CCR ACK.
		if e = h.s.RecordAnswerText(h.ctx, h.j, h.run, cmd["commandId"].(string), "这款提供 XL 尺码，具体库存暂时无法查询。"); e != nil {
			h.t.Fatal(e)
		}
	}
	auth := h.call(h.j, "JournalStart", request)
	if auth["startAuthorized"] != true {
		h.t.Fatal(auth)
	}
	repeat := h.call(h.j, "JournalStart", request)
	if repeat["startAuthorized"] != false {
		h.t.Fatal("START replay", repeat)
	}
}
func (h *harness) checkpoint(cmd d.Object, state string, seq int64, prev []string) d.PlaybackCheckpoint {
	kind := map[string]string{"PLAYING": "SINK_ADMITTED", "LOCAL_MEDIA_DRAINED": "ALL_REQUIRED_DRAIN"}[state]
	return d.PlaybackCheckpoint{SchemaVersion: "0.5", ContractRevision: d.RevisionName, TenantId: h.p.TenantID, OwnerId: h.p.OwnerID, RunId: h.run, CheckpointId: ids.New("cp"), EventId: ids.New("event"), AttemptId: cmd["attemptId"].(string), SessionId: h.sid, UtteranceId: cmd["utteranceId"].(string), CommandId: cmd["commandId"].(string), RunEpoch: convert[c.RuntimeCommand](cmd).RunEpoch, ProducerIncarnation: h.j.InstanceID, ProducerSeq: seq, State: state, OccurredAt: contentplan.Stamp(time.Now()), Evidence: d.Evidence{EvidenceType: kind, EvidenceRef: "test-sink-proof", EvidenceHash: contentplan.Hash("test-sink-proof"), RequiredSinks: []string{"test-sink"}, SinkProofs: []d.SinkProof{{SinkId: "test-sink", Kind: "RTMP_PIPE_WRITE", GenerationId: 1, FirstAudioSample: 0, FinalAudioSampleExclusive: 32000, AudioConsumedThroughExclusive: 32000, FinalVideoFrame: 49, VideoConsumedThroughFrame: 49, Terminal: state != "PLAYING"}}, PredecessorCheckpointIds: prev, AudienceVisibility: "UNVERIFIED"}}
}
func (h *harness) drain(cmd d.Object) {
	h.t.Helper()
	playing := h.checkpoint(cmd, "PLAYING", 1, []string{})
	drain := h.checkpoint(cmd, "LOCAL_MEDIA_DRAINED", 2, []string{playing.CheckpointId})
	h.call(h.j, "ConfirmCheckpoint", d.Object{"checkpoint": playing})
	h.call(h.j, "ConfirmCheckpoint", d.Object{"checkpoint": drain})
	if e := h.s.CommitDrained(h.ctx, h.p, 32); e != nil {
		h.t.Fatal(e)
	}
	if e := h.s.CommitDrained(h.ctx, h.p, 32); e != nil {
		h.t.Fatal(e)
	}
	h.call(h.j, "ConfirmCheckpoint", d.Object{"checkpoint": drain})
}
func (h *harness) comment(m *turnmanager.Manager, n string) string {
	h.t.Helper()
	now := time.Now()
	event := platform.Event{EventID: h.run + ":receipt:" + n, TraceID: "trace_" + n, Platform: "test", PlatformRoomID: h.room, InternalRoomID: h.room, SessionID: h.sid, SourceEventID: "source_" + n, Content: "这款有 XL 码吗？", ReceivedAt: now, UserExternalID: "user_" + n}
	a := turnmanager.SelectionAdapter{Manager: m, Sources: turnmanager.PreservedSources{}}
	id, e := a.Dispatch(h.ctx, interaction.Selection{Members: []platform.Event{event}, Event: event, ProductID: h.product, Audience: 1, Priority: 60, Policy: "NONE", SelectedAt: now})
	if e != nil {
		h.t.Fatal(e)
	}
	return id
}
func TestPostgresManagerBoundaryCommentResume(t *testing.T) {
	h := newHarness(t)
	m := h.manager()
	v, e := m.Step(h.ctx)
	if e != nil || v.State != turnmanager.Explaining {
		t.Fatal(v, e)
	}
	first := h.current()
	h.start(first, false)
	h.comment(m, "one")
	v, e = m.Step(h.ctx)
	if e != nil || v.State != turnmanager.YieldPending {
		t.Fatal(v, e)
	}
	if h.current()["commandId"] != first["commandId"] {
		t.Fatal("parallel media")
	}
	h.drain(first)
	if h.snapshot().CompletedPrefix != 1 {
		t.Fatal("prefix")
	}
	v, e = m.Step(h.ctx)
	if e != nil || v.Source != "COMMENT" {
		t.Fatal(v, e)
	}
	answer := h.current()
	h.start(answer, true)
	h.drain(answer)
	// Recreate Manager: progress and budgets must come from SQL, not local memory.
	m = h.manager()
	v, e = m.Step(h.ctx)
	if e != nil || v.State != turnmanager.Resuming || v.Segment == nil || v.Segment.Sequence != 2 {
		t.Fatal(v, e)
	}
	if h.snapshot().CompletedPrefix != 1 {
		t.Fatal("comment advanced script cursor")
	}
	next := h.current()
	h.start(next, false)
	h.drain(next)
	// Size segment was planned >2 seconds ago and must refresh from the real product source.
	v, e = m.Step(h.ctx)
	if e != nil || v.Segment == nil || v.Segment.Sequence != 3 {
		t.Fatal(v, e)
	}
	size := h.current()
	h.start(size, false)
	h.drain(size)
	if h.snapshot().CompletedPrefix != 3 {
		t.Fatal("final prefix")
	}
	var n int
	if e = h.s.DB.QueryRow(h.ctx, `SELECT count(*) FROM dl05_attempts WHERE run_id=$1`, h.run).Scan(&n); e != nil || n != 4 {
		t.Fatal(n, e)
	}
	if _, e = m.Stop(h.ctx, ids.New("stop")); e != nil {
		t.Fatal(e)
	}
	v, e = h.manager().Step(h.ctx)
	if e != nil || v.State != turnmanager.Stopped {
		t.Fatal(v, e)
	}
}
func TestPostgresProjectionAuthorizationRevisionAndProduct(t *testing.T) {
	h := newHarness(t)
	snap := h.snapshot()
	p, e := h.a.ReadPolicy(h.ctx, snap)
	if e != nil || !p.HistoryComplete || !p.ProviderReady {
		t.Fatal(p, e)
	}
	h.comment(h.manager(), "candidate")
	if _, e = h.a.ReadPolicy(h.ctx, snap); e == nil || e.Error() != "STATE_CONFLICT" {
		t.Fatal("torn projection accepted", e)
	}
	wrong := *h.a
	wrong.Principal.OwnerID = "other"
	if _, e = wrong.ReadPolicy(h.ctx, h.snapshot()); e == nil || e.Error() != "FORBIDDEN" {
		t.Fatal("cross owner", e)
	}
	snap = h.snapshot()
	p, e = h.a.ReadPolicy(h.ctx, snap)
	if e != nil || len(p.Candidates) != 1 || len(p.Candidates[0].SourceIdentities) != 1 {
		t.Fatal(p, e)
	}
	h.exec(`UPDATE products SET stock=stock-1,updated_at=clock_timestamp() WHERE id=$1`, h.product)
	v, e := h.manager().Step(h.ctx)
	if e != nil || v.State != turnmanager.Recovering || v.Reason != "PLAN_CHANGED" {
		t.Fatal(v, e)
	}
}
func TestPostgresUnknownGapAndStopPriority(t *testing.T) {
	h := newHarness(t)
	m := h.manager()
	if _, e := m.Step(h.ctx); e != nil {
		t.Fatal(e)
	}
	cmd := h.current()
	h.start(cmd, false)
	playing := h.checkpoint(cmd, "PLAYING", 1, []string{})
	h.call(h.j, "ConfirmCheckpoint", d.Object{"checkpoint": playing})
	h.call(h.p, "MarkExecutionUnknown", d.Object{"runEpoch": cmd["runEpoch"], "attemptId": cmd["attemptId"], "reasonCode": "TEST_RUNTIME_CRASH", "lastKnownState": "PLAYING", "evidenceRef": "test-crash", "idempotencyKey": "unknown"})
	if e := h.s.CommitDrained(h.ctx, h.p, 32); e != nil {
		t.Fatal(e)
	}
	v, e := h.manager().Step(h.ctx)
	if e != nil || v.State != turnmanager.Recovering || h.snapshot().CompletedPrefix != 0 {
		t.Fatal(v, e)
	}
	decision := d.Decision{DecisionId: ids.New("decision"), OperatorId: h.p.InstanceID, Action: "SKIP_WITH_GAP", AttemptId: cmd["attemptId"].(string), Reason: "test operator explicitly accepts gap", CreatedAt: contentplan.Stamp(time.Now())}
	if e = h.s.ResolveUnknown(h.ctx, h.p, h.run, h.snapshot().Run.Revision, decision); e == nil || e.Error() != "OUTPUT_FENCE_UNPROVEN" {
		t.Fatal("skip without fence", e)
	}
	h.call(h.g, "ConfirmOutputFence", d.Object{"runEpoch": cmd["runEpoch"], "retiredEpoch": cmd["runEpoch"], "guardianId": h.g.InstanceID, "evidenceRef": "test-stop-proof", "idempotencyKey": "second-fence"})
	if e = h.s.ResolveUnknown(h.ctx, h.p, h.run, h.snapshot().Run.Revision, decision); e != nil {
		t.Fatal(e)
	}
	snap := h.snapshot()
	p, e := h.a.ReadPolicy(h.ctx, snap)
	if e != nil || len(p.GapDecisions) != 1 || snap.CompletedPrefix != 0 || snap.ResumeSequence != 2 || snap.Bundle.Segments[0].State != "INTERRUPTED" {
		t.Fatal(snap, p, e)
	}
	// Simulate a new legal, fenced physical term after isolating the old executor.
	// No shared process is touched; these are isolated SQL lifecycle fixtures.
	h.exec(`UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()-interval '1 second',phase='SEALED' WHERE run_id=$1`, h.run)
	resume := h.call(h.p, "ResumeBroadcastRun", d.Object{"expectedPreviousEpoch": snap.Run.RunEpoch, "decisionId": ids.New("resume"), "idempotencyKey": "resume-after-gap"})
	epoch := convert[c.ResumeBroadcastRunResponse](resume).Run.RunEpoch
	if e = h.s.AttachSession(h.ctx, h.p, h.run, epoch, d.SessionAdmission{SessionID: h.sid, ProducerIncarnation: h.j.InstanceID, WorkerReady: true, CheckedAt: time.Now()}); e != nil {
		t.Fatal(e)
	}
	fence := h.call(h.g, "ConfirmOutputFence", d.Object{"runEpoch": epoch, "retiredEpoch": epoch - 1, "guardianId": h.g.InstanceID, "evidenceRef": "test-new-epoch-proof", "idempotencyKey": "gap-fence"})
	h.call(h.j, "ConfirmRunFence", d.Object{"sessionId": h.sid, "runEpoch": epoch, "producerIncarnation": h.j.InstanceID, "guardianProofRef": "test-new-epoch-proof", "fenceReceiptId": fence["fenceReceiptId"], "idempotencyKey": "gap-confirm"})
	// The prior boundary belongs to an old epoch. Claim may use the free slot but
	// Manager must not try to consume that stale boundary as the new epoch's yield.
	v, e = h.manager().Step(h.ctx)
	if e != nil || v.Segment == nil || v.Segment.Sequence != 2 {
		t.Fatal("gap resume", v, e)
	}
	second := h.current()
	h.start(second, false)
	h.drain(second)
	v, e = h.manager().Step(h.ctx)
	if e != nil || v.Segment == nil || v.Segment.Sequence != 3 {
		t.Fatal("completed segment after gap replayed/blocked", v, e)
	}
	if _, e = m.Stop(h.ctx, ids.New("stop")); e != nil {
		t.Fatal(e)
	}
	if _, e = m.Resume(h.ctx, ids.New("resume")); e == nil {
		t.Fatal("revived Stop")
	}
}
func TestLiveAdmissionCannotBeEnabledByEnvironment(t *testing.T) {
	for _, v := range []string{"true", "TRUE", "1", "yes"} {
		if d.CheckLiveAdmission(v) == nil {
			t.Fatal(v)
		}
	}
	if d.CheckLiveAdmission("") != nil || d.CheckLiveAdmission("false") != nil {
		t.Fatal("legacy disabled")
	}
}

func TestPostgresManagedSessionLateLifecycleCannotAutoStart(t *testing.T) {
	h := newHarness(t)
	h.call(h.p, "StopBroadcastRun", d.Object{"idempotencyKey": "stop", "decisionId": ids.New("stop"), "reasonCode": "OPERATOR_STOP"})
	before := h.snapshot()
	service := app.New(h.s.DB, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = h.s
	for _, kind := range []string{"SESSION_READY", "SESSION_STARTED"} {
		applied, e := service.ApplyEvent(h.ctx, app.Event{SchemaVersion: "1.0", EventID: ids.New("event"), EventType: kind, SessionID: h.sid, TraceID: ids.New("trace"), OccurredAt: time.Now().UTC(), Source: "AI_RUNTIME", Payload: map[string]any{}})
		if e != nil || !applied {
			t.Fatal(e)
		}
	}
	after := h.snapshot()
	if after.Run.Revision != before.Run.Revision || after.Run.StopRevision != before.Run.StopRevision || after.Run.Status != "STOPPING" {
		t.Fatal("late lifecycle changed run", after)
	}
	for _, operation := range []func() error{
		func() error { _, e := service.Start(h.ctx, h.sid, "test"); return e },
		func() error { _, e := service.Interrupt(h.ctx, h.sid, "test", "FORCE"); return e },
		func() error {
			_, e := service.Speak(h.ctx, h.sid, "不得走旧问答", 100, "FORCE", "OPERATOR", "test", nil)
			return e
		},
	} {
		if e := operation(); e != app.ErrConflict {
			t.Fatal("legacy mode bypass", e)
		}
	}
}

func TestPostgresLegacyMigrationUpgradePreservesData(t *testing.T) {
	h := newHarness(t)
	schema := "upgrade_" + strings.ReplaceAll(ids.New("test"), "-", "_")
	quoted := pgx.Identifier{schema}.Sanitize()
	h.exec("CREATE SCHEMA " + quoted)
	cfg := h.s.DB.Config().Copy()
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	pool, e := pgxpool.NewWithConfig(h.ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	// The isolated schema is retained with the disposable cluster for inspection.
	if _, e = pool.Exec(h.ctx, `CREATE TABLE schema_migrations(name text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now())`); e != nil {
		t.Fatal(e)
	}
	files, e := filepath.Glob("../../db/migrations/00000[1-5]_*.sql")
	if e != nil || len(files) != 5 {
		t.Fatal(files, e)
	}
	for _, file := range files {
		b, e := os.ReadFile(file)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = pool.Exec(h.ctx, string(b)); e != nil {
			t.Fatal(e)
		}
		if _, e = pool.Exec(h.ctx, `INSERT INTO schema_migrations(name) VALUES($1)`, filepath.Base(file)); e != nil {
			t.Fatal(e)
		}
	}
	if _, e = pool.Exec(h.ctx, `INSERT INTO products(id,name,description,price,currency,stock) VALUES('old-product','old','preserved',9.90,'CNY',10)`); e != nil {
		t.Fatal(e)
	}
	if e = db.Migrate(h.ctx, pool); e != nil {
		t.Fatal(e)
	}
	if e = db.Migrate(h.ctx, pool); e != nil {
		t.Fatal(e)
	}
	var value string
	if e = pool.QueryRow(h.ctx, `SELECT description FROM products WHERE id='old-product'`).Scan(&value); e != nil || value != "preserved" {
		t.Fatal(value, e)
	}
	// Assert the registered versions, not only their count: missing or unexpected
	// migrations must not cancel each other out. Keep this list explicit on upgrade.
	wantMigrations := []string{
		"000001_init.sql",
		"000002_live_room_active_product.sql",
		"000003_user_configuration.sql",
		"000004_session_integration.sql",
		"000005_interaction_receipts.sql",
		"000006_durable_live.sql",
		"000007_answer_stream.sql",
	}
	var gotMigrations []string
	if e = pool.QueryRow(h.ctx, `SELECT array_agg(name ORDER BY name) FROM schema_migrations`).Scan(&gotMigrations); e != nil {
		t.Fatal(e)
	}
	if strings.Join(gotMigrations, "\n") != strings.Join(wantMigrations, "\n") {
		t.Fatalf("migration versions: got %v, want %v", gotMigrations, wantMigrations)
	}
}

func TestPostgresRealSchedulerSelectsMergedCommentsDuringScript(t *testing.T) {
	h := newHarness(t)
	controller, e := NewController(h.ctx, h.s, h.p, h.run, h.sid, interaction.DefaultConfig())
	if e != nil {
		t.Fatal(e)
	}
	defer controller.Scheduler.Stop()
	if _, e = controller.Manager.Step(h.ctx); e != nil {
		t.Fatal(e)
	}
	first := h.current()
	h.start(first, false)
	if e = controller.Refresh(h.ctx); e != nil {
		t.Fatal(e)
	}
	for _, id := range []string{"one", "two", "three"} {
		e = controller.Scheduler.Receive(h.ctx, platform.Event{EventID: "ingress_" + id, TraceID: "trace_" + id, Platform: "mock", PlatformRoomID: h.room, InternalRoomID: h.room, SessionID: h.sid, EventType: platform.Comment, SourceEventID: "source_" + id, UserExternalID: "user_" + id, Transport: "mock", Content: "这款有 XL 码吗？"})
		if e != nil {
			t.Fatal(e)
		}
	}
	if e = controller.Scheduler.Tick(h.ctx); e != nil {
		t.Fatal(e)
	}
	selected := controller.Scheduler.Snapshot()
	if selected.Counters.Merged != 2 || selected.Counters.Delivered != 1 || selected.Current == nil || len(selected.Current.Members) != 3 {
		t.Fatal(selected)
	}
	projection, e := h.a.ReadPolicy(h.ctx, h.snapshot())
	if e != nil || len(projection.Candidates) != 1 || len(projection.Candidates[0].SourceIdentities) != 3 {
		t.Fatal(projection, e)
	}
	choice, e := controller.Manager.Step(h.ctx)
	if e != nil || choice.State != turnmanager.YieldPending {
		t.Fatal(choice, e)
	}
	if h.current()["commandId"] != first["commandId"] {
		t.Fatal("Scheduler started a concurrent legacy talk")
	}
}
func TestPostgresFairnessBudgetSurvivesManagerRestart(t *testing.T) {
	h := newHarness(t)
	m := h.manager()
	if _, e := m.Step(h.ctx); e != nil {
		t.Fatal(e)
	}
	first := h.current()
	h.start(first, false)
	for _, id := range []string{"a", "b", "c", "d", "e"} {
		h.comment(m, id)
	}
	h.drain(first)
	for i := 0; i < 2; i++ {
		m = h.manager()
		choice, e := m.Step(h.ctx)
		if e != nil || choice.Source != "COMMENT" {
			t.Fatal(choice, e)
		}
		cmd := h.current()
		h.start(cmd, true)
		h.drain(cmd)
	}
	// Rebooting the policy object cannot reset the two-answer budget.
	choice, e := h.manager().Step(h.ctx)
	if e != nil || choice.Source != "SCRIPT" || choice.Segment == nil || choice.Segment.Sequence != 2 || choice.ConsecutiveAnswers != 2 {
		t.Fatal(choice, e)
	}
}
