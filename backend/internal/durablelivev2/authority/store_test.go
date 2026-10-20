package authority

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"os"
	"strings"
	"testing"
	"time"

	"astralive/backend/db"
	"github.com/jackc/pgx/v5/pgxpool"
)

func testDB(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DURABLE_V2_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires owned isolated PostgreSQL: DURABLE_V2_TEST_DATABASE_URL")
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	if cfg.ConnConfig.Host != "127.0.0.1" || !strings.HasPrefix(cfg.ConnConfig.Database, "agent2_v2_") {
		t.Fatal("refuse shared database")
	}
	cfg.MaxConns = 24
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

type fixture struct {
	t                                                                   *testing.T
	ctx                                                                 context.Context
	s                                                                   *Store
	control, registrar, runtime, guardian, observer                     Actor
	cmd, binding, registration, unit, prepareQ, startQ, grant, consumeQ Document
	key                                                                 ed25519.PrivateKey
	prefix, product, plan                                               string
}

func (f *fixture) exec(q string, args ...any) {
	f.t.Helper()
	_, e := f.s.DB.Exec(f.ctx, q, args...)
	if e != nil {
		f.t.Fatal(e)
	}
}
func (f *fixture) call(p Actor, name string, q Document) Document {
	f.t.Helper()
	v, e := f.s.Call(f.ctx, p, name, q)
	if e != nil {
		f.t.Fatalf("%s: %v", name, e)
	}
	return v
}
func (f *fixture) q(v Document) Document {
	q := Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "requestId": id("request"), "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": f.cmd["runId"]}
	for k, x := range v {
		q[k] = x
	}
	return q
}
func (f *fixture) private(v Document) Document {
	q := Document{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "requestId": id("request")}
	for k, x := range v {
		q[k] = x
	}
	return q
}
func newFixture(t *testing.T, bootstrap bool) *fixture {
	t.Helper()
	pool := testDB(t)
	f := &fixture{t: t, ctx: context.Background(), prefix: id("fixture")}
	f.s = &Store{DB: pool, Validate: OfficialValidate, Assertions: func(context.Context, Actor, Document) error { return nil }, Observer: func(context.Context, Actor, Document, Document) error { return nil }}
	x := f.prefix
	room := x + "room"
	session := x + "session"
	run := x + "run"
	f.product = x + "product"
	f.plan = x + "plan"
	f.control = Actor{Role: "CONTROL", Tenant: x + "tenant", Owner: x + "owner", Room: room, ID: x + "backend", Incarnation: x + "backend-process"}
	f.registrar = f.control
	f.registrar.Role = "CONTROL_REGISTRAR"
	f.runtime = f.control
	f.runtime.Role = "RUNTIME_JOURNAL"
	f.runtime.ID = x + "runtime"
	f.runtime.Incarnation = x + "runtime-process"
	f.runtime.Producer = x + "producer"
	f.guardian = f.control
	f.guardian.Role = "OUTPUT_GUARDIAN"
	f.guardian.ID = x + "guardian-principal"
	f.guardian.Incarnation = x + "guardian-process"
	f.observer = f.control
	f.observer.Role = "OBSERVER"
	f.observer.ID = x + "observer"
	f.observer.Incarnation = x + "observer-process"
	f.exec("INSERT INTO config_principals VALUES($1,$2)", f.control.Tenant, f.control.Owner)
	f.exec("INSERT INTO avatars(id,name,engine) VALUES($1,'fixture','MOCK')", x+"avatar")
	f.exec("INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'fixture','mock','fixture')", x+"voice")
	f.exec("INSERT INTO products(id,name,description,price,currency,stock) VALUES($1,'测试商品','棉质',129.90,'CNY',7)", f.product)
	f.exec("INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES($1,'fixture',$2,$3,'fixture',$4)", room, x+"avatar", x+"voice", f.product)
	f.exec("INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')", session, room)
	for _, v := range [][2]string{{"room", room}, {"session", session}, {"product", f.product}} {
		f.exec("INSERT INTO resource_owners VALUES($1,$2,$3,$4)", v[0], v[1], f.control.Tenant, f.control.Owner)
	}
	f.exec("INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,$5,'{}',clock_timestamp()+interval '1 hour')", session, f.control.Tenant, f.control.Owner, x+"binding", Document{"activeProductId": f.product})
	f.exec("INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy,run_epoch,contract_revision) VALUES($1,$2,$3,$4,'LIVE','LIVE','MANUAL_ON_UNKNOWN',1,'durable-live-2')", f.control.Tenant, f.control.Owner, run, room)
	f.exec("INSERT INTO dl05_run_terms(tenant_id,owner_id,run_id,run_epoch,lease_owner,phase,previous_epoch,required_sinks,producer_incarnation,guardian_id) VALUES($1,$2,$3,1,$4,'ACTIVE',0,'[\"sink\"]',$5,$6)", f.control.Tenant, f.control.Owner, run, f.control.ID, f.runtime.Producer, x+"guardian")
	f.exec("INSERT INTO dl05_run_leases(tenant_id,owner_id,run_id,lease_owner,lease_expires_at,fencing_token,run_epoch,lease_version,phase) VALUES($1,$2,$3,$4,clock_timestamp()+interval '1 hour',1,1,1,'ACTIVE')", f.control.Tenant, f.control.Owner, run, f.control.ID)
	f.exec("INSERT INTO dl05_run_sessions(tenant_id,owner_id,run_session_id,run_id,session_id,binding_id,introduced_epoch) VALUES($1,$2,$3,$4,$5,$6,1)", f.control.Tenant, f.control.Owner, x+"run-session", run, session, x+"binding")
	f.exec("UPDATE dl05_runs SET current_session_id=$2 WHERE run_id=$1", run, session)
	f.exec("INSERT INTO dl05_run_slots(tenant_id,owner_id,run_id) VALUES($1,$2,$3)", f.control.Tenant, f.control.Owner, run)
	f.exec("INSERT INTO dl05_room_outputs(room_id,tenant_id,owner_id,active_run_id,guardian_id,expires_at,fence_proof_ref) VALUES($1,$2,$3,$4,$5,clock_timestamp()+interval '1 hour','fixture-closed-fence')", room, f.control.Tenant, f.control.Owner, run, x+"guardian")
	tx, e := pool.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	execute := func(q string, args ...any) {
		if _, e := tx.Exec(f.ctx, q, args...); e != nil {
			t.Fatal(e)
		}
	}
	turn := x + "turn"
	attempt := x + "attempt"
	command := x + "command"
	utterance := x + "utterance"
	intent := x + "intent"
	execute("INSERT INTO dl05_turns(tenant_id,owner_id,turn_id,run_id,turn_type,source_comment_trace_id,priority,state,scheduled_at,expires_at,input_text,idempotency_key,document) VALUES($1,$2,$3,$4,'COMMENT','source',70,'DISPATCHING',clock_timestamp(),clock_timestamp()+interval '30 seconds','问题','key','{}')", f.control.Tenant, f.control.Owner, turn, run)
	execute("INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES($1,$2,'COMMENT','问题',70,'QUEUE','trace')", utterance, session)
	execute("INSERT INTO dl05_attempts(tenant_id,owner_id,attempt_id,run_id,turn_id,session_id,run_epoch,utterance_id,command_id,attempt_number,last_checkpoint,required_sinks,document) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,1,'DISPATCHED','[\"sink\"]','{}')", f.control.Tenant, f.control.Owner, attempt, run, turn, session, utterance, command)
	now := time.Now().UTC()
	f.cmd = Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": run, "sessionId": session, "commandId": command, "intentId": intent, "attemptId": attempt, "turnId": turn, "utteranceId": utterance, "runEpoch": int64(1), "leaseVersion": int64(1), "idempotencyKey": "comment:1", "traceId": "trace", "createdAt": stamp(now), "operation": "EXECUTE_TURN", "payload": Document{"mode": "COMMENT_QUESTION", "text": "介绍一下", "textHash": digest([]byte("介绍一下")), "productId": f.product, "planId": f.plan, "segmentId": nil, "factDependencies": []any{}, "expiresAt": stamp(now.Add(30 * time.Second)), "requiredSinks": []any{"sink"}, "answerPreparation": "SEMANTIC_STREAM"}}
	f.cmd["requestHash"] = hash(f.cmd)
	execute("INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status,send_started_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'comment:1',1,'EXECUTE_TURN',$10,$11,'CLAIMED',clock_timestamp())", f.control.Tenant, f.control.Owner, intent, run, session, utterance, command, attempt, turn, f.cmd["requestHash"], f.cmd)
	execute("UPDATE dl05_run_slots SET active_attempt_id=$2 WHERE run_id=$1", run, attempt)
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	_, key, e := ed25519.GenerateKey(rand.Reader)
	if e != nil {
		t.Fatal(e)
	}
	f.key = key
	for _, v := range []struct {
		p     Actor
		role  string
		key   []byte
		keyID string
	}{{f.runtime, "REGISTERED_RUNTIME", nil, ""}, {f.guardian, "OUTPUT_GUARDIAN", key.Public().(ed25519.PublicKey), x + "key"}, {f.observer, "OBSERVER", nil, ""}} {
		if e = f.s.ProvisionProcess(f.ctx, f.registrar, v.p.ID, v.role, v.p.Incarnation, f.runtime.Producer, v.keyID, "fixture-os-install", v.key); e != nil {
			t.Fatal(e)
		}
	}
	f.call(f.runtime, "JournalAccept", f.q(Document{"command": f.cmd, "producerIncarnation": f.runtime.Producer}))
	projection, e := f.s.ProductProjection(f.ctx, f.control, command)
	if e != nil {
		t.Fatal(e)
	}
	tx, e = pool.Begin(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	_, e = tx.Exec(f.ctx, "INSERT INTO dl05_plans(tenant_id,owner_id,plan_id,run_id,product_id,product_snapshot_version,snapshot,revision,generation_source,segment_order,document) VALUES($1,$2,$3,$4,$5,$6,$7,1,'{}',$8,'{}')", f.control.Tenant, f.control.Owner, f.plan, run, f.product, projection["snapshotVersion"], projection["snapshot"], []any{x + "script"})
	if e != nil {
		t.Fatal(e)
	}
	_, e = tx.Exec(f.ctx, "INSERT INTO dl05_segments(tenant_id,owner_id,segment_id,run_id,plan_id,sequence,content,text_hash,state,idempotency_key,checkpoint_state,fact_dependencies,estimated_duration_ms,document) VALUES($1,$2,$3,$4,$5,1,'脚本',$6,'READY','script','PLANNED','[]',3000,'{}')", f.control.Tenant, f.control.Owner, x+"script", run, f.plan, digest([]byte("脚本")))
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(f.ctx); e != nil {
		t.Fatal(e)
	}
	f.unit = Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": run, "commandId": command, "attemptId": attempt, "sessionId": session, "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "answerId": x + "answer", "artifactId": x + "unit1", "sequence": int64(1), "previousArtifactHash": nil, "answerText": "这款商品是棉质。", "answerTextHash": digest([]byte("这款商品是棉质。")), "productId": f.product, "productSnapshotVersion": projection["snapshotVersion"], "factDependencies": []any{Document{"kind": "PRODUCT_DETAILS", "productId": f.product, "sourceVersion": projection["sourceVersion"], "validatedAt": stamp(now), "expiresAt": stamp(now.Add(2 * time.Second)), "valueHash": obj(projection, "valueHashes")["PRODUCT_DETAILS"]}}, "assertionKinds": []any{"PRODUCT_DETAILS"}, "semanticBoundary": "COMPLETE_SENTENCE", "estimatedDurationMs": int64(3000), "createdAt": stamp(now)}
	f.unit["artifactHash"] = hash(f.unit)
	f.prepareQ = f.q(Document{"commandId": command, "attemptId": attempt, "sessionId": session, "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "artifact": f.unit, "expectedInboxRevision": int64(1), "expectedAnswerRevision": int64(0), "idempotencyKey": "prepare:1"})
	f.binding = Document{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "bootstrapId": x + "bootstrap", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "roomId": room, "runId": run, "sessionId": session, "producerIncarnation": f.runtime.Producer, "attemptId": attempt, "commandId": command, "turnId": turn, "utteranceId": utterance, "guardianId": x + "guardian", "guardianIncarnation": f.guardian.Incarnation, "runtimePrincipalId": f.runtime.ID, "runtimeIncarnation": f.runtime.Incarnation, "physicalInstallProofRef": x + "install", "runEpoch": int64(1), "generationId": int64(7), "outputBindingVersion": int64(1)}
	f.s.InstallationSource = func(_ context.Context, _ Actor, b Document) (Document, error) {
		return Document{"binding": b, "installationRevision": int64(1), "observedByPrincipalId": f.registrar.ID, "guardianPrincipalId": f.guardian.ID, "closedFenceProofRef": "fixture-closed-fence", "state": "CLOSED_INSTALLED"}, nil
	}
	if bootstrap {
		f.bootstrap()
	}
	return f
}
func (f *fixture) registrationRequest() Document {
	f.t.Helper()
	if e := f.s.RecordInstallation(f.ctx, f.registrar, f.binding); e != nil {
		f.t.Fatal(e)
	}
	ch, e := f.s.IssueStageChallenge(f.ctx, f.registrar, f.binding)
	if e != nil {
		f.t.Fatal(e)
	}
	receipt := Document{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "installationRevision": int64(1), "stageReceiptId": id("stage"), "challenge": ch["challenge"], "guardianPrincipalId": f.guardian.ID, "guardianIncarnation": f.guardian.Incarnation, "keyId": f.prefix + "key", "bindingHash": hash(f.binding), "authorityIssuedAt": ch["challengeIssuedAt"], "validUntil": ch["challengeExpiresAt"], "state": "CLOSED_STAGED"}
	receipt["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(f.key, canon(receipt)))
	return f.private(Document{"binding": f.binding, "receipt": receipt, "expectedRegistrationRevision": int64(0), "expectedRunRevision": int64(1), "expectedLeaseVersion": int64(1)})
}
func (f *fixture) bootstrap() {
	out := f.call(f.registrar, "RegisterReceiverBootstrap", f.registrationRequest())
	f.registration = obj(out, "registration")
}
func (f *fixture) ready() Document {
	f.t.Helper()
	f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
	p := f.call(f.runtime, "AcquireOutputPermit", f.q(Document{"sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "guardianId": f.binding["guardianId"], "answerArtifactId": f.unit["artifactId"]}))
	f.startQ = f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": p["permitId"], "expectedInboxRevision": int64(2), "answerArtifactId": f.unit["artifactId"], "answerArtifactHash": f.unit["artifactHash"], "expectedAnswerRevision": int64(1)})
	out := f.call(f.runtime, "JournalStart", f.startQ)
	f.grant = obj(out, "answerGrant")
	refs := Document{"bootstrapId": f.binding["bootstrapId"], "artifactId": f.unit["artifactId"], "artifactHash": f.unit["artifactHash"], "grantId": f.grant["grantId"], "permitId": p["permitId"]}
	f.consumeQ = f.private(Document{"references": refs, "consumeTicket": out["consumeTicket"], "consumeRequestId": id("nonce"), "runtimePrincipalId": f.runtime.ID, "runtimeIncarnation": f.runtime.Incarnation, "channelBinding": hash("channel"), "expectedRegistrationRevision": int64(1)})
	return out
}
func TestMigrationAndNormalConsume(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	first := f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	if first["consumeAuthorized"] != true {
		t.Fatal(first)
	}
	again := f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	if again["consumeAuthorized"] != false || again["consumption"] != nil {
		t.Fatal(again)
	}
}
