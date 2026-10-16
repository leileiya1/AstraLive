package httpapi

import (
	"astralive/backend/db"
	"astralive/backend/internal/app"
	"astralive/backend/internal/durablelive"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/userconfig"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestDurableRecoveryAlwaysRequiresProductAuthentication(t *testing.T) {
	h := &Server{S: &app.Service{}}
	for _, path := range []string{"/sessions/session", "/runs/run/decisions", "/runs/run/stop"} {
		method := "POST"
		if strings.Contains(path, "sessions") {
			method = "GET"
		}
		req := httptest.NewRequest(method, path, strings.NewReader(`{}`))
		// A legacy internal token is deliberately not a product cookie/identity.
		req.Header.Set("Authorization", "Bearer legacy-control-token")
		res := httptest.NewRecorder()
		h.durableRouter().ServeHTTP(res, req)
		if res.Code != http.StatusUnauthorized {
			t.Fatal(path, res.Code, res.Body.String())
		}
	}
}

func TestPostgresDurableRecoveryOwnerCSRFAndStop(t *testing.T) {
	dsn := os.Getenv("DURABLE_LIVE_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("dedicated PostgreSQL required")
	}
	config, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	if config.ConnConfig.Host != "127.0.0.1" || !strings.HasPrefix(config.ConnConfig.Database, "agent2_") {
		t.Fatal("refuse shared database")
	}
	ctx := context.Background()
	pool, e := pgxpool.NewWithConfig(ctx, config)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	cfg := &userconfig.Service{DB: pool, Origin: "https://astralive.test"}
	id := ids.New("durable_http")
	scope := userconfig.Scope{TenantID: id, UserID: "owner"}
	other := userconfig.Scope{TenantID: id, UserID: "other"}
	token, e := cfg.IssueSession(ctx, scope)
	if e != nil {
		t.Fatal(e)
	}
	foreign, e := cfg.IssueSession(ctx, other)
	if e != nil {
		t.Fatal(e)
	}
	exec := func(q string, args ...any) {
		t.Helper()
		if _, e = pool.Exec(ctx, q, args...); e != nil {
			t.Fatal(e)
		}
	}
	exec(`INSERT INTO avatars(id,name,engine) VALUES($1,'test','MOCK')`, id+"avatar")
	exec(`INSERT INTO voices(id,name,provider,provider_voice_id) VALUES($1,'test','MOCK','test')`, id+"voice")
	exec(`INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES($1,'test',$2,$3,'test')`, id+"room", id+"avatar", id+"voice")
	exec(`INSERT INTO live_sessions(id,room_id,status) VALUES($1,$2,'LIVE')`, id+"session", id+"room")
	for _, v := range [][2]string{{"room", id + "room"}, {"session", id + "session"}} {
		exec(`INSERT INTO resource_owners VALUES($1,$2,$3,$4)`, v[0], v[1], scope.TenantID, scope.UserID)
	}
	exec(`INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,'{}','{}',clock_timestamp()+interval '1 hour')`, id+"session", scope.TenantID, scope.UserID, id+"binding")
	store := durablelive.New(pool, []string{"test-sink"})
	principal := durablelive.Principal{Role: "CONTROL", TenantID: scope.TenantID, OwnerID: scope.UserID, InstanceID: "test-control"}
	rawCall := func(op string, fields durablelive.Object) durablelive.Object {
		t.Helper()
		q := durablelive.Object{"schemaVersion": "0.5", "contractRevision": durablelive.RevisionName, "requestId": ids.New("req"), "tenantId": scope.TenantID, "ownerId": scope.UserID, "runId": id + "run"}
		for k, v := range fields {
			q[k] = v
		}
		b, _ := json.Marshal(q)
		v, e := store.Call(ctx, principal, op, b)
		if e != nil {
			t.Fatal(op, e)
		}
		return v
	}
	rawCall("CreateBroadcastRun", durablelive.Object{"roomId": id + "room", "recoveryPolicy": "MANUAL_ON_UNKNOWN", "idempotencyKey": "create"})
	rawCall("ResumeBroadcastRun", durablelive.Object{"expectedRevision": int64(1), "expectedPreviousEpoch": int64(0), "decisionId": ids.New("resume"), "idempotencyKey": "resume"})
	if e = store.AttachSession(ctx, principal, id+"run", 1, durablelive.SessionAdmission{SessionID: id + "session", ProducerIncarnation: "test-runtime", WorkerReady: true, CheckedAt: time.Now()}); e != nil {
		t.Fatal(e)
	}
	service := app.New(pool, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = store
	h := &Server{S: service, Config: cfg, Log: service.Log, Env: "production"}
	router := h.Router()
	call := func(cookie, method, path, body, origin string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, "/api/v0.5/durable-live"+path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Origin", origin)
		if cookie != "" {
			req.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: cookie})
		}
		res := httptest.NewRecorder()
		router.ServeHTTP(res, req)
		return res
	}
	if r := call("", "GET", "/sessions/"+id+"session", "", ""); r.Code != 401 {
		t.Fatal(r.Code, r.Body.String())
	}
	if r := call(foreign, "GET", "/sessions/"+id+"session", "", ""); r.Code != 404 {
		t.Fatal("foreign read", r.Code, r.Body.String())
	}
	if r := call(token, "GET", "/sessions/"+id+"session", "", ""); r.Code != 200 || !strings.Contains(r.Body.String(), `"managed":true`) {
		t.Fatal("owner read", r.Code, r.Body.String())
	}
	body := `{"decisionId":"` + id + `:stop"}`
	if r := call(token, "POST", "/runs/"+id+"run/stop", body, ""); r.Code != 403 {
		t.Fatal("csrf", r.Code)
	}
	if r := call(foreign, "POST", "/runs/"+id+"run/stop", body, cfg.Origin); r.Code != 403 {
		t.Fatal("foreign stop", r.Code, r.Body.String())
	}
	for i := 0; i < 2; i++ {
		if r := call(token, "POST", "/runs/"+id+"run/stop", body, cfg.Origin); r.Code != 202 || !strings.Contains(r.Body.String(), `"desiredState":"STOPPED"`) {
			t.Fatal("durable stop", r.Code, r.Body.String())
		}
	}
	var n int
	if e = pool.QueryRow(ctx, `SELECT count(*) FROM dl05_outbox WHERE run_id=$1 AND operation='STOP_RUN'`, id+"run").Scan(&n); e != nil || n != 1 {
		t.Fatal("duplicate Stop intent", n, e)
	}
	// A foreign user cannot choose operator identity, bypass revision or see a saved decision.
	decision := `{"decisionId":"foreign-decision","attemptId":"unknown","expectedRevision":1,"action":"WAIT_FOR_EVIDENCE","reason":"test","createdAt":"2026-10-16T00:00:00Z"}`
	if r := call(foreign, "POST", "/runs/"+id+"run/decisions", decision, cfg.Origin); r.Code != 403 {
		t.Fatal("foreign decision", r.Code, r.Body.String())
	}
}
