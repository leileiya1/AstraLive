package authority

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

func (f *fixture) denied(p Actor, n string, q Document) {
	f.t.Helper()
	v, e := f.s.Call(f.ctx, p, n, q)
	if e == nil {
		f.t.Fatalf("%s unexpectedly authorized: %v", n, v)
	}
}
func (f *fixture) count(table string) int {
	f.t.Helper()
	var n int
	if e := f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM "+table+" WHERE command_id=$1", f.cmd["commandId"]).Scan(&n); e != nil {
		f.t.Fatal(e)
	}
	return n
}
func (f *fixture) stop() {
	f.call(f.control, "StopBroadcastRun", f.q(Document{"reasonCode": "test-stop", "decisionId": f.prefix + "stop-decision", "expectedRevision": int64(1), "idempotencyKey": "stop"}))
}
func (f *fixture) unknownQ() Document {
	return f.q(Document{"expectedRevision": int64(1), "runEpoch": int64(1), "attemptId": f.cmd["attemptId"], "lastKnownState": "DISPATCHED", "reasonCode": "ACK_LOST", "evidenceRef": "test:ack-lost", "idempotencyKey": "unknown:1"})
}
func (f *fixture) permitFor(a Document) Document {
	return f.call(f.runtime, "AcquireOutputPermit", f.q(Document{"sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "guardianId": f.binding["guardianId"], "answerArtifactId": a["artifactId"]}))
}
func (f *fixture) nextUnit() (Document, Document) {
	a := clone(f.unit)
	a["artifactId"] = f.prefix + "unit2"
	a["sequence"] = int64(2)
	a["previousArtifactHash"] = f.unit["artifactHash"]
	a["answerText"] = "欢迎继续了解。"
	a["answerTextHash"] = digest([]byte(text(a, "answerText")))
	a["artifactHash"] = hash(without(a, "artifactHash"))
	q := clone(f.prepareQ)
	q["artifact"] = a
	q["idempotencyKey"] = "prepare:2"
	q["expectedInboxRevision"] = int64(3)
	q["expectedAnswerRevision"] = int64(3)
	return a, q
}
func (f *fixture) drainUnit(a Document, rev int64, first, last int64) Document {
	ev := Document{"evidenceType": "ALL_REQUIRED_DRAIN", "evidenceRef": id("observed"), "evidenceHash": hash(a), "requiredSinks": []any{"sink"}, "sinkProofs": []any{Document{"sinkId": "sink", "kind": "RTMP_PIPE_WRITE", "generationId": int64(7), "firstAudioSample": first, "finalAudioSampleExclusive": last, "audioConsumedThroughExclusive": last, "finalVideoFrame": last, "videoConsumedThroughFrame": last, "terminal": true}}, "predecessorCheckpointIds": []any{}, "audienceVisibility": "UNVERIFIED"}
	if e := f.s.RecordDrainEvidence(f.ctx, f.observer, text(f.cmd, "commandId"), text(a, "artifactId"), ev); e != nil {
		f.t.Fatal(e)
	}
	q := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "expectedAnswerRevision": rev, "idempotencyKey": "drain:" + text(a, "artifactId"), "evidence": ev})
	if e := f.s.RecordDrainEvidence(f.ctx, f.observer, text(f.cmd, "commandId"), text(a, "artifactId"), ev); e != nil {
		f.t.Fatal("duplicate evidence", e)
	}
	f.call(f.runtime, "JournalConfirmAnswerSegment", q)
	return q
}
func TestConcurrentConsumeOneLatch(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	const n = 16
	start := make(chan struct{})
	results := make(chan Document, n)
	errs := make(chan error, n)
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			v, e := f.s.Call(f.ctx, f.guardian, "CommitReceiverConsume", clone(f.consumeQ))
			results <- v
			errs <- e
		}()
	}
	close(start)
	wg.Wait()
	close(results)
	close(errs)
	for e := range errs {
		if e != nil {
			t.Fatal(e)
		}
	}
	yes := 0
	for v := range results {
		if v["consumeAuthorized"] == true {
			yes++
		} else if v["consumption"] != nil {
			t.Fatal(v)
		}
	}
	if yes != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatalf("true=%d", yes)
	}
	q := clone(f.consumeQ)
	q["consumeRequestId"] = id("other-nonce")
	f.denied(f.guardian, "CommitReceiverConsume", q)
	q = clone(f.consumeQ)
	q["channelBinding"] = hash("other-channel")
	f.denied(f.guardian, "CommitReceiverConsume", q)
}
func TestRollbackAtResponseValidation(t *testing.T) {
	for _, op := range []string{"JournalPrepareAnswer", "JournalStart", "CommitReceiverConsume"} {
		t.Run(op, func(t *testing.T) {
			f := newFixture(t, true)
			q := f.prepareQ
			p := f.runtime
			if op != "JournalPrepareAnswer" {
				f.ready()
				q = f.consumeQ
				p = f.guardian
				if op == "JournalStart" { // A fresh fixture must not already have START committed.
					f = newFixture(t, true)
					f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
					pm := f.permitFor(f.unit)
					q = f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": pm["permitId"], "expectedInboxRevision": int64(2), "answerArtifactId": f.unit["artifactId"], "answerArtifactHash": f.unit["artifactHash"], "expectedAnswerRevision": int64(1)})
					p = f.runtime
				}
			}
			f.s.Validate = func(n string, v Document) error {
				if n == op+"Response" {
					return errors.New("injected precommit failure")
				}
				return OfficialValidate(n, v)
			}
			f.denied(p, op, q)
			f.s.Validate = OfficialValidate
			table := "dl05_answer_segments"
			if op == "JournalStart" {
				table = "dl05_answer_grants"
			}
			if op == "CommitReceiverConsume" {
				table = "dl05_receiver_consumptions"
			}
			if f.count(table) != 0 {
				t.Fatal("partial commit", table)
			}
			v := f.call(p, op, q)
			if op == "JournalStart" && v["startAuthorized"] != true {
				t.Fatal(v)
			}
			if op == "CommitReceiverConsume" && v["consumeAuthorized"] != true {
				t.Fatal(v)
			}
		})
	}
}
func TestStopCommitBothOrdersAndCompetition(t *testing.T) {
	for _, mode := range []string{"stop-first", "commit-first", "race"} {
		t.Run(mode, func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			if mode == "stop-first" {
				f.stop()
				f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
			} else if mode == "commit-first" {
				f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
				f.stop()
			} else {
				var wg sync.WaitGroup
				wg.Add(2)
				go func() {
					defer wg.Done()
					_, _ = f.s.Call(f.ctx, f.guardian, "CommitReceiverConsume", clone(f.consumeQ))
				}()
				go func() {
					defer wg.Done()
					_, e := f.s.Call(f.ctx, f.control, "StopBroadcastRun", f.q(Document{"reasonCode": "test", "decisionId": f.prefix + "stop-decision", "expectedRevision": int64(1), "idempotencyKey": "stop"}))
					if e != nil {
						t.Error(e)
					}
				}()
				wg.Wait()
			}
			f.stop()
			f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
			f.denied(f.runtime, "JournalStart", f.startQ)
			f.denied(f.runtime, "JournalPrepareAnswer", f.prepareQ)
			var state string
			if e := f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_registration_state WHERE bootstrap_id=$1", f.binding["bootstrapId"]).Scan(&state); e != nil || state != "REVOKED" {
				t.Fatal(state, e)
			}
			if mode == "commit-first" && f.count("dl05_receiver_consumptions") != 1 {
				t.Fatal("lost latch")
			}
		})
	}
}
func TestUnknownDurableAuditAndNotification(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	q := f.unknownQ()
	a := f.call(f.control, "MarkExecutionUnknown", q)
	b := f.call(f.control, "MarkExecutionUnknown", q)
	if a["checkpointId"] != b["checkpointId"] || a["runRevision"] != b["runRevision"] {
		t.Fatal(a, b)
	}
	var n int
	f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM dl05_notifications WHERE checkpoint_id=$1", a["checkpointId"]).Scan(&n)
	if n != 1 || f.count("dl05_checkpoints") != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("audit/latch lost")
	}
	var slot string
	f.s.DB.QueryRow(f.ctx, "SELECT active_attempt_id FROM dl05_run_slots WHERE run_id=$1", f.cmd["runId"]).Scan(&slot)
	if slot != f.cmd["attemptId"] {
		t.Fatal("UNKNOWN lost reservation")
	}
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.denied(f.runtime, "JournalStart", f.startQ)
}
func TestPrepareAliasAndDrainScopeUnit2(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	alias := clone(f.prepareQ)
	alias["idempotencyKey"] = "alias"
	r := f.call(f.runtime, "JournalPrepareAnswer", alias)
	if r["answerRevision"] != int64(1) {
		t.Fatal(r)
	}
	drain := f.drainUnit(f.unit, 2, 0, 100)
	f.call(f.runtime, "JournalConfirmAnswerSegment", drain)
	a, q := f.nextUnit()
	f.call(f.runtime, "JournalPrepareAnswer", q)
	for _, key := range []string{"prepare:1", "alias"} {
		x := clone(q)
		x["idempotencyKey"] = key
		f.denied(f.runtime, "JournalPrepareAnswer", x)
	}
	x := clone(drain)
	x["artifactId"] = a["artifactId"]
	x["artifactHash"] = a["artifactHash"]
	f.denied(f.runtime, "JournalConfirmAnswerSegment", x)
	pm := f.permitFor(a)
	start := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": pm["permitId"], "answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "expectedAnswerRevision": int64(4)})
	out := f.call(f.runtime, "JournalStartAnswerSegment", start)
	if out["segmentStartAuthorized"] != true {
		t.Fatal(out)
	}
	q2 := clone(f.consumeQ)
	refs := obj(q2, "references")
	refs["artifactId"] = a["artifactId"]
	refs["artifactHash"] = a["artifactHash"]
	refs["grantId"] = obj(out, "grant")["grantId"]
	refs["permitId"] = pm["permitId"]
	q2["consumeTicket"] = out["consumeTicket"]
	q2["consumeRequestId"] = id("nonce2")
	f.call(f.guardian, "CommitReceiverConsume", q2)
	f.drainUnit(a, 5, 100, 200)
	if f.count("dl05_receiver_consumptions") != 2 {
		t.Fatal("unit2 missing")
	}
	manifest := []any{Document{"artifactId": f.unit["artifactId"], "sequence": int64(1), "artifactHash": f.unit["artifactHash"]}, Document{"artifactId": a["artifactId"], "sequence": int64(2), "artifactHash": a["artifactHash"]}}
	seal := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "answerId": a["answerId"], "sequenceCount": int64(2), "finalAnswerTextHash": digest([]byte(text(f.unit, "answerText") + text(a, "answerText"))), "manifestHash": hash(manifest), "expectedAnswerRevision": int64(6), "idempotencyKey": "seal"})
	f.call(f.runtime, "JournalSealAnswer", seal)
	f.call(f.runtime, "JournalSealAnswer", seal)
}
func TestScopeRolesAndCurrentIdentity(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	for _, bad := range []string{"tenant", "owner", "room", "incarnation", "producer", "role"} {
		t.Run(bad, func(t *testing.T) {
			p := f.runtime
			switch bad {
			case "tenant":
				p.Tenant = "other"
			case "owner":
				p.Owner = "other"
			case "room":
				p.Room = "other"
			case "incarnation":
				p.Incarnation = "old"
			case "producer":
				p.Producer = "old"
			case "role":
				p.Role = "OUTPUT_GUARDIAN"
			}
			f.denied(p, "JournalStart", f.startQ)
		})
	}
	f.denied(f.runtime, "QueryReceiverAuthority", f.private(Document{"references": obj(f.consumeQ, "references")}))
	f.denied(f.guardian, "StopBroadcastRun", f.q(Document{"reason": "bad", "idempotencyKey": "bad"}))
	q := clone(f.consumeQ)
	q["runtimeIncarnation"] = "old"
	f.denied(f.guardian, "CommitReceiverConsume", q)
	f.exec("UPDATE dl05_v2_processes SET revoked_at=clock_timestamp() WHERE principal_id=$1", f.runtime.ID)
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
}
func TestChangedFactsBindingEpochAndExpiry(t *testing.T) {
	for _, kind := range []string{"fact", "binding", "lease", "epoch", "generation", "permit", "sealed", "run-failed", "run-paused"} {
		t.Run(kind, func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			switch kind {
			case "fact":
				f.exec("UPDATE products SET description='changed',updated_at=clock_timestamp() WHERE id=$1", f.product)
			case "binding":
				f.exec("UPDATE session_provider_bindings SET released_at=clock_timestamp() WHERE session_id=$1", f.cmd["sessionId"])
			case "lease":
				f.exec("UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1", f.cmd["runId"])
			case "epoch":
				f.exec("UPDATE dl05_runs SET run_epoch=2 WHERE run_id=$1", f.cmd["runId"])
			case "generation":
				f.exec("UPDATE dl05_room_outputs SET output_binding_version=output_binding_version+1 WHERE room_id=$1", f.control.Room)
			case "permit":
				time.Sleep(850 * time.Millisecond)
			case "run-failed":
				f.exec("UPDATE dl05_runs SET status='FAILED' WHERE run_id=$1", f.cmd["runId"])
			case "run-paused":
				f.exec("UPDATE dl05_runs SET desired_state='PAUSED',status='PAUSED' WHERE run_id=$1", f.cmd["runId"])
			case "sealed":
				f.exec("UPDATE dl05_runtime_inbox SET executor_sealed_at=clock_timestamp() WHERE command_id=$1", f.cmd["commandId"])
			}
			f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
			if f.count("dl05_receiver_consumptions") != 0 {
				t.Fatal("unauthorized latch")
			}
		})
	}
}
func TestRenewAfterGrantExpiryDoesNotReauthorize(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	time.Sleep(850 * time.Millisecond)
	pm := f.permitFor(f.unit)
	q := f.private(Document{"references": clone(obj(f.consumeQ, "references"))})
	obj(q, "references")["permitId"] = pm["permitId"]
	out := f.call(f.guardian, "QueryReceiverAuthority", q)
	if obj(obj(out, "snapshot"), "consumption")["state"] != "CONSUMED" || strings.Contains(string(canon(out)), text(f.consumeQ, "consumeTicket")) {
		t.Fatal(out)
	}
	again := f.call(f.runtime, "JournalStart", f.startQ)
	if again["startAuthorized"] != false || again["consumeTicket"] != nil {
		t.Fatal(again)
	}
	q2 := clone(f.consumeQ)
	obj(q2, "references")["permitId"] = pm["permitId"]
	f.denied(f.guardian, "CommitReceiverConsume", q2)
	if f.count("dl05_answer_grants") != 1 {
		t.Fatal("regrant")
	}
}
func TestExternalPreflightDoesNotBlockStop(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	entered := make(chan struct{})
	release := make(chan struct{})
	f.s.Assertions = func(context.Context, Actor, Document) error { close(entered); <-release; return nil }
	done := make(chan error, 1)
	go func() { _, e := f.s.Call(f.ctx, f.guardian, "CommitReceiverConsume", clone(f.consumeQ)); done <- e }()
	<-entered
	begin := time.Now()
	f.stop()
	if time.Since(begin) > 500*time.Millisecond {
		t.Fatal("Stop waited for external callback")
	}
	close(release)
	if e := <-done; e == nil {
		t.Fatal("Stop bypass")
	}
}
func TestSQLTombstonesCannotBeRewritten(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	for _, sql := range []string{"DELETE FROM dl05_receiver_consumptions WHERE command_id=$1", "UPDATE dl05_receiver_consumptions SET consume_identity='changed' WHERE command_id=$1", "DELETE FROM dl05_answer_grants WHERE command_id=$1", "UPDATE dl05_answer_segments SET answer_text='changed' WHERE command_id=$1", "UPDATE dl05_v2_execution_state SET command_id='other' WHERE command_id=$1"} {
		if _, e := f.s.DB.Exec(f.ctx, sql, f.cmd["commandId"]); e == nil {
			t.Fatal("mutable evidence", sql)
		}
	}
	if _, e := f.s.DB.Exec(f.ctx, "UPDATE dl05_v2_grant_state SET state='ISSUED' WHERE grant_id=$1", f.grant["grantId"]); e == nil {
		t.Fatal("reset latch")
	}
	f.stop()
	if _, e := f.s.DB.Exec(f.ctx, "UPDATE dl05_v2_registration_state SET state='ACTIVE',revoked_at=NULL WHERE bootstrap_id=$1", f.binding["bootstrapId"]); e == nil {
		t.Fatal("revived registration")
	}
}
func TestExpiredRecoveryIsIdempotent(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.exec("UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1", f.cmd["runId"])
	n, e := f.s.ReconcileExpired(f.ctx, f.control, 10)
	if e != nil || n != 1 {
		t.Fatal(n, e)
	}
	n, e = f.s.ReconcileExpired(f.ctx, f.control, 10)
	if e != nil || n != 0 || f.count("dl05_checkpoints") != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal(n, e)
	}
}

