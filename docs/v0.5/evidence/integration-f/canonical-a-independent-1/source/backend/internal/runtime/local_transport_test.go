package runtime_test

import (
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/config"
	rt "astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptrace"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

func TestLegacyClientUnchanged(t *testing.T) {
	h, e := rt.NewLocal("http://legacy-runtime:8000", config.LocalTransport{Mode: "tcp", Fallback: "disabled"})
	if e != nil || h.Base != "http://legacy-runtime:8000" || h.Client.Transport != nil || h.Client.Timeout != 8*time.Second {
		t.Fatal(h, e)
	}
}
func TestActualRuntimeLocalLifecycle(t *testing.T) {
	python := os.Getenv("ASTRALIVE_IPC_TEST_PYTHON")
	if python == "" {
		t.Skip("set ASTRALIVE_IPC_TEST_PYTHON for real Python subprocess transport tests")
	}
	for _, mode := range []string{"tcp", "uds"} {
		t.Run(mode, func(t *testing.T) {
			if mode == "uds" && runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
				t.Skip("UDS unsupported")
			}
			// Canonical root avoids macOS /var and /tmp aliases; short path respects sun_path.
			tmp, _ := filepath.EvalSymlinks(os.TempDir())
			dir, e := os.MkdirTemp(tmp, "al-ipc-")
			if e != nil {
				t.Fatal(e)
			}
			defer os.RemoveAll(dir)
			os.Chmod(dir, 0700)
			tokenPath := filepath.Join(dir, "token")
			os.WriteFile(tokenPath, []byte(strings.Repeat("c", 40)), 0600)
			socketPath := filepath.Join(dir, "r.sock")
			ln, _ := net.Listen("tcp", "127.0.0.1:0")
			base := "http://" + ln.Addr().String()
			ln.Close()
			opts := config.LocalTransport{Mode: mode, SocketPath: socketPath, Fallback: "disabled"}
			h, e := rt.NewLocal(base, opts)
			if e != nil {
				t.Fatal(e)
			}
			transport := h.Client.Transport
			if transport == nil {
				transport = &http.Transport{Proxy: nil}
			}
			h.Client.Transport = userconfig.TokenTransport{Path: tokenPath, Base: transport}
			_, e = h.Health(context.Background())
			status, code := rt.MapError(e)
			if e == nil || status != 503 || code != "RUNTIME_UNAVAILABLE" {
				t.Fatal("pre-start", e)
			}
			cwd, _ := os.Getwd()
			root := filepath.Clean(filepath.Join(cwd, "../../.."))
			start := func() *exec.Cmd {
				cmd := exec.Command(python, "-m", "app.local_listener")
				cmd.Dir = root
				cmd.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "runtime")+string(os.PathListSeparator)+root, "SESSION_BINDINGS_ENABLED=false", "REDIS_URL=", "MOCK_LLM=true", "MOCK_TTS=true", "MOCK_AVATAR=true", "MOCK_MEDIA=true", "APP_ENV=development", "RUNTIME_CONTROL_TOKEN_FILE="+tokenPath, "ASTRALIVE_LOCAL_TRANSPORT="+mode, "ASTRALIVE_LOCAL_FALLBACK=disabled", "ASTRALIVE_RUNTIME_UDS_PATH="+socketPath, "AI_RUNTIME_URL="+base)
				cmd.Stdout = os.Stderr
				cmd.Stderr = os.Stderr
				if e := cmd.Start(); e != nil {
					t.Fatal(e)
				}
				return cmd
			}
			process := start()
			defer func() {
				if process != nil {
					process.Process.Kill()
					process.Wait()
				}
			}()
			ready := func() {
				deadline := time.Now().Add(10 * time.Second)
				for time.Now().Before(deadline) {
					if _, e := h.Health(context.Background()); e == nil {
						return
					}
					time.Sleep(30 * time.Millisecond)
				}
				t.Fatal("Runtime readiness timeout")
			}
			ready()
			// Token is reread on every request, including pooled connections.
			os.WriteFile(tokenPath, []byte(strings.Repeat("x", 40)), 0600)
			// Runtime uses same path, so a separate wrong client must authenticate with a distinct file.
			wrong := filepath.Join(dir, "wrong")
			os.WriteFile(wrong, []byte(strings.Repeat("z", 40)), 0600)
			h.Client.Transport = userconfig.TokenTransport{Path: wrong, Base: transport}
			_, e = h.Health(context.Background())
			status, code = rt.MapError(e)
			if status != 401 || code != "INVALID_ARGUMENT" {
				t.Fatal("token", status, code, e)
			}
			h.Client.Transport = userconfig.TokenTransport{Path: tokenPath, Base: transport}
			ready()
			// Same pooled Go client survives owned Runtime SIGKILL + stale-inode startup cleanup.
			process.Process.Kill()
			process.Wait()
			process = nil
			if _, e = h.Health(context.Background()); e == nil {
				t.Fatal("health after kill succeeded")
			}
			process = start()
			ready()
			// Valid control JSON reaches actual Runtime unchanged; no media work at missing Session.
			for _, n := range []int{1024, 10240, 102400} {
				_, e = h.Speak(context.Background(), "missing", map[string]any{"commandId": "cmd", "traceId": "trace", "utteranceId": "u", "text": strings.Repeat("x", n), "priority": 50, "source": "OPERATOR", "interruptPolicy": "NONE", "voice": map[string]any{"voiceId": "mock"}})
				status, code = rt.MapError(e)
				if status != 404 || code != "SESSION_NOT_FOUND" {
					t.Fatal(n, status, code, e)
				}
			}
			if runtime.GOOS == "windows" {
				process.Process.Kill()
			} else {
				process.Process.Signal(syscall.SIGTERM)
			}
			if e := process.Wait(); e != nil && runtime.GOOS != "windows" {
				t.Fatal("graceful stop", e)
			}
			process = nil
			if mode == "uds" {
				if _, e := os.Lstat(socketPath); !os.IsNotExist(e) {
					t.Fatal("socket remained after graceful stop", e)
				}
			}

			if c, ok := transport.(interface{ CloseIdleConnections() }); ok {
				defer c.CloseIdleConnections()
			}
		})
	}
}

