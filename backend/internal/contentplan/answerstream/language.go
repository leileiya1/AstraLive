// Package answerstream implements a deliberately closed Chinese answer language.
// It is domain logic, not a wire DTO, general NLU classifier, or product authority.
package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

var (
	ErrUnsafe = errors.New("SEMANTIC_PROOF_UNAVAILABLE")
	ErrLimit  = errors.New("ANSWER_RESOURCE_LIMIT")
	ErrFacts  = errors.New("ANSWER_FACTS_INVALID")
)

const (
	MaxUnit          = 240
	MaxSlice         = 64
	MaxFrameBytes    = 16 * 1024
	MaxArtifactBytes = 64 * 1024 // leaves room within the 256KiB request envelope
	MaxUnits         = 32
	MaxAnswer        = 2000
	MaxRules         = 64
	MaxLanguageRunes = 8192
)

// Dependency is an internal trusted Product Tool projection, without wire tags.
// Text rules must be derived from the same value/version represented by Digest.
// A model's assertion or claimed dependency list must NEVER populate this input.
type Dependency struct {
	Kind, Product, Version, Digest string
	Verified, Expires              time.Time
}

// Rule is supplied by the trusted product projection adapter, not the LLM.
// Clause must be an entire tool-verified atomic/contrast/comparison assertion.
// WhenSize optionally wraps that assertion in an indivisible if/then rule.
// These are vocabulary entries, not arbitrary caller-issued "complete" flags.
type Rule struct {
	Clause       string
	WhenSize     string
	Dependencies []Dependency
}

type word struct {
	text  string
	facts []Dependency
}
type node struct {
	next   map[rune]*node
	accept *word
}
type Language struct {
	root    *node
	allowed []string
}

// AllowedTexts supplies the bounded, trusted vocabulary to an existing single
// LLM prompt. This does not generate text, grant TTS, or introduce another LLM.
func (l *Language) AllowedTexts() []string { return append([]string(nil), l.allowed...) }

