package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"astralive/backend/internal/durablelivev2/wire"
	"encoding/json"
	"strings"
)

// WireDependencySHA is Agent4's explicitly delivered, normally merged SDK pin.
// All concrete DTOs below come from that sole package; none are redefined here.
const WireDependencySHA = "e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565"

// WireEncoding maps recognized domain drafts to the actual shared AnswerArtifact
// and canonical hash input. It does not check current authority or grant effects.
type WireEncoding struct{}

func (WireEncoding) Encode(d Draft) ([]byte, error) {
	if d.TextHash != cp.Hash(d.Text) {
		return nil, ErrUnsafe
	}
	b := d.Binding
	product, snapshot := wire.ID(b.Product), wire.Hash(b.Snapshot)
	a := wire.AnswerArtifact{
		SchemaVersion: "0.5", ContractRevision: "durable-live-2",
		TenantID: wire.ID(b.Tenant), OwnerID: wire.ID(b.Owner), RunID: wire.ID(b.Run),
		CommandID: wire.ID(b.Command), AttemptID: wire.ID(b.Attempt), SessionID: wire.ID(b.Session),
		RunEpoch: wire.Epoch(b.Epoch), ProducerIncarnation: wire.ID(b.Producer), RequestHash: wire.Hash(b.RequestHash),
		AnswerID: wire.ID(b.Answer), ArtifactID: wire.ID(d.ID), Sequence: int64(d.Sequence),
		AnswerText: d.Text, AnswerTextHash: wire.Hash(d.TextHash), ArtifactHash: wire.Hash(strings.Repeat("0", 64)),
		ProductID: &product, ProductSnapshotVersion: &snapshot,
		FactDependencies:    make([]wire.FactDependency, 0, len(d.Facts)),
		AssertionKinds:      make([]wire.AnswerArtifactAssertionKindsItem, 0, len(d.Facts)),
		SemanticBoundary:    wire.AnswerArtifactSemanticBoundaryCOMPLETE_SENTENCE,
		EstimatedDurationMs: d.Duration.Milliseconds(), CreatedAt: wire.Timestamp(cp.Stamp(d.Created)),
	}
	if d.PreviousHash != "" {
		prev := wire.Hash(d.PreviousHash)
		a.PreviousArtifactHash = &prev
	}
	seen := map[string]bool{}
	for _, f := range d.Facts {
		if seen[f.Kind] || f.Product != b.Product || !validDependency(f) {
			return nil, ErrFacts
		}
		seen[f.Kind] = true
		a.FactDependencies = append(a.FactDependencies, wire.FactDependency{Kind: wire.FactDependencyKind(f.Kind), ProductID: wire.ID(f.Product), SourceVersion: wire.ID(f.Version), ValidatedAt: wire.Timestamp(cp.Stamp(f.Verified)), ExpiresAt: wire.Timestamp(cp.Stamp(f.Expires)), ValueHash: wire.Hash(f.Digest)})
		a.AssertionKinds = append(a.AssertionKinds, wire.AnswerArtifactAssertionKindsItem(f.Kind))
	}
	// Encode validates all closed shared DTO fields (including required null/[]).
	raw, err := wire.Encode(&a)
	if err != nil {
		return nil, err
	}
	var body map[string]any
	// Avoid float64 reserialization of safe-integer identity fields.
	// Domain Epoch is validated <=2^53-1; use a Number-preserving decoder anyway.
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	if err = decoder.Decode(&body); err != nil {
		return nil, err
	}
	delete(body, "artifactHash")
	raw, err = json.Marshal(body)
	if err != nil {
		return nil, err
	}
	return wire.CanonicalJSON(raw)
}

// Typed validates the final descriptor/hash using the actual SDK, returning a
// fresh generated DTO. A Mock Encoding result cannot silently pass this boundary.
func (a Artifact) Typed() (*wire.AnswerArtifact, error) {
	decoder := json.NewDecoder(strings.NewReader(string(a.body)))
	decoder.UseNumber()
	var body map[string]any
	if err := decoder.Decode(&body); err != nil {
		return nil, err
	}
	body["artifactHash"] = a.digest
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	v, err := wire.DecodeAnswerArtifact(raw)
	if err != nil {
		return nil, err
	}
	if err = wire.VerifyAnswerArtifactHashes(v); err != nil {
		return nil, err
	}
	return v, nil
}

// PrepareRequest is a typed request builder, not a client/Authority replacement.
// The caller supplies current CAS revisions after trusted state reads. Transport
// authentication and EncodeRequest's actual context remain Agent4's responsibility.
func (a Artifact) PrepareRequest(requestID string, inbox, answerRevision int64) (*wire.JournalPrepareAnswerRequest, error) {
	artifact, err := a.Typed()
	if err != nil {
		return nil, err
	}
	b := a.draft.Binding
	q := &wire.JournalPrepareAnswerRequest{SchemaVersion: "0.5", ContractRevision: "durable-live-2", TenantID: wire.ID(b.Tenant), OwnerID: wire.ID(b.Owner), RunID: wire.ID(b.Run), CommandID: wire.ID(b.Command), AttemptID: wire.ID(b.Attempt), SessionID: wire.ID(b.Session), RunEpoch: wire.Epoch(b.Epoch), ProducerIncarnation: wire.ID(b.Producer), RequestHash: wire.Hash(b.RequestHash), RequestID: wire.ID(requestID), Artifact: *artifact, ExpectedInboxRevision: wire.Revision(inbox), ExpectedAnswerRevision: answerRevision, IdempotencyKey: wire.ID("prepare:" + a.draft.ID)}
	if _, err = wire.Encode(q); err != nil {
		return nil, err
	}
	return q, nil
}

func (s Summary) SealRequest(requestID string, answerRevision int64) (*wire.JournalSealAnswerRequest, error) {
	if len(s.Entries) < 1 || len(s.Entries) > MaxUnits || s.Characters < 1 || s.Characters > MaxAnswer {
		return nil, ErrLimit
	}
	seen := map[string]bool{}
	for i, e := range s.Entries {
		if e.Sequence != i+1 || !cp.ValidID(e.ID) || !hashPattern.MatchString(e.Digest) || seen[e.ID] {
			return nil, ErrUnsafe
		}
		seen[e.ID] = true
	}
	b := s.Binding
	q := &wire.JournalSealAnswerRequest{SchemaVersion: "0.5", ContractRevision: "durable-live-2", TenantID: wire.ID(b.Tenant), OwnerID: wire.ID(b.Owner), RunID: wire.ID(b.Run), CommandID: wire.ID(b.Command), AttemptID: wire.ID(b.Attempt), SessionID: wire.ID(b.Session), RunEpoch: wire.Epoch(b.Epoch), ProducerIncarnation: wire.ID(b.Producer), RequestHash: wire.Hash(b.RequestHash), RequestID: wire.ID(requestID), AnswerID: wire.ID(b.Answer), ExpectedAnswerRevision: wire.Revision(answerRevision), IdempotencyKey: wire.ID("seal:" + cp.Hash(b.Answer)), SequenceCount: int64(len(s.Entries)), FinalAnswerTextHash: wire.Hash(s.TextHash), ManifestHash: wire.Hash(s.ManifestHash())}
	if _, err := wire.Encode(q); err != nil {
		return nil, err
	}
	return q, nil
}
