//go:build !linux && !darwin

package main

func resourceSampler() func() map[string]any {
	return func() map[string]any {
		return map[string]any{"status": "self resource sampling unavailable on this platform"}
	}
}
