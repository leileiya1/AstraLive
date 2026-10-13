//go:build linux || darwin

package main

import (
	"os"
	"runtime"
	"syscall"
	"time"
)

func resourceSampler() func() map[string]any {
	done := make(chan struct{})
	result := make(chan int)
	go func() {
		peak := 0
		tick := time.NewTicker(5 * time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-done:
				result <- peak
				return
			case <-tick.C:
				if runtime.GOOS == "linux" {
					if f, e := os.ReadDir("/proc/self/fd"); e == nil && len(f) > peak {
						peak = len(f)
					}
				}
			}
		}
	}()
	return func() map[string]any {
		close(done)
		fd := <-result
		var r syscall.Rusage
		syscall.Getrusage(syscall.RUSAGE_SELF, &r)
		rss := r.Maxrss
		if runtime.GOOS == "linux" {
			rss *= 1024
		}
		return map[string]any{"cpuSeconds": float64(r.Utime.Sec+r.Stime.Sec) + float64(r.Utime.Usec+r.Stime.Usec)/1e6, "maxRSSBytes": rss, "selfSampledFDPeak": fd}
	}
}
