package userconfig

import (
	"astralive/backend/generated/dbgen"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/ids"
	"context"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"net/url"
	"sort"
	"time"
)

type ProviderSummary struct {
	ProfileID string    `json:"profileId"`
	Kind      string    `json:"kind"`
	Provider  string    `json:"provider"`
	Version   int64     `json:"version"`
	UpdatedAt time.Time `json:"updatedAt"`
}
type SessionProviders struct {
	IntegrationVersion string            `json:"integrationVersion"`
	SessionID          string            `json:"sessionId"`
	BindingID          string            `json:"bindingId"`
	CapturedAt         time.Time         `json:"capturedAt"`
	ExpiresAt          time.Time         `json:"expiresAt"`
	Profiles           []ProviderSummary `json:"profiles"`
	Mode               string            `json:"mode"`
	ErrorCode          string            `json:"errorCode"`
	WorkerEpoch        string            `json:"workerEpoch"`
}

// WorkerChoice exposes only scoped logical references and the existing status
// projection. Physical ports and authentication files stay in the registry.
type WorkerChoice struct {
	WorkerRef string `json:"workerRef"`
	AvatarRef string `json:"avatarRef"`
	Ready     bool   `json:"ready"`
	ErrorCode string `json:"errorCode"`
}

func (s *Service) WorkerChoicesRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(s.ProductAuth)
	r.Get("/", func(w http.ResponseWriter, r *http.Request) {
		choices := []WorkerChoice{}
		for ref, entry := range s.Workers {
			for _, allowed := range entry.AllowedScopes {
				if allowed != scopeOf(r) {
					continue
				}
				choice := WorkerChoice{WorkerRef: ref}
				status, e := s.probeWorker(r.Context(), ref)
				if e != nil {
					choice.ErrorCode = "WORKER_UNAVAILABLE"
				} else {
					choice.AvatarRef = status.AvatarCacheStatus.AvatarRef
					choice.Ready = status.Ready && status.Health == "UP" && status.Mode == "gpu" && status.AvatarCacheStatus.Status == "READY"
				}
				choices = append(choices, choice)
				break
			}
		}
		sort.Slice(choices, func(i, j int) bool { return choices[i].WorkerRef < choices[j].WorkerRef })
		write(w, r, 200, choices, nil)
	})
	return r
}

func ValidateSessionBinding(b Binding) error {
	by := map[string]Profile{}
	for _, p := range b.Profiles {
		if _, ok := by[p.Kind]; ok {
			return fault(409, "PROVIDER_BINDING_INVALID", "duplicate provider kind")
		}
		by[p.Kind] = p
	}
	for _, kind := range []string{"LLM", "TTS", "AVATAR", "GPU_WORKER"} {
		if p, ok := by[kind]; !ok || !p.Enabled || !p.Default {
			return fault(409, "PROVIDER_NOT_CONFIGURED", "select all required provider defaults")
		}
	}
	llm := by["LLM"]
	if llm.Provider != "deepseek" {
		return fault(409, "PROVIDER_UNSUPPORTED", "this integration supports DeepSeek only")
	}
	if llm.Verification != "VERIFIED" || !llm.CredentialConfigured {
		return fault(409, "CONFIG_NOT_VERIFIED", "verify the selected LLM version")
	}
	var tts, avatar, worker providerConfig
	if strictJSON(by["TTS"].Config, &tts) != nil || by["TTS"].Provider != "xiaoya" || tts.VoiceID != "xiao_ya" || tts.ModelRef != "xiaoya-default" || tts.Speed != 1 {
		return fault(409, "PROVIDER_UNSUPPORTED", "XiaoYa integration requires preset speed 1")
	}
	if strictJSON(by["AVATAR"].Config, &avatar) != nil || strictJSON(by["GPU_WORKER"].Config, &worker) != nil || by["AVATAR"].Provider != "soulx" || by["GPU_WORKER"].Provider != "soulx" || avatar.WorkerProfileID != by["GPU_WORKER"].ID {
		return fault(409, "PROVIDER_BINDING_INVALID", "select matching SoulX avatar and worker")
	}
	return nil
}
func (s *Service) ValidateWorker(ctx context.Context, scope Scope, b Binding) error {
	var av, wo providerConfig
	for _, p := range b.Profiles {
		if p.Kind == "AVATAR" {
			_ = json.Unmarshal(p.Config, &av)
		}
		if p.Kind == "GPU_WORKER" {
			_ = json.Unmarshal(p.Config, &wo)
		}
	}
	entry, ok := s.Workers[wo.WorkerRef]
	if !ok {
		return fault(409, "WORKER_UNREGISTERED", "worker not registered")
	}
	allowed := false
	for _, v := range entry.AllowedScopes {
		if v == scope {
			allowed = true
		}
	}
	if !allowed {
		return ErrNotFound
	}
	status, e := s.probeWorker(ctx, wo.WorkerRef)
	if e != nil {
		return fault(503, "WORKER_UNAVAILABLE", "selected Worker connection unavailable")
	}
	if !status.Ready || status.Health != "UP" || status.Mode != "gpu" || status.AvatarCacheStatus.Status != "READY" || status.AvatarCacheStatus.AvatarRef != av.AvatarRef {
		return fault(503, "WORKER_NOT_READY", "selected GPU avatar is unavailable")
	}
	return nil
}

