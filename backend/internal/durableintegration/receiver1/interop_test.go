package receiver1

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"astralive/backend/db"
	facts "astralive/backend/internal/contentplan/answerstream"
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"github.com/jackc/pgx/v5/pgxpool"
)

func testDigest(b []byte) string { v := sha256.Sum256(b); return hex.EncodeToString(v[:]) }
func testHash(v any) string {
	b, _ := json.Marshal(v)
	s, e := wire.DigestJSON(b)
	if e != nil {
		panic(e)
	}
	return s
}
func testStamp(t time.Time) string                   { return t.UTC().Format("2006-01-02T15:04:05.000000Z") }
func testText(d authority.Document, k string) string { s, _ := d[k].(string); return s }
func testObj(d authority.Document, k string) authority.Document {
	s, _ := d[k].(map[string]any)
	return s
}
func testDecode(raw []byte) authority.Document {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v authority.Document
	if e := d.Decode(&v); e != nil {
		panic(e)
	}
	return v
}
func testN(v any) int {
	switch x := v.(type) {
	case json.Number:
		n, _ := x.Int64()
		return int(n)
	case int64:
		return int(x)
	case float64:
		return int(x)
	}
	return 0
}

type childPeer struct {
	managed *Managed
	input   io.WriteCloser
	output  *bufio.Reader
}

func (c *childPeer) rpc(q any) authority.Document {
	b, _ := json.Marshal(q)
	b = append(b, '\n')
	if _, e := c.input.Write(b); e != nil {
		panic(e)
	}
	line, e := c.output.ReadBytes('\n')
	if e != nil {
		panic(e)
	}
	return testDecode(line)
}

type interop struct {
	channel                                 *ControlChannel
	t                                       *testing.T
	ctx                                     context.Context
	s                                       *authority.Store
	prefix, product, plan, root, repo       string
	control, registrar, runtime, guardian   authority.Actor
	cmd, template, unit, prepareQ, consumeQ authority.Document
	binding                                 wire.ReceiverBootstrapBinding
	rt, second, g                           *childPeer
	registry                                *Registry
	server                                  *Server
}

