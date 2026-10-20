package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

var at = time.Date(2026, 10, 17, 0, 0, 0, 0, time.UTC)

func fact(kind string) Dependency {
	return Dependency{kind, "product", "source_1", cp.Hash(kind), at, at.Add(2 * time.Second)}
}
func rules() []Rule {
	return []Rule{
		{Clause: "这款的价格是129.90元", Dependencies: []Dependency{fact("PRICE")}},
		{Clause: "这款有XL、XXL和2XL尺码", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款没有S尺码", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款有XXL尺码", WhenSize: "XXL", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款不是防水款，而是防泼水款", Dependencies: []Dependency{fact("PRODUCT_DETAILS")}},
		{Clause: "这款比旧款轻20g", Dependencies: []Dependency{fact("PRODUCT_DETAILS")}},
		{Clause: "这款的型号是AB-12XL", Dependencies: []Dependency{fact("PRODUCT_DETAILS")}},
		{Clause: "这款的重量是0.5kg", Dependencies: []Dependency{fact("PRODUCT_DETAILS")}},
		{Clause: "这款目前价格是 129.9，币种信息暂不可用", Dependencies: []Dependency{fact("PRICE")}},
		{Clause: "这款有 XL 尺码", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款目前没有 2XL 尺码", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款目前商品整体库存还有 20 件", Dependencies: []Dependency{fact("STOCK")}},
	}
}

type source struct {
	chunks        []string
	reads, closed int
}

func (s *source) Next(ctx context.Context) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	s.reads++
	if len(s.chunks) == 0 {
		return "", io.EOF
	}
	v := s.chunks[0]
	s.chunks = s.chunks[1:]
	return v, nil
}
func (s *source) Close() error { s.closed++; return nil }
func language(t *testing.T) *Language {
	t.Helper()
	l, e := NewLanguage(rules())
	if e != nil {
		t.Fatal(e)
	}
	return l
}
func oneRune(s string) []string {
	var out []string
	for _, r := range s {
		out = append(out, string(r))
	}
	return out
}
func scan(t *testing.T, text string) ([]Unit, error) {
	t.Helper()
	s := NewScanner(&source{chunks: oneRune(text)}, language(t))
	var out []Unit
	for {
		u, e := s.Next(context.Background())
		if e != nil {
			return out, e
		}
		out = append(out, u)
	}
}

