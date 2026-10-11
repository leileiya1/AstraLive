package narration_test

import (
	"astralive/backend/db"
	"astralive/backend/internal/app"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/platform"
	"astralive/backend/internal/recovery"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// A real isolated PostgreSQL schema and authenticated journal; media in the
// child process is explicitly a synthetic sink fixture, not audience playback.
func setup(t *testing.T) (context.Context, *pgxpool.Pool, *durability.Store, *narration.Controller) {
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
	schema := ids.New("narration_test")
	if _, e = base.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); e != nil {
		t.Fatal(e)
	}
	cfg, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	p, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		p.Close()
		base.Exec(ctx, "DROP SCHEMA "+pgx.Identifier{schema}.Sanitize()+" CASCADE")
		base.Close()
	})
	if e = db.Migrate(ctx, p); e != nil {
		t.Fatal(e)
	}
	_, e = p.Exec(ctx, `INSERT INTO config_principals VALUES('tenant','user');
 INSERT INTO avatars(id,name,engine) VALUES('a','avatar','MOCK');INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('v','voice','MOCK','mock');
 INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES('p','测试商品','水箱容量五升。',99,'CNY',20,ARRAY['XL']);
 INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt,active_product_id) VALUES('room','room','a','v','自然讲解','p');
 INSERT INTO resource_owners VALUES('room','room','tenant','user'),('product','p','tenant','user');
 INSERT INTO live_sessions(id,room_id,status) VALUES('s','room','LIVE');INSERT INTO resource_owners VALUES('session','s','tenant','user');
 INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES('s','tenant','user','binding','{"activeProductId":"p"}','{}',clock_timestamp()+interval '1 hour');`)
	if e != nil {
		t.Fatal(e)
	}
	s := durability.New(p)
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.InitialRun(ctx, tx, "s")
	if e != nil {
		tx.Rollback(ctx)
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	c := narration.New(s)
	service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = s
	service.AttachNarration(c)
	return ctx, p, s, c
}
func plan() narration.StartRequest {
	return narration.StartRequest{RequestID: "request1", ScriptVersion: "script1", RequiredSinks: []string{"fixture"}, Policy: narration.AtBoundary, Style: "自然亲切", Beats: []narration.BeatInput{
		{Title: "商品定位", RequiredFactIDs: []string{"name"}, Statements: []narration.Statement{{Text: "这款是{{name}}。", FactIDs: []string{"name"}}}},
		{Title: "水箱容量", RequiredFactIDs: []string{"description"}, Statements: []narration.Statement{{Text: "{{description}}", FactIDs: []string{"description"}}}},
		{Title: "购买说明", RequiredFactIDs: []string{"price"}, Statements: []narration.Statement{{Text: "这款目前价格是 {{price}} CNY。", FactIDs: []string{"price"}}}},
	}}
}
func TestPostgresStartAtomicFingerprintProductStop(t *testing.T) {
	ctx, p, s, c := setup(t)
	input := plan()
	d, e := c.Start(ctx, "s", "trace", input)
	if e != nil {
		t.Fatal(e)
	}
	var n int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='COMMIT_SEGMENT'`).Scan(&n)
	if n != 1 {
		t.Fatal("missing atomic next command", n)
	}
	again, e := c.Start(ctx, "s", "trace2", plan())
	if e != nil || again.Plan.ID != d.Plan.ID {
		t.Fatal("replay", e)
	}
	changed := plan()
	changed.Beats[0].Title = "changed"
	if _, e = c.Start(ctx, "s", "trace", changed); e == nil {
		t.Fatal("idempotency key changed content")
	}
	_, e = p.Exec(ctx, `UPDATE products SET price=101 WHERE id='p'`)
	if e != nil {
		t.Fatal(e)
	}
	if e = c.Drive(ctx, "s"); e != nil {
		t.Fatal(e)
	}
	snap, e := c.Snapshot(ctx, "s")
	if e != nil || snap.State != narration.Stopping || !snap.StopBarrier || snap.Cursor.NextOrdinal != 0 {
		t.Fatal("stale price admitted", e, snap.State)
	}
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='STOP_SESSION' AND delivery_state='PENDING' AND payload_envelope->'segmentId'='null'::jsonb AND lane='OPERATOR'`).Scan(&n)
	if n != 1 {
		t.Fatal("product change has no durable media stop", n)
	}
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='COMMIT_SEGMENT' AND delivery_state='CANCELLED'`).Scan(&n)
	if n != 1 {
		t.Fatal("old price media remains eligible", n)
	}
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	run, e := s.Current(ctx, tx, "s", true)
	if e != nil {
		t.Fatal(e)
	}
	if e = c.Control(ctx, tx, run, "STOP_SESSION"); e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	if e = c.Drive(ctx, "s"); e == nil {
		t.Fatal("ghost resume after stop")
	}
}

func TestPostgresProductSwitchRetiresCapturedPlan(t *testing.T) {
	ctx, p, _, c := setup(t)
	if _, e := c.Start(ctx, "s", "trace", plan()); e != nil {
		t.Fatal(e)
	}
	if _, e := p.Exec(ctx, `INSERT INTO products(id,name,description,price,currency,stock,sizes) VALUES('product-B','商品B','另一商品。',999,'CNY',1,ARRAY['M']); INSERT INTO resource_owners VALUES('product','product-B','tenant','user'); UPDATE live_rooms SET active_product_id='product-B' WHERE id='room'`); e != nil {
		t.Fatal(e)
	}
	if e := c.Drive(ctx, "s"); e != nil {
		t.Fatal(e)
	}
	d, e := c.Snapshot(ctx, "s")
	if e != nil || !d.StopBarrier || d.State != narration.Stopping || len(d.Cursor.CompletedFacts) != 0 {
		t.Fatal("old binding survived product switch", e, d.State)
	}
	var sessionState, runState string
	_ = p.QueryRow(ctx, `SELECT status FROM live_sessions WHERE id='s'`).Scan(&sessionState)
	_ = p.QueryRow(ctx, `SELECT status FROM v05_session_runs WHERE session_id='s'`).Scan(&runState)
	if sessionState != "STOPPING" || runState != "STOPPING" {
		t.Fatal("old Session lifecycle was not stopped", sessionState, runState)
	}
	var answers int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type IN ('START_AUDIENCE_ANSWER','PREPARE_RESUME_BRIDGE')`).Scan(&answers)
	if answers != 0 {
		t.Fatal("old product answer admitted")
	}
	if _, e = c.Start(ctx, "s", "trace", plan()); e == nil {
		t.Fatal("new product reused old captured Session")
	}
}

