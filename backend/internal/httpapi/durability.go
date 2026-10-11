package httpapi

import (
	"astralive/backend/internal/durability"
	"astralive/backend/internal/userconfig"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"io"
	"net/http"
)

// JournalRouter accepts a dedicated machine role only; caller-provided tenant/user fields are never used.
func JournalRouter(s *durability.Store, tokenFile string) http.Handler {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token, e := userconfig.ReadServiceToken(tokenFile)
			if e != nil || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
				http.Error(w, "unauthorized", 401)
				return
			}
			w.Header().Set("Cache-Control", "no-store")
			next.ServeHTTP(w, r)
		})
	})
	reply := func(w http.ResponseWriter, v any, e error) {
		w.Header().Set("Content-Type", "application/json")
		if e != nil {
			code, status := "DEPENDENCY_UNAVAILABLE", 503
			if errors.Is(e, durability.ErrConflict) {
				code, status = "COMMAND_CONFLICT", 409
			}
			if errors.Is(e, durability.ErrFence) {
				code, status = "LEASE_LOST", 409
			}
			if errors.Is(e, durability.ErrSealed) {
				code, status = "RUN_SEALED", 409
			}
			w.WriteHeader(status)
			_ = json.NewEncoder(w).Encode(map[string]string{"code": code})
			return
		}
		_ = json.NewEncoder(w).Encode(v)
	}
	read := func(w http.ResponseWriter, r *http.Request, v any) bool {
		d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
		d.DisallowUnknownFields()
		if d.Decode(v) != nil {
			http.Error(w, "invalid request", 422)
			return false
		}
		var extra any
		if d.Decode(&extra) != io.EOF {
			http.Error(w, "invalid request", 422)
			return false
		}
		return true
	}
	r.Post("/accept", func(w http.ResponseWriter, r *http.Request) {
		var x struct {
			Command json.RawMessage `json:"command"`
		}
		if !read(w, r, &x) {
			return
		}
		out, e := s.Accept(r.Context(), x.Command)
		reply(w, out, e)
	})
	r.Post("/start", func(w http.ResponseWriter, r *http.Request) {
		var x struct {
			SessionID string `json:"sessionId"`
			CommandID string `json:"commandId"`
			Producer  string `json:"producerIncarnation"`
			Token     int64  `json:"leaseToken"`
		}
		if !read(w, r, &x) {
			return
		}
		out, e := s.StartAttempt(r.Context(), x.SessionID, x.CommandID, x.Producer, x.Token)
		reply(w, out, e)
	})
	r.Post("/media-start", func(w http.ResponseWriter, r *http.Request) {
		var x struct {
			SessionID string `json:"sessionId"`
			CommandID string `json:"commandId"`
			Producer  string `json:"producerIncarnation"`
			Floor     int64  `json:"generationFloor"`
		}
		if !read(w, r, &x) {
			return
		}
		run, generation, e := s.StartMedia(r.Context(), x.SessionID, x.CommandID, x.Producer, x.Floor)
		reply(w, map[string]any{"run": run, "generationId": generation}, e)
	})
	r.Post("/grant", func(w http.ResponseWriter, r *http.Request) {
		var x struct {
			SessionID string `json:"sessionId"`
			Epoch     int64  `json:"runEpoch"`
		}
		if !read(w, r, &x) {
			return
		}
		out, e := s.Grant(r.Context(), x.SessionID, x.Epoch)
		reply(w, out, e)
	})
	r.Post("/receipts", func(w http.ResponseWriter, r *http.Request) {
		var x durability.Observation
		if !read(w, r, &x) {
			return
		}
		e := s.Observe(r.Context(), x)
		reply(w, map[string]bool{"stored": e == nil}, e)
	})
	r.Post("/timeline-record", func(w http.ResponseWriter, r *http.Request) {
		var x durability.TimelineRecord
		if !read(w, r, &x) {
			return
		}
		result, e := s.RecordTimeline(r.Context(), x)
		reply(w, result, e)
	})
	r.Post("/events", func(w http.ResponseWriter, r *http.Request) {
		raw, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
		if e != nil {
			http.Error(w, "invalid request", 422)
			return
		}
		stored, e := s.Ingest(r.Context(), raw)
		reply(w, map[string]bool{"stored": stored}, e)
	})
	r.Get("/sessions/{sessionId}/commands/{commandId}", func(w http.ResponseWriter, r *http.Request) {
		sid, id := chi.URLParam(r, "sessionId"), chi.URLParam(r, "commandId")
		var e error
		if incarnation := r.Header.Get("X-Runtime-Incarnation"); incarnation != "" {
			e = s.ReconcileIncarnation(r.Context(), sid, id, incarnation)
		}
		var raw json.RawMessage
		if e == nil {
			raw, e = s.Lookup(r.Context(), sid, id)
		}
		reply(w, raw, e)
	})
	return r
}