func TestCompleteChineseProductionsAcrossEveryTokenBoundary(t *testing.T) {
	for _, text := range []string{"这款的价格是129.90元。", "这款有XL、XXL和2XL尺码。", "这款没有S尺码。", "如果您需要XXL尺码，那么这款有XXL尺码。", "这款不是防水款，而是防泼水款。", "这款比旧款轻20g。", "这款的型号是AB-12XL。", "这款的重量是0.5kg。", "这款目前价格是 129.9，币种信息暂不可用。", "这款有 XL 尺码。", "这款目前没有 2XL 尺码。", "这款目前商品整体库存还有 20 件。"} {
		t.Run(text, func(t *testing.T) {
			for i := 1; i < utf8.RuneCountInString(text); i++ {
				r := []rune(text)
				src := &source{chunks: []string{string(r[:i]), string(r[i:])}}
				s := NewScanner(src, language(t))
				u, e := s.Next(context.Background())
				if e != nil || u.Text() != text || len(u.Dependencies()) == 0 {
					t.Fatalf("split=%d unit=%q err=%v", i, u.Text(), e)
				}
				if _, e = s.Next(context.Background()); e != io.EOF {
					t.Fatal(e)
				}
				if src.closed != 1 {
					t.Fatal("source not closed exactly once")
				}
			}
		})
	}
}
func TestUnprovenChineseCannotBeMadeSafeByPunctuationOrEOF(t *testing.T) {
	for _, text := range []string{"如果您需要XXL尺码。", "如果您需要XXL尺码，", "这款不是防水款。", "这款不是没有XL尺码。", "这款比旧款轻。", "这款比旧款轻20。", "这款比旧款轻20元。", "这款的价格是129。90元。", "这款有X。L尺码。", "这款没有S尺码，除非加钱。", "这款的价格是129.90", "这款的重量是0.5k", "只有您需要XL尺码，", "这款有XL尺码。", "优惠满100减20。", "这款绝对防水。", "感谢您的提问！", "这款的型号是AB-12。XL。"} {
		t.Run(text, func(t *testing.T) {
			u, e := scan(t, text)
			if !errors.Is(e, ErrUnsafe) || len(u) != 0 {
				t.Fatalf("unsafe accepted: units=%v err=%v", u, e)
			}
		})
	}
}
func TestDependencyCoverageAndConditionalSizeIdentity(t *testing.T) {
	for _, r := range []Rule{
		{Clause: "这款的价格是129.90元"},
		{Clause: "这款的价格是129.90元", Dependencies: []Dependency{fact("STOCK")}},
		{Clause: "这款有XXL尺码", WhenSize: "XL", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "这款没有XL尺码", WhenSize: "XL", Dependencies: []Dependency{fact("SIZE_OPTIONS")}},
		{Clause: "如果价格便宜", Dependencies: []Dependency{fact("PRICE")}},
		{Clause: "这款有XL尺码", Dependencies: []Dependency{fact("SIZE_OPTIONS"), fact("SIZE_OPTIONS")}},
		{Clause: "这款比旧款便宜20元", Dependencies: []Dependency{fact("PRODUCT_DETAILS")}},
	} {
		if _, e := NewLanguage([]Rule{r}); e == nil {
			t.Fatalf("invalid rule accepted: %+v", r)
		}
	}
	u, e := scan(t, "感谢您的提问。")
	if e != io.EOF || len(u) != 1 || len(u[0].Dependencies()) != 0 {
		t.Fatal(u, e)
	}
}
func TestPullBackpressureAndResourceBounds(t *testing.T) {
	src := &source{chunks: []string{"这款的价格是129.90元。", "这款有XL、XXL和2XL尺码。"}}
	s := NewScanner(src, language(t))
	if src.reads != 0 {
		t.Fatal("prefetch")
	}
	if _, e := s.Next(context.Background()); e != nil {
		t.Fatal(e)
	}
	if src.reads != 1 {
		t.Fatal("looked past complete unit")
	}
	for _, chunk := range []string{strings.Repeat("这", 65), strings.Repeat("a", MaxFrameBytes+1), string([]byte{0xff}), ""} {
		x := &source{chunks: []string{chunk}}
		r := NewScanner(x, language(t))
		if _, e := r.Next(context.Background()); !errors.Is(e, ErrLimit) {
			t.Fatal(e)
		}
		if x.closed != 1 {
			t.Fatal("error didn't close source")
		}
	}
	if _, e := NewLanguage(make([]Rule, 65)); !errors.Is(e, ErrLimit) {
		t.Fatal(e)
	}
	entries := make([]Rule, MaxRules)
	for i := range entries {
		entries[i] = Rule{Clause: "这款的价格是" + strings.Repeat("1", 180) + strings.Repeat("2", i) + "元", Dependencies: []Dependency{fact("PRICE")}}
	}
	if _, e := NewLanguage(entries); !errors.Is(e, ErrLimit) {
		t.Fatal("language trie unbounded", e)
	}
	x := &source{chunks: []string{"这款的价格是129.90元。"}}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r := NewScanner(x, language(t))
	if _, e := r.Next(ctx); e != context.Canceled || x.reads != 0 || x.closed != 1 {
		t.Fatal(e, x)
	}
	// A single 240+ character production cannot be cropped into safe fragments.
	long := "这款有" + strings.Repeat("XL、", 100) + "XL尺码"
	if _, e := NewLanguage([]Rule{{Clause: long, Dependencies: []Dependency{fact("SIZE_OPTIONS")}}}); !errors.Is(e, ErrLimit) {
		t.Fatal(e)
	}
}

type observations struct {
	now                             *time.Time
	change, missing, expired, extra bool
}

func (o observations) Observe(_ context.Context, _ Binding, want []Dependency) ([]Dependency, error) {
	out := append([]Dependency(nil), want...)
	for i := range out {
		out[i].Verified = *o.now
		out[i].Expires = o.now.Add(2 * time.Second)
		if o.change {
			out[i].Digest = cp.Hash("new price")
		}
		if o.expired {
			out[i].Expires = *o.now
		}
	}
	if o.missing && len(out) > 0 {
		out = out[1:]
	}
	if o.extra {
		out = append(out, fact("STOCK"))
	}
	return out, nil
}
func binding() Binding {
	return Binding{Tenant: "tenant", Owner: "owner", Run: "run", Session: "session", Command: "command", Attempt: "attempt", Turn: "turn", Utterance: "utterance", Producer: "producer", Answer: "answer", Product: "product", Snapshot: cp.Hash("snapshot"), RequestHash: cp.Hash("这款有XL吗？"), Epoch: 1, Generation: 3}
}