// Only this owned child is killed, after its SQL transaction has committed.
func TestOwnedCommitCrashChild(t *testing.T) {
	if os.Getenv("AGENT2_V2_CRASH_CHILD") != "1" {
		t.Skip("owned subprocess helper")
	}
	var payload struct {
		Actor   Actor
		Request Document
	}
	if e := json.Unmarshal([]byte(os.Getenv("AGENT2_V2_CRASH_PAYLOAD")), &payload); e != nil {
		t.Fatal(e)
	}
	b, _ := json.Marshal(payload.Request)
	q, e := legacyDecode(b)
	if e != nil {
		t.Fatal(e)
	}
	p, e := pgxpool.New(context.Background(), os.Getenv("DURABLE_V2_TEST_DATABASE_URL"))
	if e != nil {
		t.Fatal(e)
	}
	s := Store{DB: p, Validate: OfficialValidate, Assertions: func(context.Context, Actor, Document) error { return nil }}
	v, e := s.Call(context.Background(), payload.Actor, "CommitReceiverConsume", q)
	if e != nil || v["consumeAuthorized"] != true {
		t.Fatal(v, e)
	}
	fmt.Println("OWNED_COMMIT_DURABLE")
	select {}
}
func TestCommitThenSIGKILLFreshBackendDoesNotReplay(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	payload, _ := json.Marshal(struct {
		Actor   Actor
		Request Document
	}{f.guardian, f.consumeQ})
	cmd := exec.Command(os.Args[0], "-test.run=^TestOwnedCommitCrashChild$", "-test.timeout=10s")
	cmd.Env = append(os.Environ(), "AGENT2_V2_CRASH_CHILD=1", "AGENT2_V2_CRASH_PAYLOAD="+string(payload))
	stdout, e := cmd.StdoutPipe()
	if e != nil {
		t.Fatal(e)
	}
	if e = cmd.Start(); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	scanner := bufio.NewScanner(stdout)
	committed := false
	for scanner.Scan() {
		if scanner.Text() == "OWNED_COMMIT_DURABLE" {
			committed = true
			break
		}
	}
	if !committed {
		t.Fatal("child did not commit")
	}
	if e = cmd.Process.Kill(); e != nil {
		t.Fatal(e)
	}
	_ = cmd.Wait()
	fresh := testDB(t)
	copy := *f.s
	copy.DB = fresh
	v, e := copy.Call(f.ctx, f.guardian, "CommitReceiverConsume", f.consumeQ)
	if e != nil || v["consumeAuthorized"] != false || v["consumption"] != nil || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal(v, e)
	}
	t.Log("owned child SIGKILL after commit; new backend returned consumeAuthorized=false; immutable latch=1")
}

