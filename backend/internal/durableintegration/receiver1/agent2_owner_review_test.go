package receiver1

import (
	"astralive/backend/db"
	facts "astralive/backend/internal/contentplan/answerstream"
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

type reviewSource struct {
	valid    atomic.Bool
	blocking atomic.Bool
	entered  chan struct{}
	release  chan struct{}
	once     sync.Once
	fixture  physicalFixture
}

func (s *reviewSource) Observe(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (wire.ReceiverPhysicalInstallation, error) {
	if s.entered != nil && s.blocking.Load() {
		s.once.Do(func() { close(s.entered) })
		select {
		case <-ctx.Done():
			return wire.ReceiverPhysicalInstallation{}, ctx.Err()
		case <-s.release:
		}
	}
	if !s.valid.Load() {
		return wire.ReceiverPhysicalInstallation{}, errors.New("independent source revoked")
	}
	return s.fixture.Observe(ctx, b, r, g)
}
func reviewRecord(f *interop) *installation {
	f.registry.mu.RLock()
	defer f.registry.mu.RUnlock()
	return f.registry.records[string(f.binding.CommandID)]
}
func reviewQuery(f *interop) authority.Document {
	return f.private(authority.Document{"references": f.consumeQ["references"]})
}
func reviewNoTrue(t *testing.T, got authority.Document) {
	t.Helper()
	if got["ok"] == true && testObj(got, "result")["consumeAuthorized"] == true {
		t.Fatal("unexpected new execution authority")
	}
}

func TestAgent2ReviewNilSourceActuallyRejects(t *testing.T) {
	f := newInterop(t)
	// newInterop already verifies nil before its sole successful Install. Repeat
	// with a separately launched same-scope pair and prove no installation delta.
	r := f.launch("REGISTERED_RUNTIME")
	g := f.launch("OUTPUT_GUARDIAN")
	var before, after int
	f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM dl05_v2_installations").Scan(&before)
	_, e := f.registry.Install(f.ctx, f.registrar, r.managed.Pin, g.managed.Pin, nil)
	var ae *authority.Error
	if !errors.As(e, &ae) || ae.Code != "OUTPUT_FENCE_UNPROVEN" {
		t.Fatalf("nil source: %v", e)
	}
	f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM dl05_v2_installations").Scan(&after)
	if before != after {
		t.Fatal("nil source persisted installation")
	}
}
func TestAgent2ReviewLostRegistrationACKHistoricalOnly(t *testing.T) {
	f := newInterop(t)
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		t.Fatal(e)
	}
	stage, e := f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = f.registry.Register(f.ctx, f.registrar, f.binding, stage.Receipt); e != nil {
		t.Fatal(e)
	} // deliberately discard ACK
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			v, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
			if e != nil {
				errs <- e
				return
			}
			if v["registrationHash"] != bindingHash(f.binding) {
				errs <- errors.New("identity changed")
			}
		}()
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		t.Error(e)
	}
	if _, e = f.registry.StageRequest(f.ctx, f.registrar, f.binding); e == nil {
		t.Fatal("history enabled Stage")
	}
	b := f.binding
	b.RuntimeIncarnation = "replacement"
	if _, e = f.registry.Confirm(f.ctx, f.registrar, b); e == nil {
		t.Fatal("history accepted replacement")
	}
	if f.count("dl05_receiver_bootstraps") != 1 || f.count("dl05_answer_grants") != 0 || f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("historical confirm minted authority")
	}
}
func TestAgent2ReviewConcurrentRevokePreservesLatch(t *testing.T) {
	f := newInterop(t)
	f.ready()
	if v := f.remote("CommitReceiverConsume", f.consumeQ); v["ok"] != true || testObj(v, "result")["consumeAuthorized"] != true {
		t.Fatal(v)
	}
	f.rt.managed.Pin.Retire() // only this managed test process: supervisor native local denial
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); errs <- f.registry.ReconcileDead(f.ctx, string(f.binding.CommandID)) }()
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		if e != nil {
			t.Error(e)
		}
	}
	v, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
	if e != nil || v["state"] != "REVOKED" {
		t.Fatal(v, e)
	}
	var n int
	var state string
	if e := f.s.DB.QueryRow(f.ctx, "SELECT revision FROM dl05_v2_registration_state WHERE bootstrap_id=$1", string(f.binding.BootstrapID)).Scan(&n); e != nil {
		t.Fatal("revision read", e)
	}
	f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_execution_state WHERE command_id=$1", f.cmd["commandId"]).Scan(&state)
	if n != 2 || state != "UNKNOWN" || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatalf("CAS/latch: revision=%d state=%s", n, state)
	}
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
}
func TestAgent2ReviewReplacementCannotReuseInstallation(t *testing.T) {
	f := newInterop(t)
	f.ready()
	replacement := f.launch("REGISTERED_RUNTIME")
	b := f.binding
	b.RuntimePrincipalID = wire.ID(replacement.managed.Pin.actor.ID)
	b.RuntimeIncarnation = wire.ID(replacement.managed.Pin.actor.Incarnation)
	if _, e := f.registry.VerifyInstallation(f.ctx, f.registrar, mustDocument(&b)); e == nil {
		t.Fatal("new process reused source")
	}
	if _, e := f.registry.StageRequest(f.ctx, f.registrar, b); e == nil {
		t.Fatal("new process staged old source")
	}
	q := testDecode(mustJSON(f.consumeQ))
	q["runtimePrincipalId"] = replacement.managed.Pin.actor.ID
	q["runtimeIncarnation"] = replacement.managed.Pin.actor.Incarnation
	reviewNoTrue(t, f.remote("CommitReceiverConsume", q))
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("replacement latch")
	}
}
func TestAgent2ReviewSourceRevocationDeniesRPC(t *testing.T) {
	src := &reviewSource{}
	f := newObservedReview(t, src)
	f.ready()
	src.blocking.Store(true)
	if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] != true {
		t.Fatal(v)
	}
	src.valid.Store(false)
	for _, op := range []string{"QueryReceiverAuthority", "CommitReceiverConsume"} {
		q := reviewQuery(f)
		if op == "CommitReceiverConsume" {
			q = f.consumeQ
		}
		if v := f.remote(op, q); v["ok"] == true {
			t.Fatal("source loss allowed ", op)
		}
	}
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("invalid source consumed")
	}
}
func TestAgent2ReviewPhysicalObserveOutsideSQLLocks(t *testing.T) {
	src := &reviewSource{entered: make(chan struct{}), release: make(chan struct{})}
	f := newObservedReview(t, src)
	f.ready()
	src.blocking.Store(true)
	done := make(chan error, 1)
	go func() { _, e := f.registry.VerifyInstallation(f.ctx, f.registrar, mustDocument(&f.binding)); done <- e }()
	<-src.entered
	ctx, cancel := context.WithTimeout(f.ctx, 100*time.Millisecond)
	defer cancel()
	tx, e := f.s.DB.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	_, e = tx.Exec(ctx, "SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE NOWAIT", f.cmd["runId"])
	tx.Rollback(context.Background())
	close(src.release)
	if e != nil {
		t.Fatal("Observe held run SQL lock", e)
	}
	if e = <-done; e != nil {
		t.Fatal(e)
	}
}
func TestAgent2ReviewOutputExpiresDuringFirstConsumeRPC(t *testing.T) {
	src := &reviewSource{entered: make(chan struct{}), release: make(chan struct{})}
	f := newObservedReview(t, src)
	f.ready()
	src.blocking.Store(true)
	done := make(chan authority.Document, 1)
	go func() { done <- f.remote("CommitReceiverConsume", f.consumeQ) }()
	<-src.entered
	f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp() WHERE room_id=$1", f.control.Room)
	close(src.release)
	v := <-done
	reviewNoTrue(t, v)
	if v["ok"] == true || f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("expired output consumed", v)
	}
}
func TestAgent2ReviewRevocationDuringSourceReadDenies(t *testing.T) {
	src := &reviewSource{entered: make(chan struct{}), release: make(chan struct{})}
	f := newObservedReview(t, src)
	f.ready()
	src.blocking.Store(true)
	done := make(chan authority.Document, 1)
	go func() { done <- f.remote("CommitReceiverConsume", f.consumeQ) }()
	<-src.entered
	op, _ := wire.LookupOperation(wire.OpRevokeReceiverBootstrap)
	wc := wire.RequestContext{Role: wire.RoleControlRegistrar, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	raw := mustJSON(f.private(authority.Document{"bootstrapId": f.binding.BootstrapID, "expectedRegistrationRevision": 1, "reason": "SESSION_REPLACED"}))
	_, e := f.s.Handle(f.ctx, f.registrar, op.ID, wc, raw)
	close(src.release)
	if e != nil {
		t.Fatal(e)
	}
	v := <-done
	reviewNoTrue(t, v)
	if v["ok"] == true || f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("revoked context consumed", v)
	}
}
func TestAgent2ReviewRegistrationSourceChangeAndScope(t *testing.T) {
	f := newInterop(t)
	for _, kind := range []string{"tenant", "owner", "room", "command", "generation", "guardian", "runtime"} {
		t.Run(kind, func(t *testing.T) {
			b := f.binding
			actor := f.registrar
			switch kind {
			case "tenant":
				actor.Tenant = "foreign"
			case "owner":
				actor.Owner = "foreign"
			case "room":
				actor.Room = "foreign"
			case "command":
				b.CommandID = "foreign"
			case "generation":
				b.GenerationID++
			case "guardian":
				b.GuardianIncarnation = "foreign"
			case "runtime":
				b.RuntimePrincipalID = "foreign"
			}
			if _, e := f.registry.VerifyInstallation(f.ctx, actor, mustDocument(&b)); e == nil {
				t.Fatal("foreign source accepted")
			}
		})
	}
}
func TestAgent2ReviewSharedStoreRegistryDispatch(t *testing.T) {
	a := newInterop(t)
	b := newInterop(t)
	// Move the second immutable native installation through the SAME registry/store
	// repository seam. Both SQL scopes exist in this owned database.
	if _, e := a.registry.Install(b.ctx, b.registrar, b.rt.managed.Pin, b.g.managed.Pin, physicalFixture{b.registrar.ID, b.guardian.ID}); e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 3; i++ {
		for _, f := range []*interop{a, b} {
			if _, e := a.registry.VerifyInstallation(f.ctx, f.registrar, mustDocument(&f.binding)); e != nil {
				t.Fatal("last-session-wins source", e)
			}
		}
	}
	if _, e := NewRegistry(a.s); e == nil {
		t.Fatal("second registry replaced source")
	}
	if _, e := a.registry.VerifyInstallation(a.ctx, a.registrar, mustDocument(&b.binding)); e == nil {
		t.Fatal("foreign registrar read second scope")
	}
	// Do not invent a production Assertions dispatcher. Pin the delivered seam's
	// actual behavior: the second per-command verifier must not overwrite first.
	va, vb := a.s.Assertions, b.s.Assertions
	a.s.Assertions = func(ctx context.Context, p authority.Actor, d authority.Document) error {
		switch d["commandId"] {
		case a.cmd["commandId"]:
			return va(ctx, p, d)
		case b.cmd["commandId"]:
			return vb(ctx, p, d)
		default:
			return errors.New("unknown command")
		}
	}
	b.s = a.s
	b.registry = a.registry
	a.ready()
	b.ready()
	for _, f := range []*interop{a, b} {
		q := f.private(authority.Document{"references": f.consumeQ["references"]})
		op, _ := wire.LookupOperation(wire.OpQueryReceiverAuthority)
		wc := wire.RequestContext{Role: wire.RoleOutputGuardian, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
		if _, e := a.s.Handle(f.ctx, f.guardian, op.ID, wc, mustJSON(q)); e != nil {
			t.Fatal("shared Store legal scope denied", e)
		}
	}
	for _, f := range []*interop{a, b} {
		if e := f.server.Close(); e != nil {
			t.Fatal(e)
		}
	}
	for _, f := range []*interop{a, b} {
		var e error
		f.server, e = NewServer(a.s, a.registry, a.g.managed.Pin, b.g.managed.Pin)
		if e != nil {
			t.Fatal(e)
		}
		if e = f.server.Listen(filepath.Join(f.root, "authority.sock")); e != nil {
			t.Fatal(e)
		}
	}
	for _, f := range []*interop{a, b} {
		if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] != true {
			t.Fatal("shared native transport scope denied", v)
		}
	}
	cross := a.private(authority.Document{"references": b.consumeQ["references"]})
	if v := a.remote("QueryReceiverAuthority", cross); v["ok"] == true {
		t.Fatal("cross-tenant native scope admitted")
	}

	t.Log("InstallationSource uses delivered single dispatcher. Assertions multiplexing here is an explicit test-only composition; no production multi-room Assertions root is delivered.")
}
func TestAgent2ReviewHistoricalConsumptionAfterSourceLoss(t *testing.T) {
	src := &reviewSource{}
	f := newObservedReview(t, src)
	f.ready()
	if v := f.remote("CommitReceiverConsume", f.consumeQ); v["ok"] != true {
		t.Fatal(v)
	}
	src.valid.Store(false)
	q := f.private(authority.Document{"bootstrapId": f.binding.BootstrapID, "grantId": testObj(f.consumeQ, "references")["grantId"]})
	got := f.remote("QueryReceiverConsumption", q)
	if got["ok"] != true || testObj(testObj(got, "result"), "summary")["state"] != "CONSUMED" {
		t.Fatal("historical metadata lost", got)
	}
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("history changed latch")
	}
}
func TestAgent2ReviewGuardianRoutesDenyEveryControlOperation(t *testing.T) {
	f := newInterop(t)
	f.ready()
	for _, id := range []wire.OperationID{wire.OpRegisterReceiverBootstrap, wire.OpRevokeReceiverBootstrap, wire.OpJournalStart, wire.OpAcquireOutputPermit, wire.OpStopBroadcastRun} {
		op, _ := wire.LookupOperation(id)
		v := f.g.rpc(map[string]any{"action": "raw", "path": op.Path, "body": "e30="})
		if testN(testObj(v, "result")["status"]) != 403 {
			t.Fatal("Guardian reached control route", id, v)
		}
	}
}

