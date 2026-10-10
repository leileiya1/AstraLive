package userconfig

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestWorkerProbeProjectionAndPrivateAuth(t *testing.T) {
	token := strings.Repeat("worker-status-token-", 3)
	path := filepath.Join(t.TempDir(), "token")
	if e := os.WriteFile(path, []byte(token), 0600); e != nil {
		t.Fatal(e)
	}
	body := `{"statusVersion":"1.0","workerRef":"w","health":"UP","ready":true,"modelRevision":"9bc03de06bb0de82cd6bc477804512ae06144bf2","workerEpoch":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lastError":"secret error: should not escape","token":"secret-added-upstream","gpuAllocatedBytes":42,"generationCancelStatus":{"status":"NONE"},"mode":"gpu"}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+token {
			t.Error("worker authentication missing")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()
	port, _ := strconv.Atoi(strings.Split(strings.TrimPrefix(srv.URL, "http://"), ":")[1])
	s := &Service{Workers: map[string]WorkerEndpoint{"w": {ManagementPort: port, TokenFile: path}}}
	status, e := s.probeWorker(t.Context(), "w")
	if e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(status)
	if strings.Contains(string(raw), "secret") || status.GPUAllocatedBytes == nil || *status.GPUAllocatedBytes != 42 {
		t.Fatal("unsafe/incomplete status projection", string(raw))
	}
	if _, e = s.probeWorker(t.Context(), "other"); publicError(e).Status != 409 {
		t.Fatal("unknown worker accepted")
	}
	body = strings.Repeat("x", 65537)
	if _, e = s.probeWorker(t.Context(), "w"); publicError(e).Status != 502 {
		t.Fatal("oversized response accepted")
	}
	body = `{"statusVersion":"1.0","workerRef":"other","health":"UP"}`
	if _, e = s.probeWorker(t.Context(), "w"); publicError(e).Status != 502 {
		t.Fatal("wrong logical worker accepted")
	}
	if e = os.Chmod(path, 0644); e != nil {
		t.Fatal(e)
	}
	if _, e = s.probeWorker(t.Context(), "w"); publicError(e).Status != 502 {
		t.Fatal("public token file accepted")
	}
}

type workerRow struct {
	values []any
	err    error
}

func (r workerRow) Scan(dest ...any) error {
	if r.err != nil {
		return r.err
	}
	for i, v := range r.values {
		reflect.ValueOf(dest[i]).Elem().Set(reflect.ValueOf(v))
	}
	return nil
}

type workerDB struct{ DB }

func (d workerDB) QueryRow(ctx context.Context, sql string, args ...any) pgx.Row {
	if strings.Contains(sql, "config_auth_sessions") {
		return workerRow{values: []any{"tenant-a", "user-a"}}
	}
	// Verify BOTH identity dimensions reach the scoped SQL lookup.
	if args[0] != "tenant-a" || args[1] != "user-a" || args[2] != "owned" {
		return workerRow{err: pgx.ErrNoRows}
	}
	return workerRow{values: []any{"owned", "GPU_WORKER", "Worker", "soulx", json.RawMessage(`{"workerRef":"w"}`), int64(1), true, false, false, "UNTESTED", "", "UNKNOWN", time.Now()}}
}
func TestWorkerStatusScopeAndAuthentication(t *testing.T) {
	s := &Service{DB: workerDB{}}
	for _, test := range []struct {
		id, cookie string
		want       int
	}{{"owned", "", 401}, {"foreign", strings.Repeat("x", 43), 404}, {"owned", strings.Repeat("x", 43), 409}} {
		r := httptest.NewRequest("GET", "/profiles/"+test.id+"/worker-status", nil)
		if test.cookie != "" {
			r.AddCookie(&http.Cookie{Name: "astralive_config_session", Value: test.cookie})
		}
		w := httptest.NewRecorder()
		s.PublicRouter().ServeHTTP(w, r)
		if w.Code != test.want {
			t.Fatalf("status %d want %d: %s", w.Code, test.want, w.Body.String())
		}
	}
}

func TestOwnProfileCannotProbeForeignPhysicalWorker(t *testing.T) {
	s := &Service{DB: workerDB{}, Workers: map[string]WorkerEndpoint{"w": {ManagementPort: 17088, TokenFile: "/never-read", AllowedScopes: []Scope{{"tenant-a", "user-b"}}}}}
	r := httptest.NewRequest("GET", "/profiles/owned/worker-status", nil)
	r.AddCookie(&http.Cookie{Name: "astralive_config_session", Value: strings.Repeat("x", 43)})
	w := httptest.NewRecorder()
	s.PublicRouter().ServeHTTP(w, r)
	if w.Code != 404 {
		t.Fatal("physical worker scope bypass", w.Code, w.Body.String())
	}
}
