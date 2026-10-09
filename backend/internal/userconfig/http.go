package userconfig

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"astralive/backend/internal/ids"
	"github.com/go-chi/chi/v5"
)

type scopeKey struct{}

func write(w http.ResponseWriter, r *http.Request, status int, data any, err error) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	id := w.Header().Get("X-Request-Id")
	if id == "" {
		id = ids.New("req")
	}
	out := map[string]any{"requestId": id, "timestamp": time.Now().UTC().Format(time.RFC3339Nano)}
	if err != nil {
		f := publicError(err)
		status = f.Status
		out["code"] = f.Code
		out["message"] = f.Message
		out["details"] = map[string]any{}
	} else {
		out["code"] = "OK"
		out["message"] = "success"
		out["data"] = data
	}
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(out)
}
func read(r *http.Request, v any) error {
	if r.Header.Get("Content-Type") != "application/json" {
		return ErrInvalid
	}
	raw, e := io.ReadAll(io.LimitReader(r.Body, 16385))
	if e != nil || len(raw) > 16384 {
		return ErrInvalid
	}
	return strictJSON(raw, v)
}
func scopeOf(r *http.Request) Scope { s, _ := r.Context().Value(scopeKey{}).(Scope); return s }
func (s *Service) auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, e := r.Cookie("astralive_config_session")
		if e != nil {
			write(w, r, 401, nil, fault(401, "UNAUTHENTICATED", "sign in to manage configuration"))
			return
		}
		scope, e := s.Authenticate(r.Context(), c.Value)
		if e != nil {
			write(w, r, 401, nil, e)
			return
		}
		if r.Method != "GET" && (s.Origin == "" || r.Header.Get("Origin") != s.Origin) {
			write(w, r, 403, nil, fault(403, "ORIGIN_REJECTED", "request origin not permitted"))
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), scopeKey{}, scope)))
	})
}
func serviceToken(path string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f, e := os.Open(path)
		if e != nil {
			write(w, r, 401, nil, fault(401, "UNAUTHENTICATED", "service authentication required"))
			return
		}
		defer f.Close()
		info, e := f.Stat()
		if e != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 256 {
			write(w, r, 401, nil, fault(401, "UNAUTHENTICATED", "service authentication required"))
			return
		}
		raw, e := io.ReadAll(f)
		token := strings.TrimSpace(string(raw))
		supplied := r.Header.Get("Authorization")
		if e != nil || len(token) < 32 || subtle.ConstantTimeCompare([]byte(supplied), []byte("Bearer "+token)) != 1 {
			write(w, r, 401, nil, fault(401, "UNAUTHENTICATED", "service authentication required"))
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Service) PublicRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(s.auth)
	r.Get("/me", func(w http.ResponseWriter, r *http.Request) {
		write(w, r, 200, map[string]any{"identity": scopeOf(r), "contractVersion": "0.3.0"}, nil)
	})
	r.Get("/profiles", func(w http.ResponseWriter, r *http.Request) {
		p, e := s.List(r.Context(), scopeOf(r))
		write(w, r, 200, p, e)
	})
	r.Post("/profiles", func(w http.ResponseWriter, r *http.Request) {
		var create struct {
			Kind     string          `json:"kind"`
			Name     string          `json:"name"`
			Provider string          `json:"provider"`
			Config   json.RawMessage `json:"config"`
			Secret   string          `json:"secret"`
		}
		if e := read(r, &create); e != nil {
			write(w, r, 422, nil, e)
			return
		}
		p, e := s.Create(r.Context(), scopeOf(r), Input{Kind: create.Kind, Name: create.Name, Provider: create.Provider, Config: create.Config, Secret: create.Secret})
		create.Secret = ""
		write(w, r, 201, p, e)
	})
	r.Put("/profiles/{profileId}", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			ExpectedVersion int64           `json:"expectedVersion"`
			Name            string          `json:"name"`
			Config          json.RawMessage `json:"config"`
		}
		if e := read(r, &in); e != nil {
			write(w, r, 422, nil, e)
			return
		}
		p, e := s.Mutate(r.Context(), scopeOf(r), chi.URLParam(r, "profileId"), "update", Input{Name: in.Name, Config: in.Config, ExpectedVersion: in.ExpectedVersion})
		write(w, r, 200, p, e)
	})
	r.Put("/profiles/{profileId}/credential", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			ExpectedVersion int64  `json:"expectedVersion"`
			Secret          string `json:"secret"`
		}
		if e := read(r, &in); e != nil {
			write(w, r, 422, nil, e)
			return
		}
		p, e := s.Mutate(r.Context(), scopeOf(r), chi.URLParam(r, "profileId"), "credential", Input{Secret: in.Secret, ExpectedVersion: in.ExpectedVersion})
		in.Secret = ""
		write(w, r, 200, p, e)
	})
	action := func(a string) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			var in struct {
				ExpectedVersion int64 `json:"expectedVersion"`
			}
			if e := read(r, &in); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			var p Profile
			var e error
			if a == "test" {
				p, e = s.Test(r.Context(), scopeOf(r), chi.URLParam(r, "profileId"), in.ExpectedVersion)
			} else {
				p, e = s.Mutate(r.Context(), scopeOf(r), chi.URLParam(r, "profileId"), a, Input{ExpectedVersion: in.ExpectedVersion})
			}
			var data any = p
			if a == "delete" {
				data = map[string]any{}
			}
			write(w, r, 200, data, e)
		}
	}
	r.Post("/profiles/{profileId}/test", action("test"))
	r.Post("/profiles/{profileId}/default", action("default"))
	r.Post("/profiles/{profileId}/disable", action("disable"))
	r.Delete("/profiles/{profileId}", action("delete"))
	r.Delete("/profiles/{profileId}/credential", action("remove-credential"))
	r.Get("/settings", func(w http.ResponseWriter, r *http.Request) {
		p, e := s.Settings(r.Context(), scopeOf(r))
		write(w, r, 200, p, e)
	})
	r.Put("/settings", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			ExpectedVersion int64  `json:"expectedVersion"`
			Policy          Policy `json:"policy"`
		}
		if e := read(r, &in); e != nil {
			write(w, r, 422, nil, e)
			return
		}
		p, e := s.SaveSettings(r.Context(), scopeOf(r), in.ExpectedVersion, in.Policy)
		write(w, r, 200, p, e)
	})
	return r
}
func (s *Service) InternalRouter() http.Handler {
	r := chi.NewRouter()
	r.Group(func(r chi.Router) {
		r.Use(func(next http.Handler) http.Handler { return serviceToken(s.IdentityTokenFile, next) })
		r.Post("/config-sessions", func(w http.ResponseWriter, r *http.Request) {
			var scope Scope
			if e := read(r, &scope); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			token, e := s.IssueSession(r.Context(), scope)
			write(w, r, 201, map[string]any{"token": token, "expiresInSeconds": 43200}, e)
		})
		r.Delete("/config-sessions", func(w http.ResponseWriter, r *http.Request) {
			var in struct {
				Token string `json:"token"`
			}
			if e := read(r, &in); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			_, e := s.DB.Exec(r.Context(), `DELETE FROM config_auth_sessions WHERE token_hash=$1`, tokenHash(in.Token))
			write(w, r, 200, map[string]any{}, e)
		})
	})
	r.Group(func(r chi.Router) {
		r.Use(func(next http.Handler) http.Handler { return serviceToken(s.WorkerTokenFile, next) })
		r.Post("/provider-bindings", func(w http.ResponseWriter, r *http.Request) {
			var scope Scope
			if e := read(r, &scope); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			p, e := s.Capture(r.Context(), scope)
			write(w, r, 201, p, e)
		})
		r.Post("/provider-bindings/{bindingId}/resolve", func(w http.ResponseWriter, r *http.Request) {
			var scope Scope
			if e := read(r, &scope); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			p, keys, e := s.Resolve(r.Context(), scope, chi.URLParam(r, "bindingId"))
			write(w, r, 200, map[string]any{"binding": p, "credentials": keys}, e)
		})
		r.Delete("/provider-bindings/{bindingId}", func(w http.ResponseWriter, r *http.Request) {
			var scope Scope
			if e := read(r, &scope); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			tag, e := s.DB.Exec(r.Context(), `DELETE FROM provider_bindings WHERE id=$1 AND tenant_id=$2 AND user_id=$3`, chi.URLParam(r, "bindingId"), scope.TenantID, scope.UserID)
			if e == nil && tag.RowsAffected() != 1 {
				e = ErrNotFound
			}
			write(w, r, 200, map[string]any{}, e)
		})
		r.Post("/worker-health", func(w http.ResponseWriter, r *http.Request) {
			var in struct {
				Scope
				ProfileID       string `json:"profileId"`
				ExpectedVersion int64  `json:"expectedVersion"`
				Health          string `json:"health"`
			}
			if e := read(r, &in); e != nil {
				write(w, r, 422, nil, e)
				return
			}
			if !validScope(in.Scope) || in.ExpectedVersion < 1 || (in.Health != "UP" && in.Health != "DOWN") {
				write(w, r, 422, nil, ErrInvalid)
				return
			}
			tag, e := s.DB.Exec(r.Context(), `UPDATE config_profiles SET health=$5,health_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3 AND version=$4 AND kind='GPU_WORKER'`, in.TenantID, in.UserID, in.ProfileID, in.ExpectedVersion, in.Health)
			if e == nil && tag.RowsAffected() != 1 {
				e = ErrConflict
			}
			write(w, r, 200, map[string]any{}, e)
		})
	})
	return r
}
