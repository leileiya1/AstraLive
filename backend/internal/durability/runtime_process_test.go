package durability_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/app"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
)

type testIntegration struct{}

func (testIntegration) Prepare(context.Context, string, *runtimeapi.CreateRuntimeSessionRequest) error {
	return nil
}
func (testIntegration) Release(context.Context, string) error { return nil }
func eventually(t *testing.T, budget time.Duration, predicate func() bool) {
	t.Helper()
	deadline := time.Now().Add(budget)
	for time.Now().Before(deadline) {
		if predicate() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("checkpoint timed out")
}
func TestRuntimeProcessCrashRedisOff(t *testing.T) {
	python := os.Getenv("DURABILITY_TEST_PYTHON")
	if python == "" {
		t.Skip("DURABILITY_TEST_PYTHON not set: real owned CPU Runtime process required")
	}
	ctx, p, s := pg(t)
	run(t, ctx, p, s, "s")
	_, e := p.Exec(ctx, `DELETE FROM v05_recovery_leases;DELETE FROM v05_session_runs;UPDATE live_sessions SET status='CREATED' WHERE id='s'`)
	if e != nil {
		t.Fatal(e)
	}
	journalFile := filepath.Join(t.TempDir(), "journal.token")
	controlFile := filepath.Join(t.TempDir(), "control.token")
	if e = os.WriteFile(journalFile, []byte(strings.Repeat("j", 48)), 0600); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(controlFile, []byte(strings.Repeat("c", 48)), 0600); e != nil {
		t.Fatal(e)
	}
	// Independent journal HTTP server can be interrupted without losing PostgreSQL state.
	journal := httptest.NewServer(http.StripPrefix("/internal/v0.5/durability", httpapi.JournalRouter(s, journalFile)))
	defer journal.Close()
	listener, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	addr := listener.Addr().(*net.TCPAddr)
	listener.Close()
	root, e := filepath.Abs("../../..")
	if e != nil {
		t.Fatal(e)
	}
	effects := filepath.Join(t.TempDir(), "effects.log")
	spool := filepath.Join(t.TempDir(), "spool")
	var child *exec.Cmd
	var runtimeLog string
	t.Cleanup(func() {
		if t.Failed() {
			raw, _ := os.ReadFile(runtimeLog)
			t.Log(string(raw))
		}
	})
	start := func() {
		child = exec.Command(python, "-m", "uvicorn", "durability_cpu_server:app", "--host", "127.0.0.1", "--port", fmt.Sprint(addr.Port), "--log-level", "warning")
		child.Dir = root
		child.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "runtime")+":"+filepath.Join(root, "runtime/tests"), "ASTRALIVE_DURABILITY_ENABLED=true", "ASTRALIVE_EVENT_MODE=postgres_only", "REDIS_URL=redis://127.0.0.1:1", "SESSION_BINDINGS_ENABLED=false", "APP_ENV=development", "CONFIG_BACKEND_URL="+journal.URL, "RUNTIME_JOURNAL_TOKEN_FILE="+journalFile, "RUNTIME_CONTROL_TOKEN_FILE="+controlFile, "RUNTIME_EVENT_SPOOL_DIR="+spool, "DURABILITY_CPU_EFFECT_FILE="+effects)
		runtimeLog = filepath.Join(t.TempDir(), "runtime.log")
		output, e := os.OpenFile(runtimeLog, os.O_CREATE|os.O_WRONLY, 0600)
		if e != nil {
			t.Fatal(e)
		}
		child.Stdout = output
		child.Stderr = output
		if e = child.Start(); e != nil {
			t.Fatal(e)
		}
		t.Cleanup(func() { output.Close() })
	}
	start()
	defer func() {
		if t.Failed() {
			raw, _ := os.ReadFile(runtimeLog)
			t.Log("runtime:", string(raw))
			rows, _ := p.Query(ctx, `SELECT command_type,delivery_state,COALESCE(last_error_code,'') FROM v05_outbox`)
			if rows != nil {
				defer rows.Close()
				for rows.Next() {
					var kind, state, code string
					_ = rows.Scan(&kind, &state, &code)
					t.Log(kind, state, code)
				}
			}
			var proof string
			_ = p.QueryRow(ctx, `SELECT COALESCE(jsonb_agg(jsonb_build_object('state',execution_state,'seq',last_receipt_seq)),'[]')::text FROM v05_inbox`).Scan(&proof)
			t.Log("inbox", proof)
			var events string
			_ = p.QueryRow(ctx, `SELECT COALESCE(jsonb_agg(jsonb_build_object('type',event_type,'state',processing_state,'reason',last_error_code)),'[]')::text FROM v05_events`).Scan(&events)
			t.Log("events", events)
			var command []byte
			_ = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox ORDER BY command_seq LIMIT 1`).Scan(&command)
			t.Log("replay error", func() error {
				debug := runtime.New("http://" + addr.String())
				debug.Client.Transport = userconfig.TokenTransport{Path: controlFile, Base: &http.Transport{Proxy: nil}}
				return debug.Deliver(ctx, "s", command)
			}())
		}
	}()
	defer func() {
		if child != nil && child.ProcessState == nil {
			_ = child.Process.Kill()
			_ = child.Wait()
		}
	}()
	rt := runtime.New("http://" + addr.String())
	rt.Client.Transport = userconfig.TokenTransport{Path: controlFile, Base: &http.Transport{Proxy: nil}}
	eventually(t, 5*time.Second, func() bool { h, e := rt.Health(ctx); return e == nil && h.Status == "UP" })
	service := app.New(p, rt, slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = s
	service.Integration = testIntegration{}
	loop, cancel := context.WithCancel(ctx)
	defer cancel()
	d := &durability.Dispatcher{Store: s, Remote: rt, Log: service.Log}
	go d.Run(loop)
	go eventbus.RunPostgres(loop, service, service.Log)
	go func() {
		tick := time.NewTicker(time.Second)
		defer tick.Stop()
		for {
			select {
			case <-loop.Done():
				return
			case <-tick.C:
				_ = s.Renew(loop)
			}
		}
	}()
	if _, e = service.Start(ctx, "s", "start_trace"); e != nil {
		t.Fatal(e)
	}
	eventually(t, 5*time.Second, func() bool { se, e := service.Q.GetSession(ctx, "s"); return e == nil && se.Status == "LIVE" })
	u, e := service.Speak(ctx, "s", "CPU crash test", 40, "NONE", "OPERATOR", "speak_trace", nil)
	if e != nil {
		t.Fatal(e)
	}
	eventually(t, 5*time.Second, func() bool { b, _ := os.ReadFile(effects); return len(b) > 0 })
	// SIGKILL during synthetic media handoff. Only this child is targeted.
	_ = child.Process.Kill()
	_ = child.Wait()
	before, _ := os.ReadFile(effects)
	var cid string
	if e = p.QueryRow(ctx, `SELECT command_id FROM v05_outbox WHERE utterance_id=$1`, u.ID).Scan(&cid); e != nil {
		t.Fatal(e)
	}
	start()
	eventually(t, 5*time.Second, func() bool { _, e := rt.Health(ctx); return e == nil })
	receipt, e := rt.Reconcile(ctx, "s", cid)
	if e != nil {
		t.Fatal(e)
	}
	var state map[string]any
	_ = json.Unmarshal(receipt, &state)
	if state["executionState"] != "UNKNOWN" {
		t.Fatalf("restart did not retain uncertainty: %s", receipt)
	}
	var raw []byte
	_ = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_id=$1`, cid).Scan(&raw)
	if e = rt.Deliver(ctx, "s", raw); e != nil {
		t.Fatal(e)
	} // stable receipt replay, no media execution
	after, _ := os.ReadFile(effects)
	if string(after) != string(before) {
		t.Fatal("Runtime restart replayed STARTED media")
	}
	var pending int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_events`).Scan(&pending)
	if pending == 0 {
		t.Fatal("Redis-off events not in PostgreSQL")
	}
	t.Log("CPU_SIMULATION SIGKILL: execution UNKNOWN after restart; same command produced zero additional synthetic sink writes; Redis unreachable")
}
