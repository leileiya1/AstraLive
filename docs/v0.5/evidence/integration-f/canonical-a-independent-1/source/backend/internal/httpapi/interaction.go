package httpapi

import (
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	mockplatform "astralive/backend/internal/platform/mock"
	"astralive/backend/internal/userconfig"
	"fmt"
	"github.com/go-chi/chi/v5"
	"net/http"
)

// Separate v0.4 route; every method requires product identity and Session ownership,
// even in development. No caller-selected room, session, platform or trace mapping.
func (h *Server) interactionRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if h.Config == nil || h.S.Interaction == nil {
				failure(w, r, 401, "INVALID_ARGUMENT", "authenticated interaction unavailable")
				return
			}
			h.Config.ProductAuth(next).ServeHTTP(w, r)
		})
	})
	r.Route("/{sessionId}", func(r chi.Router) {
		r.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, err := h.S.Interaction.Ensure(r.Context(), userconfig.ScopeFromContext(r.Context()), chi.URLParam(r, "sessionId"))
				if err != nil {
					runtimeFail(w, r, err)
					return
				}
				next.ServeHTTP(w, r)
			})
		})
		r.Get("/", func(w http.ResponseWriter, r *http.Request) {
			respond(w, r, 200, h.S.Interaction.Snapshot(chi.URLParam(r, "sessionId")))
		})
		r.Put("/mode", func(w http.ResponseWriter, r *http.Request) {
			var input struct {
				Mode interaction.Mode `json:"mode"`
			}
			if !decode(w, r, &input) {
				return
			}
			s, err := h.S.Interaction.Ensure(r.Context(), userconfig.ScopeFromContext(r.Context()), chi.URLParam(r, "sessionId"))
			if err != nil {
				runtimeFail(w, r, err)
				return
			}
			if err = s.SetMode(input.Mode); err != nil {
				failure(w, r, 422, "INVALID_ARGUMENT", "invalid interaction mode")
				return
			}
			respond(w, r, 200, h.S.Interaction.Snapshot(chi.URLParam(r, "sessionId")))
		})
		if h.Env != "production" {
			r.Post("/mock", func(w http.ResponseWriter, r *http.Request) {
				var input struct {
					Text  string `json:"text"`
					Users int    `json:"users"`
				}
				if !decode(w, r, &input) {
					return
				}
				if !valid(input.Text) || len(input.Text) > 2048 || input.Users < 1 || input.Users > 100 {
					failure(w, r, 422, "INVALID_ARGUMENT", "text and users 1..100 required")
					return
				}
				rows := []mockplatform.Record{}
				for i := 0; i < input.Users; i++ {
					rows = append(rows, mockplatform.Record{SourceEventID: ids.New("mock"), User: fmt.Sprintf("mock-viewer-%d", i), Content: input.Text})
				}
				if err := h.S.Interaction.Replay(chi.URLParam(r, "sessionId"), rows); err != nil {
					failure(w, r, 409, "CONFLICT", "replay already active or session stopped")
					return
				}
				respond(w, r, 202, map[string]any{"accepted": true, "platform": "mock"})
			})
			r.Post("/replay", func(w http.ResponseWriter, r *http.Request) {
				var input struct {
					Rate  int `json:"rate"`
					Count int `json:"count"`
				}
				if !decode(w, r, &input) {
					return
				}
				if (input.Rate != 0 && input.Rate != 1 && input.Rate != 5 && input.Rate != 20) || input.Count < 1 || input.Count > 1000 {
					failure(w, r, 422, "INVALID_ARGUMENT", "rate 0/1/5/20 and count 1..1000 required")
					return
				}
				rows := mockplatform.Scenario(input.Rate, input.Count)
				prefix := ids.New("replay")
				for i := range rows {
					rows[i].SourceEventID = prefix + "-" + rows[i].SourceEventID
				}
				if err := h.S.Interaction.Replay(chi.URLParam(r, "sessionId"), rows); err != nil {
					failure(w, r, 409, "CONFLICT", "replay already active or session stopped")
					return
				}
				respond(w, r, 202, map[string]any{"accepted": true, "platform": "mock"})
			})
			r.Delete("/replay", func(w http.ResponseWriter, r *http.Request) {
				h.S.Interaction.StopReplay(chi.URLParam(r, "sessionId"))
				respond(w, r, 200, map[string]any{"stopped": true})
			})
		}
	})
	return r
}
