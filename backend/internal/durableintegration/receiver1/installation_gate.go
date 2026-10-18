package receiver1

import (
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"sync"
)

// CoordinatedPhysicalSource is a trusted host-lifecycle repository capability,
// not a wire field, Runtime receipt, or an automatic wrapper around Observe.
// The owner MUST keep the exact installed tuple immutable until
// Registry.RetireInstallation has closed admission, drained SQL users and
// durably retired/revoked the old installation. Out-of-band replacement is not
// supported. A source that cannot enforce this MUST NOT implement this seam.
// Physical reads/IPC happen before a SQL transaction, never inside it.
type CoordinatedPhysicalSource interface {
	PhysicalSource
	InstallationGate(context.Context, wire.ReceiverBootstrapBinding, Identity, Identity) (*InstallationGate, error)
}

// InstallationGate belongs to one immutable native installation, not a Room's
// mutable current slot. Its owner retains this handle and closes it immediately
// on withdrawal. New revisions/Generations need a different installed identity;
// a closed gate cannot reopen. Creating a gate is not physical evidence.
type InstallationGate struct {
	snapshot wire.ReceiverPhysicalInstallation
	mu       sync.Mutex
	closed   bool
	readers  int
	drained  chan struct{}
}

func NewInstallationGate(snapshot wire.ReceiverPhysicalInstallation) (*InstallationGate, error) {
	if _, e := wire.Encode(&snapshot); e != nil || snapshot.State != "CLOSED_INSTALLED" {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	return &InstallationGate{snapshot: snapshot, drained: make(chan struct{})}, nil
}
func (g *InstallationGate) acquire(ctx context.Context) (func(), error) {
	if g == nil || ctx.Err() != nil {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	g.mu.Lock()
	if g.closed {
		g.mu.Unlock()
		return nil, fault("REGISTRATION_REVOKED")
	}
	g.readers++
	g.mu.Unlock()
	var once sync.Once
	return func() {
		once.Do(func() {
			g.mu.Lock()
			defer g.mu.Unlock()
			g.readers--
			if g.closed && g.readers == 0 {
				close(g.drained)
			}
		})
	}, nil
}
func (g *InstallationGate) valid() bool { g.mu.Lock(); defer g.mu.Unlock(); return !g.closed }

// CloseAdmission is nonblocking: Stop/withdrawal never waits for RPC or SQL.
// It does not authorize physical replacement. RetireInstallation must complete
// before changing the physical tuple; errors/timeouts keep the old source closed.
func (g *InstallationGate) CloseAdmission() {
	if g == nil {
		return
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if !g.closed {
		g.closed = true
		if g.readers == 0 {
			close(g.drained)
		}
	}
}
func (g *InstallationGate) wait(ctx context.Context) error {
	select {
	case <-g.drained:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
