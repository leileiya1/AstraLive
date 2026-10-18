package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	domain "astralive/backend/internal/contentplan/answerstream"
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"encoding/json"
	"io"
	"sync"
	"testing"
	"time"
)

func TestPostgresStreamingTwoUnits(t *testing.T) {
	for _, order := range []string{"prepare-before-drain", "drain-before-late-prepare"} {
		t.Run(order, func(t *testing.T) {
			f := newPGStream(t)
			c := f.coordinator(&mockSource{tokens: []rune(pgReply)})
			must(t, c.PrepareNext())
			must(t, c.StartNext())
			f.assertSlot(true)
			if order == "prepare-before-drain" {
				must(t, c.PrepareNext())
				expect(t, c.StartNext(), ErrNotReady)
				must(t, c.Drain())
			} else {
				must(t, c.Drain())
				must(t, c.PrepareNext())
			}
			f.assertSlot(true)
			must(t, c.StartNext())
			expect(t, c.PrepareNext(), io.EOF)
			expect(t, c.Complete(), ErrNotReady)
			must(t, c.Drain())
			f.assertSlot(true)
			must(t, c.Complete())
			f.assertSlot(false)
			if f.count("dl05_answer_segments") != 2 || f.count("dl05_answer_grants") != 2 || f.count("dl05_receiver_consumptions") != 2 {
				t.Fatal("wrong durable unit/grant/latch counts")
			}
			var first, executions, turns int
			if e := f.pool.QueryRow(f.ctx, "SELECT count(*) FROM dl05_answer_grants WHERE command_id=$1 AND (grant_body->>'sequence')::int=1", f.b.Command).Scan(&first); e != nil {
				t.Fatal(e)
			}
			if e := f.pool.QueryRow(f.ctx, "SELECT count(DISTINCT execution_id) FROM dl05_receiver_consumptions WHERE command_id=$1", f.b.Command).Scan(&executions); e != nil {
				t.Fatal(e)
			}
			if e := f.pool.QueryRow(f.ctx, "SELECT count(*) FROM dl05_turns WHERE run_id=$1", f.b.Run).Scan(&turns); e != nil {
				t.Fatal(e)
			}
			if first != 1 || executions != 2 || turns != 1 || f.receiver.acks != 2 {
				t.Fatal("duplicate business identity/first START")
			}
			t.Logf("REAL_PG order=%s global_start_grants=%d units=2 grants=2 latches=2 executions=%d turns=%d synthetic_receiver_acks=%d CONTROL_completed=true script_cursor_unchanged=true", order, first, executions, turns, f.receiver.acks)
		})
	}
}
func TestPostgresStreamingFirstUnitBeforeProviderEOF(t *testing.T) {
	f := newPGStream(t)
	s := &channelSource{chunks: make(chan string), done: make(chan struct{})}
	c := f.coordinator(s)
	result := make(chan error, 1)
	go func() { result <- c.PrepareNext() }()
	s.chunks <- "这款的价格是129.90元。"
	must(t, <-result)
	must(t, c.StartNext())
	if c.View().Sealed || f.count("dl05_answer_grants") != 1 || f.receiver.acks != 1 {
		t.Fatal("EOF gate")
	}
	f.assertSlot(true)
	go func() { result <- c.PrepareNext() }()
	must(t, c.Drain())
	s.chunks <- "这款有XL尺码。"
	must(t, <-result)
	must(t, c.StartNext())
	must(t, c.Drain())
	close(s.chunks)
	expect(t, c.PrepareNext(), io.EOF)
	must(t, c.Complete())
	f.assertSlot(false)
	t.Log("REAL_PG first Prepare+legal START+Backend latch committed before provider EOF; second Prepare after trusted fixture drain")
}
func TestPostgresStreamingUnsafeAssertions(t *testing.T) {
	for _, text := range []string{"这款的价格是1元。", "如果您需要XL尺码。", "这款不是防水款。", "这款比旧款轻20g。", "这款的价格是129。90元。"} {
		t.Run(text, func(t *testing.T) {
			f := newPGStream(t)
			c := f.coordinator(&mockSource{tokens: []rune(text)})
			if e := c.PrepareNext(); e == nil {
				t.Fatal("unproven SQL-source assertion accepted")
			}
			if f.count("dl05_answer_segments") != 0 {
				t.Fatal("unproven artifact persisted")
			}
			f.assertSlot(true)
		})
	}
}

