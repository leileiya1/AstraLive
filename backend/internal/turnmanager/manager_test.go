package turnmanager

import (
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

var background = context.Background()

func step(t *testing.T, m *Manager) Choice {
	t.Helper()
	v, e := m.Step(background)
	if e != nil {
		t.Fatal(e)
	}
	return v
}

type fixtureSources struct{ members []c.CommentSource }

func (src fixtureSources) SelectionSources(_ context.Context, s interaction.Selection) ([]c.CommentSource, error) {
	if len(src.members) > 0 {
		return src.members, nil
	}
	if s.Audience > 1 {
		return nil, fmt.Errorf("merged identities unavailable")
	}
	id := s.Event.SourceEventID
	if id == "" {
		id = s.Event.EventID
	}
	return []c.CommentSource{{Platform: s.Event.Platform, PlatformRoomId: s.Event.PlatformRoomID, SourceReceiptId: s.Event.EventID, SourceEventId: id, TraceId: s.Event.TraceID}}, nil
}
func (f *fakeDurable) offer(t *testing.T, m *Manager, id, text string) string {
	t.Helper()
	at := f.clock()
	a := SelectionAdapter{m, fixtureSources{}}
	v := interaction.Selection{Event: platform.Event{EventID: "receipt_" + id, SourceEventID: id, Platform: "mock", PlatformRoomID: "room", InternalRoomID: "room", SessionID: "session", UserExternalID: id, TraceID: "trace_" + id, Content: text, ReceivedAt: at}, Topic: "product", Audience: 1, Priority: 80, Policy: "NONE", ProductID: "product", SelectedAt: at}
	turn, e := a.Dispatch(background, v)
	if e != nil {
		t.Fatal(e)
	}
	return turn
}
func assertNext(t *testing.T, m *Manager, source string, seq int64) {
	t.Helper()
	v := step(t, m)
	if v.Source != source {
		t.Fatalf("want %s, got %+v", source, v)
	}
	if source == "SCRIPT" && (v.Segment == nil || v.Segment.Sequence != seq) {
		t.Fatal(v)
	}
}
func TestTenSegmentsWithoutComments(t *testing.T) {
	f := newFake(t, 10)
	m := f.manager(t)
	for i := int64(1); i <= 10; i++ {
		assertNext(t, m, "SCRIPT", i)
		if f.snap.CompletedPrefix != i-1 {
			t.Fatal("dispatch advanced cursor")
		}
		f.play(t, m, 3*time.Second)
	}
	if v := step(t, m); v.State != Idle {
		t.Fatal(v)
	}
	if f.snap.CompletedPrefix != 10 || f.claimCount != 10 || f.wakeCount != 10 {
		t.Fatal(f.snap)
	}
	seen := map[string]bool{}
	for _, id := range f.emissions {
		if seen[id] {
			t.Fatal("duplicate script")
		}
		seen[id] = true
	}
}
func TestNaturalCommentBoundaryAndResume(t *testing.T) {
	f := newFake(t, 10)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	f.advance(time.Second)
	comment := f.offer(t, m, "size-xl", "这款有XL尺码吗？")
	v := step(t, m)
	if v.State != YieldPending || f.claimCount != 1 {
		t.Fatal(v)
	}
	if _, e := m.Confirm(background, f.checkpoint("PLAYING")); e != nil {
		t.Fatal(e)
	}
	f.advance(2 * time.Second)
	// TTS completion / local drain alone is not a BUSINESS_COMMIT boundary.
	if _, e := m.Confirm(background, f.checkpoint("LOCAL_MEDIA_DRAINED")); e != nil {
		t.Fatal(e)
	}
	if v := step(t, m); v.State != YieldPending || f.claimCount != 1 || f.snap.CompletedPrefix != 0 {
		t.Fatal(v)
	}
	cp := f.checkpoint("COMPLETED")
	cp.ExpectedRevision = ptr(f.snap.Run.Revision)
	if _, e := m.Confirm(background, cp); e != nil {
		t.Fatal(e)
	}
	assertNext(t, m, "COMMENT", 0)
	if f.emissions[len(f.emissions)-1] != comment {
		t.Fatal("wrong comment")
	}
	// Delayed duplicate completion cannot release the newly owned COMMENT slot.
	before := *f.snap.Slot.ActiveAttemptId
	if _, e := m.Confirm(background, cp); e != nil {
		t.Fatal(e)
	}
	if *f.snap.Slot.ActiveAttemptId != before {
		t.Fatal("duplicate released slot")
	}
	f.play(t, m, 2*time.Second)
	v = step(t, m)
	if v.State != Resuming || v.Source != "SCRIPT" || v.Segment.Sequence != 2 {
		t.Fatal(v)
	}
}
func TestFairnessBudgetsAndRestart(t *testing.T) {
	f := newFake(t, 10)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	f.play(t, m, 3*time.Second)
	for i := 0; i < 4; i++ {
		f.offer(t, m, fmt.Sprint(i), fmt.Sprintf("问题%d是什么？", i))
	}
	for i := 0; i < 2; i++ {
		assertNext(t, m, "COMMENT", 0)
		f.play(t, m, 2*time.Second)
	}
	m = f.manager(t)
	v := step(t, m)
	if v.Source != "SCRIPT" || v.Segment.Sequence != 2 || v.ConsecutiveAnswers != 2 {
		t.Fatal(v)
	}
	f.play(t, m, 3*time.Second)
	assertNext(t, m, "COMMENT", 0)
}
func TestOccupancyAndMaxScriptWait(t *testing.T) {
	for _, tc := range []struct {
		name          string
		delay, answer time.Duration
	}{{"occupancy", 0, 8 * time.Second}, {"script-wait", 11 * time.Second, time.Second}} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFake(t, 3)
			m := f.manager(t)
			assertNext(t, m, "SCRIPT", 1)
			f.play(t, m, time.Second)
			f.offer(t, m, "a", "价格多少？")
			f.offer(t, m, "b", "有XL吗？")
			f.advance(tc.delay)
			assertNext(t, m, "COMMENT", 0)
			f.play(t, m, tc.answer)
			assertNext(t, m, "SCRIPT", 2)
		})
	}
}
func TestTTLNeverResetByWaitingOrRestart(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	f.offer(t, m, "old", "价格多少？")
	f.advance(20 * time.Second)
	f.play(t, m, time.Second)
	m = f.manager(t)
	assertNext(t, m, "SCRIPT", 2)
	if f.wakeCount != 2 {
		t.Fatal("expired comment emitted")
	}
}
func TestUnknownAndOldEpochFailClosed(t *testing.T) {
	f := newFake(t, 4)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	if _, e := m.Confirm(background, f.checkpoint("PLAYING")); e != nil {
		t.Fatal(e)
	}
	old := f.checkpoint("COMPLETED")
	if _, e := m.Confirm(background, f.checkpoint("UNKNOWN")); e != nil {
		t.Fatal(e)
	}
	m = f.manager(t)
	if v := step(t, m); v.State != Recovering || f.claimCount != 1 {
		t.Fatal(v)
	}
	f.snap.Run.RunEpoch = 2
	if _, e := m.Confirm(background, old); e == nil {
		t.Fatal("accepted old epoch")
	}
	if v := step(t, m); v.State != Recovering || f.snap.CompletedPrefix != 0 {
		t.Fatal(v)
	}
}
func TestUnknownWithoutSlotStillBlocksCursor(t *testing.T) {
	f := newFake(t, 3)
	f.snap.Bundle.Segments[0].State = "UNKNOWN"
	f.snap.Bundle.Segments[0].CheckpointState = "UNKNOWN"
	if v := step(t, f.manager(t)); v.State != Recovering || f.claimCount != 0 {
		t.Fatal(v)
	}
}
func TestStopDoesNotRestartAndLateEvidenceCannotResume(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	if _, e := m.Stop(background, "stop_decision"); e != nil {
		t.Fatal(e)
	}
	f.play(t, m, time.Second)
	if v := step(t, m); v.State != Stopped {
		t.Fatal(v)
	}
	m = f.manager(t)
	if v := step(t, m); v.State != Stopped {
		t.Fatal(v)
	}
	if _, e := m.Resume(background, "resume_after_stop"); e == nil {
		t.Fatal("resurrected stopped run")
	}
	if f.claimCount != 1 {
		t.Fatal(f.claimCount)
	}
}
func TestForceRequiresExplicitResumeAndFence(t *testing.T) {
	f := newFake(t, 4)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	m.Override()
	q := f.checkpoint("INTERRUPTED")
	q.Checkpoint.ReasonCode = ptr("OPERATOR_FORCE")
	if _, e := m.Confirm(background, q); e != nil {
		t.Fatal(e)
	}
	if v := step(t, m); v.State != OperatorOverride {
		t.Fatal(v)
	}
	if _, e := m.Resume(background, "explicit"); e == nil {
		t.Fatal("resume without durable pause")
	}
	f.override = true
	f.snap.Run.Status = "PAUSED"
	f.snap.Run.DesiredState = "PAUSED"
	if v := step(t, f.manager(t)); v.State != OperatorOverride {
		t.Fatal(v)
	}
	if _, e := m.Resume(background, "explicit"); e != nil {
		t.Fatal(e)
	}
	if v := step(t, m); v.State != OperatorOverride {
		t.Fatal(v)
	} // projection still overridden until coordinator clears it
	f.override = false
	f.snap.Run.Status = "LIVE"
	if v := step(t, m); v.State != Recovering {
		t.Fatal("interrupted segment replay", v)
	}
}
func TestProductSwitchDoesNotReuseOldFactsOrTurns(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	f.offer(t, m, "old-product", "XL有货吗？")
	f.currentVersion = "changed"
	if v := step(t, m); v.State != Recovering || f.claimCount != 0 {
		t.Fatal(v)
	}
	f.snap.Run.Status = "PAUSED"
	f.snap.Run.DesiredState = "PAUSED"
	b := clone(*f.snap.Bundle)
	b.Plan.PlanId = "new_plan"
	b.Plan.ProductId = "product_new"
	b.Plan.Snapshot.ProductId = "product_new"
	b.Plan.Snapshot.SourceVersion = "v2"
	b.Plan.ProductSnapshotVersion, _ = contentplan.Version(b.Plan.Snapshot)
	b.Plan.Revision = 2
	for i := range b.Segments {
		s := &b.Segments[i]
		s.PlanId = b.Plan.PlanId
		s.SegmentId = "new_" + s.SegmentId
		s.IdempotencyKey = "segment:" + s.SegmentId + ":initial"
		b.Plan.SegmentOrder[i] = s.SegmentId
	}
	if _, e := m.SavePlan(background, b); e != nil {
		t.Fatal(e)
	}
	f.snap.Run.Status = "LIVE"
	f.snap.Run.DesiredState = "LIVE"
	f.snap.Run.RunEpoch++
	assertNext(t, m, "SCRIPT", 1)
	if f.claimCount != 1 {
		t.Fatal("old comment emitted")
	}
}
func TestFailureStagesNeverCompleteSegment(t *testing.T) {
	for _, stage := range []string{"LLM_FAILED", "TTS_FAILED", "WORKER_DEGRADED"} {
		t.Run(stage, func(t *testing.T) {
			f := newFake(t, 3)
			m := f.manager(t)
			assertNext(t, m, "SCRIPT", 1)
			q := f.checkpoint("INTERRUPTED")
			q.Checkpoint.ReasonCode = ptr(stage)
			if _, e := m.Confirm(background, q); e != nil {
				t.Fatal(e)
			}
			if f.snap.CompletedPrefix != 0 || f.snap.Bundle.Segments[0].State != "INTERRUPTED" {
				t.Fatal(f.snap)
			}
			if v := step(t, m); v.State != Recovering || f.claimCount != 1 {
				t.Fatal(v)
			}
		})
	}
}
func TestCommentFailureCanResumeAfterProvenBarrier(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	f.play(t, m, time.Second)
	f.offer(t, m, "bad", "帮我介绍商品？")
	assertNext(t, m, "COMMENT", 0)
	q := f.checkpoint("INTERRUPTED")
	q.Checkpoint.ReasonCode = ptr("LLM_FAILED")
	if _, e := m.Confirm(background, q); e != nil {
		t.Fatal(e)
	}
	assertNext(t, m, "SCRIPT", 2)
}
func TestDegradedProviderAndLostAck(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	f.provider = false
	if v := step(t, m); v.State != Recovering || f.claimCount != 0 {
		t.Fatal(v)
	}
	f.provider = true
	f.dispatchErr = true
	if _, e := m.Step(background); e == nil {
		t.Fatal("missing lost ack")
	}
	m = f.manager(t)
	_ = step(t, m)
	if f.claimCount != 1 || f.wakeCount != 1 {
		t.Fatal("ambiguous replay")
	}
}
func TestDrainProofRequiredAndEvidenceConflict(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	q := f.checkpoint("COMPLETED")
	if _, e := m.Confirm(background, q); e == nil {
		t.Fatal("completed without drain")
	}
	q = f.checkpoint("LOCAL_MEDIA_DRAINED")
	q.Checkpoint.Evidence.SinkProofs[0].AudioConsumedThroughExclusive = 15999
	if _, e := m.Confirm(background, q); e == nil {
		t.Fatal("partial drain accepted")
	}
	q = f.play(t, m, time.Second)
	q.Checkpoint.Evidence.EvidenceHash = contentplan.Hash("conflict")
	if _, e := m.Confirm(background, q); e == nil {
		t.Fatal("same event different proof")
	}
}
func TestConcurrentManagersDoNotDoubleDispatch(t *testing.T) {
	f := newFake(t, 4)
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); m := f.manager(t); _, _ = m.Step(background) }()
	}
	wg.Wait()
	if f.claimCount != 1 || f.wakeCount > 1 || len(f.snap.UnresolvedAttempts) != 1 {
		t.Fatalf("claims=%d wakes=%d", f.claimCount, f.wakeCount)
	}
}
func TestDecideRejectsInconsistentProjectionAndScope(t *testing.T) {
	f := newFake(t, 3)
	p, _ := f.ReadPolicy(background, f.snap)
	p.HistoryComplete = false
	if v, _ := Decide(f.snap, p, DefaultConfig(), f.now); v.State != Recovering {
		t.Fatal(v)
	}
	p.HistoryComplete = true
	p.RunRevision++
	if v, _ := Decide(f.snap, p, DefaultConfig(), f.now); v.State != Recovering {
		t.Fatal(v)
	}
	f.snap.CompletedPrefix = 2
	if _, e := NextSegment(f.snap, p); e == nil {
		t.Fatal("bad prefix")
	}
}
func TestFactRefreshCannotChangeAssertion(t *testing.T) {
	f := newFake(t, 1)
	p := f.snap.Bundle.Plan
	a := c.FactDependency{Kind: "PRICE", ProductId: p.ProductId, SourceVersion: p.Snapshot.SourceVersion, ValueHash: contentplan.Hash("129.90"), ValidatedAt: contentplan.Stamp(f.now), ExpiresAt: contentplan.Stamp(f.now.Add(2 * time.Second))}
	b := a
	b.ValueHash = contentplan.Hash("199.90")
	if e := validateRefreshed(p, []c.FactDependency{a}, []c.FactDependency{b}, f.now); e == nil {
		t.Fatal("changed price")
	}
	if e := validateRefreshed(p, []c.FactDependency{a}, []c.FactDependency{a}, f.now.Add(2*time.Second)); e == nil {
		t.Fatal("stale fact")
	}
}
func TestSchedulerContinuousBurstUsesExistingAlgorithms(t *testing.T) {
	f := newFake(t, 10)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	adapter := &SelectionAdapter{m, fixtureSources{}}
	cfg := interaction.DefaultConfig()
	scheduler, e := interaction.New(cfg, platform.Mapping{Platform: "mock", PlatformRoomID: "room", RoomID: "room", SessionID: "session"}, "product", adapter, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, ProductID: "product"}, nil
	}, f.clock, nil)
	if e != nil {
		t.Fatal(e)
	}
	_ = scheduler.SetMode(interaction.ProductExplaining)
	// Gate here means candidate ADMISSION, not physical Avatar idleness. Agent 4
	// wires the explicit selection-only gate patch, and disables legacy dispatch.
	for second := 0; second < 5; second++ {
		for i := 0; i < 20; i++ {
			id := fmt.Sprintf("%d_%d", second, i)
			event := platform.Event{Platform: "mock", PlatformRoomID: "room", InternalRoomID: "room", SessionID: "session", EventType: platform.Comment, SourceEventID: id, UserExternalID: fmt.Sprint(i), Transport: "mock", Content: fmt.Sprintf("帮我介绍商品%s？", id)}
			if e = scheduler.Receive(background, event); e != nil {
				t.Fatal(e)
			}
			if e = scheduler.Receive(background, event); e != nil {
				t.Fatal(e)
			}
		}
		if e = scheduler.Tick(background); e != nil {
			t.Fatal(e)
		}
		f.advance(time.Second)
	}
	if v := step(t, m); v.State != YieldPending || f.claimCount != 1 {
		t.Fatal(v)
	}
	f.play(t, m, time.Second)
	for i := 0; i < 20; i++ {
		v := step(t, m)
		if v.Source == "" {
			break
		}
		f.play(t, m, time.Second)
	}
	stats := scheduler.Snapshot().Counters
	if stats.Input != 200 || stats.Deduplicated < 100 || stats.Force != 0 || f.snap.CompletedPrefix != 10 {
		t.Fatalf("scheduler=%+v prefix=%d", stats, f.snap.CompletedPrefix)
	}
	t.Logf("all receipts=%d duplicate=%d merged=%d selected=%d dropped=%d expired=%d script_completed=%d", stats.Input, stats.Deduplicated, stats.Merged, stats.Selected, stats.Dropped, stats.Expired, f.snap.CompletedPrefix)
}
func TestSegmentThreeMergedSizesAndRepeatedSelection(t *testing.T) {
	f := newFake(t, 5)
	m := f.manager(t)
	for i := int64(1); i <= 2; i++ {
		assertNext(t, m, "SCRIPT", i)
		f.play(t, m, time.Second)
	}
	assertNext(t, m, "SCRIPT", 3)
	sources := []c.CommentSource{{SourceReceiptId: "receipt_a", Platform: "mock", PlatformRoomId: "room", SourceEventId: "a", TraceId: "trace_a"}, {SourceReceiptId: "receipt_b", Platform: "mock", PlatformRoomId: "room", SourceEventId: "b", TraceId: "trace_b"}}
	adapter := SelectionAdapter{m, fixtureSources{sources}}
	selection := interaction.Selection{Event: platform.Event{Platform: "mock", PlatformRoomID: "room", InternalRoomID: "room", SessionID: "session", SourceEventID: "a", EventID: "receipt_a", TraceID: "trace_a", ReceivedAt: f.clock(), Content: "这款有XL吗？"}, Audience: 2, Priority: 80, Policy: "NONE", ProductID: "product", SelectedAt: f.clock()}
	a, e := adapter.Dispatch(background, selection)
	if e != nil {
		t.Fatal(e)
	}
	b, e := adapter.Dispatch(background, selection)
	if e != nil || a != b {
		t.Fatal("duplicate admission", e)
	}
	f.play(t, m, time.Second)
	assertNext(t, m, "COMMENT", 0)
	f.play(t, m, time.Second)
	assertNext(t, m, "SCRIPT", 4)
	if len(f.turns[a].SourceIdentities) != 2 {
		t.Fatal("lost merged source")
	}
}
func TestGapRequiresExplicitDurableDecision(t *testing.T) {
	f := newFake(t, 3)
	p, _ := f.ReadPolicy(background, f.snap)
	s := &f.snap.Bundle.Segments[0]
	s.State = "UNKNOWN"
	s.CheckpointState = "UNKNOWN"
	f.snap.ResumeSequence = 2
	p.GapDecisions = map[string]string{s.SegmentId: "operator_gap"}
	if _, e := NextSegment(f.snap, p); e == nil {
		t.Fatal("unapproved gap")
	}
	f.snap.Decisions = []c.Decision{{DecisionId: "operator_gap", OperatorId: "owner", Action: "SKIP_WITH_GAP", AttemptId: "sealed_attempt", Reason: "explicit skip", CreatedAt: contentplan.Stamp(f.now)}}
	seg, e := NextSegment(f.snap, p)
	if e != nil || seg.Sequence != 2 || f.snap.CompletedPrefix != 0 {
		t.Fatal(seg, e)
	}
}
func TestConfigRelationship(t *testing.T) {
	cfg := DefaultConfig()
	cfg.MaxScriptWait = cfg.CommentTTL
	if cfg.Validate() == nil {
		t.Fatal("unreachable budget")
	}
	cfg = DefaultConfig()
	cfg.MaxConsecutiveAnswers = 3
	if cfg.Validate() == nil {
		t.Fatal("contract maximum")
	}
}

