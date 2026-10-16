package turnmanager

import (
	"testing"
	"time"
)

func TestMetricsRetainSlowSamplesAndSeparatePopulations(t *testing.T) {
	m, e := NewMetrics(20)
	if e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 20; i++ {
		_ = m.Observe(FirstAVBusy, time.Duration(i+1)*time.Second)
	}
	_ = m.Observe(FirstAVIdle, time.Second)
	_ = m.Count("ingress", 100)
	_ = m.Count("selected", 20)
	_ = m.Count("expired", 30)
	s := m.Snapshot()
	if s.Timings[FirstAVBusy].P95MS != 19000 || s.Timings[FirstAVIdle].P95MS != 1000 || s.Counters["ingress"] != 100 || s.TotalObservations[FirstAVBusy] != 20 {
		t.Fatal(s)
	}
	if e = m.Observe(FirstAVBusy, -time.Second); e == nil {
		t.Fatal("negative clock")
	}
	_ = m.Observe(FirstAVBusy, 30*time.Second)
	s = m.Snapshot()
	if s.Timings[FirstAVBusy].MaxMS != 30000 || s.TotalObservations[FirstAVBusy] != 21 || s.Timings[FirstAVBusy].Samples != 20 {
		t.Fatal(s)
	}
}
