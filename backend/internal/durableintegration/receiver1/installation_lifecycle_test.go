package receiver1

import (
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

type lifecycleSource struct {
	physicalFixture
	gate     *InstallationGate
	revision atomic.Int64
}

func (s *lifecycleSource) Observe(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (wire.ReceiverPhysicalInstallation, error) {
	v, e := s.physicalFixture.Observe(ctx, b, r, g)
	v.InstallationRevision = wire.Revision(s.revision.Load())
	return v, e
}
func (s *lifecycleSource) InstallationGate(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (*InstallationGate, error) {
	v, e := s.Observe(ctx, b, r, g)
	if e != nil {
		return nil, e
	}
	s.gate, e = NewInstallationGate(v)
	return s.gate, e
}
func newLifecycle(t *testing.T) (*interop, *lifecycleSource) {
	s := &lifecycleSource{}
	s.revision.Store(1)
	f := newReviewInterop(t, func(f *interop) PhysicalSource {
		s.physicalFixture = physicalFixture{f.registrar.ID, f.guardian.ID}
		return s
	})
	return f, s
}
func waitGateClosed(t *testing.T, g *InstallationGate) {
	t.Helper()
	until := time.Now().Add(time.Second)
	for g.valid() {
		if time.Now().After(until) {
			t.Fatal("close admission was blocked")
		}
		time.Sleep(time.Millisecond)
	}
}
func waitRunLock(t *testing.T, f *interop) {
	t.Helper()
	until := time.Now().Add(time.Second)
	for {
		var n int
		e := f.s.DB.QueryRow(f.ctx, `SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND query LIKE '%FOR UPDATE%'`).Scan(&n)
		if e != nil {
			t.Fatal(e)
		}
		if n > 0 {
			return
		}
		if time.Now().After(until) {
			t.Fatal("no actual Authority Run-lock wait")
		}
		time.Sleep(time.Millisecond)
	}
}
func assertRetired(t *testing.T, f *interop) {
	t.Helper()
	var retired bool
	if e := f.s.DB.QueryRow(f.ctx, `SELECT retired_at IS NOT NULL FROM dl05_v2_installations WHERE command_id=$1`, f.cmd["commandId"]).Scan(&retired); e != nil || !retired {
		t.Fatal("mirror not durably retired", e)
	}
	v, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
	if e == nil && v["state"] != "REVOKED" {
		t.Fatal("active registration", v)
	}
}
func TestPostgresInstallationRetirementSerializesConsumeAndRunLock(t *testing.T) {
	f, s := newLifecycle(t)
	f.ready()
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, `SELECT 1 FROM dl05_runs WHERE run_id=$1 FOR UPDATE`, f.cmd["runId"]); e != nil {
		t.Fatal(e)
	}
	result := make(chan authority.Document, 1)
	go func() { result <- f.remote("CommitReceiverConsume", f.consumeQ) }()
	waitRunLock(t, f)
	changed := make(chan error, 1)
	go func() {
		e := f.registry.RetireInstallation(f.ctx, f.registrar, string(f.binding.CommandID))
		if e == nil {
			s.revision.Store(2)
		}
		changed <- e
	}()
	waitGateClosed(t, s.gate)
	if s.revision.Load() != 1 {
		t.Fatal("physical revision changed while SQL user still held gate")
	}
	select {
	case <-changed:
		t.Fatal("retirement bypassed active SQL user")
	default:
	}
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	got := <-result
	if got["ok"] == true {
		t.Fatal("positive ACK after admission withdrawal", got)
	}
	if e = <-changed; e != nil {
		t.Fatal(e)
	}
	if s.revision.Load() != 2 {
		t.Fatal("test transition missing")
	}
	assertRetired(t, f)
	var n int
	f.s.DB.QueryRow(f.ctx, `SELECT count(*) FROM dl05_receiver_consumptions WHERE command_id=$1`, f.cmd["commandId"]).Scan(&n)
	if n == 1 {
		var state string
		f.s.DB.QueryRow(f.ctx, `SELECT state FROM dl05_v2_execution_state WHERE command_id=$1`, f.cmd["commandId"]).Scan(&state)
		if state != "UNKNOWN" {
			t.Fatal("consumed execution lost UNKNOWN", state)
		}
	}
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
	t.Logf("Run-locked consume + retirement: latches=%d, physical changed only after durable revoke; no positive ACK", n)
}
func TestPostgresInstallationRetirementDuringRegister(t *testing.T) {
	f, s := newLifecycle(t)
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		t.Fatal(e)
	}
	staged, e := f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q)
	if e != nil {
		t.Fatal(e)
	}
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, `SELECT 1 FROM dl05_runs WHERE run_id=$1 FOR UPDATE`, f.cmd["runId"]); e != nil {
		t.Fatal(e)
	}
	registered := make(chan error, 1)
	go func() { _, e := f.registry.Register(f.ctx, f.registrar, f.binding, staged.Receipt); registered <- e }()
	waitRunLock(t, f)
	changed := make(chan error, 1)
	go func() {
		e := f.registry.RetireInstallation(f.ctx, f.registrar, string(f.binding.CommandID))
		if e == nil {
			s.revision.Store(2)
		}
		changed <- e
	}()
	waitGateClosed(t, s.gate)
	if s.revision.Load() != 1 {
		t.Fatal("source changed before SQL quiescence")
	}
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	if e = <-registered; e == nil {
		t.Fatal("positive registration after withdrawal")
	}
	if e = <-changed; e != nil {
		t.Fatal(e)
	}
	assertRetired(t, f)
	if _, e = f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q); e == nil {
		t.Fatal("old stage reopened retired source")
	}
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("Register minted a consumption")
	}
}
func TestPostgresInstallationConsumedRetirementPreservesHistory(t *testing.T) {
	f, s := newLifecycle(t)
	f.ready()
	got := f.remote("CommitReceiverConsume", f.consumeQ)
	if got["ok"] != true || testObj(got, "result")["consumeAuthorized"] != true {
		t.Fatal(got)
	}
	var before string
	f.s.DB.QueryRow(f.ctx, `SELECT row_to_json(c)::text FROM dl05_receiver_consumptions c WHERE command_id=$1`, f.cmd["commandId"]).Scan(&before)
	if e := f.registry.RetireInstallation(f.ctx, f.registrar, string(f.binding.CommandID)); e != nil {
		t.Fatal(e)
	}
	s.revision.Store(2)
	assertRetired(t, f)
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
	if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] == true {
		t.Fatal("retired proof renewed", v)
	}
	var after, state string
	f.s.DB.QueryRow(f.ctx, `SELECT row_to_json(c)::text FROM dl05_receiver_consumptions c WHERE command_id=$1`, f.cmd["commandId"]).Scan(&after)
	if before != after {
		t.Fatal("immutable consumption modified")
	}
	f.s.DB.QueryRow(f.ctx, `SELECT state FROM dl05_v2_execution_state WHERE command_id=$1`, f.cmd["commandId"]).Scan(&state)
	if state != "UNKNOWN" {
		t.Fatal(state)
	}
}