// Closed predicate forms keep units, model identifiers, negation and comparisons
// inside one assertion. Exact tool vocabulary matching additionally verifies the
// values; matching a regex alone is NEVER sufficient for generated text.
var predicates = []struct {
	pattern *regexp.Regexp
	kind    string
}{
	{regexp.MustCompile(`^这款的价格是[0-9]+(?:\.[0-9]{1,2})?元$`), "PRICE"},
	// Existing FactAnswerResolver explicitly reports unknown currency. Keep its
	// exact spaces/text; an absent Tool currency must never silently become CNY.
	{regexp.MustCompile(`^这款目前价格是 [0-9]+(?:\.[0-9]+)?，币种信息暂不可用$`), "PRICE"},
	{regexp.MustCompile(`^这款(?:有|没有|目前没有) ?(?:S|M|L|XL|XXL|[2-9]XL)(?:(?:、|和)(?:S|M|L|XL|XXL|[2-9]XL))* ?尺码$`), "SIZE_OPTIONS"},
	{regexp.MustCompile(`^这款的库存是[0-9]+件$`), "STOCK"},
	{regexp.MustCompile(`^这款目前商品整体库存(?:还有|为) [0-9]+ 件$`), "STOCK"},
	{regexp.MustCompile(`^这款(?:暂时缺货|目前有货)$`), "AVAILABILITY"},
	{regexp.MustCompile(`^这款的型号是[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$`), "PRODUCT_DETAILS"},
	{regexp.MustCompile(`^这款的重量是[0-9]+(?:\.[0-9]+)?(?:g|kg|克|千克)$`), "PRODUCT_DETAILS"},
	{regexp.MustCompile(`^这款采用(?:纯棉|棉麻|羊毛|涤纶)面料$`), "PRODUCT_DETAILS"},
	{regexp.MustCompile(`^这款比(?:旧款|上一款)(?:(?:轻|重)[0-9]+(?:\.[0-9]+)?(?:g|kg)|(?:长|短)[0-9]+(?:\.[0-9]+)?(?:cm|mm))$`), "PRODUCT_DETAILS"},
	{regexp.MustCompile(`^这款比(?:旧款|上一款)便宜[0-9]+(?:\.[0-9]{1,2})?元$`), "PRICE"},
	{regexp.MustCompile(`^这款不是防水款，而是防泼水款$`), "PRODUCT_DETAILS"},
}
var size = regexp.MustCompile(`^(?:S|M|L|XL|XXL|[2-9]XL)$`)
var hashPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// NewLanguage compiles a bounded prefix trie of verified grammatical productions.
// Unsupported paraphrases fail closed; no punctuation/length fallback exists.
func NewLanguage(rules []Rule) (*Language, error) {
	if len(rules) > MaxRules {
		return nil, ErrLimit
	}
	l := &Language{root: &node{next: map[rune]*node{}}}
	total := 0
	insert := func(text string, deps []Dependency) error {
		n := l.root
		total += utf8.RuneCountInString(text)
		if total > MaxLanguageRunes || utf8.RuneCountInString(text) > MaxUnit {
			return ErrLimit
		}
		for _, r := range text {
			if n.accept != nil {
				return fmt.Errorf("%w: ambiguous prefix", ErrUnsafe)
			}
			if n.next[r] == nil {
				n.next[r] = &node{next: map[rune]*node{}}
			}
			n = n.next[r]
		}
		if n.accept != nil || len(n.next) != 0 {
			return fmt.Errorf("%w: duplicate/prefix", ErrUnsafe)
		}
		n.accept = &word{text, append([]Dependency(nil), deps...)}
		l.allowed = append(l.allowed, text)
		return nil
	}
	for _, rule := range rules {
		if len(rule.Clause) > 4*MaxUnit || utf8.RuneCountInString(rule.Clause) > MaxUnit {
			return nil, ErrLimit
		}
		if !utf8.ValidString(rule.Clause) {
			return nil, ErrUnsafe
		}
		kind := ""
		for _, p := range predicates {
			if p.pattern.MatchString(rule.Clause) {
				kind = p.kind
				break
			}
		}
		if kind == "" {
			return nil, fmt.Errorf("%w: unsupported predicate", ErrUnsafe)
		}
		deps := append([]Dependency(nil), rule.Dependencies...)
		if len(deps) == 0 || len(deps) > 32 {
			return nil, ErrFacts
		}
		sort.Slice(deps, func(i, j int) bool { return factKey(deps[i]) < factKey(deps[j]) })
		matched := false
		for i, d := range deps {
			if d.Kind == kind {
				matched = true
			}
			if !validDependency(d) || (i > 0 && factKey(deps[i-1]) == factKey(d)) {
				return nil, ErrFacts
			}
		}
		if !matched {
			return nil, ErrFacts
		}
		text := rule.Clause + "。"
		if rule.WhenSize != "" {
			// The antecedent is user preference, not an unverified product fact.
			// Require exact size membership, never substring XL inside XXL/2XL.
			if !size.MatchString(rule.WhenSize) || kind != "SIZE_OPTIONS" || !strings.HasPrefix(rule.Clause, "这款有") {
				return nil, ErrUnsafe
			}
			options := strings.TrimSuffix(strings.TrimPrefix(rule.Clause, "这款有"), "尺码")
			found := false
			for _, v := range strings.FieldsFunc(options, func(r rune) bool { return r == '、' || r == '和' }) {
				if strings.TrimSpace(v) == rule.WhenSize {
					found = true
				}
			}
			if !found {
				return nil, ErrUnsafe
			}
			text = "如果您需要" + rule.WhenSize + "尺码，那么" + text
		}
		if err := insert(text, deps); err != nil {
			return nil, err
		}
	}
	// Exhaustive non-product speech allowlist: empty dependencies never mean
	// arbitrary unclassified model assertions are safe.
	for _, text := range []string{"感谢您的提问。", "我来为您介绍。"} {
		if err := insert(text, nil); err != nil {
			return nil, err
		}
	}
	sort.Strings(l.allowed)
	return l, nil
}

func factKey(d Dependency) string { return d.Kind + "\x00" + d.Product }
func validDependency(d Dependency) bool {
	switch d.Kind {
	case "PRICE", "STOCK", "AVAILABILITY", "SIZE_OPTIONS", "PROMOTION", "DELIVERY", "SKU_STOCK", "PRODUCT_DETAILS":
	default:
		return false
	}
	return cp.ValidID(d.Product) && cp.ValidID(d.Version) && hashPattern.MatchString(d.Digest) &&
		!d.Verified.IsZero() && d.Expires.After(d.Verified) && d.Expires.Sub(d.Verified) <= 2*time.Second
}

// Unit can only be constructed by recognition of a complete production.
type Unit struct {
	text  string
	facts []Dependency
}

func (u Unit) Text() string               { return u.text }
func (u Unit) Dependencies() []Dependency { return append([]Dependency(nil), u.facts...) }
