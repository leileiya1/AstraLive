package durability_test

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"testing"
	"time"

	"astralive/backend/db"
	"astralive/backend/internal/app"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/recovery"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func pg(t *testing.T) (context.Context, *pgxpool.Pool, *durability.Store) {
	t.Helper()
	dsn := os.Getenv("DURABILITY_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("DURABILITY_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	base, e := pgxpool.New(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	schema := ids.New("test")
	if _, e = base.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); e != nil {
		t.Fatal(e)
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	pool, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		pool.Close()
		_, _ = base.Exec(ctx, "DROP SCHEMA "+pgx.Identifier{schema}.Sanitize()+" CASCADE")
		base.Close()
	})
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	_, e = pool.Exec(ctx, `INSERT INTO config_principals VALUES('tenant','user');
 INSERT INTO avatars(id,name,engine) VALUES('a','avatar','MOCK');INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('v','voice','MOCK','mock');
 INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('room','room','a','v','prompt');
 INSERT INTO resource_owners VALUES('room','room','tenant','user');`)
	if e != nil {
		t.Fatal(e)
	}
	return ctx, pool, durability.New(pool)
}
func run(t *testing.T, ctx context.Context, p *pgxpool.Pool, s *durability.Store, sid string) durability.Run {
	t.Helper()
	_, e := p.Exec(ctx, `INSERT INTO live_sessions(id,room_id,status) VALUES($1,'room','LIVE')`, sid)
	if e != nil {
		t.Fatal(e)
	}
	_, e = p.Exec(ctx, `INSERT INTO resource_owners VALUES('session',$1,'tenant','user')`, sid)
	if e != nil {
		t.Fatal(e)
	}
	_, e = p.Exec(ctx, `INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,'tenant','user',$2,'{}','{}',clock_timestamp()+interval '1 hour')`, sid, "binding_"+sid)
	if e != nil {
		t.Fatal(e)
	}
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	r, e := s.InitialRun(ctx, tx, sid)
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	return r
}
func enqueue(t *testing.T, ctx context.Context, p *pgxpool.Pool, s *durability.Store, r durability.Run, key string) durability.Command {
	t.Helper()
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	rr, e := s.Current(ctx, tx, r.SessionID, true)
	if e != nil {
		t.Fatal(e)
	}
	c, e := s.Enqueue(ctx, tx, rr, "SPEAK", key, "trace", "", map[string]any{"text": "你好<&"})
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	return c
}
func TestPostgresJournalIdempotencyAndFences(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	c := enqueue(t, ctx, p, s, r, "one")
	again := enqueue(t, ctx, p, s, r, "one")
	if c.CommandID != again.CommandID {
		t.Fatal("semantic replay allocated another command")
	}
	raw, _ := json.Marshal(c)
	a, e := s.Accept(ctx, raw)
	if e != nil || !a.Execute || a.ReceiptSeq != 1 {
		t.Fatalf("accept %v %v", a, e)
	}
	aa, e := s.Accept(ctx, raw)
	if e != nil || aa.OperationID != a.OperationID {
		t.Fatal("acceptance changed")
	}
	bad := c
	bad.Payload = json.RawMessage(`{"text":"changed"}`)
	badRaw, _ := json.Marshal(bad)
	if _, e = s.Accept(ctx, badRaw); !errors.Is(e, durability.ErrConflict) {
		t.Fatalf("payload conflict %v", e)
	}
	first, e := s.StartAttempt(ctx, "s", c.CommandID, "process1", r.Token)
	if e != nil || !first.Execute {
		t.Fatal(e)
	}
	second, e := s.StartAttempt(ctx, "s", c.CommandID, "process2", r.Token)
	if e != nil || second.Execute {
		t.Fatal("executed STARTED twice")
	}
	lookup, e := s.Lookup(ctx, "s", c.CommandID)
	if e != nil {
		t.Fatal(e)
	}
	var x map[string]any
	_ = json.Unmarshal(lookup, &x)
	if x["executionState"] != "UNKNOWN" {
		t.Fatal(string(lookup))
	}
	if _, e = s.StartAttempt(ctx, "s", c.CommandID, "process1", r.Token+1); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("stale fence accepted %v", e)
	}
}
func TestTwoDispatchersLeaseExpiryOldAck(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	_ = enqueue(t, ctx, p, s, r, "one")
	// Dispatcher replicas for a current lease owner still race independently via SKIP LOCKED.
	var wg sync.WaitGroup
	var mu sync.Mutex
	var claims []durability.Claim
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			c, e := s.Claim(ctx)
			if e == nil {
				mu.Lock()
				claims = append(claims, c)
				mu.Unlock()
			} else if !errors.Is(e, pgx.ErrNoRows) {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	if len(claims) != 1 {
		t.Fatalf("claims %d", len(claims))
	}
	c := claims[0]
	if _, e := p.Exec(ctx, `UPDATE v05_outbox SET lease_expires_at=clock_timestamp()-interval '1 second'`); e != nil {
		t.Fatal(e)
	}
	if e := s.Finish(ctx, c, "ACKED", "", 0); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("expired ACK %v", e)
	}
	_, e := s.Claim(ctx)
	if !errors.Is(e, pgx.ErrNoRows) {
		t.Fatal(e)
	}
	var state string
	_ = p.QueryRow(ctx, `SELECT delivery_state FROM v05_outbox`).Scan(&state)
	if state != "UNKNOWN" {
		t.Fatal(state)
	}
	foreign := durability.New(p)
	if _, e = foreign.Claim(ctx); !errors.Is(e, pgx.ErrNoRows) {
		t.Fatal("nonowner dispatch")
	}
}
func TestRecoveryStopRaceAndOldEpoch(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	cmd := enqueue(t, ctx, p, s, r, "old")
	raw, _ := json.Marshal(cmd)
	a, e := s.Accept(ctx, raw)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.StartAttempt(ctx, "s", cmd.CommandID, "old-runtime", a.Run.Token); e != nil {
		t.Fatal(e)
	}
	_, e = p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second'`)
	if e != nil {
		t.Fatal(e)
	}
	newOwner := durability.New(p)
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	co := &recovery.Coordinator{Store: newOwner, Log: log}
	if e = co.Sweep(ctx); e != nil {
		t.Fatal(e)
	}
	var epoch int64
	var status string
	if e = p.QueryRow(ctx, `SELECT l.run_epoch,r.status FROM v05_recovery_leases l JOIN v05_session_runs r USING(session_id,run_epoch)`).Scan(&epoch, &status); e != nil {
		t.Fatal(e)
	}
	if epoch != 2 || status != "RECOVERY_REQUIRED" {
		t.Fatalf("%d %s", epoch, status)
	}
	if _, e = newOwner.Accept(ctx, raw); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("old epoch accepted %v", e)
	}
	service := app.New(p, nil, log)
	service.Durable = newOwner
	if _, e = service.Stop(ctx, "s", "stop"); e != nil {
		t.Fatal(e)
	}
	if e = co.Sweep(ctx); e != nil {
		t.Fatal(e)
	}
	if _, e = service.Speak(ctx, "s", "late", 40, "NONE", "OPERATOR", "trace", nil); !errors.Is(e, app.ErrConflict) {
		t.Fatalf("Stop revived: %v", e)
	}
	_ = p.QueryRow(ctx, `SELECT status FROM v05_session_runs WHERE session_id='s' AND run_epoch=2`).Scan(&status)
	if status != "STOPPING" {
		t.Fatal(status)
	}
}
func TestEventDupConflictReorderAndTerminal(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	service := app.New(p, nil, log)
	service.Durable = s
	u, e := service.Speak(ctx, "s", "hello", 40, "NONE", "OPERATOR", "trace", nil)
	if e != nil {
		t.Fatal(e)
	}
	var raw []byte
	if e = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE utterance_id=$1`, u.ID).Scan(&raw); e != nil {
		t.Fatal(e)
	}
	var cmd durability.Command
	_ = json.Unmarshal(raw, &cmd)
	a, e := s.Accept(ctx, raw)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.StartAttempt(ctx, "s", cmd.CommandID, "runtime", a.Run.Token); e != nil {
		t.Fatal(e)
	}
	types := []string{"UTTERANCE_COMPLETED", "UTTERANCE_PLAYING", "UTTERANCE_RENDERING", "UTTERANCE_SYNTHESIZING", "UTTERANCE_GENERATING", "UTTERANCE_QUEUED"}
	var first []byte
	for i, kind := range types {
		legacy := app.Event{SchemaVersion: "1.0", EventID: fmt.Sprint("e", i), EventType: kind, SessionID: "s", UtteranceID: &u.ID, TraceID: "trace", OccurredAt: time.Now().UTC(), Source: "AI_RUNTIME", Payload: map[string]any{}}
		payload, _ := json.Marshal(map[string]any{"legacy": legacy})
		d := durability.DurableEvent{SchemaVersion: "0.5", EventID: legacy.EventID, SessionID: "s", RunEpoch: r.Epoch, Producer: "runtime", ProducerSeq: int64(i + 1), CommandID: cmd.CommandID, TraceID: "trace", OccurredAt: legacy.OccurredAt, EventType: kind, Source: "AI_RUNTIME", Payload: payload}
		b, _ := json.Marshal(d)
		if i == 0 {
			first = b
		}
		if _, e = s.Ingest(ctx, b); e != nil {
			t.Fatal(e)
		}
	}
	if stored, e := s.Ingest(ctx, first); e != nil || stored {
		t.Fatal("duplicate event", e)
	}
	var bad map[string]any
	_ = json.Unmarshal(first, &bad)
	bad["traceId"] = "tamper"
	b, _ := json.Marshal(bad)
	if _, e = s.Ingest(ctx, b); !errors.Is(e, durability.ErrConflict) {
		t.Fatal("event hash conflict", e)
	}
	for wave := 0; wave < 8; wave++ {
		for i := 0; i < 6; i++ {
			if _, e = service.ApplyNextDurable(ctx); e != nil {
				t.Fatal(e)
			}
		}
		_, _ = p.Exec(ctx, `UPDATE v05_events SET next_attempt_at=clock_timestamp() WHERE processing_state='PENDING'`)
	}
	got, e := service.Q.GetUtterance(ctx, u.ID)
	if e != nil {
		t.Fatal(e)
	}
	if got.Status != "COMPLETED" {
		t.Fatal(got.Status)
	}
	// Late generation events cannot regress a terminal utterance or advance a new run.
	var state string
	_ = p.QueryRow(ctx, `SELECT execution_state FROM v05_inbox WHERE command_id=$1`, cmd.CommandID).Scan(&state)
	if state != "TERMINAL" {
		t.Fatal(state)
	}
}
func TestDifferentRoomsAndConcurrentSpeakStop(t *testing.T) {
	ctx, p, s := pg(t)
	run(t, ctx, p, s, "a_session")
	run(t, ctx, p, s, "b_session")
	if _, e := p.Exec(ctx, `INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('room_b','room','a','v','prompt'); INSERT INTO resource_owners VALUES('room','room_b','tenant','user'); UPDATE live_sessions SET room_id='room_b' WHERE id='b_session'`); e != nil {
		t.Fatal(e)
	}
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	service := app.New(p, nil, log)
	service.Durable = s
	held, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer held.Rollback(ctx)
	if _, e = held.Exec(ctx, `SELECT id FROM live_sessions WHERE id='a_session' FOR UPDATE`); e != nil {
		t.Fatal(e)
	}
	blocked := make(chan error, 1)
	go func() { _, e := service.Speak(ctx, "a_session", "a", 40, "NONE", "OPERATOR", "t", nil); blocked <- e }()
	bctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()
	if _, e = service.Speak(bctx, "b_session", "b", 40, "NONE", "OPERATOR", "t", nil); e != nil {
		t.Fatalf("other room blocked %v", e)
	}
	if e = held.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	if e = <-blocked; e != nil {
		t.Fatal(e)
	}
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		_, _ = service.Speak(ctx, "a_session", "race", 40, "NONE", "OPERATOR", "t", nil)
	}()
	go func() {
		defer wg.Done()
		_, e := service.Stop(ctx, "a_session", "stop")
		if e != nil {
			t.Error(e)
		}
	}()
	wg.Wait()
	if _, e = service.Speak(ctx, "a_session", "late", 40, "NONE", "OPERATOR", "t", nil); !errors.Is(e, app.ErrConflict) {
		t.Fatal(e)
	}
	var pending int
	if e = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE session_id='a_session' AND command_type='SPEAK' AND delivery_state='PENDING'`).Scan(&pending); e != nil || pending != 0 {
		t.Fatalf("pending speech %d %v", pending, e)
	}
}
func TestMigrationConcurrentAndReplay(t *testing.T) {
	ctx, p, _ := pg(t)
	var wg sync.WaitGroup
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if e := db.Migrate(ctx, p); e != nil {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	var n int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM schema_migrations`).Scan(&n)
	if n != 6 {
		t.Fatal(n)
	}
}

// Real SIGKILL: only the child test process started by this test is killed.
func TestTransactionSIGKILL(t *testing.T) {
	if mode := os.Getenv("ASTRALIVE_FAULT_HELPER"); mode != "" {
		ctx := context.Background()
		cfg, e := pgxpool.ParseConfig(os.Getenv("DURABILITY_TEST_DATABASE_URL"))
		if e != nil {
			panic(e)
		}
		cfg.ConnConfig.RuntimeParams["search_path"] = os.Getenv("ASTRALIVE_FAULT_SCHEMA")
		p, e := pgxpool.NewWithConfig(ctx, cfg)
		if e != nil {
			panic(e)
		}
		s := durability.New(p)
		s.Owner = os.Getenv("ASTRALIVE_FAULT_OWNER")
		tx, e := p.Begin(ctx)
		if e != nil {
			panic(e)
		}
		r, e := s.Current(ctx, tx, "s", true)
		if e != nil {
			panic(e)
		}
		_, e = tx.Exec(ctx, `INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES('crash_utt','s','OPERATOR','hello',40,'NONE','trace')`)
		if e != nil {
			panic(e)
		}
		_, e = s.Enqueue(ctx, tx, r, "SPEAK", "crash", "trace", "crash_utt", map[string]any{"text": "hello"})
		if e != nil {
			panic(e)
		}
		if mode == "after" {
			if e = tx.Commit(ctx); e != nil {
				panic(e)
			}
		}
		fmt.Println("FAULT_READY")
		time.Sleep(time.Hour)
		return
	}
	for _, mode := range []string{"before", "after"} {
		t.Run(mode, func(t *testing.T) {
			ctx, p, s := pg(t)
			run(t, ctx, p, s, "s")
			var schema string
			if e := p.QueryRow(ctx, "SELECT current_schema()").Scan(&schema); e != nil {
				t.Fatal(e)
			}
			child := exec.Command(os.Args[0], "-test.run=^TestTransactionSIGKILL$", "-test.v")
			child.Env = append(os.Environ(), "ASTRALIVE_FAULT_HELPER="+mode, "ASTRALIVE_FAULT_SCHEMA="+schema, "ASTRALIVE_FAULT_OWNER="+s.Owner)
			stdout, e := child.StdoutPipe()
			if e != nil {
				t.Fatal(e)
			}
			child.Stderr = os.Stderr
			if e = child.Start(); e != nil {
				t.Fatal(e)
			}
			ready := make(chan bool, 1)
			go func() {
				scan := bufio.NewScanner(stdout)
				for scan.Scan() {
					if scan.Text() == "FAULT_READY" {
						ready <- true
						return
					}
				}
				ready <- false
			}()
			select {
			case okay := <-ready:
				if !okay {
					t.Fatal("child failed before injection")
				}
			case <-time.After(5 * time.Second):
				_ = child.Process.Kill()
				_ = child.Wait()
				t.Fatal("injection checkpoint timeout")
			}
			_ = child.Process.Kill()
			_ = child.Wait()
			var count int
			e = p.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE id='crash_utt'`).Scan(&count)
			if e != nil {
				t.Fatal(e)
			}
			expected := 0
			if mode == "after" {
				expected = 1
			}
			if count != expected {
				t.Fatalf("utterances=%d", count)
			}
			var commands int
			_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE utterance_id='crash_utt'`).Scan(&commands)
			if commands != expected {
				t.Fatalf("non-atomic outbox %d", commands)
			}
		})
	}
}
func TestControlReceipt(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	c, e := s.Enqueue(ctx, tx, r, "BEGIN_RUN", "initial", "trace", "", map[string]any{})
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(c)
	if _, e = s.Accept(ctx, raw); e != nil {
		t.Fatal(e)
	}
	if _, e = s.StartAttempt(ctx, "s", c.CommandID, "runtime", 1); e != nil {
		t.Fatal(e)
	}
	if e = s.Observe(ctx, durability.Observation{SessionID: "s", RunEpoch: 1, CommandID: c.CommandID, ReceiptSeq: 3, State: "completed", Producer: "runtime", EvidenceType: "control_cleanup", EvidenceRef: "installed"}); e != nil {
		t.Fatal(e)
	}
}
func TestForceFencesDelayedSpeakAndStopExpiredRun(t *testing.T) {
	ctx, p, s := pg(t)
	run(t, ctx, p, s, "s")
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	service := app.New(p, nil, log)
	service.Durable = s
	u, e := service.Speak(ctx, "s", "pending", 40, "NONE", "OPERATOR", "trace", nil)
	if e != nil {
		t.Fatal(e)
	}
	var raw []byte
	_ = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE utterance_id=$1`, u.ID).Scan(&raw)
	if _, e = service.Interrupt(ctx, "s", "force", "OPERATOR_INTERRUPT"); e != nil {
		t.Fatal(e)
	}
	if _, e = s.Accept(ctx, raw); e == nil {
		t.Fatal("late pre-FORCE command accepted")
	}
	got, e := service.Q.GetUtterance(ctx, u.ID)
	if e != nil || got.Status != "CANCELLED" {
		t.Fatal(got.Status, e)
	}
	_, e = p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second';UPDATE session_provider_bindings SET expires_at=clock_timestamp()-interval '1 second'`)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = service.Stop(ctx, "s", "stop"); e != nil {
		t.Fatalf("expired binding prevented cleanup: %v", e)
	}
	var stopRaw []byte
	_ = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_type='STOP_SESSION'`).Scan(&stopRaw)
	if _, e = s.Accept(ctx, stopRaw); e != nil {
		t.Fatalf("cleanup command rejected: %v", e)
	}
	if _, e = service.Speak(ctx, "s", "forbidden", 40, "NONE", "OPERATOR", "trace", nil); e == nil {
		t.Fatal("expired run generated media")
	}
}
func TestStopConcurrentWithRecovery(t *testing.T) {
	ctx, p, s := pg(t)
	run(t, ctx, p, s, "s")
	_, e := p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second'`)
	if e != nil {
		t.Fatal(e)
	}
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	service := app.New(p, nil, log)
	service.Durable = s
	co := &recovery.Coordinator{Store: durability.New(p), Log: log}
	start := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		<-start
		if _, e := service.Stop(ctx, "s", "stop"); e != nil {
			t.Error(e)
		}
	}()
	go func() {
		defer wg.Done()
		<-start
		if e := co.Sweep(ctx); e != nil {
			t.Error(e)
		}
	}()
	close(start)
	wg.Wait()
	var status string
	var count int
	if e = p.QueryRow(ctx, `SELECT r.status FROM v05_session_runs r JOIN v05_recovery_leases l USING(session_id,run_epoch) WHERE l.session_id='s'`).Scan(&status); e != nil {
		t.Fatal(e)
	}
	if status != "STOPPING" {
		t.Fatal("recovery resurrected Stop", status)
	}
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='STOP_SESSION'`).Scan(&count)
	if count != 1 {
		t.Fatal(count)
	}
	if _, e = service.Speak(ctx, "s", "late", 40, "NONE", "OPERATOR", "trace", nil); e == nil {
		t.Fatal("speech after Stop/recovery race")
	}
}

func TestMediaAttemptGenerationAndEventFence(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	first := enqueue(t, ctx, p, s, r, "media1")
	raw, _ := json.Marshal(first)
	if _, e := s.Accept(ctx, raw); e != nil {
		t.Fatal(e)
	}
	a, e := s.StartAttempt(ctx, "s", first.CommandID, "runtime", r.Token)
	if e != nil || a.AttemptID == "" {
		t.Fatalf("attempt not journaled: %v %v", a, e)
	}
	if _, _, e = s.StartMedia(ctx, "s", first.CommandID, "wrong-runtime", 0); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("wrong executor: %v", e)
	}
	_, gen, e := s.StartMedia(ctx, "s", first.CommandID, "runtime", 0)
	if e != nil || gen != 1 {
		t.Fatalf("initial generation %d: %v", gen, e)
	}
	if _, _, e = s.StartMedia(ctx, "s", first.CommandID, "runtime", 0); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("replayed media attempt: %v", e)
	}
	second := enqueue(t, ctx, p, s, r, "media2")
	raw, _ = json.Marshal(second)
	if _, e = s.Accept(ctx, raw); e != nil {
		t.Fatal(e)
	}
	if _, e = s.StartAttempt(ctx, "s", second.CommandID, "runtime", r.Token); e != nil {
		t.Fatal(e)
	}
	_, gen2, e := s.StartMedia(ctx, "s", second.CommandID, "runtime", 10)
	if e != nil || gen2 != 11 {
		t.Fatalf("generation did not exceed installed fence: %d %v", gen2, e)
	}
	timeline := int64(1)
	event := durability.DurableEvent{SchemaVersion: "0.5", EventID: "media-proof", SessionID: "s", RunEpoch: r.Epoch, Producer: "runtime", ProducerSeq: 1, CommandID: first.CommandID, AttemptID: a.AttemptID, GenerationID: &gen, TimelineEpoch: &timeline, TraceID: "trace", OccurredAt: time.Now().UTC(), EventType: "RUNTIME_WARNING", Source: "AI_RUNTIME", Payload: json.RawMessage(`{"legacy":{}}`)}
	raw, _ = json.Marshal(event)
	if _, e = s.Ingest(ctx, raw); e != nil {
		t.Fatal(e)
	}
	event.EventID = "wrong-media-proof"
	event.ProducerSeq = 2
	event.GenerationID = &gen2
	raw, _ = json.Marshal(event)
	if _, e = s.Ingest(ctx, raw); !errors.Is(e, durability.ErrConflict) {
		t.Fatalf("foreign generation event accepted: %v", e)
	}
}