// Optional artifact export contains CPU-only requests for independent JSON Schema
// validation. This is an evidence collection switch, not a production feature.
func TestExportContractRequests(t *testing.T) {
	dir := os.Getenv("ASTRALIVE_DIRECTOR_EVIDENCE")
	if dir == "" {
		t.Skip("set ASTRALIVE_DIRECTOR_EVIDENCE for schema/evidence export")
	}
	f := newFake(t, 3)
	m := f.manager(t)
	f.snap.Run.Status = "PAUSED"
	f.snap.Run.DesiredState = "PAUSED"
	if _, e := m.SavePlan(background, *f.snap.Bundle); e != nil {
		t.Fatal(e)
	}
	f.snap.Run.Status = "LIVE"
	f.snap.Run.DesiredState = "LIVE"
	assertNext(t, m, "SCRIPT", 1)
	f.offer(t, m, "c", "价格多少？")
	f.play(t, m, 3*time.Second)
	assertNext(t, m, "COMMENT", 0)
	f.play(t, m, 2*time.Second)
	assertNext(t, m, "SCRIPT", 2)
	f.play(t, m, 3*time.Second)
	if _, e := m.Stop(background, "stop"); e != nil {
		t.Fatal(e)
	}
	raw, e := json.MarshalIndent(f.events, "", "  ")
	if e != nil {
		t.Fatal(e)
	}
	if e = os.MkdirAll(dir, 0755); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(dir, "cpu-contract-requests.json"), raw, 0644); e != nil {
		t.Fatal(e)
	}
	raw, _ = json.MarshalIndent(f.commands, "", "  ")
	if e = os.WriteFile(filepath.Join(dir, "cpu-commands.json"), raw, 0644); e != nil {
		t.Fatal(e)
	}
}

