package httpapi

import (
	"astralive/backend/internal/durability"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/userconfig"
	"errors"
	"github.com/go-chi/chi/v5"
	"net/http"
)

// Current binding/run authority precedes even an idempotency response for a
// Timeline-bound request. Compatibility mode keeps its existing handler.
func (h *Server) narrationAdmission(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if h.S.Narration != nil {
			tx, e := h.S.DB.Begin(r.Context())
			if e != nil {
				runtimeFail(w, r, e)
				return
			}
			defer tx.Rollback(r.Context())
			run, e := h.S.Durable.Current(r.Context(), tx, chi.URLParam(r, "sessionId"), false)
			if e == nil && run.Status != "ACTIVE" {
				e = durability.ErrSealed
			}
			if e != nil {
				runtimeFail(w, r, e)
				return
			}
			tx.Rollback(r.Context())
		}
		next(w, r)
	}
}

// Versioned opt-in routes. Identity comes from ProductAuth, never the body.
func (h *Server) narrationRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if h.Config == nil || h.S.Narration == nil {
				failure(w, r, 503, "DEPENDENCY_UNAVAILABLE", "continuity unavailable")
				return
			}
			h.Config.ProductAuth(next).ServeHTTP(w, r)
		})
	})
	r.Route("/{sessionId}", func(r chi.Router) {
		r.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				sid := chi.URLParam(r, "sessionId")
				scope := userconfig.ScopeFromContext(r.Context())
				if e := h.Config.CheckOwner(r.Context(), scope, "session", sid); e != nil {
					configFailure(w, r, e)
					return
				}
				session, e := h.S.Q.GetSession(r.Context(), sid)
				if e != nil {
					runtimeFail(w, r, e)
					return
				}
				if e = h.Config.CheckOwner(r.Context(), scope, "room", session.RoomID); e != nil {
					configFailure(w, r, e)
					return
				}
				next.ServeHTTP(w, r)
			})
		})
		r.Get("/", func(w http.ResponseWriter, r *http.Request) {
			d, e := h.S.Narration.Snapshot(r.Context(), chi.URLParam(r, "sessionId"))
			if e != nil {
				narrationFail(w, r, e)
				return
			}
			respond(w, r, 200, d)
		})
		r.Post("/start", func(w http.ResponseWriter, r *http.Request) {
			var x narration.StartRequest
			if !decode(w, r, &x) {
				return
			}
			d, e := h.S.Narration.Start(r.Context(), chi.URLParam(r, "sessionId"), requestID(r), x)
			if e != nil {
				narrationFail(w, r, e)
				return
			}
			respond(w, r, 202, d)
		})
	})
	return r
}
func narrationFail(w http.ResponseWriter, r *http.Request, e error) {
	if errors.Is(e, narration.ErrDependency) {
		failure(w, r, 503, "DEPENDENCY_UNAVAILABLE", "continuity unavailable")
		return
	}
	for _, known := range []error{narration.ErrConflict, narration.ErrBoundary, narration.ErrStale, narration.ErrStopped, narration.ErrUnknown, narration.ErrExpired, narration.ErrProduct} {
		if errors.Is(e, known) {
			failure(w, r, 409, known.Error(), "narration transition rejected")
			return
		}
	}
	runtimeFail(w, r, e)
}
