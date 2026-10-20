package turnmanager

import (
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/ids"
	"context"
	"fmt"
	"sync/atomic"
	"time"
)

type Manager struct {
	durable  Durable
	reader   PolicyReader
	facts    Facts
	scope    Scope
	cfg      Config
	now      func() time.Time
	stepping atomic.Bool // exclusion only; no mutex/SQL/borrowed transaction cycle
	stopped  atomic.Bool
	override atomic.Bool
}

func New(d Durable, r PolicyReader, f Facts, scope Scope, cfg Config, clock func() time.Time) (*Manager, error) {
	if d == nil || r == nil || f == nil || !contentplan.ValidID(scope.TenantID) || !contentplan.ValidID(scope.OwnerID) || !contentplan.ValidID(scope.RunID) {
		return nil, fmt.Errorf("INVALID_ARGUMENT: dependencies/scope")
	}
	if e := cfg.Validate(); e != nil {
		return nil, e
	}
	if clock == nil {
		clock = time.Now
	}
	return &Manager{durable: d, reader: r, facts: f, scope: scope, cfg: cfg, now: clock}, nil
}
func (m *Manager) restore(ctx context.Context) (c.RestoreSnapshot, error) {
	r, e := m.durable.RestoreContentPlan(ctx, c.RestoreContentPlanRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID})
	if e != nil {
		return c.RestoreSnapshot{}, e
	}
	s := r.Snapshot
	if s.Run.RunId != m.scope.RunID || s.Run.TenantId != m.scope.TenantID || s.Run.OwnerId != m.scope.OwnerID {
		return s, fmt.Errorf("FORBIDDEN")
	}
	return s, nil
}
func (m *Manager) read(ctx context.Context) (c.RestoreSnapshot, Projection, Choice, error) {
	s, e := m.restore(ctx)
	if e != nil {
		return s, Projection{}, Choice{State: Recovering}, e
	}
	// Stop never depends on a history-reader being available.
	if s.Run.DesiredState == "STOPPED" || s.Run.StopRevision > 0 || s.Run.Status == "FAILED" {
		return s, Projection{}, Choice{State: Stopped}, nil
	}
	p, e := m.reader.ReadPolicy(ctx, s)
	if e != nil {
		return s, p, Choice{State: Recovering}, e
	}
	v, e := Decide(s, p, m.cfg, m.now())
	return s, p, v, e
}
func (m *Manager) SavePlan(ctx context.Context, b c.PlanBundle) (c.SaveContentPlanResponse, error) {
	if e := contentplan.Validate(b); e != nil {
		return c.SaveContentPlanResponse{}, e
	}
	s, e := m.restore(ctx)
	if e != nil {
		return c.SaveContentPlanResponse{}, e
	}
	if b.Plan.RunId != m.scope.RunID || b.Plan.TenantId != m.scope.TenantID || b.Plan.OwnerId != m.scope.OwnerID {
		return c.SaveContentPlanResponse{}, fmt.Errorf("FORBIDDEN")
	}
	return m.durable.SaveContentPlan(ctx, c.SaveContentPlanRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, IdempotencyKey: "plan:" + contentplan.Hash(b.Plan.PlanId), Bundle: b})
}

