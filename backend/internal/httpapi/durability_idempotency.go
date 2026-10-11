package httpapi

import (
	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/userconfig"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"strings"
)

// durableIdempotency buffers the HTTP result until the shared business+Outbox+response transaction commits.
func (h *Server) durableIdempotency(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		key := r.Header.Get("Idempotency-Key")
		if key == "" {
			failure(w, r, 400, "INVALID_ARGUMENT", "Idempotency-Key required")
			return
		}
		raw, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
		if e != nil {
			failure(w, r, 422, "INVALID_ARGUMENT", "invalid body")
			return
		}
		r.Body = io.NopCloser(bytes.NewReader(raw))
		digest := sha256.Sum256(raw)
		hash := hex.EncodeToString(digest[:])
		route := r.URL.Path
		if h.Config != nil {
			scope := userconfig.ScopeFromContext(r.Context())
			route = scope.TenantID + ":" + scope.UserID + ":" + route
		}
		tx, e := h.S.DB.Begin(r.Context())
		if e != nil {
			if strings.HasSuffix(r.URL.Path, "/stop") {
				_ = h.S.EmergencyStop(r.Context(), chi.URLParam(r, "sessionId"))
			}
			dbFail(w, r, e, "")
			return
		}
		defer tx.Rollback(r.Context())
		if _, e = tx.Exec(r.Context(), `SELECT pg_advisory_xact_lock(hashtext($1))`, route+":"+key); e != nil {
			dbFail(w, r, e, "")
			return
		}
		if h.Config != nil {
			se, err := h.S.Q.WithTx(tx).GetSession(r.Context(), chi.URLParam(r, "sessionId"))
			if err != nil {
				dbFail(w, r, err, "SESSION_NOT_FOUND")
				return
			}
			if err = h.Config.CheckOwner(r.Context(), userconfig.ScopeFromContext(r.Context()), "room", se.RoomID); err != nil {
				configFailure(w, r, err)
				return
			}
		}
		old, e := h.S.Q.WithTx(tx).GetIdempotency(r.Context(), dbgen.GetIdempotencyParams{Key: key, Route: route})
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
		buffer := &durableResponse{header: make(http.Header), Code: 200}
		next(buffer, r.WithContext(durability.WithBusinessTx(r.Context(), tx)))
		if buffer.Code >= 200 && buffer.Code < 300 {
			_, e = tx.Exec(r.Context(), `INSERT INTO idempotency_keys(key,route,request_hash,response_status,response_body,expires_at) VALUES($1,$2,$3,$4,$5,clock_timestamp()+interval '24 hours')`, key, route, hash, buffer.Code, buffer.Body.Bytes())
			if e != nil {
				dbFail(w, r, e, "")
				return
			}
			if e = tx.Commit(r.Context()); e != nil {
				dbFail(w, r, e, "")
				return
			}
		}
		for k, v := range buffer.Header() {
			w.Header()[k] = v
		}
		w.WriteHeader(buffer.Code)
		_, _ = w.Write(buffer.Body.Bytes())
	}
}

type durableResponse struct {
	header      http.Header
	Code        int
	Body        bytes.Buffer
	wroteHeader bool
}

func (b *durableResponse) Header() http.Header { return b.header }
func (b *durableResponse) WriteHeader(status int) {
	if !b.wroteHeader {
		b.Code = status
		b.wroteHeader = true
	}
}
func (b *durableResponse) Write(raw []byte) (int, error) {
	if !b.wroteHeader {
		b.WriteHeader(200)
	}
	return b.Body.Write(raw)
}
