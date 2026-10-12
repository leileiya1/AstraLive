package narration

import (
	"fmt"
	"os"
	"strings"
)

// TimelineEnabled matches Runtime's user-approved CCR-B-001 configuration.
// Explicit empty/invalid values and conflicting primary/alias values are errors.
func TimelineEnabled() (bool, error) {
	parse := func(name string) (bool, bool, error) {
		v, present := os.LookupEnv(name)
		if !present {
			return false, false, nil
		}
		switch strings.ToLower(v) {
		case "true", "1":
			return true, true, nil
		case "false", "0":
			return false, true, nil
		default:
			return false, true, fmt.Errorf("invalid %s", name)
		}
	}
	primary, hasPrimary, err := parse("ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED")
	if err != nil {
		return false, err
	}
	alias, hasAlias, err := parse("ASTRALIVE_MEDIA_TIMELINE_ENABLED")
	if err != nil {
		return false, err
	}
	if hasPrimary && hasAlias && primary != alias {
		return false, fmt.Errorf("conflicting MediaTimeline feature flags")
	}
	if hasPrimary {
		return primary, nil
	}
	return alias, nil
}
