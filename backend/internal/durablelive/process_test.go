package durablelive

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type processConfig struct {
	RuntimeHTTP   bool      `json:"runtimeHTTP"`
	URL           string    `json:"url"`
	ControlToken  string    `json:"controlToken"`
	RuntimeToken  string    `json:"runtimeToken"`
	GuardianToken string    `json:"guardianToken"`
	Control       Principal `json:"control"`
	Runtime       Principal `json:"runtime"`
	Guardian      Principal `json:"guardian"`
	RunID         string    `json:"runID"`
	SessionID     string    `json:"sessionID"`
	RoomID        string    `json:"roomID"`
	Binding       int64     `json:"binding"`
	Command       Object    `json:"command"`
	Intent        Object    `json:"intent"`
}

// This is invoked ONLY as a subprocess of tests below. It refuses normal use.
func TestIsolatedBackendHelper(t *testing.T) {
	path := os.Getenv("DURABLE_LIVE_HELPER_CONFIG")
	if path == "" {
		t.Skip("owned subprocess helper")
	}
	if !strings.Contains(path, "TestProcess") {
		t.Fatal("refuse external path")
	}
	var cfg processConfig
	var s *Store
	b, e := os.ReadFile(path)
	if e == nil {
		if e = json.Unmarshal(b, &cfg); e != nil {
			t.Fatal(e)
		}
		s = New(testDB(t), []string{"test-sink"})
		cfg.Control.InstanceID = freshID("restarted-backend")
	} else {
		f := newFixture(t, true)
		s = f.s
		out := f.claim(f.turn("OPERATOR", nil, nil))
		var c Claimed
		if os.Getenv("DURABLE_LIVE_HELPER_STAGE") == "commit" {
			tx, e := f.s.begin(f.ctx)
			if e != nil {
				t.Fatal(e)
			}
			in, e := loadIntent(f.ctx, tx, str(obj(out, "intent"), "intentId"))
			if e != nil {
				t.Fatal(e)
			}
			cmd, e := commandFor(f.ctx, tx, f.run(), str(in, "commandId"))
			if e != nil {
				t.Fatal(e)
			}
			_ = tx.Rollback(f.ctx)
			c = Claimed{in, cmd}
		} else {
			c = f.send()
		}

		cfg = processConfig{Control: f.p, Runtime: f.j, Guardian: f.g, ControlToken: freshID("control") + freshID("token"), RuntimeToken: freshID("journal") + freshID("token"), GuardianToken: freshID("guardian") + freshID("token"), RunID: f.runID, SessionID: f.sid, RoomID: f.roomID, Command: c.Command, Intent: c.Intent}
		if e = s.DB.QueryRow(f.ctx, `SELECT output_binding_version FROM dl05_room_outputs WHERE room_id=$1`, f.roomID).Scan(&cfg.Binding); e != nil {
			t.Fatal(e)
		}
	}
	address := "127.0.0.1:0"
	if cfg.URL != "" {
		address = strings.TrimPrefix(cfg.URL, "http://")
	}
	listener, e := net.Listen("tcp", address)
	if e != nil {
		t.Fatal(e)
	}
	cfg.URL = "http://" + listener.Addr().String()
	handler, e := NewHandler(s, []Credential{{cfg.ControlToken, cfg.Control}, {cfg.RuntimeToken, cfg.Runtime}, {cfg.GuardianToken, cfg.Guardian}})
	if e != nil {
		t.Fatal(e)
	}
	b, _ = json.Marshal(cfg)
	if e = os.WriteFile(path, b, 0600); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(path+".ready", []byte("ready"), 0600); e != nil {
		t.Fatal(e)
	}
	server := &http.Server{Handler: handler, ReadHeaderTimeout: time.Second}
	if e = server.Serve(listener); e != nil {
		t.Fatal(e)
	}
}
func waitPath(t *testing.T, path string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, e := os.Stat(path); e == nil {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timeout waiting for %s", filepath.Base(path))
}
func startOwned(t *testing.T, cmd *exec.Cmd, logPath string) {
	t.Helper()
	file, e := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	cmd.Stdout = file
	cmd.Stderr = file
	if e = cmd.Start(); e != nil {
		t.Fatal(e)
	}
	_ = file.Close()
	t.Cleanup(func() {
		if cmd.ProcessState == nil {
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
		}
	})
}
func startBackend(t *testing.T, path string) *exec.Cmd {
	t.Helper()
	_ = os.Remove(path + ".ready")
	cmd := exec.Command(os.Args[0], "-test.run=^TestIsolatedBackendHelper$")
	cmd.Env = append(os.Environ(), "DURABLE_LIVE_HELPER_CONFIG="+path)
	startOwned(t, cmd, path+".backend.log")
	waitPath(t, path+".ready", 15*time.Second)
	return cmd
}
func loadConfig(t *testing.T, path string) processConfig {
	t.Helper()
	b, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	var cfg processConfig
	if e = json.Unmarshal(b, &cfg); e != nil {
		t.Fatal(e)
	}
	cfg.Command, e = Decode(mustJSON(cfg.Command))
	if e != nil {
		t.Fatal(e)
	}
	cfg.Intent, e = Decode(mustJSON(cfg.Intent))
	if e != nil {
		t.Fatal(e)
	}
	return cfg
}
func mustJSON(v any) []byte { b, _ := json.Marshal(v); return b }
func TestProcessGoSIGKILLWhilePythonPlayingAndReattach(t *testing.T) {
	python := os.Getenv("DURABLE_LIVE_TEST_PYTHON")
	if python == "" {
		t.Skip("isolated Python required")
	}
	_ = testDB(t)
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	backend := startBackend(t, path)
	cfg := loadConfig(t, path)
	runtime := exec.Command(python, "../../../scripts/durable-live/runtime_fault_probe.py", path)
	startOwned(t, runtime, filepath.Join(dir, "runtime.log"))
	waitPath(t, filepath.Join(dir, "playing"), 15*time.Second)
	// Kill ONLY the Go subprocess that this test created. A real Python task and
	// its journal STARTED/PLAYING records survive the Backend process.
	if e := backend.Process.Kill(); e != nil {
		t.Fatal(e)
	}
	_ = backend.Wait()
	waitPath(t, filepath.Join(dir, "sink-closed"), 3*time.Second)
	stat, e := os.Stat(filepath.Join(dir, "sink-bytes"))
	if e != nil {
		t.Fatal(e)
	}
	size := stat.Size()
	time.Sleep(120 * time.Millisecond)
	stat, _ = os.Stat(filepath.Join(dir, "sink-bytes"))
	if stat.Size() != size {
		t.Fatal("media handoff continued after permit expiry")
	}
	startBackend(t, path)
	cfg = loadConfig(t, path)
	time.Sleep(time.Second) // wait for the last DB permit, not just the local close
	pool := testDB(t)
	s := New(pool, []string{"test-sink"})
	if e = (&Coordinator{s, cfg.Control, 32}).Tick(context.Background()); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(dir, "duplicate"), []byte("query only"), 0600); e != nil {
		t.Fatal(e)
	}
	waitPath(t, filepath.Join(dir, "duplicate-result"), 3*time.Second)
	b, e := os.ReadFile(filepath.Join(dir, "effects"))
	if e != nil || len(strings.Fields(string(b))) != 1 {
		t.Fatal("duplicate physical test effect", e)
	}
	var state, last string
	if e = pool.QueryRow(context.Background(), `SELECT i.status,a.last_checkpoint FROM dl05_runtime_inbox i JOIN dl05_attempts a USING(command_id) WHERE i.command_id=$1`, cfg.Command["commandId"]).Scan(&state, &last); e != nil {
		t.Fatal(e)
	}
	if state != "UNKNOWN" || last != "UNKNOWN" {
		t.Fatal(state, last)
	}
	_ = os.WriteFile(filepath.Join(dir, "finish"), []byte("finish"), 0600)
	if e = runtime.Wait(); e != nil {
		t.Fatal("runtime probe failed; inspect owned log", e)
	}
	t.Log("real Go child SIGKILL; Python survived; watchdog closed local sink; restarted Go reconciled UNKNOWN; one synthetic sink execution; no replay")
}
func TestProcessPythonSIGKILLPreservesUnknown(t *testing.T) {
	python := os.Getenv("DURABLE_LIVE_TEST_PYTHON")
	if python == "" {
		t.Skip("isolated Python required")
	}
	_ = testDB(t)
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	startBackend(t, path)
	cfg := loadConfig(t, path)
	runtime := exec.Command(python, "../../../scripts/durable-live/runtime_fault_probe.py", path)
	startOwned(t, runtime, filepath.Join(dir, "runtime.log"))
	waitPath(t, filepath.Join(dir, "playing"), 15*time.Second)
	if e := runtime.Process.Kill(); e != nil {
		t.Fatal(e)
	}
	_ = runtime.Wait()
	time.Sleep(time.Second)
	pool := testDB(t)
	s := New(pool, []string{"test-sink"})
	if e := (&Coordinator{s, cfg.Control, 32}).Tick(context.Background()); e != nil {
		t.Fatal(e)
	}
	var state string
	if e := pool.QueryRow(context.Background(), `SELECT status FROM dl05_runtime_inbox WHERE command_id=$1`, cfg.Command["commandId"]).Scan(&state); e != nil {
		t.Fatal(e)
	}
	if state != "UNKNOWN" {
		t.Fatal(state)
	}
	claims, e := s.ClaimBatch(context.Background(), cfg.Control, 16)
	if e != nil || len(claims) != 0 {
		t.Fatal("replayed dead runtime", e)
	}
	t.Log("real Python child SIGKILL; SQL retains uncertain playback as UNKNOWN; no re-dispatch")
}
func TestPostgresOwnedConnectionDropRecovery(t *testing.T) {
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	conn, e := f.s.DB.Acquire(f.ctx)
	if e != nil {
		t.Fatal(e)
	}
	pid := conn.Conn().PgConn().PID()
	if _, e = f.s.DB.Exec(f.ctx, `SELECT pg_terminate_backend($1)`, pid); e != nil {
		t.Fatal(e)
	}
	if _, e = conn.Exec(f.ctx, `SELECT 1`); e == nil {
		t.Fatal("connection was not interrupted")
	}
	conn.Release()
	if e = f.s.DB.Ping(f.ctx); e != nil {
		t.Fatal(e)
	}
	f.tick()
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 1 {
		t.Fatal("durable work lost on reconnect", e)
	}
	t.Log(fmt.Sprintf("terminated only test-owned PostgreSQL connection PID=%d; pool reconnected; stable pending command retained", pid))
}

