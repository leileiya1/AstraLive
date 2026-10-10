package interaction

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

func FromEnvironment() (Config, error) {
	c := DefaultConfig()
	if raw := os.Getenv("INTERACTION_ALLOW_PRIORITY_PREEMPTION"); raw != "" {
		v, err := strconv.ParseBool(raw)
		if err != nil {
			return c, fmt.Errorf("invalid preemption flag")
		}
		c.AllowPriorityPreemption = v
	}
	for key, ptr := range map[string]*time.Duration{"INTERACTION_TTL_MS": &c.TTL, "INTERACTION_MERGE_MS": &c.MergeWindow, "INTERACTION_INTERVAL_MS": &c.Interval, "INTERACTION_USER_WINDOW_MS": &c.UserWindow} {
		if raw := os.Getenv(key); raw != "" {
			n, err := strconv.Atoi(raw)
			if err != nil || n < 1 || n > 600000 {
				return c, fmt.Errorf("invalid %s", key)
			}
			*ptr = time.Duration(n) * time.Millisecond
		}
	}
	for key, ptr := range map[string]*int{"INTERACTION_CAPACITY": &c.Capacity, "INTERACTION_USER_LIMIT": &c.UserLimit, "INTERACTION_GLOBAL_LIMIT": &c.GlobalLimit, "INTERACTION_CACHE_CAPACITY": &c.CacheCapacity} {
		if raw := os.Getenv(key); raw != "" {
			n, err := strconv.Atoi(raw)
			if err != nil || n < 1 || n > 10000 {
				return c, fmt.Errorf("invalid %s", key)
			}
			*ptr = n
		}
	}
	return c, c.Validate()
}
