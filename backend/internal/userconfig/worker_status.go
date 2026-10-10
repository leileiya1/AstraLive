package userconfig

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/go-chi/chi/v5"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
)

// WorkerEndpoint is operator supplied. It is never accepted in a user profile.
type WorkerEndpoint struct {
	ManagementPort int     `json:"managementPort"`
	TokenFile      string  `json:"tokenFile"`
	AllowedScopes  []Scope `json:"allowedScopes"`
}

var workerEpochPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)
var workerCachePattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func validWorkerStatus(s WorkerStatus) bool {
	return s.ModelRevision == "9bc03de06bb0de82cd6bc477804512ae06144bf2" && workerEpochPattern.MatchString(s.WorkerEpoch) &&
		(s.AvatarCacheStatus.CacheID == "" || workerCachePattern.MatchString(s.AvatarCacheStatus.CacheID)) &&
		(s.AvatarCacheStatus.AvatarRef == "" || logicalID.MatchString(s.AvatarCacheStatus.AvatarRef)) &&
		(s.AvatarCacheStatus.Status == "" || s.AvatarCacheStatus.Status == "READY") &&
		(s.GenerationCancelStatus.Status == "NONE" || s.GenerationCancelStatus.Status == "PUBLICATION_FENCED") &&
		(s.Mode == "gpu" || s.Mode == "simulation") &&
		s.QueueDepth.AudioSamples >= 0 && s.QueueDepth.AudioSamples <= 32000 && s.QueueDepth.VideoFrames >= 0 && s.QueueDepth.VideoFrames <= 24 &&
		s.TrueGeneratedFPS >= 0 && s.ModelComputeFPS >= 0
}

type WorkerStatus struct {
	StatusVersion     string `json:"statusVersion"`
	WorkerRef         string `json:"workerRef"`
	Ready             bool   `json:"ready"`
	Health            string `json:"health"`
	ModelRevision     string `json:"modelRevision"`
	AvatarCacheStatus struct {
		CacheID              string `json:"cacheId"`
		AvatarRef            string `json:"avatarRef"`
		Status               string `json:"status"`
		MetadataRestored     bool   `json:"metadataRestored"`
		PreprocessingRebuilt bool   `json:"preprocessingRebuilt"`
	} `json:"avatarCacheStatus"`
	GPUAllocatedBytes        *uint64 `json:"gpuAllocatedBytes"`
	GPUReservedBytes         *uint64 `json:"gpuReservedBytes"`
	GPUUtilizationPercent    *int    `json:"gpuUtilizationPercent"`
	GPUTemperatureC          *int    `json:"gpuTemperatureC"`
	GPUDeviceMemoryUsedBytes *uint64 `json:"gpuDeviceMemoryUsedBytes"`
	TrueGeneratedFPS         float64 `json:"trueGeneratedFPS"`
	ModelComputeFPS          float64 `json:"modelComputeFPS"`
	GeneratedFrames          uint64  `json:"generatedFrames"`
	PublishedFrames          uint64  `json:"publishedFrames"`
	QueueDepth               struct {
		AudioSamples int `json:"audioSamples"`
		VideoFrames  int `json:"videoFrames"`
	} `json:"queueDepth"`
	LastError              *string `json:"lastError"`
	WorkerEpoch            string  `json:"workerEpoch"`
	GenerationCancelStatus struct {
		GenerationID *int64 `json:"generationId"`
		Status       string `json:"status"`
	} `json:"generationCancelStatus"`
	DiskFreeBytes      uint64 `json:"diskFreeBytes"`
	DiskTotalBytes     uint64 `json:"diskTotalBytes"`
	ActiveGenerationID *int64 `json:"activeGenerationId"`
	Mode               string `json:"mode"`
}

