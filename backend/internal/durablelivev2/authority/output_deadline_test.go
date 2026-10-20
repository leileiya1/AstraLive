package authority

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"
)

// Test source mirrors use the same Run -> output lock order as the trusted
// Registrar. Neither Runtime input nor the Go wall clock sets authority time.
func (f *fixture) outputDeadline(after time.Duration) time.Time {
	f.t.Helper()
	tx, e := f.s.DB.Begin(f.ctx)
	if e != nil {
		f.t.Fatal(e)
	}
	defer tx.Rollback(f.ctx)
	if _, e = tx.Exec(f.ctx, "SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE", f.cmd["runId"]); e != nil {
		f.t.Fatal(e)
	}
	var until time.Time
	if e = tx.QueryRow(f.ctx, "UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+$2::bigint*interval '1 microsecond' WHERE room_id=$1 RETURNING expires_at", f.control.Room, after.Microseconds()).Scan(&until); e != nil {
		f.t.Fatal(e)
	}
	if e = tx.Commit(f.ctx); e != nil {
		f.t.Fatal(e)
	}
	return until
}
func (f *fixture) queryAuthority() Document {
	return f.private(Document{"references": clone(obj(f.consumeQ, "references"))})
}
func (f *fixture) permitRequest(a Document) Document {
	return f.q(Document{"sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "guardianId": f.binding["guardianId"], "answerArtifactId": a["artifactId"]})
}
func (f *fixture) assertBudget(snapshot Document, until time.Time) {
	f.t.Helper()
	at := date(snapshot, "authorityTime")
	valid := date(snapshot, "validUntil")
	budget := number(obj(snapshot, "timing"), "remainingProofMs")
	if valid.After(until) || !valid.After(at) || budget < 0 || budget > valid.Sub(at).Milliseconds() {
		f.t.Fatalf("proof outside authority deadline: remaining=%d, authorityTime=%s, validUntil=%s, output=%s", budget, at, valid, until)
	}
	if e := OfficialValidate("ReceiverAuthoritySnapshot", snapshot); e != nil {
		f.t.Fatal(e)
	}
}
func TestOutputDeadlineEqualDatabaseNow(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	var expires, dbNow time.Time
	if e := f.s.DB.QueryRow(f.ctx, `WITH n AS MATERIALIZED(SELECT clock_timestamp() AS at) UPDATE dl05_room_outputs o SET expires_at=n.at FROM n WHERE o.room_id=$1 RETURNING o.expires_at,n.at`, f.control.Room).Scan(&expires, &dbNow); e != nil {
		t.Fatal(e)
	}
	if !expires.Equal(dbNow) {
		t.Fatal("fixture did not set exact DB equality")
	}
	f.denied(f.runtime, "AcquireOutputPermit", f.permitRequest(f.unit))
	f.denied(f.guardian, "QueryReceiverAuthority", f.queryAuthority())
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
	if f.count("dl05_receiver_consumptions") != 0 {
		t.Fatal("expired equality created latch")
	}
}
func TestOutputDeadlineExpiresDuringPublication(t *testing.T) {
	for _, op := range []string{"AcquireOutputPermit", "QueryReceiverAuthority", "CommitReceiverConsume"} {
		t.Run(op, func(t *testing.T) {
			f := newFixture(t, true)
			p := f.guardian
			var q Document
			if op == "AcquireOutputPermit" {
				f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
				p = f.runtime
				q = f.permitRequest(f.unit)
			} else {
				f.ready()
				q = f.queryAuthority()
				if op == "CommitReceiverConsume" {
					q = f.consumeQ
				}
			}
			f.outputDeadline(150 * time.Millisecond)
			f.s.Validate = func(n string, v Document) error {
				if n == op+"Response" {
					time.Sleep(220 * time.Millisecond)
				}
				return OfficialValidate(n, v)
			}
			f.denied(p, op, q)
			if f.count("dl05_receiver_consumptions") != 0 {
				t.Fatal("expired transaction committed a latch")
			}
			if op == "AcquireOutputPermit" && (f.count("dl05_v2_permits") != 0 || f.count("dl05_answer_fact_observations") != 0) {
				t.Fatal("expired permit/observation was not rolled back")
			}
		})
	}
}
func TestOutputDeadlineQueryBudgetUsesFinalDatabaseTime(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	until := f.outputDeadline(600 * time.Millisecond)
	var afterValidation time.Time
	f.s.Validate = func(n string, v Document) error {
		if n == "QueryReceiverAuthorityResponse" {
			time.Sleep(150 * time.Millisecond)
			if e := f.s.DB.QueryRow(f.ctx, "SELECT clock_timestamp()").Scan(&afterValidation); e != nil {
				return e
			}
		}
		return OfficialValidate(n, v)
	}
	out := f.call(f.guardian, "QueryReceiverAuthority", f.queryAuthority())
	snap := obj(out, "snapshot")
	f.assertBudget(snap, until)
	if date(snap, "authorityTime").Before(afterValidation) {
		t.Fatal("returned relative budget predates final validation")
	}
	if hash(obj(snap, "grant")) != hash(f.grant) {
		t.Fatal("query rewrote original immutable Grant")
	}
}
func waitBlockedOn(t *testing.T, f *fixture, pid uint32) {
	t.Helper()
	ctx, cancel := context.WithTimeout(f.ctx, 2*time.Second)
	defer cancel()
	for {
		var blocked bool
		e := f.s.DB.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND $1::int=ANY(pg_blocking_pids(pid)))", pid).Scan(&blocked)
		if e != nil {
			t.Fatal(e)
		}
		if blocked {
			return
		}
		select {
		case <-ctx.Done():
			t.Fatal("expected SQL lock wait not observed")
		case <-time.After(time.Millisecond):
		}
	}
}
func TestOutputDeadlineShorteningTransactionWins(t *testing.T) {
	// Another transaction shortens the mirror while the Authority transaction is
	// already running but waiting on its Run lock. The fresh committed row wins.
	for _, op := range []string{"QueryReceiverAuthority", "CommitReceiverConsume"} {
		t.Run(op, func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			tx, e := f.s.DB.Begin(f.ctx)
			if e != nil {
				t.Fatal(e)
			}
			defer tx.Rollback(f.ctx)
			if _, e = tx.Exec(f.ctx, "SELECT run_id FROM dl05_runs WHERE run_id=$1 FOR UPDATE", f.cmd["runId"]); e != nil {
				t.Fatal(e)
			}
			var until time.Time
			if e = tx.QueryRow(f.ctx, "UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '250 milliseconds' WHERE room_id=$1 RETURNING expires_at", f.control.Room).Scan(&until); e != nil {
				t.Fatal(e)
			}
			q := f.queryAuthority()
			if op == "CommitReceiverConsume" {
				q = f.consumeQ
				f.s.Validate = func(n string, v Document) error {
					if n == op+"Response" {
						time.Sleep(220 * time.Millisecond)
					}
					return OfficialValidate(n, v)
				}
			}
			type result struct {
				v Document
				e error
			}
			done := make(chan result, 1)
			go func() { v, e := f.s.Call(f.ctx, f.guardian, op, q); done <- result{v, e} }()
			waitBlockedOn(t, f, tx.Conn().PgConn().PID())
			if e = tx.Commit(f.ctx); e != nil {
				t.Fatal(e)
			}
			r := <-done
			if op == "CommitReceiverConsume" {
				if r.e == nil {
					t.Fatal("shortened deadline left a positive/unusable consume")
				}
				if f.count("dl05_receiver_consumptions") != 0 {
					t.Fatal("partial latch")
				}
			} else if r.e != nil {
				t.Fatal(r.e)
			} else {
				f.assertBudget(obj(r.v, "snapshot"), until)
			}
		})
	}
}
func TestOutputDeadlineWriterCannotCrossFinalPublication(t *testing.T) {
	// An output-only SQL writer (even without the trusted Run lock) must wait on
	// the existing output SHARE lock. There is no shortening between final check
	// and SQL commit; its later revocation rejects the next proof.
	for _, op := range []string{"AcquireOutputPermit", "QueryReceiverAuthority", "CommitReceiverConsume"} {
		t.Run(op, func(t *testing.T) {
			f := newFixture(t, true)
			p := f.guardian
			var q Document
			if op == "AcquireOutputPermit" {
				f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
				p = f.runtime
				q = f.permitRequest(f.unit)
			} else {
				f.ready()
				q = f.queryAuthority()
				if op == "CommitReceiverConsume" {
					q = f.consumeQ
				}
			}
			entered := make(chan struct{})
			release := make(chan struct{})
			var releaseOnce sync.Once
			unblock := func() { releaseOnce.Do(func() { close(release) }) }
			defer unblock()
			f.s.Validate = func(n string, v Document) error {
				if n == op+"Response" {
					close(entered)
					<-release
				}
				return OfficialValidate(n, v)
			}
			type result struct {
				v Document
				e error
			}
			auth := make(chan result, 1)
			go func() { v, e := f.s.Call(f.ctx, p, op, q); auth <- result{v, e} }()
			<-entered
			writer, e := f.s.DB.Begin(f.ctx)
			if e != nil {
				t.Fatal(e)
			}
			defer writer.Rollback(f.ctx)
			writerPID := writer.Conn().PgConn().PID()
			writerDone := make(chan error, 1)
			go func() {
				_, e := writer.Exec(f.ctx, "UPDATE dl05_room_outputs SET expires_at=clock_timestamp() WHERE room_id=$1", f.control.Room)
				if e == nil {
					e = writer.Commit(f.ctx)
				}
				writerDone <- e
			}()
			ctx, cancel := context.WithTimeout(f.ctx, 2*time.Second)
			defer cancel()
			for {
				var blocked bool
				if e = f.s.DB.QueryRow(ctx, "SELECT COALESCE(wait_event_type='Lock',false) FROM pg_stat_activity WHERE pid=$1", writerPID).Scan(&blocked); e != nil {
					t.Fatal(e)
				}
				if blocked {
					break
				}
				select {
				case e := <-writerDone:
					t.Fatalf("writer crossed locked publication: %v", e)
				case <-ctx.Done():
					t.Fatal("writer never waited")
				case <-time.After(time.Millisecond):
				}
			}
			unblock()
			r := <-auth
			if r.e != nil {
				t.Fatal(r.e)
			}
			if e = <-writerDone; e != nil {
				t.Fatal(e)
			}
			// Restore the ordinary local validator before the next (rejected) request.
			f.s.Validate = OfficialValidate
			f.denied(p, op, q)
			if op == "CommitReceiverConsume" {
				if r.v["consumeAuthorized"] != true || f.count("dl05_receiver_consumptions") != 1 {
					t.Fatal("lost first winner or latch")
				}
			}
		})
	}
}
func TestOutputDeadlineConcurrentConsumeAndRevocation(t *testing.T) {
	for _, ordered := range []bool{true, false} {
		t.Run(fmt.Sprint(ordered), func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			const n = 8
			entered := make(chan struct{}, n)
			release := make(chan struct{})
			start := make(chan struct{})
			if ordered {
				f.s.Assertions = func(context.Context, Actor, Document) error { entered <- struct{}{}; <-release; return nil }
			}
			type result struct {
				v Document
				e error
			}
			results := make(chan result, n)
			var wg sync.WaitGroup
			for i := 0; i < n; i++ {
				wg.Add(1)
				go func() {
					defer wg.Done()
					<-start
					v, e := f.s.Call(f.ctx, f.guardian, "CommitReceiverConsume", clone(f.consumeQ))
					results <- result{v, e}
				}()
			}
			close(start)
			if ordered {
				for i := 0; i < n; i++ {
					<-entered
				}
				f.outputDeadline(0)
				close(release)
			} else {
				f.outputDeadline(0)
			}
			wg.Wait()
			close(results)
			positive := 0
			for r := range results {
				if r.e == nil && r.v["consumeAuthorized"] == true {
					positive++
				}
			}
			if positive > 1 || f.count("dl05_receiver_consumptions") != positive || (ordered && positive != 0) {
				t.Fatalf("positive=%d, latch=%d", positive, f.count("dl05_receiver_consumptions"))
			}
			f.s.Assertions = func(context.Context, Actor, Document) error { return nil }
			f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
		})
	}
}
func TestOutputDeadlineLostACKKeepsLatchAndUnknown(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.outputDeadline(0)
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.call(f.control, "MarkExecutionUnknown", f.unknownQ())
	f.outputDeadline(time.Hour)
	f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.denied(f.runtime, "AcquireOutputPermit", f.permitRequest(f.unit))
	f.denied(f.runtime, "JournalStart", f.startQ)
	var state string
	if e := f.s.DB.QueryRow(f.ctx, "SELECT state FROM dl05_v2_grant_state WHERE grant_id=$1", f.grant["grantId"]).Scan(&state); e != nil || state != "CONSUMED" {
		t.Fatal(state, e)
	}
	if f.count("dl05_receiver_consumptions") != 1 || f.count("dl05_answer_grants") != 1 {
		t.Fatal("ACK loss reset immutable authority")
	}
}
func TestOutputDeadlineUnit2StillUsesIndependentGrant(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	until := f.outputDeadline(650 * time.Millisecond)
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	f.drainUnit(f.unit, 2, 0, 100)
	a, q := f.nextUnit()
	f.call(f.runtime, "JournalPrepareAnswer", q)
	pm := f.permitFor(a)
	start := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": pm["permitId"], "answerId": a["answerId"], "artifactId": a["artifactId"], "artifactHash": a["artifactHash"], "expectedAnswerRevision": int64(4)})
	out := f.call(f.runtime, "JournalStartAnswerSegment", start)
	g := obj(out, "grant")
	if out["segmentStartAuthorized"] != true || g["grantId"] == f.grant["grantId"] || date(g, "expiresAt").After(until) {
		t.Fatal("bad continuation Grant")
	}
	request := clone(f.consumeQ)
	refs := obj(request, "references")
	refs["artifactId"] = a["artifactId"]
	refs["artifactHash"] = a["artifactHash"]
	refs["permitId"] = pm["permitId"]
	refs["grantId"] = g["grantId"]
	request["consumeTicket"] = out["consumeTicket"]
	request["consumeRequestId"] = id("unit2")
	result := f.call(f.guardian, "CommitReceiverConsume", request)
	if result["consumeAuthorized"] != true || f.count("dl05_receiver_consumptions") != 2 {
		t.Fatal("Unit2 blocked or shared latch")
	}
}
func TestOutputDeadlineConsumedLongUnitCanRefreshProof(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	oldGrantHash := hash(f.grant)
	until := f.outputDeadline(3 * time.Second)
	time.Sleep(850 * time.Millisecond)
	pm := f.permitFor(f.unit)
	q := f.queryAuthority()
	obj(q, "references")["permitId"] = pm["permitId"]
	out := f.call(f.guardian, "QueryReceiverAuthority", q)
	snap := obj(out, "snapshot")
	f.assertBudget(snap, until)
	if hash(obj(snap, "grant")) != oldGrantHash || number(obj(snap, "timing"), "remainingGrantMs") != 0 || number(obj(snap, "timing"), "remainingProofMs") <= 100 {
		t.Fatal("renewal rewrote Grant or reused expired budget")
	}
	again := f.call(f.runtime, "JournalStart", f.startQ)
	if again["startAuthorized"] != false || again["consumeTicket"] != nil {
		t.Fatal("renewal regranted START")
	}
	if f.count("dl05_answer_grants") != 1 || f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("renewal expanded task identities")
	}
}
func TestOutputDeadlineStopUnknownAndEpochRemainClosed(t *testing.T) {
	for _, kind := range []string{"Stop", "Unknown", "Epoch"} {
		t.Run(kind, func(t *testing.T) {
			f := newFixture(t, true)
			f.ready()
			f.outputDeadline(0)
			switch kind {
			case "Stop":
				f.stop()
			case "Unknown":
				f.call(f.control, "MarkExecutionUnknown", f.unknownQ())
			case "Epoch":
				f.exec("UPDATE dl05_runs SET run_epoch=run_epoch+1 WHERE run_id=$1", f.cmd["runId"])
			}
			f.denied(f.guardian, "QueryReceiverAuthority", f.queryAuthority())
			f.denied(f.guardian, "CommitReceiverConsume", f.consumeQ)
			f.denied(f.runtime, "AcquireOutputPermit", f.permitRequest(f.unit))
			f.denied(f.runtime, "JournalStart", f.startQ)
			if f.count("dl05_receiver_consumptions") != 0 {
				t.Fatal("invalid context armed a latch")
			}
		})
	}
}
func TestOutputDeadlineRegistrationMustRemainCurrentAtCommit(t *testing.T) {
	f := newFixture(t, false)
	q := f.registrationRequest()
	f.outputDeadline(150 * time.Millisecond)
	f.s.Validate = func(n string, v Document) error {
		if n == "RegisterReceiverBootstrapResponse" {
			time.Sleep(220 * time.Millisecond)
		}
		return OfficialValidate(n, v)
	}
	f.denied(f.registrar, "RegisterReceiverBootstrap", q)
	if f.count("dl05_receiver_bootstraps") != 0 {
		t.Fatal("expired output registered through copied state")
	}
}

