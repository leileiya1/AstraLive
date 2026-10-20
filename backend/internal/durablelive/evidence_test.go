package durablelive

import (
	"astralive/backend/db"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func (f *fixture) cp(c Claimed, state string, seq int64, predecessors []any) Object {
	a := Object{"tenantId": f.p.TenantID, "ownerId": f.p.OwnerID, "runId": f.runID, "attemptId": c.Command["attemptId"], "sessionId": f.sid, "utteranceId": c.Command["utteranceId"], "commandId": c.Command["commandId"], "runEpoch": f.epoch, "requiredSinks": obj(c.Command, "payload")["requiredSinks"]}
	kind := map[string]string{"PLAYING": "SINK_ADMITTED", "LOCAL_MEDIA_DRAINED": "ALL_REQUIRED_DRAIN", "COMPLETED": "BUSINESS_COMMIT"}[state]
	cp := systemCheckpoint(a, state, kind, f.j.InstanceID, freshID("sinkproof"))
	cp["producerSeq"] = seq
	ev := obj(cp, "evidence")
	ev["predecessorCheckpointIds"] = predecessors
	ev["sinkProofs"] = []any{Object{"sinkId": "test-sink", "kind": "RTMP_PIPE_WRITE", "generationId": int64(1), "firstAudioSample": int64(0), "finalAudioSampleExclusive": int64(32000), "audioConsumedThroughExclusive": int64(32000), "finalVideoFrame": int64(49), "videoConsumedThroughFrame": int64(49), "terminal": state != "PLAYING"}}
	return cp
}
func (f *fixture) plan(n int) Object {
	planID := freshID("plan")
	snapshot := Object{"productId": f.productID, "name": "测试商品", "description": "冻结描述", "sizes": []any{}, "sourceVersion": "test-version-1"}
	plan := Object{"tenantId": f.p.TenantID, "ownerId": f.p.OwnerID, "runId": f.runID, "planId": planID, "productId": f.productID, "productSnapshotVersion": hash(snapshot), "revision": int64(1), "segmentOrder": []any{}, "generationSource": Object{"kind": "OPERATOR", "reference": "test-input", "modelVersion": nil, "promptVersion": nil}, "snapshot": snapshot, "createdAt": stamp(time.Now()), "updatedAt": stamp(time.Now())}
	segments := []any{}
	order := []any{}
	for i := 1; i <= n; i++ {
		id := freshID("segment")
		content := "这段测试文案保持原样。"
		seg := Object{"tenantId": f.p.TenantID, "ownerId": f.p.OwnerID, "runId": f.runID, "segmentId": id, "planId": planID, "sequence": int64(i), "content": content, "textHash": textHash(content), "state": "READY", "utteranceId": nil, "idempotencyKey": "segment:" + id + ":initial", "checkpointState": "PLANNED", "estimatedDurationMs": int64(3000), "factDependencies": []any{}, "createdAt": stamp(time.Now()), "updatedAt": stamp(time.Now())}
		segments = append(segments, seg)
		order = append(order, id)
	}
	plan["segmentOrder"] = order
	return Object{"plan": plan, "segments": segments}
}
func TestPostgresCheckpointOrderingDuplicateAndBusinessCommit(t *testing.T) {
	f := newFixture(t, false)
	bundle := f.plan(2)
	f.call(f.p, "SaveContentPlan", Object{"idempotencyKey": "plan", "bundle": bundle})
	f.activate()
	seg := arr(bundle, "segments")[0].(map[string]any)
	turn := f.turn("SCRIPT", seg["segmentId"], obj(bundle, "plan")["planId"])
	turn["inputText"] = seg["content"]
	f.claim(turn)
	c := f.send()
	f.start(c, f.accept(c))
	playing := f.cp(c, "PLAYING", 1, []any{})
	drain := f.cp(c, "LOCAL_MEDIA_DRAINED", 2, []any{playing["checkpointId"]})
	out := f.call(f.j, "ConfirmCheckpoint", Object{"checkpoint": drain})
	if str(out, "disposition") != "PENDING" {
		t.Fatal(out)
	}
	f.call(f.j, "ConfirmCheckpoint", Object{"checkpoint": playing})
	out = f.call(f.j, "ConfirmCheckpoint", Object{"checkpoint": playing})
	if str(out, "disposition") != "DUPLICATE" {
		t.Fatal(out)
	}
	commit := f.cp(c, "COMPLETED", 1, []any{drain["checkpointId"]})
	commit["producerIncarnation"] = f.p.InstanceID
	out = f.call(f.p, "ConfirmCheckpoint", Object{"checkpoint": commit, "expectedRevision": f.run()["revision"]})
	if !out["applied"].(bool) || num(out, "completedPrefix") != 1 {
		t.Fatal(out)
	}
	snap := f.call(f.p, "RestoreContentPlan", Object{})
	slot := obj(obj(snap, "snapshot"), "slot")
	if slot["activeAttemptId"] != nil {
		t.Fatal("completion did not free slot")
	}
	yield := f.call(f.p, "YieldAtSegmentBoundary", Object{"runEpoch": f.epoch, "boundaryCheckpointId": commit["checkpointId"], "expectedSlotVersion": slot["slotVersion"], "idempotencyKey": "yield"})
	if str(yield, "state") != "YIELDED" {
		t.Fatal(yield)
	}
	f.call(f.p, "YieldAtSegmentBoundary", Object{"runEpoch": f.epoch, "boundaryCheckpointId": commit["checkpointId"], "expectedSlotVersion": slot["slotVersion"], "idempotencyKey": "yield"})
	conflict := wire(playing)
	obj(conflict, "evidence")["evidenceRef"] = "different-proof"
	_, e := f.try(f.j, "ConfirmCheckpoint", Object{"checkpoint": conflict})
	wantCode(t, e, "EVIDENCE_CONFLICT")
	notifications := 0
	if e = f.s.DeliverNotifications(f.ctx, f.p, 32, func(context.Context, string, PlaybackCheckpoint) error { notifications++; return nil }); e != nil || notifications != 6 {
		t.Fatal("notification recovery", notifications, e)
	}
}
func TestPostgresRejectFakeCompletionAndOldEpochEvent(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	f.start(c, f.accept(c))
	cp := f.cp(c, "COMPLETED", 1, []any{"untrusted-drain"})
	_, e := f.try(f.j, "ConfirmCheckpoint", Object{"checkpoint": cp})
	wantCode(t, e, "FORBIDDEN")
	// All-required proof: adding a required sink without its proof must fail.
	playing := f.cp(c, "PLAYING", 1, []any{})
	obj(playing, "evidence")["requiredSinks"] = []any{"test-sink", "missing"}
	_, e = f.try(f.j, "ConfirmCheckpoint", Object{"checkpoint": playing})
	wantCode(t, e, "EVIDENCE_CONFLICT")
	f.call(f.p, "StopBroadcastRun", Object{"idempotencyKey": "stop", "decisionId": freshID("decision"), "reasonCode": "STOP"})
	late := f.cp(c, "PLAYING", 1, []any{})
	out := f.call(f.j, "ConfirmCheckpoint", Object{"checkpoint": late})
	if str(out, "disposition") != "HISTORICAL" {
		t.Fatal(out)
	}
	if str(f.run(), "status") != "STOPPING" {
		t.Fatal("event revived stopped run")
	}
}
func TestPostgresForeignKeysAndImmutableEnvelope(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	if _, e := f.s.DB.Exec(f.ctx, `UPDATE dl05_outbox SET envelope=envelope || '{"traceId":"changed"}' WHERE command_id=$1`, c.Command["commandId"]); e == nil {
		t.Fatal("mutable command")
	}
	if _, e := f.s.DB.Exec(f.ctx, `UPDATE dl05_attempts SET session_id='other' WHERE command_id=$1`, c.Command["commandId"]); e == nil {
		t.Fatal("mutable attempt")
	}
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	// Even same-tenant SQL callers cannot cross a run boundary via a slot.
	if _, e = tx.Exec(f.ctx, `UPDATE dl05_run_slots SET active_attempt_id='not-an-attempt' WHERE run_id=$1`, f.runID); e == nil {
		t.Fatal("missing FK")
	}
}
func TestPostgresConcurrentMigrationRunners(t *testing.T) {
	p := testDB(t)
	errs := make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() { errs <- db.Migrate(context.Background(), p) }()
	}
	for i := 0; i < 2; i++ {
		if e := <-errs; e != nil {
			t.Fatal(e)
		}
	}
}
func TestPostgresNoSQLTransactionAcrossHTTP(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tx, e := f.s.DB.Begin(r.Context())
		if e != nil {
			t.Error(e)
			w.WriteHeader(500)
			return
		}
		defer tx.Rollback(r.Context())
		if _, e = tx.Exec(r.Context(), `SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE NOWAIT`, f.runID); e != nil {
			t.Error("network call retained row lock", e)
		}
		_ = tx.Rollback(r.Context())
		response := f.accept(c)
		w.WriteHeader(202)
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()
	sender := HTTPSender{BaseURL: server.URL, Token: strings.Repeat("x", 32)}
	if _, e := sender.Send(f.ctx, c.Command); e != nil {
		t.Fatal(e)
	}
}
func TestRedisStreamsDuplicateReclaimAndSQLProjection(t *testing.T) {
	url := os.Getenv("DURABLE_LIVE_TEST_REDIS_URL")
	if url == "" {
		t.Skip("isolated Redis required")
	}
	options, e := redis.ParseURL(url)
	if e != nil || options.Addr != "127.0.0.1:56382" {
		t.Fatal("refuse shared Redis")
	}
	r := redis.NewClient(options)
	defer r.Close()
	ctx := context.Background()
	stream := freshID("agent2-stream")
	defer r.Del(ctx, stream)
	if e = r.XGroupCreateMkStream(ctx, stream, "test-group", "0").Err(); e != nil {
		t.Fatal(e)
	}
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	f.start(c, f.accept(c))
	playing := f.cp(c, "PLAYING", 1, []any{})
	drain := f.cp(c, "LOCAL_MEDIA_DRAINED", 2, []any{playing["checkpointId"]})
	for _, cp := range []Object{drain, playing, playing} {
		b, _ := Canonical(cp)
		if e = r.XAdd(ctx, &redis.XAddArgs{Stream: stream, Values: map[string]any{"checkpoint": string(b)}}).Err(); e != nil {
			t.Fatal(e)
		}
	}
	msgs, e := r.XReadGroup(ctx, &redis.XReadGroupArgs{Group: "test-group", Consumer: "crashed", Streams: []string{stream, ">"}, Count: 10}).Result()
	if e != nil || len(msgs[0].Messages) != 3 {
		t.Fatal(e)
	}
	// Leave all messages pending (consumer crash), then exercise real XAUTOCLAIM.
	claimed, _, e := r.XAutoClaim(ctx, &redis.XAutoClaimArgs{Stream: stream, Group: "test-group", Consumer: "recovery", MinIdle: time.Millisecond, Start: "0-0", Count: 10}).Result()
	if e != nil {
		t.Fatal(e)
	}
	if len(claimed) == 0 {
		time.Sleep(2 * time.Millisecond)
		claimed, _, e = r.XAutoClaim(ctx, &redis.XAutoClaimArgs{Stream: stream, Group: "test-group", Consumer: "recovery", MinIdle: time.Millisecond, Start: "0-0", Count: 10}).Result()
	}
	if e != nil || len(claimed) != 3 {
		t.Fatal("reclaim", len(claimed), e)
	}
	for _, m := range claimed {
		cp, e := Decode([]byte(m.Values["checkpoint"].(string)))
		if e != nil {
			t.Fatal(e)
		}
		f.call(f.j, "ConfirmCheckpoint", Object{"checkpoint": cp})
		if e = r.XAck(ctx, stream, "test-group", m.ID).Err(); e != nil {
			t.Fatal(e)
		}
	}
	if f.count(`SELECT count(*) FROM dl05_checkpoints WHERE attempt_id=$1 AND producer_incarnation=$2`, c.Command["attemptId"], f.j.InstanceID) != 2 {
		t.Fatal("duplicate evidence")
	}
	if f.count(`SELECT count(*) FROM dl05_checkpoints WHERE attempt_id=$1 AND state='LOCAL_MEDIA_DRAINED' AND projection_status='APPLIED'`, c.Command["attemptId"]) != 1 {
		t.Fatal("unordered projection not reconciled")
	}
}

