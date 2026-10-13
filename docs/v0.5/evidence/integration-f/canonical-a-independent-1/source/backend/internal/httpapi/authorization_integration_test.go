package httpapi

import (
	"astralive/backend/db"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/app"
	"astralive/backend/internal/userconfig"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestProductAuthorizationAndPinnedBindings(t *testing.T) {
	url := os.Getenv("CONFIG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("explicit disposable DB required")
	}
	ctx := context.Background()
	pool, e := pgxpool.New(ctx, url)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	dir := t.TempDir()
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	raw, _ := json.Marshal(map[string]any{"activeKeyId": "test", "keys": map[string]string{"test": base64.StdEncoding.EncodeToString(key)}})
	keyFile := filepath.Join(dir, "keyring.json")
	if e = os.WriteFile(keyFile, raw, 0600); e != nil {
		t.Fatal(e)
	}
	workerFile := filepath.Join(dir, "worker-token")
	_ = os.WriteFile(workerFile, []byte(strings.Repeat("w", 40)), 0600)
	identityFile := filepath.Join(dir, "identity-token")
	_ = os.WriteFile(identityFile, []byte(strings.Repeat("i", 40)), 0600)
	tenant := "auth-test-" + time.Now().Format("150405.000000")
	a := userconfig.Scope{TenantID: tenant, UserID: "a"}
	b := userconfig.Scope{TenantID: tenant, UserID: "b"}
	cfg := &userconfig.Service{DB: pool, Vault: userconfig.Vault{Path: keyFile}, Origin: "https://astralive.test", Hosts: map[string]bool{"api.deepseek.com": true}, WorkerTokenFile: workerFile, IdentityTokenFile: identityFile}
	at, e := cfg.IssueSession(ctx, a)
	if e != nil {
		t.Fatal(e)
	}
	bt, e := cfg.IssueSession(ctx, b)
	if e != nil {
		t.Fatal(e)
	}
	h := &Server{Config: cfg, S: app.New(pool, nil, slog.Default()), Log: slog.New(slog.NewTextHandler(io.Discard, nil)), Env: "production", Token: strings.Repeat("t", 40)}
	router := h.Router()
	call := func(token, method, path, body, origin string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Origin", origin)
		if token != "" {
			r.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: token})
			r.AddCookie(&http.Cookie{Name: "astralive_config_session", Value: token})
		}
		w := httptest.NewRecorder()
		router.ServeHTTP(w, r)
		return w
	}
	if w := call("", "POST", "/api/v1/live-sessions/x/stop", "{}", cfg.Origin); w.Code != 401 {
		t.Fatal("anonymous control", w.Code)
	}
	if w := call(at, "POST", "/api/v1/avatars", `{"name":"a","engine":"MOCK"}`, ""); w.Code != 403 {
		t.Fatal("csrf", w.Code)
	}
	decodeID := func(w *httptest.ResponseRecorder, key string) string {
		t.Helper()
		if w.Code != 201 {
			t.Fatal(w.Code, w.Body.String())
		}
		var result struct {
			Data map[string]any `json:"data"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &result)
		return result.Data[key].(string)
	}
	avatar := decodeID(call(at, "POST", "/api/v1/avatars", `{"name":"a","engine":"MOCK"}`, cfg.Origin), "avatarId")
	voice := decodeID(call(at, "POST", "/api/v1/voices", `{"name":"v","provider":"MOCK","providerVoiceId":"x"}`, cfg.Origin), "voiceId")
	roomBody := `{"name":"room-a","avatarId":"` + avatar + `","voiceId":"` + voice + `","systemPrompt":"original"}`
	if w := call(bt, "POST", "/api/v1/live-rooms", roomBody, cfg.Origin); w.Code != 404 {
		t.Fatal("foreign reference", w.Code)
	}
	room := decodeID(call(at, "POST", "/api/v1/live-rooms", roomBody, cfg.Origin), "roomId")
	for _, path := range []string{"/api/v1/live-rooms/" + room, "/api/v1/avatars/" + avatar} {
		if w := call(bt, "GET", path, "", ""); w.Code != 404 {
			t.Fatal("cross user", path, w.Code)
		}
	}
	if w := call(bt, "GET", "/api/v1/live-rooms", "", ""); w.Code != 200 || !strings.Contains(w.Body.String(), `"data":[]`) {
		t.Fatal("collection leak", w.Code, w.Body.String())
	}
	if w := call(bt, "POST", "/api/v1/live-sessions", `{"roomId":"`+room+`"}`, cfg.Origin); w.Code != 404 {
		t.Fatal("foreign room Session", w.Code)
	}
	if w := call(at, "POST", "/internal/v0.3/provider-bindings", `{"tenantId":"`+tenant+`","userId":"a"}`, cfg.Origin); w.Code != 401 {
		t.Fatal("user cookie internal", w.Code)
	}
	if w := call(at, "GET", "/internal/v0.4/sessions/known/binding", "", ""); w.Code != 401 {
		t.Fatal("internal binding", w.Code)
	}
	// Profiles use real encryption/SQL; upstream verification result is a fixture.
	mk := func(kind, provider, config, secret string) userconfig.Profile {
		t.Helper()
		p, e := cfg.Create(ctx, a, userconfig.Input{Kind: kind, Name: kind, Provider: provider, Config: json.RawMessage(config), Secret: secret})
		if e != nil {
			t.Fatal(e)
		}
		return p
	}
	llm := mk("LLM", "deepseek", `{"model":"deepseek-flash","maxTokens":128}`, "old-synthetic-key")
	tts := mk("TTS", "xiaoya", `{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}`, "")
	worker := mk("GPU_WORKER", "soulx", `{"workerRef":"test-worker"}`, "")
	av := mk("AVATAR", "soulx", `{"avatarRef":"official-girl","workerProfileId":"`+worker.ID+`"}`, "")
	if _, e = cfg.Mutate(ctx, a, llm.ID, "default", userconfig.Input{ExpectedVersion: 1}); e == nil {
		t.Fatal("unverified default admitted")
	}
	_, e = pool.Exec(ctx, `UPDATE config_profiles SET verification='VERIFIED' WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, tenant, a.UserID, llm.ID)
	if e != nil {
		t.Fatal(e)
	}
	for _, p := range []userconfig.Profile{llm, tts, worker, av} {
		if _, e = cfg.Mutate(ctx, a, p.ID, "default", userconfig.Input{ExpectedVersion: 1}); e != nil {
			t.Fatal(e)
		}
	}
	cfg.IntegrationEnabled = true
	sessionID := decodeID(call(at, "POST", "/api/v1/live-sessions", `{"roomId":"`+room+`"}`, cfg.Origin), "sessionId")
	for _, suffix := range []string{"", "/start", "/stop", "/utterances", "/interrupt", "/webrtc/offer", "/events"} {
		method, body := "POST", "{}"
		if suffix == "" || suffix == "/events" {
			method = "GET"
		}
		if w := call(bt, method, "/api/v1/live-sessions/"+sessionID+suffix, body, cfg.Origin); w.Code != 404 {
			t.Fatal("Session isolation", suffix, w.Code)
		}
	}
	if w := call(bt, "GET", "/api/v0.4/sessions/"+sessionID+"/providers", "", ""); w.Code != 404 {
		t.Fatal("summary isolation", w.Code)
	}
	if w := call(bt, "GET", "/api/v0.3/config/profiles/"+worker.ID+"/worker-status", "", ""); w.Code != 404 {
		t.Fatal("Worker isolation", w.Code)
	}
	cfg.Workers = map[string]userconfig.WorkerEndpoint{"only-a": {TokenFile: "/never-present", AllowedScopes: []userconfig.Scope{a}}}
	if w := call(bt, "GET", "/api/v0.4/workers/", "", ""); w.Code != 200 || !strings.Contains(w.Body.String(), `"data":[]`) {
		t.Fatal("registry enumeration isolation", w.Code)
	}
	if w := call(at, "GET", "/api/v0.4/workers/", "", ""); w.Code != 200 || !strings.Contains(w.Body.String(), `"workerRef":"only-a"`) || strings.Contains(w.Body.String(), "/never-present") {
		t.Fatal("registry safe selection", w.Code)
	}
	if w := call(bt, "PUT", "/api/v0.3/config/profiles/"+llm.ID+"/credential", `{"expectedVersion":1,"secret":"synthetic-key"}`, cfg.Origin); w.Code != 404 {
		t.Fatal("Profile isolation", w.Code)
	}
	var bindingID string
	_ = pool.QueryRow(ctx, `SELECT binding_id FROM session_provider_bindings WHERE session_id=$1`, sessionID).Scan(&bindingID)
	if _, _, e = cfg.Resolve(ctx, b, bindingID); e == nil {
		t.Fatal("binding scope bypass")
	}
	p, e := cfg.Mutate(ctx, a, llm.ID, "credential", userconfig.Input{ExpectedVersion: 1, Secret: "new-synthetic-key"})
	if e != nil || p.Version != 2 || p.Default || p.Verification != "UNTESTED" {
		t.Fatal("rotation", e)
	}
	old, keys, e := cfg.Resolve(ctx, a, bindingID)
	if e != nil || keys[llm.ID] != "old-synthetic-key" {
		t.Fatal("snapshot changed", e)
	}
	if old.Profiles[0].Version != 1 {
		for _, p := range old.Profiles {
			if p.ID == llm.ID && p.Version != 1 {
				t.Fatal("old version changed")
			}
		}
	}
	if w := call(at, "POST", "/api/v1/live-sessions", `{"roomId":"`+room+`"}`, cfg.Origin); w.Code != 409 {
		t.Fatal("missing verified default", w.Code)
	}
	_, _ = pool.Exec(ctx, `UPDATE config_profiles SET verification='VERIFIED' WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, tenant, a.UserID, llm.ID)
	if _, e = cfg.Mutate(ctx, a, llm.ID, "default", userconfig.Input{ExpectedVersion: 2}); e != nil {
		t.Fatal(e)
	}
	newer := decodeID(call(at, "POST", "/api/v1/live-sessions", `{"roomId":"`+room+`"}`, cfg.Origin), "sessionId")
	var newerID string
	_ = pool.QueryRow(ctx, `SELECT binding_id FROM session_provider_bindings WHERE session_id=$1`, newer).Scan(&newerID)
	_, newKeys, e := cfg.Resolve(ctx, a, newerID)
	if e != nil || newKeys[llm.ID] != "new-synthetic-key" {
		t.Fatal("new capture old key", e)
	}
	req := runtimeapi.CreateRuntimeSessionRequest{}
	_, _ = pool.Exec(ctx, `UPDATE live_rooms SET system_prompt='edited' WHERE id=$1`, room)
	if e = cfg.Prepare(ctx, sessionID, &req); e != nil || req.Context.SystemPrompt != "original" {
		t.Fatal("room snapshot", e)
	}
	_, _ = pool.Exec(ctx, `UPDATE session_provider_bindings SET expires_at=now() WHERE session_id=$1`, newer)
	if e = cfg.Prepare(ctx, newer, &req); e == nil {
		t.Fatal("expired binding admitted")
	}
	if e = cfg.Reconcile(ctx); e != nil {
		t.Fatal(e)
	}
	if _, _, e = cfg.Resolve(ctx, a, newerID); e == nil {
		t.Fatal("expired snapshot retained")
	}
	if e = cfg.Release(ctx, sessionID); e != nil {
		t.Fatal(e)
	}
	if e = cfg.Release(ctx, sessionID); e != nil {
		t.Fatal("release not idempotent", e)
	}
	// Real bcrypt login -> hashed DB Session -> cookies -> logout revocation.
	hash, _ := bcrypt.GenerateFromPassword([]byte("test-password-123"), 12)
	operator := filepath.Join(dir, "operator.json")
	raw, _ = json.Marshal(userconfig.OperatorLogin{Username: "operator", PasswordHash: string(hash), Scope: a})
	_ = os.WriteFile(operator, raw, 0600)
	cfg.OperatorFile = operator
	_, _ = pool.Exec(ctx, `DELETE FROM operator_login_attempts`)
	if w := call("", "POST", "/api/v0.4/auth/login", `{"username":"operator","password":"test-password-123"}`, ""); w.Code != 403 {
		t.Fatal("login CSRF", w.Code)
	}
	w := call("", "POST", "/api/v0.4/auth/login", `{"username":"operator","password":"test-password-123"}`, cfg.Origin)
	if w.Code != 200 {
		t.Fatal("login", w.Code, w.Body.String())
	}
	token := ""
	for _, cookie := range w.Result().Cookies() {
		if !cookie.Secure || !cookie.HttpOnly || cookie.SameSite != http.SameSiteStrictMode {
			t.Fatal("cookie flags")
		}
		if cookie.Name == userconfig.ProductCookie {
			token = cookie.Value
		}
	}
	if token == "" || strings.Contains(w.Body.String(), token) {
		t.Fatal("token exposed in JSON")
	}
	if w = call(token, "GET", "/api/v1/live-rooms", "", ""); w.Code != 200 {
		t.Fatal("product login", w.Code)
	}
	if w = call(token, "POST", "/api/v0.4/auth/logout", "{}", cfg.Origin); w.Code != 200 {
		t.Fatal("logout", w.Code)
	}
	if w = call(token, "GET", "/api/v1/live-rooms", "", ""); w.Code != 401 {
		t.Fatal("logout did not revoke", w.Code)
	}
	if w = call(token, "GET", "/api/v0.3/config/me", "", ""); w.Code != 401 {
		t.Fatal("configuration token remained valid", w.Code)
	}
}
