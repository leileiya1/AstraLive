package httpapi

import (
	"astralive/backend/internal/userconfig"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

var resourceKinds = map[string]string{"avatars": "avatar", "voices": "voice", "products": "product", "knowledge-bases": "knowledge", "live-rooms": "room", "live-sessions": "session", "jobs": "job"}
var referenceKinds = map[string]string{"avatarId": "avatar", "voiceId": "voice", "activeProductId": "product", "knowledgeBaseId": "knowledge", "roomId": "room"}

func (h *Server) authorization(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.URL.Path, "/api/v1/") {
			next.ServeHTTP(w, r)
			return
		}
		if h.Config == nil {
			if h.Env == "production" {
				failure(w, r, 401, "INVALID_ARGUMENT", "sign in required")
				return
			}
			next.ServeHTTP(w, r)
			return
		}
		h.Config.ProductAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			scope := userconfig.ScopeFromContext(r.Context())
			parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/"), "/")
			if kind := resourceKinds[parts[0]]; kind != "" && len(parts) > 1 {
				if e := h.Config.CheckOwner(r.Context(), scope, kind, parts[1]); e != nil {
					configFailure(w, r, e)
					return
				}
			}
			if r.Method != "GET" && r.Body != nil {
				raw, e := io.ReadAll(io.LimitReader(r.Body, (1<<20)+1))
				if e != nil || len(raw) > 1<<20 {
					failure(w, r, 422, "INVALID_ARGUMENT", "invalid body")
					return
				}
				r.Body = io.NopCloser(bytes.NewReader(raw))
				var input map[string]json.RawMessage
				if json.Unmarshal(raw, &input) == nil {
					for field, kind := range referenceKinds {
						if value, ok := input[field]; ok {
							var id string
							if json.Unmarshal(value, &id) == nil && id != "" {
								if e := h.Config.CheckOwner(r.Context(), scope, kind, id); e != nil {
									configFailure(w, r, e)
									return
								}
							}
						}
					}
				}
			}
			next.ServeHTTP(w, r)
		})).ServeHTTP(w, r)
	})
}
func configFailure(w http.ResponseWriter, r *http.Request, e error) {
	userconfig.WriteError(w, r, e)
}
func (h *Server) claim(w http.ResponseWriter, r *http.Request, kind, id string) bool {
	if h.Config == nil {
		return true
	}
	if e := h.Config.Own(r.Context(), userconfig.ScopeFromContext(r.Context()), kind, id); e != nil {
		configFailure(w, r, e)
		return false
	}
	return true
}
func (h *Server) owned(w http.ResponseWriter, r *http.Request, kind string) (map[string]bool, bool) {
	if h.Config == nil {
		return nil, true
	}
	ids, e := h.Config.OwnedIDs(r.Context(), userconfig.ScopeFromContext(r.Context()), kind)
	if e != nil {
		configFailure(w, r, e)
		return nil, false
	}
	return ids, true
}
