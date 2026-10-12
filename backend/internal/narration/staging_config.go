package narration

import (
	"astralive/backend/internal/durability"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"os"
	"regexp"
	"strings"
)

// StagingSettings is captured in BEGIN_RUN, never reread for each segment.
type StagingSettings struct {
	Enabled         bool
	LimitsRevision  *string
	ShortGateSHA256 *string
}

func (s StagingSettings) Validate() error {
	if !s.Enabled {
		if s.LimitsRevision != nil || s.ShortGateSHA256 != nil {
			return fmt.Errorf("disabled staging capture must be null")
		}
		return nil
	}
	if s.LimitsRevision == nil {
		return fmt.Errorf("staging profile required")
	}
	switch *s.LimitsRevision {
	case "staging-short-1":
		if s.ShortGateSHA256 != nil {
			return fmt.Errorf("short profile gate must be null")
		}
	case "staging-segment-8s-1":
		if s.ShortGateSHA256 == nil || !regexp.MustCompile(`^sha256:[0-9a-f]{64}$`).MatchString(*s.ShortGateSHA256) {
			return fmt.Errorf("8s staging requires reviewed short GPU gate SHA256")
		}
	default:
		return fmt.Errorf("invalid staging limits revision")
	}
	return nil
}
func (s StagingSettings) Capture() map[string]any {
	return map[string]any{"soulxStagingEnabled": s.Enabled, "soulxStagingLimitsRevision": s.LimitsRevision, "soulxStagingShortGateSHA256": s.ShortGateSHA256}
}
func StagingFromEnvironment() (StagingSettings, error) {
	v, present := os.LookupEnv("ASTRALIVE_SOULX_STAGING_ENABLED")
	enabled := false
	if present {
		switch strings.ToLower(v) {
		case "true", "1":
			enabled = true
		case "false", "0":
		default:
			return StagingSettings{}, fmt.Errorf("invalid ASTRALIVE_SOULX_STAGING_ENABLED")
		}
	}
	if !enabled {
		return StagingSettings{}, nil
	}
	profile := os.Getenv("ASTRALIVE_SOULX_STAGING_LIMITS_REVISION")
	if profile == "" {
		profile = "staging-short-1"
	}
	s := StagingSettings{Enabled: true, LimitsRevision: &profile}
	if gate := os.Getenv("ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256"); gate != "" {
		s.ShortGateSHA256 = &gate
	}
	return s, s.Validate()
}

// CapturedStaging validates these additions in immutable BEGIN_RUN featureFlags.
func CapturedStaging(flags map[string]json.RawMessage) (StagingSettings, error) {
	var s StagingSettings
	names := []string{"soulxStagingEnabled", "soulxStagingLimitsRevision", "soulxStagingShortGateSHA256"}
	present := 0
	for _, n := range names {
		if _, ok := flags[n]; ok {
			present++
		}
	}
	if present == 0 {
		return s, nil
	}
	if present != 3 || string(flags[names[0]]) == "null" || json.Unmarshal(flags[names[0]], &s.Enabled) != nil || json.Unmarshal(flags[names[1]], &s.LimitsRevision) != nil || json.Unmarshal(flags[names[2]], &s.ShortGateSHA256) != nil {
		return s, fmt.Errorf("invalid captured staging settings")
	}
	return s, s.Validate()
}

func (c *Controller) capturedStaging(ctx context.Context, tx pgx.Tx, r durability.Run) (StagingSettings, error) {
	var raw []byte
	err := tx.QueryRow(ctx, `SELECT payload_envelope->'payload'->'featureFlags' FROM v05_outbox WHERE session_id=$1 AND run_epoch=$2 AND command_type='BEGIN_RUN' ORDER BY command_seq LIMIT 1`, r.SessionID, r.Epoch).Scan(&raw)
	if errors.Is(err, pgx.ErrNoRows) && !c.StagingSettings.Enabled {
		return StagingSettings{}, nil
	}
	if err != nil {
		return StagingSettings{}, err
	}
	var flags map[string]json.RawMessage
	if json.Unmarshal(raw, &flags) != nil {
		return StagingSettings{}, fmt.Errorf("missing captured feature flags")
	}
	settings, err := CapturedStaging(flags)
	if err != nil {
		return settings, err
	}
	actual, _ := json.Marshal(settings.Capture())
	configured, _ := json.Marshal(c.StagingSettings.Capture())
	if !bytes.Equal(actual, configured) {
		return settings, fmt.Errorf("captured staging mode/profile mismatch")
	}
	return settings, nil
}
