package httpapi

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/app"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/metrics"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
)

type Server struct {
	Config     *userconfig.Service
	S          *app.Service
	Redis      *redis.Client
	Env, Token string
	Log        *slog.Logger
}
type ctxKey string

const requestIDKey ctxKey = "requestId"

func requestID(r *http.Request) string { v, _ := r.Context().Value(requestIDKey).(string); return v }
func respond(w http.ResponseWriter, r *http.Request, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	message := "success"
	if status == 202 {
		message = "accepted"
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"code": "OK", "message": message, "data": data, "requestId": requestID(r), "timestamp": time.Now().UTC().Format(time.RFC3339Nano)})
}
func failure(w http.ResponseWriter, r *http.Request, status int, code, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"code": code, "message": msg, "details": map[string]any{}, "requestId": requestID(r), "timestamp": time.Now().UTC().Format(time.RFC3339Nano)})
}
func dbFail(w http.ResponseWriter, r *http.Request, e error, notFound string) {
	if errors.Is(e, pgx.ErrNoRows) {
		failure(w, r, 404, notFound, "resource not found")
		return
	}
	if errors.Is(e, app.ErrConflict) {
		failure(w, r, 409, "SESSION_NOT_READY", "invalid state transition")
		return
	}
	var pe *pgconn.PgError
	if errors.As(e, &pe) {
		if pe.Code == "23503" {
			failure(w, r, 409, "CONFLICT", "resource is referenced or dependency missing")
			return
		}
		if pe.Code == "23505" {
			failure(w, r, 409, "CONFLICT", "resource already exists")
			return
		}
	}
	slog.Error("database operation failed", "requestId", requestID(r), "error", e)
	failure(w, r, 500, "INTERNAL_ERROR", "internal error")
}
func runtimeFail(w http.ResponseWriter, r *http.Request, e error) {
	var f *userconfig.Fault
	if errors.As(e, &f) {
		configFailure(w, r, e)
		return
	}
	if errors.Is(e, app.ErrConflict) {
		dbFail(w, r, e, "")
		return
	}
	if errors.Is(e, pgx.ErrNoRows) {
		dbFail(w, r, e, "SESSION_NOT_FOUND")
		return
	}
	if e.Error() == "AVATAR_NOT_READY" {
		failure(w, r, 409, "AVATAR_NOT_READY", e.Error())
		return
	}
	status, code := runtime.MapError(e)
	failure(w, r, status, code, "runtime command failed")
}
func body(r *http.Request, v any) error {
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		return fmt.Errorf("content type must be application/json")
	}
	d := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		return e
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return fmt.Errorf("multiple JSON values")
	}
	return nil
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	if e := body(r, v); e != nil {
		failure(w, r, 400, "INVALID_ARGUMENT", e.Error())
		return false
	}
	return true
}
func valid(s string) bool { return strings.TrimSpace(s) != "" }
func (h *Server) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(h.requestContext)
	r.Use(h.authorization)
	r.Use(h.validateContract)
	if h.Config != nil {
		r.Mount("/api/v0.3/config", h.Config.PublicRouter())
		r.Mount("/api/v0.4/auth", h.Config.AuthRouter())
		r.Mount("/api/v0.4/workers", h.Config.WorkerChoicesRouter())
		r.Mount("/api/v0.4/sessions", h.Config.SessionPublicRouter())
		r.Mount("/internal/v0.4", h.Config.SessionInternalRouter())
		r.Mount("/internal/v0.3", h.Config.InternalRouter())
	}
	r.Mount("/api/v0.4/interaction", h.interactionRouter())
	r.Get("/health/live", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"status": "UP"})
	})
	r.Get("/health/ready", h.ready)
	r.Handle("/metrics", promhttp.Handler())
	r.Route("/api/v1", func(r chi.Router) {
		r.Post("/avatars", h.createAvatar)
		r.Get("/avatars", h.listAvatars)
		r.Get("/avatars/{avatarId}", h.getAvatar)
		r.Delete("/avatars/{avatarId}", h.deleteAvatar)
		r.Post("/avatars/{avatarId}/prepare", h.idem(h.prepareAvatar))
		r.Post("/voices", h.createVoice)
		r.Get("/voices", h.listVoices)
		r.Get("/voices/{voiceId}", h.getVoice)
		r.Delete("/voices/{voiceId}", h.deleteVoice)
		r.Post("/products", h.createProduct)
		r.Get("/products", h.listProducts)
		r.Get("/products/{productId}", h.getProduct)
		r.Put("/products/{productId}", h.updateProduct)
		r.Post("/knowledge-bases", h.createKnowledge)
		r.Post("/knowledge-bases/{knowledgeBaseId}/documents", h.addDocument)
		r.Post("/knowledge-bases/{knowledgeBaseId}/index", h.idem(h.indexKnowledge))
		r.Get("/jobs/{jobId}", h.getJob)
		r.Post("/live-rooms", h.createRoom)
		r.Get("/live-rooms", h.listRooms)
		r.Get("/live-rooms/{roomId}", h.getRoom)
		r.Put("/live-rooms/{roomId}", h.updateRoom)
		r.Post("/live-sessions", h.createSession)
		r.Get("/live-sessions/{sessionId}", h.getSession)
		r.Post("/live-sessions/{sessionId}/start", h.idem(h.startSession))
		r.Post("/live-sessions/{sessionId}/stop", h.idem(h.stopSession))
		r.Post("/live-sessions/{sessionId}/utterances", h.idem(h.createUtterance))
		r.Post("/live-sessions/{sessionId}/webrtc/offer", h.webrtcOffer)
		r.Post("/live-sessions/{sessionId}/interrupt", h.interrupt)
		r.Get("/live-sessions/{sessionId}/events", h.events)
		if h.Env != "production" {
			r.Post("/dev/platform-events", h.devPlatformEvent)
		}
	})
	r.Route("/internal/v1/tools", func(r chi.Router) {
		r.Use(h.authorizeInternal)
		r.Get("/products/{productId}", h.toolProduct)
		r.Get("/products/{productId}/stock", h.toolStock)
		r.Get("/products/{productId}/price", h.toolPrice)
	})
	return r
}
func (h *Server) requestContext(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := ids.New("req")
		w.Header().Set("X-Request-Id", id)
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w}
		r = r.WithContext(context.WithValue(r.Context(), requestIDKey, id))
		next.ServeHTTP(sw, r)
		status := sw.status
		if status == 0 {
			status = 200
		}
		route := chi.RouteContext(r.Context()).RoutePattern()
		if route == "" {
			route = "unmatched"
		}
		metrics.HTTPRequests.WithLabelValues(r.Method, route, strconv.Itoa(status)).Inc()
		metrics.HTTPDuration.WithLabelValues(r.Method, route).Observe(float64(time.Since(start).Milliseconds()))
		h.Log.Info("http request", "requestId", id, "route", route, "durationMs", time.Since(start).Milliseconds())
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
		w.ResponseWriter.WriteHeader(status)
	}
}
func (w *statusWriter) Write(p []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(200)
	}
	return w.ResponseWriter.Write(p)
}
func (w *statusWriter) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}
func (h *Server) authorizeInternal(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if h.Token == "" || r.Header.Get("Authorization") != "Bearer "+token || subtle.ConstantTimeCompare([]byte(token), []byte(h.Token)) != 1 {
			failure(w, r, 401, "INVALID_ARGUMENT", "unauthorized")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (h *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if h.S.DB.Ping(ctx) != nil || h.Redis.Ping(ctx).Err() != nil {
		failure(w, r, 503, "RUNTIME_UNAVAILABLE", "dependency unavailable")
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"status": "UP"})
}

type capture struct {
	http.ResponseWriter
	status int
	body   bytes.Buffer
}

func (c *capture) WriteHeader(n int) {
	if c.status == 0 {
		c.status = n
		c.ResponseWriter.WriteHeader(n)
	}
}
func (c *capture) Write(p []byte) (int, error) {
	if c.status == 0 {
		c.WriteHeader(200)
	}
	c.body.Write(p)
	return c.ResponseWriter.Write(p)
}
func (h *Server) idem(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		key := r.Header.Get("Idempotency-Key")
		if key == "" {
			failure(w, r, 400, "INVALID_ARGUMENT", "Idempotency-Key required")
			return
		}
		b, e := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if e != nil {
			failure(w, r, 400, "INVALID_ARGUMENT", "invalid body")
			return
		}
		r.Body = io.NopCloser(bytes.NewReader(b))
		digest := sha256.Sum256(b)
		hash := hex.EncodeToString(digest[:])
		route := r.URL.Path
		if h.Config != nil {
			scope := userconfig.ScopeFromContext(r.Context())
			route = scope.TenantID + ":" + scope.UserID + ":" + route
		}
		tx, e := h.S.DB.Begin(r.Context())
		if e != nil {
			dbFail(w, r, e, "")
			return
		}
		defer tx.Rollback(r.Context())
		_, e = tx.Exec(r.Context(), "SELECT pg_advisory_xact_lock(hashtext($1))", route+":"+key)
		if e != nil {
			dbFail(w, r, e, "")
			return
		}
		q := h.S.Q.WithTx(tx)
		old, e := q.GetIdempotency(r.Context(), dbgen.GetIdempotencyParams{Key: key, Route: route})
		if e == nil {
			if old.RequestHash != hash {
				failure(w, r, 409, "CONFLICT", "idempotency key reused with different request")
				return
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(int(old.ResponseStatus))
			_, _ = w.Write(old.ResponseBody)
			return
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			dbFail(w, r, e, "")
			return
		}
		c := &capture{ResponseWriter: w}
		next(c, r)
		if c.status >= 200 && c.status < 300 {
			_, e = tx.Exec(r.Context(), "INSERT INTO idempotency_keys(key,route,request_hash,response_status,response_body,expires_at) VALUES($1,$2,$3,$4,$5,now()+interval '24 hours')", key, route, hash, c.status, c.body.Bytes())
			if e != nil {
				h.Log.Error("idempotency store failed", "error", e)
				return
			}
			_ = tx.Commit(r.Context())
		}
	}
}
func avatar(v dbgen.Avatar) any {
	return map[string]any{"avatarId": v.ID, "name": v.Name, "engine": v.Engine, "status": v.Status}
}
func voice(v dbgen.Voice) any {
	return map[string]any{"voiceId": v.ID, "name": v.Name, "provider": v.Provider, "providerVoiceId": v.ProviderVoiceID}
}
func product(v dbgen.Product) any {
	val, _ := v.Price.Value()
	price, _ := strconv.ParseFloat(fmt.Sprint(val), 64)
	return map[string]any{"productId": v.ID, "name": v.Name, "description": v.Description, "price": price, "currency": v.Currency, "stock": v.Stock, "sizes": v.Sizes}
}
func room(v dbgen.LiveRoom) any {
	m := map[string]any{"roomId": v.ID, "name": v.Name, "avatarId": v.AvatarID, "voiceId": v.VoiceID, "systemPrompt": v.SystemPrompt}
	if v.ActiveProductID.Valid {
		m["activeProductId"] = v.ActiveProductID.String
	}
	if v.KnowledgeBaseID.Valid {
		m["knowledgeBaseId"] = v.KnowledgeBaseID.String
	}
	return m
}
func session(v dbgen.LiveSession) any {
	return map[string]any{"sessionId": v.ID, "roomId": v.RoomID, "status": v.Status}
}
func num(v float64) (pgtype.Numeric, error) {
	var n pgtype.Numeric
	e := n.Scan(strconv.FormatFloat(v, 'f', 2, 64))
	return n, e
}

type productInput struct {
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Price       float64  `json:"price"`
	Currency    string   `json:"currency"`
	Stock       int32    `json:"stock"`
	Sizes       []string `json:"sizes"`
}

func (v productInput) valid() bool {
	return valid(v.Name) && valid(v.Currency) && v.Price >= 0 && v.Stock >= 0 && v.Sizes != nil
}

type roomInput struct {
	Name            string `json:"name"`
	AvatarID        string `json:"avatarId"`
	VoiceID         string `json:"voiceId"`
	KnowledgeBaseID string `json:"knowledgeBaseId"`
	ActiveProductID string `json:"activeProductId"`
	SystemPrompt    string `json:"systemPrompt"`
}

func (v roomInput) params(id string) dbgen.CreateRoomParams {
	return dbgen.CreateRoomParams{ID: id, Name: v.Name, AvatarID: v.AvatarID, VoiceID: v.VoiceID, KnowledgeBaseID: pgtype.Text{String: v.KnowledgeBaseID, Valid: v.KnowledgeBaseID != ""}, ActiveProductID: pgtype.Text{String: v.ActiveProductID, Valid: v.ActiveProductID != ""}, SystemPrompt: v.SystemPrompt}
}
