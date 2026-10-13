package interaction

import "github.com/prometheus/client_golang/prometheus"

var (
	outcomes       = prometheus.NewCounterVec(prometheus.CounterOpts{Name: "interaction_events_total", Help: "Scheduler outcomes; bounded outcome enum only, no room/user/content labels."}, []string{"outcome"})
	selectionDelay = prometheus.NewHistogram(prometheus.HistogramOpts{Name: "interaction_selection_delay_seconds", Help: "Go process comment receive to select; not full reply latency.", Buckets: []float64{.1, .5, 1, 2, 3, 5, 10, 20, 30}})
)

func init() { prometheus.MustRegister(outcomes, selectionDelay) }
