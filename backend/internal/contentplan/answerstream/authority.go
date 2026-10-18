package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"time"
)

// AuthorityFacts runs only in the trusted Go Backend. Runtime/Guardian receive no
// DB credentials. Projection supplies all source/snapshot/value hashes. The SQL
// Product Tool read supplies literal price/stock values absent from Projection;
// their hashes must agree, otherwise the read raced a product update and fails.
// This adapter performs READS only; all answer mutations remain Authority.Handle.
type AuthorityFacts struct {
	Store   *authority.Store
	Control authority.Actor // authenticated composition data, never model/body data
	Binding Binding
}

type Knowledge struct {
	Language          *Language
	Snapshot, Version string
	Facts             []Dependency
}

func (s *AuthorityFacts) Load(ctx context.Context) (Knowledge, error) {
	b := s.Binding
	if s.Store == nil || s.Control.Role != "CONTROL" || s.Control.Tenant != b.Tenant || s.Control.Owner != b.Owner {
		return Knowledge{}, ErrFacts
	}
	p, err := s.Store.ProductProjection(ctx, s.Control, b.Command)
	if err != nil {
		return Knowledge{}, err
	}
	if p["productId"] != b.Product || p["snapshotVersion"] != b.Snapshot {
		return Knowledge{}, ErrFacts
	}
	version, ok := p["sourceVersion"].(string)
	if !ok {
		return Knowledge{}, ErrFacts
	}
	hashes, ok := p["valueHashes"].(map[string]any)
	if !ok {
		return Knowledge{}, ErrFacts
	}
	snapshot, ok := p["snapshot"].(map[string]any)
	if !ok {
		return Knowledge{}, ErrFacts
	}
	var price, currency string
	var stock int64
	var now time.Time
	err = s.Store.DB.QueryRow(ctx, "SELECT price::text,currency,stock,clock_timestamp() FROM products WHERE id=$1", b.Product).Scan(&price, &currency, &stock, &now)
	if err != nil {
		return Knowledge{}, err
	}
	priceHash, _ := cp.Version(map[string]any{"price": price, "currency": currency})
	stockHash, _ := cp.Version(stock)
	if hashes["PRICE"] != priceHash || hashes["STOCK"] != stockHash {
		return Knowledge{}, ErrFacts
	}
	deps := map[string]Dependency{}
	for _, kind := range []string{"PRICE", "STOCK", "AVAILABILITY", "SIZE_OPTIONS", "PRODUCT_DETAILS"} {
		digest, ok := hashes[kind].(string)
		if !ok {
			return Knowledge{}, ErrFacts
		}
		deps[kind] = Dependency{kind, b.Product, version, digest, now, now.Add(2 * time.Second)}
	}
	rules := []Rule{}
	add := func(text, kind, when string) {
		rules = append(rules, Rule{Clause: text, WhenSize: when, Dependencies: []Dependency{deps[kind]}})
	}
	if currency == "CNY" {
		add("这款的价格是"+price+"元", "PRICE", "")
	} // no invented currency conversion
	add(fmt.Sprintf("这款的库存是%d件", stock), "STOCK", "")
	if stock > 0 {
		add("这款目前有货", "AVAILABILITY", "")
	} else {
		add("这款暂时缺货", "AVAILABILITY", "")
	}
	available := map[string]bool{}
	items, ok := snapshot["sizes"].([]any)
	if !ok || len(items) > 128 {
		return Knowledge{}, ErrFacts
	}
	for _, item := range items {
		v, ok := item.(string)
		if !ok {
			return Knowledge{}, ErrFacts
		}
		available[v] = true
	}
	for _, v := range []string{"S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL", "7XL", "8XL", "9XL"} {
		if available[v] {
			add("这款有"+v+"尺码", "SIZE_OPTIONS", "")
			add("这款有"+v+"尺码", "SIZE_OPTIONS", v)
		} else {
			add("这款没有"+v+"尺码", "SIZE_OPTIONS", "")
		}
	}
	// Only exact supported material data, never a free-form description promoted
	// into a new fact. SQL projection cannot prove comparisons/model/weight/SKU.
	for _, material := range []string{"纯棉", "棉麻", "羊毛", "涤纶"} {
		if snapshot["description"] == material {
			add("这款采用"+material+"面料", "PRODUCT_DETAILS", "")
		}
	}
	l, err := NewLanguage(rules)
	if err != nil {
		return Knowledge{}, err
	}
	facts := []Dependency{}
	for _, kind := range []string{"PRICE", "STOCK", "AVAILABILITY", "SIZE_OPTIONS", "PRODUCT_DETAILS"} {
		facts = append(facts, deps[kind])
	}
	return Knowledge{l, b.Snapshot, version, facts}, nil
}