type uncoordinatedSource struct{ base physicalFixture }

func (s uncoordinatedSource) Observe(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (wire.ReceiverPhysicalInstallation, error) {
	return s.base.Observe(ctx, b, r, g)
}
func TestPostgresInstallationObserveOnlyCannotAuthorize(t *testing.T) {
	f := newInterop(t)
	rt := f.launch("REGISTERED_RUNTIME")
	g := f.launch("OUTPUT_GUARDIAN")
	n := f.count("dl05_v2_installations")
	if _, e := f.registry.Install(f.ctx, f.registrar, rt.managed.Pin, g.managed.Pin, uncoordinatedSource{physicalFixture{f.registrar.ID, g.managed.Pin.actor.ID}}); e == nil {
		t.Fatal("Observe-only source admitted")
	}
	if f.count("dl05_v2_installations") != n {
		t.Fatal("unsupported source mirrored")
	}
}
func TestInstallationGateCloseNeverReopensOrBlocks(t *testing.T) {
	// Local gate mechanics only; no physical-source acceptance.
	g := &InstallationGate{drained: make(chan struct{})}
	release, e := g.acquire(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	g.CloseAdmission()
	if g.valid() {
		t.Fatal("reopened")
	}
	if _, e = g.acquire(context.Background()); e == nil {
		t.Fatal("new reader")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
	defer cancel()
	if e = g.wait(ctx); e == nil {
		t.Fatal("drained before user returned")
	}
	release()
	release()
	if e = g.wait(context.Background()); e != nil {
		t.Fatal(e)
	}
	g.CloseAdmission()
}

func TestPostgresInstallationQueryConsumeWithdrawalSQLRace(t *testing.T) {
	f, s := newLifecycle(t)
	f.ready()
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, `SELECT 1 FROM dl05_runs WHERE run_id=$1 FOR UPDATE`, f.cmd["runId"]); e != nil {
		t.Fatal(e)
	}
	results := make(chan authority.Document, 1)
	go func() {
		results <- f.g.rpc(map[string]any{"action": "mixed_authority", "query": reviewQuery(f), "consume": f.consumeQ})
	}()
	waitRunLock(t, f)
	retired := make(chan error, 1)
	go func() {
		e := f.registry.RetireInstallation(f.ctx, f.registrar, string(f.binding.CommandID))
		if e == nil {
			s.revision.Store(2)
		}
		retired <- e
	}()
	waitGateClosed(t, s.gate)
	if s.revision.Load() != 1 {
		t.Fatal("source advanced while active SQL reader")
	}
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	got := <-results
	if got["ok"] != true || testN(testObj(got, "result")["positiveResponses"]) != 0 {
		t.Fatal("positive old proof/ACK after withdrawal", got)
	}
	if e = <-retired; e != nil {
		t.Fatal(e)
	}
	assertRetired(t, f)
	if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] == true {
		t.Fatal("retired proof", v)
	}
}
func TestPostgresInstallationUncoordinatedDriftDuringRegisterRefused(t *testing.T) {
	// Defense against an adapter violating the lifecycle contract. It is not an
	// example of how a real source may legally transition its physical revision.
	f, s := newLifecycle(t)
	q, e := f.registry.StageRequest(f.ctx, f.registrar, f.binding)
	if e != nil {
		t.Fatal(e)
	}
	staged, e := f.channel.Stage(f.ctx, filepath.Join(f.root, "guardian/control.sock"), f.g.managed.Pin, q)
	if e != nil {
		t.Fatal(e)
	}
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, `SELECT 1 FROM dl05_runs WHERE run_id=$1 FOR UPDATE`, f.cmd["runId"]); e != nil {
		t.Fatal(e)
	}
	done := make(chan error, 1)
	go func() { _, e := f.registry.Register(f.ctx, f.registrar, f.binding, staged.Receipt); done <- e }()
	waitRunLock(t, f)
	s.revision.Store(2)
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	if e = <-done; e == nil {
		t.Fatal("stale Register acknowledged")
	}
	if e = f.registry.RetireInstallation(f.ctx, f.registrar, string(f.binding.CommandID)); e != nil {
		t.Fatal(e)
	}
	assertRetired(t, f)
	var rev int
	f.s.DB.QueryRow(f.ctx, `SELECT installation_revision FROM dl05_v2_installations WHERE command_id=$1`, f.cmd["commandId"]).Scan(&rev)
	if rev != 1 {
		t.Fatal("historical revision rewritten", rev)
	}
}