func TestSealedAllDrainControlCompletionAndNoEarlyRelease(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.s.CheckpointProof = func(context.Context, Actor, Document) error { return nil } // Explicit synthetic physical verifier.
	cp := Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": f.cmd["runId"], "checkpointId": id("playing"), "eventId": id("event"), "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "utteranceId": f.cmd["utteranceId"], "commandId": f.cmd["commandId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "producerSeq": int64(1), "state": "PLAYING", "lastKnownState": nil, "reasonCode": nil, "occurredAt": stamp(time.Now()), "evidence": Document{"evidenceType": "SINK_ADMITTED", "evidenceRef": "fixture:playing", "evidenceHash": hash("playing"), "requiredSinks": []any{"sink"}, "sinkProofs": []any{Document{"sinkId": "sink", "kind": "RTMP_PIPE_WRITE", "generationId": int64(7), "firstAudioSample": int64(0), "finalAudioSampleExclusive": int64(100), "audioConsumedThroughExclusive": int64(1), "finalVideoFrame": int64(100), "videoConsumedThroughFrame": int64(0), "terminal": false}}, "predecessorCheckpointIds": []any{}, "audienceVisibility": "UNVERIFIED"}}
	f.call(f.runtime, "ConfirmCheckpoint", f.q(Document{"checkpoint": cp, "expectedRevision": nil}))
	drain := f.drainUnit(f.unit, 2, 0, 100)
	ev := clone(obj(drain, "evidence"))
	ev["predecessorCheckpointIds"] = []any{cp["checkpointId"]}
	local := clone(cp)
	local["checkpointId"] = id("local")
	local["eventId"] = id("event")
	local["producerSeq"] = int64(2)
	local["state"] = "LOCAL_MEDIA_DRAINED"
	local["evidence"] = ev
	f.denied(f.runtime, "ConfirmCheckpoint", f.q(Document{"checkpoint": local, "expectedRevision": nil})) // no seal yet.
	seal := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "answerId": f.unit["answerId"], "sequenceCount": int64(1), "finalAnswerTextHash": f.unit["answerTextHash"], "manifestHash": hash([]any{Document{"artifactId": f.unit["artifactId"], "sequence": int64(1), "artifactHash": f.unit["artifactHash"]}}), "expectedAnswerRevision": int64(3), "idempotencyKey": "seal"})
	f.call(f.runtime, "JournalSealAnswer", seal)
	f.call(f.runtime, "ConfirmCheckpoint", f.q(Document{"checkpoint": local, "expectedRevision": nil}))
	var slot string
	if e := f.s.DB.QueryRow(f.ctx, "SELECT active_attempt_id FROM dl05_run_slots WHERE run_id=$1", f.cmd["runId"]).Scan(&slot); e != nil || slot != f.cmd["attemptId"] {
		t.Fatal("slot released before CONTROL", e)
	}
	complete := clone(local)
	complete["checkpointId"] = id("complete")
	complete["eventId"] = id("event")
	complete["producerSeq"] = int64(1)
	complete["producerIncarnation"] = f.control.Incarnation
	complete["state"] = "COMPLETED"
	obj(complete, "evidence")["evidenceType"] = "BUSINESS_COMMIT"
	obj(complete, "evidence")["predecessorCheckpointIds"] = []any{local["checkpointId"]}
	q := f.q(Document{"checkpoint": complete, "expectedRevision": int64(3)})
	f.call(f.control, "ConfirmCheckpoint", q)
	again := f.call(f.control, "ConfirmCheckpoint", q)
	if again["disposition"] != "DUPLICATE" {
		t.Fatal(again)
	}
	var busy bool
	if e := f.s.DB.QueryRow(f.ctx, "SELECT active_attempt_id IS NOT NULL FROM dl05_run_slots WHERE run_id=$1", f.cmd["runId"]).Scan(&busy); e != nil || busy {
		t.Fatal("slot still busy", e)
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("latch lost")
	}
	f.denied(f.runtime, "JournalStart", f.startQ)
}
func TestStopRegisterAndUntrustedBootstrap(t *testing.T) {
	f := newFixture(t, false)
	f.s.InstallationSource = nil
	if e := f.s.RecordInstallation(f.ctx, f.registrar, f.binding); e == nil {
		t.Fatal("missing trusted source allowed")
	}
	f.stop()
	if _, e := f.s.IssueStageChallenge(f.ctx, f.registrar, f.binding); e == nil {
		t.Fatal("challenge after Stop")
	}
	if f.count("dl05_receiver_bootstraps") != 0 {
		t.Fatal("registered after Stop")
	}
}
func TestAtomicFactMismatchPrepareAndBadTicket(t *testing.T) {
	f := newFixture(t, true)
	a := clone(f.unit)
	list(a, "factDependencies")[0].(map[string]any)["sourceVersion"] = hash("stale")
	a["artifactHash"] = hash(without(a, "artifactHash"))
	q := clone(f.prepareQ)
	q["artifact"] = a
	f.denied(f.runtime, "JournalPrepareAnswer", q)
	if f.count("dl05_answer_streams") != 0 || f.count("dl05_answer_prepare_keys") != 0 {
		t.Fatal("partial prepare")
	}
	f.ready()
	q = clone(f.consumeQ)
	q["consumeTicket"] = secret()
	f.denied(f.guardian, "CommitReceiverConsume", q)
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("bad ticket consumed")
	}
}

