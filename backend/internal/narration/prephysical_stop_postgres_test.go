package narration_test

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"astralive/backend/internal/app"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
)

// Production Go Stop/journal/Binding DELETE/event projection with real PG;
// the child's Provider packet is explicitly captured fixture and no media starts.
func TestPostgresPrephysicalFailedCreateStopProof(t *testing.T) {
	python := os.Getenv("DURABILITY_TEST_PYTHON")
	if python == "" {
		t.Skip("DURABILITY_TEST_PYTHON not set")
	}
	for _, scenario := range []string{"success", "delete_failure"} {
		t.Run(scenario, func(t *testing.T) {
			ctx, p, store, _ := setup(t)
			if _, err := p.Exec(ctx, `UPDATE live_sessions SET status='PREPARING' WHERE id='s'`); err != nil {
				t.Fatal(err)
			}
			tx, err := p.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			run, err := store.Current(ctx, tx, "s", false)
			if err != nil {
				t.Fatal(err)
			}
			payload := map[string]any{"expectedPreviousEpoch": 0, "featureFlags": map[string]any{"soulxStagingEnabled": true, "soulxStagingLimitsRevision": "staging-short-1", "soulxStagingShortGateSHA256": nil},
				"createSession": map[string]any{"commandId": "legacy-create", "traceId": "begin-trace", "sessionId": "s", "avatar": map[string]any{"avatarId": "a", "engine": "SOULX"}, "voice": map[string]any{"voiceId": "v", "provider": "xiaoya"}, "config": map[string]any{"fps": 30, "preview": map[string]any{"type": "WEBRTC"}}, "context": map[string]any{"roomId": "room", "systemPrompt": "fixture"}}}
			begin, err := store.Enqueue(ctx, tx, run, "BEGIN_RUN", "prephysical-begin", "begin-trace", "", payload)
			if err != nil {
				t.Fatal(err)
			}
			if err = tx.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			dir := t.TempDir()
			jf, bf, cf := filepath.Join(dir, "journal"), filepath.Join(dir, "binding"), filepath.Join(dir, "begin.json")
			raw, err := json.Marshal(begin)
			if err != nil {
				t.Fatal(err)
			}
			for path, data := range map[string][]byte{jf: []byte(strings.Repeat("j", 48)), bf: []byte(strings.Repeat("b", 48)), cf: raw} {
				if err = os.WriteFile(path, data, 0600); err != nil {
					t.Fatal(err)
				}
			}
			service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
			service.Durable = store
			cfg := &userconfig.Service{DB: p, IntegrationEnabled: true, WorkerTokenFile: bf}
			mux := http.NewServeMux()
			mux.Handle("/internal/v0.5/durability/", http.StripPrefix("/internal/v0.5/durability", httpapi.JournalRouter(store, jf)))
			bindingRoute := http.StripPrefix("/internal/v0.4", cfg.SessionInternalRouter())
			mux.Handle("/internal/v0.4/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if scenario == "delete_failure" && r.Method == http.MethodDelete {
					http.Error(w, "owned injected Binding HTTP failure", 503)
					return
				}
				bindingRoute.ServeHTTP(w, r)
			}))
			// Private test sequencing hook invokes production service.Stop, not a substitute
			// receiver. A separately verifies owner/foreign/Origin public-route admission.
			mux.HandleFunc("/fixture/admit-stop", func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("j", 48) {
					http.Error(w, "unauthorized", 401)
					return
				}
				var execution string
				var released bool
				if err := p.QueryRow(ctx, `SELECT i.execution_state,b.released_at IS NOT NULL FROM v05_inbox i JOIN session_provider_bindings b USING(session_id) WHERE i.command_id=$1`, begin.CommandID).Scan(&execution, &released); err != nil {
					t.Error(err)
					http.Error(w, "SQL proof missing", 500)
					return
				}
				if execution != "STARTED" || released != (scenario == "success") {
					t.Errorf("wrong pre-Stop observations: %s/%t", execution, released)
					http.Error(w, "proof mismatch", 500)
					return
				}
				if _, err := service.Stop(ctx, "s", "stop-trace"); err != nil {
					t.Error(err)
					http.Error(w, "production Stop rejected", 500)
					return
				}
				var command []byte
				if err := p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE session_id='s' AND command_type='STOP_SESSION'`).Scan(&command); err != nil {
					t.Error(err)
					http.Error(w, "Stop command missing", 500)
					return
				}
				w.Header().Set("Content-Type", "application/json")
				w.Write(command)
			})
			server := httptest.NewServer(mux)
			defer server.Close()
			root, err := filepath.Abs("../../..")
			if err != nil {
				t.Fatal(err)
			}
			child := exec.CommandContext(ctx, python, filepath.Join(root, "runtime/tests/prephysical_stop_pg.py"), server.URL, jf, bf, cf, scenario)
			child.Dir = root
			child.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "runtime")+string(os.PathListSeparator)+filepath.Join(root, "runtime/tests")+string(os.PathListSeparator)+root)
			output, err := child.CombinedOutput()
			t.Log(string(output))
			if err != nil {
				t.Fatal(err)
			}
			for i := 0; i < 10; i++ {
				applied, err := service.ApplyNextDurable(ctx)
				if err != nil {
					t.Fatal(err)
				}
				if !applied {
					break
				}
			}
			var status, runState, execution string
			var ended, terminal bool
			if err := p.QueryRow(ctx, `SELECT s.status,r.status,i.execution_state,EXISTS(SELECT 1 FROM v05_events WHERE session_id='s' AND event_type='SESSION_ENDED'),EXISTS(SELECT 1 FROM v05_receipts WHERE session_id='s' AND state='completed' AND evidence_type='control_cleanup') FROM live_sessions s JOIN v05_session_runs r ON r.session_id=s.id JOIN v05_inbox i ON i.session_id=s.id WHERE i.command_id=$1`, begin.CommandID).Scan(&status, &runState, &execution, &ended, &terminal); err != nil {
				t.Fatal(err)
			}
			if execution != "STARTED" {
				t.Fatal("original unknown BEGIN rewritten", execution)
			}
			if scenario == "success" {
				if status != "ENDED" || runState != "SEALED" || !ended || !terminal {
					t.Fatal("proved Stop not finalized", status, runState, ended, terminal)
				}
			} else {
				if status != "STOPPING" || ended || terminal {
					t.Fatal("failed Binding ACK fabricated terminal", status, ended, terminal)
				}
			}
		})
	}
}
