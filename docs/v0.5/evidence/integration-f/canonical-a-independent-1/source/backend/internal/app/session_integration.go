package app

import (
	"astralive/backend/generated/runtimeapi"
	"context"
)

// SessionIntegration keeps binding/ownership outside the frozen v1.1 request.
// Prepare is called before Runtime admission; Release must be idempotent.
type SessionIntegration interface {
	Prepare(context.Context, string, *runtimeapi.CreateRuntimeSessionRequest) error
	Release(context.Context, string) error
}