func TestPostgresAuthenticatedPublicForceRejectsLegacyAndStopsResume(t *testing.T) {
	for _, phase := range []string{"BEFORE_FIRST_COMMAND", "NARRATING", "ANSWERING", "FINISHED", "CANCELLED", "EXPIRED_LEASE"} {
		t.Run(phase, func(t *testing.T) {
			ctx, p, store, c := setup(t)
			cfg := &userconfig.Service{DB: p, IntegrationEnabled: true, Origin: "https://continuity.example"}
			cookie, e := cfg.IssueSession(ctx, userconfig.Scope{TenantID: "tenant", UserID: "user"})
			if e != nil {
				t.Fatal(e)
			}
			service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
			service.Durable = store
			service.AttachNarration(c)
			service.Integration = cfg
			h := (&httpapi.Server{S: service, Config: cfg, Env: "development", Log: service.Log}).Router()
			call := func(token, origin, policy string) int {
				req := httptest.NewRequest("POST", "/api/v1/live-sessions/s/utterances", strings.NewReader(`{"text":"人工操作","priority":99,"interruptPolicy":"`+policy+`","source":"OPERATOR"}`))
				req.Header.Set("Idempotency-Key", ids.New("request"))
				req.Header.Set("Content-Type", "application/json")
				req.Header.Set("Origin", origin)
				if token != "" {
					req.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: token})
				}
				w := httptest.NewRecorder()
				h.ServeHTTP(w, req)
				return w.Code
			}
			if code := call("", cfg.Origin, "FORCE"); code != 401 {
				t.Fatal("missing auth accepted", code)
			}
			if code := call(cookie, "https://wrong.example", "FORCE"); code != 403 {
				t.Fatal("origin bypass", code)
			}
			other, e := cfg.IssueSession(ctx, userconfig.Scope{TenantID: "tenant", UserID: "other"})
			if e != nil {
				t.Fatal(e)
			}
			if code := call(other, cfg.Origin, "FORCE"); code != 404 {
				t.Fatal("cross user accepted", code)
			}
			if phase != "BEFORE_FIRST_COMMAND" {
				d, e := c.Start(ctx, "s", "trace", plan())
				if e != nil {
					t.Fatal(e)
				}
				d.Revision++
				// Explicit state fixture checks public authorization/barriers, not playback.
				switch phase {
				case "NARRATING", "EXPIRED_LEASE":
					d.State = narration.Narrating
					d.Plan.Segments[0].Status = "EXECUTING"
				case "ANSWERING":
					d.State = narration.Answering
					d.Turn = &narration.Turn{ID: "turn-fixture", Status: "ANSWERING"}
				case "FINISHED":
					d.State = narration.Stopped
					d.StopBarrier = true
					d.Reason = "FINISHED"
				case "CANCELLED":
					d.State = narration.RecoveryRequired
					d.OperatorOverride = true
				}
				raw, _ := json.Marshal(d)
				_, e = p.Exec(ctx, `UPDATE v05_narrations SET state=$1,revision=$2,document_json=$3,stop_barrier=$4 WHERE session_id='s'`, d.State, d.Revision, raw, d.StopBarrier)
				if e != nil {
					t.Fatal(e)
				}
			}
			if code := call(cookie, cfg.Origin, "NONE"); code != 409 {
				t.Fatal("bound run accepted untimed ordinary speech", code)
			}
			if phase == "EXPIRED_LEASE" {
				_, e = p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second'`)
				if e != nil {
					t.Fatal(e)
				}
			}
			if code := call(cookie, cfg.Origin, "FORCE"); (phase == "EXPIRED_LEASE" && code < 400) || (phase != "EXPIRED_LEASE" && code != 202) {
				t.Fatal("wrong failed FORCE disposition", code)
			}
			var speak int
			_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='SPEAK'`).Scan(&speak)
			if speak != 0 {
				t.Fatal("legacy generation enqueued")
			}
			var barriers int
			_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='FORCE_INTERRUPT'`).Scan(&barriers)
			if phase != "EXPIRED_LEASE" && barriers != 1 {
				t.Fatal("FORCE failed to persist override", barriers)
			}
			if phase != "EXPIRED_LEASE" {
				var status, reason string
				e = p.QueryRow(ctx, `SELECT status,failure_code FROM utterances WHERE session_id='s'`).Scan(&status, &reason)
				if e != nil || status != "FAILED" || reason != "DEPENDENCY_UNAVAILABLE" {
					t.Fatal("fake queued/speech success", status, reason, e)
				}
			}
			if phase != "BEFORE_FIRST_COMMAND" {
				if e = c.Drive(ctx, "s"); e == nil {
					t.Fatal("ghost resume")
				}
			}
		})
	}
}

