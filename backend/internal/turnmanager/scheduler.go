package turnmanager

import (
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"context"
	"fmt"
)

// Sources resolves ALL stable identities of one merged Scheduler selection from
// trusted ingress. The legacy Selection only carries its representative event;
// Agent 4's unapplied scheduler patch preserves members for this adapter.
type Sources interface {
	SelectionSources(context.Context, interaction.Selection) ([]c.CommentSource, error)
}
type SelectionAdapter struct {
	Manager *Manager
	Sources Sources
}

var _ interaction.Dispatcher = (*SelectionAdapter)(nil)

func (a *SelectionAdapter) Dispatch(ctx context.Context, v interaction.Selection) (string, error) {
	if a.Manager == nil || a.Sources == nil {
		return "", fmt.Errorf("DEPENDENCY_UNAVAILABLE: durable ingress")
	}
	m := a.Manager
	if v.Policy != "NONE" {
		return "", fmt.Errorf("INVALID_ARGUMENT: ordinary comments never interrupt")
	}
	if m.stopped.Load() || m.override.Load() {
		return "", fmt.Errorf("STATE_CONFLICT")
	}
	s, e := m.restore(ctx)
	if e != nil {
		return "", e
	}
	if s.Bundle == nil || s.Run.DesiredState != "LIVE" || s.Run.Status != "LIVE" || s.Run.StopRevision > 0 || v.ProductID != s.Bundle.Plan.ProductId || v.Event.InternalRoomID != s.Run.RoomId || s.Run.CurrentSessionId == nil || v.Event.SessionID != *s.Run.CurrentSessionId {
		return "", fmt.Errorf("PLAN_CHANGED or RUN_STOPPED")
	}
	expires := v.Event.ReceivedAt.Add(m.cfg.CommentTTL)
	if !m.now().Before(expires) {
		return "", fmt.Errorf("EXPIRED")
	}
	sources, e := a.Sources.SelectionSources(ctx, v)
	if e != nil {
		return "", e
	}
	if len(sources) < v.Audience || len(sources) == 0 || len(sources) > 128 {
		return "", fmt.Errorf("INVALID_ARGUMENT: merged identities missing")
	}
	for _, src := range sources {
		if !contentplan.ValidID(src.SourceReceiptId) || !contentplan.ValidID(src.SourceEventId) || !contentplan.ValidID(src.Platform) || !contentplan.ValidID(src.PlatformRoomId) || !contentplan.ValidID(src.TraceId) || src.Platform != v.Event.Platform || src.PlatformRoomId != v.Event.PlatformRoomID || src.TraceId == "" {
			return "", fmt.Errorf("INVALID_ARGUMENT: stable source identity")
		}
	}
	// Durable run-scoped identity uniqueness is the deduplication authority; the
	// Scheduler remains the sole owner of scoring, semantic merging and rate limits.
	// Use representative stable source, not traceId or a regenerated receive time.
	key, _ := contentplan.Version([]string{s.Run.RunId, sources[0].Platform, sources[0].PlatformRoomId, sources[0].SourceEventId})
	id := "turn_" + key
	deadline := contentplan.Stamp(expires)
	priority := int64(v.Priority)
	if priority < 40 {
		priority = 40
	}
	if priority > 80 {
		priority = 80
	}
	turn := c.Turn{TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, TurnId: id, PlanId: &s.Bundle.Plan.PlanId, TurnType: "COMMENT", SourceCommentTraceId: &v.Event.TraceID, SourceIdentities: sources, Priority: priority, State: "WAITING", ScheduledAt: contentplan.Stamp(v.SelectedAt), ExpiresAt: &deadline, InputText: v.Event.Content, IdempotencyKey: "selection:" + key, Revision: 1}
	admitted, e := m.durable.AdmitTurn(ctx, c.AdmitTurnRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: ids.New("req"), TenantId: m.scope.TenantID, OwnerId: m.scope.OwnerID, RunId: m.scope.RunID, ExpectedRevision: s.Run.Revision, IdempotencyKey: turn.IdempotencyKey, Turn: turn})
	if e != nil {
		return "", e
	}
	// Legacy Dispatcher calls this an utterance ID. In durable mode this is an
	// admission TURN ID, never a fabricated UtteranceId. UI wiring must label it.
	return admitted.Turn.TurnId, nil
}

// SourcesFromEvents converts the Scheduler's preserved normalized members. Events
// without platform IDs must already carry a DURABLE ingress receipt identity.
func SourcesFromEvents(events []platform.Event) ([]c.CommentSource, error) {
	if len(events) == 0 || len(events) > 128 {
		return nil, fmt.Errorf("INVALID_ARGUMENT: source count")
	}
	out := make([]c.CommentSource, 0, len(events))
	for _, e := range events {
		if !contentplan.ValidID(e.EventID) || !contentplan.ValidID(e.TraceID) || !contentplan.ValidID(e.Platform) || !contentplan.ValidID(e.PlatformRoomID) {
			return nil, fmt.Errorf("INVALID_ARGUMENT: durable ingress identity required")
		}
		source := e.SourceEventID
		if source == "" {
			source = e.EventID
		}
		if !contentplan.ValidID(source) {
			return nil, fmt.Errorf("INVALID_ARGUMENT: ingress must map external source to stable contract ID")
		}
		out = append(out, c.CommentSource{SourceReceiptId: e.EventID, Platform: e.Platform, PlatformRoomId: e.PlatformRoomID, SourceEventId: source, TraceId: e.TraceID})
	}
	return out, nil
}
