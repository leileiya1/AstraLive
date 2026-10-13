package narration_test

import (
	"context"
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
	"time"

	"astralive/backend/internal/app"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
)

func TestPostgresCapturedRetirementNativeCleanupAndFreshSession(t *testing.T) {
	python := os.Getenv("DURABILITY_TEST_PYTHON")
	if python == "" {
		t.Skip("DURABILITY_TEST_PYTHON not set")
	}
	for _, scenario := range []string{"price", "product", "cleanup_failure"} {
		t.Run(scenario, func(t *testing.T) {
			ctx, p, store, c := setup(t)
			if _, err := c.Start(ctx, "s", "start", plan()); err != nil {
				t.Fatal(err)
			}
			_, err := p.Exec(ctx, `INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES('p2','新商品','新商品说明。',888,'CNY',1,ARRAY['M']); INSERT INTO resource_owners VALUES('product','p2','tenant','user');`)
			if err != nil {
				t.Fatal(err)
			}
			if scenario == "price" {
				_, err = p.Exec(ctx, `UPDATE products SET price=100 WHERE id='p'`)
			} else {
				_, err = p.Exec(ctx, `UPDATE live_rooms SET active_product_id='p2' WHERE id='room'`)
			}
			if err != nil {
				t.Fatal(err)
			}
			if err = c.Drive(ctx, "s"); err != nil {
				t.Fatal(err)
			}
			var raw []byte
			if err = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE session_id='s' AND command_type='STOP_SESSION'`).Scan(&raw); err != nil {
				t.Fatal(err)
			}
			_, err = p.Exec(ctx, `INSERT INTO live_sessions(id,room_id,status) VALUES('s2','room','LIVE'); INSERT INTO resource_owners VALUES('session','s2','tenant','user'); INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) SELECT 's2','tenant','user','binding2',jsonb_build_object('activeProductId',active_product_id),'{}',clock_timestamp()+interval '1 hour' FROM live_rooms WHERE id='room'`)
			if err != nil {
				t.Fatal(err)
			}
			tx, err := p.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = store.InitialRun(ctx, tx, "s2"); err != nil {
				tx.Rollback(ctx)
				t.Fatal(err)
			}
			if err = tx.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			journalFile, bindingFile, commandFile := filepath.Join(t.TempDir(), "journal"), filepath.Join(t.TempDir(), "binding"), filepath.Join(t.TempDir(), "command.json")
			for name, value := range map[string][]byte{journalFile: []byte(strings.Repeat("j", 48)), bindingFile: []byte(strings.Repeat("b", 48)), commandFile: raw} {
				if err = os.WriteFile(name, value, 0600); err != nil {
					t.Fatal(err)
				}
			}
			cfg := &userconfig.Service{DB: p, IntegrationEnabled: true, WorkerTokenFile: bindingFile}
			service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
			service.Durable = store
			service.AttachNarration(c)
			// Production events can arrive before binding release and the final
			// control receipt. Deliberately process them during both gaps.
			checkPending := func() {
				deadline := time.Now().Add(150 * time.Millisecond)
				for time.Now().Before(deadline) {
					if _, er := service.ApplyNextDurable(ctx); er != nil {
						t.Error(er)
					}
					time.Sleep(10 * time.Millisecond)
				}
				var state, projection string
				if er := p.QueryRow(ctx, `SELECT se.status,n.state FROM live_sessions se JOIN v05_narrations n ON n.session_id=se.id WHERE se.id='s'`).Scan(&state, &projection); er != nil {
					t.Error(er)
				}
				if state != "STOPPING" || projection != "STOPPING" {
					t.Errorf("premature finalization: %s/%s", state, projection)
				}
			}
			mux := http.NewServeMux()
			journalRoute := http.StripPrefix("/internal/v0.5/durability", httpapi.JournalRouter(store, journalFile))
			mux.Handle("/internal/v0.5/durability/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/internal/v0.5/durability/receipts" {
					checkPending()
				}
				journalRoute.ServeHTTP(w, r)
			}))
			bindingRoute := http.StripPrefix("/internal/v0.4", cfg.SessionInternalRouter())
			mux.Handle("/internal/v0.4/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodDelete && strings.Contains(r.URL.Path, "/s/binding") {
					checkPending()
				}
				bindingRoute.ServeHTTP(w, r)
			}))
			server := httptest.NewServer(mux)
			defer server.Close()
			root, err := filepath.Abs("../../..")
			if err != nil {
				t.Fatal(err)
			}
			child := exec.CommandContext(ctx, python, filepath.Join(root, "runtime/tests/narration_lifecycle_pg.py"), server.URL, journalFile, bindingFile, commandFile, scenario)
			child.Dir = root
			child.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "runtime")+string(os.PathListSeparator)+filepath.Join(root, "runtime/tests")+string(os.PathListSeparator)+root)
			output, err := child.CombinedOutput()
			t.Log(string(output))
			if err != nil {
				t.Fatal(err)
			}
			var terminal, released bool
			if err = p.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_receipts WHERE session_id='s' AND state='completed' AND evidence_type='control_cleanup'),released_at IS NOT NULL FROM session_provider_bindings WHERE session_id='s'`).Scan(&terminal, &released); err != nil {
				t.Fatal(err)
			}
			if scenario == "cleanup_failure" {
				if terminal || released {
					t.Fatal("failed cleanup fabricated terminal/release", terminal, released)
				}
				var execution string
				if err = p.QueryRow(ctx, `SELECT execution_state FROM v05_inbox WHERE command_type='STOP_SESSION' AND session_id='s'`).Scan(&execution); err != nil {
					t.Fatal(err)
				}
				if execution != "STARTED" {
					t.Fatal(execution)
				}
				return
			}
			if !terminal || !released {
				t.Fatal("successful cleanup missing proof/release", terminal, released)
			}
			// The earlier attempt waits the A-owned one-second event backoff.
			time.Sleep(time.Second)
			for i := 0; i < 10; i++ {
				applied, er := service.ApplyNextDurable(context.Background())
				if er != nil {
					t.Fatal(er)
				}
				if !applied {
					break
				}
			}
			var state, run string
			if err = p.QueryRow(ctx, `SELECT se.status,r.status FROM live_sessions se JOIN v05_session_runs r ON r.session_id=se.id WHERE se.id='s'`).Scan(&state, &run); err != nil {
				t.Fatal(err)
			}
			if state != "ENDED" || run != "SEALED" {
				t.Fatal("old run not finalized", state, run)
			}
			d, err := c.Snapshot(ctx, "s")
			if err != nil || d.State != narration.Stopped || !d.StopBarrier {
				t.Fatal("narration not final", err, d.State)
			}
			fresh, err := c.Start(ctx, "s2", "fresh", plan())
			if err != nil {
				t.Fatal(err)
			}
			if fresh.Plan.SessionID != "s2" || fresh.Plan.ID == d.Plan.ID || len(fresh.Cursor.CompletedFacts) != 0 {
				t.Fatal("fresh session inherited old cursor")
			}
			if scenario != "price" && fresh.Plan.ProductID != "p2" {
				t.Fatal("fresh product wrong", fresh.Plan.ProductID)
			}
			var decoded map[string]any
			if err = json.Unmarshal(raw, &decoded); err != nil {
				t.Fatal(err)
			}
			if decoded["segmentId"] != nil || decoded["lane"] != "OPERATOR" {
				t.Fatal("Stop envelope mutated")
			}
		})
	}
}
