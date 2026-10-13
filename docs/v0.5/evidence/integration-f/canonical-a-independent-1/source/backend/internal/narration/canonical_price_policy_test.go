package narration

import (
	"encoding/json"
	"testing"
)

func TestCanonicalPriceAuthoredProvenanceOnlyExactSingleton(t *testing.T) {
	for _, test := range []struct {
		name, text, currency string
		facts                []string
		enabled, want        bool
	}{
		{"subject", "本商品当前标价是人民币{{price}}元。", "CNY", []string{"price"}, true, true},
		{"answer wording", "这款目前价格是人民币{{price}}元。", "CNY", []string{"price"}, true, true},
		{"flags off", "本商品当前标价是人民币{{price}}元。", "CNY", []string{"price"}, false, false},
		{"USD", "本商品当前标价是人民币{{price}}元。", "USD", []string{"price"}, true, false},
		{"whitespace", " 本商品当前标价是人民币{{price}}元。", "CNY", []string{"price"}, true, false},
		{"qualifier", "本商品优惠标价是人民币{{price}}元。", "CNY", []string{"price"}, true, false},
		{"category", "这份电子说明书，当前标价是人民币{{price}}元。", "CNY", []string{"price"}, true, false},
		{"extra claim", "本商品当前标价是人民币{{price}}元。购买后保证有效。", "CNY", []string{"price"}, true, false},
		{"multiclaim", "本商品当前标价是人民币{{price}}元。", "CNY", []string{"price", "stock"}, true, false},
		{"custom label", "本商品当前标价是人民币{{price}}元。", "CNY", []string{"custom_price"}, true, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			facts := map[string]string{"price": "99.00", "currency": test.currency}
			input := []BeatInput{{Statements: []Statement{{Text: test.text, FactIDs: test.facts}}}}
			templates := canonicalPriceTemplates(input, facts)
			text := "本商品当前标价是人民币99.00元。"
			if test.name == "answer wording" {
				text = "这款目前价格是人民币99.00元。"
			}
			p := Plan{ID: "n", SessionID: "s", ProductID: "p", ProductHash: "hash", ProductVersion: "hash", Segments: []Segment{{ID: "seg", Text: text, TextHash: Hash(text), FactIDs: test.facts, Lane: "NARRATION"}}}
			raw, err := marshalCanonicalPlan(p, 1, test.enabled, templates)
			if err != nil {
				t.Fatal(err)
			}
			var saved map[string]json.RawMessage
			json.Unmarshal(raw, &saved)
			if (len(saved[canonicalPricePolicyKey]) > 0) != test.want {
				t.Fatal("unsafe provenance coverage", string(raw))
			}
			// The typed public Plan has no private policy; it never consumes user metadata.
			var public Plan
			json.Unmarshal(raw, &public)
			publicRaw, _ := json.Marshal(public)
			var output map[string]json.RawMessage
			json.Unmarshal(publicRaw, &output)
			if len(output[canonicalPricePolicyKey]) != 0 {
				t.Fatal("private policy leaked into DTO")
			}
		})
	}
}