func TestRealSchedulerMergesSizeQuestionsAtSegmentThree(t *testing.T) {
	f := newFake(t, 5)
	m := f.manager(t)
	for i := int64(1); i < 3; i++ {
		assertNext(t, m, "SCRIPT", i)
		f.play(t, m, time.Second)
	}
	assertNext(t, m, "SCRIPT", 3)
	mapping := platform.Mapping{Platform: "mock", PlatformRoomID: "room", RoomID: "room", SessionID: "session"}
	events := []platform.Event{}
	for i := 0; i < 3; i++ {
		events = append(events, platform.Event{Platform: "mock", PlatformRoomID: "room", InternalRoomID: "room", SessionID: "session", EventType: platform.Comment, SourceEventID: fmt.Sprint(i), UserExternalID: fmt.Sprint(i), Transport: "mock", Content: "这款有XL吗？"})
	}
	normalized := []platform.Event{}
	for _, e := range events {
		n, err := platform.Normalize(e, mapping, f.clock())
		if err != nil {
			t.Fatal(err)
		}
		normalized = append(normalized, n)
	}
	identities, e := SourcesFromEvents(normalized)
	if e != nil {
		t.Fatal(e)
	}
	adapter := &SelectionAdapter{m, fixtureSources{identities}}
	scheduler, e := interaction.New(interaction.DefaultConfig(), mapping, "product", adapter, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, ProductID: "product"}, nil
	}, f.clock, nil)
	if e != nil {
		t.Fatal(e)
	}
	for _, event := range events {
		if e = scheduler.Receive(background, event); e != nil {
			t.Fatal(e)
		}
	}
	if e = scheduler.Tick(background); e != nil {
		t.Fatal(e)
	}
	stats := scheduler.Snapshot()
	if stats.Counters.Merged != 2 || stats.Counters.Selected != 1 || stats.Current.Audience != 3 {
		t.Fatal(stats)
	}
	if v := step(t, m); v.State != YieldPending || f.claimCount != 3 {
		t.Fatal(v)
	}
	f.play(t, m, time.Second)
	assertNext(t, m, "COMMENT", 0)
	f.play(t, m, time.Second)
	assertNext(t, m, "SCRIPT", 4)
	if len(f.turns[stats.UtteranceID].SourceIdentities) != 3 {
		t.Fatal("merged source lost")
	}
}
func TestIdentityBridgeAndNonForceAdmission(t *testing.T) {
	if _, e := SourcesFromEvents([]platform.Event{{Platform: "mock"}}); e == nil {
		t.Fatal("invented receipt")
	}
	f := newFake(t, 2)
	m := f.manager(t)
	a := SelectionAdapter{m, fixtureSources{}}
	if _, e := a.Dispatch(background, interaction.Selection{Policy: "FORCE"}); e == nil {
		t.Fatal("automatic FORCE")
	}
}
func TestSustainedCommentsNeverStarveExplanation(t *testing.T) {
	f := newFake(t, 10)
	m := f.manager(t)
	consecutive := 0
	for i := 0; i < 40; i++ {
		f.offer(t, m, fmt.Sprint(i), fmt.Sprintf("商品问题%d？", i))
		v := step(t, m)
		if v.Source == "" {
			break
		}
		if v.Source == "COMMENT" {
			consecutive++
			if consecutive > 2 {
				t.Fatal("script starved")
			}
		} else {
			consecutive = 0
		}
		f.play(t, m, time.Second)
		if f.snap.CompletedPrefix == 10 {
			break
		}
	}
	if f.snap.CompletedPrefix != 10 {
		t.Fatal(f.snap.CompletedPrefix)
	}
}
func TestFractionalTimestampsPreserveFairnessOrder(t *testing.T) {
	f := newFake(t, 3)
	m := f.manager(t)
	assertNext(t, m, "SCRIPT", 1)
	f.play(t, m, time.Second)
	f.offer(t, m, "one", "价格多少？")
	assertNext(t, m, "COMMENT", 0)
	f.play(t, m, 100*time.Millisecond)
	f.offer(t, m, "two", "XL有吗？")
	assertNext(t, m, "COMMENT", 0)
	f.play(t, m, 100*time.Millisecond)
	f.offer(t, m, "three", "有货吗？")
	assertNext(t, m, "SCRIPT", 2)
}
