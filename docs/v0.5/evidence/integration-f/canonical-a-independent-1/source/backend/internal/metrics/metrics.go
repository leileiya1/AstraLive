package metrics

import "github.com/prometheus/client_golang/prometheus"

var (
	HTTPRequests         = prometheus.NewCounterVec(prometheus.CounterOpts{Name: "http_requests_total", Help: "Control API requests."}, []string{"method", "route", "status"})
	HTTPDuration         = prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "http_request_duration_ms", Help: "Control API request duration in milliseconds.", Buckets: prometheus.ExponentialBuckets(1, 2, 12)}, []string{"method", "route"})
	RuntimeRequests      = prometheus.NewCounterVec(prometheus.CounterOpts{Name: "runtime_requests_total", Help: "Runtime command requests."}, []string{"operation"})
	RuntimeDuration      = prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "runtime_request_duration_ms", Help: "Runtime command duration in milliseconds.", Buckets: prometheus.ExponentialBuckets(1, 2, 12)}, []string{"operation"})
	RuntimeErrors        = prometheus.NewCounterVec(prometheus.CounterOpts{Name: "runtime_errors_total", Help: "Runtime command errors."}, []string{"operation"})
	RedisEventLag        = prometheus.NewGauge(prometheus.GaugeOpts{Name: "redis_event_lag", Help: "Runtime event processing lag in seconds."})
	SSEConnections       = prometheus.NewGauge(prometheus.GaugeOpts{Name: "sse_connections", Help: "Active SSE connections."})
	LiveSessionCount     = prometheus.NewGauge(prometheus.GaugeOpts{Name: "live_session_count", Help: "Sessions created by this backend process."})
	UtteranceCount       = prometheus.NewCounter(prometheus.CounterOpts{Name: "utterance_count", Help: "Utterances created."})
	UtteranceFailedCount = prometheus.NewCounter(prometheus.CounterOpts{Name: "utterance_failed_count", Help: "Utterances failed."})
)

func init() {
	prometheus.MustRegister(HTTPRequests, HTTPDuration, RuntimeRequests, RuntimeDuration, RuntimeErrors, RedisEventLag, SSEConnections, LiveSessionCount, UtteranceCount, UtteranceFailedCount)
}