func (f *interop) exec(q string, a ...any) {
	f.t.Helper()
	if _, e := f.s.DB.Exec(f.ctx, q, a...); e != nil {
		f.t.Fatal(e)
	}
}
func (f *interop) q(v authority.Document) authority.Document {
	q := authority.Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "requestId": fresh("req_"), "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": f.cmd["runId"]}
	for k, x := range v {
		q[k] = x
	}
	return q
}
func (f *interop) private(v authority.Document) authority.Document {
	q := authority.Document{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "requestId": fresh("req_")}
	for k, x := range v {
		q[k] = x
	}
	return q
}
func (f *interop) call(p authority.Actor, name string, q authority.Document) authority.Document {
	f.t.Helper()
	op, ok := wire.LookupOperation(wire.OperationID(name))
	if !ok {
		f.t.Fatal("op")
	}
	raw, _ := json.Marshal(q)
	wc := wire.RequestContext{Role: wire.Role(p.Role), Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	v, e := f.s.Handle(f.ctx, p, op.ID, wc, raw)
	if e != nil {
		f.t.Fatalf("%s: %v", name, e)
	}
	b, e := wire.Encode(v)
	if e != nil {
		f.t.Fatal(e)
	}
	return testDecode(b)
}
func (f *interop) launch(role string) *childPeer {
	f.t.Helper()
	p := authority.Actor{Role: role, Tenant: f.control.Tenant, Owner: f.control.Owner, Room: f.control.Room, Producer: f.prefix + "producer"}
	py := os.Getenv("AGENT4_RECEIVER1_PYTHON")
	if py == "" {
		py = "/tmp/astralive-agent2-python/bin/python"
	}
	cmd := exec.Command(py, filepath.Join(f.repo, "backend/internal/durableintegration/receiver1/testdata/guardian_peer.py"), role)
	cmd.Env = []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"), "PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=" + f.repo}
	in, e := cmd.StdinPipe()
	if e != nil {
		f.t.Fatal(e)
	}
	out, e := cmd.StdoutPipe()
	if e != nil {
		f.t.Fatal(e)
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	var channels []*ControlChannel
	if role == "OUTPUT_GUARDIAN" {
		channels = []*ControlChannel{f.channel}
	}
	m, e := StartManaged(f.ctx, cmd, p, f.binding, channels...)
	if e != nil {
		f.t.Fatal(e)
	}
	child := &childPeer{m, in, bufio.NewReader(out)}
	f.t.Cleanup(func() {
		in.Close()
		done := make(chan struct{})
		go func() { cmd.Wait(); close(done) }()
		select {
		case <-done:
			m.Pin.Retire()
		case <-time.After(time.Second):
			now, e := InspectProcess(m.Pin.identity.PID)
			if e == nil && now == m.Pin.identity {
				cmd.Process.Kill()
			}
			<-done
			m.Pin.Retire()
		}
		if stderr.Len() > 0 {
			f.t.Log("dedicated peer diagnostic:", stderr.String())
		}
	})
	got := child.rpc(map[string]any{"action": "identity"})
	if got["ok"] != true {
		f.t.Fatal("peer startup")
	}
	return child
}

// This source is EXPLICITLY a physical Session/closed-fence fixture. OS process
// identity/liveness and SQL/transport are real; no production fence is claimed.
type physicalFixture struct{ registrar, guardian string }

func (p physicalFixture) Observe(_ context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (wire.ReceiverPhysicalInstallation, error) {
	return wire.ReceiverPhysicalInstallation{Binding: b, InstallationRevision: 1, ObservedByPrincipalID: wire.ID(p.registrar), GuardianPrincipalID: wire.ID(p.guardian), ClosedFenceProofRef: "fixture-closed-fence", State: "CLOSED_INSTALLED"}, nil
}
func newInterop(t *testing.T) *interop {
	t.Helper()
	dsn := os.Getenv("AGENT4_RECEIVER1_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires owned receiver1 PostgreSQL and pinned PR11 archive")
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	root := os.Getenv("AGENT4_RECEIVER1_OWNED_ROOT")
	marker, e := os.ReadFile(filepath.Join(root, "AGENT4_RECEIVER1_OWNED"))
	if e != nil || string(marker) != "Agent4 dedicated receiver1 PostgreSQL\n" || cfg.ConnConfig.Host != "127.0.0.1" || !strings.HasPrefix(cfg.ConnConfig.Database, "agent4_receiver1_") {
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
	repo, e := filepath.Abs("../../../..")
	if e != nil {
		t.Fatal(e)
	}
	f := &interop{t: t, ctx: context.Background(), prefix: fresh("int4_"), s: authority.New(pool), repo: repo}
	x := f.prefix
	f.root, e = os.MkdirTemp("/tmp", "adl4-")
	if e != nil {
		t.Fatal(e)
	}
	os.Chmod(f.root, 0700)
	f.control = authority.Actor{Role: "CONTROL", Tenant: x + "tenant", Owner: x + "owner", Room: x + "room", ID: x + "backend", Incarnation: x + "backend-process"}
	f.registrar = f.control
	f.registrar.Role = "CONTROL_REGISTRAR"
	f.registrar.ID = x + "registrar"
	f.channel, e = NewControlChannel(f.registrar)
	if e != nil {
		t.Fatal(e)
	}
	f.product = x + "product"
	f.plan = x + "plan"
	f.template = authority.Document{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "bootstrapId": x + "bootstrap", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "roomId": f.control.Room, "runId": x + "run", "sessionId": x + "session", "producerIncarnation": x + "producer", "attemptId": x + "attempt", "commandId": x + "command", "turnId": x + "turn", "utteranceId": x + "utterance", "guardianId": x + "guardian", "guardianIncarnation": "placeholder_guardian", "runtimePrincipalId": "placeholder_runtime", "runtimeIncarnation": "placeholder_incarnation", "physicalInstallProofRef": x + "install", "runEpoch": 1, "generationId": 7, "outputBindingVersion": 1}
	raw, _ := json.Marshal(f.template)
	m, e := wire.Decode("ReceiverBootstrapBinding", raw)
	if e != nil {
		t.Fatal(e)
	}
	f.binding = *m.(*wire.ReceiverBootstrapBinding)
	f.rt = f.launch("REGISTERED_RUNTIME")
	f.second = f.launch("REGISTERED_RUNTIME")
	f.g = f.launch("OUTPUT_GUARDIAN")
	f.runtime = f.rt.managed.Pin.Actor()
	f.runtime.Role = "RUNTIME_JOURNAL"
	f.guardian = f.g.managed.Pin.Actor()
	f.seed()
	f.productSetup()
	// NewRegistry is the sole install dispatcher; a nil real PhysicalSource denies.
	f.registry, e = NewRegistry(f.s)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.registry.Provision(f.ctx, f.registrar, f.rt.managed.Pin, f.second.managed.Pin, f.g.managed.Pin); e != nil {
		t.Fatal(e)
	}
	f.call(f.runtime, "JournalAccept", f.q(authority.Document{"command": f.cmd, "producerIncarnation": f.runtime.Producer}))
	if _, e = f.registry.Install(f.ctx, f.registrar, f.rt.managed.Pin, f.g.managed.Pin, nil); e == nil {
		t.Fatal("missing physical source accepted")
	}
	f.binding, e = f.registry.Install(f.ctx, f.registrar, f.rt.managed.Pin, f.g.managed.Pin, physicalFixture{f.registrar.ID, f.guardian.ID})
	if e != nil {
		t.Fatal("Install", e)
	}
	projection, e := f.s.ProductProjection(f.ctx, f.control, testText(f.cmd, "commandId"))
	if e != nil {
		t.Fatal(e)
	}
	factSource := &facts.AuthorityFacts{Store: f.s, Control: f.control, Binding: facts.Binding{Tenant: f.control.Tenant, Owner: f.control.Owner, Run: testText(f.cmd, "runId"), Session: testText(f.cmd, "sessionId"), Command: testText(f.cmd, "commandId"), Attempt: testText(f.cmd, "attemptId"), Turn: testText(f.cmd, "turnId"), Utterance: testText(f.cmd, "utteranceId"), Producer: f.runtime.Producer, Answer: x + "answer", Product: f.product, Snapshot: projection["snapshotVersion"].(string), Epoch: 1, Generation: 7}}
	f.s.Assertions = factSource.Verify
	f.server, e = NewServer(f.s, f.registry, f.g.managed.Pin)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.server.Listen(filepath.Join(f.root, "authority.sock")); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { f.server.Close() })
	me, e := InspectProcess(os.Getpid())
	if e != nil {
		t.Fatal(e)
	}
	producer1, e := ProducerProvision(f.rt.managed.Pin)
	if e != nil {
		t.Fatal(e)
	}
	producer2, e := ProducerProvision(f.second.managed.Pin)
	if e != nil {
		t.Fatal(e)
	}
	result := f.g.rpc(map[string]any{"action": "configure", "socket": filepath.Join(f.root, "authority.sock"), "backend": me, "binding": f.binding, "guardianSource": os.Getenv("AGENT4_PR11_ARCHIVE"), "guardianIPC": filepath.Join(f.root, "guardian"), "producers": []any{producer1, producer2}, "journal": filepath.Join(f.root, "denials"), "runtimeChannel": testHash("fixture-runtime-channel"), "registrar": f.registrar})
	if result["ok"] != true {
		t.Fatal("configure", result)
	}
	t.Log("REAL_OS_PEER real Go/Python/SQL; physical installation/Runtime Peer/Outputs are EXPLICIT FIXTURES; CONTROL Stage uses real Unix PID auth; no media/TTS")
	return f
}
func (f *interop) stageRegister() {
	f.t.Helper()
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		f.t.Fatal(e)
	}
	staged, e := f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q)
	if e != nil {
		f.t.Fatal("authenticated CONTROL Stage", e)
	}
	_, e = f.registry.Register(f.ctx, f.registrar, f.binding, staged.Receipt)
	if e != nil {
		f.t.Fatal(e)
	}
	reg, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
	if e != nil || testText(reg, "state") != "ACTIVE" {
		f.t.Fatal("registration readback", e)
	}
}
func (f *interop) ready() {
	f.stageRegister()
	f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
	p := f.call(f.runtime, "AcquireOutputPermit", f.q(authority.Document{"sessionId": f.cmd["sessionId"], "runEpoch": 1, "producerIncarnation": f.runtime.Producer, "guardianId": f.binding.GuardianID, "answerArtifactId": f.unit["artifactId"]}))
	start := f.call(f.runtime, "JournalStart", f.q(authority.Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": 1, "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": p["permitId"], "expectedInboxRevision": 2, "answerArtifactId": f.unit["artifactId"], "answerArtifactHash": f.unit["artifactHash"], "expectedAnswerRevision": 1}))
	f.consumeQ = f.private(authority.Document{"references": authority.Document{"bootstrapId": f.binding.BootstrapID, "artifactId": f.unit["artifactId"], "artifactHash": f.unit["artifactHash"], "grantId": testObj(start, "answerGrant")["grantId"], "permitId": p["permitId"]}, "consumeTicket": start["consumeTicket"], "consumeRequestId": fresh("consume_"), "runtimePrincipalId": f.runtime.ID, "runtimeIncarnation": f.runtime.Incarnation, "channelBinding": testHash("fixture-runtime-channel"), "expectedRegistrationRevision": 1})
}
func (f *interop) remote(name string, q authority.Document) authority.Document {
	return f.g.rpc(map[string]any{"action": "call", "operation": name, "document": q})
}
func (f *interop) count(table string) int {
	var n int
	if e := f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM "+table+" WHERE command_id=$1", f.cmd["commandId"]).Scan(&n); e != nil {
		f.t.Fatal(e)
	}
	return n
}

func TestPostgresReceiver1RealTransport(t *testing.T) {
	f := newInterop(t)
	f.ready()
	query := f.private(authority.Document{"references": f.consumeQ["references"]})
	if got := f.remote("QueryReceiverAuthority", query); got["ok"] != true {
		t.Fatal("query", got)
	}
	first := f.remote("CommitReceiverConsume", f.consumeQ)
	if first["ok"] != true || testObj(first, "result")["consumeAuthorized"] != true {
		t.Fatal("first", first)
	}
	duplicate := f.remote("CommitReceiverConsume", f.consumeQ)
	if duplicate["ok"] != true || testObj(duplicate, "result")["consumeAuthorized"] != false || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("duplicate", duplicate)
	}
	metadata := f.remote("QueryReceiverConsumption", f.private(authority.Document{"bootstrapId": f.binding.BootstrapID, "grantId": testObj(f.consumeQ, "references")["grantId"]}))
	if metadata["ok"] != true || testText(testObj(testObj(metadata, "result"), "summary"), "state") != "CONSUMED" {
		t.Fatal("metadata", metadata)
	}
}

func TestPostgresReceiver1ConcurrentLatchAndRuntimeIdentity(t *testing.T) {
	f := newInterop(t)
	f.ready()
	other := f.second
	bad := testDecode(mustJSON(f.consumeQ))
	bad["runtimePrincipalId"] = other.managed.Pin.actor.ID
	bad["runtimeIncarnation"] = other.managed.Pin.actor.Incarnation
	if v := f.remote("CommitReceiverConsume", bad); v["ok"] == true {
		t.Fatal("other real Runtime obtained original grant")
	}
	v := f.g.rpc(map[string]any{"action": "concurrent", "document": f.consumeQ})
	if v["ok"] != true || testN(testObj(v, "result")["true"]) != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("concurrent", v)
	}
}
func mustJSON(v any) []byte {
	b, e := json.Marshal(v)
	if e != nil {
		panic(e)
	}
	return b
}
func TestPostgresReceiver1WrongProcessAndChannel(t *testing.T) {
	f := newInterop(t)
	f.ready()
	q := f.private(authority.Document{"references": f.consumeQ["references"]})
	stolen := f.g.rpc(map[string]any{"action": "wrong_process", "operation": "QueryReceiverAuthority", "document": q})
	if testText(testObj(stolen, "result"), "code") != "UNAUTHENTICATED" {
		t.Fatal("stolen valid credential accepted from different PID", stolen)
	}
	first := f.remote("CommitReceiverConsume", f.consumeQ)
	if first["ok"] != true {
		t.Fatal(first)
	}
	bad := testDecode(mustJSON(f.consumeQ))
	bad["channelBinding"] = testHash("other-channel")
	if v := f.remote("CommitReceiverConsume", bad); v["ok"] == true {
		t.Fatal("different channel replayed")
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("extra latch")
	}
}
func TestPostgresReceiver1LostBackendReply(t *testing.T) {
	f := newInterop(t)
	f.ready()
	v := f.g.rpc(map[string]any{"action": "drop_commit_reply", "document": f.consumeQ})
	if v["ok"] != true {
		t.Fatal(v)
	}
	end := time.Now().Add(time.Second)
	for f.count("dl05_receiver_consumptions") == 0 && time.Now().Before(end) {
		time.Sleep(time.Millisecond)
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("no committed latch")
	}
	again := f.remote("CommitReceiverConsume", f.consumeQ)
	if again["ok"] != true || testObj(again, "result")["consumeAuthorized"] != false {
		t.Fatal("ACK loss reminted true", again)
	}
	// A positive Backend latch alone never activated this Receiver gate.
	state := testObj(f.g.rpc(map[string]any{"action": "metadata"}), "result")
	if state["active"] == true || testN(state["acks"]) != 0 {
		t.Fatal("lost Backend reply armed Receiver")
	}
	// Supervisor records UNKNOWN using the approved CONTROL operation.
	f.call(f.control, "MarkExecutionUnknown", f.q(authority.Document{"expectedRevision": 1, "runEpoch": 1, "attemptId": f.cmd["attemptId"], "lastKnownState": "DISPATCHED", "reasonCode": "ACK_LOST", "evidenceRef": "test:backend-reply-discarded", "idempotencyKey": "unknown:lost-response"}))
}
func TestPostgresReceiver1StopBeforeFinalReceiverACK(t *testing.T) {
	f := newInterop(t)
	f.ready()
	verify := f.s.Assertions
	var count atomic.Int32
	f.s.Assertions = func(ctx context.Context, p authority.Actor, a authority.Document) error {
		if e := verify(ctx, p, a); e != nil {
			return e
		}
		if count.Add(1) == 3 { // initial Query, Commit, final proof Query before ACK
			op, _ := wire.LookupOperation(wire.OpStopBroadcastRun)
			wc := wire.RequestContext{Role: wire.RoleControl, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
			raw := mustJSON(f.q(authority.Document{"reasonCode": "test-stop", "decisionId": fresh("decision_"), "expectedRevision": 1, "idempotencyKey": "stop"}))
			if _, e := f.s.Handle(ctx, f.control, op.ID, wc, raw); e != nil {
				return e
			}
		}
		return nil
	}
	consume := f.private(authority.Document{"references": f.consumeQ["references"], "consumeTicket": f.consumeQ["consumeTicket"], "consumeRequestId": f.consumeQ["consumeRequestId"], "expectedGenerationId": 7, "expectedGuardianIncarnation": f.guardian.Incarnation, "expectedRegistrationRevision": 1})
	got := f.g.rpc(map[string]any{"action": "consume", "document": consume})
	if got["ok"] == true {
		t.Fatal("true Receiver ACK crossed Stop")
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("consumed evidence lost")
	}
	var state string
	f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_execution_state WHERE command_id=$1", f.cmd["commandId"]).Scan(&state)
	if state != "UNKNOWN" {
		t.Fatal("not UNKNOWN", state)
	}
	meta := testObj(f.g.rpc(map[string]any{"action": "metadata"}), "result")
	if meta["active"] == true || testN(meta["acks"]) != 0 {
		t.Fatal("Stop left active/ACK")
	}
}
func TestPostgresReceiver1ExpiryDuringRPC(t *testing.T) {
	f := newInterop(t)
	f.ready()
	f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '150 milliseconds' WHERE room_id=$1", f.control.Room)
	verify := f.s.Assertions
	f.s.Assertions = func(ctx context.Context, p authority.Actor, a authority.Document) error {
		if e := verify(ctx, p, a); e != nil {
			return e
		}
		time.Sleep(220 * time.Millisecond)
		return nil
	}
	got := f.remote("QueryReceiverAuthority", f.private(authority.Document{"references": f.consumeQ["references"]}))
	if got["ok"] == true {
		t.Fatal("expired RPC proof escaped")
	}
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("expiry consumed latch")
	}
}
func TestPostgresReceiver1RenewConsumedLongUnit(t *testing.T) {
	f := newInterop(t)
	f.ready()
	if v := f.remote("CommitReceiverConsume", f.consumeQ); v["ok"] != true {
		t.Fatal(v)
	}
	time.Sleep(1100 * time.Millisecond)
	permit := f.call(f.runtime, "AcquireOutputPermit", f.q(authority.Document{"sessionId": f.cmd["sessionId"], "runEpoch": 1, "producerIncarnation": f.runtime.Producer, "guardianId": f.binding.GuardianID, "answerArtifactId": f.unit["artifactId"]}))
	refs := testObj(testDecode(mustJSON(f.consumeQ)), "references")
	refs["permitId"] = permit["permitId"]
	got := f.remote("QueryReceiverAuthority", f.private(authority.Document{"references": refs}))
	if got["ok"] != true {
		t.Fatal("old Grant truncated current proof", got)
	}
	snap := testObj(testObj(got, "result"), "snapshot")
	if testN(testObj(snap, "timing")["remainingGrantMs"]) != 0 || testN(testObj(snap, "timing")["remainingProofMs"]) <= 100 {
		t.Fatal("renewal budget")
	}
	if f.count("dl05_answer_grants") != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("renewal minted authorization")
	}
}
func TestPostgresReceiver1ScopeVersionAndStaleIdentity(t *testing.T) {
	for _, kind := range []string{"cross-room", "old-epoch", "generation", "old-key", "old-binding", "body-role"} {
		t.Run(kind, func(t *testing.T) {
			f := newInterop(t)
			f.ready()
			q := f.private(authority.Document{"references": f.consumeQ["references"]})
			switch kind {
			case "cross-room":
				testObj(q, "references")["bootstrapId"] = "foreign_room_bootstrap"
			case "old-epoch":
				f.exec("UPDATE dl05_runs SET run_epoch=2 WHERE run_id=$1", f.cmd["runId"])
			case "old-key":
				f.exec("UPDATE dl05_v2_processes SET revoked_at=clock_timestamp() WHERE principal_id=$1", f.guardian.ID)
			case "old-binding":
				f.exec("UPDATE session_provider_bindings SET expires_at=clock_timestamp() WHERE session_id=$1", f.cmd["sessionId"])
			case "body-role":
				q["role"] = "CONTROL"
			case "generation":
				req := f.private(authority.Document{"references": f.consumeQ["references"], "consumeTicket": f.consumeQ["consumeTicket"], "consumeRequestId": f.consumeQ["consumeRequestId"], "expectedGenerationId": 8, "expectedGuardianIncarnation": f.guardian.Incarnation, "expectedRegistrationRevision": 1})
				if v := f.g.rpc(map[string]any{"action": "consume", "document": req}); v["ok"] == true {
					t.Fatal("Generation substituted")
				}
				return
			}
			if v := f.remote("QueryReceiverAuthority", q); v["ok"] == true {
				t.Fatal("stale/foreign scope authorized", kind)
			}
			if f.count("dl05_receiver_consumptions") != 0 {
				t.Fatal("invalid identity reserved latch")
			}
		})
	}
}
func TestPostgresReceiver1CrashReconciliation(t *testing.T) {
	f := newInterop(t)
	f.ready()
	if v := f.remote("CommitReceiverConsume", f.consumeQ); v["ok"] != true {
		t.Fatal(v)
	}
	f.rt.managed.Cmd.Process.Kill()
	f.rt.managed.Cmd.Wait()
	if e := f.registry.ReconcileDead(f.ctx, string(f.binding.CommandID)); e != nil {
		t.Fatal(e)
	}
	var state string
	f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_execution_state WHERE command_id=$1", f.cmd["commandId"]).Scan(&state)
	if state != "UNKNOWN" || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("crash lost UNKNOWN/latch", state)
	}
	if v := f.remote("CommitReceiverConsume", f.consumeQ); v["ok"] == true {
		t.Fatal("dead context reauthorized")
	}
	registration, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
	if e != nil || registration["state"] != "REVOKED" {
		t.Fatal("metadata recovery", e)
	}
}

