package turnmanager

import (
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"
)

// This CPU fake models atomic contract effects, NOT PostgreSQL, real journal
// durability or actual sink authenticity. It exists only in _test.go.
type fakeDurable struct {
	mu                    sync.Mutex
	snap                  c.RestoreSnapshot
	now                   time.Time
	turns                 map[string]c.Turn
	claims                map[string]c.ClaimNextTurnResponse
	commands              map[string]c.RuntimeCommand
	checkpoints           map[string]string
	drained               map[string]bool
	sources               map[string]string
	intents               map[string]c.DispatchIntent
	calls                 []string
	emissions             []string
	events                []wireEvent
	claimCount, wakeCount int
	dispatchErr           bool
	provider              bool
	override              bool
	currentVersion        string
	gaps                  map[string]string
}
type wireEvent struct {
	Operation string `json:"operation"`
	Request   any    `json:"request"`
}

func clone[T any](x T) T { b, _ := json.Marshal(x); var y T; _ = json.Unmarshal(b, &y); return y }
func ptr[T any](x T) *T  { return &x }

var clockStart = time.Date(2026, 10, 16, 0, 0, 0, 0, time.UTC)

func newFake(t *testing.T, n int) *fakeDurable {
	t.Helper()
	f := &fakeDurable{now: clockStart, turns: map[string]c.Turn{}, claims: map[string]c.ClaimNextTurnResponse{}, commands: map[string]c.RuntimeCommand{}, checkpoints: map[string]string{}, drained: map[string]bool{}, sources: map[string]string{}, intents: map[string]c.DispatchIntent{}, provider: true, gaps: map[string]string{}}
	r := c.BroadcastRun{TenantId: "tenant", OwnerId: "owner", RunId: "run", RoomId: "room", Status: "LIVE", RunEpoch: 1, CurrentSessionId: ptr("session"), CurrentPlanId: ptr("plan"), StartedAt: ptr(contentplan.Stamp(f.now)), UpdatedAt: contentplan.Stamp(f.now), DesiredState: "LIVE", RecoveryPolicy: "MANUAL_ON_UNKNOWN", Revision: 1}
	statements := []contentplan.Statement{}
	for i := 1; i <= n; i++ {
		statements = append(statements, contentplan.Statement{Text: fmt.Sprintf("第%d段介绍纯棉面料。", i)})
	}
	bundle, e := contentplan.Build(contentplan.Input{Run: r, Snapshot: c.ProductSnapshot{ProductId: "product", Name: "上衣", Description: "纯棉面料。", Sizes: []string{}, SourceVersion: "v1"}, PlanID: "plan", Revision: 1, Statements: statements}, contentplan.DefaultConfig(), f.now)
	if e != nil {
		t.Fatal(e)
	}
	f.currentVersion = bundle.Plan.ProductSnapshotVersion
	f.snap = c.RestoreSnapshot{Run: r, Bundle: &bundle, ResumeSequence: 1, Slot: c.Slot{SlotVersion: 1}, Decisions: []c.Decision{}, UnresolvedAttempts: []c.ExecutionAttempt{}}
	return f
}
func (f *fakeDurable) clock() time.Time { f.mu.Lock(); defer f.mu.Unlock(); return f.now }
func (f *fakeDurable) advance(d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.now = f.now.Add(d)
}
func (f *fakeDurable) manager(t *testing.T) *Manager {
	t.Helper()
	m, e := New(f, f, f, Scope{"tenant", "owner", "run"}, DefaultConfig(), f.clock)
	if e != nil {
		t.Fatal(e)
	}
	return m
}
func (f *fakeDurable) record(op string, req any) {
	f.calls = append(f.calls, op)
	f.events = append(f.events, wireEvent{op, clone(req)})
}
func (f *fakeDurable) RestoreContentPlan(_ context.Context, q c.RestoreContentPlanRequest) (c.RestoreContentPlanResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("RestoreContentPlan", q)
	return c.RestoreContentPlanResponse{RequestId: q.RequestId, Snapshot: clone(f.snap)}, nil
}
func (f *fakeDurable) ReadPolicy(_ context.Context, s c.RestoreSnapshot) (Projection, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := Projection{RunRevision: f.snap.Run.Revision, HistoryComplete: true, ProviderReady: f.provider, ProductSnapshotVersion: f.currentVersion, OperatorOverride: f.override, GapDecisions: clone(f.gaps)}
	for _, t := range f.turns {
		p.History = append(p.History, clone(t))
		if t.State == "READY" || t.State == "WAITING" {
			p.Candidates = append(p.Candidates, clone(t))
		}
	}
	return p, nil
}
func (f *fakeDurable) Revalidate(_ context.Context, p c.ContentPlan, deps []c.FactDependency) ([]c.FactDependency, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if p.ProductSnapshotVersion != f.currentVersion {
		return nil, fmt.Errorf("PLAN_CHANGED")
	}
	out := clone(deps)
	for i := range out {
		out[i].ValidatedAt = contentplan.Stamp(f.now)
		out[i].ExpiresAt = contentplan.Stamp(f.now.Add(2 * time.Second))
	}
	return out, nil
}
func (f *fakeDurable) guard(revision, epoch int64) error {
	r := f.snap.Run
	if r.DesiredState != "LIVE" || r.Status != "LIVE" || r.StopRevision > 0 {
		return fmt.Errorf("RUN_STOPPED")
	}
	if epoch != r.RunEpoch {
		return fmt.Errorf("STALE_RUN_EPOCH")
	}
	if revision != r.Revision {
		return fmt.Errorf("STATE_CONFLICT")
	}
	return nil
}
func (f *fakeDurable) SaveContentPlan(_ context.Context, q c.SaveContentPlanRequest) (c.SaveContentPlanResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("SaveContentPlan", q)
	if f.snap.Run.Status != "CREATED" && f.snap.Run.Status != "PAUSED" {
		return c.SaveContentPlanResponse{}, fmt.Errorf("STATE_CONFLICT")
	}
	if f.snap.Slot.ActiveAttemptId != nil || q.ExpectedRevision != f.snap.Run.Revision {
		return c.SaveContentPlanResponse{}, fmt.Errorf("STATE_CONFLICT")
	}
	f.snap.Bundle = ptr(clone(q.Bundle))
	f.snap.Run.CurrentPlanId = ptr(q.Bundle.Plan.PlanId)
	f.snap.Run.Revision++
	f.snap.CompletedPrefix = 0
	f.snap.ResumeSequence = 1
	f.currentVersion = q.Bundle.Plan.ProductSnapshotVersion
	return c.SaveContentPlanResponse{RequestId: q.RequestId, PlanId: q.Bundle.Plan.PlanId, RunRevision: f.snap.Run.Revision}, nil
}
func sourceKey(src c.CommentSource) string {
	return src.Platform + "/" + src.PlatformRoomId + "/" + src.SourceEventId
}
func (f *fakeDurable) AdmitTurn(_ context.Context, q c.AdmitTurnRequest) (c.AdmitTurnResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("AdmitTurn", q)
	if t, ok := f.turns[q.Turn.TurnId]; ok {
		return c.AdmitTurnResponse{RequestId: q.RequestId, Turn: clone(t), RunRevision: f.snap.Run.Revision}, nil
	}
	for _, src := range q.Turn.SourceIdentities {
		if id := f.sources[sourceKey(src)]; id != "" {
			return c.AdmitTurnResponse{RequestId: q.RequestId, Turn: clone(f.turns[id]), RunRevision: f.snap.Run.Revision}, nil
		}
	}
	if e := f.guard(q.ExpectedRevision, f.snap.Run.RunEpoch); e != nil {
		return c.AdmitTurnResponse{}, e
	}
	if !scopeTurn(q.Turn, f.snap.Run) || q.Turn.PlanId == nil || *q.Turn.PlanId != *f.snap.Run.CurrentPlanId {
		return c.AdmitTurnResponse{}, fmt.Errorf("PLAN_CHANGED")
	}
	f.turns[q.Turn.TurnId] = clone(q.Turn)
	for _, src := range q.Turn.SourceIdentities {
		f.sources[sourceKey(src)] = q.Turn.TurnId
	}
	f.snap.Run.Revision++
	return c.AdmitTurnResponse{RequestId: q.RequestId, Turn: clone(q.Turn), RunRevision: f.snap.Run.Revision}, nil
}
func (f *fakeDurable) ClaimNextTurn(_ context.Context, q c.ClaimNextTurnRequest) (c.ClaimNextTurnResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("ClaimNextTurn", q)
	if e := f.guard(q.ExpectedRevision, q.RunEpoch); e != nil {
		return c.ClaimNextTurnResponse{}, e
	}
	if f.snap.Slot.ActiveAttemptId != nil || q.ExpectedSlotVersion != f.snap.Slot.SlotVersion || len(f.snap.UnresolvedAttempts) > 0 {
		return c.ClaimNextTurnResponse{}, fmt.Errorf("STATE_CONFLICT: slot")
	}
	t, ok := f.turns[q.CandidateTurnId]
	if !ok || (t.State != "READY" && t.State != "WAITING") {
		return c.ClaimNextTurnResponse{}, fmt.Errorf("STATE_CONFLICT: turn")
	}
	if t.ExpiresAt != nil {
		x, _ := timestamp(*t.ExpiresAt)
		if !f.now.Before(x) {
			return c.ClaimNextTurnResponse{}, fmt.Errorf("STATE_CONFLICT: expired")
		}
	}
	if t.PlanId == nil || *t.PlanId != *f.snap.Run.CurrentPlanId || f.currentVersion != f.snap.Bundle.Plan.ProductSnapshotVersion {
		return c.ClaimNextTurnResponse{}, fmt.Errorf("PLAN_CHANGED")
	}
	f.claimCount++
	suffix := fmt.Sprint(f.claimCount)
	now := contentplan.Stamp(f.now)
	attempt := c.ExecutionAttempt{TenantId: t.TenantId, OwnerId: t.OwnerId, RunId: t.RunId, AttemptId: "attempt_" + suffix, TurnId: t.TurnId, SegmentId: t.SourceSegmentId, SessionId: *f.snap.Run.CurrentSessionId, UtteranceId: "utterance_" + suffix, CommandId: "command_" + suffix, RunEpoch: q.RunEpoch, AttemptNumber: 1, LastCheckpoint: "PLANNED", RequiredSinks: []string{"cpu_sink"}, CreatedAt: now, UpdatedAt: now}
	deps := []c.FactDependency{}
	mode := "COMMENT_QUESTION"
	if t.TurnType == "SCRIPT" {
		mode = "SCRIPT_TEXT"
		found := false
		for i := range f.snap.Bundle.Segments {
			s := &f.snap.Bundle.Segments[i]
			if s.SegmentId == *t.SourceSegmentId {
				if s.State != "READY" || s.Sequence != f.snap.ResumeSequence {
					return c.ClaimNextTurnResponse{}, fmt.Errorf("STATE_CONFLICT: segment")
				}
				s.State = "ACTIVE"
				s.UtteranceId = &attempt.UtteranceId
				deps = clone(s.FactDependencies)
				found = true
			}
		}
		if !found {
			return c.ClaimNextTurnResponse{}, fmt.Errorf("segment missing")
		}
	}
	for i := range deps {
		deps[i].ValidatedAt = now
		deps[i].ExpiresAt = contentplan.Stamp(f.now.Add(2 * time.Second))
	}
	payload := c.ExecutePayload{Mode: mode, Text: t.InputText, TextHash: contentplan.Hash(t.InputText), ProductId: &f.snap.Bundle.Plan.ProductId, PlanId: t.PlanId, SegmentId: t.SourceSegmentId, FactDependencies: deps, ExpiresAt: contentplan.Stamp(f.now.Add(20 * time.Second)), RequiredSinks: []string{"cpu_sink"}}
	if t.ExpiresAt != nil {
		payload.ExpiresAt = *t.ExpiresAt
	}
	cmd := c.RuntimeCommand{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, TenantId: t.TenantId, OwnerId: t.OwnerId, RunId: t.RunId, SessionId: attempt.SessionId, CommandId: attempt.CommandId, IntentId: "intent_" + suffix, AttemptId: attempt.AttemptId, TurnId: t.TurnId, UtteranceId: attempt.UtteranceId, RunEpoch: q.RunEpoch, LeaseVersion: 1, IdempotencyKey: t.IdempotencyKey, TraceId: "trace_" + suffix, CreatedAt: now, Operation: "EXECUTE_TURN", Payload: payload}
	raw, _ := contentplan.Canonical(cmd)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "requestHash")
	cmd.RequestHash, _ = contentplan.Version(m)
	intent := c.DispatchIntent{TenantId: t.TenantId, OwnerId: t.OwnerId, RunId: t.RunId, IntentId: cmd.IntentId, CommandId: cmd.CommandId, AttemptId: &attempt.AttemptId, TurnId: &t.TurnId, SessionId: &cmd.SessionId, UtteranceId: &cmd.UtteranceId, RunEpoch: q.RunEpoch, IdempotencyKey: t.IdempotencyKey, Operation: "EXECUTE_TURN", RequestHash: cmd.RequestHash, Status: "PENDING", NextAttemptAt: now, CreatedAt: now, UpdatedAt: now}
	t.State = "DISPATCHING"
	t.Revision++
	f.turns[t.TurnId] = t
	f.snap.Run.Revision++
	f.snap.Slot.ActiveAttemptId = &attempt.AttemptId
	f.snap.Slot.SlotVersion++
	f.snap.UnresolvedAttempts = []c.ExecutionAttempt{attempt}
	f.commands[cmd.CommandId] = cmd
	f.intents[intent.IntentId] = intent
	res := c.ClaimNextTurnResponse{RequestId: q.RequestId, RunRevision: f.snap.Run.Revision, Turn: t, Attempt: attempt, Intent: intent, Slot: f.snap.Slot}
	f.claims[t.TurnId] = res
	return clone(res), nil
}
func (f *fakeDurable) DispatchTurn(_ context.Context, q c.DispatchTurnRequest) (c.DispatchTurnResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("DispatchTurn", q)
	if e := f.guard(q.ExpectedRevision, q.RunEpoch); e != nil {
		return c.DispatchTurnResponse{}, e
	}
	v, ok := f.intents[q.IntentId]
	if !ok || v.CommandId != q.CommandId {
		return c.DispatchTurnResponse{}, fmt.Errorf("COMMAND_CONFLICT")
	}
	if v.Status == "PENDING" {
		f.wakeCount++
		v.Status = "ACCEPTED"
		f.intents[v.IntentId] = v
		f.emissions = append(f.emissions, f.commands[v.CommandId].TurnId)
	}
	if f.dispatchErr {
		return c.DispatchTurnResponse{}, fmt.Errorf("lost202")
	}
	return c.DispatchTurnResponse{RequestId: q.RequestId, Intent: v}, nil
}
func (f *fakeDurable) YieldAtSegmentBoundary(_ context.Context, q c.YieldAtSegmentBoundaryRequest) (c.YieldAtSegmentBoundaryResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("YieldAtSegmentBoundary", q)
	if e := f.guard(q.ExpectedRevision, q.RunEpoch); e != nil {
		return c.YieldAtSegmentBoundaryResponse{}, e
	}
	if f.snap.Slot.ActiveAttemptId != nil {
		return c.YieldAtSegmentBoundaryResponse{State: "WAITING", Slot: f.snap.Slot}, nil
	}
	if f.snap.Slot.BoundaryCheckpointId == nil || *f.snap.Slot.BoundaryCheckpointId != q.BoundaryCheckpointId {
		return c.YieldAtSegmentBoundaryResponse{}, fmt.Errorf("BOUNDARY_CONFLICT")
	}
	f.snap.Run.Revision++
	f.snap.Slot.BoundaryCheckpointId = nil
	f.snap.Slot.SlotVersion++
	return c.YieldAtSegmentBoundaryResponse{RequestId: q.RequestId, State: "YIELDED", BoundaryCheckpointId: q.BoundaryCheckpointId, Slot: clone(f.snap.Slot), RunRevision: f.snap.Run.Revision}, nil
}
func fullDrain(e c.Evidence, required []string) bool {
	for _, sink := range required {
		ok := false
		for _, p := range e.SinkProofs {
			if p.SinkId == sink && p.Terminal && p.FinalAudioSampleExclusive > p.FirstAudioSample && p.FinalVideoFrame >= 0 && p.AudioConsumedThroughExclusive >= p.FinalAudioSampleExclusive && p.VideoConsumedThroughFrame >= p.FinalVideoFrame {
				ok = true
			}
		}
		if !ok {
			return false
		}
	}
	return len(required) > 0
}
func (f *fakeDurable) ConfirmCheckpoint(_ context.Context, q c.ConfirmCheckpointRequest) (c.ConfirmCheckpointResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("ConfirmCheckpoint", q)
	cp := q.Checkpoint
	hash, _ := contentplan.Version(cp)
	if cp.RunEpoch != f.snap.Run.RunEpoch {
		return c.ConfirmCheckpointResponse{}, fmt.Errorf("STALE_RUN_EPOCH")
	}
	if old, ok := f.checkpoints[cp.EventId]; ok {
		if old != hash {
			return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
		}
		return c.ConfirmCheckpointResponse{RequestId: q.RequestId, CheckpointId: cp.CheckpointId, RunRevision: f.snap.Run.Revision, CompletedPrefix: f.snap.CompletedPrefix, Disposition: "DUPLICATE"}, nil
	}
	if len(f.snap.UnresolvedAttempts) != 1 {
		return c.ConfirmCheckpointResponse{}, fmt.Errorf("STATE_CONFLICT")
	}
	a := f.snap.UnresolvedAttempts[0]
	if a.AttemptId != cp.AttemptId || a.UtteranceId != cp.UtteranceId || a.CommandId != cp.CommandId || a.SessionId != cp.SessionId {
		return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
	}
	t := f.turns[a.TurnId]
	switch cp.State {
	case "PLAYING":
		if cp.Evidence.EvidenceType != "SINK_ADMITTED" {
			return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
		}
		t.State = "PLAYING"
		t.StartedAt = ptr(contentplan.Stamp(f.now))
	case "LOCAL_MEDIA_DRAINED":
		if cp.Evidence.EvidenceType != "ALL_REQUIRED_DRAIN" || !fullDrain(cp.Evidence, a.RequiredSinks) {
			return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
		}
		f.drained[a.AttemptId] = true
	case "COMPLETED":
		if cp.Evidence.EvidenceType != "BUSINESS_COMMIT" || !f.drained[a.AttemptId] || !fullDrain(cp.Evidence, a.RequiredSinks) {
			return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
		}
		t.State = "COMPLETED"
		t.FinishedAt = ptr(contentplan.Stamp(f.now))
		f.snap.Slot.ActiveAttemptId = nil
		f.snap.Slot.BoundaryCheckpointId = &cp.CheckpointId
	case "INTERRUPTED":
		if cp.Evidence.EvidenceType != "FENCE_BARRIER" {
			return c.ConfirmCheckpointResponse{}, fmt.Errorf("EVIDENCE_CONFLICT")
		}
		t.State = "INTERRUPTED"
		t.FinishedAt = ptr(contentplan.Stamp(f.now))
		f.snap.Slot.ActiveAttemptId = nil
		f.snap.Slot.BoundaryCheckpointId = &cp.CheckpointId
	case "UNKNOWN":
		t.State = "UNKNOWN"
	default:
		return c.ConfirmCheckpointResponse{}, fmt.Errorf("INVALID_ARGUMENT")
	}
	f.checkpoints[cp.EventId] = hash
	f.turns[t.TurnId] = t
	a.LastCheckpoint = cp.State
	for i := range f.snap.Bundle.Segments {
		seg := &f.snap.Bundle.Segments[i]
		if a.SegmentId != nil && seg.SegmentId == *a.SegmentId {
			seg.CheckpointState = cp.State
			switch cp.State {
			case "COMPLETED", "INTERRUPTED", "UNKNOWN":
				seg.State = cp.State
			}
		}
	}
	if cp.State == "COMPLETED" || cp.State == "INTERRUPTED" {
		f.snap.UnresolvedAttempts = []c.ExecutionAttempt{}
	} else {
		f.snap.UnresolvedAttempts = []c.ExecutionAttempt{a}
	}
	prefix := int64(0)
	for _, s := range f.snap.Bundle.Segments {
		if s.State != "COMPLETED" {
			break
		}
		prefix++
	}
	f.snap.CompletedPrefix = prefix
	f.snap.ResumeSequence = prefix + 1
	f.snap.Run.Revision++
	f.snap.Slot.SlotVersion++
	return c.ConfirmCheckpointResponse{RequestId: q.RequestId, CheckpointId: cp.CheckpointId, Applied: true, RunRevision: f.snap.Run.Revision, CompletedPrefix: prefix, Disposition: "APPLIED"}, nil
}
func (f *fakeDurable) QueryExecutionStatus(context.Context, c.QueryExecutionStatusRequest) (c.QueryExecutionStatusResponse, error) {
	return c.QueryExecutionStatusResponse{}, fmt.Errorf("RECOVERY_UNKNOWN")
}
func (f *fakeDurable) MarkExecutionUnknown(context.Context, c.MarkExecutionUnknownRequest) (c.MarkExecutionUnknownResponse, error) {
	return c.MarkExecutionUnknownResponse{}, fmt.Errorf("coordinator owns reconciliation")
}
func (f *fakeDurable) ResumeBroadcastRun(_ context.Context, q c.ResumeBroadcastRunRequest) (c.ResumeBroadcastRunResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("ResumeBroadcastRun", q)
	if f.snap.Run.StopRevision > 0 || f.snap.Run.DesiredState == "STOPPED" {
		return c.ResumeBroadcastRunResponse{}, fmt.Errorf("RUN_STOPPED")
	}
	if f.snap.Run.Status != "PAUSED" || len(f.snap.UnresolvedAttempts) > 0 {
		return c.ResumeBroadcastRunResponse{}, fmt.Errorf("RECOVERY_UNKNOWN")
	}
	f.snap.Run.Status = "RECOVERING"
	f.snap.Run.DesiredState = "LIVE"
	f.snap.Run.RunEpoch++
	f.snap.Run.Revision++
	return c.ResumeBroadcastRunResponse{RequestId: q.RequestId, Run: f.snap.Run}, nil
}
func (f *fakeDurable) StopBroadcastRun(_ context.Context, q c.StopBroadcastRunRequest) (c.StopBroadcastRunResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.record("StopBroadcastRun", q)
	if f.snap.Run.StopRevision == 0 {
		f.snap.Run.StopRevision = 1
		f.snap.Run.Revision++
	}
	f.snap.Run.Status = "STOPPING"
	f.snap.Run.DesiredState = "STOPPED"
	return c.StopBroadcastRunResponse{RequestId: q.RequestId, Run: f.snap.Run, StopRevision: f.snap.Run.StopRevision}, nil
}
func (f *fakeDurable) checkpoint(state string) c.ConfirmCheckpointRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	a := f.snap.UnresolvedAttempts[0]
	kind := map[string]string{"PLAYING": "SINK_ADMITTED", "LOCAL_MEDIA_DRAINED": "ALL_REQUIRED_DRAIN", "COMPLETED": "BUSINESS_COMMIT", "INTERRUPTED": "FENCE_BARRIER", "UNKNOWN": "KNOWLEDGE_GAP"}[state]
	cp := c.PlaybackCheckpoint{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, TenantId: "tenant", OwnerId: "owner", RunId: "run", CheckpointId: a.AttemptId + "_" + state, EventId: a.AttemptId + "_" + state, AttemptId: a.AttemptId, SessionId: a.SessionId, UtteranceId: a.UtteranceId, CommandId: a.CommandId, RunEpoch: a.RunEpoch, ProducerIncarnation: "cpu_producer", ProducerSeq: 1, State: state, OccurredAt: contentplan.Stamp(f.now), Evidence: c.Evidence{EvidenceType: kind, EvidenceRef: "cpu_evidence", EvidenceHash: contentplan.Hash(a.AttemptId + state), RequiredSinks: a.RequiredSinks, AudienceVisibility: "UNVERIFIED", PredecessorCheckpointIds: []string{}, SinkProofs: []c.SinkProof{}}}
	if state == "PLAYING" || state == "LOCAL_MEDIA_DRAINED" || state == "COMPLETED" {
		cp.Evidence.SinkProofs = []c.SinkProof{{SinkId: "cpu_sink", Kind: "RTMP_PIPE_WRITE", GenerationId: 1, FirstAudioSample: 0, FinalAudioSampleExclusive: 16000, AudioConsumedThroughExclusive: 16000, FinalVideoFrame: 24, VideoConsumedThroughFrame: 24, Terminal: true}}
	}
	if state == "LOCAL_MEDIA_DRAINED" {
		cp.ProducerSeq = 2
		cp.Evidence.PredecessorCheckpointIds = []string{a.AttemptId + "_PLAYING"}
	}
	if state == "COMPLETED" {
		cp.ProducerSeq = 3
		cp.Evidence.PredecessorCheckpointIds = []string{a.AttemptId + "_LOCAL_MEDIA_DRAINED"}
	}
	if state == "UNKNOWN" {
		cp.LastKnownState = ptr("PLAYING")
		cp.ReasonCode = ptr("CRASH")
	}
	return c.ConfirmCheckpointRequest{SchemaVersion: c.SchemaVersion, ContractRevision: c.RevisionName, RequestId: "req_cpu", TenantId: "tenant", OwnerId: "owner", RunId: "run", ExpectedRevision: nil, Checkpoint: cp}
}
func (f *fakeDurable) play(t *testing.T, m *Manager, d time.Duration) c.ConfirmCheckpointRequest {
	t.Helper()
	ctx := context.Background()
	if _, e := m.Confirm(ctx, f.checkpoint("PLAYING")); e != nil {
		t.Fatal(e)
	}
	f.advance(d)
	if _, e := m.Confirm(ctx, f.checkpoint("LOCAL_MEDIA_DRAINED")); e != nil {
		t.Fatal(e)
	}
	q := f.checkpoint("COMPLETED")
	q.ExpectedRevision = ptr(f.snap.Run.Revision)
	if _, e := m.Confirm(ctx, q); e != nil {
		t.Fatal(e)
	}
	return q
}
