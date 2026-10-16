package durableintegration

import (
	"context"
	"errors"
	"sync/atomic"
	"time"

	contract "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/durablelive"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"astralive/backend/internal/turnmanager"
	"golang.org/x/sync/errgroup"
)

type cachedGate struct {
	gate interaction.Gate
	at   time.Time
}

// Controller composes the REAL existing comment Scheduler with the SQL-backed
// Manager. It does not create a physical Session or bypass the LIVE release gate.
// Trusted ingress must persist/map source identities before Scheduler.Receive.
type Controller struct {
	Manager   *turnmanager.Manager
	Scheduler *interaction.Scheduler
	adapter   *Adapter
	scope     turnmanager.Scope
	session   string
	gate      atomic.Pointer[cachedGate]
}

func NewController(ctx context.Context, store *durablelive.Store, p durablelive.Principal, runID, sessionID string, cfg interaction.Config) (*Controller, error) {
	if store == nil || p.Role != "CONTROL" || store.Facts == nil {
		return nil, errors.New("DEPENDENCY_UNAVAILABLE")
	}
	a := &Adapter{Store: store, Principal: p}
	scope := turnmanager.Scope{TenantID: p.TenantID, OwnerID: p.OwnerID, RunID: runID}
	tc := turnmanager.DefaultConfig()
	tc.CommentTTL = cfg.TTL
	m, err := turnmanager.New(a, a, Facts{Store: store, Principal: p, RunID: runID}, scope, tc, nil)
	if err != nil {
		return nil, err
	}
	controller := &Controller{Manager: m, adapter: a, scope: scope, session: sessionID}
	s, err := controller.restore(ctx)
	if err != nil {
		return nil, err
	}
	if s.Run.CurrentSessionId == nil || *s.Run.CurrentSessionId != sessionID || s.Bundle == nil {
		return nil, errors.New("FORBIDDEN")
	}
	selection := &turnmanager.SelectionAdapter{Manager: m, Sources: turnmanager.PreservedSources{}}
	// This callback runs under the Scheduler lock. It is strictly an atomic
	// read; all database work stays in Refresh, before Tick takes that lock.
	gate := func(context.Context) (interaction.Gate, error) {
		v := controller.gate.Load()
		if v == nil || time.Since(v.at) > 250*time.Millisecond {
			return interaction.Gate{}, errors.New("DEPENDENCY_UNAVAILABLE")
		}
		return v.gate, nil
	}
	controller.Scheduler, err = interaction.New(cfg, platform.Mapping{Platform: "mock", PlatformRoomID: s.Run.RoomId, RoomID: s.Run.RoomId, SessionID: sessionID}, s.Bundle.Plan.ProductId, selection, gate, nil, nil)
	if err != nil {
		return nil, err
	}
	if err = controller.Refresh(ctx); err != nil {
		return nil, err
	}
	return controller, nil
}

func (c *Controller) restore(ctx context.Context) (contractSnapshot contract.RestoreSnapshot, err error) {
	v, err := c.adapter.RestoreContentPlan(ctx, restoreRequest(c.scope))
	return v.Snapshot, err
}

func restoreRequest(scope turnmanager.Scope) contract.RestoreContentPlanRequest {
	return contract.RestoreContentPlanRequest{SchemaVersion: contract.SchemaVersion, ContractRevision: contract.RevisionName, RequestId: ids.New("req"), TenantId: scope.TenantID, OwnerId: scope.OwnerID, RunId: scope.RunID}
}

func (c *Controller) Refresh(ctx context.Context) error {
	s, err := c.restore(ctx)
	if err != nil {
		c.gate.Store(nil)
		return err
	}
	p, err := c.adapter.ReadPolicy(ctx, s)
	if err != nil {
		c.gate.Store(nil)
		return err
	}
	g := interaction.Gate{SelectionOnly: true, Running: s.Run.Status == "LIVE" && s.Run.DesiredState == "LIVE" && s.Run.StopRevision == 0 && p.ProviderReady && s.Run.CurrentSessionId != nil && *s.Run.CurrentSessionId == c.session}
	if s.Bundle != nil {
		g.ProductID = s.Bundle.Plan.ProductId
		g.Running = g.Running && p.ProductSnapshotVersion == s.Bundle.Plan.ProductSnapshotVersion
	}
	g.Busy = s.Slot.ActiveAttemptId != nil
	for _, t := range p.History {
		if t.State == "DISPATCHING" || t.State == "PLAYING" {
			g.CurrentSource = map[string]string{"SCRIPT": "AUTO_SCRIPT", "COMMENT": "PLATFORM_EVENT"}[t.TurnType]
			g.CurrentPriority = int(t.Priority)
		}
	}
	c.gate.Store(&cachedGate{gate: g, at: time.Now()})
	return nil
}

// Run's cancellation owns only these controller goroutines, never shared Worker
// processes. Runtime effects still go exclusively through durable Outbox/journal.
func (c *Controller) Run(ctx context.Context, onStep func(turnmanager.Choice, error)) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	defer c.Scheduler.Stop()
	group, ctx := errgroup.WithContext(ctx)
	group.Go(func() error { defer cancel(); return c.Manager.Run(ctx, nil, onStep) })
	group.Go(func() error {
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-ticker.C:
			}
			// A dependency failure clears the cache; it never authorizes an empty
			// projection. Refresh precedes Tick; no SQL is held under its mutex.
			if err := c.Refresh(ctx); err != nil {
				continue
			}
			_ = c.Scheduler.Tick(ctx)
		}
	})
	return group.Wait()
}