var _ pgx.Tx

func TestRedisIsolatedDisconnectAndSQLFallback(t *testing.T) {
	if os.Getenv("DURABLE_LIVE_TEST_REDIS_URL") != "redis://127.0.0.1:56382/0" {
		t.Skip("owned Redis required")
	}
	dir := os.Getenv("DURABLE_LIVE_ISOLATED_REDISDIR")
	if !strings.HasPrefix(dir, "/tmp/astralive-agent2-") {
		t.Skip("owned Redis directory required")
	}
	if _, e := os.Stat(filepath.Join(dir, "AGENT2_OWNED")); e != nil {
		t.Fatal("missing marker")
	}
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	client := redis.NewClient(&redis.Options{Addr: "127.0.0.1:56382", MaxRetries: -1, DialTimeout: 100 * time.Millisecond})
	defer client.Close()
	_ = client.Shutdown(f.ctx).Err()
	if e := client.Ping(f.ctx).Err(); e == nil {
		t.Fatal("Redis did not disconnect")
	}
	// SQL Outbox/Coordinator operate without Redis; no second business database.
	f.tick()
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 1 {
		t.Fatal("Redis outage blocked SQL", e)
	}
	cmd := exec.Command("redis-server", "--bind", "127.0.0.1", "--port", "56382", "--dir", dir, "--save", "", "--appendonly", "no", "--daemonize", "yes", "--pidfile", filepath.Join(dir, "redis.pid"), "--logfile", filepath.Join(dir, "redis.log"))
	if out, e := cmd.CombinedOutput(); e != nil {
		t.Fatalf("owned Redis restart %s", out)
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if client.Ping(f.ctx).Err() == nil {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("Redis reconnect failed")
}

func TestPostgresLeaseRenewDoesNotMutateCommandOrReplayStart(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	var version int64
	if e := f.s.DB.QueryRow(f.ctx, `SELECT lease_version FROM dl05_run_leases WHERE run_id=$1`, f.runID).Scan(&version); e != nil {
		t.Fatal(e)
	}
	renewed, e := f.s.RenewLease(f.ctx, f.p, f.runID, f.epoch, version)
	if e != nil || renewed.LeaseVersion != version+1 {
		t.Fatal(e)
	}
	if f.start(c, f.accept(c))["startAuthorized"] != true {
		t.Fatal("leaseVersion audit snapshot incorrectly invalidated command")
	}
}
func TestPostgresCommentAnswerJournalRequiredBeforeStart(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("COMMENT", nil, nil))
	c := f.send()
	accepted := f.accept(c)
	permit := f.call(f.j, "AcquireOutputPermit", Object{"sessionId": f.sid, "runEpoch": f.epoch, "producerIncarnation": f.j.InstanceID, "guardianId": f.g.InstanceID})
	_, e := f.try(f.j, "JournalStart", Object{"commandId": c.Command["commandId"], "attemptId": c.Command["attemptId"], "runEpoch": f.epoch, "producerIncarnation": f.j.InstanceID, "permitId": permit["permitId"], "requestHash": c.Command["requestHash"], "expectedInboxRevision": accepted["revision"]})
	wantCode(t, e, "DEPENDENCY_UNAVAILABLE")
	if e = f.s.RecordAnswerText(f.ctx, f.j, f.runID, str(c.Command, "commandId"), "真实回答测试文本"); e != nil {
		t.Fatal(e)
	}
	if f.start(c, accepted)["startAuthorized"] != true {
		t.Fatal("prepared answer did not authorize start")
	}
}
func TestPostgresSealNoEffectRequiresIndependentFence(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	c := f.send()
	f.accept(c)
	e := f.s.SealNotExecuted(f.ctx, f.p, f.runID, str(c.Command, "commandId"), "unproven")
	wantCode(t, e, "OUTPUT_FENCE_UNPROVEN")
	fence := f.call(f.g, "ConfirmOutputFence", Object{"runEpoch": f.epoch, "guardianId": f.g.InstanceID, "retiredEpoch": f.epoch, "evidenceRef": "test-physical-closed", "idempotencyKey": "seal-fence"})
	if fence["fenceReceiptId"] == nil {
		t.Fatal(fence)
	}
	if e = f.s.SealNotExecuted(f.ctx, f.p, f.runID, str(c.Command, "commandId"), "test-physical-closed"); e != nil {
		t.Fatal(e)
	}
	status := f.call(f.p, "QueryExecutionStatus", Object{"commandId": c.Command["commandId"], "runEpoch": f.epoch})
	if str(obj(status, "status"), "state") != "NOT_EXECUTED" || obj(status, "status")["executorSealed"] != true {
		t.Fatal(status)
	}
}
func TestPostgresCrossRunPublisherExclusionAfterFailedRun(t *testing.T) {
	f := newFixture(t, true)
	f.exec(`UPDATE dl05_runs SET status='FAILED' WHERE run_id=$1`, f.runID)
	second := f.runID + "new"
	q := f.req("CreateBroadcastRun", Object{"runId": second, "roomId": f.roomID, "idempotencyKey": "new-run", "recoveryPolicy": "MANUAL_ON_UNKNOWN"})
	raw, _ := json.Marshal(q)
	if _, e := f.s.Call(f.ctx, f.p, "CreateBroadcastRun", raw); e != nil {
		t.Fatal(e)
	}
	q = f.req("ResumeBroadcastRun", Object{"runId": second, "expectedRevision": int64(1), "expectedPreviousEpoch": int64(0), "idempotencyKey": "new-resume", "decisionId": freshID("decision")})
	raw, _ = json.Marshal(q)
	if _, e := f.s.Call(f.ctx, f.p, "ResumeBroadcastRun", raw); e != nil {
		t.Fatal(e)
	}
	var rev int64
	if e := f.s.DB.QueryRow(f.ctx, `SELECT state_revision FROM dl05_runs WHERE run_id=$1`, second).Scan(&rev); e != nil {
		t.Fatal(e)
	}
	q = f.req("ConfirmOutputFence", Object{"runId": second, "expectedRevision": rev, "runEpoch": int64(1), "guardianId": f.g.InstanceID, "retiredEpoch": int64(0), "evidenceRef": "new-output", "idempotencyKey": "new-fence"})
	raw, _ = json.Marshal(q)
	_, e := f.s.Call(f.ctx, f.g, "ConfirmOutputFence", raw)
	wantCode(t, e, "OUTPUT_FENCE_UNPROVEN")
}

func TestPostgresCannotAdoptLegacyBusyOrMixSchedulers(t *testing.T) {
	f := newFixture(t, true)
	if _, e := f.s.DB.Exec(f.ctx, `INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES($1,$2,'OPERATOR','legacy',100,'QUEUE','test')`, freshID("legacy"), f.sid); e == nil {
		t.Fatal("legacy scheduler entered a durable Session")
	}
	g := newFixture(t, false)
	g.call(g.p, "ResumeBroadcastRun", Object{"idempotencyKey": "resume", "expectedPreviousEpoch": int64(0), "decisionId": freshID("decision")})
	g.exec(`INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES($1,$2,'OPERATOR','legacy',100,'QUEUE','test')`, freshID("legacy"), g.sid)
	e := g.s.AttachSession(g.ctx, g.p, g.runID, 1, SessionAdmission{g.sid, g.j.InstanceID, true, time.Now()})
	wantCode(t, e, "STATE_CONFLICT")
}

func TestPostgresRoleAuthenticationAndBodyScope(t *testing.T) {
	f := newFixture(t, true)
	token := strings.Repeat("c", 32)
	h, e := NewHandler(f.s, []Credential{{token, f.p}, {strings.Repeat("j", 32), f.j}, {strings.Repeat("g", 32), f.g}})
	if e != nil {
		t.Fatal(e)
	}
	q := f.req("RestoreContentPlan", Object{})
	b, _ := json.Marshal(q)
	path := "/internal/v0.5/broadcast-runs/" + f.runID + "/plans/restore"
	req := httptest.NewRequest("POST", path+"?token="+token, strings.NewReader(string(b)))
	req.AddCookie(&http.Cookie{Name: "token", Value: token})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 401 {
		t.Fatal("cookie/query authenticated service role")
	}
	req = httptest.NewRequest("POST", path, strings.NewReader(string(b)))
	req.Header.Set("Authorization", "Bearer "+strings.Repeat("j", 32))
	w = httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("runtime escalated to CONTROL", w.Code)
	}
	q["ownerId"] = "someone-else"
	b, _ = json.Marshal(q)
	req = httptest.NewRequest("POST", path, strings.NewReader(string(b)))
	req.Header.Set("Authorization", "Bearer "+token)
	w = httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("body escalated owner scope", w.Code)
	}
}