func TestPostgresIsolatedServerOutage(t *testing.T) {
	data := os.Getenv("DURABLE_LIVE_ISOLATED_PGDATA")
	if data == "" {
		t.Skip("owned cluster path required")
	}
	if !strings.HasPrefix(data, "/tmp/astralive-agent2-") {
		t.Fatal("refuse shared PostgreSQL")
	}
	if _, e := os.Stat(filepath.Join(data, "AGENT2_OWNED")); e != nil {
		t.Fatal("missing owned marker")
	}
	f := newFixture(t, true)
	f.claim(f.turn("OPERATOR", nil, nil))
	q := f.req("RestoreContentPlan", Object{})
	raw, _ := json.Marshal(q)
	if out, e := exec.Command("pg_ctl", "-D", data, "-m", "fast", "-w", "-t", "10", "stop").CombinedOutput(); e != nil {
		t.Fatalf("owned pg stop: %s", out)
	}
	restarted := false
	restart := func() {
		if restarted {
			return
		}
		out, e := exec.Command("pg_ctl", "-D", data, "-l", data+".log", "-o", "-h 127.0.0.1 -p 55462 -k /tmp", "-w", "-t", "10", "start").CombinedOutput()
		if e != nil {
			t.Fatalf("owned pg restart: %s", out)
		}
		restarted = true
	}
	defer restart()
	ctx, cancel := context.WithTimeout(f.ctx, 300*time.Millisecond)
	defer cancel()
	if _, e := f.s.Call(ctx, f.p, "RestoreContentPlan", raw); e == nil {
		t.Fatal("database outage incorrectly succeeded")
	}
	restart()
	f.tick()
	claims, e := f.s.ClaimBatch(f.ctx, f.p, 16)
	if e != nil || len(claims) != 1 {
		t.Fatal("pending command lost after service outage", e)
	}
	t.Log("isolated PostgreSQL server stopped/restarted; admission failed closed; persisted pending command recovered")
}

