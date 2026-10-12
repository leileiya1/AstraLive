package durability_test

import (
	"astralive/backend/internal/config"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"golang.org/x/crypto/bcrypt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestLocalIPCProductionServerStartup(t *testing.T) {
	if os.Getenv("ASTRALIVE_IPC_TEST_PYTHON") == "" {
		t.Skip("explicit Python subprocess required")
	}
	for _, mode := range []string{"tcp", "uds"} {
		t.Run(mode, func(t *testing.T) { localIPCProductionServerStartup(t, mode) })
	}
}

// Actual cmd/server + production local listener + real PostgreSQL. Providers and
// media are the existing CPU fault fixture; this is no real inference acceptance.
func localIPCProductionServerStartup(t *testing.T, mode string) {
	ctx, p, store := pg(t)
	var schema string
	if e := p.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); e != nil {
		t.Fatal(e)
	}
	tmp, _ := filepath.EvalSymlinks(os.TempDir())
	dir, e := os.MkdirTemp(tmp, "al-d-")
	if e != nil {
		t.Fatal(e)
	}
	defer os.RemoveAll(dir)
	_ = os.Chmod(dir, 0700)
	socketPath := filepath.Join(dir, "r.sock")
	backend, e := filepath.Abs("../..")
	if e != nil {
		t.Fatal(e)
	}
	binary := filepath.Join(dir, "backend")
	build := exec.Command("go", "build", "-o", binary, "./cmd/server")
	build.Dir = backend
	if output, e := build.CombinedOutput(); e != nil {
		t.Fatalf("build %v %s", e, output)
	}
	file := func(name string, value any) string {
		path := filepath.Join(dir, name)
		var b []byte
		if str, ok := value.(string); ok {
			b = []byte(str)
		} else {
			b, _ = json.Marshal(value)
		}
		if e := os.WriteFile(path, b, 0600); e != nil {
			t.Fatal(e)
		}
		return path
	}
	keyring := file("keyring.json", map[string]any{"activeKeyId": "a", "keys": map[string]string{"a": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("k", 32)))}})
	password, e := bcrypt.GenerateFromPassword([]byte("synthetic-password"), 12)
	if e != nil {
		t.Fatal(e)
	}
	operator := file("operator.json", map[string]any{"username": "operator", "passwordHash": string(password), "scope": map[string]string{"tenantId": "tenant", "userId": "user"}})
	listener, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	addr := listener.Addr().String()
	listener.Close()
	controlFile := file("control.token", strings.Repeat("c", 48))
	journalFile := file("journal.token", strings.Repeat("j", 48))
	runtimeURL := "http://127.0.0.1:1"
	effects := filepath.Join(dir, "effects.log")
	var runtimeChild *exec.Cmd
	if python := os.Getenv("ASTRALIVE_IPC_TEST_PYTHON"); python != "" {
		runtimeListener, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			t.Fatal(e)
		}
		runtimeAddr := runtimeListener.Addr().(*net.TCPAddr)
		runtimeListener.Close()
		runtimeURL = "http://" + runtimeAddr.String()
		runtimeChild = exec.Command(python, "-m", "app.local_listener", "--app", "durability_cpu_server:app")
		repo := filepath.Dir(backend)
		runtimeChild.Dir = repo
		runtimeChild.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(repo, "runtime")+":"+filepath.Join(repo, "runtime/tests"), "ASTRALIVE_DURABILITY_ENABLED=true", "ASTRALIVE_EVENT_MODE=postgres_only", "SESSION_BINDINGS_ENABLED=false", "APP_ENV=development", "CONFIG_BACKEND_URL=http://"+addr, "RUNTIME_JOURNAL_TOKEN_FILE="+journalFile, "RUNTIME_CONTROL_TOKEN_FILE="+controlFile, "RUNTIME_EVENT_SPOOL_DIR="+filepath.Join(dir, "spool"), "DURABILITY_CPU_EFFECT_FILE="+effects, "REDIS_URL=redis://127.0.0.1:1", "ASTRALIVE_LOCAL_TRANSPORT="+mode, "ASTRALIVE_LOCAL_FALLBACK=disabled", "ASTRALIVE_RUNTIME_UDS_PATH="+socketPath, "AI_RUNTIME_URL="+runtimeURL, "ASTRALIVE_CONTINUITY_ENABLED=false", "ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED=false", "ASTRALIVE_MEDIA_TIMELINE_ENABLED=false")
		output, e := os.OpenFile(filepath.Join(dir, "runtime.log"), os.O_CREATE|os.O_WRONLY, 0600)
		if e != nil {
			t.Fatal(e)
		}
		defer output.Close()
		runtimeChild.Stdout = output
		runtimeChild.Stderr = output
		if e = runtimeChild.Start(); e != nil {
			t.Fatal(e)
		}
		defer func() {
			_ = runtimeChild.Process.Kill()
			_ = runtimeChild.Wait()
			if t.Failed() {
				raw, _ := os.ReadFile(output.Name())
				t.Log(string(raw))
			}
		}()
		rt, e := runtime.NewLocal(runtimeURL, config.LocalTransport{Mode: mode, SocketPath: socketPath, Fallback: "disabled"})
		if e != nil {
			t.Fatal(e)
		}
		base := rt.Client.Transport
		if base == nil {
			base = &http.Transport{Proxy: nil}
		}
		rt.Client.Transport = userconfig.TokenTransport{Path: controlFile, Base: base}
		eventually(t, 5*time.Second, func() bool { _, e := rt.Health(ctx); return e == nil })
		run(t, ctx, p, store, "s")
		_, e = p.Exec(ctx, `DELETE FROM v05_timeline_epochs;DELETE FROM v05_recovery_leases;DELETE FROM v05_session_runs;UPDATE live_sessions SET status='CREATED' WHERE id='s';UPDATE session_provider_bindings SET room_snapshot='{"roomId":"room","systemPrompt":"prompt"}' WHERE session_id='s'`)
		if e != nil {
			t.Fatal(e)
		}
	}
	// Deliberately invalid Redis URL: PostgreSQL-only must not even parse it.
	child := exec.Command(binary)
	child.Env = append(os.Environ(), "DATABASE_URL="+os.Getenv("DURABILITY_TEST_DATABASE_URL")+"&search_path="+schema, "HTTP_ADDR="+addr, "APP_ENV=development", "ASTRALIVE_DURABILITY_ENABLED=true", "ASTRALIVE_EVENT_MODE=postgres_only", "REDIS_URL=not-a-redis-url", "AI_RUNTIME_URL="+runtimeURL, "INTERNAL_API_TOKEN="+strings.Repeat("t", 48), "CONFIG_PUBLIC_ORIGIN=https://durability.example", "SESSION_BINDINGS_ENABLED=true", "AUTH_OPERATOR_FILE="+operator, "CONFIG_KEYRING_FILE="+keyring, "CONFIG_IDENTITY_TOKEN_FILE="+file("identity.token", strings.Repeat("i", 48)), "CONFIG_WORKER_TOKEN_FILE="+file("worker.token", strings.Repeat("w", 48)), "RUNTIME_CONTROL_TOKEN_FILE="+controlFile, "RUNTIME_JOURNAL_TOKEN_FILE="+journalFile, "ASTRALIVE_LOCAL_TRANSPORT="+mode, "ASTRALIVE_LOCAL_FALLBACK=disabled", "ASTRALIVE_RUNTIME_UDS_PATH="+socketPath, "ASTRALIVE_CONTINUITY_ENABLED=false", "ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED=false", "ASTRALIVE_MEDIA_TIMELINE_ENABLED=false")
	logfile, e := os.OpenFile(filepath.Join(dir, "server.log"), os.O_CREATE|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	defer logfile.Close()
	child.Stdout = logfile
	child.Stderr = logfile
	start := func() {
		if e := child.Start(); e != nil {
			t.Fatal(e)
		}
	}
	start()
	defer func() {
		if child.ProcessState == nil {
			_ = child.Process.Kill()
			_ = child.Wait()
		}
		if t.Failed() {
			b, _ := os.ReadFile(logfile.Name())
			t.Log(string(b))
		}
	}()
	eventually(t, 5*time.Second, func() bool {
		client := &http.Client{Timeout: 100 * time.Millisecond}
		res, e := client.Get("http://" + addr + "/health/ready")
		if e != nil {
			return false
		}
		res.Body.Close()
		return res.StatusCode == 200
	})
	cookie := strings.Repeat("a", 43)
	public := func(suffix, key string, body []byte) []byte {
		t.Helper()
		req, e := http.NewRequest("POST", "http://"+addr+"/api/v1/live-sessions/s/"+suffix, bytes.NewReader(body))
		if e != nil {
			t.Fatal(e)
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Origin", "https://durability.example")
		req.Header.Set("Idempotency-Key", key)
		req.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: cookie})
		response, e := http.DefaultClient.Do(req)
		if e != nil {
			t.Fatal(e)
		}
		defer response.Body.Close()
		raw, _ := io.ReadAll(response.Body)
		if response.StatusCode != 202 {
			t.Fatalf("%s status %d %s", suffix, response.StatusCode, raw)
		}
		return raw
	}
	speakBody := []byte(`{"text":"Go restart CPU","priority":40,"interruptPolicy":"NONE","source":"OPERATOR"}`)
	var firstResponse []byte
	if runtimeChild != nil {
		hash := sha256.Sum256([]byte(cookie))
		_, e = p.Exec(ctx, `INSERT INTO config_auth_sessions(token_hash,tenant_id,user_id,expires_at) VALUES($1,'tenant','user',clock_timestamp()+interval '1 hour')`, hex.EncodeToString(hash[:]))
		if e != nil {
			t.Fatal(e)
		}
		_ = public("start", "start", []byte(`{}`))
		eventually(t, 5*time.Second, func() bool {
			var state string
			_ = p.QueryRow(ctx, `SELECT status FROM live_sessions WHERE id='s'`).Scan(&state)
			return state == "LIVE"
		})
		firstResponse = public("utterances", "speak", speakBody)
		eventually(t, 5*time.Second, func() bool { raw, _ := os.ReadFile(effects); return len(raw) > 0 })
	}
	_ = child.Process.Kill()
	_ = child.Wait()
	if runtimeChild != nil {
		time.Sleep(400 * time.Millisecond)
	}
	// Restart the actual cmd/server binary against the same migrated PostgreSQL.
	replacement := exec.Command(binary)
	replacement.Env = child.Env
	replacement.Stdout = logfile
	replacement.Stderr = logfile
	child = replacement
	start()
	eventually(t, 5*time.Second, func() bool {
		res, e := http.Get("http://" + addr + "/health/ready")
		if e != nil {
			return false
		}
		res.Body.Close()
		return res.StatusCode == 200
	})
	if runtimeChild != nil {
		repeated := public("utterances", "speak", speakBody)
		var original, replay any
		_ = json.Unmarshal(firstResponse, &original)
		_ = json.Unmarshal(repeated, &replay)
		if !reflect.DeepEqual(original, replay) {
			t.Fatal("HTTP idempotency result changed after Go restart")
		}
		var count int
		_ = p.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id='s'`).Scan(&count)
		if count != 1 {
			t.Fatal("Go restart duplicated logical speech", count)
		}
		_ = public("stop", "stop", []byte(`{}`))
		eventually(t, 5*time.Second, func() bool {
			var state string
			_ = p.QueryRow(ctx, `SELECT status FROM live_sessions WHERE id='s'`).Scan(&state)
			return state == "ENDED"
		})
		raw, _ := os.ReadFile(effects)
		zero := 0
		for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
			fields := strings.Fields(line)
			if len(fields) >= 3 && fields[2] == "0" {
				zero++
			}
		}
		if zero != 1 {
			t.Fatalf("synthetic media attempt restarted %d times", zero)
		}
		var warnings int
		_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_events WHERE event_type='RUNTIME_WARNING' AND processing_state='APPLIED'`).Scan(&warnings)
		if warnings == 0 {
			t.Fatal("surviving Runtime event journal did not flush")
		}
		t.Log("actual Go SIGKILL/restart, same Runtime PID: HTTP idempotency stable; one logical utterance; one synthetic sequence start; Stop ended; PostgreSQL event spool flushed")
	}
	t.Log("actual cmd/server local transport", mode, "PG-only, idempotency/restart/Stop PASS; synthetic providers only")
}
