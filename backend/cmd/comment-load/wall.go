package main

import (
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	mockplatform "astralive/backend/internal/platform/mock"
	"context"
	"runtime"
	"sync/atomic"
	"time"
)

type wallDispatch struct{ busy atomic.Int64 }

func (d *wallDispatch) Dispatch(_ context.Context, s interaction.Selection) (string, error) {
	d.busy.Store(time.Now().Add(2 * time.Second).UnixNano())
	return s.Event.SourceEventID, nil
}
func runWall(name string, rate, count int) result {
	runtime.GC()
	var before, mem runtime.MemStats
	runtime.ReadMemStats(&before)
	start := time.Now()
	cpuStart := cpuSeconds()
	d := &wallDispatch{}
	cfg := interaction.DefaultConfig()
	mapping := platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}
	s, _ := interaction.New(cfg, mapping, "p", d, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, Busy: time.Now().UnixNano() < d.busy.Load(), ProductID: "p"}, nil
	}, time.Now, nil)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	peak := before.HeapAlloc
	go func() {
		defer close(done)
		tick := time.NewTicker(100 * time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				_ = s.Tick(ctx)
				runtime.ReadMemStats(&mem)
				if mem.HeapAlloc > peak {
					peak = mem.HeapAlloc
				}
			}
		}
	}()
	adapter := &mockplatform.Adapter{Mapping: mapping, Records: loadRecords(rate, count)}
	_ = adapter.Start(ctx, s)
	time.Sleep(250 * time.Millisecond)
	cancel()
	<-done
	s.Stop()
	runtime.ReadMemStats(&mem)
	if mem.HeapAlloc > peak {
		peak = mem.HeapAlloc
	}
	v := s.Snapshot()
	return result{Name: name, Clock: "real wall-clock Replay; fake speech busy 2s; Stop drops pending candidates", Counters: v.Counters, Latency: v.Latency, PeakHeapBytes: peak, HeapGrowthBytes: int64(mem.HeapAlloc) - int64(before.HeapAlloc), WallMS: float64(time.Since(start).Microseconds()) / 1000, VirtualSeconds: time.Since(start).Seconds(), CPUSeconds: cpuSeconds() - cpuStart, RandomArrival: randomArrival, Seed: arrivalSeed}
}