func TestProcessCommitThenGoSIGKILL(t *testing.T) {
	_ = testDB(t)
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	child := exec.Command(os.Args[0], "-test.run=^TestIsolatedBackendHelper$")
	child.Env = append(os.Environ(), "DURABLE_LIVE_HELPER_CONFIG="+path, "DURABLE_LIVE_HELPER_STAGE=commit")
	startOwned(t, child, path+".backend.log")
	waitPath(t, path+".ready", 15*time.Second)
	cfg := loadConfig(t, path)
	if e := child.Process.Kill(); e != nil {
		t.Fatal(e)
	}
	_ = child.Wait()
	startBackend(t, path)
	pool := testDB(t)
	var status string
	var marker *time.Time
	if e := pool.QueryRow(context.Background(), `SELECT status,send_started_at FROM dl05_outbox WHERE command_id=$1`, cfg.Command["commandId"]).Scan(&status, &marker); e != nil {
		t.Fatal(e)
	}
	if status != "PENDING" || marker != nil {
		t.Fatal("lost post-commit intent", status)
	}
	var n int
	if e := pool.QueryRow(context.Background(), `SELECT count(*) FROM utterances u JOIN dl05_attempts a ON a.utterance_id=u.id JOIN dl05_outbox o USING(command_id) WHERE o.command_id=$1`, cfg.Command["commandId"]).Scan(&n); e != nil || n != 1 {
		t.Fatal("non-atomic persistence", e)
	}
	t.Log("SIGKILL after SQL commit and before dispatch; restarted Go sees exactly one original PENDING intent + attempt + QUEUED utterance; no fabricated execute")
}
func TestProcessRealRuntimeLost202(t *testing.T) {
	python := os.Getenv("DURABLE_LIVE_TEST_PYTHON")
	if python == "" {
		t.Skip("isolated Python required")
	}
	_ = testDB(t)
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	startBackend(t, path)
	cfg := loadConfig(t, path)
	cfg.RuntimeHTTP = true
	if e := os.WriteFile(path, mustJSON(cfg), 0600); e != nil {
		t.Fatal(e)
	}
	runtime := exec.Command(python, "../../../scripts/durable-live/runtime_fault_probe.py", path)
	startOwned(t, runtime, filepath.Join(dir, "runtime.log"))
	waitPath(t, filepath.Join(dir, "runtime-url"), 15*time.Second)
	url, e := os.ReadFile(filepath.Join(dir, "runtime-url"))
	if e != nil {
		t.Fatal(e)
	}
	sender := HTTPSender{BaseURL: string(url), Token: cfg.ControlToken, Client: &http.Client{Timeout: 100 * time.Millisecond}}
	_, err := sender.Send(context.Background(), cfg.Command)
	if err == nil {
		t.Fatal("202 response was not lost")
	}
	waitPath(t, filepath.Join(dir, "playing"), 5*time.Second)
	pool := testDB(t)
	s := New(pool, []string{"test-sink"})
	c := Claimed{cfg.Intent, cfg.Command}
	if e = s.recordSend(context.Background(), cfg.Control, c, nil, err); e != nil {
		t.Fatal(e)
	}
	if e = (&Coordinator{s, cfg.Control, 32}).Tick(context.Background()); e != nil {
		t.Fatal(e)
	}
	// Even a duplicate transport request to the live Python object returns state;
	// its durable STARTED receipt cannot create a second task/effect.
	_, _ = sender.Send(context.Background(), cfg.Command)
	b, e := os.ReadFile(filepath.Join(dir, "effects"))
	if e != nil || len(strings.Fields(string(b))) != 1 {
		t.Fatal("lost 202 caused replay", e)
	}
	claims, e := s.ClaimBatch(context.Background(), cfg.Control, 16)
	if e != nil || len(claims) != 0 {
		t.Fatal("blind retransmission", e)
	}
	_ = os.WriteFile(filepath.Join(dir, "finish"), []byte("finish"), 0600)
	if e = runtime.Wait(); e != nil {
		t.Fatal("runtime probe failed", e)
	}
	t.Log("real Python v0.5 HTTP received command and played synthetic local sink; 202 delayed beyond Go timeout; SQL reconciliation and duplicate execute produced one effect")
}
