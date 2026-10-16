package httpapi

import (
	"errors"
	"net/http"
	"time"

	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/durableintegration"
	"astralive/backend/internal/durablelive"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/turnmanager"
	"astralive/backend/internal/userconfig"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
)

// This owner-authenticated product surface calls existing in-process repository
// seams. It exposes no internal role tokens, Publisher credentials or raw SQL.
// There is deliberately no LIVE/create/attach endpoint while release is blocked.
func (h *Server) durableRouter() http.Handler {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if h.Config == nil {
				failure(w, r, 401, "UNAUTHENTICATED", "sign in required")
				return
			}
			if h.S.Durable == nil {
				failure(w, r, 503, "DEPENDENCY_UNAVAILABLE", "durable recovery unavailable")
				return
			}
			h.Config.ProductAuth(next).ServeHTTP(w, r)
		})
	})
	r.Get("/sessions/{sessionId}", h.durableSession)
	r.Post("/runs/{runId}/decisions", h.durableDecision)
	r.Post("/runs/{runId}/stop", h.durableStop)
	return r
}

func durablePrincipal(r *http.Request) durablelive.Principal {
	scope := userconfig.ScopeFromContext(r.Context())
	return durablelive.Principal{Role: "CONTROL", TenantID: scope.TenantID, OwnerID: scope.UserID, InstanceID: scope.UserID}
}

func durableFailure(w http.ResponseWriter, r *http.Request, e error) {
	var f *durablelive.Fault
	if !errors.As(e, &f) {
		failure(w, r, 503, "DEPENDENCY_UNAVAILABLE", "durable recovery unavailable")
		return
	}
	status := 409
	switch f.Code {
	case "UNAUTHENTICATED":
		status = 401
	case "FORBIDDEN":
		status = 403
	case "RESOURCE_NOT_FOUND":
		status = 404
	case "INVALID_ARGUMENT":
		status = 422
	case "OVERLOADED":
		status = 429
	case "DEPENDENCY_UNAVAILABLE", "RECOVERY_UNKNOWN":
		status = 503
	}
	failure(w, r, status, f.Code, f.Code)
}

func (h *Server) durableSession(w http.ResponseWriter, r *http.Request) {
	p := durablePrincipal(r)
	sid := chi.URLParam(r, "sessionId")
	if e := h.Config.CheckOwner(r.Context(), userconfig.ScopeFromContext(r.Context()), "session", sid); e != nil {
		configFailure(w, r, e)
		return
	}
	var runID string
	e := h.S.DB.QueryRow(r.Context(), `SELECT run_id FROM dl05_run_sessions WHERE session_id=$1 AND tenant_id=$2 AND owner_id=$3`, sid, p.TenantID, p.OwnerID).Scan(&runID)
	if e != nil {
		if errors.Is(e, pgx.ErrNoRows) {
			respond(w, r, 200, map[string]any{"managed": false})
			return
		}
		durableFailure(w, r, e)
		return
	}
	a := &durableintegration.Adapter{Store: h.S.Durable, Principal: p}
	snapshot, e := a.RestoreContentPlan(r.Context(), c.RestoreContentPlanRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: p.TenantID, OwnerId: p.OwnerID, RunId: runID})
	if e != nil {
		durableFailure(w, r, e)
		return
	}
	projection, e := a.ReadPolicy(r.Context(), snapshot.Snapshot)
	if e != nil {
		durableFailure(w, r, e)
		return
	}
	choice, e := turnmanager.Decide(snapshot.Snapshot, projection, turnmanager.DefaultConfig(), time.Now())
	if e != nil {
		durableFailure(w, r, e)
		return
	}
	respond(w, r, 200, map[string]any{"managed": true, "snapshot": snapshot.Snapshot, "choice": choice, "releaseGate": "OUTPUT_FENCE_UNPROVEN"})
}

func (h *Server) durableDecision(w http.ResponseWriter, r *http.Request) {
	var input struct {
		DecisionID       string `json:"decisionId"`
		AttemptID        string `json:"attemptId"`
		ExpectedRevision int64  `json:"expectedRevision"`
		Action           string `json:"action"`
		Reason           string `json:"reason"`
		CreatedAt        string `json:"createdAt"`
	}
	if !decode(w, r, &input) {
		return
	}
	if !contentplan.ValidID(input.DecisionID) || !contentplan.ValidID(input.AttemptID) || input.ExpectedRevision < 1 {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid decision identity/revision")
		return
	}
	p := durablePrincipal(r)
	d := durablelive.Decision{DecisionId: input.DecisionID, AttemptId: input.AttemptID, OperatorId: p.InstanceID, Action: input.Action, Reason: input.Reason, CreatedAt: input.CreatedAt}
	if e := h.S.Durable.ResolveUnknown(r.Context(), p, chi.URLParam(r, "runId"), input.ExpectedRevision, d); e != nil {
		durableFailure(w, r, e)
		return
	}
	respond(w, r, 200, map[string]any{"decisionId": d.DecisionId, "action": d.Action, "mediaAuthorized": false})
}

func (h *Server) durableStop(w http.ResponseWriter, r *http.Request) {
	var input struct {
		DecisionID string `json:"decisionId"`
	}
	if !decode(w, r, &input) {
		return
	}
	p := durablePrincipal(r)
	out, e := h.S.Durable.StopBroadcastRun(r.Context(), p, durablelive.StopBroadcastRunRequest{SchemaVersion: "0.5", ContractRevision: durablelive.RevisionName, RequestId: ids.New("req"), TenantId: p.TenantID, OwnerId: p.OwnerID, RunId: chi.URLParam(r, "runId"), ExpectedRevision: 1, DecisionId: input.DecisionID, IdempotencyKey: "stop:" + input.DecisionID, ReasonCode: "OPERATOR_STOP"})
	if e != nil {
		durableFailure(w, r, e)
		return
	}
	respond(w, r, 202, out)
}
