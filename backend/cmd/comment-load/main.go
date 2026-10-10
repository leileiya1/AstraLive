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
	"math/rand"
	"os"
	"runtime"
	"syscall"
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
	CPUSeconds      float64              `json:"processCPUSeconds"`
	RandomArrival   bool                 `json:"randomArrival"`
	Seed            int64                `json:"seed"`
}

var randomArrival bool
var arrivalSeed int64

func cpuSeconds() float64 {
	var usage syscall.Rusage
	if syscall.Getrusage(syscall.RUSAGE_SELF, &usage) != nil {
		return 0
	}
	return float64(usage.Utime.Sec+usage.Stime.Sec) + float64(usage.Utime.Usec+usage.Stime.Usec)/1e6
}

func loadRecords(rate, count int) []mockplatform.Record {
	rows := mockplatform.Scenario(rate, count)
	if randomArrival && rate > 0 {
		rng := rand.New(rand.NewSource(arrivalSeed + int64(rate)))
		for i := range rows {
			rows[i].AfterMS = int(rng.ExpFloat64() * 1000 / float64(rate))
		}
	}
	return rows
}

func run(name string, rate, count int, mixed bool) result {
	runtime.GC()
	var before, mem runtime.MemStats
	runtime.ReadMemStats(&before)
	peak := before.HeapAlloc
	start := time.Now()
	cpuStart := cpuSeconds()
	now := time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC)
	origin := now
	d := &dispatcher{now: &now}
	s, _ := interaction.New(interaction.DefaultConfig(), platform.Mapping{Platform: "mock", PlatformRoomID: "r", RoomID: "r", SessionID: "s"}, "p", d, func(context.Context) (interaction.Gate, error) {
		return interaction.Gate{Running: true, Busy: now.Before(d.busyUntil), ProductID: "p"}, nil
	}, func() time.Time { return now }, nil)
	rows := loadRecords(rate, count)
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
	return result{Name: name, Clock: "virtual arrivals; fake speech busy 2s", Counters: v.Counters, Latency: v.Latency, PeakHeapBytes: peak, HeapGrowthBytes: int64(mem.HeapAlloc) - int64(before.HeapAlloc), WallMS: float64(time.Since(start).Microseconds()) / 1000, VirtualSeconds: now.Sub(origin).Seconds(), CPUSeconds: cpuSeconds() - cpuStart, RandomArrival: randomArrival, Seed: arrivalSeed}
}
func main() {
	wall := flag.Bool("wall", false, "real-clock 10-second 1/5/20 Replay scenarios")
	flag.BoolVar(&randomArrival, "random", false, "seeded exponential interarrival times instead of fixed cadence")
	flag.Int64Var(&arrivalSeed, "seed", 20261010, "random arrival seed")
	wSeconds := flag.Int("wall-seconds", 10, "expected wall arrival duration (1..50 seconds; at most 1000 events)")
	flag.Parse()
	if *wSeconds < 1 || *wSeconds > 50 {
		fmt.Fprintln(os.Stderr, "wall-seconds must be 1..50")
		os.Exit(2)
	}
	rows := []result{run("1_per_second", 1, 100, false), run("5_per_second", 5, 100, false), run("20_per_second", 20, 100, false), run("burst_100", 0, 100, false), run("mixed_1000", 20, 1000, true)}
	if *wall {
		rows = []result{runWall("wall_1_per_second", 1, *wSeconds), runWall("wall_5_per_second", 5, 5**wSeconds), runWall("wall_20_per_second", 20, 20**wSeconds), runWall("wall_burst_100", 0, 100)}
	}
	e := json.NewEncoder(os.Stdout)
	e.SetIndent("", "  ")
	_ = e.Encode(rows)
}
