package userconfig

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/go-chi/chi/v5"
	"golang.org/x/crypto/bcrypt"
)

const ProductCookie = "astralive_user_session"

// OperatorLogin is a deployment adapter for ONE operator, not an account store.
type OperatorLogin struct {
	Username     string `json:"username"`
	PasswordHash string `json:"passwordHash"`
	Scope        Scope  `json:"scope"`
}

func privateFile(path string, limit int64) ([]byte, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, errors.New("private configuration unavailable")
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil || !st.Mode().IsRegular() || st.Mode().Perm()&0077 != 0 || st.Size() > limit {
		return nil, errors.New("invalid private configuration")
	}
	return io.ReadAll(io.LimitReader(f, limit+1))
}
func ReadServiceToken(path string) (string, error) {
	raw, e := privateFile(path, 256)
	token := strings.TrimSpace(string(raw))
	if e != nil || len(token) < 32 || strings.ContainsAny(token, " \t\r\n") {
		return "", errors.New("service token unavailable")
	}
	return token, nil
}
func (s *Service) operator() (OperatorLogin, error) {
	var op OperatorLogin
	raw, e := privateFile(s.OperatorFile, 4096)
	if e != nil || strictJSON(raw, &op) != nil || !logicalID.MatchString(op.Username) || !validScope(op.Scope) {
		return op, errors.New("operator login unavailable")
	}
	cost, e := bcrypt.Cost([]byte(op.PasswordHash))
	if e != nil || cost < 12 || cost > 14 {
		return op, errors.New("operator login unavailable")
	}
	return op, nil
}
func ScopeFromContext(ctx context.Context) Scope {
	scope, _ := ctx.Value(scopeKey{}).(Scope)
	return scope
}
func (s *Service) ProductAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		cookie, e := r.Cookie(ProductCookie)
		if e != nil {
			write(w, r, 401, nil, fault(401, "UNAUTHENTICATED", "sign in to control live resources"))
			return
		}
		scope, e := s.Authenticate(r.Context(), cookie.Value)
		if e != nil {
			write(w, r, 401, nil, publicError(e))
			return
		}
		if r.Method != "GET" && (s.Origin == "" || r.Header.Get("Origin") != s.Origin) {
			write(w, r, 403, nil, fault(403, "ORIGIN_REJECTED", "request origin not permitted"))
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), scopeKey{}, scope)))
	})
}
func cookies(w http.ResponseWriter, token string, age int) {
	for name, path := range map[string]string{ProductCookie: "/api", "astralive_config_session": "/api/v0.3/config"} {
		http.SetCookie(w, &http.Cookie{Name: name, Value: token, Path: path, Secure: true, HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: age})
	}
}
func (s *Service) AuthRouter() http.Handler {
	r := chi.NewRouter()
	r.Post("/login", func(w http.ResponseWriter, r *http.Request) {
		if s.Origin == "" || r.Header.Get("Origin") != s.Origin {
			write(w, r, 403, nil, fault(403, "ORIGIN_REJECTED", "request origin not permitted"))
			return
		}
		var in struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if read(r, &in) != nil || len(in.Password) > 72 || len(in.Password) < 12 || len(in.Username) > 128 {
			write(w, r, 401, nil, fault(401, "LOGIN_FAILED", "invalid login"))
			return
		}
		var attempts int
		e := s.DB.QueryRow(r.Context(), `INSERT INTO operator_login_attempts(id,window_at,attempts) VALUES(true,now(),1) ON CONFLICT(id) DO UPDATE SET window_at=CASE WHEN operator_login_attempts.window_at<now()-interval '1 minute' THEN now() ELSE operator_login_attempts.window_at END,attempts=CASE WHEN operator_login_attempts.window_at<now()-interval '1 minute' THEN 1 ELSE operator_login_attempts.attempts+1 END RETURNING attempts`).Scan(&attempts)
		if e != nil {
			write(w, r, 503, nil, fault(503, "LOGIN_UNAVAILABLE", "login unavailable"))
			return
		}
		if attempts > 5 {
			write(w, r, 429, nil, fault(429, "RATE_LIMITED", "wait before retrying login"))
			return
		}
		op, e := s.operator()
		if e != nil {
			write(w, r, 503, nil, fault(503, "LOGIN_UNAVAILABLE", "operator login unavailable"))
			return
		}
		passwordOK := bcrypt.CompareHashAndPassword([]byte(op.PasswordHash), []byte(in.Password)) == nil
		in.Password = ""
		if !passwordOK || subtle.ConstantTimeCompare([]byte(in.Username), []byte(op.Username)) != 1 {
			write(w, r, 401, nil, fault(401, "LOGIN_FAILED", "invalid login"))
			return
		}
		if old, e := r.Cookie(ProductCookie); e == nil {
			_, _ = s.DB.Exec(r.Context(), `DELETE FROM config_auth_sessions WHERE token_hash=$1`, tokenHash(old.Value))
		}
		token, e := s.IssueSession(r.Context(), op.Scope)
		if e != nil {
			write(w, r, 500, nil, e)
			return
		}
		cookies(w, token, 43200)
		write(w, r, 200, map[string]any{"identity": op.Scope, "mode": "SINGLE_OPERATOR", "expiresInSeconds": 43200}, nil)
	})
	r.Group(func(r chi.Router) {
		r.Use(s.ProductAuth)
		r.Get("/me", func(w http.ResponseWriter, r *http.Request) {
			write(w, r, 200, map[string]any{"identity": scopeOf(r), "mode": "SINGLE_OPERATOR"}, nil)
		})
		r.Post("/logout", func(w http.ResponseWriter, r *http.Request) {
			c, _ := r.Cookie(ProductCookie)
			_, e := s.DB.Exec(r.Context(), `DELETE FROM config_auth_sessions WHERE token_hash=$1`, tokenHash(c.Value))
			if e == nil {
				cookies(w, "", -1)
			}
			write(w, r, 200, map[string]any{}, e)
		})
	})
	return r
}