func TestPostgresReceiver1BackendStrictDecode(t *testing.T) {
	f := newInterop(t)
	f.ready()
	op, _ := wire.LookupOperation(wire.OpQueryReceiverAuthority)
	good := mustJSON(f.private(authority.Document{"references": f.consumeQ["references"]}))
	cases := [][]byte{append(append([]byte{}, good[:len(good)-1]...), []byte(`,"requestId":"duplicate"}`)...), append(append([]byte{}, good[:len(good)-1]...), []byte(`,"role":"CONTROL"}`)...), []byte("\xff"), bytes.Replace(good, []byte(`"receiver-1"`), []byte(`"receiver-0"`), 1), bytes.Repeat([]byte{' '}, 262145)}
	for i, b := range cases {
		v := f.g.rpc(map[string]any{"action": "raw", "path": op.Path, "body": base64.StdEncoding.EncodeToString(b)})
		if !(i == 4 && v["ok"] == false) && testN(testObj(v, "result")["status"]) < 400 {
			t.Fatal("raw request accepted", i, v)
		}
	}
	forbidden, _ := wire.LookupOperation(wire.OpRegisterReceiverBootstrap)
	v := f.g.rpc(map[string]any{"action": "raw", "path": forbidden.Path, "body": base64.StdEncoding.EncodeToString(good)})
	if testN(testObj(v, "result")["status"]) != 403 {
		t.Fatal("Guardian obtained CONTROL route", v)
	}
	if v := f.g.rpc(map[string]any{"action": "environment"}); testObj(v, "result")["sqlOrProviderCredentialsPresent"] != false {
		t.Fatal("Backend credentials inherited")
	}
}
func TestPostgresReceiver1RegistrarAdmissionAndReadback(t *testing.T) {
	f := newInterop(t)
	op, _ := wire.LookupOperation(wire.OpJournalPrepareAnswer)
	wc := wire.RequestContext{Role: wire.RoleRuntimeJournal, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	if _, e := f.s.Handle(f.ctx, f.runtime, op.ID, wc, mustJSON(f.prepareQ)); e == nil {
		t.Fatal("Prepare before registration")
	}
	for _, field := range []string{"generation", "epoch", "guardian"} {
		b := f.binding
		switch field {
		case "generation":
			b.GenerationID++
		case "epoch":
			b.RunEpoch++
		case "guardian":
			b.GuardianIncarnation = "old_guardian"
		}
		if _, e := f.registry.StageRequest(f.ctx, f.registrar, b); e == nil {
			t.Fatal("uninstalled context staged", field)
		}
	}
	f.stageRegister() // Drop the registration result; recover only its same identity.
	reg, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
	if e != nil || reg["registrationHash"] != bindingHash(f.binding) {
		t.Fatal("registration ACK readback", e)
	}
	if f.count("dl05_answer_grants") != 0 || f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("registration minted execution")
	}
}
func TestPostgresReceiver1ExpiredInstallationCannotStage(t *testing.T) {
	f := newInterop(t)
	f.exec("UPDATE session_provider_bindings SET expires_at=clock_timestamp() WHERE session_id=$1", f.cmd["sessionId"])
	if _, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding); e == nil {
		t.Fatal("expired Binding reused installation")
	}
	if f.count("dl05_receiver_bootstraps") != 0 {
		t.Fatal("stale registration")
	}
}

