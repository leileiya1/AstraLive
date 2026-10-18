package receiver1

import (
	"astralive/backend/internal/durablelivev2/wire"
	"context"
)

// Compatibility for Agent2's explicitly synthetic valid/blocking read fixture.
// The 623-line probe itself is retained byte-for-byte. This is test-only; the
// source remains adversarial (it can violate lifecycle discipline), and its
// changes must be detected, never treated as proof of physical coordination.
func (s *reviewSource) InstallationGate(ctx context.Context, b wire.ReceiverBootstrapBinding, r, g Identity) (*InstallationGate, error) {
	return s.fixture.InstallationGate(ctx, b, r, g)
}
