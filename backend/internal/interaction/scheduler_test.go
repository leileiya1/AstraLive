package interaction

import (
	"astralive/backend/internal/platform"
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"
)

type fakeDispatch struct {
	mu    sync.Mutex
	items []Selection
	fail  bool
}

func (d *fakeDispatch) Dispatch(ctx context.Context, s Selection) (string, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.items = append(d.items, s)
	if d.fail {
		return "", errors.New("fake runtime rejected")
	}
	return "utt", nil
}
func fixture(t *testing.T) (*Scheduler, *time.Time, *fakeDispatch, *Gate) {
	t.Helper()
	now := time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC)
	d := &fakeDispatch{}
	gate := &Gate{Running: true, ProductID: "p"}
	s, err := New(DefaultConfig(), platform.Mapping{Platform: "mock", PlatformRoomID: "external", RoomID: "room", SessionID: "session"}, "p", d, func(context.Context) (Gate, error) { return *gate, nil }, func() time.Time { return now }, nil)
	if err != nil {
		t.Fatal(err)
	}
	return s, &now, d, gate
}
func event(id, user, text string) platform.Event {
	return platform.Event{Platform: "mock", PlatformRoomID: "external", InternalRoomID: "room", SessionID: "session", EventType: platform.Comment, SourceEventID: id, UserExternalID: user, Content: text, Transport: "MOCK_REPLAY"}
}
func receive(t *testing.T, s *Scheduler, e platform.Event) {
	t.Helper()
	if err := s.Receive(context.Background(), e); err != nil {
		t.Fatal(err)
	}
}
func TestDedupMergeAndStockSeparation(t *testing.T) {
	s, _, _, _ := fixture(t)
	receive(t, s, event("1", "a", "有 XL 吗？"))
	receive(t, s, event("1", "a", "有 XL 吗？"))
	receive(t, s, event("2", "b", "主播 XL 码有吗？"))
	receive(t, s, event("3", "c", "XL 有库存吗？"))
	receive(t, s, event("4", "d", "商品有库存吗？"))
	receive(t, s, event("5", "a", "有 XL 吗？"))
	v := s.Snapshot()
	if v.Candidates != 3 || v.Counters.Deduplicated != 2 || v.Counters.Merged != 1 {
		t.Fatal(v)
	}
}
func TestDirectedRequestSelectedButAmbientStatementFiltered(t *testing.T) {
	s, _, d, _ := fixture(t)
	receive(t, s, event("request", "a", "帮我想一句直播开场白。"))
	receive(t, s, event("ambient", "b", "今天天气晴朗。"))
	if v := s.Snapshot(); v.Candidates != 1 || v.Counters.Filtered != 1 {
		t.Fatal(v)
	}
	if err := s.Tick(context.Background()); err != nil || len(d.items) != 1 || d.items[0].Event.Content != "帮我想一句直播开场白。" {
		t.Fatal(err, d.items)
	}
}
func TestTTLRateCapacityAndStop(t *testing.T) {
	s, now, _, _ := fixture(t)
	s.config.Capacity = 3
	for i := 0; i < 100; i++ {
		receive(t, s, event(fmt.Sprint(i), fmt.Sprint(i), fmt.Sprintf("问题%d是什么？", i)))
	}
	if v := s.Snapshot(); v.Candidates != 3 || v.Counters.Dropped != 97 {
		t.Fatal(v)
	}
	*now = now.Add(21 * time.Second)
	if v := s.Snapshot(); v.Candidates != 0 || v.Counters.Expired != 3 {
		t.Fatal(v)
	}
	s.Stop()
	receive(t, s, event("after", "a", "你好"))
	if v := s.Snapshot(); v.Candidates != 0 || !v.Stopped {
		t.Fatal(v)
	}
}
func TestUserLimitAndGlobalLimit(t *testing.T) {
	s, _, _, _ := fixture(t)
	for i := 0; i < 5; i++ {
		receive(t, s, event(fmt.Sprint(i), "a", fmt.Sprintf("问题%d？", i)))
	}
	if s.Snapshot().Counters.Dropped != 2 {
		t.Fatal(s.Snapshot())
	}
	s.config.GlobalLimit = 4
	receive(t, s, event("b", "b", "你好"))
	receive(t, s, event("c", "c", "你好"))
	if s.Snapshot().Counters.Dropped != 3 {
		t.Fatal(s.Snapshot())
	}
}
func TestPriorityFairnessOperatorProductSwitchAndBoundary(t *testing.T) {
	s, now, d, g := fixture(t)
	receive(t, s, event("1", "a", "你好"))
	receive(t, s, event("2", "b", "多少钱？"))
	g.Busy = true
	_ = s.Tick(context.Background())
	if len(d.items) != 0 {
		t.Fatal("busy dispatched")
	}
	g.Busy = false
	_ = s.Tick(context.Background())
	if d.items[0].Topic != "price" || d.items[0].Policy != "NONE" {
		t.Fatal(d.items)
	}
	_ = s.SetMode(OperatorOverride)
	*now = now.Add(3 * time.Second)
	_ = s.Tick(context.Background())
	if len(d.items) != 1 {
		t.Fatal("operator override ignored")
	}
	_ = s.SetMode(ProductExplaining)
	_ = s.Tick(context.Background())
	if len(d.items) != 2 || s.Snapshot().Mode != CommentInteraction {
		t.Fatal(s.Snapshot())
	}
	receive(t, s, event("3", "c", "XL 有吗？"))
	g.ProductID = "new"
	*now = now.Add(3 * time.Second)
	_ = s.Tick(context.Background())
	if s.Snapshot().Candidates != 0 || s.Snapshot().Mode != OperatorOverride {
		t.Fatal(s.Snapshot())
	}
}
func TestFairness(t *testing.T) {
	s, now, d, _ := fixture(t)
	receive(t, s, event("1", "a", "多少钱？"))
	_ = s.Tick(context.Background())
	*now = now.Add(3 * time.Second)
	receive(t, s, event("2", "a", "商品库存？"))
	receive(t, s, event("3", "b", "你好"))
	_ = s.Tick(context.Background())
	if d.items[1].Event.UserExternalID != "b" {
		t.Fatal("fairness", d.items)
	}
}
func TestFailureNoRetryAndSessionIsolation(t *testing.T) {
	s, now, d, g := fixture(t)
	d.fail = true
	receive(t, s, event("1", "a", "你好"))
	if s.Tick(context.Background()) == nil {
		t.Fatal("failure missing")
	}
	*now = now.Add(3 * time.Second)
	_ = s.Tick(context.Background())
	if len(d.items) != 1 || s.Snapshot().Counters.Failed != 1 {
		t.Fatal(s.Snapshot())
	}
	e := event("x", "b", "你好")
	e.SessionID = "other"
	if s.Receive(context.Background(), e) == nil {
		t.Fatal("cross session")
	}
	g.Running = false
	_ = s.Tick(context.Background())
	if !s.Snapshot().Stopped {
		t.Fatal("stop")
	}
}
func TestConcurrentDeliveryDedup(t *testing.T) {
	s, _, d, _ := fixture(t)
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = s.Receive(context.Background(), event("same", "a", "多少钱？"))
			_ = s.Tick(context.Background())
		}()
	}
	wg.Wait()
	if len(d.items) != 1 {
		t.Fatal(len(d.items))
	}
}