// Step may be called by a coalesced event/poll loop. It executes at most one
// ClaimNextTurn and one persisted outbox wake. All media completion comes back
// through Agent 2. A 202 response never advances a cursor here.
func (m *Manager) Step(ctx context.Context) (Choice, error) {
	if m.stopped.Load() {
		return Choice{State: Stopped}, nil
	}
	if m.override.Load() {
		return Choice{State: OperatorOverride}, nil
	}
	if !m.stepping.CompareAndSwap(false, true) {
		return Choice{State: Recovering}, fmt.Errorf("OVERLOADED: step in progress")
	}
	defer m.stepping.Store(false)
	s, _, choice, e := m.read(ctx)
	if e != nil {
		return choice, e
	}
	if choice.Current != nil || choice.Source == "" {
		return choice, nil
	}
	if s.Slot.BoundaryCheckpointId != nil {
		identity, _ := contentplan.Version([]any{m.scope.RunID, s.Run.RunEpoch, *s.Slot.BoundaryCheckpointId})
		key := "yield:" + identity
		y, e := m.durable.YieldAtSegmentBoundary(ctx, c.YieldAtSegmentBoundaryRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, RunEpoch: s.Run.RunEpoch, BoundaryCheckpointId: *s.Slot.BoundaryCheckpointId, ExpectedSlotVersion: s.Slot.SlotVersion, IdempotencyKey: key})
		if e != nil {
			return choice, e
		}
		if y.State != "YIELDED" {
			choice.State = YieldPending
			return choice, nil
		}
		// Re-evaluate TTL, product, Stop, fairness and revision AFTER yielding.
		s, _, choice, e = m.read(ctx)
		if e != nil || choice.Current != nil || choice.Source == "" {
			return choice, e
		}
	}
	if s.Bundle == nil {
		return Choice{State: Recovering, Reason: "PLAN_REQUIRED"}, nil
	}
	plan := s.Bundle.Plan
	var turn c.Turn
	if choice.Comment != nil {
		turn = *choice.Comment
	} else if choice.Segment != nil {
		seg := *choice.Segment
		turn = c.Turn{TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, TurnId: "turn_" + contentplan.Hash(seg.IdempotencyKey), PlanId: &plan.PlanId, TurnType: "SCRIPT", SourceSegmentId: &seg.SegmentId, SourceIdentities: []c.CommentSource{}, Priority: 20, State: "READY", ScheduledAt: seg.CreatedAt, InputText: seg.Content, IdempotencyKey: "turn:" + seg.IdempotencyKey, Revision: 1}
	} else {
		return choice, nil
	}
	deps := []c.FactDependency{}
	if choice.Comment == nil && choice.Segment != nil {
		deps = choice.Segment.FactDependencies
	}
	fresh, e := m.facts.Revalidate(ctx, plan, deps)
	if e != nil {
		return Choice{State: Recovering, Reason: "FACT_VALIDATION_FAILED"}, e
	}
	if e = validateRefreshed(plan, deps, fresh, m.now()); e != nil {
		return Choice{State: Recovering, Reason: "PLAN_CHANGED"}, e
	}
	if m.stopped.Load() || m.override.Load() {
		return Choice{State: Recovering, Reason: "CONTROL_BARRIER"}, nil
	}
	if turn.ExpiresAt != nil {
		x, e := timestamp(*turn.ExpiresAt)
		if e != nil || !m.now().Before(x) {
			return Choice{State: Idle, Reason: "EXPIRED"}, nil
		}
	}
	if turn.TurnType == "SCRIPT" {
		a, e := m.durable.AdmitTurn(ctx, c.AdmitTurnRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, IdempotencyKey: turn.IdempotencyKey, Turn: turn})
		if e != nil {
			return choice, e
		}
		turn = a.Turn
		s.Run.Revision = a.RunRevision
	}
	// The repository MUST repeat facts/TTL/Stop/epoch/slot checks, and bind freshly
	// validated exact-value dependencies into the immutable command. Claim has no
	// policy-owned alternate SQL path or side-channel payload fields.
	claimed, e := m.durable.ClaimNextTurn(ctx, c.ClaimNextTurnRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, RunEpoch: s.Run.RunEpoch, CandidateTurnId: turn.TurnId, ExpectedSlotVersion: s.Slot.SlotVersion, IdempotencyKey: "claim:" + turn.IdempotencyKey})
	if e != nil {
		return choice, e
	}
	_, e = m.durable.DispatchTurn(ctx, c.DispatchTurnRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: claimed.RunRevision, RunEpoch: s.Run.RunEpoch, IntentId: claimed.Intent.IntentId, CommandId: claimed.Intent.CommandId, IdempotencyKey: "dispatch:" + contentplan.Hash(claimed.Intent.IntentId)})
	// An ambiguous dispatch response leaves the durable slot owned. A subsequent
	// Step reads it and waits for Recovery; it does not retry a speech request.
	return choice, e
}
func validateRefreshed(p c.ContentPlan, old, fresh []c.FactDependency, now time.Time) error {
	if len(old) != len(fresh) {
		return fmt.Errorf("PLAN_CHANGED: fact count")
	}
	for i, f := range fresh {
		if f.ProductId != p.ProductId || f.SourceVersion != p.Snapshot.SourceVersion || f.Kind != old[i].Kind || f.ValueHash != old[i].ValueHash {
			return fmt.Errorf("PLAN_CHANGED: fact assertion")
		}
		if e := contentplan.Fresh(f, now); e != nil {
			return e
		}
	}
	return nil
}