func TestPostgresLeaseKeeperDoesNotReviveStopOrExpiredOwner(t *testing.T) {
	f := newFixture(t, true)
	keeper := LeaseKeeper{f.s, f.p}
	if e := keeper.Tick(f.ctx); e != nil {
		t.Fatal(e)
	}
	var v int64
	if e := f.s.DB.QueryRow(f.ctx, `SELECT lease_version FROM dl05_run_leases WHERE run_id=$1`, f.runID).Scan(&v); e != nil || v != 2 {
		t.Fatal("keeper did not renew", e)
	}
	f.call(f.p, "StopBroadcastRun", Object{"idempotencyKey": "stop", "decisionId": freshID("decision"), "reasonCode": "STOP"})
	if e := keeper.Tick(f.ctx); e != nil {
		t.Fatal(e)
	}
	var phase string
	if e := f.s.DB.QueryRow(f.ctx, `SELECT phase FROM dl05_run_leases WHERE run_id=$1`, f.runID).Scan(&phase); e != nil || phase != "SEALED" {
		t.Fatal("keeper revived Stop", e)
	}
}

func TestPostgresUnsentCannotBecomeUnknownByInventedTransition(t *testing.T) {
	f := newFixture(t, true)
	out := f.claim(f.turn("OPERATOR", nil, nil))
	_, e := f.try(f.p, "MarkExecutionUnknown", Object{"runEpoch": f.epoch, "attemptId": obj(out, "attempt")["attemptId"], "reasonCode": "TEST", "lastKnownState": "PLANNED", "evidenceRef": "test", "idempotencyKey": "unknown"})
	wantCode(t, e, "STATE_CONFLICT")
}

