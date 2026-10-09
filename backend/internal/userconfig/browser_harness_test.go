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

// A loopback HTTPS integration fixture only. These routes never compile into server/main.
// It uses synthetic credentials and a disposable DB; no external Provider request is made.
func TestConfigurationBrowserHarness(t *testing.T) {
	if os.Getenv("CONFIG_BROWSER_TEST") != "1" {
		t.Skip("browser harness opt-in")
	}
	databaseURL := os.Getenv("CONFIG_TEST_DATABASE_URL")
	ready := os.Getenv("CONFIG_BROWSER_READY_FILE")
	if databaseURL == "" || ready == "" {
		t.Fatal("explicit disposable DB and ready file required")
	}
	ctx := context.Background()
	pool, e := pgxpool.New(ctx, databaseURL)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	scope := Scope{"browser-" + time.Now().Format("150405.000000"), "user-a"}
	s := &Service{DB: pool, Vault: testVault(t), Hosts: map[string]bool{"api.deepseek.com": true}}
	s.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		status, body := 200, `{"choices":[{"message":{"content":"Hello from synthetic integration fixture"}}]}`
		if strings.HasPrefix(key, "invalid-") {
			status, body = 401, `{"error":"credential rejected"}`
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body)), Header: http.Header{}}, nil
	})}
	token, e := s.IssueSession(ctx, scope)
	if e != nil {
		t.Fatal(e)
	}
	defer func() {
		for _, table := range []string{"provider_bindings", "config_test_attempts", "config_profiles", "config_auth_sessions", "user_settings", "config_principals"} {
			_, _ = pool.Exec(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", scope.TenantID)
		}
	}()
	mux := http.NewServeMux()
	done := make(chan struct{}, 1)
	mux.Handle("/api/v0.3/config/", http.StripPrefix("/api/v0.3/config", s.PublicRouter()))
	mux.HandleFunc("/_test/login", func(w http.ResponseWriter, r *http.Request) {
		http.SetCookie(w, &http.Cookie{Name: "astralive_config_session", Value: token, Path: "/api/v0.3/config", Secure: true, HttpOnly: true, SameSite: http.SameSiteStrictMode})
		w.WriteHeader(204)
	})
	mux.HandleFunc("/_test/cooldown", func(w http.ResponseWriter, r *http.Request) {
		_, e := pool.Exec(ctx, `UPDATE config_test_attempts SET attempted_at=now()-interval '6 seconds' WHERE tenant_id=$1 AND user_id=$2`, scope.TenantID, scope.UserID)
		if e != nil {
			w.WriteHeader(500)
			return
		}
		w.WriteHeader(204)
	})
	mux.HandleFunc("/_test/stop", func(w http.ResponseWriter, r *http.Request) {
		select {
		case done <- struct{}{}:
		default:
		}
		w.WriteHeader(204)
	})
	mux.Handle("/", http.FileServer(http.Dir(filepath.Join("..", "..", "..", "frontend", "dist"))))
	server := httptest.NewTLSServer(mux)
	defer server.Close()
	s.Origin = server.URL
	raw, _ := json.Marshal(map[string]string{"url": server.URL})
	if e = os.WriteFile(ready, raw, 0600); e != nil {
		t.Fatal(e)
	}
	defer os.Remove(ready)
	select {
	case <-done:
	case <-time.After(5 * time.Minute):
		t.Fatal("browser test timeout")
	}
}
