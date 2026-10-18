package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"hash"
	"time"
	"unicode/utf8"
)

// Binding is the existing admitted COMMENT identity projected by Agent4.
// It is not an alternative RuntimeCommand/AnswerArtifact DTO. No new identities
// may be allocated for continuations. Product is pinned even for a greeting.
type Binding struct {
	Tenant, Owner, Run, Session, Command, Attempt, Turn, Utterance, Producer string
	Answer, Product, Snapshot, RequestHash                                   string
	Epoch, Generation                                                        int64
}

// Draft is immutable by convention at the encoder boundary; Builder/Artifact
// retain their own copies. It describes an actual recognized answer, not a prompt
// or the accepted question. Intentionally has NO wire marshaler/JSON field tags.
type Draft struct {
	Binding                      Binding
	ID                           string
	Sequence                     int
	Text, TextHash, PreviousHash string // PreviousHash=="" means first unit
	Facts                        []Dependency
	Duration                     time.Duration
	Created                      time.Time
}

// Encoding is implemented only by Agent4 using the sole formal wire package.
// Encode must schema/semantics-validate the exact Draft mapping and return the
// canonical complete AnswerArtifact EXCLUDING ONLY artifactHash. Empty facts
// map to [], first previousArtifactHash to null; never trim/normalize Text.
// This package intentionally ships no production encoder or shadow v2 DTO.
type Encoding interface{ Encode(Draft) ([]byte, error) }

// Facts re-reads trusted Tool assertions outside SQL. It must return the exact
// requested dependencies, same product/snapshot/sourceVersion/valueHash, with
// fresh authority timestamps. Missing/changed/extra facts fail; it is not a
// mutable override for Artifact metadata or a replacement for Backend checks.
type Facts interface {
	Observe(context.Context, Binding, []Dependency) ([]Dependency, error)
}

type Artifact struct {
	draft  Draft
	body   []byte
	digest string
}

func (a Artifact) Draft() Draft {
	d := a.draft
	d.Facts = append([]Dependency(nil), d.Facts...)
	return d
}
func (a Artifact) Hash() string          { return a.digest }
func (a Artifact) CanonicalBody() []byte { return append([]byte(nil), a.body...) }

// Summary is a bounded internal manifest, not JournalSealAnswer's wire request.
type ManifestEntry struct {
	ID       string
	Sequence int
	Digest   string
}
type Summary struct {
	Binding    Binding
	Entries    []ManifestEntry
	TextHash   string
	Characters int
}

type Builder struct {
	binding    Binding
	clock      func() time.Time
	facts      Facts
	encoding   Encoding
	text       hash.Hash
	entries    []ManifestEntry
	characters int
	previous   string
}

// ManifestHash uses the frozen ordered {artifactId,sequence,artifactHash} hash
// input, not the domain struct's Go field names. This is a hash primitive, not
// a request DTO or a substitute for Agent4's strict operation decoder.
func (s Summary) ManifestHash() string {
	rows := make([]any, 0, len(s.Entries))
	for _, e := range s.Entries {
		rows = append(rows, map[string]any{"artifactId": e.ID, "sequence": e.Sequence, "artifactHash": e.Digest})
	}
	body, _ := cp.Canonical(rows)
	return cp.Hash(string(body))
}

func NewBuilder(b Binding, clock func() time.Time, facts Facts, encoding Encoding) (*Builder, error) {
	for _, id := range []string{b.Tenant, b.Owner, b.Run, b.Session, b.Command, b.Attempt, b.Turn, b.Utterance, b.Producer, b.Answer, b.Product} {
		if !cp.ValidID(id) {
			return nil, ErrUnsafe
		}
	}
	if b.Epoch < 1 || b.Epoch > 9007199254740991 || b.Generation < 1 || b.Generation > 9007199254740991 || !hashPattern.MatchString(b.Snapshot) || !hashPattern.MatchString(b.RequestHash) || clock == nil || facts == nil || encoding == nil {
		return nil, ErrUnsafe
	}
	return &Builder{binding: b, clock: clock, facts: facts, encoding: encoding, text: sha256.New()}, nil
}

// Build has one owner. It does no persistence and grants no execution authority.
// Every successful result must be Prepared before requesting the next result.
func (b *Builder) Build(ctx context.Context, u Unit) (Artifact, error) {
	if err := ctx.Err(); err != nil {
		return Artifact{}, err
	}
	count := utf8.RuneCountInString(u.text)
	if count < 1 || count > MaxUnit {
		return Artifact{}, ErrUnsafe
	}
	if len(b.entries) >= MaxUnits || b.characters+count > MaxAnswer {
		return Artifact{}, ErrLimit
	}
	duration := cp.DefaultConfig().Estimate(u.text)
	if duration > 6*time.Second {
		return Artifact{}, ErrLimit
	}
	deps, err := b.facts.Observe(ctx, b.binding, u.Dependencies())
	if err != nil {
		return Artifact{}, err
	}
	if len(deps) != len(u.facts) {
		return Artifact{}, ErrFacts
	}
	// Match by identity, retaining canonical vocabulary order, never silently
	// replacing an old value with the latest product value.
	now := b.clock()
	ordered := make([]Dependency, 0, len(deps))
	seen := map[string]bool{}
	for _, expected := range u.facts {
		found := false
		for _, d := range deps {
			if factKey(d) != factKey(expected) {
				continue
			}
			if seen[factKey(d)] || !validDependency(d) || d.Product != b.binding.Product || d.Version != expected.Version || d.Digest != expected.Digest || d.Verified.After(now) || !now.Before(d.Expires) {
				return Artifact{}, ErrFacts
			}
			seen[factKey(d)] = true
			ordered = append(ordered, d)
			found = true
		}
		if !found {
			return Artifact{}, ErrFacts
		}
	}
	seq := len(b.entries) + 1
	idHash, _ := cp.Version([]any{"answer-unit-domain-1", b.binding.Run, b.binding.Command, b.binding.Attempt, b.binding.Answer, seq})
	d := Draft{Binding: b.binding, ID: "au_" + idHash, Sequence: seq, Text: u.text, TextHash: cp.Hash(u.text), PreviousHash: b.previous, Facts: ordered, Duration: duration, Created: now}
	copyDraft := d
	copyDraft.Facts = append([]Dependency(nil), d.Facts...)
	body, err := b.encoding.Encode(copyDraft)
	if err != nil {
		return Artifact{}, err
	}
	if len(body) == 0 || len(body) > MaxArtifactBytes {
		return Artifact{}, ErrLimit
	}
	if err := ctx.Err(); err != nil {
		return Artifact{}, err
	}
	digest := cp.Hash(string(body))
	a := Artifact{d, append([]byte(nil), body...), digest}
	b.entries = append(b.entries, ManifestEntry{d.ID, seq, digest})
	b.characters += count
	b.previous = digest
	_, _ = b.text.Write([]byte(u.text))
	return a, nil
}
func (b *Builder) Summary() Summary {
	return Summary{b.binding, append([]ManifestEntry(nil), b.entries...), hex.EncodeToString(b.text.Sum(nil)), b.characters}
}

// Prevent accidentally treating domain drafts as an unofficial HTTP DTO.
func (Draft) MarshalJSON() ([]byte, error) {
	return nil, errors.New("formal Agent4 wire encoder required")
}