func TestOriginalFactAndGrantExpiryFreshProofOnly(t *testing.T) {
	for _, consumed := range []bool{false, true} {
		t.Run(fmt.Sprint(consumed), func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			if consumed {
				f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
			}
			time.Sleep(2100 * time.Millisecond)
			pm := f.permitFor(f.unit)
			refs := clone(obj(f.consumeQ, "references"))
			refs["permitId"] = pm["permitId"]
			v := f.call(f.guardian, "QueryReceiverAuthority", f.private(Document{"references": refs}))
			if obj(obj(v, "snapshot"), "grant")["expiresAt"] != f.grant["expiresAt"] {
				t.Fatal("extended immutable grant")
			}
			q := clone(f.consumeQ)
			q["references"] = refs
			f.denied(f.guardian, "CommitReceiverConsume", q)
			if f.count("dl05_answer_grants") != 1 {
				t.Fatal("reissued grant")
			}
			if consumed && f.count("dl05_receiver_consumptions") != 1 {
				t.Fatal("lost consumption")
			}
		})
	}
}
func TestNoVerifierNoAuthority(t *testing.T) {
	f := newFixture(t, true)
	f.s.Assertions = nil
	f.denied(f.runtime, "JournalPrepareAnswer", f.prepareQ)
	if f.count("dl05_answer_segments") != 0 {
		t.Fatal("unverified fact committed")
	}
	f.s.Validate = nil
	f.denied(f.control, "StopBroadcastRun", f.q(Document{}))
}
func TestLateValidationCannotReturnExpiredPositive(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.s.Validate = func(n string, v Document) error {
		if n == "CommitReceiverConsumeResponse" {
			time.Sleep(850 * time.Millisecond)
		}
		return OfficialValidate(n, v)
	}
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("expired positive committed")
	}
}