// Explicit MOCK encoding adapter: adapts the frozen fixture through generic
// test JSON. No production DTO/encoder is implemented or duplicated here.
type fixtureEncoding struct {
	template map[string]any
	bodies   [][]byte
}

func newEncoding(t *testing.T) *fixtureEncoding {
	t.Helper()
	raw, e := os.ReadFile("../../../../contracts/v0.5/durable-live-2/examples/objects.json")
	if e != nil {
		t.Fatal(e)
	}
	var objects []struct {
		Name  string         `json:"name"`
		Value map[string]any `json:"value"`
	}
	if e = json.Unmarshal(raw, &objects); e != nil {
		t.Fatal(e)
	}
	for _, x := range objects {
		if x.Name == "AnswerUnit1" {
			return &fixtureEncoding{template: x.Value}
		}
	}
	t.Fatal("fixture missing")
	return nil
}
func (e *fixtureEncoding) Encode(d Draft) ([]byte, error) {
	v := map[string]any{}
	for k, x := range e.template {
		v[k] = x
	}
	delete(v, "artifactHash")
	b := d.Binding
	for k, x := range map[string]any{"tenantId": b.Tenant, "ownerId": b.Owner, "runId": b.Run, "sessionId": b.Session, "commandId": b.Command, "attemptId": b.Attempt, "runEpoch": b.Epoch, "producerIncarnation": b.Producer, "requestHash": b.RequestHash, "answerId": b.Answer, "artifactId": d.ID, "sequence": d.Sequence, "answerText": d.Text, "answerTextHash": d.TextHash, "productId": b.Product, "productSnapshotVersion": b.Snapshot, "estimatedDurationMs": d.Duration.Milliseconds(), "createdAt": cp.Stamp(d.Created)} {
		v[k] = x
	}
	if d.PreviousHash == "" {
		v["previousArtifactHash"] = nil
	} else {
		v["previousArtifactHash"] = d.PreviousHash
	}
	facts := []any{}
	kinds := []string{}
	for _, f := range d.Facts {
		facts = append(facts, map[string]any{"kind": f.Kind, "productId": f.Product, "sourceVersion": f.Version, "valueHash": f.Digest, "validatedAt": cp.Stamp(f.Verified), "expiresAt": cp.Stamp(f.Expires)})
		kinds = append(kinds, f.Kind)
	}
	v["factDependencies"] = facts
	v["assertionKinds"] = kinds
	// JSON's fixture float64 values are only unchanged constants here; normalize
	// via integer json.Number before reusing existing canonical implementation.
	raw, _ := json.Marshal(v)
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.UseNumber()
	var value any
	if err := dec.Decode(&value); err != nil {
		return nil, err
	}
	body, err := cp.Canonical(value)
	e.bodies = append(e.bodies, body)
	return body, err
}