func TestPostgresFailedForceIdempotencyRollbackAndStop(t *testing.T) {
	for _, scenario := range []string{"idempotent", "rollback", "stop"} {
		t.Run(scenario, func(t *testing.T) {
			ctx, p, store, c := setup(t)
			_, e := c.Start(ctx, "s", "trace", plan())
			if e != nil {
				t.Fatal(e)
			}
			cfg := &userconfig.Service{DB: p, IntegrationEnabled: true, Origin: "https://continuity.example"}
			cookie, e := cfg.IssueSession(ctx, userconfig.Scope{TenantID: "tenant", UserID: "user"})
			if e != nil {
				t.Fatal(e)
			}
			service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
			service.Durable = store
			service.AttachNarration(c)
			service.Integration = cfg
			h := (&httpapi.Server{S: service, Config: cfg, Env: "development", Log: service.Log}).Router()
			call := func(text string) (int, []byte) {
				req := httptest.NewRequest("POST", "/api/v1/live-sessions/s/utterances", strings.NewReader(`{"text":"`+text+`","priority":99,"interruptPolicy":"FORCE","source":"OPERATOR"}`))
				req.Header.Set("Content-Type", "application/json")
				req.Header.Set("Origin", cfg.Origin)
				req.Header.Set("Idempotency-Key", "same-request")
				req.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: cookie})
				w := httptest.NewRecorder()
				h.ServeHTTP(w, req)
				return w.Code, w.Body.Bytes()
			}
			if scenario == "rollback" {
				_, e = p.Exec(ctx, `CREATE FUNCTION fail_response_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture response rollback' USING ERRCODE='23514'; END $$; CREATE TRIGGER response_fixture BEFORE INSERT ON idempotency_keys FOR EACH ROW EXECUTE FUNCTION fail_response_fixture()`)
				if e != nil {
					t.Fatal(e)
				}
			}
			if scenario == "stop" {
				if _, e = service.Stop(ctx, "s", "stop-trace"); e != nil {
					t.Fatal(e)
				}
			}
			code, raw := call("人工操作")
			if scenario == "idempotent" {
				if code != 202 || !bytes.Contains(raw, []byte(`"status":"FAILED"`)) {
					t.Fatal("missing explicit failure result", code, string(raw))
				}
				again, body := call("人工操作")
				var first, second any
				json.Unmarshal(raw, &first)
				json.Unmarshal(body, &second)
				a, _ := json.Marshal(first)
				b, _ := json.Marshal(second)
				if again != 202 || !bytes.Equal(a, b) {
					t.Fatal("retry changed result", again)
				}
				if code, _ = call("改变正文"); code != 409 {
					t.Fatal("same key changed body", code)
				}
				_, e = p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second'`)
				if e != nil {
					t.Fatal(e)
				}
				if code, _ = call("人工操作"); code < 400 {
					t.Fatal("expired authority served cached acceptance", code)
				}
			} else if code < 400 {
				t.Fatal("partial/stop request accepted", scenario, code)
			}
			var force, utterances int
			_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='FORCE_INTERRUPT'`).Scan(&force)
			_ = p.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id='s'`).Scan(&utterances)
			want := 0
			if scenario == "idempotent" {
				want = 1
			}
			if force != want || utterances != want {
				t.Fatal("non-atomic/duplicate request", force, utterances, want)
			}
			if scenario == "rollback" {
				d, e := c.Snapshot(ctx, "s")
				if e != nil || d.State != narration.Planning || d.OperatorOverride {
					t.Fatal("rollback changed business state", d.State, e)
				}
			}
		})
	}
}