func TestStopFirstRegistrationActualCompetition(t *testing.T) {
	for i := 0; i < 6; i++ {
		f := newFixture(t, false)
		q := f.registrationRequest()
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); _, _ = f.s.Call(f.ctx, f.registrar, "RegisterReceiverBootstrap", q) }()
		go func() {
			defer wg.Done()
			_, e := f.s.Call(f.ctx, f.control, "StopBroadcastRun", f.q(Document{"reasonCode": "test", "decisionId": f.prefix + "stop", "expectedRevision": int64(1), "idempotencyKey": "stop"}))
			if e != nil {
				t.Error(e)
			}
		}()
		wg.Wait()
		f.denied(f.registrar, "RegisterReceiverBootstrap", q)
		f.denied(f.runtime, "JournalPrepareAnswer", f.prepareQ)
		var active int
		if e := f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM dl05_v2_registration_state s JOIN dl05_receiver_bootstraps b USING(bootstrap_id) WHERE b.command_id=$1 AND s.state='ACTIVE'", f.cmd["commandId"]).Scan(&active); e != nil || active != 0 {
			t.Fatal(active, e)
		}
	}
}
func TestConcurrentPrepareCASAndOriginalReceipt(t *testing.T) {
	f := newFixture(t, true)
	const n = 8
	var wg sync.WaitGroup
	errs := make(chan error, n)
	receipts := make(chan string, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			out, e := f.s.Call(f.ctx, f.runtime, "JournalPrepareAnswer", clone(f.prepareQ))
			if e == nil {
				receipts <- text(out, "receiptId")
			}
			errs <- e
		}()
	}
	wg.Wait()
	close(errs)
	close(receipts)
	for e := range errs {
		if e != nil {
			t.Fatal(e)
		}
	}
	saved := ""
	for r := range receipts {
		if saved != "" && saved != r {
			t.Fatal("non-atomic receipt")
		}
		saved = r
	}
	if f.count("dl05_answer_segments") != 1 || f.count("dl05_answer_prepare_keys") != 1 {
		t.Fatal("expanded retry tasks")
	}
}

