package answerstream

import (
	"astralive/backend/db"
	cp "astralive/backend/internal/contentplan"
	domain "astralive/backend/internal/contentplan/answerstream"
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"astralive/backend/internal/ids"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// Fixture boundary: SQL seeds ONLY an already-admitted Run/COMMENT/Outbox/Plan
// plus trusted source mirrors. No answer/grant/inbox/latch/drain/receipt state is
// inserted or updated by test SQL. Those mutations all traverse real Handle.
type pgStream struct {
	seedTx                                          pgx.Tx
	t                                               *testing.T
	ctx                                             context.Context
	pool                                            *pgxpool.Pool
	store                                           *authority.Store
	control, registrar, runtime, guardian, observer authority.Actor
	b                                               domain.Binding
	prefix, room, plan                              string
	command                                         *wire.RuntimeCommand
	bootstrap                                       wire.ReceiverBootstrapBinding
	facts                                           *domain.AuthorityFacts
	adapter                                         *AuthorityAdapter
	receiver                                        *syntheticReceiver
}

func newPGStream(t *testing.T) *pgStream {
	t.Helper()
	dsn := os.Getenv("AGENT3_STREAM_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires Agent3 owned PostgreSQL runner")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal(err)
	}
	marker, err := os.ReadFile(filepath.Join(os.Getenv("AGENT3_PG_OWNED_ROOT"), "AGENT3_OWNED"))
	if err != nil || string(marker) != "agent3 isolated streaming acceptance\n" || cfg.ConnConfig.Host != "127.0.0.1" || !strings.HasPrefix(cfg.ConnConfig.Database, "agent3_streaming_") {
		t.Fatal("refuse unowned/non-loopback database")
	}
	cfg.MaxConns = 16
	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err = db.Migrate(context.Background(), pool); err != nil {
		t.Fatal(err)
	}
	f := &pgStream{t: t, ctx: context.Background(), pool: pool, prefix: ids.New("pg3")}
	p := f.prefix
	f.room = p + "room"
	f.plan = p + "plan"
	f.control = authority.Actor{Role: "CONTROL", Tenant: p + "tenant", Owner: p + "owner", Room: f.room, ID: p + "control", Incarnation: p + "control_process"}
	f.registrar = f.control
	f.registrar.Role = "CONTROL_REGISTRAR"
	f.runtime = f.control
	f.runtime.Role = "RUNTIME_JOURNAL"
	f.runtime.ID = p + "runtime"
	f.runtime.Incarnation = p + "runtime_process"
	f.runtime.Producer = p + "producer"
	f.guardian = f.control
	f.guardian.Role = "OUTPUT_GUARDIAN"
	f.guardian.ID = p + "guardian"
	f.guardian.Incarnation = p + "guardian_process"
	f.observer = f.control
	f.observer.Role = "OBSERVER"
	f.observer.ID = p + "observer"
	f.observer.Incarnation = p + "observer_process"
	f.b = domain.Binding{Tenant: f.control.Tenant, Owner: f.control.Owner, Run: p + "run", Session: p + "session", Command: p + "command", Attempt: p + "attempt", Turn: p + "turn", Utterance: p + "utterance", Producer: f.runtime.Producer, Answer: p + "answer", Product: p + "product", Epoch: 1, Generation: 7}
	f.store = authority.New(pool)
	f.seedAdmission()
	projection, err := f.store.ProductProjection(f.ctx, f.control, f.b.Command)
	if err != nil {
		t.Fatal(err)
	}
	f.b.Snapshot = projection["snapshotVersion"].(string)
	tx, err := pool.Begin(f.ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(f.ctx)
	f.seedTx = tx
	f.exec(`INSERT INTO dl05_plans(tenant_id,owner_id,plan_id,run_id,product_id,product_snapshot_version,snapshot,revision,generation_source,segment_order,document) VALUES($1,$2,$3,$4,$5,$6,$7,1,'{}',$8,'{}')`, f.b.Tenant, f.b.Owner, f.plan, f.b.Run, f.b.Product, f.b.Snapshot, projection["snapshot"], []string{p + "script"})
	f.exec(`INSERT INTO dl05_segments(tenant_id,owner_id,segment_id,run_id,plan_id,sequence,content,text_hash,state,idempotency_key,checkpoint_state,fact_dependencies,estimated_duration_ms,document) VALUES($1,$2,$3,$4,$5,1,'商品讲解下一段',$6,'READY','script','PLANNED','[]',3000,'{}')`, f.b.Tenant, f.b.Owner, p+"script", f.b.Run, f.plan, cp.Hash("商品讲解下一段"))
	if err := tx.Commit(f.ctx); err != nil {
		t.Fatal(err)
	}
	f.seedTx = nil
	f.facts = &domain.AuthorityFacts{Store: f.store, Control: f.control, Binding: f.b}
	f.store.Assertions = f.facts.Verify
	f.receiver = &syntheticReceiver{f: f, drains: map[string]wire.Evidence{}, consumed: map[string]wire.ReceiverConsumption{}}
	f.adapter = &AuthorityAdapter{Store: f.store, Runtime: f.runtime, Control: f.control, Facts: f.facts, Receiver: f.receiver, GuardianID: p + "output"}
	f.installFixture()
	return f
}
func (f *pgStream) exec(sql string, args ...any) {
	f.t.Helper()
	if f.seedTx != nil {
		if _, err := f.seedTx.Exec(f.ctx, sql, args...); err != nil {
			f.t.Fatal(err)
		}
		return
	}
	if _, err := f.pool.Exec(f.ctx, sql, args...); err != nil {
		f.t.Fatal(err)
	}
}
func (f *pgStream) seedAdmission() {
	tx, err := f.pool.Begin(f.ctx)
	if err != nil {
		f.t.Fatal(err)
	}
	f.seedTx = tx
	defer tx.Rollback(f.ctx)
	b := f.b
	p := f.prefix
	f.exec("INSERT INTO config_principals VALUES($1,$2)", b.Tenant, b.Owner)
	f.exec("INSERT INTO avatars(id,name,engine) VALUES($1,'test','MOCK')", p+"avatar")
	f.exec("INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'test','mock','test')", p+"voice")
	f.exec("INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES($1,'测试商品','纯棉',129.90,'CNY',7,ARRAY['XL','XXL','2XL'])", b.Product)
	f.exec("INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES($1,'test',$2,$3,'test',$4)", f.room, p+"avatar", p+"voice", b.Product)
	f.exec("INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')", b.Session, f.room)
	for _, v := range [][2]string{{"room", f.room}, {"session", b.Session}, {"product", b.Product}} {
		f.exec("INSERT INTO resource_owners VALUES($1,$2,$3,$4)", v[0], v[1], b.Tenant, b.Owner)
	}
	f.exec("INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,$5,'{}',clock_timestamp()+interval '1 hour')", b.Session, b.Tenant, b.Owner, p+"binding", map[string]any{"activeProductId": b.Product})
	f.exec("INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy,run_epoch,contract_revision) VALUES($1,$2,$3,$4,'LIVE','LIVE','MANUAL_ON_UNKNOWN',1,'durable-live-2')", b.Tenant, b.Owner, b.Run, f.room)
	f.exec("INSERT INTO dl05_run_terms(tenant_id,owner_id,run_id,run_epoch,lease_owner,phase,previous_epoch,required_sinks,producer_incarnation,guardian_id) VALUES($1,$2,$3,1,$4,'ACTIVE',0,'[\"sink\"]',$5,$6)", b.Tenant, b.Owner, b.Run, f.control.ID, b.Producer, p+"output")
	f.exec("INSERT INTO dl05_run_leases(tenant_id,owner_id,run_id,lease_owner,lease_expires_at,fencing_token,run_epoch,lease_version,phase) VALUES($1,$2,$3,$4,clock_timestamp()+interval '1 hour',1,1,1,'ACTIVE')", b.Tenant, b.Owner, b.Run, f.control.ID)
	f.exec("INSERT INTO dl05_run_sessions(tenant_id,owner_id,run_session_id,run_id,session_id,binding_id,introduced_epoch) VALUES($1,$2,$3,$4,$5,$6,1)", b.Tenant, b.Owner, p+"rs", b.Run, b.Session, p+"binding")
	f.exec("UPDATE dl05_runs SET current_session_id=$2 WHERE run_id=$1", b.Run, b.Session)
	f.exec("INSERT INTO dl05_run_slots(tenant_id,owner_id,run_id,active_attempt_id) VALUES($1,$2,$3,NULL)", b.Tenant, b.Owner, b.Run)
	f.exec("INSERT INTO dl05_room_outputs(room_id,tenant_id,owner_id,active_run_id,guardian_id,expires_at,fence_proof_ref) VALUES($1,$2,$3,$4,$5,clock_timestamp()+interval '1 hour','SYNTHETIC:closed-install')", f.room, b.Tenant, b.Owner, b.Run, p+"output")
	f.exec("INSERT INTO dl05_turns(tenant_id,owner_id,turn_id,run_id,turn_type,source_comment_trace_id,priority,state,scheduled_at,expires_at,input_text,idempotency_key,document) VALUES($1,$2,$3,$4,'COMMENT','merged-source',70,'DISPATCHING',clock_timestamp(),clock_timestamp()+interval '2 minutes','商品价格尺码','key','{}')", b.Tenant, b.Owner, b.Turn, b.Run)
	f.exec("INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES($1,$2,'COMMENT','商品价格尺码',70,'QUEUE','trace')", b.Utterance, b.Session)
	f.exec("INSERT INTO dl05_attempts(tenant_id,owner_id,attempt_id,run_id,turn_id,session_id,run_epoch,utterance_id,command_id,attempt_number,last_checkpoint,required_sinks,document) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,1,'DISPATCHED','[\"sink\"]','{}')", b.Tenant, b.Owner, b.Attempt, b.Run, b.Turn, b.Session, b.Utterance, b.Command)
	now := time.Now().UTC()
	cmd := map[string]any{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": b.Tenant, "ownerId": b.Owner, "runId": b.Run, "sessionId": b.Session, "commandId": b.Command, "intentId": p + "intent", "attemptId": b.Attempt, "turnId": b.Turn, "utteranceId": b.Utterance, "runEpoch": 1, "leaseVersion": 1, "idempotencyKey": "comment:1", "traceId": "trace", "createdAt": cp.Stamp(now), "operation": "EXECUTE_TURN", "payload": map[string]any{"mode": "COMMENT_QUESTION", "text": "商品价格尺码", "textHash": cp.Hash("商品价格尺码"), "productId": b.Product, "planId": f.plan, "segmentId": nil, "factDependencies": []any{}, "expiresAt": cp.Stamp(now.Add(2 * time.Minute)), "requiredSinks": []string{"sink"}, "answerPreparation": "SEMANTIC_STREAM"}}
	hash, err := cp.Version(cmd)
	if err != nil {
		f.t.Fatal(err)
	}
	cmd["requestHash"] = hash
	f.b.RequestHash = hash
	raw, _ := json.Marshal(cmd)
	f.command, err = wire.DecodeRuntimeCommand(raw)
	if err != nil {
		f.t.Fatal(err)
	}
	f.exec("INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status,send_started_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'comment:1',1,'EXECUTE_TURN',$10,$11,'CLAIMED',clock_timestamp())", b.Tenant, b.Owner, p+"intent", b.Run, b.Session, b.Utterance, b.Command, b.Attempt, b.Turn, hash, cmd)
	f.exec("UPDATE dl05_run_slots SET active_attempt_id=$2 WHERE run_id=$1", b.Run, b.Attempt)
	if err := tx.Commit(f.ctx); err != nil {
		f.t.Fatal(err)
	}
	f.seedTx = nil
}
func (f *pgStream) call(p authority.Actor, name string, q map[string]any) (wire.Message, error) {
	op, _ := wire.LookupOperation(wire.OperationID(name))
	raw, err := json.Marshal(q)
	if err != nil {
		return nil, err
	}
	msg, err := wire.Decode(op.RequestSchema, raw)
	if err != nil {
		return nil, err
	}
	return CallAuthority(f.ctx, f.store, p, op.ID, msg)
}
func (f *pgStream) mustCall(p authority.Actor, name string, q map[string]any) wire.Message {
	f.t.Helper()
	v, e := f.call(p, name, q)
	if e != nil {
		f.t.Fatalf("%s: %v", name, e)
	}
	return v
}
func (f *pgStream) base() map[string]any {
	return map[string]any{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "requestId": ids.New("req"), "tenantId": f.b.Tenant, "ownerId": f.b.Owner, "runId": f.b.Run}
}
func (f *pgStream) private() map[string]any {
	return map[string]any{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "requestId": ids.New("req")}
}
func (f *pgStream) installFixture() {
	_, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		f.t.Fatal(err)
	}
	for _, v := range []struct {
		p     authority.Actor
		role  string
		pub   []byte
		keyID string
	}{{f.runtime, "REGISTERED_RUNTIME", nil, ""}, {f.guardian, "OUTPUT_GUARDIAN", key.Public().(ed25519.PublicKey), f.prefix + "key"}, {f.observer, "OBSERVER", nil, ""}} {
		if err = f.store.ProvisionProcess(f.ctx, f.registrar, v.p.ID, v.role, v.p.Incarnation, f.b.Producer, v.keyID, "SYNTHETIC:process-install", v.pub); err != nil {
			f.t.Fatal(err)
		}
	}
	q := f.base()
	q["command"] = f.command
	q["producerIncarnation"] = f.b.Producer
	f.mustCall(f.runtime, "JournalAccept", q)
	b := f.b
	f.bootstrap = wire.ReceiverBootstrapBinding{ContractRevision: "durable-live-2", ReceiverRevision: "receiver-1", BootstrapID: wire.ID(f.prefix + "bootstrap"), TenantID: wire.ID(b.Tenant), OwnerID: wire.ID(b.Owner), RoomID: wire.ID(f.room), RunID: wire.ID(b.Run), SessionID: wire.ID(b.Session), ProducerIncarnation: wire.ID(b.Producer), AttemptID: wire.ID(b.Attempt), CommandID: wire.ID(b.Command), TurnID: wire.ID(b.Turn), UtteranceID: wire.ID(b.Utterance), GuardianID: wire.ID(f.prefix + "output"), GuardianIncarnation: wire.ID(f.guardian.Incarnation), RuntimePrincipalID: wire.ID(f.runtime.ID), RuntimeIncarnation: wire.ID(f.runtime.Incarnation), PhysicalInstallProofRef: wire.ID(f.prefix + "install"), RunEpoch: 1, GenerationID: 7, OutputBindingVersion: 1}
	raw, _ := wire.Encode(&f.bootstrap)
	var binding authority.Document
	_ = json.Unmarshal(raw, &binding)
	// Normalize numbers through the official decoder's canonical hash format;
	// Store's domain binding expects integers, not float64 from encoding/json.
	binding = integerDocument(raw)
	f.store.InstallationSource = func(_ context.Context, _ authority.Actor, b authority.Document) (authority.Document, error) {
		return authority.Document{"binding": b, "installationRevision": int64(1), "observedByPrincipalId": f.registrar.ID, "guardianPrincipalId": f.guardian.ID, "closedFenceProofRef": "SYNTHETIC:closed-install", "state": "CLOSED_INSTALLED"}, nil
	}
	if err = f.store.RecordInstallation(f.ctx, f.registrar, binding); err != nil {
		f.t.Fatal(err)
	}
	challenge, err := f.store.IssueStageChallenge(f.ctx, f.registrar, binding)
	if err != nil {
		f.t.Fatal(err)
	}
	h, _ := wire.DigestJSON(raw)
	receipt := map[string]any{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "installationRevision": 1, "stageReceiptId": ids.New("stage"), "challenge": challenge["challenge"], "guardianPrincipalId": f.guardian.ID, "guardianIncarnation": f.guardian.Incarnation, "keyId": f.prefix + "key", "bindingHash": h, "authorityIssuedAt": challenge["challengeIssuedAt"], "validUntil": challenge["challengeExpiresAt"], "state": "CLOSED_STAGED"}
	bytes, _ := cp.Canonical(receipt)
	receipt["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(key, bytes))
	q = f.private()
	q["binding"] = f.bootstrap
	q["receipt"] = receipt
	q["expectedRegistrationRevision"] = 0
	q["expectedRunRevision"] = 1
	q["expectedLeaseVersion"] = 1
	f.mustCall(f.registrar, "RegisterReceiverBootstrap", q)
	f.store.Observer = f.receiver.verifyObserver
	f.store.CheckpointProof = func(_ context.Context, _ authority.Actor, cp authority.Document) error {
		if cp["state"] != "PLAYING" {
			return ErrUnknown
		}
		return nil
	} // explicit synthetic physical SINK_ADMITTED verifier
}
func integerDocument(raw []byte) authority.Document {
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	var m map[string]any
	_ = d.Decode(&m)
	var fix func(any) any
	fix = func(v any) any {
		switch x := v.(type) {
		case json.Number:
			n, _ := x.Int64()
			return n
		case map[string]any:
			for k, v := range x {
				x[k] = fix(v)
			}
		case []any:
			for i, v := range x {
				x[i] = fix(v)
			}
		}
		return v
	}
	return fix(m).(map[string]any)
}
func (f *pgStream) coordinator(source domain.Source) *Coordinator {
	f.t.Helper()
	k, e := f.facts.Load(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	b, e := domain.NewBuilder(f.b, time.Now, f.facts, domain.WireEncoding{})
	if e != nil {
		f.t.Fatal(e)
	}
	c := New(f.ctx, domain.NewScanner(source, k.Language), b, f.adapter, f.adapter)
	f.t.Cleanup(c.Stop)
	return c
}
func (f *pgStream) artifacts() []domain.Artifact {
	f.t.Helper()
	k, e := f.facts.Load(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	b, e := domain.NewBuilder(f.b, time.Now, f.facts, domain.WireEncoding{})
	if e != nil {
		f.t.Fatal(e)
	}
	s := domain.NewScanner(&mockSource{tokens: []rune(pgReply)}, k.Language)
	var out []domain.Artifact
	for i := 0; i < 2; i++ {
		u, e := s.Next(f.ctx)
		if e != nil {
			f.t.Fatal(e)
		}
		a, e := b.Build(f.ctx, u)
		if e != nil {
			f.t.Fatal(e)
		}
		out = append(out, a)
	}
	return out
}

const pgReply = "这款的价格是129.90元。这款有XL尺码。"

// Synthetic Receiver/Observer: real CommitReceiverConsume transaction, but NO
// Guardian IPC, fsync, PCM, once-TTS, media or real sink. Counters are fixture ACKs.
type syntheticReceiver struct {
	f           *pgStream
	mu          sync.Mutex
	consumed    map[string]wire.ReceiverConsumption
	drains      map[string]wire.Evidence
	acks        int
	afterLatch  func()
	loseACK     bool
	lastConsume map[string]any
}

func (r *syntheticReceiver) Consume(ctx context.Context, a domain.Artifact, g wire.AnswerGrant, ticket wire.ReceiverConsumeTicket, timing wire.ReceiverTiming, pm wire.AcquireOutputPermitResponse) error {
	f := r.f
	refs := wire.ReceiverReferences{BootstrapID: f.bootstrap.BootstrapID, ArtifactID: wire.ID(a.Draft().ID), ArtifactHash: wire.Hash(a.Hash()), GrantID: g.GrantID, PermitID: pm.PermitID}
	q := f.private()
	q["references"] = refs
	if _, err := f.call(f.guardian, "QueryReceiverAuthority", q); err != nil {
		return err
	}
	q = f.private()
	q["references"] = refs
	q["consumeTicket"] = ticket
	q["consumeRequestId"] = ids.New("consume")
	q["runtimeIncarnation"] = f.runtime.Incarnation
	q["runtimePrincipalId"] = f.runtime.ID
	q["channelBinding"] = cp.Hash("owned-test-channel")
	q["expectedRegistrationRevision"] = 1
	response, e := f.call(f.guardian, "CommitReceiverConsume", q)
	if e != nil {
		return e
	}
	v := response.(*wire.CommitReceiverConsumeResponse)
	if !v.ConsumeAuthorized || v.Consumption == nil {
		return ErrUnknown
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastConsume = q
	r.consumed[a.Hash()] = *v.Consumption
	if r.afterLatch != nil {
		r.afterLatch()
	}
	if r.loseACK {
		return context.DeadlineExceeded
	}
	r.acks++
	return nil
}
func (r *syntheticReceiver) evidence(first, last int64, terminal bool, kind string) wire.Evidence {
	return wire.Evidence{EvidenceType: wire.EvidenceEvidenceType(kind), EvidenceRef: wire.ID(ids.New("SYNTHETIC_evidence")), EvidenceHash: wire.Hash(cp.Hash("SYNTHETIC registered test ranges")), RequiredSinks: []wire.ID{"sink"}, SinkProofs: []wire.SinkProof{{SinkID: "sink", Kind: wire.SinkProofKind("RTMP_PIPE_WRITE"), GenerationID: 7, FirstAudioSample: first, FinalAudioSampleExclusive: last, AudioConsumedThroughExclusive: last, FinalVideoFrame: last, VideoConsumedThroughFrame: last, Terminal: terminal}}, PredecessorCheckpointIDs: []wire.ID{}, AudienceVisibility: "UNVERIFIED"}
}
func (r *syntheticReceiver) Playing(ctx context.Context, a domain.Artifact) (wire.Evidence, error) {
	return r.evidence(0, 100, false, "SINK_ADMITTED"), nil
}
func (r *syntheticReceiver) Drain(ctx context.Context, a domain.Artifact) (wire.Evidence, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if ev, ok := r.drains[a.Hash()]; ok {
		return ev, nil
	}
	if _, ok := r.consumed[a.Hash()]; !ok {
		return wire.Evidence{}, ErrUnknown
	}
	seq := int64(a.Draft().Sequence)
	ev := r.evidence((seq-1)*100, seq*100, true, "ALL_REQUIRED_DRAIN")
	raw, e := wire.Encode(&ev)
	if e != nil {
		return ev, e
	}
	if e = r.f.store.RecordDrainEvidence(ctx, r.f.observer, r.f.b.Command, a.Draft().ID, integerDocument(raw)); e != nil {
		return ev, e
	}
	r.drains[a.Hash()] = ev
	return ev, nil
}
func (r *syntheticReceiver) verifyObserver(_ context.Context, p authority.Actor, a, e authority.Document) error {
	if p.ID != r.f.observer.ID || a["commandId"] != r.f.b.Command || e["evidenceType"] != "ALL_REQUIRED_DRAIN" {
		return ErrUnknown
	}
	return nil
}
func (r *syntheticReceiver) Aggregate(ctx context.Context, s domain.Summary) (wire.Evidence, error) {
	return r.evidence(0, int64(len(s.Entries))*100, true, "ALL_REQUIRED_DRAIN"), nil
}
func (f *pgStream) count(table string) int {
	f.t.Helper()
	var n int
	if e := f.pool.QueryRow(f.ctx, "SELECT count(*) FROM "+table+" WHERE command_id=$1", f.b.Command).Scan(&n); e != nil {
		f.t.Fatal(e)
	}
	return n
}
func (f *pgStream) assertSlot(busy bool) {
	f.t.Helper()
	var actual bool
	if e := f.pool.QueryRow(f.ctx, "SELECT active_attempt_id IS NOT NULL FROM dl05_run_slots WHERE run_id=$1", f.b.Run).Scan(&actual); e != nil || actual != busy {
		f.t.Fatalf("slot busy=%v want=%v err=%v", actual, busy, e)
	}
	var state string
	if e := f.pool.QueryRow(f.ctx, "SELECT state FROM dl05_segments WHERE segment_id=$1", f.prefix+"script").Scan(&state); e != nil || state != "READY" {
		f.t.Fatal("COMMENT moved script cursor", state, e)
	}
}
func (f *pgStream) stop() {
	q := f.base()
	q["reasonCode"] = "OWNED_TEST_STOP"
	q["decisionId"] = f.prefix + "stop"
	q["expectedRevision"] = 1
	q["idempotencyKey"] = "stop"
	f.mustCall(f.control, "StopBroadcastRun", q)
}
