package userconfig

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"time"
)

// Local probes reuse scoped profiles and the installed physical Worker contract.
// They never start a GPU, create a second registry or resolve browser credentials.
func (s *Service) testLocalProvider(ctx context.Context, scope Scope, p Profile) (Profile, error) {
	if !s.IntegrationEnabled || !((p.Kind == "TTS" && p.Provider == "xiaoya") || (p.Kind == "GPU_WORKER" || p.Kind == "AVATAR") && p.Provider == "soulx") {
		return Profile{}, fault(409, "PROVIDER_TEST_UNAVAILABLE", "provider has no real probe in this deployment")
	}
	e := s.transaction(ctx, scope, func(tx pgx.Tx) error {
		tag, e := tx.Exec(ctx, `INSERT INTO config_test_attempts(tenant_id,user_id,attempted_at) VALUES($1,$2,now()) ON CONFLICT(tenant_id,user_id) DO UPDATE SET attempted_at=now() WHERE config_test_attempts.attempted_at < now()-interval '5 seconds'`, scope.TenantID, scope.UserID)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return fault(429, "RATE_LIMITED", "wait five seconds before another probe")
		}
		return nil
	})
	if e != nil {
		return Profile{}, e
	}
	var cfg providerConfig
	if strictJSON(p.Config, &cfg) != nil {
		return Profile{}, ErrInvalid
	}
	var probeErr error
	switch p.Kind {
	case "TTS":
		probeErr = s.probeTTS(ctx, p)
	case "GPU_WORKER":
		entry, ok := s.Workers[cfg.WorkerRef]
		allowed := false
		for _, v := range entry.AllowedScopes {
			if v == scope {
				allowed = true
			}
		}
		if !ok || !allowed {
			return Profile{}, ErrNotFound
		}
		status, err := s.probeWorker(ctx, cfg.WorkerRef)
		if err != nil {
			probeErr = fault(503, "WORKER_UNAVAILABLE", "Worker connection unavailable")
		} else if !status.Ready || status.Health != "UP" || status.Mode != "gpu" || status.AvatarCacheStatus.Status != "READY" {
			probeErr = fault(503, "WORKER_NOT_READY", "real GPU Worker is not ready")
		}
	case "AVATAR":
		worker, err := s.Get(ctx, scope, cfg.WorkerProfileID)
		if err != nil {
			return Profile{}, err
		}
		if worker.Kind != "GPU_WORKER" || worker.Provider != "soulx" || !worker.Enabled {
			return Profile{}, fault(409, "PROVIDER_BINDING_INVALID", "select an enabled SoulX Worker profile")
		}
		probeErr = s.ValidateWorker(ctx, scope, Binding{Profiles: []Profile{p, worker}})
	}
	return s.saveProbeResult(ctx, scope, p, probeErr)
}

func (s *Service) probeTTS(ctx context.Context, p Profile) error {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	request, e := http.NewRequestWithContext(ctx, "POST", s.RuntimeStatusURL+"/internal/v0.4/provider-probes/tts", bytes.NewReader(p.Config))
	if e != nil {
		return fault(503, "PROVIDER_TEST_FAILED", "TTS probe unavailable")
	}
	request.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 20 * time.Second, Transport: TokenTransport{Path: s.RuntimeControlTokenFile, Base: &http.Transport{Proxy: nil}}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	response, e := client.Do(request)
	if e != nil {
		return fault(503, "PROVIDER_TEST_FAILED", "TTS probe unavailable")
	}
	defer response.Body.Close()
	raw, e := io.ReadAll(io.LimitReader(response.Body, 4097))
	var result struct {
		Real       bool   `json:"real"`
		Provider   string `json:"provider"`
		SampleRate int    `json:"sampleRate"`
		Samples    int    `json:"samples"`
	}
	if e != nil || len(raw) > 4096 || response.StatusCode != 200 || json.Unmarshal(raw, &result) != nil || !result.Real || result.Provider != "xiaoya" || result.SampleRate < 16000 || result.Samples < 1600 {
		return fault(502, "PROVIDER_TEST_FAILED", "real XiaoYa synthesis probe failed")
	}
	return nil
}

func (s *Service) saveProbeResult(ctx context.Context, scope Scope, p Profile, probeErr error) (Profile, error) {
	verification, code, health := "VERIFIED", "", "UP"
	if probeErr != nil {
		verification, code, health = "FAILED", publicError(probeErr).Code, "DOWN"
	}
	tag, e := s.DB.Exec(ctx, `UPDATE config_profiles SET verification=$5,error_code=$6,health=$7,health_at=now(),is_default=CASE WHEN $5='FAILED' THEN false ELSE is_default END,updated_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3 AND version=$4`, scope.TenantID, scope.UserID, p.ID, p.Version, verification, code, health)
	if e != nil {
		return Profile{}, e
	}
	if tag.RowsAffected() != 1 {
		return Profile{}, ErrConflict
	}
	if probeErr != nil {
		return Profile{}, probeErr
	}
	return s.Get(ctx, scope, p.ID)
}