func TestStopStaleCASPersistsOneStopIntent(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.exec("UPDATE dl05_runs SET state_revision=state_revision+1 WHERE run_id=$1", f.cmd["runId"])
	f.stop()
	f.stop()
	var n int
	var phase string
	if e := f.s.DB.QueryRow(f.ctx, "SELECT count(*) FROM dl05_outbox WHERE run_id=$1 AND operation='STOP_RUN'", f.cmd["runId"]).Scan(&n); e != nil || n != 1 {
		t.Fatal(n, e)
	}
	if e := f.s.DB.QueryRow(f.ctx, "SELECT phase FROM dl05_run_leases WHERE run_id=$1", f.cmd["runId"]).Scan(&phase); e != nil || phase != "SEALED" {
		t.Fatal(phase, e)
	}
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
}
func TestSQLRejectsCrossTenantMirrorAndArtifact(t *testing.T) {
	a := newFixture(t, true)
	b := newFixture(t, true)
	a.call(a.runtime, "JournalPrepareAnswer", a.prepareQ)
	b.call(b.runtime, "JournalPrepareAnswer", b.prepareQ)
	_, e := a.s.DB.Exec(a.ctx, `INSERT INTO dl05_v2_installations(proof_id,command_id,binding,binding_hash,installation_revision,runtime_principal,guardian_principal,observed_by,fence_ref) VALUES($1,$2,'{}',$3,1,$4,$5,'test','test')`, id("cross"), a.cmd["commandId"], hash("bad"), b.runtime.ID, b.guardian.ID)
	if e == nil {
		t.Fatal("cross tenant mirror SQL accepted")
	}
	unit := clone(a.unit)
	unit["artifactId"] = id("cross-artifact")
	unit["artifactHash"] = hash(without(unit, "artifactHash"))
	_, e = a.s.DB.Exec(a.ctx, `INSERT INTO dl05_answer_segments(artifact_id,command_id,answer_id,sequence,descriptor,artifact_hash,answer_text,text_hash,previous_hash,product_id,snapshot_version,facts,prepare_receipt) VALUES($1,$2,$3,2,$4,$5,$6,$7,$8,$9,$10,$11,'{}')`, unit["artifactId"], b.cmd["commandId"], b.unit["answerId"], unit, unit["artifactHash"], unit["answerText"], unit["answerTextHash"], a.unit["artifactHash"], unit["productId"], unit["productSnapshotVersion"], unit["factDependencies"])
	if e == nil {
		t.Fatal("cross tenant Artifact SQL accepted")
	}
}

