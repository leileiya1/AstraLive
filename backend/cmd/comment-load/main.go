// Reproducible offline scheduling load. Virtual arrival clock; real measured CPU/heap.
package main

import (
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	mockplatform "astralive/backend/internal/platform/mock"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"time"
)

type dispatcher struct {
	now       *time.Time
	busyUntil time.Time
}

func (d *dispatcher) Dispatch(_ context.Context, v interaction.Selection) (string, error) {
	d.busyUntil = d.now.Add(2 * time.Second)
	return fmt.Sprint(v.Event.SourceEventID), nil
}

type result struct {
	Name            string               `json:"name"`
	Clock           string               `json:"clock"`
	Counters        interaction.Counters `json:"counters"`
	Latency         interaction.Latency  `json:"selectionLatency"`
	PeakHeapBytes   uint64               `json:"sampledPeakHeapBytes"`
	HeapGrowthBytes int64                `json:"heapGrowthBytes"`
	WallMS          float64              `json:"wallMs"`
	VirtualSeconds  float64              `json:"arrivalDurationSeconds"`
}

func run(name string, rate, count int, mixed bool) result {
	runtime.GC()
	var before, mem runtime.MemStats
	runtime.ReadMemStats(&before)
	peak := before.HeapAlloc
	start := time.Now()
	now := time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC)
	origin := now
	d := &dispatcher{now: &now}
	s, _ := interaction.New(interaction.DefaultConfig(), platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, "p", d, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, Busy: now.Before(d.busyUntil), ProductID: "p"}, nil
	}, func() time.Time { return now }, nil)
	rows := mockplatform.Scenario(rate, count)
	for i, r := range rows {
		now = now.Add(time.Duration(r.AfterMS) * time.Millisecond)
		source := r.SourceEventID
		transport := "MOCK_REPLAY"
		text := r.Content
		if mixed && i%10 == 9 {
			source = rows[i-1].SourceEventID
			text = rows[i-1].Content
			transport = "MOCK_BACKUP"
		}
		if mixed && i%13 == 0 {
			text = fmt.Sprintf("第%d个咨询怎么操作？", i)
		}
		e := platform.Event{Platform: "mock", PlatformRoomID: "r", InternalRoomID: "r", SessionID: "s", EventType: platform.Comment, SourceEventID: source, UserExternalID: r.User, Content: text, Transport: transport}
		_ = s.Receive(context.Background(), e)
		_ = s.Tick(context.Background())
		runtime.ReadMemStats(&mem)
		if mem.HeapAlloc > peak {
			peak = mem.HeapAlloc
		}
	}
	for i := 0; i < 25; i++ {
		now = now.Add(time.Second)
		_ = s.Tick(context.Background())
		runtime.ReadMemStats(&mem)
		if mem.HeapAlloc > peak {
			peak = mem.HeapAlloc
		}
	}
	v := s.Snapshot()
	return result{name, "virtual arrivals; real CPU wall time; fake speech busy 2s", v.Counters, v.Latency, peak, int64(mem.HeapAlloc) - int64(before.HeapAlloc), float64(time.Since(start).Microseconds()) / 1000, now.Sub(origin).Seconds()}
}
func main() {
	wall := flag.Bool("wall", false, "real-clock 10-second 1/5/20 Replay scenarios")
	flag.Parse()
	rows := []result{run("1_per_second", 1, 100, false), run("5_per_second", 5, 100, false), run("20_per_second", 20, 100, false), run("burst_100", 0, 100, false), run("mixed_1000", 20, 1000, true)}
	if *wall {
		rows = []result{runWall("wall_1_per_second", 1, 10), runWall("wall_5_per_second", 5, 50), runWall("wall_20_per_second", 20, 200), runWall("wall_burst_100", 0, 100)}
	}
	e := json.NewEncoder(os.Stdout)
	e.SetIndent("", "  ")
	_ = e.Encode(rows)
}