func TestOutputDeadlineStartCapsOriginalGrantAndBudget(t *testing.T) {
	f := newFixture(t, true)
	f.call(f.runtime, "JournalPrepareAnswer", f.prepareQ)
	pm := f.permitFor(f.unit)
	until := f.outputDeadline(250 * time.Millisecond)
	q := f.q(Document{"commandId": f.cmd["commandId"], "attemptId": f.cmd["attemptId"], "sessionId": f.cmd["sessionId"], "runEpoch": int64(1), "producerIncarnation": f.runtime.Producer, "requestHash": f.cmd["requestHash"], "permitId": pm["permitId"], "expectedInboxRevision": int64(2), "answerArtifactId": f.unit["artifactId"], "answerArtifactHash": f.unit["artifactHash"], "expectedAnswerRevision": int64(1)})
	out := f.call(f.runtime, "JournalStart", q)
	grant := obj(out, "answerGrant")
	if out["startAuthorized"] != true || date(grant, "expiresAt").After(until) || number(obj(out, "consumeTiming"), "remainingProofMs") > 250 || number(obj(out, "consumeTiming"), "remainingGrantMs") > 250 {
		t.Fatal("START ignored current Output deadline")
	}
	saved, e := row(f.s.DB.QueryRow(f.ctx, "SELECT grant_body FROM dl05_answer_grants WHERE grant_id=$1", grant["grantId"]))
	if e != nil || hash(saved) != hash(grant) {
		t.Fatal("returned Grant differs from immutable row", e)
	}
	again := f.call(f.runtime, "JournalStart", q)
	if again["startAuthorized"] != false || again["consumeTicket"] != nil {
		t.Fatal("START replayed positive authority")
	}
}
func TestOutputDeadlineIntersectsEarlierRunLease(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.outputDeadline(600 * time.Millisecond)
	var until time.Time
	if e := f.s.DB.QueryRow(f.ctx, "UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()+interval '250 milliseconds' WHERE run_id=$1 RETURNING lease_expires_at", f.cmd["runId"]).Scan(&until); e != nil {
		t.Fatal(e)
	}
	out := f.call(f.guardian, "QueryReceiverAuthority", f.queryAuthority())
	f.assertBudget(obj(out, "snapshot"), until)
	pm := f.permitFor(f.unit)
	if date(pm, "expiresAt").After(until) || date(pm, "factValidUntil").After(until) {
		t.Fatal("Output deadline displaced earlier lease/fact limit")
	}
}

