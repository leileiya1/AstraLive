package turnmanager

import (
	"astralive/backend/internal/interaction"
	"fmt"
	"sync"
	"time"
)

// Metrics accepts same-clock measured durations from integration observers. It
// never substitutes HTTP acceptance or PCM onset for associated Chrome A/V.
// Counts cover ALL inputs; latency samples are a bounded chronological tail.
// FirstAVIdle and FirstAVBusy must be supplied from the actual browser observer.
type Metric string

const (
	FirstAVIdle    Metric = "idle_comment_to_chrome_associated_av"
	FirstAVBusy    Metric = "busy_comment_to_chrome_associated_av"
	YieldWait      Metric = "selection_to_committed_boundary"
	ResumeWait     Metric = "answer_commit_to_next_script_playing"
	CheckpointWait Metric = "local_drain_to_business_commit"
	SilentGap      Metric = "local_speech_silence"
)

type Metrics struct {
	mu       sync.Mutex
	capacity int
	timings  map[Metric][]float64
	totals   map[Metric]int64
	counts   map[string]int64
}
type MetricsSnapshot struct {
	Counters          map[string]int64               `json:"counters"`
	Timings           map[Metric]interaction.Latency `json:"timings"`
	TotalObservations map[Metric]int64               `json:"totalObservations"`
	Capacity          int                            `json:"capacity"`
}

func NewMetrics(capacity int) (*Metrics, error) {
	if capacity < 20 || capacity > 10000 {
		return nil, fmt.Errorf("INVALID_ARGUMENT: metrics capacity")
	}
	return &Metrics{capacity: capacity, timings: map[Metric][]float64{}, totals: map[Metric]int64{}, counts: map[string]int64{}}, nil
}
func (m *Metrics) Observe(kind Metric, d time.Duration) error {
	switch kind {
	case FirstAVIdle, FirstAVBusy, YieldWait, ResumeWait, CheckpointWait, SilentGap:
	default:
		return fmt.Errorf("INVALID_ARGUMENT: timing")
	}
	if d < 0 {
		return fmt.Errorf("INVALID_ARGUMENT: negative or mixed clock duration")
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	v := m.timings[kind]
	if len(v) == m.capacity {
		copy(v, v[1:])
		v = v[:len(v)-1]
	}
	m.timings[kind] = append(v, float64(d.Microseconds())/1000)
	m.totals[kind]++
	return nil
}
func (m *Metrics) Count(name string, n int64) error {
	switch name {
	case "ingress", "selected", "expired", "dropped", "merged", "deduplicated", "segment_planned", "segment_completed", "resume_correct", "resume_attempted", "duplicate_explanation", "interruption", "comment_occupancy_ms", "script_occupancy_ms":
	default:
		return fmt.Errorf("INVALID_ARGUMENT: counter")
	}
	if n < 0 {
		return fmt.Errorf("INVALID_ARGUMENT: counter")
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.counts[name] += n
	return nil
}
func (m *Metrics) Snapshot() MetricsSnapshot {
	m.mu.Lock()
	defer m.mu.Unlock()
	r := MetricsSnapshot{Counters: map[string]int64{}, Timings: map[Metric]interaction.Latency{}, TotalObservations: map[Metric]int64{}, Capacity: m.capacity}
	for k, v := range m.counts {
		r.Counters[k] = v
	}
	for _, k := range []Metric{FirstAVIdle, FirstAVBusy, YieldWait, ResumeWait, CheckpointWait, SilentGap} {
		r.Timings[k] = interaction.Stats(m.timings[k], string(k))
		r.TotalObservations[k] = m.totals[k]
	}
	return r
}