func TestPostgresSemanticTurnConflictIsNotRetryableDependencyFailure(t *testing.T) {
	f := newFixture(t, true)
	turn := f.turn("OPERATOR", nil, nil)
	f.call(f.p, "AdmitTurn", Object{"idempotencyKey": "first-request", "turn": turn})
	_, e := f.try(f.p, "AdmitTurn", Object{"idempotencyKey": "another-request", "turn": turn})
	wantCode(t, e, "COMMAND_CONFLICT")
}

func TestPostgresBoundedRecoveryDoesNotStarveLaterRooms(t *testing.T) {
	f := newFixture(t, false)
	room2 := freshID("room")
	run2 := freshID("run")
	f.exec(`INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) SELECT $1,'test',avatar_id,voice_id,'test' FROM live_rooms WHERE id=$2`, room2, f.roomID)
	f.exec(`INSERT INTO resource_owners(kind,resource_id,tenant_id,user_id) VALUES('room',$1,$2,$3)`, room2, f.p.TenantID, f.p.OwnerID)
	f.call(f.p, "CreateBroadcastRun", Object{"runId": run2, "roomId": room2, "idempotencyKey": "second", "recoveryPolicy": "MANUAL_ON_UNKNOWN"})
	coordinator := Coordinator{f.s, f.p, 1}
	for i := 0; i < 2; i++ {
		if e := coordinator.Tick(f.ctx); e != nil {
			t.Fatal(e)
		}
	}
	if f.count(`SELECT count(*) FROM dl05_runs WHERE tenant_id=$1 AND owner_id=$2 AND last_reconciled_at IS NOT NULL`, f.p.TenantID, f.p.OwnerID) != 2 {
		t.Fatal("bounded scan starved a room")
	}
}
