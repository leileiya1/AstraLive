package eventbus

import (
	"astralive/backend/internal/app"
	"context"
	"log/slog"
	"time"
)

// RunPostgres polls persisted Inbox work; no Redis or NOTIFY delivery dependency.
func RunPostgres(ctx context.Context, s *app.Service, log *slog.Logger) {
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
		for n := 0; n < 64; n++ {
			worked, e := s.ApplyNextDurable(ctx)
			if e != nil {
				log.Warn("event projection pending", "reason", "DEPENDENCY_UNAVAILABLE")
				break
			}
			if !worked {
				break
			}
		}
	}
}