func TestUDSSafetyAndHTTPParity(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		t.Skip("Unix-only filesystem security")
	}
	tmp, _ := filepath.EvalSymlinks(os.TempDir())
	dir, e := os.MkdirTemp(tmp, "al-ipc-")
	if e != nil {
		t.Fatal(e)
	}
	defer os.RemoveAll(dir)
	os.Chmod(dir, 0700)
	p := filepath.Join(dir, "r.sock")
	opts := config.LocalTransport{Mode: "uds", SocketPath: p, Fallback: "tcp"}
	os.Chmod(dir, 0777)
	if _, e := rt.NewLocal("http://127.0.0.1:1", opts); e == nil {
		t.Fatal("unsafe parent accepted")
	}
	os.Chmod(dir, 0700)
	h, e := rt.NewLocal("http://127.0.0.1:1", opts)
	if e != nil {
		t.Fatal(e)
	}
	os.WriteFile(p, []byte("preserve"), 0600)
	if _, e = h.Health(context.Background()); e == nil {
		t.Fatal("regular file accepted")
	}
	os.Remove(p)
	target := filepath.Join(dir, "target")
	os.WriteFile(target, []byte("preserve"), 0600)
	os.Symlink(target, p)
	if _, e = h.Health(context.Background()); e == nil {
		t.Fatal("symlink accepted")
	}
	os.Remove(p)
	ln, e := net.Listen("unix", p)
	if e != nil {
		t.Fatal(e)
	}
	os.Chmod(p, 0600)
	var requests atomic.Int32
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path == "/internal/v1/health" {
			w.Write([]byte(`{"status":"ok"}`))
			return
		}
		if strings.HasSuffix(r.URL.Path, "/webrtc/offer") {
			time.Sleep(25 * time.Millisecond)
			w.Write([]byte(`{"type":"answer","sdp":"answer"}`))
			return
		}
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		if body["traceId"] != "trace-exact" {
			t.Error("trace changed")
		}
		if body["redirect"] == true {
			w.Header().Set("Location", "http://127.0.0.1:1")
			w.WriteHeader(307)
			return
		}
		w.WriteHeader(202)
		w.Write([]byte(`{"accepted":true,"operationId":"op-exact"}`))
	})}
	go srv.Serve(ln)
	defer srv.Close()
	base := h.Client.Transport
	defer base.(interface{ CloseIdleConnections() }).CloseIdleConnections()
	os.Chmod(p, 0666)
	if _, e := h.Health(context.Background()); e == nil {
		t.Fatal("unsafe socket permission accepted")
	}
	os.Chmod(p, 0600)
	var reused bool
	ctx := httptrace.WithClientTrace(context.Background(), &httptrace.ClientTrace{GotConn: func(info httptrace.GotConnInfo) { reused = info.Reused }})
	if _, e = h.Health(ctx); e != nil {
		t.Fatal(e)
	}
	if _, e = h.Health(ctx); e != nil || !reused {
		t.Fatal("connection not reused", e)
	}
	body := map[string]any{"traceId": "trace-exact", "text": strings.Repeat("x", 100*1024)}
	if op, e := h.CreateSession(context.Background(), body); e != nil || op.OperationID != "op-exact" {
		t.Fatal(op, e)
	}
	body["redirect"] = true
	before := requests.Load()
	if _, e := h.CreateSession(context.Background(), body); e == nil || requests.Load() != before+1 {
		t.Fatal("redirect replay", e)
	}
	// No additional header deadline defeats the original WebRTC30s timeout clone.
	h.Client.Timeout = time.Millisecond
	if _, e := h.WebRTCOffer(context.Background(), "s", runtimeapi.WebRTCOffer{Type: runtimeapi.Offer, Sdp: "offer"}); e != nil {
		t.Fatal("WebRTC timeout changed", e)
	}
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	before = requests.Load()
	if _, e := h.Health(canceled); e == nil || requests.Load() != before {
		t.Fatal("cancel not preserved", e)
	}
	// A parent-directory replacement fails before any reconnect or TCP fallback.
	base.(interface{ CloseIdleConnections() }).CloseIdleConnections()
	original := dir + "-old"
	if e := os.Rename(dir, original); e != nil {
		t.Fatal(e)
	}
	defer os.RemoveAll(original)
	os.Mkdir(dir, 0700)
	if _, e := h.Health(context.Background()); e == nil {
		t.Fatal("parent replacement accepted")
	}
}