func TestOptInControlledPreemption(t *testing.T) {
	s, _, d, g := fixture(t)
	s.config.AllowPriorityPreemption = true
	_ = s.SetMode(ProductExplaining)
	g.Busy = true
	g.CurrentSource = "OPERATOR"
	g.CurrentPriority = 20
	for i := 0; i < 3; i++ {
		receive(t, s, event(fmt.Sprint(i), fmt.Sprint(i), "多少钱？"))
	}
	_ = s.Tick(context.Background())
	if len(d.items) != 0 {
		t.Fatal("preempted operator")
	}
	g.CurrentSource = "AUTO_SCRIPT"
	_ = s.Tick(context.Background())
	if len(d.items) != 1 || d.items[0].Policy != "INTERRUPT_LOWER_PRIORITY" || s.Snapshot().Mode != OperatorOverride {
		t.Fatal(d.items, s.Snapshot())
	}
	if s.Snapshot().Counters.Force != 0 {
		t.Fatal("auto force")
	}
}
func TestTwoRoomsShareLimiterWithoutEventMix(t *testing.T) {
	now := time.Now()
	limit := &Limiter{}
	cfg := DefaultConfig()
	cfg.GlobalLimit = 1
	makeRoom := func(id string) *Scheduler {
		s, err := New(cfg, platform.Mapping{Platform: "mock", PlatformRoomID: id, RoomID: id, SessionID: id}, "p", &fakeDispatch{}, func(context.Context) (Gate, error) { return Gate{Running: true, ProductID: "p"}, nil }, func() time.Time { return now }, limit)
		if err != nil {
			t.Fatal(err)
		}
		return s
	}
	a, b := makeRoom("a"), makeRoom("b")
	e := event("same", "u", "你好")
	e.PlatformRoomID = "a"
	e.InternalRoomID = "a"
	e.SessionID = "a"
	receive(t, a, e)
	e.PlatformRoomID = "b"
	e.InternalRoomID = "b"
	e.SessionID = "b"
	receive(t, b, e)
	if a.Snapshot().Candidates != 1 || b.Snapshot().Candidates != 0 || b.Snapshot().Counters.Dropped != 1 {
		t.Fatal(a.Snapshot(), b.Snapshot())
	}
}

func TestObservationUsesLocalClockAndDispatchAcknowledgement(t *testing.T) {
	s, now, _, _ := fixture(t)
	receive(t, s, event("clock", "viewer", "价格多少？"))
	*now = now.Add(250 * time.Millisecond)
	if err := s.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	*now = now.Add(time.Second)
	v := s.Snapshot()
	if v.Observation == nil || v.Observation.ClockDomain != "go_monotonic" || v.Observation.ReceiveToSelectedMS != 250 || v.Observation.ReceiveToDispatchAckMS != 250 || v.Observation.ReceiptAgeMS != 1250 {
		t.Fatalf("invalid local observation: %+v", v.Observation)
	}
}

func TestDurableSourceCapPreservesLegacyMergeCounters(t *testing.T) {
	for _, durable := range []bool{false, true} {
		t.Run(fmt.Sprint(durable), func(t *testing.T) {
			s, _, _, _ := fixture(t)
			s.config.GlobalLimit = 1000
			s.config.PreserveSources = durable
			for i := 0; i < 160; i++ {
				receive(t, s, event(fmt.Sprint(i), fmt.Sprint(i), "有 XL 码吗？"))
			}
			snapshot := s.Snapshot()
			if len(s.queue) != 1 || len(s.queue[0].selection.Members) != 128 {
				t.Fatal("source memory must stay bounded", snapshot)
			}
			merged, dropped := 159, 0
			if durable {
				merged, dropped = 127, 32
			}
			if snapshot.Counters.Merged != merged || snapshot.Counters.Dropped != dropped {
				t.Fatal("mode changed merge admission", durable, snapshot)
			}
		})
	}
}
