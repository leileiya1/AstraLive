package durablelive

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
)

// Credential is supplied by a trusted registrar (owner/session binding). Never
// construct it from request tenant/owner fields. Use distinct instance tokens.
type Credential struct {
	Token     string
	Principal Principal
}

func NewHandler(s *Store, credentials []Credential) (http.Handler, error) {
	if len(credentials) == 0 {
		return nil, fault("UNAUTHENTICATED")
	}
	seen := map[string]bool{}
	roles := map[string]bool{}
	for _, c := range credentials {
		if len(c.Token) < 32 || seen[c.Token] || c.Principal.InstanceID == "" || c.Principal.TenantID == "" || c.Principal.OwnerID == "" {
			return nil, fault("UNAUTHENTICATED")
		}
		if c.Principal.Role != "CONTROL" && c.Principal.Role != "RUNTIME_JOURNAL" && c.Principal.Role != "OUTPUT_GUARDIAN" {
			return nil, fault("FORBIDDEN")
		}
		seen[c.Token] = true
		roles[c.Principal.Role] = true
	}
	for _, r := range []string{"CONTROL", "RUNTIME_JOURNAL", "OUTPUT_GUARDIAN"} {
		if !roles[r] {
			return nil, fault("UNAUTHENTICATED")
		}
	}
	mux := http.NewServeMux()
	for _, op := range Operations() {
		if op.Target != "BACKEND" {
			continue
		}
		op := op
		mux.HandleFunc(op.Method+" "+op.Path, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			var p Principal
			auth := r.Header.Get("Authorization")
			if strings.HasPrefix(auth, "Bearer ") {
				token := strings.TrimPrefix(auth, "Bearer ")
				for _, c := range credentials {
					if subtle.ConstantTimeCompare([]byte(token), []byte(c.Token)) == 1 {
						p = c.Principal
					}
				}
			}
			if p.Role == "" {
				writeFault(w, "unknown", fault("UNAUTHENTICATED"))
				return
			}
			b, e := io.ReadAll(io.LimitReader(r.Body, MaxBody+1))
			if e != nil || len(b) > MaxBody {
				writeFault(w, "unknown", fault("INVALID_ARGUMENT"))
				return
			}
			q, e := Decode(b)
			if e != nil {
				writeFault(w, "unknown", e)
				return
			}
			if str(q, "runId") != r.PathValue("runId") {
				writeFault(w, str(q, "requestId"), fault("INVALID_ARGUMENT"))
				return
			}
			out, e := s.Call(r.Context(), p, op.OperationID, b)
			if e != nil {
				writeFault(w, str(q, "requestId"), e)
				return
			}
			w.WriteHeader(op.SuccessStatus)
			_ = json.NewEncoder(w).Encode(out)
		})
	}
	return mux, nil
}
func writeFault(w http.ResponseWriter, requestID string, e error) {
	code := "DEPENDENCY_UNAVAILABLE"
	var f *Fault
	if errors.As(e, &f) {
		code = f.Code
	}
	if requestID == "" {
		requestID = "unknown"
	}
	status := 503
	switch code {
	case "UNAUTHENTICATED":
		status = 401
	case "FORBIDDEN":
		status = 403
	case "RESOURCE_NOT_FOUND":
		status = 404
	case "INVALID_ARGUMENT", "SEGMENT_TOO_LONG":
		status = 422
	case "OVERLOADED":
		status = 429
	case "DEPENDENCY_UNAVAILABLE", "RECOVERY_UNKNOWN":
		status = 503
	default:
		status = 409
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(Object{"requestId": requestID, "code": code, "message": staticMessage(code), "retryable": status == 503 || status == 429})
}
