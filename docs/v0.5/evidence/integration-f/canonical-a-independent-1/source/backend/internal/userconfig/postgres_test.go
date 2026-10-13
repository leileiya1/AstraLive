package userconfig

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"astralive/backend/db"
	"github.com/jackc/pgx/v5/pgxpool"
)

// This test requires a disposable DB. It never uses DATABASE_URL implicitly.
func TestPostgresConfigurationLifecycle(t *testing.T) {
	url := os.Getenv("CONFIG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("CONFIG_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, e := pgxpool.New(ctx, url)
	if e != nil {
		t.Fatal("test postgres unavailable")
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal("migration not idempotent", e)
	}
	var receivedKeys []string
	s := &Service{DB: pool, Vault: testVault(t), Origin: "https://settings.example", Hosts: map[string]bool{"api.deepseek.com": true}}
	s.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		receivedKeys = append(receivedKeys, key)
		status, body := 200, `{"choices":[{"message":{"content":"Hello"}}]}`
		if key == "invalid-synthetic-key" {
			status, body = 401, `{"error":"invalid-synthetic-key"}`
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body)), Header: http.Header{}}, nil
	})}
	scope := Scope{"test-tenant-" + time.Now().Format("150405.000000"), "user-a"}
	token, e := s.IssueSession(ctx, scope)
	if e != nil {
		t.Fatal(e)
	}
	other := Scope{scope.TenantID, "user-b"}
	otherToken, e := s.IssueSession(ctx, other)
	if e != nil {
		t.Fatal(e)
	}
	third := Scope{scope.TenantID + "-other", "user-a"}
	thirdToken, e := s.IssueSession(ctx, third)
	if e != nil {
		t.Fatal(e)
	}
	defer func() {
		for _, table := range []string{"provider_bindings", "config_test_attempts", "config_profiles", "config_auth_sessions", "user_settings", "config_principals"} {
			_, _ = pool.Exec(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1 OR tenant_id=$2", scope.TenantID, third.TenantID)
		}
	}()
	call := func(token, method, path string, body any, origin string) (int, json.RawMessage) {
		t.Helper()
		raw, _ := json.Marshal(body)
		r := httptest.NewRequest(method, path, strings.NewReader(string(raw)))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Origin", origin)
		r.AddCookie(&http.Cookie{Name: "astralive_config_session", Value: token})
		w := httptest.NewRecorder()
		s.PublicRouter().ServeHTTP(w, r)
		for _, key := range []string{"original-synthetic-key", "new-synthetic-key", "invalid-synthetic-key"} {
			if strings.Contains(w.Body.String(), key) {
				t.Fatal("public response contains secret")
			}
		}
		var result struct {
			Data json.RawMessage `json:"data"`
		}
		if e = json.Unmarshal(w.Body.Bytes(), &result); e != nil {
			t.Fatal(e)
		}
		return w.Code, result.Data
	}
	decode := func(raw []byte) Profile {
		var p Profile
		if e = json.Unmarshal(raw, &p); e != nil {
			t.Fatal(e)
		}
		return p
	}
	code, _ := call(token, "POST", "/profiles", Input{Kind: "LLM", Name: "DeepSeek", Provider: "deepseek", Config: json.RawMessage(`{"model":"deepseek-flash","maxTokens":256}`), Secret: "original-synthetic-key"}, "")
	if code != 403 {
		t.Fatalf("missing origin %d", code)
	}
	code, raw := call(token, "POST", "/profiles", Input{Kind: "LLM", Name: "DeepSeek", Provider: "deepseek", Config: json.RawMessage(`{"model":"deepseek-flash","maxTokens":256}`), Secret: "original-synthetic-key"}, s.Origin)
	if code != 201 {
		t.Fatal("save", code)
	}
	p := decode(raw)
	if !p.CredentialConfigured || p.Version != 1 || p.Verification != "UNTESTED" {
		t.Fatal("wrong saved status")
	}
	var cipher []byte
	if e = pool.QueryRow(ctx, "SELECT ciphertext FROM provider_credentials WHERE tenant_id=$1 AND user_id=$2 AND profile_id=$3", scope.TenantID, scope.UserID, p.ID).Scan(&cipher); e != nil || strings.Contains(string(cipher), "original-synthetic-key") {
		t.Fatal("encryption at rest failed", e)
	}
	code, raw = call(token, "GET", "/profiles", nil, s.Origin)
	if code != 200 || !strings.Contains(string(raw), `"credentialConfigured":true`) {
		t.Fatal("refresh readback")
	}
	for _, tok := range []string{otherToken, thirdToken} {
		code, raw = call(tok, "GET", "/profiles", nil, s.Origin)
		if code != 200 || string(raw) != "[]" {
			t.Fatal("cross scope list")
		}
		for _, a := range []string{"test", "default", "disable"} {
			code, _ = call(tok, "POST", "/profiles/"+p.ID+"/"+a, map[string]any{"expectedVersion": 1}, s.Origin)
			if code != 404 {
				t.Fatalf("cross scope %s %d", a, code)
			}
		}
		code, _ = call(tok, "PUT", "/profiles/"+p.ID+"/credential", map[string]any{"expectedVersion": 1, "secret": "cross-user-synthetic-key"}, s.Origin)
		if code != 404 {
			t.Fatal("cross scope credential")
		}
	}
	code, raw = call(token, "POST", "/profiles/"+p.ID+"/test", map[string]any{"expectedVersion": 1}, s.Origin)
	if code != 200 {
		t.Fatal("test", code)
	}
	p = decode(raw)
	if p.Verification != "VERIFIED" || receivedKeys[0] != "original-synthetic-key" {
		t.Fatal("test failed to use credential")
	}
	code, raw = call(token, "POST", "/profiles/"+p.ID+"/default", map[string]any{"expectedVersion": 1}, s.Origin)
	if code != 200 || !decode(raw).Default {
		t.Fatal("default failed")
	}
	binding, e := s.Capture(ctx, scope)
	if e != nil {
		t.Fatal(e)
	}
	code, raw = call(token, "PUT", "/profiles/"+p.ID+"/credential", map[string]any{"expectedVersion": 1, "secret": "new-synthetic-key"}, s.Origin)
	if code != 200 {
		t.Fatal(code)
	}
	p = decode(raw)
	if p.Version != 2 || p.Default || p.Verification != "UNTESTED" {
		t.Fatal("rotation did not invalidate config")
	}
	code, _ = call(token, "POST", "/profiles/"+p.ID+"/default", map[string]any{"expectedVersion": 2}, s.Origin)
	if code != 409 {
		t.Fatal("unverified default")
	}
	code, _ = call(token, "PUT", "/profiles/"+p.ID+"/credential", map[string]any{"expectedVersion": 1, "secret": "stale-synthetic-key"}, s.Origin)
	if code != 409 {
		t.Fatal("stale update")
	}
	_, keys, e := s.Resolve(ctx, scope, binding.ID)
	if e != nil || keys[p.ID] != "original-synthetic-key" {
		t.Fatal("binding mixed credentials", e)
	}
	if _, _, e = s.Resolve(ctx, other, binding.ID); e == nil {
		t.Fatal("cross user binding")
	}
	cooldown := func() {
		_, e = pool.Exec(ctx, `UPDATE config_test_attempts SET attempted_at=now()-interval '6 seconds' WHERE tenant_id=$1 AND user_id=$2`, scope.TenantID, scope.UserID)
		if e != nil {
			t.Fatal(e)
		}
	}
	cooldown()
	code, raw = call(token, "POST", "/profiles/"+p.ID+"/test", map[string]any{"expectedVersion": 2}, s.Origin)
	if code != 200 || decode(raw).Verification != "VERIFIED" || receivedKeys[len(receivedKeys)-1] != "new-synthetic-key" {
		t.Fatal("new credential unused")
	}
	code, raw = call(token, "PUT", "/profiles/"+p.ID+"/credential", map[string]any{"expectedVersion": 2, "secret": "invalid-synthetic-key"}, s.Origin)
	if code != 200 {
		t.Fatal(code)
	}
	p = decode(raw)
	cooldown()
	code, _ = call(token, "POST", "/profiles/"+p.ID+"/test", map[string]any{"expectedVersion": 3}, s.Origin)
	if code != 502 {
		t.Fatal("401 silently successful", code)
	}
	current, e := s.Get(ctx, scope, p.ID)
	if e != nil || current.Verification != "FAILED" || current.ErrorCode != "PROVIDER_AUTH_FAILED" {
		t.Fatal("401 state not persisted")
	}
	cooldown()
	s.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		_, e := s.Mutate(ctx, scope, p.ID, "credential", Input{ExpectedVersion: 3, Secret: "race-new-synthetic-key"})
		if e != nil {
			t.Fatal(e)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"choices":[{"message":{"content":"Hi"}}]}`)), Header: http.Header{}}, nil
	})}
	code, _ = call(token, "POST", "/profiles/"+p.ID+"/test", map[string]any{"expectedVersion": 3}, s.Origin)
	if code != 409 {
		t.Fatal("stale test accepted")
	}
	current, _ = s.Get(ctx, scope, p.ID)
	if current.Verification != "UNTESTED" {
		t.Fatal("stale test verified new key")
	}
	for _, in := range []Input{{Kind: "TTS", Name: "XiaoYa", Provider: "xiaoya", Config: json.RawMessage(`{"voiceId":"xiao_ya","speed":1.2,"modelRef":"xiaoya-default"}`)}, {Kind: "AVATAR", Name: "Avatar", Provider: "soulx", Config: json.RawMessage(`{"avatarRef":"avatar-user-a"}`)}, {Kind: "GPU_WORKER", Name: "Worker", Provider: "soulx", Config: json.RawMessage(`{"workerRef":"worker-user-a"}`)}, {Kind: "LIVE_PLATFORM", Name: "Live", Provider: "generic", Config: json.RawMessage(`{"platform":"generic"}`), Secret: "stream-synthetic-secret"}} {
		saved, e := s.Create(ctx, scope, in)
		if e != nil {
			t.Fatal(e)
		}
		read, e := s.Get(ctx, scope, saved.ID)
		if e != nil || read.Kind != in.Kind || string(read.Config) == "" {
			t.Fatal("config readback")
		}
		if _, e = s.Test(ctx, scope, saved.ID, saved.Version); publicError(e).Code != "PROVIDER_TEST_UNAVAILABLE" {
			t.Fatal("fake provider success")
		}
	}
	foreignWorker, e := s.Create(ctx, other, Input{Kind: "GPU_WORKER", Name: "Other user worker", Provider: "soulx", Config: json.RawMessage(`{"workerRef":"other-worker"}`)})
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Create(ctx, scope, Input{Kind: "AVATAR", Name: "Invalid reference", Provider: "soulx", Config: json.RawMessage(`{"avatarRef":"ref","workerProfileId":"` + foreignWorker.ID + `"}`)}); publicError(e).Status != 404 {
		t.Fatal("cross-scope worker reference accepted")
	}
	workerRows, e := s.List(ctx, scope)
	if e != nil {
		t.Fatal(e)
	}
	var worker Profile
	for _, candidate := range workerRows {
		if candidate.Kind == "GPU_WORKER" {
			worker = candidate
		}
	}
	if worker.Health != "UNKNOWN" {
		t.Fatal("unreported worker appears healthy")
	}
	if _, e = pool.Exec(ctx, `UPDATE config_profiles SET health='UP',health_at=now()-interval '61 seconds' WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, worker.ID); e != nil {
		t.Fatal(e)
	}
	worker, e = s.Get(ctx, scope, worker.ID)
	if e != nil || worker.Health != "UNKNOWN" {
		t.Fatal("stale worker health not unknown")
	}
	tokenDir := t.TempDir()
	s.WorkerTokenFile = filepath.Join(tokenDir, "worker-token")
	s.IdentityTokenFile = filepath.Join(tokenDir, "identity-token")
	workerToken := strings.Repeat("worker-test-only-", 4)
	identityToken := strings.Repeat("identity-test-only-", 4)
	if e = os.WriteFile(s.WorkerTokenFile, []byte(workerToken), 0600); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(s.IdentityTokenFile, []byte(identityToken), 0600); e != nil {
		t.Fatal(e)
	}
	internalCall := func(path, token string, input any) int {
		t.Helper()
		raw, _ := json.Marshal(input)
		r := httptest.NewRequest("POST", path, strings.NewReader(string(raw)))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.InternalRouter().ServeHTTP(w, r)
		return w.Code
	}
	if code := internalCall("/provider-bindings/"+binding.ID+"/resolve", identityToken, scope); code != 401 {
		t.Fatal("identity token used as worker privilege")
	}
	if code := internalCall("/provider-bindings/"+binding.ID+"/resolve", workerToken, other); code != 404 {
		t.Fatal("internal resolution ignores binding scope")
	}
	if code := internalCall("/provider-bindings/"+binding.ID+"/resolve", workerToken, scope); code != 200 {
		t.Fatal("internal snapshot resolution failed")
	}
	healthInput := map[string]any{"tenantId": scope.TenantID, "userId": scope.UserID, "profileId": worker.ID, "expectedVersion": worker.Version, "health": "UP"}
	if code := internalCall("/worker-health", workerToken, healthInput); code != 200 {
		t.Fatal("worker report failed")
	}
	worker, e = s.Get(ctx, scope, worker.ID)
	if e != nil || worker.Health != "UP" {
		t.Fatal("fresh health not visible")
	}
	healthInput["expectedVersion"] = worker.Version + 1
	if code := internalCall("/worker-health", workerToken, healthInput); code != 409 {
		t.Fatal("stale worker report accepted")
	}
	if code := internalCall("/config-sessions", workerToken, Scope{scope.TenantID, "adapter-user"}); code != 401 {
		t.Fatal("worker token used as identity privilege")
	}
	if code := internalCall("/config-sessions", identityToken, Scope{scope.TenantID, "adapter-user"}); code != 201 {
		t.Fatal("trusted identity adapter failed")
	}
	saved, e := s.SaveSettings(ctx, scope, 0, Policy{50, "STOP"})
	if e != nil || saved.Version != 1 || saved.Policy.MaxQueue != 50 {
		t.Fatal("settings", e)
	}
	if _, e = s.SaveSettings(ctx, scope, 0, Policy{60, "STOP"}); e != ErrConflict {
		t.Fatal("stale settings")
	}
	code, _ = call(token, "DELETE", "/profiles/"+p.ID, map[string]any{"expectedVersion": 4}, s.Origin)
	if code != 200 {
		t.Fatal("delete", code)
	}
	_, keys, e = s.Resolve(ctx, scope, binding.ID)
	if e != nil || keys[p.ID] != "original-synthetic-key" {
		t.Fatal("deletion changed pinned binding")
	}
	_, e = pool.Exec(ctx, `UPDATE provider_bindings SET expires_at=now()-interval '1 second' WHERE id=$1`, binding.ID)
	if e != nil {
		t.Fatal(e)
	}
	if _, _, e = s.Resolve(ctx, scope, binding.ID); e == nil {
		t.Fatal("expired binding accessible")
	}
	_, e = pool.Exec(ctx, `DELETE FROM config_auth_sessions WHERE token_hash=$1`, tokenHash(token))
	if e != nil {
		t.Fatal(e)
	}
	code, _ = call(token, "GET", "/profiles", nil, s.Origin)
	if code != 401 {
		t.Fatal("revoked session accessible")
	}
}
