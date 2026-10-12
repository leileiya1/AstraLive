package narration_test

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"astralive/backend/db"
	"astralive/backend/internal/app"
	localconfig "astralive/backend/internal/config"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/recovery"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
	goruntime "runtime"
)

// This opt-in gate has NO injected LLM/TTS/avatar/media factory, fake binding
// GET, direct business-row fixture or synthetic speech/marker renderer. It
// runs production Go components in the test process, not cmd/server. F owns
// source pinning, isolated PostgreSQL, cloud lifecycle and independent audit.
func TestPostgresRealGPUContinuityGolden(t *testing.T) {
	if os.Getenv("ASTRALIVE_GOLDEN_REAL") != "true" {
		t.Skip("ASTRALIVE_GOLDEN_REAL=true and explicit real-provider inputs required")
	}
	required := func(name string) string {
		t.Helper()
		value := os.Getenv(name)
		if value == "" {
			t.Fatalf("missing Golden input %s", name)
		}
		return value
	}
	integer := func(name string, fallback int) int {
		t.Helper()
		value := os.Getenv(name)
		if value == "" {
			return fallback
		}
		n, err := strconv.Atoi(value)
		if err != nil || n <= 0 {
			t.Fatalf("invalid Golden integer %s", name)
		}
		return n
	}
	python := required("DURABILITY_TEST_PYTHON")
	keyFile, modelDir := required("ASTRALIVE_GOLDEN_LLM_KEY_FILE"), required("ASTRALIVE_GOLDEN_TTS_MODEL_DIR")
	inferenceToken, managementToken := required("ASTRALIVE_GOLDEN_WORKER_TOKEN_FILE"), required("ASTRALIVE_GOLDEN_WORKER_MANAGEMENT_TOKEN_FILE")
	workerRef, avatarRef, assetSHA := required("ASTRALIVE_GOLDEN_WORKER_REF"), required("ASTRALIVE_GOLDEN_AVATAR_REF"), required("ASTRALIVE_GOLDEN_ASSET_SHA256")
	fixture := required("ASTRALIVE_GOLDEN_PLAN_FILE")
	profile := required("ASTRALIVE_GOLDEN_PROFILE")
	inferencePort, managementPort := integer("ASTRALIVE_GOLDEN_WORKER_PORT", 0), integer("ASTRALIVE_GOLDEN_WORKER_MANAGEMENT_PORT", 0)
	mode := os.Getenv("NARRATION_GOLDEN_MODE")
	if mode == "" {
		mode = "short"
	}
	if mode != "short" && mode != "ten-minute" && mode != "soak" {
		t.Fatal("invalid Golden mode")
	}
	localMode := os.Getenv("ASTRALIVE_GOLDEN_LOCAL_TRANSPORT")
	if localMode == "" {
		localMode = "tcp"
	}
	if localMode != "tcp" && localMode != "uds" {
		t.Fatal("invalid Golden local transport")
	}
	if localMode == "uds" && goruntime.GOOS != "darwin" && goruntime.GOOS != "linux" {
		t.Skip("real UDS Golden unsupported: NOT TESTED")
	}
	seconds, seed := integer("NARRATION_GOLDEN_SECONDS", 60), integer("NARRATION_GOLDEN_SEED", 20261012)
	out := required("NARRATION_MEDIA_EVIDENCE_DIR")
	if err := os.MkdirAll(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, file := range []string{keyFile, inferenceToken, managementToken} {
		if _, err := userconfig.ReadServiceToken(file); err != nil {
			t.Fatal("invalid private Golden credential input")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	base, err := pgxpool.New(ctx, required("DURABILITY_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer base.Close()
	schema := ids.New("golden")
	if _, err = base.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); err != nil {
		t.Fatal(err)
	}
	defer base.Exec(context.Background(), "DROP SCHEMA "+pgx.Identifier{schema}.Sanitize()+" CASCADE")
	config, err := pgxpool.ParseConfig(required("DURABILITY_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err = db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	private := t.TempDir()
	secret := func() string {
		raw := make([]byte, 32)
		if _, e := rand.Read(raw); e != nil {
			t.Fatal(e)
		}
		return hex.EncodeToString(raw)
	}
	writePrivate := func(name string, value any) string {
		path := filepath.Join(private, name)
		raw, e := json.Marshal(value)
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(path, raw, 0600); e != nil {
			t.Fatal(e)
		}
		return path
	}
	writeToken := func(name string) string {
		path := filepath.Join(private, name)
		if e := os.WriteFile(path, []byte(secret()), 0600); e != nil {
			t.Fatal(e)
		}
		return path
	}
	journalToken, controlToken, bindingToken, identityToken, toolToken := writeToken("journal"), writeToken("control"), writeToken("binding"), writeToken("identity"), writeToken("tool")
	password := secret()
	passwordFile := filepath.Join(private, "operator-password")
	if err = os.WriteFile(passwordFile, []byte(password), 0600); err != nil {
		t.Fatal(err)
	}
	passwordHash, err := bcrypt.GenerateFromPassword([]byte(password), 12)
	password = ""
	if err != nil {
		t.Fatal(err)
	}
	scope := userconfig.Scope{TenantID: "golden-tenant", UserID: "golden-user"}
	operator := writePrivate("operator.json", userconfig.OperatorLogin{Username: "golden", PasswordHash: string(passwordHash), Scope: scope})
	key := make([]byte, 32)
	if _, err = rand.Read(key); err != nil {
		t.Fatal(err)
	}
	keyring := writePrivate("keyring.json", userconfig.Keyring{Active: "golden", Keys: map[string]string{"golden": base64.StdEncoding.EncodeToString(key)}})
	registry := writePrivate("inference-registry.json", map[string]any{"registryVersion": "1.0", "workers": map[string]any{workerRef: map[string]any{
		"port": inferencePort, "tokenFile": inferenceToken, "avatarRef": avatarRef, "assetSHA256": assetSHA, "allowSimulation": false, "allowedScopes": []userconfig.Scope{scope}}}})
	freePort := func() int {
		listener, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			t.Fatal(e)
		}
		port := listener.Addr().(*net.TCPAddr).Port
		listener.Close()
		return port
	}
	runtimePort, rtmpPort := freePort(), freePort()
	runtimeURL := fmt.Sprintf("http://127.0.0.1:%d", runtimePort)
	ipcRoot, err := filepath.EvalSymlinks(os.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	ipcDir, err := os.MkdirTemp(ipcRoot, "ag-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(ipcDir)
	if err = os.Chmod(ipcDir, 0700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(ipcDir, "r.sock")
	rt, err := runtime.NewLocal(runtimeURL, localconfig.LocalTransport{Mode: localMode, SocketPath: socketPath, Fallback: "disabled"})
	if err != nil {
		t.Fatal(err)
	}
	controlBase := rt.Client.Transport
	if controlBase == nil {
		controlBase = &http.Transport{Proxy: nil}
	}
	rt.Client.Transport = userconfig.TokenTransport{Path: controlToken, Base: controlBase}
	rt.Client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	logFile, err := os.OpenFile(filepath.Join(out, "backend.log"), os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer logFile.Close()
	log := slog.New(slog.NewJSONHandler(logFile, nil))
	service := app.New(pool, rt, log)
	service.Durable = durability.New(pool)
	stageSettings := narration.StagingSettings{Enabled: true, LimitsRevision: &profile}
	if gate := os.Getenv("ASTRALIVE_GOLDEN_SHORT_GPU_GATE_SHA256"); gate != "" {
		stageSettings.ShortGateSHA256 = &gate
	}
	if err = stageSettings.Validate(); err != nil {
		t.Fatal(err)
	}
	service.StagingSettings = stageSettings
	service.AttachNarration(narration.New(service.Durable))
	// Staging capture settings are composed here after the exact production
	// helper is frozen. Without that implementation this real gate fails closed.
	cfg := &userconfig.Service{DB: pool, Vault: userconfig.Vault{Path: keyring}, OperatorFile: operator, IntegrationEnabled: true,
		RuntimeStatusURL: rt.Base, RuntimeTransport: controlBase, RuntimeControlTokenFile: controlToken, WorkerTokenFile: bindingToken, IdentityTokenFile: identityToken,
		Hosts: map[string]bool{"api.deepseek.com": true}, Workers: map[string]userconfig.WorkerEndpoint{workerRef: {ManagementPort: managementPort, TokenFile: managementToken, AllowedScopes: []userconfig.Scope{scope}}}}
	service.Integration = cfg
	interactionConfig := interaction.DefaultConfig()
	interactionConfig.TTL = time.Minute
	service.Interaction = app.NewInteraction(ctx, service, cfg, interactionConfig)
	toolValue, err := userconfig.ReadServiceToken(toolToken)
	if err != nil {
		t.Fatal(err)
	}
	h := (&httpapi.Server{S: service, Config: cfg, Env: "development", Token: toolValue, Log: log, JournalTokenFile: journalToken}).Router()
	internal := httptest.NewServer(h)
	defer internal.Close()
	root, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	html, err := os.ReadFile(filepath.Join(root, "runtime/tests/fixtures/golden_browser.html"))
	if err != nil {
		t.Fatal(err)
	}
	publicMux := http.NewServeMux()
	publicMux.Handle("/", h)
	publicMux.HandleFunc("/__golden/browser", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(html)
	})
	public := httptest.NewTLSServer(publicMux)
	defer public.Close()
	cfg.Origin = public.URL
	runtimeLog := filepath.Join(out, "runtime.log")
	runtimeOutput, err := os.OpenFile(runtimeLog, os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer runtimeOutput.Close()
	receiverLog, err := os.OpenFile(filepath.Join(out, "rtmp-receiver.log"), os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer receiverLog.Close()
	rtmpURL := fmt.Sprintf("rtmp://127.0.0.1:%d/live/golden", rtmpPort)
	receiver := exec.Command("ffmpeg", "-hide_banner", "-loglevel", "error", "-listen", "1", "-i", rtmpURL, "-c", "copy", "-y", filepath.Join(out, "rtmp.flv"))
	receiver.Stderr = receiverLog
	receiver.Stdout = io.Discard
	if err = receiver.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if receiver.ProcessState == nil {
			receiver.Process.Kill()
			receiver.Wait()
		}
	}()
	env := []string{}
	for _, name := range []string{"PATH", "HOME", "TMPDIR", "LANG"} {
		if value := os.Getenv(name); value != "" {
			env = append(env, name+"="+value)
		}
	}
	env = append(env, "PYTHONPATH="+filepath.Join(root, "runtime")+string(os.PathListSeparator)+root,
		"ASTRALIVE_LOCAL_TRANSPORT="+localMode, "ASTRALIVE_LOCAL_FALLBACK=disabled", "ASTRALIVE_RUNTIME_UDS_PATH="+socketPath, "AI_RUNTIME_URL="+runtimeURL,
		"APP_ENV=development", "ASTRALIVE_DURABILITY_ENABLED=true", "ASTRALIVE_EVENT_MODE=postgres_only", "REDIS_URL=redis://127.0.0.1:1",
		"ASTRALIVE_CONTINUITY_ENABLED=true", "ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED=true", "ASTRALIVE_SOULX_STAGING_ENABLED=true",
		"ASTRALIVE_SOULX_STAGING_LIMITS_REVISION="+profile, "ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256="+os.Getenv("ASTRALIVE_GOLDEN_SHORT_GPU_GATE_SHA256"),
		"SESSION_BINDINGS_ENABLED=true", "CONFIG_BACKEND_URL="+internal.URL, "RUNTIME_JOURNAL_TOKEN_FILE="+journalToken,
		"RUNTIME_CONTROL_TOKEN_FILE="+controlToken, "CONFIG_WORKER_TOKEN_FILE="+bindingToken, "CONFIG_IDENTITY_TOKEN_FILE="+identityToken,
		"RUNTIME_EVENT_SPOOL_DIR="+filepath.Join(private, "spool"), "GPU_WORKER_INFERENCE_REGISTRY_FILE="+registry,
		"SESSION_PROVIDER_STATE_DIR="+filepath.Join(private, "providers"), "TTS_MODEL_DIR="+modelDir, "TOOL_BASE_URL="+internal.URL,
		"TOOL_TOKEN="+toolValue, "MOCK_LLM=false", "MOCK_TTS=false", "MOCK_AVATAR=false", "MOCK_MEDIA=false", "WEBRTC_ENABLED=true",
		"RTMP_ENABLED=true", "RTMP_PUBLISH_URL="+rtmpURL, "RTMP_WIDTH=512", "RTMP_HEIGHT=512", "RTMP_FPS=25",
		"ASTRALIVE_STAGING_OBSERVER_DIR="+filepath.Join(out, "staged-observer"),
		"RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS=0.2", "TTS_NUM_THREADS=2")
	child := exec.Command(python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", fmt.Sprint(runtimePort), "--log-level", "warning")
	if localMode == "uds" {
		child = exec.Command(python, "-m", "app.local_listener")
	}
	child.Dir = root
	child.Env = env
	child.Stdout = runtimeOutput
	child.Stderr = runtimeOutput
	if err = child.Start(); err != nil {
		t.Fatal(err)
	}
	processes, e := json.MarshalIndent(map[string]any{"goPID": os.Getpid(), "runtimePID": child.Process.Pid, "rtmpReceiverPID": receiver.Process.Pid, "source": os.Getenv("ASTRALIVE_GOLDEN_SOURCE_SHA"), "localTransport": localMode, "scope": "actual local test-process components; remote GPU operator evidence separate"}, "", "  ")
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(out, "processes.json"), processes, 0600); e != nil {
		t.Fatal(e)
	}
	defer func() {
		if child.ProcessState == nil {
			child.Process.Signal(os.Interrupt)
			done := make(chan error, 1)
			go func() { done <- child.Wait() }()
			select {
			case <-done:
			case <-time.After(15 * time.Second):
				child.Process.Kill()
				<-done
			}
		}
	}()
	for n := 0; n < 100; n++ {
		if health, e := rt.Health(ctx); e == nil && health.Status == "UP" {
			break
		}
		if n == 99 {
			t.Fatal("actual Runtime startup unavailable")
		}
		time.Sleep(100 * time.Millisecond)
	}
	dispatcher := &durability.Dispatcher{Store: service.Durable, Remote: rt, Log: log}
	go dispatcher.Run(ctx)
	go (&recovery.Coordinator{Store: service.Durable, Dispatcher: dispatcher, Log: log}).Run(ctx)
	go eventbus.RunPostgres(ctx, service, log)
	go service.Narration.Run(ctx)
	observer := exec.Command(python, filepath.Join(root, "runtime/tests/narration_real_golden.py"), "--backend", public.URL, "--username", "golden",
		"--password-file", passwordFile, "--llm-key-file", keyFile, "--worker-ref", workerRef, "--avatar-ref", avatarRef,
		"--mode", mode, "--local-transport", localMode, "--fixture", fixture, "--runtime-log", runtimeLog, "--output", filepath.Join(out, "observer"), "--seconds", fmt.Sprint(seconds), "--seed", fmt.Sprint(seed))
	observer.Dir = root
	observer.Env = env
	observerLog, err := os.OpenFile(filepath.Join(out, "observer.log"), os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	observer.Stdout = observerLog
	observer.Stderr = observerLog
	err = observer.Run()
	observerLog.Close()
	// Retain only business/media proof, never private bindings/vault/credentials.
	dump := map[string]json.RawMessage{}
	queries := map[string]string{
		"sessions":          `SELECT COALESCE(jsonb_agg(to_jsonb(s)),'[]') FROM live_sessions s`,
		"narrations":        `SELECT COALESCE(jsonb_agg(to_jsonb(n)),'[]') FROM v05_narrations n`,
		"segments":          `SELECT COALESCE(jsonb_agg(to_jsonb(s)),'[]') FROM v05_segments s`,
		"attempts":          `SELECT COALESCE(jsonb_agg(to_jsonb(a)),'[]') FROM v05_segment_attempts a`,
		"turns":             `SELECT COALESCE(jsonb_agg(to_jsonb(t)),'[]') FROM v05_interaction_turns t`,
		"commits":           `SELECT COALESCE(jsonb_agg(to_jsonb(c)),'[]') FROM v05_timeline_commits c`,
		"receipts":          `SELECT COALESCE(jsonb_agg(to_jsonb(r)),'[]') FROM v05_receipts r`,
		"runs":              `SELECT COALESCE(jsonb_agg(to_jsonb(r)),'[]') FROM v05_session_runs r`,
		"commandIdentities": `SELECT COALESCE(jsonb_agg(jsonb_build_object('commandId',command_id,'sessionId',session_id,'runEpoch',run_epoch,'traceId',trace_id,'commandType',command_type,'narrationId',payload_envelope->'narrationId','segmentId',payload_envelope->'segmentId','lane',payload_envelope->'lane','timelineEpoch',payload_envelope->'timelineEpoch','beatId',payload_envelope->'payload'->'beatId','interactionTurnId',payload_envelope->'payload'->'interactionTurnId','attemptId',payload_envelope->'payload'->'attemptId','utteranceId',payload_envelope->'payload'->'utteranceId')),'[]') FROM v05_outbox WHERE command_type='COMMIT_SEGMENT'`,
		"observations":      `SELECT COALESCE(jsonb_agg(jsonb_build_object('command_id',command_id,'operation',operation,'observation_hash',observation_hash,'response_json',response_json,'session_id',session_id,'run_epoch',run_epoch)),'[]') FROM v05_timeline_observations`,
		"bindingRelease":    `SELECT COALESCE(jsonb_agg(jsonb_build_object('sessionId',session_id,'released',released_at IS NOT NULL)),'[]') FROM session_provider_bindings`,
	}
	for name, query := range queries {
		var raw []byte
		if e := pool.QueryRow(context.Background(), query).Scan(&raw); e != nil {
			t.Error("proof dump unavailable", name)
		} else {
			dump[name] = raw
		}
	}
	encoded, e := json.MarshalIndent(dump, "", "  ")
	if e != nil {
		t.Error(e)
	} else if e = os.WriteFile(filepath.Join(out, "sql-proof.json"), encoded, 0600); e != nil {
		t.Error(e)
	}
	if err != nil {
		t.Fatal("real Golden observer failed; inspect sanitized observer/runtime/SQL evidence")
	}
	var completeTurns int
	if err = pool.QueryRow(ctx, `SELECT count(*) FROM v05_interaction_turns WHERE state='COMPLETED'`).Scan(&completeTurns); err != nil {
		t.Fatal(err)
	}
	var authored struct {
		Questions []string `json:"questions"`
	}
	fixtureBytes, readErr := os.ReadFile(fixture)
	if readErr != nil || json.Unmarshal(fixtureBytes, &authored) != nil || len(authored.Questions) == 0 {
		t.Fatal("invalid authored Golden questions")
	}
	if mode == "ten-minute" && len(authored.Questions) < 5 {
		t.Fatal("formal G1 needs 5 questions")
	}
	if completeTurns < len(authored.Questions) {
		t.Fatalf("only %d completed audience answers; no simulated PASS", completeTurns)
	}
	var bad int
	if err = pool.QueryRow(ctx, `SELECT count(*) FROM live_sessions se JOIN session_provider_bindings b ON b.session_id=se.id WHERE se.status<>'ENDED' OR b.released_at IS NULL`).Scan(&bad); err != nil {
		t.Fatal(err)
	}
	if bad != 0 {
		t.Fatal("normal Stop/binding release incomplete")
	}
	t.Log("REAL_PROVIDER_OBSERVATION_COMPLETE: production Go HTTP components in test process; actual Runtime/LLM/TTS/GPU/Chrome/RTMP. Correlated AV/human naturalness/SLA require F independent audit.")
}
