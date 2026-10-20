// Package turnmanager arbitrates the next business turn; it never enqueues GPU
// media, rates comments, or owns a database/lease/recovery coordinator.
package turnmanager

import (
	c "astralive/backend/internal/contentplan/contract"
	"context"
)

// Durable is the frozen CONTROL seam. Agent 2 implements every operation using
// short committed transactions. These request/response types are schema-generated.
// Agent 4 can alias its shared generated DTOs here or adapt at the JSON boundary.
type Durable interface {
	RestoreContentPlan(context.Context, c.RestoreContentPlanRequest) (c.RestoreContentPlanResponse, error)
	SaveContentPlan(context.Context, c.SaveContentPlanRequest) (c.SaveContentPlanResponse, error)
	AdmitTurn(context.Context, c.AdmitTurnRequest) (c.AdmitTurnResponse, error)
	ClaimNextTurn(context.Context, c.ClaimNextTurnRequest) (c.ClaimNextTurnResponse, error)
	DispatchTurn(context.Context, c.DispatchTurnRequest) (c.DispatchTurnResponse, error)
	YieldAtSegmentBoundary(context.Context, c.YieldAtSegmentBoundaryRequest) (c.YieldAtSegmentBoundaryResponse, error)
	ConfirmCheckpoint(context.Context, c.ConfirmCheckpointRequest) (c.ConfirmCheckpointResponse, error)
	QueryExecutionStatus(context.Context, c.QueryExecutionStatusRequest) (c.QueryExecutionStatusResponse, error)
	MarkExecutionUnknown(context.Context, c.MarkExecutionUnknownRequest) (c.MarkExecutionUnknownResponse, error)
	ResumeBroadcastRun(context.Context, c.ResumeBroadcastRunRequest) (c.ResumeBroadcastRunResponse, error)
	StopBroadcastRun(context.Context, c.StopBroadcastRunRequest) (c.StopBroadcastRunResponse, error)
}

// Projection is an in-process read model, NOT a new wire DTO or second store.
// RestoreSnapshot intentionally has no pending-turn/history listing operation.
// Agent 4 must supply an authorized consistent Agent 2 repo projection, including
// selected WAITING comments and executed turns since the last completed SCRIPT.
// Refuse incomplete/torn projections; never replace these with a volatile queue.
type Projection struct {
	RunRevision            int64
	Candidates             []c.Turn // already chosen by interaction.Scheduler; durable order
	History                []c.Turn // includes active and terminated turns, complete for budget
	HistoryComplete        bool
	ProductSnapshotVersion string
	ProviderReady          bool
	OperatorOverride       bool              // must be backed by durable pause/override at ingress
	GapDecisions           map[string]string // segmentId -> authorized SKIP_WITH_GAP decisionId
}
type PolicyReader interface {
	ReadPolicy(context.Context, c.RestoreSnapshot) (Projection, error)
}

// Facts re-reads trusted Product Tools outside transactions. Same valueHash is
// required, not just a refreshed timestamp. Runtime MUST revalidate again before
// its effect-start CAS; this preflight is not a replacement for that check.
type Facts interface {
	Revalidate(context.Context, c.ContentPlan, []c.FactDependency) ([]c.FactDependency, error)
}
type Scope struct{ TenantID, OwnerID, RunID string }
