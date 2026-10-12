// Control-plane benchmark. No Speak generation or provider work is executed.
package main

import (
	"astralive/backend/internal/config"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"context"
	"encoding/json"
	"flag"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptrace"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type sample struct {
	TotalMS   float64 `json:"totalMs"`
	ConnectMS float64 `json:"connectMs"`
	Reused    bool    `json:"reused"`
	ServerMS  float64 `json:"serverMs"`
	Status    int     `json:"status"`
	Error     string  `json:"error,omitempty"`
}

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	base := flag.String("url", "http://127.0.0.1:28000", "Runtime base URL")
	token := flag.String("token-file", "", "private token file")
	size := flag.Int("size", 1024, "serialized JSON bytes (approximate)")
	concurrency := flag.Int("concurrency", 1, "workers")
	count := flag.Int("count", 200, "requests")
	cold := flag.Bool("cold", false, "close idle connections between requests; use concurrency=1")
	flag.Parse()
	h := runtime.New(*base)
	if os.Getenv("ASTRALIVE_BENCH_LOCAL") == "true" {
		options, e := config.LocalTransportFromEnv()
		if e != nil {
			panic(e)
		}
		h, e = runtime.NewLocal(*base, options)
		if e != nil {
			panic(e)
		}
	}
	baseTransport := h.Client.Transport
	if baseTransport == nil {
		baseTransport = &http.Transport{Proxy: nil}
	}
	h.Client.Transport = userconfig.TokenTransport{Path: *token, Base: timingTransport{baseTransport}}
	resources := resourceSampler()
	samples := make([]sample, *count)
	jobs := make(chan int)
	var wg sync.WaitGroup
	body := map[string]any{"commandId": "benchmark-command", "traceId": "benchmark-trace", "utteranceId": "benchmark-utterance", "priority": 50, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": map[string]string{"voiceId": "benchmark-voice"}, "text": ""}
	body["text"] = strings.Repeat("x", max(1, *size-len(mustJSON(body))))
	for w := 0; w < *concurrency; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				if *cold {
					if closer, ok := baseTransport.(interface{ CloseIdleConnections() }); ok {
						closer.CloseIdleConnections()
					}
				}
				s := sample{}
				var start time.Time
				ctxBase := context.WithValue(context.Background(), sampleKey{}, &s)
				trace := &httptrace.ClientTrace{ConnectStart: func(_, _ string) { start = time.Now() }, ConnectDone: func(_, _ string, e error) {
					if !start.IsZero() {
						s.ConnectMS = float64(time.Since(start).Nanoseconds()) / 1e6
					}
				}, GotConn: func(c httptrace.GotConnInfo) { s.Reused = c.Reused }}
				ctx := httptrace.WithClientTrace(ctxBase, trace)
				begin := time.Now()
				_, e := h.Speak(ctx, "benchmark-missing", body)
				s.TotalMS = float64(time.Since(begin).Nanoseconds()) / 1e6
				if e != nil {
					if er, ok := e.(*runtime.Error); ok {
						s.Status = er.Status
					} else if s.Status == 0 {
						s.Error = e.Error()
					}
				}
				samples[i] = s
			}
		}()
	}
	for i := 0; i < *count; i++ {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	if closer, ok := baseTransport.(interface{ CloseIdleConnections() }); ok {
		closer.CloseIdleConnections()
	}
	encoded, _ := json.Marshal(map[string]any{"samples": samples, "payloadBytes": len(mustJSON(body)), "pid": os.Getpid(), "resources": resources()})
	os.Stdout.Write(encoded)
}
func mustJSON(v any) []byte { b, _ := json.Marshal(v); return b }

type sampleKey struct{}
type timingTransport struct{ base http.RoundTripper }

func (t timingTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	resp, e := t.base.RoundTrip(r)
	if e == nil {
		if s, ok := r.Context().Value(sampleKey{}).(*sample); ok {
			s.Status = resp.StatusCode
			s.ServerMS, _ = strconv.ParseFloat(strings.TrimPrefix(resp.Header.Get("Server-Timing"), "app;dur="), 64)
		}
	}
	return resp, e
}