// CreateBusinessSession captures defaults once, persists ownership and room context.
func (s *Service) CreateBusinessSession(ctx context.Context, scope Scope, roomID string) (dbgen.LiveSession, error) {
	b, e := s.Capture(ctx, scope)
	if e != nil {
		return dbgen.LiveSession{}, e
	}
	success := false
	defer func() {
		if !success {
			cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_, _ = s.DB.Exec(cleanup, `DELETE FROM provider_bindings WHERE id=$1 AND tenant_id=$2 AND user_id=$3`, b.ID, scope.TenantID, scope.UserID)
		}
	}()
	if e = ValidateSessionBinding(b); e != nil {
		return dbgen.LiveSession{}, e
	}
	// Physical readiness is rechecked at Runtime admission, so configuration capture
	// itself does not start, rent or assume the current Worker is healthy.
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return dbgen.LiveSession{}, e
	}
	defer tx.Rollback(ctx)
	var owned bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM resource_owners WHERE kind='room' AND resource_id=$1 AND tenant_id=$2 AND user_id=$3)`, roomID, scope.TenantID, scope.UserID).Scan(&owned)
	if e != nil {
		return dbgen.LiveSession{}, e
	}
	if !owned {
		return dbgen.LiveSession{}, ErrNotFound
	}
	// Pin a coherent room snapshot under a share lock against concurrent updates.
	var locked string
	e = tx.QueryRow(ctx, `SELECT id FROM live_rooms WHERE id=$1 FOR SHARE`, roomID).Scan(&locked)
	if e != nil {
		return dbgen.LiveSession{}, e
	}
	q := dbgen.New(tx)
	ro, e := q.GetRoom(ctx, roomID)
	if e != nil {
		return dbgen.LiveSession{}, e
	}
	req := runtimeapi.CreateRuntimeSessionRequest{}
	req.Context.RoomId, req.Context.SystemPrompt = ro.ID, ro.SystemPrompt
	if ro.ActiveProductID.Valid {
		req.Context.ActiveProductId = &ro.ActiveProductID.String
	}
	if ro.KnowledgeBaseID.Valid {
		req.Context.KnowledgeBaseId = &ro.KnowledgeBaseID.String
	}
	snapshot, _ := json.Marshal(req.Context)
	se, e := q.CreateSession(ctx, dbgen.CreateSessionParams{ID: ids.New("session"), RoomID: roomID})
	if e != nil {
		return se, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO resource_owners(kind,resource_id,tenant_id,user_id) VALUES('session',$1,$2,$3)`, se.ID, scope.TenantID, scope.UserID)
	if e != nil {
		return se, e
	}
	summary := SessionProviders{IntegrationVersion: "0.4.0", SessionID: se.ID, BindingID: b.ID, CapturedAt: time.Now().UTC(), ExpiresAt: b.ExpiresAt, Profiles: []ProviderSummary{}, Mode: "UNAVAILABLE", ErrorCode: "SESSION_NOT_STARTED"}
	for _, p := range b.Profiles {
		if p.Kind == "LIVE_PLATFORM" {
			continue
		}
		summary.Profiles = append(summary.Profiles, ProviderSummary{p.ID, p.Kind, p.Provider, p.Version, p.UpdatedAt})
	}
	raw, _ := json.Marshal(summary)
	_, e = tx.Exec(ctx, `INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,captured_at,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, se.ID, scope.TenantID, scope.UserID, b.ID, snapshot, raw, summary.CapturedAt, b.ExpiresAt)
	if e != nil {
		return se, e
	}
	e = tx.Commit(ctx)
	success = e == nil
	return se, e
}
func (s *Service) Prepare(ctx context.Context, id string, req *runtimeapi.CreateRuntimeSessionRequest) error {
	var raw []byte
	var expires time.Time
	e := s.DB.QueryRow(ctx, `SELECT room_snapshot,expires_at FROM session_provider_bindings WHERE session_id=$1 AND released_at IS NULL`, id).Scan(&raw, &expires)
	if errors.Is(e, pgx.ErrNoRows) {
		return fault(409, "PROVIDER_BINDING_UNAVAILABLE", "Session has no active provider binding")
	}
	if e != nil {
		return e
	}
	if time.Until(expires) <= 60*time.Second {
		return fault(409, "PROVIDER_BINDING_EXPIRED", "create a new Session")
	}
	return json.Unmarshal(raw, &req.Context)
}
func (s *Service) resolveSession(ctx context.Context, id string) (Scope, Binding, map[string]string, time.Time, error) {
	var scope Scope
	var bindingID string
	var captured, expires time.Time
	e := s.DB.QueryRow(ctx, `SELECT tenant_id,user_id,binding_id,captured_at,expires_at FROM session_provider_bindings WHERE session_id=$1 AND released_at IS NULL`, id).Scan(&scope.TenantID, &scope.UserID, &bindingID, &captured, &expires)
	if errors.Is(e, pgx.ErrNoRows) {
		e = fault(409, "PROVIDER_BINDING_UNAVAILABLE", "active binding unavailable")
	}
	if e != nil {
		return scope, Binding{}, nil, captured, e
	}
	if time.Until(expires) <= 60*time.Second {
		return scope, Binding{}, nil, captured, fault(409, "PROVIDER_BINDING_EXPIRED", "binding lease exhausted")
	}
	b, keys, e := s.Resolve(ctx, scope, bindingID)
	if e == nil {
		e = ValidateSessionBinding(b)
	}
	if e == nil {
		e = s.ValidateWorker(ctx, scope, b)
	}
	if e != nil {
		return scope, Binding{}, nil, captured, e
	}
	return scope, b, keys, captured, nil
}
func (s *Service) SessionInternalRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler { return serviceToken(s.WorkerTokenFile, next) })
	r.Get("/sessions/{sessionId}/binding", func(w http.ResponseWriter, r *http.Request) {
		if !s.IntegrationEnabled {
			write(w, r, 503, nil, fault(503, "INTEGRATION_DISABLED", "Session integration disabled"))
			return
		}
		scope, b, keys, at, e := s.resolveSession(r.Context(), chi.URLParam(r, "sessionId"))
		write(w, r, 200, map[string]any{"integrationVersion": "0.4.0", "scope": scope, "binding": b, "credentials": keys, "capturedAt": at}, e)
	})
	r.Delete("/sessions/{sessionId}/binding", func(w http.ResponseWriter, r *http.Request) {
		e := s.Release(r.Context(), chi.URLParam(r, "sessionId"))
		write(w, r, 200, map[string]any{}, e)
	})
	return r
}
func (s *Service) SessionPublicRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(s.ProductAuth)
	r.Get("/{sessionId}/providers", func(w http.ResponseWriter, r *http.Request) {
		id := chi.URLParam(r, "sessionId")
		if e := s.CheckOwner(r.Context(), scopeOf(r), "session", id); e != nil {
			write(w, r, 404, nil, e)
			return
		}
		var raw []byte
		var released *time.Time
		var state string
		var failureCode *string
		e := s.DB.QueryRow(r.Context(), `SELECT m.summary,m.released_at,l.status,l.failure_code FROM session_provider_bindings m JOIN live_sessions l ON l.id=m.session_id WHERE m.session_id=$1`, id).Scan(&raw, &released, &state, &failureCode)
		if errors.Is(e, pgx.ErrNoRows) {
			e = fault(409, "PROVIDER_BINDING_UNAVAILABLE", "legacy Session has no provider summary")
		}
		if e != nil {
			write(w, r, 404, nil, e)
			return
		}
		var summary SessionProviders
		if json.Unmarshal(raw, &summary) != nil {
			write(w, r, 500, nil, errors.New("invalid summary"))
			return
		}
		if released != nil || state == "ENDED" || state == "FAILED" {
			summary.Mode = "UNAVAILABLE"
			summary.ErrorCode = "SESSION_" + state
			if state == "FAILED" && failureCode != nil {
				switch *failureCode {
				case "WORKER_NOT_READY", "WORKER_UNAVAILABLE", "WORKER_UNREGISTERED", "PROVIDER_BINDING_EXPIRED", "PROVIDER_START_FAILED", "PROVIDER_PREPARE_FAILED", "PROVIDER_BINDING_UNAVAILABLE", "CONFIG_NOT_VERIFIED", "RUNTIME_UNAVAILABLE", "PROVIDER_AUTH_FAILED", "LLM_FAILED":
					summary.ErrorCode = *failureCode
				}
			}
			write(w, r, 200, summary, nil)
			return
		}
		if state == "CREATED" {
			write(w, r, 200, summary, nil)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		req, _ := http.NewRequestWithContext(ctx, "GET", s.RuntimeStatusURL+"/internal/v0.4/sessions/"+url.PathEscape(id)+"/providers", nil)
		client := &http.Client{Timeout: 3 * time.Second, Transport: TokenTransport{Path: s.RuntimeControlTokenFile, Base: &http.Transport{Proxy: nil}}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
		defer client.CloseIdleConnections()
		response, er := client.Do(req)
		valid := false
		if er == nil {
			defer response.Body.Close()
			bytes, readErr := io.ReadAll(io.LimitReader(response.Body, 65537))
			var current SessionProviders
			if readErr == nil && len(bytes) <= 65536 && response.StatusCode == 200 && json.Unmarshal(bytes, &current) == nil && current.IntegrationVersion == "0.4.0" && current.BindingID == summary.BindingID && current.SessionID == id && (current.Mode == "REAL" || current.Mode == "DEGRADED" || current.Mode == "UNAVAILABLE") {
				summary.Mode = current.Mode
				// Closed error projection; no raw Runtime field reaches browser.
				switch current.ErrorCode {
				case "", "PROVIDER_AUTH_FAILED", "LLM_FAILED", "WORKER_DISCONNECTED", "PROVIDER_BINDING_EXPIRED", "SESSION_NOT_STARTED", "SESSION_FAILED", "SESSION_ENDED":
					summary.ErrorCode = current.ErrorCode
				default:
					summary.ErrorCode = "PROVIDER_UNAVAILABLE"
				}
				if workerEpochPattern.MatchString(current.WorkerEpoch) {
					summary.WorkerEpoch = current.WorkerEpoch
				}
				valid = true
			}
		}
		if !valid {
			summary.Mode = "UNAVAILABLE"
			summary.ErrorCode = "RUNTIME_UNAVAILABLE"
		}
		write(w, r, 200, summary, nil)
	})
	return r
}

// Reconcile restores cleanup after missed events, crashes and unstarted bindings.
func (s *Service) Reconcile(ctx context.Context) error {
	rows, e := s.DB.Query(ctx, `SELECT m.session_id FROM session_provider_bindings m JOIN live_sessions l ON l.id=m.session_id WHERE m.released_at IS NULL AND (m.expires_at<=now() OR l.status IN ('ENDED','FAILED'))`)
	if e != nil {
		return e
	}
	var ids []string
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return e
		}
		ids = append(ids, id)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, id := range ids {
		if e = s.Release(ctx, id); e != nil {
			return e
		}
	}
	return nil
}