func TestPostgresReceiver1NativeRuntimeIPCChannels(t *testing.T) {
	f := newInterop(t)
	f.ready()
	q := f.private(authority.Document{"references": f.consumeQ["references"], "consumeTicket": f.consumeQ["consumeTicket"], "consumeRequestId": f.consumeQ["consumeRequestId"], "expectedGenerationId": 7, "expectedGuardianIncarnation": f.guardian.Incarnation, "expectedRegistrationRevision": 1})
	call := map[string]any{"action": "runtime_consume_ipc", "socket": filepath.Join(f.root, "guardian/runtime.sock"), "guardian": f.g.managed.Pin.Identity(), "document": q}
	other := f.second.rpc(call)
	if other["ok"] == true && testObj(other, "result")["consumeAuthorized"] == true {
		t.Fatal("second registered OS Runtime consumed first registration")
	}
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("ineligible Runtime reserved latch")
	}
	first := f.rt.rpc(call)
	if first["ok"] != true || testObj(first, "result")["consumeAuthorized"] != true {
		t.Fatal("actual Runtime IPC", first)
	}
	record := testObj(testObj(first, "result"), "consumption")
	if record["runtimePrincipalId"] != f.runtime.ID || record["runtimeIncarnation"] != f.runtime.Incarnation || testText(record, "channelBinding") == testHash("fixture-runtime-channel") || len(testText(record, "channelBinding")) != 64 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("native peer/channel did not bind durable latch")
	}
	// No TTS side effect is available in this test peer. Positive IPC ACK is not
	// production Runtime once-TTS, required drain, browser AV or SLA acceptance.
}
func TestPostgresReceiver1ControlCredentialSeparation(t *testing.T) {
	f := newInterop(t)
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		t.Fatal(e)
	}
	wrong, e := NewControlChannel(f.registrar)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = wrong.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q); e == nil {
		t.Fatal("unprovisioned CONTROL credential staged")
	}
	if _, e = NewControlChannel(f.guardian); e == nil {
		t.Fatal("Guardian role became CONTROL")
	}
	for _, verb := range []string{"%v", "%+v", "%#v"} {
		if strings.Contains(fmt.Sprintf(verb, f.channel), f.channel.token) {
			t.Fatal("CONTROL secret in diagnostic")
		}
	}
	f.stageRegister()
}