func TestSQLLatencyEvidence(t *testing.T) {
	prepareToGrant := []time.Duration{}
	consume := []time.Duration{}
	for i := 0; i < 12; i++ {
		f := newFixture(t, true)
		start := time.Now()
		f.ready()
		prepareToGrant = append(prepareToGrant, time.Since(start))
		start = time.Now()
		f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
		consume = append(consume, time.Since(start))
	}
	report := func(xs []time.Duration) Document {
		sort.Slice(xs, func(i, j int) bool { return xs[i] < xs[j] })
		return Document{"samples": int64(len(xs)), "p50Microseconds": xs[len(xs)/2].Microseconds(), "p95Microseconds": xs[len(xs)-1].Microseconds()}
	}
	t.Log("SQL_LATENCY " + string(canon(Document{"prepare_permit_start": report(prepareToGrant), "backend_consume": report(consume)})))
}

func TestLostStartACKExpiresWithoutRegrant(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	time.Sleep(850 * time.Millisecond)
	n, e := f.s.ReconcileExpired(f.ctx, f.control, 10)
	if e != nil || n != 1 {
		t.Fatal(n, e)
	}
	if f.count("dl05_receiver_consumptions") != 0 || f.count("dl05_answer_grants") != 1 || f.count("dl05_checkpoints") != 1 {
		t.Fatal("expired START replayed")
	}
	f.denied(f.runtime, "JournalStart", f.startQ)
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
}

