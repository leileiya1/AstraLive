// Package durableintegration connects the planner/manager to the authoritative SQL Store.
// It owns no shadow queue, database or execution authorization.
package durableintegration

import (
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/durablelive"
	"astralive/backend/internal/turnmanager"
	"bytes"
	"context"
	"encoding/json"
	"errors"
)

// Adapter captures a registered principal. Caller JSON can never select a role or owner.
type Adapter struct {
	Store     *durablelive.Store
	Principal durablelive.Principal
}

var _ turnmanager.Durable = (*Adapter)(nil)
var _ turnmanager.PolicyReader = (*Adapter)(nil)

func (a *Adapter) call(ctx context.Context, operation string, request, response any) error {
	if a == nil || a.Store == nil {
		return errors.New("DEPENDENCY_UNAVAILABLE")
	}
	raw, err := json.Marshal(request)
	if err != nil {
		return err
	}
	result, err := a.Store.Call(ctx, a.Principal, operation, raw)
	if err != nil {
		return err
	}
	raw, err = durablelive.Canonical(result)
	if err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	return decoder.Decode(response)
}

func (a *Adapter) RestoreContentPlan(ctx context.Context, request c.RestoreContentPlanRequest) (out c.RestoreContentPlanResponse, err error) {
	err = a.call(ctx, "RestoreContentPlan", request, &out)
	return
}

func (a *Adapter) SaveContentPlan(ctx context.Context, request c.SaveContentPlanRequest) (out c.SaveContentPlanResponse, err error) {
	err = a.call(ctx, "SaveContentPlan", request, &out)
	return
}

func (a *Adapter) AdmitTurn(ctx context.Context, request c.AdmitTurnRequest) (out c.AdmitTurnResponse, err error) {
	err = a.call(ctx, "AdmitTurn", request, &out)
	return
}

func (a *Adapter) ClaimNextTurn(ctx context.Context, request c.ClaimNextTurnRequest) (out c.ClaimNextTurnResponse, err error) {
	err = a.call(ctx, "ClaimNextTurn", request, &out)
	return
}

func (a *Adapter) DispatchTurn(ctx context.Context, request c.DispatchTurnRequest) (out c.DispatchTurnResponse, err error) {
	err = a.call(ctx, "DispatchTurn", request, &out)
	return
}

func (a *Adapter) YieldAtSegmentBoundary(ctx context.Context, request c.YieldAtSegmentBoundaryRequest) (out c.YieldAtSegmentBoundaryResponse, err error) {
	err = a.call(ctx, "YieldAtSegmentBoundary", request, &out)
	return
}

func (a *Adapter) ConfirmCheckpoint(ctx context.Context, request c.ConfirmCheckpointRequest) (out c.ConfirmCheckpointResponse, err error) {
	err = a.call(ctx, "ConfirmCheckpoint", request, &out)
	return
}

func (a *Adapter) QueryExecutionStatus(ctx context.Context, request c.QueryExecutionStatusRequest) (out c.QueryExecutionStatusResponse, err error) {
	err = a.call(ctx, "QueryExecutionStatus", request, &out)
	return
}

func (a *Adapter) MarkExecutionUnknown(ctx context.Context, request c.MarkExecutionUnknownRequest) (out c.MarkExecutionUnknownResponse, err error) {
	err = a.call(ctx, "MarkExecutionUnknown", request, &out)
	return
}

func (a *Adapter) ResumeBroadcastRun(ctx context.Context, request c.ResumeBroadcastRunRequest) (out c.ResumeBroadcastRunResponse, err error) {
	err = a.call(ctx, "ResumeBroadcastRun", request, &out)
	return
}

func (a *Adapter) StopBroadcastRun(ctx context.Context, request c.StopBroadcastRunRequest) (out c.StopBroadcastRunResponse, err error) {
	err = a.call(ctx, "StopBroadcastRun", request, &out)
	return
}

func (a *Adapter) ReadPolicy(ctx context.Context, snapshot c.RestoreSnapshot) (out turnmanager.Projection, err error) {
	if a == nil || a.Store == nil {
		return out, errors.New("DEPENDENCY_UNAVAILABLE")
	}
	state, err := a.Store.ReadPolicyState(ctx, a.Principal, snapshot.Run.RunId, snapshot.Run.Revision)
	if err != nil {
		return out, err
	}
	raw, err := json.Marshal(state.Candidates)
	if err != nil {
		return out, err
	}
	if err = json.Unmarshal(raw, &out.Candidates); err != nil {
		return out, err
	}
	raw, err = json.Marshal(state.History)
	if err != nil {
		return out, err
	}
	if err = json.Unmarshal(raw, &out.History); err != nil {
		return out, err
	}
	out.RunRevision = state.RunRevision
	out.HistoryComplete = state.HistoryComplete
	out.ProductSnapshotVersion = state.ProductSnapshotVersion
	out.ProviderReady = state.ProviderReady
	out.OperatorOverride = state.OperatorOverride
	out.GapDecisions = state.GapDecisions
	return out, nil
}
