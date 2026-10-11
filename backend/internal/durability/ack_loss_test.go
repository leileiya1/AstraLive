package durability_test

import (
	"astralive/backend/internal/app"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/runtime"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestAcceptedBeforeLostACK(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	c := enqueue(t, ctx, p, s, r, "ack-loss")
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.Method == "GET" {
			raw, e := s.Lookup(ctx, "s", c.CommandID)
			if e != nil {
				t.Error(e)
				w.WriteHeader(503)
				return
			}
			_ = json.NewEncoder(w).Encode(raw)
			return
		}
		raw, e := io.ReadAll(req.Body)
		if e != nil {
			t.Error(e)
			return
		}
		a, e := s.Accept(ctx, raw)
		if e != nil {
			t.Error(e)
			return
		}
		if _, e = s.StartAttempt(ctx, "s", c.CommandID, "runtime", a.Run.Token); e != nil {
			t.Error(e)
			return
		}
		connection, _, e := w.(http.Hijacker).Hijack()
		if e != nil {
			t.Error(e)
			return
		}
		_ = connection.Close() // no ACK bytes reach Go
	}))
	defer remote.Close()
	rt := runtime.New(remote.URL)
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	d := &durability.Dispatcher{Store: s, Remote: rt, Log: log}
	loop, cancel := context.WithCancel(ctx)
	defer cancel()
	go d.Run(loop)
	eventually(t, 2*time.Second, func() bool {
		var state string
		_ = p.QueryRow(ctx, `SELECT delivery_state FROM v05_outbox WHERE command_id=$1`, c.CommandID).Scan(&state)
		return state == "UNKNOWN"
	})
	// Reconciliation uses the durable STARTED receipt, not request retry or Redis.
	_, _ = p.Exec(ctx, `UPDATE v05_outbox SET next_attempt_at=clock_timestamp()`)
	if e := d.ReconcileUnknown(ctx); e != nil {
		t.Fatal(e)
	}
	var state string
	_ = p.QueryRow(ctx, `SELECT delivery_state FROM v05_outbox WHERE command_id=$1`, c.CommandID).Scan(&state)
	if state != "ACKED" {
		t.Fatal(state)
	}
	var count int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_inbox WHERE command_id=$1`, c.CommandID).Scan(&count)
	if count != 1 {
		t.Fatal(count)
	}
}
func TestBoundedUnsentRetryDeadLetter(t *testing.T) {
	ctx, p, s := pg(t)
	_ = run(t, ctx, p, s, "s")
	service := app.New(p, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = s
	u, e := service.Speak(ctx, "s", "never sent", 40, "NONE", "OPERATOR", "trace", nil)
	if e != nil {
		t.Fatal(e)
	}
	remote := runtime.New("http://127.0.0.1:1")
	d := &durability.Dispatcher{Store: s, Remote: remote, Log: service.Log}
	loop, cancel := context.WithCancel(ctx)
	defer cancel()
	go d.Run(loop)
	eventually(t, 6*time.Second, func() bool {
		var state string
		_ = p.QueryRow(ctx, `SELECT delivery_state FROM v05_outbox WHERE utterance_id=$1`, u.ID).Scan(&state)
		return state == "FAILED"
	})
	var count int
	_ = p.QueryRow(ctx, `SELECT attempt_count FROM v05_outbox WHERE utterance_id=$1`, u.ID).Scan(&count)
	if count != 5 {
		t.Fatal(count)
	}
	got, e := service.Q.GetUtterance(ctx, u.ID)
	if e != nil || got.Status != "FAILED" {
		t.Fatalf("task not finalized: %s %v", got.Status, e)
	}
}
func TestUnknownProbeBudgetAndNoReplay(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	cmd := enqueue(t, ctx, p, s, r, "unknown")
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "missing history", 404) }))
	defer remote.Close()
	_, e := p.Exec(ctx, `UPDATE v05_outbox SET delivery_state='UNKNOWN',unknown_since=clock_timestamp()-interval '31 seconds' WHERE command_id=$1`, cmd.CommandID)
	if e != nil {
		t.Fatal(e)
	}
	d := &durability.Dispatcher{Store: s, Remote: runtime.New(remote.URL), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if e = d.ReconcileUnknown(ctx); e != nil {
		t.Fatal(e)
	}
	var status string
	_ = p.QueryRow(ctx, `SELECT status FROM v05_session_runs WHERE session_id='s'`).Scan(&status)
	if status != "RECOVERY_REQUIRED" {
		t.Fatal(status)
	}
	var state string
	_ = p.QueryRow(ctx, `SELECT delivery_state FROM v05_outbox`).Scan(&state)
	if state != "UNKNOWN" {
		t.Fatal("missing receipt triggered replay", state)
	}
}
