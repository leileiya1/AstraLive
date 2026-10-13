package userconfig

import (
	"context"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Transport/probe protocol fixture only: the response is synthetic and is not a
// real TTS provider verification. Both protected secondary request paths reuse
// the captured dialer and reread the outer control token.
func TestCapturedLocalProviderTransport(t *testing.T) {
	for _, mode := range []string{"tcp", "uds"} {
		t.Run(mode, func(t *testing.T) {
			if mode == "uds" && runtime.GOOS != "darwin" && runtime.GOOS != "linux" {
				t.Skip("Unix only")
			}
			tmp, _ := filepath.EvalSymlinks(os.TempDir())
			dir, e := os.MkdirTemp(tmp, "al-probe-")
			if e != nil {
				t.Fatal(e)
			}
			defer os.RemoveAll(dir)
			os.Chmod(dir, 0700)
			socketPath := filepath.Join(dir, "r.sock")
			tokenPath := filepath.Join(dir, "token")
			os.WriteFile(tokenPath, []byte(strings.Repeat("c", 48)), 0600)
			network, address := "tcp", "127.0.0.1:0"
			if mode == "uds" {
				network, address = "unix", socketPath
			}
			listener, e := net.Listen(network, address)
			if e != nil {
				t.Fatal(e)
			}
			if mode == "uds" {
				os.Chmod(socketPath, 0600)
			}
			var requests atomic.Int32
			server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				token, _ := os.ReadFile(tokenPath)
				if r.Header.Get("Authorization") != "Bearer "+string(token) {
					w.WriteHeader(401)
					return
				}
				if r.URL.Path == "/internal/v0.4/provider-probes/tts" {
					if r.Method != "POST" {
						t.Error("probe method")
					}
					body, _ := io.ReadAll(r.Body)
					if string(body) != `{"voiceId":"x"}` {
						t.Error("probe JSON changed")
					}
					w.Write([]byte(`{"real":true,"provider":"xiaoya","sampleRate":22050,"samples":4000}`))
					return
				}
				w.Write([]byte(`{"status":"protocol-fixture"}`))
			})}
			go server.Serve(listener)
			defer server.Close()
			base := "http://127.0.0.1:1"
			if mode == "tcp" {
				base = "http://" + listener.Addr().String()
			}
			t.Setenv("ASTRALIVE_LOCAL_TRANSPORT", mode)
			t.Setenv("ASTRALIVE_RUNTIME_UDS_PATH", socketPath)
			t.Setenv("ASTRALIVE_LOCAL_FALLBACK", "disabled")
			s := &Service{RuntimeStatusURL: base, RuntimeControlTokenFile: tokenPath}
			if e = s.captureLocalRuntimeTransport(); e != nil {
				t.Fatal(e)
			}
			// Environment changes never move a live service to a different endpoint.
			t.Setenv("ASTRALIVE_LOCAL_TRANSPORT", "tcp")
			t.Setenv("ASTRALIVE_RUNTIME_UDS_PATH", "/missing")
			if e = s.probeTTS(context.Background(), Profile{Config: []byte(`{"voiceId":"x"}`)}); e != nil {
				t.Fatal(e)
			}
			os.WriteFile(tokenPath, []byte(strings.Repeat("n", 48)), 0600)
			client, e := s.localRuntimeHTTP(3 * time.Second)
			if e != nil {
				t.Fatal(e)
			}
			defer client.CloseIdleConnections()
			request, _ := http.NewRequest("GET", base+"/internal/v0.4/sessions/s/providers", nil)
			response, e := client.Do(request)
			if e != nil {
				t.Fatal(e)
			}
			response.Body.Close()
			if response.StatusCode != 200 {
				t.Fatal("rotation/status", response.StatusCode)
			}
			before := requests.Load()
			canceled, cancel := context.WithCancel(context.Background())
			cancel()
			if e = s.probeTTS(canceled, Profile{Config: []byte(`{"voiceId":"x"}`)}); e == nil || requests.Load() != before {
				t.Fatal("cancellation lost or POST replay")
			}
		})
	}
}