func TestActualAnswerBodyHashChainFactsAndManifest(t *testing.T) {
	now := at
	encoding := newEncoding(t)
	b, e := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, encoding)
	if e != nil {
		t.Fatal(e)
	}
	text := "这款的价格是129.90元。这款有XL、XXL和2XL尺码。"
	units, e := scan(t, text)
	if e != io.EOF {
		t.Fatal(e)
	}
	var previous string
	for i, u := range units {
		a, e := b.Build(context.Background(), u)
		if e != nil {
			t.Fatal(e)
		}
		d := a.Draft()
		if d.Sequence != i+1 || d.Text != u.Text() || d.TextHash != cp.Hash(u.Text()) || a.Hash() != cp.Hash(string(a.CanonicalBody())) || d.PreviousHash != previous || d.TextHash == binding().RequestHash || d.Binding != binding() {
			t.Fatal(d)
		}
		if len(d.Facts) != 1 || d.Facts[0].Digest != u.Dependencies()[0].Digest {
			t.Fatal("missing facts")
		}
		body := a.CanonicalBody()
		body[0] = 'X'
		if a.CanonicalBody()[0] == 'X' {
			t.Fatal("mutable artifact")
		}
		d.Facts[0].Digest = "mutated"
		if a.Draft().Facts[0].Digest == "mutated" {
			t.Fatal("mutable facts")
		}
		previous = a.Hash()
	}
	s := b.Summary()
	if s.TextHash != cp.Hash(text) || len(s.Entries) != 2 || s.Characters != utf8.RuneCountInString(text) {
		t.Fatal(s)
	}
	if !hashPattern.MatchString(s.ManifestHash()) {
		t.Fatal("manifest hash missing")
	}
	if output := os.Getenv("ASTRALIVE_AGENT3_ARTIFACT_EVIDENCE"); output != "" {
		// Optional test evidence only: external frozen-schema/hash validation.
		rows := []any{}
		for _, body := range encoding.bodies {
			var v map[string]any
			decoder := json.NewDecoder(strings.NewReader(string(body)))
			decoder.UseNumber()
			if e := decoder.Decode(&v); e != nil {
				t.Fatal(e)
			}
			v["artifactHash"] = cp.Hash(string(body))
			rows = append(rows, v)
		}
		raw, e := json.MarshalIndent(rows, "", "  ")
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(output, raw, 0600); e != nil {
			t.Fatal(e)
		}
	}
	if _, e := json.Marshal(units); e != nil {
		t.Fatal(e)
	} // Unit isn't a wire authorization.
	if _, e := json.Marshal(Draft{}); e == nil {
		t.Fatal("draft accidentally serialized as DTO")
	}
}
func TestFactMutationExpiryMissingOrExtraNeverBuildsArtifact(t *testing.T) {
	units, _ := scan(t, "这款的价格是129.90元。")
	for _, mode := range []string{"changed", "expired", "missing", "extra"} {
		t.Run(mode, func(t *testing.T) {
			now := at
			o := observations{now: &now, change: mode == "changed", expired: mode == "expired", missing: mode == "missing", extra: mode == "extra"}
			encoder := newEncoding(t)
			b, _ := NewBuilder(binding(), func() time.Time { return now }, o, encoder)
			if _, e := b.Build(context.Background(), units[0]); !errors.Is(e, ErrFacts) {
				t.Fatal(e)
			}
			if len(encoder.bodies) != 0 || len(b.Summary().Entries) != 0 {
				t.Fatal("bad fact reached encoding")
			}
		})
	}
}
func TestNoTruncationLongModelAndAnswerAuditLimit(t *testing.T) {
	l, e := NewLanguage([]Rule{{Clause: "这款的型号是" + strings.Repeat("X", 60), Dependencies: []Dependency{fact("PRODUCT_DETAILS")}}})
	if e != nil {
		t.Fatal(e)
	}
	s := NewScanner(&source{chunks: oneRune("这款的型号是" + strings.Repeat("X", 60) + "。")}, l)
	u, e := s.Next(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	now := at
	b, _ := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, newEncoding(t))
	if _, e = b.Build(context.Background(), u); !errors.Is(e, ErrLimit) {
		t.Fatal(e)
	}
	units, _ := scan(t, "感谢您的提问。")
	for i := 0; i < MaxUnits; i++ {
		if _, e = b.Build(context.Background(), units[0]); e != nil {
			t.Fatal(e)
		}
	}
	if _, e = b.Build(context.Background(), units[0]); !errors.Is(e, ErrLimit) {
		t.Fatal(e)
	}
}

func TestFreshFactsCanBeObservedAfterLateUnitWithoutChangingValue(t *testing.T) {
	units, _ := scan(t, "这款的价格是129.90元。")
	now := at.Add(3 * time.Second)
	b, _ := NewBuilder(binding(), func() time.Time { return now }, observations{now: &now}, newEncoding(t))
	a, e := b.Build(context.Background(), units[0])
	if e != nil {
		t.Fatal(e)
	}
	d := a.Draft()
	if d.Facts[0].Verified != now || d.Facts[0].Digest != fact("PRICE").Digest || d.Binding.Snapshot != binding().Snapshot {
		t.Fatal("refreshed or replaced the wrong assertion")
	}
}

func TestCloseRejectsAlreadyBufferedNextUnit(t *testing.T) {
	src := &source{chunks: []string{"感谢您的提问。我来为您介绍。"}}
	s := NewScanner(src, language(t))
	if _, e := s.Next(context.Background()); e != nil {
		t.Fatal(e)
	}
	s.Close()
	if _, e := s.Next(context.Background()); e != context.Canceled {
		t.Fatal("closed stream reused pending text", e)
	}
	if src.reads != 1 || src.closed != 1 {
		t.Fatal(src)
	}
}
