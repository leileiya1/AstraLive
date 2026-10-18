package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"encoding/json"
	"io"
	"os"
	"testing"
	"time"
)

func TestOfficialWireArtifactsPrepareAndSeal(t *testing.T) {
	now := at
	b, err := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, WireEncoding{})
	if err != nil {
		t.Fatal(err)
	}
	units, err := scan(t, "这款的价格是129.90元。这款有XL、XXL和2XL尺码。")
	if err != io.EOF {
		t.Fatal(err)
	}
	artifacts := []*wire.AnswerArtifact{}
	requests := []*wire.JournalPrepareAnswerRequest{}
	for _, u := range units {
		a, err := b.Build(context.Background(), u)
		if err != nil {
			t.Fatal(err)
		}
		v, err := a.Typed()
		if err != nil {
			t.Fatal(err)
		}
		if string(v.AnswerTextHash) != cp.Hash(u.Text()) || string(v.ArtifactHash) != a.Hash() || v.AnswerText != u.Text() {
			t.Fatal("actual answer hash lost")
		}
		q, err := a.PrepareRequest("request", 1, 0)
		if err != nil {
			t.Fatal(err)
		}
		ctx := wire.RequestContext{Role: wire.RoleRuntimeJournal, Target: wire.TargetBackend, Method: "POST", RouteTemplate: wire.PathJournalPrepareAnswer}
		raw, err := wire.EncodeRequest(wire.OpJournalPrepareAnswer, ctx, q)
		if err != nil {
			t.Fatal(err)
		}
		decoded, err := wire.DecodeRequest(wire.OpJournalPrepareAnswer, ctx, raw)
		if err != nil {
			t.Fatal(err)
		}
		if decoded.(*wire.JournalPrepareAnswerRequest).Artifact.ArtifactHash != v.ArtifactHash {
			t.Fatal("wire changed identity")
		}
		artifacts = append(artifacts, v)
		requests = append(requests, q)
	}
	if artifacts[0].PreviousArtifactHash != nil || *artifacts[1].PreviousArtifactHash != artifacts[0].ArtifactHash {
		t.Fatal("chain/null mismatch")
	}
	summary := b.Summary()
	seal, err := summary.SealRequest("seal_request", 3)
	if err != nil {
		t.Fatal(err)
	}
	ctx := wire.RequestContext{Role: wire.RoleRuntimeJournal, Target: wire.TargetBackend, Method: "POST", RouteTemplate: wire.PathJournalSealAnswer}
	raw, err := wire.EncodeRequest(wire.OpJournalSealAnswer, ctx, seal)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = wire.DecodeRequest(wire.OpJournalSealAnswer, ctx, raw); err != nil {
		t.Fatal(err)
	}
	if string(seal.FinalAnswerTextHash) != summary.TextHash || string(seal.ManifestHash) != summary.ManifestHash() {
		t.Fatal("seal hashes")
	}
	if output := os.Getenv("ASTRALIVE_AGENT3_WIRE_EVIDENCE"); output != "" {
		raw, err := json.MarshalIndent(struct {
			Artifacts []*wire.AnswerArtifact              `json:"artifacts"`
			Prepares  []*wire.JournalPrepareAnswerRequest `json:"prepares"`
			Seal      *wire.JournalSealAnswerRequest      `json:"seal"`
		}{artifacts, requests, seal}, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(output, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestOfficialWireEmptyFactsAreArrayAndFirstPreviousIsNull(t *testing.T) {
	now := at
	b, _ := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, WireEncoding{})
	u, _ := scan(t, "感谢您的提问。")
	a, err := b.Build(context.Background(), u[0])
	if err != nil {
		t.Fatal(err)
	}
	v, err := a.Typed()
	if err != nil {
		t.Fatal(err)
	}
	if v.FactDependencies == nil || v.AssertionKinds == nil || v.PreviousArtifactHash != nil {
		t.Fatal("required null/[] lost")
	}
}

func TestOfficialWireRejectsTamperedOrMockArtifactsAndQuestionHash(t *testing.T) {
	now := at
	b, _ := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, WireEncoding{})
	u, _ := scan(t, "这款的价格是129.90元。")
	a, err := b.Build(context.Background(), u[0])
	if err != nil {
		t.Fatal(err)
	}
	bad := a
	bad.digest = binding().RequestHash
	if _, err = bad.Typed(); err == nil {
		t.Fatal("question hash accepted as artifact hash")
	}
	d := a.Draft()
	d.TextHash = binding().RequestHash
	if _, err = (WireEncoding{}).Encode(d); err == nil {
		t.Fatal("question hash accepted as answer text hash")
	}
	bad.body = []byte(`{"testOnly":true}`)
	if _, err = bad.Typed(); err == nil {
		t.Fatal("mock wire accepted")
	}
	if _, err = a.PrepareRequest("request", 0, 0); err == nil {
		t.Fatal("invalid inbox revision accepted")
	}
	s := b.Summary()
	s.Entries[0].Sequence = 2
	if _, err = s.SealRequest("seal", 1); err == nil {
		t.Fatal("noncontiguous manifest accepted")
	}
}
