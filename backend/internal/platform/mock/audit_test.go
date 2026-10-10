package mock

import (
	"astralive/backend/internal/platform"
	"context"
	"testing"
	"time"
)

type blockedDelivery struct{ entered, cancelled, release chan struct{} }

func (s *blockedDelivery) Receive(ctx context.Context, e platform.Event) error {
	close(s.entered)
	<-ctx.Done()
	close(s.cancelled)
	<-s.release
	return ctx.Err()
}

func TestAuditReplayStopWaitsForInFlightDelivery(t *testing.T) {
	s := &blockedDelivery{make(chan struct{}), make(chan struct{}), make(chan struct{})}
	a := &Adapter{Mapping: platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, Records: Scenario(0, 1)}
	started := make(chan error, 1)
	go func() { started <- a.Start(context.Background(), s) }()
	select {
	case <-s.entered:
	case <-time.After(time.Second):
		t.Fatal("delivery never started")
	}
	stopped := make(chan struct{})
	go func() { a.Stop(); close(stopped) }()
	<-s.cancelled
	select {
	case <-stopped:
		t.Error("Stop returned while an event delivery was still in flight")
	case <-time.After(50 * time.Millisecond):
	}
	close(s.release)
	if err := <-started; err != context.Canceled {
		t.Fatal(err)
	}
	select {
	case <-stopped:
	case <-time.After(time.Second):
		t.Fatal("Stop did not finish")
	}
}
