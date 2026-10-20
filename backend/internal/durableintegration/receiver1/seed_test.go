package receiver1

import (
	"astralive/backend/internal/durablelivev2/authority"
	"time"
)

func (f *interop) seed() {
	x := f.prefix
	room := f.control.Room
	session := testText(f.template, "sessionId")
	run := testText(f.template, "runId")
	f.exec("INSERT INTO config_principals VALUES($1,$2)", f.control.Tenant, f.control.Owner)
	f.exec("INSERT INTO avatars(id,name,engine) VALUES($1,'fixture','MOCK')", x+"avatar")
	f.exec("INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'fixture','mock','fixture')", x+"voice")
	f.exec("INSERT INTO products(id,name,description,price,currency,stock) VALUES($1,'测试商品','纯棉',129.90,'CNY',7)", f.product)
	f.exec("INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES($1,'fixture',$2,$3,'fixture',$4)", room, x+"avatar", x+"voice", f.product)
	f.exec("INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')", session, room)
	for _, v := range [][2]string{{"room", room}, {"session", session}, {"product", f.product}} {
		f.exec("INSERT INTO resource_owners VALUES($1,$2,$3,$4)", v[0], v[1], f.control.Tenant, f.control.Owner)
	}
	f.exec("INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,$5,'{}',clock_timestamp()+interval '1 hour')", session, f.control.Tenant, f.control.Owner, x+"binding", authority.Document{"activeProductId": f.product})
	f.exec("INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy,run_epoch,contract_revision) VALUES($1,$2,$3,$4,'LIVE','LIVE','MANUAL_ON_UNKNOWN',1,'durable-live-2')", f.control.Tenant, f.control.Owner, run, room)
	f.exec("INSERT INTO dl05_run_terms(tenant_id,owner_id,run_id,run_epoch,lease_owner,phase,previous_epoch,required_sinks,producer_incarnation,guardian_id) VALUES($1,$2,$3,1,$4,'ACTIVE',0,'[\"sink\"]',$5,$6)", f.control.Tenant, f.control.Owner, run, f.control.ID, f.runtime.Producer, x+"guardian")
	f.exec("INSERT INTO dl05_run_leases(tenant_id,owner_id,run_id,lease_owner,lease_expires_at,fencing_token,run_epoch,lease_version,phase) VALUES($1,$2,$3,$4,clock_timestamp()+interval '1 hour',1,1,1,'ACTIVE')", f.control.Tenant, f.control.Owner, run, f.control.ID)
	f.exec("INSERT INTO dl05_run_sessions(tenant_id,owner_id,run_session_id,run_id,session_id,binding_id,introduced_epoch) VALUES($1,$2,$3,$4,$5,$6,1)", f.control.Tenant, f.control.Owner, x+"run-session", run, session, x+"binding")
	f.exec("UPDATE dl05_runs SET current_session_id=$2 WHERE run_id=$1", run, session)
	f.exec("INSERT INTO dl05_run_slots(tenant_id,owner_id,run_id) VALUES($1,$2,$3)", f.control.Tenant, f.control.Owner, run)
	f.exec("INSERT INTO dl05_room_outputs(room_id,tenant_id,owner_id,active_run_id,guardian_id,expires_at,fence_proof_ref) VALUES($1,$2,$3,$4,$5,clock_timestamp()+interval '1 hour','fixture-closed-fence')", room, f.control.Tenant, f.control.Owner, run, x+"guardian")
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	execute := func(q string, args ...any) {
		if _, e := tx.Exec(f.ctx, q, args...); e != nil {
			f.t.Fatal(e)
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
	f.cmd = authority.Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": run, "sessionId": session, "commandId": command, "intentId": intent, "attemptId": attempt, "turnId": turn, "utteranceId": utterance, "runEpoch": int64(1), "leaseVersion": int64(1), "idempotencyKey": "comment:1", "traceId": "trace", "createdAt": testStamp(now), "operation": "EXECUTE_TURN", "payload": authority.Document{"mode": "COMMENT_QUESTION", "text": "介绍一下", "textHash": testDigest([]byte("介绍一下")), "productId": f.product, "planId": f.plan, "segmentId": nil, "factDependencies": []any{}, "expiresAt": testStamp(now.Add(30 * time.Second)), "requiredSinks": []any{"sink"}, "answerPreparation": "SEMANTIC_STREAM"}}
	f.cmd["requestHash"] = testHash(f.cmd)
	execute("INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status,send_started_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'comment:1',1,'EXECUTE_TURN',$10,$11,'CLAIMED',clock_timestamp())", f.control.Tenant, f.control.Owner, intent, run, session, utterance, command, attempt, turn, f.cmd["requestHash"], f.cmd)
	execute("UPDATE dl05_run_slots SET active_attempt_id=$2 WHERE run_id=$1", run, attempt)
	if e = tx.Commit(f.ctx); e != nil {
		f.t.Fatal(e)
	}
}
func (f *interop) productSetup() {
	x := f.prefix
	projection, e := f.s.ProductProjection(f.ctx, f.control, testText(f.cmd, "commandId"))
	if e != nil {
		f.t.Fatal(e)
	}
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	_, e = tx.Exec(f.ctx, "INSERT INTO dl05_plans(tenant_id,owner_id,plan_id,run_id,product_id,product_snapshot_version,snapshot,revision,generation_source,segment_order,document) VALUES($1,$2,$3,$4,$5,$6,$7,1,'{}',$8,'{}')", f.control.Tenant, f.control.Owner, f.plan, testText(f.cmd, "runId"), f.product, projection["snapshotVersion"], projection["snapshot"], []any{x + "script"})
	if e != nil {
		f.t.Fatal(e)
	}
	_, e = tx.Exec(f.ctx, "INSERT INTO dl05_segments(tenant_id,owner_id,segment_id,run_id,plan_id,sequence,content,text_hash,state,idempotency_key,checkpoint_state,fact_dependencies,estimated_duration_ms,document) VALUES($1,$2,$3,$4,$5,1,'脚本',$6,'READY','script','PLANNED','[]',3000,'{}')", f.control.Tenant, f.control.Owner, x+"script", testText(f.cmd, "runId"), f.plan, testDigest([]byte("脚本")))
	if e != nil {
		f.t.Fatal(e)
	}
	if e = tx.Commit(f.ctx); e != nil {
		f.t.Fatal(e)
	}
	f.unit = authority.Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": f.cmd["runId"], "commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "answerId": x + "answer", "artifactId": x + "unit1", "sequence": int64(1), "previousArtifactHash": nil, "answerText": "这款采用纯棉面料。", "answerTextHash": testDigest([]byte("这款采用纯棉面料。")), "productId": f.product, "productSnapshotVersion": projection["snapshotVersion"], "factDependencies": []any{authority.Document{"kind": "PRODUCT_DETAILS", "productId": f.product, "sourceVersion": projection["sourceVersion"], "validatedAt": testStamp(time.Now()), "expiresAt": testStamp(time.Now().Add(2 * time.Second)), "valueHash": testObj(projection, "valueHashes")["PRODUCT_DETAILS"]}}, "assertionKinds": []any{"PRODUCT_DETAILS"}, "semanticBoundary": "COMPLETE_SENTENCE", "estimatedDurationMs": int64(3000), "createdAt": testStamp(time.Now())}
	f.unit["artifactHash"] = testHash(f.unit)
	f.prepareQ = f.q(authority.Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "artifact": f.unit, "expectedInboxRevision": int64(1), "expectedAnswerRevision": int64(0), "idempotencyKey": "prepare:1"})
}
