// Package userconfig implements the additive v0.3 configuration boundary.
package userconfig

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type DB interface {
	Begin(context.Context) (pgx.Tx, error)
	Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
	Query(context.Context, string, ...any) (pgx.Rows, error)
	QueryRow(context.Context, string, ...any) pgx.Row
}
type Scope struct {
	TenantID string `json:"tenantId"`
	UserID   string `json:"userId"`
}
type Profile struct {
	ID                   string          `json:"profileId"`
	Kind                 string          `json:"kind"`
	Name                 string          `json:"name"`
	Provider             string          `json:"provider"`
	Config               json.RawMessage `json:"config"`
	Version              int64           `json:"version"`
	Enabled              bool            `json:"enabled"`
	Default              bool            `json:"isDefault"`
	CredentialConfigured bool            `json:"credentialConfigured"`
	Verification         string          `json:"verification"`
	ErrorCode            string          `json:"errorCode"`
	Health               string          `json:"health"`
	UpdatedAt            time.Time       `json:"updatedAt"`
}
type Input struct {
	Kind            string          `json:"kind"`
	Name            string          `json:"name"`
	Provider        string          `json:"provider"`
	Config          json.RawMessage `json:"config"`
	Secret          string          `json:"secret,omitempty"`
	ExpectedVersion int64           `json:"expectedVersion,omitempty"`
}
type Policy struct {
	MaxQueue      int    `json:"maxQueue"`
	FailurePolicy string `json:"failurePolicy"`
}
type Settings struct {
	Version int64  `json:"version"`
	Policy  Policy `json:"policy"`
	Effect  string `json:"effect"`
}
type storedSecret struct {
	ProfileID  string `json:"profileId"`
	KeyID      string `json:"keyId"`
	Ciphertext []byte `json:"ciphertext"`
}
type Binding struct {
	ID              string    `json:"bindingId"`
	ContractVersion string    `json:"contractVersion"`
	Profiles        []Profile `json:"profiles"`
	Settings        Settings  `json:"settings"`
	ExpiresAt       time.Time `json:"expiresAt"`
}
type snapshot struct {
	Binding Binding        `json:"binding"`
	Secrets []storedSecret `json:"secrets"`
}
type Fault struct {
	Status  int
	Code    string
	Message string
}

func (e *Fault) Error() string                 { return e.Code }
func (e *Fault) IntegrationCode() string       { return e.Code }
func fault(status int, code, msg string) error { return &Fault{status, code, msg} }

var ErrNotFound = fault(404, "RESOURCE_NOT_FOUND", "configuration not found")
var ErrConflict = fault(409, "CONFIG_VERSION_CONFLICT", "configuration changed; refresh and retry")
var ErrInvalid = fault(422, "INVALID_ARGUMENT", "invalid configuration")

func publicError(err error) *Fault {
	var f *Fault
	if errors.As(err, &f) {
		return f
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrNotFound.(*Fault)
	}
	return &Fault{500, "INTERNAL_ERROR", "configuration operation failed"}
}