// A new independently observed installation revision must not validate the old
// staged revision merely because the immutable descriptor did not change.
type revisionSource struct {
	physicalFixture
	revision atomic.Int64
}

func (s *revisionSource) Observe(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (wire.ReceiverPhysicalInstallation, error) {
	v, e := s.physicalFixture.Observe(ctx, b, r, g)
	v.InstallationRevision = wire.Revision(s.revision.Load())
	return v, e
}
func TestAgent2ReviewCurrentPhysicalRevisionBeforeRegister(t *testing.T) {
	source := &revisionSource{}
	source.revision.Store(1)
	f := newReviewInterop(t, func(f *interop) PhysicalSource {
		source.physicalFixture = physicalFixture{f.registrar.ID, f.guardian.ID}
		return source
	})
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		t.Fatal(e)
	}
	staged, e := f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q)
	if e != nil {
		t.Fatal(e)
	}
	if staged.Receipt.InstallationRevision != 1 {
		t.Fatal("fixture did not stage revision1")
	}
	source.revision.Store(2)
	observed, e := f.registry.VerifyInstallation(f.ctx, f.registrar, mustDocument(&f.binding))
	if e != nil {
		t.Log("current-source discrepancy refused early", e)
		return
	}
	t.Logf("trusted current installationRevision=%v; staged revision=%v", observed["installationRevision"], staged.Receipt.InstallationRevision)
	out, e := f.registry.Register(f.ctx, f.registrar, f.binding, staged.Receipt)
	if e == nil {
		f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
		pm := f.call(f.runtime, "AcquireOutputPermit", f.q(authority.Document{"sessionId": f.cmd["sessionId"], "runEpoch": 1, "producerIncarnation": f.runtime.Producer, "guardianId": f.binding.GuardianID, "answerArtifactId": f.unit["artifactId"]}))
		start := f.call(f.runtime, "JournalStart", f.q(authority.Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": 1, "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": pm["permitId"], "expectedInboxRevision": 2, "answerArtifactId": f.unit["artifactId"], "answerArtifactHash": f.unit["artifactHash"], "expectedAnswerRevision": 1}))
		consume := f.private(authority.Document{"references": authority.Document{"bootstrapId": f.binding.BootstrapID, "artifactId": f.unit["artifactId"], "artifactHash": f.unit["artifactHash"], "grantId": testObj(start, "answerGrant")["grantId"], "permitId": pm["permitId"]}, "consumeTicket": start["consumeTicket"], "consumeRequestId": fresh("consume_"), "runtimePrincipalId": f.runtime.ID, "runtimeIncarnation": f.runtime.Incarnation, "channelBinding": testHash("fixture-runtime-channel"), "expectedRegistrationRevision": 1})
		v := f.remote("CommitReceiverConsume", consume)
		t.Fatalf("STALE_PHYSICAL_REVISION: source=2 staged=1 mirror=1 register=%T ACTIVE bootstraps=%d; real Authority RPC ok=%v consumeAuthorized=%v latches=%d", out, f.count("dl05_receiver_bootstraps"), v["ok"], testObj(v, "result")["consumeAuthorized"], f.count("dl05_receiver_consumptions"))
	}
}

func TestAgent2ReviewCurrentPhysicalRevisionAfterRegister(t *testing.T) {
	source := &revisionSource{}
	source.revision.Store(1)
	f := newReviewInterop(t, func(f *interop) PhysicalSource {
		source.physicalFixture = physicalFixture{f.registrar.ID, f.guardian.ID}
		return source
	})
	f.ready()
	source.revision.Store(2)
	query := f.remote("QueryReceiverAuthority", reviewQuery(f))
	consume := f.remote("CommitReceiverConsume", f.consumeQ)
	if query["ok"] == true || consume["ok"] == true {
		t.Fatalf("STALE_PHYSICAL_REVISION_AFTER_REGISTER: source=2 mirror/staged=1 queryOK=%v consumeOK=%v consumeAuthorized=%v latches=%d", query["ok"], consume["ok"], testObj(consume, "result")["consumeAuthorized"], f.count("dl05_receiver_consumptions"))
	}
}

func TestAgent2ReviewFirstConsumeFinalDeadlineAndRPCGate(t *testing.T) {
	f := newInterop(t)
	f.ready()
	f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '150 milliseconds' WHERE room_id=$1", f.control.Room)
	original := f.s.Validate
	entered := make(chan struct{})
	finished := make(chan struct{})
	var once sync.Once
	f.s.Validate = func(name string, d authority.Document) error {
		if e := original(name, d); e != nil {
			return e
		}
		if name == "CommitReceiverConsumeResponse" {
			once.Do(func() { close(entered) })
			time.Sleep(220 * time.Millisecond)
			close(finished)
		}
		return nil
	}
	got := f.remote("CommitReceiverConsume", f.consumeQ)
	reviewNoTrue(t, got)
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("final Consume validator was not exercised")
	}
	select {
	case <-finished:
	case <-time.After(time.Second):
		t.Fatal("final Consume validation did not finish")
	}
	// Query waits until the response transaction releases the same run lock,
	// proving its eventual commit/rollback result rather than checking too early.
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	_, e = tx.Exec(f.ctx, "SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE", f.cmd["runId"])
	if e != nil {
		t.Fatal(e)
	}
	tx.Rollback(f.ctx)
	if got["ok"] == true || f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("expired final Consume survived DB/transport gate", got)
	}
}

// Test-only clone of Agent4 newInterop, changing only the constructor name and
// initial PhysicalSource injection. No production/Agent4 source is modified.
func newReviewInterop(t *testing.T, factory func(*interop) PhysicalSource) *interop {
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
	f.binding, e = f.registry.Install(f.ctx, f.registrar, f.rt.managed.Pin, f.g.managed.Pin, factory(f))
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

func newObservedReview(t *testing.T, source *reviewSource) *interop {
	source.valid.Store(true)
	return newReviewInterop(t, func(f *interop) PhysicalSource {
		source.fixture = physicalFixture{f.registrar.ID, f.guardian.ID}
		return source
	})
}
