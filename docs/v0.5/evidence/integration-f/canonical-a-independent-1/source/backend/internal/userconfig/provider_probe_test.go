package userconfig

import (
	"astralive/backend/db"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestLocalProviderProbesScopedAndVersioned(t *testing.T) {
	address := os.Getenv("CONFIG_TEST_DATABASE_URL")
	if address == "" {
		t.Skip("explicit disposable DB required")
	}
	ctx := context.Background()
	pool, e := pgxpool.New(ctx, address)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	scope := Scope{"probe-test-" + strconv.FormatInt(time.Now().UnixNano(), 10), "a"}
	defer func() {
		for _, table := range []string{"config_test_attempts", "config_profiles", "config_auth_sessions", "config_principals"} {
			_, _ = pool.Exec(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", scope.TenantID)
		}
	}()
	token := strings.Repeat("p", 40)
	path := filepath.Join(t.TempDir(), "token")
	_ = os.WriteFile(path, []byte(token), 0600)
	real := true
	runtime := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v0.4/provider-probes/tts" || r.Header.Get("Authorization") != "Bearer "+token {
			t.Error("private TTS probe authentication/path")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"real": real, "provider": "xiaoya", "sampleRate": 22050, "samples": 4000})
	}))
	defer runtime.Close()
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+token {
			t.Error("private Worker authentication")
		}
		_, _ = w.Write([]byte(`{"statusVersion":"1.0","workerRef":"w","ready":true,"health":"UP","mode":"gpu","modelRevision":"9bc03de06bb0de82cd6bc477804512ae06144bf2","workerEpoch":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","avatarCacheStatus":{"status":"READY","avatarRef":"official-girl"},"generationCancelStatus":{"status":"NONE"}}`))
	}))
	defer worker.Close()
	u, _ := url.Parse(worker.URL)
	port, _ := strconv.Atoi(u.Port())
	s := &Service{DB: pool, Vault: testVault(t), IntegrationEnabled: true, RuntimeStatusURL: runtime.URL, RuntimeControlTokenFile: path, Workers: map[string]WorkerEndpoint{"w": {ManagementPort: port, TokenFile: path, AllowedScopes: []Scope{scope}}}}
	if _, e = s.IssueSession(ctx, scope); e != nil {
		t.Fatal(e)
	}
	reset := func() { _, _ = pool.Exec(ctx, `DELETE FROM config_test_attempts WHERE tenant_id=$1`, scope.TenantID) }
	create := func(kind, provider, config string) Profile {
		p, e := s.Create(ctx, scope, Input{Kind: kind, Provider: provider, Name: kind, Config: json.RawMessage(config)})
		if e != nil {
			t.Fatal(e)
		}
		return p
	}
	tts := create("TTS", "xiaoya", `{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}`)
	if p, e := s.Test(ctx, scope, tts.ID, 1); e != nil || p.Verification != "VERIFIED" || p.Health != "UP" {
		t.Fatal("TTS valid probe", e)
	}
	if _, e := s.Test(ctx, scope, tts.ID, 1); publicError(e).Code != "RATE_LIMITED" {
		t.Fatal("unbounded expensive probes")
	}
	reset()
	real = false
	if _, e := s.Test(ctx, scope, tts.ID, 1); publicError(e).Code != "PROVIDER_TEST_FAILED" {
		t.Fatal("simulated TTS reply accepted")
	}
	p, _ := s.Get(ctx, scope, tts.ID)
	if p.Verification != "FAILED" {
		t.Fatal("failure not persisted")
	}
	gpu := create("GPU_WORKER", "soulx", `{"workerRef":"w"}`)
	reset()
	if _, e := s.Test(ctx, scope, gpu.ID, 1); e != nil {
		t.Fatal("GPU health probe", e)
	}
	avatar := create("AVATAR", "soulx", `{"avatarRef":"official-girl","workerProfileId":"`+gpu.ID+`"}`)
	reset()
	if _, e := s.Test(ctx, scope, avatar.ID, 1); e != nil {
		t.Fatal("Avatar match probe", e)
	}
	reset()
	s.Workers["w"] = WorkerEndpoint{ManagementPort: port, TokenFile: path, AllowedScopes: []Scope{{scope.TenantID, "b"}}}
	if _, e := s.Test(ctx, scope, gpu.ID, 1); publicError(e).Code != "RESOURCE_NOT_FOUND" {
		t.Fatal("physical Worker enumeration")
	}
}