func TestPostgresPythonTimelineQuestionBridgeResume(t *testing.T) {
	runPython(t, "")
}
func TestPostgresNativeChromeRTMPContinuity(t *testing.T) {
	if os.Getenv("NARRATION_REAL_SINKS") != "true" {
		t.Skip("NARRATION_REAL_SINKS=true required")
	}
	runPython(t, "MEDIA")
}
func TestPostgresTenMinuteFiveQuestions(t *testing.T) {
	if os.Getenv("NARRATION_REAL_SINKS") != "true" || os.Getenv("NARRATION_TEN_MINUTE") != "true" {
		t.Skip("NARRATION_REAL_SINKS=true and NARRATION_TEN_MINUTE=true required")
	}
	if deadline, ok := t.Deadline(); ok && time.Until(deadline) < 12*time.Minute {
		t.Fatal("ten-minute source plus answers/bridges requires go test -timeout=20m")
	}
	runPython(t, "MEDIA_SOAK")
}
func TestPostgresSIGKILLFiveContinuityWindows(t *testing.T) {
	for _, phase := range []string{"SUSPEND_PENDING", "SUSPENDED", "ANSWER_PREPARING", "ANSWERING", "RESUME_PREPARING"} {
		t.Run(phase, func(t *testing.T) { runPython(t, phase) })
	}
}
func TestPostgresExpiredSelectedQuestionResumesWithoutAnswer(t *testing.T) {
	runPython(t, "EXPIRED")
}
func runPython(t *testing.T, phase string) {
	ctx, p, s, c := setup(t)
	media := phase == "MEDIA" || phase == "MEDIA_SOAK"
	count := 3
	if phase == "MEDIA" {
		count = 20
	} else if phase == "MEDIA_SOAK" {
		count = 200
	}
	workerCtx, cancelWorker := context.WithCancel(ctx)
	defer cancelWorker()
	service := app.New(p, runtime.New("http://127.0.0.1:1"), slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = s
	service.AttachNarration(c)
	cfg := &userconfig.Service{DB: p, IntegrationEnabled: true}
	settings := interaction.DefaultConfig()
	settings.TTL = time.Minute
	if phase == "EXPIRED" {
		settings.TTL = 300 * time.Millisecond
	}
	service.Interaction = app.NewInteraction(workerCtx, service, cfg, settings)
	python := os.Getenv("NARRATION_TEST_PYTHON")
	if python == "" {
		t.Skip("NARRATION_TEST_PYTHON not set")
	}
	var e error
	if !media {
		_, e = c.Start(ctx, "s", "trace", plan())
		if e != nil {
			t.Fatal(e)
		}
	}
	tokenFile := filepath.Join(t.TempDir(), "journal.token")
	if e = os.WriteFile(tokenFile, []byte("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), 0600); e != nil {
		t.Fatal(e)
	}
	mux := http.NewServeMux()
	mux.Handle("/internal/v0.5/durability/", http.StripPrefix("/internal/v0.5/durability", httpapi.JournalRouter(s, tokenFile)))
	var mu sync.Mutex
	claims := map[string]durability.Claim{}
	reply := func(w http.ResponseWriter, v any, e error) {
		if e != nil {
			http.Error(w, e.Error(), 409)
			return
		}
		json.NewEncoder(w).Encode(v)
	}
	mux.HandleFunc("/fixture/next", func(w http.ResponseWriter, r *http.Request) {
		s.Renew(ctx)
		_ = c.Drive(ctx, "s")
		claim, e := s.Claim(ctx)
		if e == pgx.ErrNoRows {
			w.WriteHeader(204)
			return
		}
		if e != nil {
			reply(w, nil, e)
			return
		}
		mu.Lock()
		claims[claim.Command.CommandID] = claim
		mu.Unlock()
		reply(w, claim.Command, nil)
	})
	mux.HandleFunc("/fixture/ack", func(w http.ResponseWriter, r *http.Request) {
		var x struct {
			ID string `json:"commandId"`
		}
		json.NewDecoder(r.Body).Decode(&x)
		mu.Lock()
		claim := claims[x.ID]
		mu.Unlock()
		reply(w, map[string]bool{"acked": true}, s.Finish(ctx, claim, "ACKED", "", 0))
	})
	mux.HandleFunc("/fixture/select", func(w http.ResponseWriter, r *http.Request) {
		question := r.URL.Query().Get("question")
		if question == "" {
			question = "多少钱？"
		}
		now := time.Now()
		scheduler, e := service.Interaction.Ensure(ctx, userconfig.Scope{TenantID: "tenant", UserID: "user"}, "s")
		if e != nil {
			reply(w, nil, e)
			return
		}
		eventID := ids.New("comment")
		e = scheduler.Receive(ctx, platform.Event{SourceEventID: eventID, SessionID: "s", InternalRoomID: "room", PlatformRoomID: "room", Platform: "mock", EventType: platform.Comment, Transport: "MOCK_REPLAY", UserExternalID: eventID, ReceivedAt: now, Content: question})
		if e == nil {
			e = scheduler.Tick(ctx)
		}
		reply(w, map[string]any{"accepted": true, "scheduler": scheduler.Snapshot()}, e)
	})
	mux.HandleFunc("/fixture/snapshot", func(w http.ResponseWriter, r *http.Request) {
		var raw json.RawMessage
		e := p.QueryRow(ctx, `SELECT document_json FROM v05_narrations WHERE session_id='s' ORDER BY updated_at DESC LIMIT 1`).Scan(&raw)
		reply(w, raw, e)
	})
	mux.HandleFunc("/fixture/start", func(w http.ResponseWriter, r *http.Request) {
		var sinks []string
		if e := json.NewDecoder(r.Body).Decode(&sinks); e != nil {
			reply(w, nil, e)
			return
		}
		x := plan()
		x.RequiredSinks = sinks
		if media {
			price := x.Beats[2]
			x.Beats = x.Beats[:2]
			for i := 2; i < count-1; i++ {
				fact := fmt.Sprintf("authored-fixture-step-%d", i)
				x.Beats = append(x.Beats, narration.BeatInput{Title: fmt.Sprintf("使用步骤%d", i), RequiredFactIDs: []string{fact}, Statements: []narration.Statement{{Text: fmt.Sprintf("这段说明介绍第%d个独立使用步骤。", i), FactIDs: []string{fact}}}})
			}
			x.Beats = append(x.Beats, price)
		}
		d, e := c.Start(ctx, "s", "trace", x)
		reply(w, d, e)
	})
	server := httptest.NewServer(mux)
	defer server.Close()
	root, e := filepath.Abs("../../..")
	if e != nil {
		t.Fatal(e)
	}
	cmd := exec.Command(python, filepath.Join(root, "runtime/tests/narration_pg_fixture.py"), server.URL, tokenFile)
	if phase != "" {
		cmd.Args = append(cmd.Args, phase)
	}
	if media {
		evidence := os.Getenv("NARRATION_MEDIA_EVIDENCE_DIR")
		if evidence == "" {
			evidence = t.TempDir()
		}
		cmd.Args = append(cmd.Args, evidence)
	}
	cmd.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "runtime")+string(os.PathListSeparator)+root)
	if phase != "" && !media && phase != "EXPIRED" {
		var stderr bytes.Buffer
		cmd.Stderr = &stderr
		stdout, e := cmd.StdoutPipe()
		if e != nil {
			t.Fatal(e)
		}
		if e = cmd.Start(); e != nil {
			t.Fatal(e)
		}
		ready := make(chan string, 1)
		go func() { line, _ := bufio.NewReader(stdout).ReadString('\n'); ready <- line }()
		select {
		case line := <-ready:
			if line != "KILL_READY:"+phase+"\n" {
				cmd.Process.Kill()
				cmd.Wait()
				t.Fatalf("not at crash phase: %q %s", line, stderr.String())
			}
		case <-time.After(10 * time.Second):
			cmd.Process.Kill()
			cmd.Wait()
			t.Fatal("crash phase timeout", stderr.String())
		}
		var before []byte
		var crashState string
		_ = p.QueryRow(ctx, `SELECT state FROM v05_narrations WHERE session_id='s'`).Scan(&crashState)
		expectedState := map[string]string{"SUSPEND_PENDING": "SUSPEND_REQUESTED", "SUSPENDED": "SUSPENDED", "ANSWER_PREPARING": "SUSPENDED", "ANSWERING": "ANSWERING", "RESUME_PREPARING": "ANSWERING"}[phase]
		if crashState != expectedState {
			cmd.Process.Kill()
			cmd.Wait()
			t.Fatalf("wrong actual SQL crash window: %s expected %s", crashState, expectedState)
		}
		t.Logf("actual SQL crash window %s (%s)", phase, crashState)
		e = p.QueryRow(ctx, `SELECT completion_cursor_json FROM v05_narrations WHERE session_id='s'`).Scan(&before)
		if e != nil {
			t.Fatal(e)
		}
		if e = cmd.Process.Kill(); e != nil {
			t.Fatal(e)
		}
		_ = cmd.Wait()
		_, e = p.Exec(ctx, `UPDATE v05_recovery_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE session_id='s'`)
		if e != nil {
			t.Fatal(e)
		}
		recovered := durability.New(p)
		coordinator := recovery.Coordinator{Store: recovered, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
		if e = coordinator.Sweep(ctx); e != nil {
			t.Fatal(e)
		}
		var after []byte
		var state string
		var epoch int64
		e = p.QueryRow(ctx, `SELECT completion_cursor_json,state FROM v05_narrations WHERE session_id='s'`).Scan(&after, &state)
		if e != nil {
			t.Fatal(e)
		}
		_ = p.QueryRow(ctx, `SELECT run_epoch FROM v05_recovery_leases WHERE session_id='s'`).Scan(&epoch)
		if !bytes.Equal(before, after) || state != "RECOVERY_REQUIRED" || epoch != 2 {
			t.Fatalf("cursor replay/loss on recovery: %s %s %s %d", before, after, state, epoch)
		}
		if e = narration.New(recovered).Drive(ctx, "s"); e == nil {
			t.Fatal("recovery implicitly resumed")
		}
		var newMedia int
		_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE run_epoch=2 AND command_type<>'BEGIN_RUN'`).Scan(&newMedia)
		if newMedia != 0 {
			t.Fatal("ghost answer/resume", newMedia)
		}
		t.Log("SIGKILL Runtime; fresh A recovery owner retained cursor, sealed old media, no replay")
		return
	}
	out, e := cmd.CombinedOutput()
	if e != nil {
		t.Fatalf("Python/PG seam failed: %v\n%s", e, out)
	}
	t.Log(string(out))
	var raw []byte
	e = p.QueryRow(ctx, `SELECT document_json FROM v05_narrations WHERE session_id='s'`).Scan(&raw)
	if e != nil {
		t.Fatal(e)
	}
	var d narration.Document
	json.Unmarshal(raw, &d)
	epoch := int64(3)
	completions := count + 1
	if phase == "MEDIA_SOAK" {
		epoch = 11
		completions = count + 9
	}
	if phase == "EXPIRED" {
		epoch = 2
		completions = count
	}
	turnState := "COMPLETED"
	if phase == "EXPIRED" {
		turnState = "EXPIRED"
	}
	if d.Reason != "FINISHED" || len(d.PendingFacts()) != 0 || len(d.Cursor.CompletedFacts) != count || d.Turn == nil || d.Turn.Status != turnState || d.TimelineEpoch != epoch {
		t.Fatalf("not resumed: %s", raw)
	}
	if d.Turn.SourceScope.Platform != "mock" || d.Turn.SourceScope.InternalRoomID != "room" || len(d.Turn.SourceIDs) == 0 {
		t.Fatal("selected source mapping was not persisted")
	}
	if phase != "EXPIRED" && d.Plan.Segments[count-1].Status != "SATISFIED_BY_ANSWER" {
		t.Fatal("exact price answer repeated")
	}
	var observations int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_timeline_observations WHERE operation='SEGMENT_COMPLETED'`).Scan(&observations)
	if observations != completions {
		t.Fatal("expected narration,answer,bridge,narration completions", observations)
	}
	if directory := os.Getenv("NARRATION_MEDIA_EVIDENCE_DIR"); media && directory != "" {
		var sqlProof []byte
		e = p.QueryRow(ctx, `SELECT jsonb_build_object('scope','synthetic fixture, real PG required-sink proof, not audience audibility',
 'document',(SELECT document_json FROM v05_narrations WHERE session_id='s'),
 'turns',(SELECT jsonb_agg(document_json ORDER BY document_json->>'selectedAt') FROM v05_interaction_turns),
 'commits',(SELECT jsonb_agg(jsonb_build_object('segmentId',segment_id,'attemptId',attempt_id,'identity',identity_json,'startSample',start_sample,'endSample',end_sample,'sampleRate',sample_rate,'status',status,'requiredSinks',required_sinks,'sinkReceipts',sink_receipts) ORDER BY start_sample) FROM v05_timeline_commits))`).Scan(&sqlProof)
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(filepath.Join(directory, "sql-proof.json"), sqlProof, 0600); e != nil {
			t.Fatal(e)
		}
	}
}
