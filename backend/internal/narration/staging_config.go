package narration

import (
	"fmt"
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