func loadWorkerRegistry(path string) (map[string]WorkerEndpoint, error) {
	if path == "" {
		return nil, nil
	}
	raw, e := os.ReadFile(path)
	if e != nil || len(raw) > 65536 {
		return nil, errors.New("worker registry unavailable")
	}
	var entries map[string]WorkerEndpoint
	if strictJSON(raw, &entries) != nil || len(entries) > 64 {
		return nil, errors.New("invalid worker registry")
	}
	for ref, entry := range entries {
		if !logicalID.MatchString(ref) || entry.ManagementPort < 1 || entry.ManagementPort > 65535 || entry.TokenFile == "" {
			return nil, errors.New("invalid worker registry")
		}
		if len(entry.AllowedScopes) == 0 || len(entry.AllowedScopes) > 128 {
			return nil, errors.New("worker registry requires scoped ownership")
		}
		for _, scope := range entry.AllowedScopes {
			if !validScope(scope) {
				return nil, errors.New("invalid worker registry scope")
			}
		}
	}
	return entries, nil
}

func (s *Service) probeWorker(ctx context.Context, ref string) (WorkerStatus, error) {
	status := WorkerStatus{StatusVersion: "1.0", WorkerRef: ref, Health: "UNKNOWN"}
	entry, ok := s.Workers[ref]
	if !ok {
		return status, fault(409, "PROVIDER_TEST_UNAVAILABLE", "worker not registered")
	}
	f, e := os.Open(entry.TokenFile)
	if e != nil {
		return status, fault(502, "PROVIDER_TEST_FAILED", "worker unavailable")
	}
	defer f.Close()
	info, e := f.Stat()
	if e != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 256 {
		return status, fault(502, "PROVIDER_TEST_FAILED", "worker unavailable")
	}
	raw, e := io.ReadAll(io.LimitReader(f, 257))
	token := strings.TrimSpace(string(raw))
	if e != nil || len(token) < 32 {
		return status, fault(502, "PROVIDER_TEST_FAILED", "worker unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", fmt.Sprintf("http://127.0.0.1:%d/v1/status", entry.ManagementPort), nil)
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }, Transport: &http.Transport{Proxy: nil}}
	defer client.CloseIdleConnections()
	response, e := client.Do(req)
	if e != nil {
		return status, fault(502, "PROVIDER_TEST_FAILED", "worker unavailable")
	}
	defer response.Body.Close()
	raw, e = io.ReadAll(io.LimitReader(response.Body, 65537))
	if e != nil || len(raw) > 65536 || response.StatusCode != 200 || json.Unmarshal(raw, &status) != nil || status.StatusVersion != "1.0" || subtle.ConstantTimeCompare([]byte(status.WorkerRef), []byte(ref)) != 1 || (status.Health != "UP" && status.Health != "DOWN") || !validWorkerStatus(status) {
		return WorkerStatus{}, fault(502, "PROVIDER_TEST_FAILED", "invalid worker status")
	}
	// Struct projection removes all arbitrary upstream metadata/credentials.
	if status.LastError != nil {
		switch *status.LastError {
		case "INFERENCE_STALLED", "INFERENCE_FAILED", "DISK_LOW":
		default:
			code := "WORKER_ERROR"
			status.LastError = &code
		}
	}
	return status, nil
}

func (s *Service) workerStatus(w http.ResponseWriter, r *http.Request) {
	profile, e := s.Get(r.Context(), scopeOf(r), chi.URLParam(r, "profileId"))
	if e != nil {
		write(w, r, 404, nil, e)
		return
	}
	if profile.Kind != "GPU_WORKER" || profile.Provider != "soulx" {
		write(w, r, 404, nil, ErrNotFound)
		return
	}
	var config providerConfig
	if strictJSON(profile.Config, &config) != nil {
		write(w, r, 422, nil, ErrInvalid)
		return
	}
	entry, registered := s.Workers[config.WorkerRef]
	if registered {
		allowed := false
		for _, scope := range entry.AllowedScopes {
			if scope == scopeOf(r) {
				allowed = true
				break
			}
		}
		if !allowed {
			write(w, r, 404, nil, ErrNotFound)
			return
		}
	}
	status, e := s.probeWorker(r.Context(), config.WorkerRef)
	write(w, r, 200, status, e)
}
