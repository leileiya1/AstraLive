package mock

import (
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

type sink struct{ events []platform.Event }

func (s *sink) Receive(ctx context.Context, e platform.Event) error {
	s.events = append(s.events, e)
	return nil
}
func TestReplayReconnectDuplicateAndStop(t *testing.T) {
	rows, err := Load(strings.NewReader(`[{"afterMs":0,"sourceEventId":"1","user":"a","content":"你好"},{"afterMs":0,"disconnect":true},{"afterMs":0,"sourceEventId":"1","user":"a","content":"你好","transport":"MOCK_BACKUP"}]`))
	if err != nil {
		t.Fatal(err)
	}
	a := &Adapter{Mapping: platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, Records: rows, Wait: func(ctx context.Context, d time.Duration) error { return ctx.Err() }}
	s := &sink{}
	if err = a.Start(context.Background(), s); err != nil {
		t.Fatal(err)
	}
	if len(s.events) != 2 || a.Health().Reconnects != 1 || a.Health().State != "STOPPED" {
		t.Fatal(a.Health())
	}
	a.Stop()
	if a.Start(context.Background(), s) != context.Canceled {
		t.Fatal("stop before start")
	}
}
func TestCancelAndLimits(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	a := &Adapter{Mapping: platform.Mapping{Platform: "mock"}, Records: Scenario(1, 10)}
	if a.Start(ctx, &sink{}) != context.Canceled {
		t.Fatal("cancel")
	}
	a = &Adapter{Mapping: platform.Mapping{Platform: "douyin"}}
	if a.Start(context.Background(), &sink{}) == nil {
		t.Fatal("real label accepted")
	}
	a = &Adapter{Mapping: platform.Mapping{Platform: "mock"}, Records: Scenario(20, 1001)}
	if a.Start(context.Background(), &sink{}) == nil {
		t.Fatal("count limit")
	}
	if _, err := Load(strings.NewReader(`[{"afterMs":-1}]`)); err == nil {
		t.Fatal("negative delay")
	}
}

func TestReplayFixtureThroughScheduler(t *testing.T) {
	f, err := os.Open("testdata/reconnect-duplicates.json")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	rows, err := Load(f)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	s, err := interaction.New(interaction.DefaultConfig(), platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, "p", noopDispatcher{}, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, Busy: true, ProductID: "p"}, nil
	}, func() time.Time { return now }, nil)
	if err != nil {
		t.Fatal(err)
	}
	a := &Adapter{Mapping: platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, Records: rows, Wait: func(ctx context.Context, d time.Duration) error { now = now.Add(d); return ctx.Err() }}
	if err = a.Start(context.Background(), s); err != nil {
		t.Fatal(err)
	}
	v := s.Snapshot()
	if v.Counters.Input != 8 || v.Counters.Deduplicated != 2 || v.Counters.Merged != 1 || v.Counters.Delivered != 0 || v.Candidates != 5 || a.Health().Heartbeats != 1 {
		t.Fatal(v, a.Health())
	}
}

type noopDispatcher struct{}

func (noopDispatcher) Dispatch(context.Context, interaction.Selection) (string, error) {
	return "fake", nil
}