func TestPostgresInstallationSessionExpiryReconcilesWithoutReplay(t *testing.T) {
	f, _ := newLifecycle(t)
	f.ready()
	got := f.remote("CommitReceiverConsume", f.consumeQ)
	if got["ok"] != true || testObj(got, "result")["consumeAuthorized"] != true {
		t.Fatal(got)
	}
	f.exec(`UPDATE session_provider_bindings SET expires_at=clock_timestamp() WHERE session_id=$1`, f.cmd["sessionId"])
	deadline := time.Now().Add(time.Second)
	for {
		v, e := f.registry.Confirm(f.ctx, f.registrar, f.binding)
		if e == nil && v["state"] == "REVOKED" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("trusted supervisor did not durably revoke expired Session", v, e)
		}
		time.Sleep(time.Millisecond)
	}
	assertRetired(t, f)
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("consumed latch changed")
	}
	if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] == true {
		t.Fatal("expired Binding proof renewed from old mirror", v)
	}
}
func TestPostgresInstallationCoexistingNativeGenerationCannotReuseOldGate(t *testing.T) {
	f, _ := newLifecycle(t)
	f.ready()
	old := f.binding
	f.binding.GenerationID++
	newRuntime := f.launch("REGISTERED_RUNTIME")
	newGuardian := f.launch("OUTPUT_GUARDIAN")
	f.binding = old
	// Both physical native processes coexist, same tenant/Room/Session/Attempt,
	// but new Generation/native key cannot replace an immutable current command.
	if _, e := f.registry.Install(f.ctx, f.registrar, newRuntime.managed.Pin, newGuardian.managed.Pin, physicalFixture{f.registrar.ID, newGuardian.managed.Pin.actor.ID}); e == nil {
		t.Fatal("new Generation silently overwrote old installation")
	}
	if e := f.registry.RetireInstallation(f.ctx, f.registrar, string(old.CommandID)); e != nil {
		t.Fatal(e)
	}
	f.exec(`UPDATE dl05_room_outputs SET output_binding_version=output_binding_version+1 WHERE room_id=$1`, f.control.Room)
	if v := f.remote("QueryReceiverAuthority", reviewQuery(f)); v["ok"] == true {
		t.Fatal("old native Generation inherited new output eligibility", v)
	}
	reviewNoTrue(t, f.remote("CommitReceiverConsume", f.consumeQ))
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("retired Generation created latch")
	}
}