func TestOutputDeadlineContinuousProofRefreshBeyondInitialGrantAndFacts(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	f.call(f.guardian, "CommitReceiverConsume", f.consumeQ)
	until := f.outputDeadline(5 * time.Second)
	original := hash(f.grant)
	previousExpiry := date(f.grant, "expiresAt")
	var snap Document
	for i := 0; i < 9; i++ {
		time.Sleep(250 * time.Millisecond)
		pm := f.permitFor(f.unit)
		if !date(pm, "issuedAt").Before(previousExpiry) {
			t.Fatal("fixture allowed a current-proof gap")
		}
		q := f.queryAuthority()
		obj(q, "references")["permitId"] = pm["permitId"]
		snap = obj(f.call(f.guardian, "QueryReceiverAuthority", q), "snapshot")
		f.assertBudget(snap, until)
		if hash(obj(snap, "grant")) != original || obj(snap, "consumption")["state"] != "CONSUMED" {
			t.Fatal("renewal altered consumed identity")
		}
		previousExpiry = date(pm, "expiresAt")
	}
	initialFact := list(f.unit, "factDependencies")[0].(map[string]any)
	if number(obj(snap, "timing"), "remainingGrantMs") != 0 || !date(obj(snap, "observation"), "verifiedAt").After(date(initialFact, "expiresAt")) {
		t.Fatal("test did not cross initial Grant and fact deadlines")
	}
	if f.count("dl05_receiver_consumptions") != 1 || f.count("dl05_answer_grants") != 1 {
		t.Fatal("continuous refresh reauthorized execution")
	}
}
