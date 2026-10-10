package httpapi

import (
	"astralive/backend/db"
	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/app"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"bufio"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// Uses only explicit isolated DB/Redis URLs. Fake provider bundle is installed in
// a test-only Python launcher, without changing production admission or bindings.
func TestInteractionFormalCPU(t *testing.T) {
	if os.Getenv("RUN_INTERACTION_CPU") != "1" {
		t.Skip("RUN_INTERACTION_CPU=1 and disposable SQL/Redis required")
	}
	dbURL, redisURL := os.Getenv("CONFIG_TEST_DATABASE_URL"), os.Getenv("INTERACTION_TEST_REDIS_URL")
	if dbURL == "" || redisURL == "" {
		t.Fatal("explicit isolated URLs required")
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err = db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	raw, _ := json.Marshal(map[string]any{"activeKeyId": "test", "keys": map[string]string{"test": base64.StdEncoding.EncodeToString(key)}})
	write := func(name string, contents []byte) string {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, contents, 0600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	keyFile := write("keyring.json", raw)
	workerFile := write("worker-token", []byte(strings.Repeat("w", 40)))
	identityFile := write("identity-token", []byte(strings.Repeat("i", 40)))
	controlFile := write("control-token", []byte(strings.Repeat("c", 40)))
	scope := userconfig.Scope{TenantID: ids.New("test"), UserID: "owner"}
	foreign := userconfig.Scope{TenantID: scope.TenantID, UserID: "foreign"}
	cfg := &userconfig.Service{DB: pool, Vault: userconfig.Vault{Path: keyFile}, Origin: "https://astralive.test", Hosts: map[string]bool{"api.deepseek.com": true}, WorkerTokenFile: workerFile, IdentityTokenFile: identityFile, RuntimeControlTokenFile: controlFile, IntegrationEnabled: true}
	fakeWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("w", 40) {
			w.WriteHeader(401)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"statusVersion": "1.0", "workerRef": "cpu-fixture", "ready": true, "health": "UP", "mode": "gpu", "modelRevision": "9bc03de06bb0de82cd6bc477804512ae06144bf2", "workerEpoch": strings.Repeat("a", 32), "generationCancelStatus": map[string]any{"status": "NONE"}, "avatarCacheStatus": map[string]any{"avatarRef": "cpu-fixture-avatar", "status": "READY", "cacheId": strings.Repeat("b", 64)}})
	}))
	defer fakeWorker.Close()
	fakePort := fakeWorker.Listener.Addr().(*net.TCPAddr).Port
	cfg.Workers = map[string]userconfig.WorkerEndpoint{"cpu-fixture": {ManagementPort: fakePort, TokenFile: workerFile, AllowedScopes: []userconfig.Scope{scope}}}
	token, err := cfg.IssueSession(ctx, scope)
	if err != nil {
		t.Fatal(err)
	}
	other, err := cfg.IssueSession(ctx, foreign)
	if err != nil {
		t.Fatal(err)
	}
	cfgProfile := func(kind, provider, config, secret string) userconfig.Profile {
		p, e := cfg.Create(ctx, scope, userconfig.Input{Kind: kind, Name: "CPU fixture", Provider: provider, Config: json.RawMessage(config), Secret: secret})
		if e != nil {
			t.Fatal(e)
		}
		return p
	}
	llm := cfgProfile("LLM", "deepseek", `{"model":"deepseek-chat","maxTokens":128}`, "synthetic-not-valid-provider-key")
	tts := cfgProfile("TTS", "xiaoya", `{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}`, "")
	worker := cfgProfile("GPU_WORKER", "soulx", `{"workerRef":"cpu-fixture"}`, "")
	avatar := cfgProfile("AVATAR", "soulx", `{"avatarRef":"cpu-fixture-avatar","workerProfileId":"`+worker.ID+`"}`, "")
	if _, err = pool.Exec(ctx, `UPDATE config_profiles SET verification='VERIFIED' WHERE id=$1`, llm.ID); err != nil {
		t.Fatal(err)
	} // explicit FAKE upstream verification
	for _, p := range []userconfig.Profile{llm, tts, worker, avatar} {
		if _, err = cfg.Mutate(ctx, scope, p.ID, "default", userconfig.Input{ExpectedVersion: 1}); err != nil {
			t.Fatal(err)
		}
	}
	portListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := portListener.Addr().(*net.TCPAddr).Port
	_ = portListener.Close()
	runtimeURL := fmt.Sprintf("http://127.0.0.1:%d", port)
	rt := runtime.New(runtimeURL)
	rt.Client.Transport = userconfig.TokenTransport{Path: controlFile, Base: &http.Transport{Proxy: nil}}
	cfg.RuntimeStatusURL = runtimeURL
	service := app.New(pool, rt, slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Integration = cfg
	schedulerConfig := interaction.DefaultConfig()
	schedulerConfig.Interval = 200 * time.Millisecond
	service.Interaction = app.NewInteraction(ctx, service, cfg, schedulerConfig)
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		t.Fatal(err)
	}
	rc := redis.NewClient(opts)
	defer rc.Close()
	h := &Server{S: service, Config: cfg, Redis: rc, Env: "development", Token: strings.Repeat("t", 40), Log: service.Log}
	server := httptest.NewServer(h.Router())
	defer server.Close()
	wd, _ := os.Getwd()
	root := filepath.Clean(filepath.Join(wd, "../../.."))
	python := os.Getenv("INTERACTION_TEST_PYTHON")
	if python == "" {
		python = filepath.Join(root, "runtime/.venv/bin/python")
	}
	command := exec.Command(python, filepath.Join(root, "runtime/tests/interaction_cpu_server.py"), strconv.Itoa(port))
	command.Env = append(os.Environ(), "SESSION_BINDINGS_ENABLED=true", "APP_ENV=development", "CONFIG_BACKEND_URL="+server.URL, "CONFIG_WORKER_TOKEN_FILE="+workerFile, "RUNTIME_CONTROL_TOKEN_FILE="+controlFile, "REDIS_URL="+redisURL, "TOOL_BASE_URL="+server.URL, "TOOL_TOKEN="+h.Token)
	logFile, err := os.Create(filepath.Join(dir, "runtime.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer logFile.Close()
	command.Stdout = logFile
	command.Stderr = logFile
	if err = command.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = command.Process.Signal(os.Interrupt); _ = command.Wait() }()
	wait := func(label string, fn func() bool) {
		t.Helper()
		deadline := time.Now().Add(12 * time.Second)
		for time.Now().Before(deadline) {
			if fn() {
				return
			}
			time.Sleep(20 * time.Millisecond)
		}
		data, _ := os.ReadFile(logFile.Name())
		t.Log(string(data))
		t.Fatal("timeout", label)
	}
	wait("runtime health", func() bool { _, e := rt.Health(ctx); return e == nil })
	go func() { _ = eventbus.New(rc, service, "dh.runtime.events.v1", service.Log).Run(ctx) }()
	call := func(token, method, path, body string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Origin", cfg.Origin)
		r.Header.Set("Idempotency-Key", ids.New("test"))
		if token != "" {
			r.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: token})
		}
		w := httptest.NewRecorder()
		h.Router().ServeHTTP(w, r)
		return w
	}
	getID := func(w *httptest.ResponseRecorder, key string) string {
		t.Helper()
		if w.Code != 201 {
			t.Fatal(w.Code, w.Body.String())
		}
		var packet struct {
			Data map[string]string `json:"data"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &packet)
		return packet.Data[key]
	}
	avatarID := getID(call(token, "POST", "/api/v1/avatars", `{"name":"CPU","engine":"MOCK"}`), "avatarId")
	voiceID := getID(call(token, "POST", "/api/v1/voices", `{"name":"CPU","provider":"MOCK","providerVoiceId":"cpu"}`), "voiceId")
	productID := getID(call(token, "POST", "/api/v1/products", `{"name":"测试卫衣","description":"棉质","price":129.9,"currency":"CNY","stock":27,"sizes":["M","L","XL"]}`), "productId")
	roomID := getID(call(token, "POST", "/api/v1/live-rooms", `{"name":"CPU room","avatarId":"`+avatarID+`","voiceId":"`+voiceID+`","activeProductId":"`+productID+`","systemPrompt":"可信测试主播提示"}`), "roomId")
	sid := getID(call(token, "POST", "/api/v1/live-sessions", `{"roomId":"`+roomID+`"}`), "sessionId")
	var bindingBefore []byte
	if err = pool.QueryRow(ctx, `SELECT summary FROM session_provider_bindings WHERE session_id=$1`, sid).Scan(&bindingBefore); err != nil {
		t.Fatal(err)
	}
	if w := call(token, "POST", "/api/v1/live-sessions/"+sid+"/start", `{}`); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	wait("LIVE", func() bool { s, e := service.Q.GetSession(ctx, sid); return e == nil && s.Status == "LIVE" })
	base := "/api/v0.4/interaction/" + sid
	if w := call("", "GET", base+"/", ""); w.Code != 401 {
		t.Fatal("anonymous", w.Code)
	}
	if w := call(other, "POST", base+"/mock", `{"text":"多少钱？","users":1}`); w.Code != 404 {
		t.Fatal("foreign", w.Code)
	}
	hostile := httptest.NewRequest("POST", base+"/mock", strings.NewReader(`{"text":"x","users":1}`))
	hostile.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: token})
	hostile.Header.Set("Origin", "https://evil.test")
	w := httptest.NewRecorder()
	h.Router().ServeHTTP(w, hostile)
	if w.Code != 403 {
		t.Fatal("csrf", w.Code)
	}
	if w := call(token, "POST", base+"/mock", `{"text":"多少钱？","users":1001}`); w.Code != 422 {
		t.Fatal("limit", w.Code)
	}
	if w := call(token, "PUT", base+"/mode", `{"mode":"OPERATOR_OVERRIDE"}`); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	// A second synthetic LIVE DB Session for the same Room cannot allocate a
	// second candidate queue. It has no Runtime; this is an admission guard fixture.
	sibling, e := service.Q.CreateSession(ctx, dbgen.CreateSessionParams{ID: ids.New("session"), RoomID: roomID})
	if e != nil {
		t.Fatal(e)
	}
	if e = cfg.Own(ctx, scope, "session", sibling.ID); e != nil {
		t.Fatal(e)
	}
	_, e = pool.Exec(ctx, `UPDATE live_sessions SET status='LIVE' WHERE id=$1`, sibling.ID)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = service.Interaction.Ensure(ctx, scope, sibling.ID); e != app.ErrConflict {
		t.Fatal("same Room second queue admitted", e)
	}
	_, _ = pool.Exec(ctx, `UPDATE live_sessions SET status='ENDED' WHERE id=$1`, sibling.ID)
	// SSE observes real Redis→SQL→hub events, with product cookie verification.
	req, _ := http.NewRequestWithContext(ctx, "GET", server.URL+"/api/v1/live-sessions/"+sid+"/events", nil)
	req.AddCookie(&http.Cookie{Name: userconfig.ProductCookie, Value: token})
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var sseMu sync.Mutex
	frames := []string{}
	go func() {
		scanner := bufio.NewScanner(resp.Body)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.HasPrefix(line, "event:") {
				sseMu.Lock()
				frames = append(frames, line)
				sseMu.Unlock()
			}
		}
	}()
	if w := call(token, "POST", base+"/mock", `{"text":"多少钱？","users":10}`); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	wait("ten received", func() bool { return service.Interaction.Snapshot(sid).Counters.Input == 10 })
	var count int
	_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1`, sid).Scan(&count)
	if count != 0 {
		t.Fatal("unselected utterances", count)
	}
	if w := call(token, "PUT", base+"/mode", `{"mode":"IDLE"}`); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	wait("selected completed", func() bool {
		_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1 AND status='COMPLETED'`, sid).Scan(&count)
		return count == 1
	})
	snap := service.Interaction.Snapshot(sid)
	if snap.Counters.Selected != 1 || snap.Counters.Delivered != 1 || snap.Counters.Merged != 9 {
		t.Fatal(snap)
	}
	if w := call(token, "POST", "/api/v1/live-sessions/"+sid+"/interrupt", `{"reason":"OPERATOR_INTERRUPT"}`); w.Code != 202 {
		t.Fatal("operator interrupt", w.Code, w.Body.String())
	}
	if service.Interaction.Snapshot(sid).Mode != interaction.OperatorOverride {
		t.Fatal("operator control not prioritized")
	}
	if w := call(token, "PUT", base+"/mode", `{"mode":"IDLE"}`); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := call(token, "POST", base+"/mock", `{"text":"主播今天心情怎么样？","users":1}`); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	wait("selected LLM chat completed", func() bool {
		_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1 AND status='COMPLETED'`, sid).Scan(&count)
		return count == 2
	})
	snap = service.Interaction.Snapshot(sid)
	var bindingAfter []byte
	_ = pool.QueryRow(ctx, `SELECT summary FROM session_provider_bindings WHERE session_id=$1`, sid).Scan(&bindingAfter)
	if string(bindingBefore) != string(bindingAfter) {
		t.Fatal("binding mutated")
	}
	// Persisted receipt prevents delivery on a restarted controller with the same event.
	selected := snap.Current.Event
	service.Interaction.Stop(sid)
	service.Interaction = app.NewInteraction(ctx, service, cfg, schedulerConfig)
	restarted, err := service.Interaction.Ensure(ctx, scope, sid)
	if err != nil {
		t.Fatal(err)
	}
	if err = restarted.Receive(ctx, selected); err != nil {
		t.Fatal(err)
	}
	_ = restarted.Tick(ctx)
	if v := restarted.Snapshot(); v.Counters.Failed != 1 || v.Counters.Delivered != 0 {
		t.Fatal("restart duplicate", v)
	}
	_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1`, sid).Scan(&count)
	if count != 2 {
		t.Fatal("restart created duplicate", count)
	}
	// Frozen developer API still always creates priority80 Utterance and returns 202.
	oldBody := `{"eventType":"COMMENT","roomId":"` + roomID + `","user":{"externalId":"legacy","nickname":"测试"},"payload":{"text":"你好"}}`
	if w := call(token, "POST", "/api/v1/dev/platform-events", oldBody); w.Code != 202 {
		t.Fatal("legacy", w.Code, w.Body.String())
	}
	wait("legacy completed", func() bool {
		_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1 AND status='COMPLETED'`, sid).Scan(&count)
		return count == 3
	})
	rejectRequest, _ := http.NewRequest("POST", runtimeURL+"/internal/test/reject-next", nil)
	rejectRequest.Header.Set("Authorization", "Bearer "+strings.Repeat("c", 40))
	rejectResponse, e := http.DefaultClient.Do(rejectRequest)
	if e != nil {
		t.Fatal(e)
	}
	_ = rejectResponse.Body.Close()
	if rejectResponse.StatusCode != 200 {
		t.Fatal("fake injection refused")
	}
	rejectedEvent := selected
	rejectedEvent.SourceEventID = "fake-rejected-" + ids.New("event")
	rejectedEvent.UserExternalID = "new-viewer"
	rejectedEvent.Content = "你好主播"
	rejectedEvent.TraceID = ""
	if err = restarted.Receive(ctx, rejectedEvent); err != nil {
		t.Fatal(err)
	}
	wait("Runtime rejection projected", func() bool {
		var failed int
		_ = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1 AND status='FAILED'`, sid).Scan(&failed)
		return failed == 1
	})
	if w := call(token, "POST", base+"/replay", `{"rate":1,"count":100}`); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := call(token, "POST", "/api/v1/live-sessions/"+sid+"/stop", `{}`); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	wait("ENDED", func() bool { s, e := service.Q.GetSession(ctx, sid); return e == nil && s.Status == "ENDED" })
	if v := service.Interaction.Snapshot(sid); !v.Stopped || v.Candidates != 0 {
		t.Fatal("stop cleanup", v)
	}
	wait("adapter stopped", func() bool { return service.Interaction.Snapshot(sid).Adapter.State == "STOPPED" })
	if w := call(token, "POST", base+"/mock", `{"text":"你好","users":1}`); w.Code != 409 {
		t.Fatal("post stop", w.Code)
	}
	if w := call(token, "POST", "/api/v1/dev/platform-events", oldBody); w.Code != 409 {
		t.Fatal("legacy stopped", w.Code)
	}
	// Formal binding release actually deletes encrypted snapshot.
	var released bool
	_ = pool.QueryRow(ctx, `SELECT released_at IS NOT NULL FROM session_provider_bindings WHERE session_id=$1`, sid).Scan(&released)
	if !released {
		t.Fatal("binding unreleased")
	}
	request, _ := http.NewRequest("GET", runtimeURL+"/internal/test/interaction", nil)
	request.Header.Set("Authorization", "Bearer "+strings.Repeat("c", 40))
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var diagnostics map[string]any
	if err = json.NewDecoder(response.Body).Decode(&diagnostics); err != nil {
		t.Fatal(err)
	}
	if diagnostics["sessions"] != float64(0) || diagnostics["leases"] != float64(0) {
		t.Fatal("runtime cleanup", diagnostics)
	}
	wait("SSE completed and ended", func() bool {
		sseMu.Lock()
		defer sseMu.Unlock()
		joined := strings.Join(frames, "\n")
		return strings.Contains(joined, "utterance.completed") && strings.Contains(joined, "session.ended")
	})
	// Safe evidence only: synthetic trace IDs and counters, never cookies/provider payloads.
	if out := os.Getenv("INTERACTION_TEST_EVIDENCE"); out != "" {
		evidence := map[string]any{"classification": "FORMAL_SESSION_CPU_FAKE_PROVIDERS", "selectedCounters": snap.Counters, "selectionLatency": snap.Latency, "faultPhaseCounters": service.Interaction.Snapshot(sid).Counters, "runtime": diagnostics, "checks": []string{"ownership", "csrf", "unselected_no_utterance", "pinned_binding", "redis_events", "SSE", "restart_at_most_once", "legacy_202_409", "stop_cleanup", "runtime_429_fake_injection"}}
		data, _ := json.MarshalIndent(evidence, "", "  ")
		if err = os.WriteFile(out, append(data, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}

}