func TestUnknownRequiresIndependentFenceToReleaseSlot(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.call(f.control, "MarkExecutionUnknown", f.unknownQ())
	cp := Document{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "tenantId": f.control.Tenant, "ownerId": f.control.Owner, "runId": f.cmd["runId"], "checkpointId": id("fenced"), "eventId": id("event"), "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "utteranceId": f.cmd["utteranceId"], "commandId": f.cmd["commandId"], "runEpoch": int64(1), "producerIncarnation": f.control.Incarnation, "producerSeq": int64(1), "state": "INTERRUPTED", "lastKnownState": nil, "reasonCode": nil, "occurredAt": stamp(time.Now()), "evidence": Document{"evidenceType": "FENCE_BARRIER", "evidenceRef": "fixture:independent-fence", "evidenceHash": hash("fence"), "requiredSinks": []any{"sink"}, "sinkProofs": []any{}, "predecessorCheckpointIds": []any{}, "audienceVisibility": "UNVERIFIED"}}
	q := f.q(Document{"checkpoint": cp, "expectedRevision": int64(2)})
	f.denied(f.control, "ConfirmCheckpoint", q)
	f.s.CheckpointProof = func(context.Context, Actor, Document) error { return nil }
	f.call(f.control, "ConfirmCheckpoint", q)
	var state string
	if e := f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_execution_state WHERE command_id=$1", f.cmd["commandId"]).Scan(&state); e != nil || state != "FENCED" {
		t.Fatal(state, e)
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("deleted latch")
	}
	f.denied(f.runtime, "JournalStart", f.startQ)
}