// Confirm accepts evidence through the durable validator; it never projects local
// progress or invents a BUSINESS_COMMIT from an HTTP/TTS completion notification.
func (m *Manager) Confirm(ctx context.Context, req c.ConfirmCheckpointRequest) (c.ConfirmCheckpointResponse, error) {
	if req.TenantId != m.scope.TenantID || req.OwnerId != m.scope.OwnerID || req.RunId != m.scope.RunID || req.SchemaVersion != c.SchemaVersion || req.ContractRevision != c.RevisionName {
		return c.ConfirmCheckpointResponse{}, fmt.Errorf("FORBIDDEN")
	}
	return m.durable.ConfirmCheckpoint(ctx, req)
}

// Override closes local admission immediately. Ingress must also pause the run
// and use the EXISTING FORCE/fence path. This method does not interrupt media.
func (m *Manager) Override() { m.override.Store(true) }
func (m *Manager) Resume(ctx context.Context, decisionID string) (c.ResumeBroadcastRunResponse, error) {
	if !contentplan.ValidID(decisionID) || m.stopped.Load() {
		return c.ResumeBroadcastRunResponse{}, fmt.Errorf("RUN_STOPPED or missing decision")
	}
	s, e := m.restore(ctx)
	if e != nil {
		return c.ResumeBroadcastRunResponse{}, e
	}
	r, e := m.durable.ResumeBroadcastRun(ctx, c.ResumeBroadcastRunRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, ExpectedPreviousEpoch: s.Run.RunEpoch, DecisionId: decisionID, IdempotencyKey: "resume:" + contentplan.Hash(decisionID)})
	if e == nil {
		m.override.Store(false)
	}
	return r, e
}
func (m *Manager) Stop(ctx context.Context, decisionID string) (c.StopBroadcastRunResponse, error) {
	m.stopped.Store(true) // sticky even if SQL fails; caller can retry Stop safely
	if !contentplan.ValidID(decisionID) {
		return c.StopBroadcastRunResponse{}, fmt.Errorf("INVALID_ARGUMENT: decision")
	}
	// Stop's expectedRevision is audit-only; do not make Stop depend on restore.
	return m.durable.StopBroadcastRun(ctx, c.StopBroadcastRunRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: 1, DecisionId: decisionID, IdempotencyKey: "stop:" + contentplan.Hash(decisionID), ReasonCode: "OPERATOR_STOP"})
}

// Run owns no durable state. Agent 4 supplies checkpoint/ingress wakeups and a
// bounded ticker so no-comment sessions still continue after each completion.
func (m *Manager) Run(ctx context.Context, wake <-chan struct{}, onStep func(Choice, error)) error {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		v, e := m.Step(ctx)
		if onStep != nil {
			onStep(v, e)
		}
		if v.State == Stopped {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case _, ok := <-wake:
			if !ok {
				wake = nil
			}
		case <-ticker.C:
		}
	}
}