// Transport fault injection forwards the exact official request to REAL Handle,
// then discards only the committed response. It never synthesizes a SQL success.
type droppedResponse struct {
	store *authority.Store
	op    wire.OperationID
	once  sync.Once
}

func (h *droppedResponse) Handle(ctx context.Context, p authority.Actor, op wire.OperationID, meta wire.RequestContext, raw []byte) (wire.Message, error) {
	v, e := h.store.Handle(ctx, p, op, meta, raw)
	if e == nil && op == h.op {
		lost := false
		h.once.Do(func() { lost = true })
		if lost {
			return nil, context.DeadlineExceeded
		}
	}
	return v, e
}
func denied(t *testing.T, e error) {
	t.Helper()
	if e == nil {
		t.Fatal("authority unexpectedly authorized")
	}
}
func summary(f *pgStream, a []domain.Artifact) domain.Summary {
	s := domain.Summary{Binding: f.b}
	text := ""
	for _, v := range a {
		d := v.Draft()
		s.Entries = append(s.Entries, domain.ManifestEntry{ID: d.ID, Sequence: d.Sequence, Digest: v.Hash()})
		text += d.Text
		s.Characters += len([]rune(d.Text))
	}
	s.TextHash = cp.Hash(text)
	return s
}
func prepareCall(f *pgStream, a domain.Artifact, i, r int64, key string) (wire.Message, error) {
	q, e := a.PrepareRequest("owned-request", i, r)
	if e != nil {
		return nil, e
	}
	if key != "" {
		q.IdempotencyKey = wire.ID(key)
	}
	return CallAuthority(f.ctx, f.store, f.runtime, wire.OpJournalPrepareAnswer, q)
}
func TestPostgresStreamingPrepareCASReceiptAndLostReply(t *testing.T) {
	f := newPGStream(t)
	a := f.artifacts()[0]
	_, e := prepareCall(f, a, 2, 0, "")
	denied(t, e)
	if e.Error() != "STATE_CONFLICT" || f.count("dl05_answer_segments") != 0 {
		t.Fatal("failed CAS had effects", e)
	}
	// Two competing revisions for the same immutable artifact: one fresh CAS and
	// one stale CAS are serialized; the duplicate returns the original receipt.
	results := make(chan wire.Message, 2)
	errs := make(chan error, 2)
	var wg sync.WaitGroup
	for n := 0; n < 2; n++ {
		wg.Add(1)
		go func() { defer wg.Done(); v, e := prepareCall(f, a, 1, 0, ""); results <- v; errs <- e }()
	}
	wg.Wait()
	close(results)
	close(errs)
	for e := range errs {
		must(t, e)
	}
	rev := int64(0)
	for v := range results {
		x := v.(*wire.JournalPrepareAnswerResponse)
		if rev != 0 && int64(x.AnswerRevision) != rev {
			t.Fatal("receipt changed")
		}
		rev = int64(x.AnswerRevision)
	}
	_, e = prepareCall(f, a, 1, 0, "alias")
	must(t, e)
	_, e = prepareCall(f, a, 1, 0, "")
	must(t, e)
	if f.count("dl05_answer_segments") != 1 || f.count("dl05_answer_prepare_keys") != 2 || f.count("dl05_answer_grants") != 0 {
		t.Fatal("duplicate Prepare created execution permission")
	}
	var text, th, ah, snapshot string
	var deps []byte
	must(t, f.pool.QueryRow(f.ctx, "SELECT answer_text,text_hash,artifact_hash,snapshot_version,facts FROM dl05_answer_segments WHERE command_id=$1", f.b.Command).Scan(&text, &th, &ah, &snapshot, &deps))
	if text != a.Draft().Text || th != cp.Hash(text) || ah != a.Hash() || snapshot != f.b.Snapshot {
		t.Fatal("actual body/hash/snapshot mismatch")
	}
	var facts []map[string]any
	must(t, json.Unmarshal(deps, &facts))
	if len(facts) != 1 || facts[0]["kind"] != "PRICE" {
		t.Fatal("missing actual dependencies")
	}
	t.Log("REAL_PG stale CAS rollback; concurrent original request+alias return original receipt; actual body/textHash/artifactHash/snapshot/PRICE persisted; grants=0")
	t.Run("lost-prepare-reply", func(t *testing.T) {
		f := newPGStream(t)
		f.adapter.Client = &droppedResponse{store: f.store, op: wire.OpJournalPrepareAnswer}
		c := f.coordinator(&mockSource{tokens: []rune(pgReply)})
		expect(t, c.PrepareNext(), ErrPrepareUncertain)
		must(t, c.PrepareNext())
		must(t, c.StartNext())
		if f.count("dl05_answer_segments") != 1 || f.count("dl05_answer_grants") != 1 || f.count("dl05_receiver_consumptions") != 1 {
			t.Fatal("same-identity retry created duplicate")
		}
	})
}
func TestPostgresStreamingChangedTrustedProduct(t *testing.T) {
	for _, kind := range []string{"price", "stock", "version", "switch"} {
		t.Run(kind, func(t *testing.T) {
			f := newPGStream(t)
			a := f.artifacts()
			must(t, f.adapter.Prepare(f.ctx, a[0]))
			must(t, f.adapter.Start(f.ctx, a[0], First))
			must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
			must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
			switch kind {
			case "price":
				f.exec("UPDATE products SET price=130.00,updated_at=clock_timestamp() WHERE id=$1", f.b.Product)
			case "stock":
				f.exec("UPDATE products SET stock=0,updated_at=clock_timestamp() WHERE id=$1", f.b.Product)
			case "version":
				f.exec("UPDATE products SET updated_at=clock_timestamp() WHERE id=$1", f.b.Product)
			case "switch":
				f.exec("INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES($1,'new','纯棉',99,'CNY',2,ARRAY['XL'])", f.prefix+"other")
				f.exec("INSERT INTO resource_owners VALUES('product',$1,$2,$3)", f.prefix+"other", f.b.Tenant, f.b.Owner)
				f.exec("UPDATE live_rooms SET active_product_id=$2 WHERE id=$1", f.room, f.prefix+"other")
			}
			denied(t, f.adapter.Check(f.ctx, a[1]))
			denied(t, f.adapter.Prepare(f.ctx, a[1]))
			denied(t, f.adapter.Start(f.ctx, a[1], Continuation))
			f.assertSlot(true)
			if f.count("dl05_answer_grants") != 1 || f.count("dl05_receiver_consumptions") != 1 {
				t.Fatal("old answer authorized after change")
			}
		})
	}
}
func TestPostgresStreamingLostACKUnknownNoReplay(t *testing.T) {
	for _, op := range []string{"JournalStart", "CommitReceiverConsume"} {
		t.Run(op, func(t *testing.T) {
			f := newPGStream(t)
			c := f.coordinator(&mockSource{tokens: []rune(pgReply)})
			if op == "JournalStart" {
				f.adapter.Client = &droppedResponse{store: f.store, op: wire.OpJournalStart}
			} else {
				f.receiver.loseACK = true
			}
			must(t, c.PrepareNext())
			expect(t, c.StartNext(), ErrUnknown)
			var state string
			must(t, f.pool.QueryRow(f.ctx, "SELECT last_checkpoint FROM dl05_attempts WHERE attempt_id=$1", f.b.Attempt).Scan(&state))
			if state != "UNKNOWN" || !c.View().Unknown {
				t.Fatal("lost ACK not durable UNKNOWN", state)
			}
			expect(t, c.StartNext(), ErrUnknown)
			denied(t, c.Complete())
			f.assertSlot(true)
			// Simulate coordinator restart, retaining the same admitted identity; real
			// Authority UNKNOWN prevents fresh Adapter state from obtaining another START.
			f.adapter = &AuthorityAdapter{Store: f.store, Runtime: f.runtime, Control: f.control, Facts: f.facts, Receiver: f.receiver, GuardianID: f.prefix + "output"}
			a := f.artifacts()[0]
			denied(t, f.adapter.Start(f.ctx, a, First))
			want := 0
			if op == "CommitReceiverConsume" {
				want = 1
				_, e := f.call(f.guardian, "CommitReceiverConsume", f.receiver.lastConsume)
				denied(t, e)
			}
			if f.count("dl05_receiver_consumptions") != want || f.count("dl05_answer_grants") != 1 || f.receiver.acks != 0 {
				t.Fatal("uncertain latch replayed")
			}
			t.Logf("REAL_PG lost %s reply -> durable UNKNOWN; latch=%d; original START grant=1; restart denied; Slot held; cursor READY", op, want)
		})
	}
}
func (f *pgStream) stopRequest() map[string]any {
	q := f.base()
	q["reasonCode"] = "OWNED_TEST_STOP"
	q["decisionId"] = f.prefix + "stop"
	q["expectedRevision"] = 1
	q["idempotencyKey"] = "stop"
	return q
}
func TestPostgresStreamingStopCompetition(t *testing.T) {
	for _, stage := range []string{"Prepare", "Start", "Continuation"} {
		for _, order := range []string{"stop-first", "operation-first", "race"} {
			t.Run(stage+"/"+order, func(t *testing.T) {
				f := newPGStream(t)
				a := f.artifacts()
				work := func() error { return f.adapter.Prepare(f.ctx, a[0]) }
				if stage != "Prepare" {
					must(t, work())
					work = func() error { return f.adapter.Start(f.ctx, a[0], First) }
				}
				if stage == "Continuation" {
					must(t, work())
					must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
					must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
					must(t, f.adapter.Prepare(f.ctx, a[1]))
					work = func() error { return f.adapter.Start(f.ctx, a[1], Continuation) }
				}
				stop := func() error { _, e := f.call(f.control, "StopBroadcastRun", f.stopRequest()); return e }
				if order == "stop-first" {
					must(t, stop())
					denied(t, work())
				} else if order == "operation-first" {
					must(t, work())
					must(t, stop())
				} else {
					var wg sync.WaitGroup
					wg.Add(2)
					go func() { defer wg.Done(); _ = work() }()
					go func() {
						defer wg.Done()
						if e := stop(); e != nil {
							t.Error(e)
						}
					}()
					wg.Wait()
				}
				n := f.count("dl05_answer_grants")
				l := f.count("dl05_receiver_consumptions")
				denied(t, f.adapter.Prepare(f.ctx, a[0]))
				denied(t, f.adapter.Start(f.ctx, a[0], First))
				denied(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
				denied(t, f.adapter.Start(f.ctx, a[1], Continuation))
				if f.count("dl05_answer_grants") != n || f.count("dl05_receiver_consumptions") != l {
					t.Fatal("Stop reauthorized")
				}
				f.assertSlot(true)
			})
		}
	}
}
func TestPostgresStreamingSealDrainControlGates(t *testing.T) {
	for _, missing := range []string{"seal", "required-drain"} {
		t.Run(missing, func(t *testing.T) {
			f := newPGStream(t)
			a := f.artifacts()[:1]
			s := summary(f, a)
			must(t, f.adapter.Prepare(f.ctx, a[0]))
			must(t, f.adapter.Start(f.ctx, a[0], First))
			must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
			if missing == "seal" {
				must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
			} else {
				must(t, f.adapter.Seal(f.ctx, s))
			}
			denied(t, f.adapter.Commit(f.ctx, s))
			f.assertSlot(true)
			if missing == "seal" {
				must(t, f.adapter.Seal(f.ctx, s))
			} else {
				must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
			}
			f.assertSlot(true)
			must(t, f.adapter.Commit(f.ctx, s))
			f.assertSlot(false)
		})
	}
}
func TestPostgresStreamingSourceAssertionsCannotSelfCertify(t *testing.T) {
	f := newPGStream(t)
	a := f.artifacts()[0]
	q, e := a.PrepareRequest("owned-request", 1, 0)
	must(t, e)
	// Rehash actual malicious body after removing its PRICE dependency: schema
	// hashes alone are not an authority claim. Trusted assertion mapping rejects.
	q.Artifact.FactDependencies = []wire.FactDependency{}
	q.Artifact.AssertionKinds = []wire.AnswerArtifactAssertionKindsItem{}
	raw, e := wire.Encode(&q.Artifact)
	must(t, e)
	m := integerDocument(raw)
	delete(m, "artifactHash")
	hash, e := cp.Version(m)
	must(t, e)
	q.Artifact.ArtifactHash = wire.Hash(hash)
	_, e = CallAuthority(f.ctx, f.store, f.runtime, wire.OpJournalPrepareAnswer, q)
	denied(t, e)
	if f.count("dl05_answer_segments") != 0 {
		t.Fatal("LLM dependencies became authority")
	}
}

// Trusted mirror updates only, in Run -> mirror lock order. No answer, inbox,
// grant, execution, drain, latch or receipt SQL mutation is used by these tests.
func (f *pgStream) outputDeadline(after time.Duration) time.Time {
	f.t.Helper()
	tx, e := f.pool.Begin(f.ctx)
	must(f.t, e)
	defer tx.Rollback(f.ctx)
	_, e = tx.Exec(f.ctx, "SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE", f.b.Run)
	must(f.t, e)
	var until time.Time
	e = tx.QueryRow(f.ctx, "UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+$2::bigint*interval '1 microsecond' WHERE room_id=$1 RETURNING expires_at", f.room, after.Microseconds()).Scan(&until)
	must(f.t, e)
	must(f.t, tx.Commit(f.ctx))
	return until
}
func TestPostgresStreamingEarliestOutputDeadline(t *testing.T) {
	for _, stage := range []string{"before-permit", "after-grant", "after-consume"} {
		t.Run(stage, func(t *testing.T) {
			f := newPGStream(t)
			a := f.artifacts()[0]
			must(t, f.adapter.Prepare(f.ctx, a))
			if stage == "before-permit" {
				f.outputDeadline(-time.Millisecond)
				denied(t, f.adapter.Start(f.ctx, a, First))
			} else {
				f.outputDeadline(600 * time.Millisecond)
				must(t, f.adapter.Start(f.ctx, a, First))
				f.adapter.mu.Lock()
				p := f.adapter.pending[a.Draft().ID]
				f.adapter.mu.Unlock()
				if stage == "after-consume" {
					must(t, f.adapter.ConsumeOnce(f.ctx, a))
				}
				until := f.outputDeadline(200 * time.Millisecond)
				q := f.private()
				q["references"] = wire.ReceiverReferences{BootstrapID: f.bootstrap.BootstrapID, ArtifactID: wire.ID(a.Draft().ID), ArtifactHash: wire.Hash(a.Hash()), GrantID: p.grant.GrantID, PermitID: p.permit.PermitID}
				response, e := f.call(f.guardian, "QueryReceiverAuthority", q)
				must(t, e)
				snapshot := response.(*wire.QueryReceiverAuthorityResponse).Snapshot
				at, e := time.Parse(time.RFC3339Nano, string(snapshot.AuthorityTime))
				must(t, e)
				valid, e := time.Parse(time.RFC3339Nano, string(snapshot.ValidUntil))
				must(t, e)
				if valid.After(until) || int64(snapshot.Timing.RemainingProofMs) > valid.Sub(at).Milliseconds() {
					t.Fatal("proof exceeds earliest output deadline")
				}
				f.outputDeadline(-time.Millisecond)
				_, e = f.call(f.guardian, "QueryReceiverAuthority", q)
				denied(t, e)
				if stage == "after-grant" {
					denied(t, f.adapter.ConsumeOnce(f.ctx, a))
				} else {
					denied(t, f.adapter.Start(f.ctx, a, First))
				}
			}
			want := 0
			if stage == "after-consume" {
				want = 1
			}
			if f.count("dl05_receiver_consumptions") != want {
				t.Fatal("expired output created latch")
			}
			f.assertSlot(true)
		})
	}
}
func TestPostgresStreamingPermitExpiryAndRenewal(t *testing.T) {
	f := newPGStream(t)
	a := f.artifacts()[0]
	must(t, f.adapter.Prepare(f.ctx, a))
	must(t, f.adapter.Start(f.ctx, a, First))
	must(t, f.adapter.ConsumeOnce(f.ctx, a))
	time.Sleep(1050 * time.Millisecond) // actual one-second Permit expires; no TTL override
	q := f.base()
	q["sessionId"] = f.b.Session
	q["runEpoch"] = f.b.Epoch
	q["producerIncarnation"] = f.b.Producer
	q["guardianId"] = f.prefix + "output"
	q["answerArtifactId"] = a.Draft().ID
	pm, e := f.call(f.runtime, "AcquireOutputPermit", q)
	must(t, e)
	query := f.private()
	query["references"] = wire.ReceiverReferences{BootstrapID: f.bootstrap.BootstrapID, ArtifactID: wire.ID(a.Draft().ID), ArtifactHash: wire.Hash(a.Hash()), GrantID: f.receiver.consumed[a.Hash()].Binding.GrantID, PermitID: pm.(*wire.AcquireOutputPermitResponse).PermitID}
	proof, e := f.call(f.guardian, "QueryReceiverAuthority", query)
	must(t, e)
	if proof.(*wire.QueryReceiverAuthorityResponse).Snapshot.Consumption.State != "CONSUMED" {
		t.Fatal("renewed proof lost existing consumption")
	}
	// Draining an already consumed unit after its original Grant expires is
	// legal with unchanged facts and renewed proof, without a new START/TTS.
	must(t, f.adapter.ConfirmDrain(f.ctx, a))
	denied(t, f.adapter.Start(f.ctx, a, First))
	denied(t, f.adapter.ConsumeOnce(f.ctx, a))
	if f.count("dl05_answer_grants") != 1 || f.count("dl05_receiver_consumptions") != 1 || f.receiver.acks != 1 {
		t.Fatal("renew caused repeated speech")
	}
	f.assertSlot(true)
	t.Run("expiry-before-consume", func(t *testing.T) {
		f := newPGStream(t)
		a := f.artifacts()[0]
		must(t, f.adapter.Prepare(f.ctx, a))
		must(t, f.adapter.Start(f.ctx, a, First))
		time.Sleep(1050 * time.Millisecond)
		denied(t, f.adapter.ConsumeOnce(f.ctx, a))
		if f.count("dl05_receiver_consumptions") != 0 {
			t.Fatal("expired permit consumed")
		}
		f.assertSlot(true)
	})
}
func TestPostgresStreamingStaleEpochBindingAndExecution(t *testing.T) {
	for _, kind := range []string{"epoch", "output-binding", "old-generation-drain", "old-unit-drain"} {
		t.Run(kind, func(t *testing.T) {
			f := newPGStream(t)
			a := f.artifacts()
			must(t, f.adapter.Prepare(f.ctx, a[0]))
			must(t, f.adapter.Start(f.ctx, a[0], First))
			must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
			must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
			must(t, f.adapter.Prepare(f.ctx, a[1]))
			switch kind {
			case "epoch":
				f.exec("UPDATE dl05_runs SET run_epoch=2 WHERE run_id=$1", f.b.Run)
				denied(t, f.adapter.Start(f.ctx, a[1], Continuation))
			case "output-binding":
				f.exec("UPDATE dl05_room_outputs SET output_binding_version=output_binding_version+1 WHERE room_id=$1", f.room)
				denied(t, f.adapter.Start(f.ctx, a[1], Continuation))
			default:
				must(t, f.adapter.Start(f.ctx, a[1], Continuation))
				must(t, f.adapter.ConsumeOnce(f.ctx, a[1]))
				ev := f.receiver.evidence(100, 200, true, "ALL_REQUIRED_DRAIN")
				if kind == "old-generation-drain" {
					ev.SinkProofs[0].GenerationID = 6
				} else {
					ev = f.receiver.drains[a[0].Hash()]
				}
				raw, e := wire.Encode(&ev)
				must(t, e)
				denied(t, f.store.RecordDrainEvidence(f.ctx, f.observer, f.b.Command, a[1].Draft().ID, integerDocument(raw)))
				// Real new execution stays active; late old proof did not complete Unit2.
				var state string
				must(t, f.pool.QueryRow(f.ctx, "SELECT e.state FROM dl05_v2_execution_state e JOIN dl05_receiver_consumptions c USING(execution_id) WHERE c.artifact_id=$1", a[1].Draft().ID).Scan(&state))
				if state != "ACTIVE" {
					t.Fatal("late old execution crossed lineage", state)
				}
			}
			f.assertSlot(true)
		})
	}
}

func TestPostgresStreamingConcurrentDifferentPrepare(t *testing.T) {
	f := newPGStream(t)
	a := f.artifacts()[0]
	b := f.artifacts()[0]
	if a.Hash() == b.Hash() {
		t.Fatal("fixture requires different immutable descriptor")
	}
	start := make(chan struct{})
	results := make(chan error, 2)
	for _, v := range []domain.Artifact{a, b} {
		go func(a domain.Artifact) { <-start; _, e := prepareCall(f, a, 1, 0, ""); results <- e }(v)
	}
	close(start)
	wins, conflicts := 0, 0
	for n := 0; n < 2; n++ {
		e := <-results
		if e == nil {
			wins++
		} else if e.Error() == "ANSWER_CONFLICT" {
			conflicts++
		} else {
			t.Fatal(e)
		}
	}
	if wins != 1 || conflicts != 1 || f.count("dl05_answer_segments") != 1 || f.count("dl05_answer_grants") != 0 {
		t.Fatal("conflicting concurrent descriptors won", wins, conflicts)
	}
	f.assertSlot(true)
}
func TestPostgresStreamingLateUnitAfterFactObservationWindow(t *testing.T) {
	f := newPGStream(t)
	s := &channelSource{chunks: make(chan string), done: make(chan struct{})}
	c := f.coordinator(s)
	done := make(chan error, 1)
	go func() { done <- c.PrepareNext() }()
	s.chunks <- "这款的价格是129.90元。"
	must(t, <-done)
	must(t, c.StartNext())
	must(t, c.Drain())
	time.Sleep(2100 * time.Millisecond) // original fact observation is expired
	go func() { done <- c.PrepareNext() }()
	s.chunks <- "这款有XL尺码。"
	must(t, <-done)
	must(t, c.StartNext())
	must(t, c.Drain())
	close(s.chunks)
	expect(t, c.PrepareNext(), io.EOF)
	must(t, c.Complete())
	if f.count("dl05_answer_grants") != 2 || f.count("dl05_receiver_consumptions") != 2 {
		t.Fatal("late Unit2 lost parent identity")
	}
	f.assertSlot(false)
	t.Log("REAL_PG late Unit2 after original two-second observation expiry obtains fresh same-value facts/Permit; no ANSWER_GAP; START count remains one")
}
func TestPostgresStreamingContinuationBeforeDrainDeniedAndLostReply(t *testing.T) {
	for _, lost := range []bool{false, true} {
		t.Run(map[bool]string{false: "before-drain", true: "continuation-ACK-loss"}[lost], func(t *testing.T) {
			f := newPGStream(t)
			a := f.artifacts()
			must(t, f.adapter.Prepare(f.ctx, a[0]))
			must(t, f.adapter.Start(f.ctx, a[0], First))
			must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
			must(t, f.adapter.Prepare(f.ctx, a[1]))
			if !lost {
				q := f.adapter.base()
				q["sessionId"] = f.b.Session
				q["runEpoch"] = f.b.Epoch
				q["producerIncarnation"] = f.b.Producer
				q["guardianId"] = f.prefix + "output"
				q["answerArtifactId"] = a[1].Draft().ID
				pm, e := f.adapter.handle(f.ctx, f.runtime, "AcquireOutputPermit", q)
				must(t, e)
				_, rev, _, _, e := f.adapter.revisions(f.ctx)
				must(t, e)
				q = f.adapter.unitBase()
				q["permitId"] = pm.(*wire.AcquireOutputPermitResponse).PermitID
				q["answerId"] = f.b.Answer
				q["artifactId"] = a[1].Draft().ID
				q["artifactHash"] = a[1].Hash()
				q["expectedAnswerRevision"] = rev
				_, e = f.adapter.handle(f.ctx, f.runtime, "JournalStartAnswerSegment", q)
				denied(t, e)
				if f.count("dl05_answer_grants") != 1 {
					t.Fatal("early continuation granted")
				}
			}
			must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
			if lost {
				f.adapter.Client = &droppedResponse{store: f.store, op: wire.OpJournalStartAnswerSegment}
				expect(t, f.adapter.Start(f.ctx, a[1], Continuation), ErrUnknown)
				denied(t, f.adapter.Start(f.ctx, a[1], Continuation))
				denied(t, f.adapter.ConsumeOnce(f.ctx, a[1]))
				if f.count("dl05_receiver_consumptions") != 1 {
					t.Fatal("lost continuation reply replayed")
				}
			} else {
				must(t, f.adapter.Start(f.ctx, a[1], Continuation))
				must(t, f.adapter.ConsumeOnce(f.ctx, a[1]))
			}
			if f.count("dl05_answer_grants") != 2 {
				t.Fatal("duplicate START or continuation")
			}
			f.assertSlot(true)
		})
	}
}
func TestPostgresStreamingStopCutsConsumedACK(t *testing.T) {
	f := newPGStream(t)
	f.receiver.loseACK = true
	f.receiver.afterLatch = f.stop
	c := f.coordinator(&mockSource{tokens: []rune(pgReply)})
	must(t, c.PrepareNext())
	expect(t, c.StartNext(), ErrUnknown)
	var state string
	must(t, f.pool.QueryRow(f.ctx, "SELECT last_checkpoint FROM dl05_attempts WHERE attempt_id=$1", f.b.Attempt).Scan(&state))
	if state != "UNKNOWN" || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("Stop lost consumed uncertainty", state)
	}
	_, e := f.call(f.guardian, "CommitReceiverConsume", f.receiver.lastConsume)
	denied(t, e)
	f.assertSlot(true)
}
func TestPostgresStreamingLostLocalDrainCheckpointACK(t *testing.T) {
	f := newPGStream(t)
	a := f.artifacts()[:1]
	s := summary(f, a)
	must(t, f.adapter.Prepare(f.ctx, a[0]))
	must(t, f.adapter.Start(f.ctx, a[0], First))
	must(t, f.adapter.ConsumeOnce(f.ctx, a[0]))
	must(t, f.adapter.ConfirmDrain(f.ctx, a[0]))
	must(t, f.adapter.Seal(f.ctx, s))
	f.adapter.Client = &droppedResponse{store: f.store, op: wire.OpConfirmCheckpoint}
	expect(t, f.adapter.Commit(f.ctx, s), ErrUnknown)
	var state string
	must(t, f.pool.QueryRow(f.ctx, "SELECT last_checkpoint FROM dl05_attempts WHERE attempt_id=$1", f.b.Attempt).Scan(&state))
	if state != "UNKNOWN" {
		t.Fatal("lost checkpoint ACK not reconciled", state)
	}
	f.assertSlot(true)
}

func TestPostgresStreamingTrustedChineseSemanticUnits(t *testing.T) {
	for _, text := range []string{"这款的价格是129.90元。", "这款有XL尺码。", "这款有XXL尺码。", "这款有2XL尺码。", "这款没有S尺码。", "如果您需要XL尺码，那么这款有XL尺码。", "这款的库存是7件。", "这款采用纯棉面料。"} {
		t.Run(text, func(t *testing.T) {
			f := newPGStream(t)
			c := f.coordinator(&mockSource{tokens: []rune(text)})
			must(t, c.PrepareNext())
			must(t, c.StartNext())
			must(t, c.Drain())
			expect(t, c.PrepareNext(), io.EOF)
			must(t, c.Complete())
			f.assertSlot(false)
			var saved string
			must(t, f.pool.QueryRow(f.ctx, "SELECT answer_text FROM dl05_answer_segments WHERE command_id=$1", f.b.Command).Scan(&saved))
			if saved != text {
				t.Fatal("semantic assertion altered")
			}
		})
	}
}
