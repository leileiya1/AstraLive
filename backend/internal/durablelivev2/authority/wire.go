package authority

import (
	"context"

	"astralive/backend/internal/durablelivev2/wire"
	"github.com/jackc/pgx/v5/pgxpool"
)

// DTODelivery pins the sole Agent4 delivery consumed by this implementation.
const DTODelivery = "e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565"

// New installs the official strict local codec. Physical source, actual assertion
// and Observer verifiers remain nil/fail-closed until trusted composition.
func New(db *pgxpool.Pool) *Store { return &Store{DB: db, Validate: OfficialValidate} }

func OfficialValidate(name string, v Document) error {
	message, e := wire.Decode(name, canon(v))
	if e != nil {
		return fail("INVALID_ARGUMENT")
	}
	switch value := message.(type) {
	case *wire.JournalPrepareAnswerRequest:
		if wire.VerifyAnswerArtifactHashes(&value.Artifact) != nil {
			return fail("ANSWER_CONFLICT")
		}
	case *wire.AnswerArtifact:
		if wire.VerifyAnswerArtifactHashes(value) != nil {
			return fail("ANSWER_CONFLICT")
		}
	}
	return nil
}

func allowed(role, name string) bool {
	op, ok := wire.LookupOperation(wire.OperationID(name))
	if !ok || op.Target != wire.TargetBackend {
		return false
	}
	for _, r := range op.Roles {
		if string(r) == role {
			return true
		}
	}
	return false
}

// Handle is an unmounted transport adapter. Actor and metadata MUST be constructed
// from authenticated peer/router data, never request JSON. It mounts no route and
// supplies no credentials. Callers must not log the raw body or serialized DTO.
func (s *Store) Handle(ctx context.Context, p Actor, op wire.OperationID, peer wire.RequestContext, body []byte) (wire.Message, error) {
	if string(peer.Role) != p.Role || peer.Target != wire.TargetBackend || !allowed(p.Role, string(op)) {
		return nil, fail("FORBIDDEN")
	}
	message, e := wire.DecodeRequest(op, peer, body)
	if e != nil {
		return nil, fail("INVALID_ARGUMENT")
	}
	raw, e := wire.Encode(message)
	if e != nil {
		return nil, fail("INVALID_ARGUMENT")
	}
	q, e := legacyDecode(raw)
	if e != nil {
		return nil, fail("INVALID_ARGUMENT")
	}
	result, e := s.Call(ctx, p, string(op), q)
	if e != nil {
		return nil, e
	}
	definition, ok := wire.LookupOperation(op)
	if !ok {
		return nil, fail("INVALID_ARGUMENT")
	}
	out, e := wire.DecodeResponse(op, definition.SuccessStatus, canon(result))
	if e != nil {
		return nil, fail("DEPENDENCY_UNAVAILABLE")
	}
	return out, nil
}