func (s *AuthorityFacts) Observe(ctx context.Context, b Binding, want []Dependency) ([]Dependency, error) {
	if b != s.Binding {
		return nil, ErrFacts
	}
	k, err := s.Load(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]Dependency, 0, len(want))
	for _, expected := range want {
		found := false
		for _, d := range k.Facts {
			if d.Kind == expected.Kind && d.Product == expected.Product && d.Version == expected.Version && d.Digest == expected.Digest {
				out = append(out, d)
				found = true
				break
			}
		}
		if !found {
			return nil, ErrFacts
		}
	}
	return out, nil
}

// Verify is a real preflight assertion classifier for Store.Assertions. It
// derives a fresh language from ProductProjection, recognizes the ACTUAL text,
// and compares its complete dependencies; model-provided lists cannot omit facts.
// Backend rechecks SQL product/plan versions under locks after this callback.
func (s *AuthorityFacts) Verify(ctx context.Context, p authority.Actor, raw authority.Document) error {
	if p.Tenant != s.Control.Tenant || p.Owner != s.Control.Owner || p.Room != s.Control.Room {
		return ErrFacts
	}
	encoded, err := json.Marshal(raw)
	if err != nil {
		return err
	}
	a, err := wire.DecodeAnswerArtifact(encoded)
	if err != nil {
		return err
	}
	if err = wire.VerifyAnswerArtifactHashes(a); err != nil {
		return err
	}
	if a.CommandID != wire.ID(s.Binding.Command) || a.ProductID == nil || *a.ProductID != wire.ID(s.Binding.Product) || a.ProductSnapshotVersion == nil || *a.ProductSnapshotVersion != wire.Hash(s.Binding.Snapshot) {
		return ErrFacts
	}
	k, err := s.Load(ctx)
	if err != nil {
		return err
	}
	scanner := NewScanner(&literalSource{text: a.AnswerText}, k.Language)
	defer scanner.Close()
	u, err := scanner.Next(ctx)
	if err != nil {
		return err
	}
	if u.Text() != a.AnswerText {
		return ErrUnsafe
	}
	if _, err = scanner.Next(ctx); err != io.EOF {
		return ErrUnsafe
	}
	deps := u.Dependencies()
	if len(deps) != len(a.FactDependencies) || len(deps) != len(a.AssertionKinds) {
		return ErrFacts
	}
	kinds := map[string]bool{}
	for _, v := range a.AssertionKinds {
		kinds[string(v)] = true
	}
	for _, expected := range deps {
		found := false
		for _, d := range a.FactDependencies {
			if string(d.Kind) == expected.Kind && string(d.ProductID) == expected.Product && string(d.SourceVersion) == expected.Version && string(d.ValueHash) == expected.Digest {
				found = true
			}
		}
		if !found || !kinds[expected.Kind] {
			return ErrFacts
		}
	}
	return nil
}
func (s *AuthorityFacts) Check(ctx context.Context, a Artifact) error {
	typed, err := a.Typed()
	if err != nil {
		return err
	}
	raw, err := wire.Encode(typed)
	if err != nil {
		return err
	}
	var v authority.Document
	if err = json.Unmarshal(raw, &v); err != nil {
		return err
	}
	return s.Verify(ctx, s.Control, v)
}

type literalSource struct{ text string }

func (s *literalSource) Next(ctx context.Context) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if s.text == "" {
		return "", io.EOF
	}
	r := []rune(s.text)
	n := min(len(r), MaxSlice)
	out := string(r[:n])
	s.text = string(r[n:])
	return out, nil
}
func (s *literalSource) Close() error { s.text = ""; return nil }

// Compile-time seam check; no production route or provider is registered.
var _ Facts = (*AuthorityFacts)(nil)