func TestCanonicalCoverageStillNeedsFullProofAndCannotCoverOtherFacts(t *testing.T) {
	d := fixture(t, 2)
	s := start(t, &d)
	must(t, d.CompleteNarration(proof(d, s), d.Revision, d.RunEpoch))
	target := &d.Plan.Segments[1]
	target.FactIDs = []string{"price"}
	target.Text = "本商品当前标价是人民币99.00元。"
	target.TextHash = Hash(target.Text)
	d.State = Answering
	d.Turn = &Turn{ID: "turn", MappedNarrationFacts: []string{"price"}, Answer: &Segment{ID: "answer", Text: "这款目前价格是人民币99.00元。", TextHash: Hash("这款目前价格是人民币99.00元。"), FactIDs: []string{"price"}, Lane: "AUDIENCE_ANSWER"}}
	d.Resume = &ResumePoint{NextSegmentID: target.ID, NextBeatID: target.BeatID}
	coverage := map[string]string{target.ID: target.TextHash}
	p := proof(d, *d.Turn.Answer)
	for _, kind := range []string{"partial", "stale", "Stop", "wrong hash", "unknown target", "other fact", "legacy"} {
		t.Run(kind, func(t *testing.T) {
			raw, _ := json.Marshal(d)
			var copy Document
			json.Unmarshal(raw, &copy)
			cp := p
			cp.Sinks = append([]SinkRange{}, p.Sinks...)
			allowed := coverage
			switch kind {
			case "partial":
				cp.Sinks[1].AudioEnd--
			case "stale":
				cp.Identity.RunEpoch--
			case "Stop":
				copy.StopBarrier = true
			case "wrong hash":
				allowed = map[string]string{target.ID: "bad"}
			case "unknown target":
				copy.Plan.Segments[1].Status = "UNKNOWN"
			case "other fact":
				copy.Turn.MappedNarrationFacts = []string{"stock"}
			case "legacy":
				allowed = nil
			}
			err := copy.completeAnswerWithCoverage(cp, copy.Revision, copy.RunEpoch, allowed)
			if kind == "partial" || kind == "stale" || kind == "Stop" {
				if err == nil {
					t.Fatal("invalid proof accepted")
				}
			} else {
				must(t, err)
			}
			if copy.Plan.Segments[1].Status == "SATISFIED_BY_ANSWER" || contains(copy.Cursor.CompletedFacts, "price") {
				t.Fatal("unproved price skipped")
			}
		})
	}
	must(t, d.completeAnswerWithCoverage(p, d.Revision, d.RunEpoch, coverage))
	if d.Plan.Segments[1].Status != "SATISFIED_BY_ANSWER" || d.Cursor.NextOrdinal != 2 || d.Resume.NextSegmentID != "" || !contains(d.Cursor.CompletedFacts, "price") {
		t.Fatal("canonical complete proof did not skip once")
	}
}

func TestPublicOrMissingCanonicalCoverageNeverInfersEmptyTargetHashMapping(t *testing.T) {
	for _, mode := range []string{"public-nil", "private-nil", "missing-key", "explicit-empty"} {
		t.Run(mode, func(t *testing.T) {
			d := fixture(t, 2)
			s := start(t, &d)
			must(t, d.CompleteNarration(proof(d, s), d.Revision, d.RunEpoch))
			target := &d.Plan.Segments[1]
			target.FactIDs = []string{"price"}
			target.Text = "本商品当前标价是人民币99.00元。"
			target.TextHash = ""
			d.State = Answering
			d.Turn = &Turn{ID: "turn", MappedNarrationFacts: []string{"price"}, Answer: &Segment{ID: "answer", Text: "这款目前价格是人民币99.00元。", TextHash: Hash("这款目前价格是人民币99.00元。"), FactIDs: []string{"price"}, Lane: "AUDIENCE_ANSWER"}}
			d.Resume = &ResumePoint{NextSegmentID: target.ID, NextBeatID: target.BeatID}
			p := proof(d, *d.Turn.Answer)
			var coverage map[string]string
			if mode == "missing-key" {
				coverage = map[string]string{"other": "some-hash"}
			}
			if mode == "explicit-empty" {
				coverage = map[string]string{target.ID: ""}
			}
			if mode == "public-nil" {
				must(t, d.CompleteAnswer(p, d.Revision, d.RunEpoch))
			} else {
				must(t, d.completeAnswerWithCoverage(p, d.Revision, d.RunEpoch, coverage))
			}
			if d.Plan.Segments[1].Status != "PENDING" || d.Cursor.NextOrdinal != 1 || contains(d.Cursor.CompletedFacts, "price") {
				t.Fatal("missing explicit nonempty mapping skipped price")
			}
		})
	}
}