// TokenTransport authenticates Go -> Runtime separately from user/Tool sessions.
type TokenTransport struct {
	Path string
	Base http.RoundTripper
}

func (t TokenTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	token, e := ReadServiceToken(t.Path)
	if e != nil {
		return nil, e
	}
	copy := r.Clone(r.Context())
	copy.Header = r.Header.Clone()
	copy.Header.Set("Authorization", "Bearer "+token)
	base := t.Base
	if base == nil {
		base = &http.Transport{Proxy: nil}
	}
	response, e := base.RoundTrip(copy)
	if e != nil || response.StatusCode < 400 {
		return response, e
	}
	raw, readErr := io.ReadAll(io.LimitReader(response.Body, 4097))
	response.Body.Close()
	response.Body = io.NopCloser(bytes.NewReader(raw))
	var envelope struct {
		Details struct {
			IntegrationCode string `json:"integrationCode"`
		} `json:"details"`
	}
	if readErr == nil && len(raw) <= 4096 && json.Unmarshal(raw, &envelope) == nil {
		switch envelope.Details.IntegrationCode {
		case "PROVIDER_BINDING_EXPIRED", "PROVIDER_BINDING_UNAVAILABLE", "CONFIG_NOT_VERIFIED", "WORKER_NOT_READY", "WORKER_UNAVAILABLE", "WORKER_UNREGISTERED", "PROVIDER_NOT_CONFIGURED", "PROVIDER_UNSUPPORTED", "PROVIDER_BINDING_INVALID":
			return nil, fault(response.StatusCode, envelope.Details.IntegrationCode, "Session Provider unavailable")
		}
	}
	return response, nil
}

// SafeFault translates errors without reflecting SQL, payloads or provider bodies.
func SafeFault(err error) *Fault { return publicError(err) }
