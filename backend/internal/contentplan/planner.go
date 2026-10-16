package contentplan

import (
	c "astralive/backend/internal/contentplan/contract"
	"fmt"
	"math"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Statement must come from trusted Product Tools or an operator-approved
// generation stage. Arbitrary LLM output is not an approved fact source.
type Statement struct {
	Text  string
	Facts []c.FactDependency
}
type Input struct {
	Run          c.BroadcastRun
	Snapshot     c.ProductSnapshot
	PlanID       string // allocated once at ingress, reused on save retries
	Revision     int64
	Statements   []Statement
	Style        string
	TargetLength time.Duration // advisory; never repeat/invent facts to fill time
}
type Config struct {
	Target         time.Duration
	UnitsPerSecond float64
}

func DefaultConfig() Config { return Config{3 * time.Second, 5} }
func (cfg Config) Validate() error {
	if cfg.Target < 2*time.Second || cfg.Target > 4*time.Second || math.IsNaN(cfg.UnitsPerSecond) || math.IsInf(cfg.UnitsPerSecond, 0) || cfg.UnitsPerSecond < 2 || cfg.UnitsPerSecond > 10 {
		return fmt.Errorf("INVALID_ARGUMENT: planner configuration")
	}
	return nil
}

// Estimate is text-based guidance, never a media playback clock. ASCII letters
// and digits count individually to include spoken sizes/model numbers.
func (cfg Config) Estimate(s string) time.Duration {
	units := 0.0
	for _, r := range s {
		if unicode.IsSpace(r) {
			continue
		}
		if unicode.IsPunct(r) {
			units += 0.4
		} else {
			units++
		}
	}
	d := time.Duration(units / cfg.UnitsPerSecond * float64(time.Second))
	if d < time.Millisecond {
		d = time.Millisecond
	}
	return d
}
func hasAny(s string, words ...string) bool {
	for _, w := range words {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}
func dependent(s string) bool {
	return strings.Contains(s, "如果") && !hasAny(s, "就", "那么", "则") || strings.Contains(s, "只有") && !strings.Contains(s, "才")
}

// Split cuts only strong sentence boundaries, never commas, tokens or audio.
// Indivisible long sentences are rejected for upstream replanning.
func (cfg Config) Split(s string) ([]string, error) {
	if e := cfg.Validate(); e != nil {
		return nil, e
	}
	if !utf8.ValidString(s) || strings.TrimSpace(s) == "" {
		return nil, fmt.Errorf("INVALID_ARGUMENT: empty speech")
	}
	var parts []string
	rr := []rune(s)
	start, depth := 0, 0
	for i, r := range rr {
		switch r {
		case '“', '「', '（', '(':
			depth++
		case '”', '」', '）', ')':
			if depth > 0 {
				depth--
			}
		}
		boundary := strings.ContainsRune("。！？!?", r) || r == '.' && (i+1 == len(rr) || unicode.IsSpace(rr[i+1]))
		if boundary && depth == 0 {
			parts = append(parts, string(rr[start:i+1]))
			start = i + 1
		}
	}
	if start < len(rr) {
		parts = append(parts, string(rr[start:]))
	}
	var semantic []string
	for i := 0; i < len(parts); i++ {
		p := parts[i]
		if dependent(p) && i+1 < len(parts) {
			i++
			p += parts[i]
		}
		if dependent(p) {
			return nil, fmt.Errorf("INVALID_ARGUMENT: incomplete conditional assertion")
		}
		if strings.TrimSpace(p) == "" {
			if len(semantic) > 0 {
				semantic[len(semantic)-1] += p
			}
			continue
		}
		if cfg.Estimate(p) > 6*time.Second || utf8.RuneCountInString(p) > 2000 {
			return nil, fmt.Errorf("SEGMENT_TOO_LONG: replan complete sentence")
		}
		semantic = append(semantic, p)
	}
	var out []string
	for _, p := range semantic {
		if len(out) > 0 && cfg.Estimate(out[len(out)-1]) < 2*time.Second && cfg.Estimate(out[len(out)-1]+p) <= cfg.Target {
			out[len(out)-1] += p
		} else {
			out = append(out, p)
		}
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("INVALID_ARGUMENT: no speech")
	}
	return out, nil
}

var promotionToken = regexp.MustCompile(`满\s*[0-9]+(?:\.[0-9]+)?\s*减\s*[0-9]+`)

func dynamicKinds(s string) []string {
	var out []string
	for _, r := range []struct {
		kind  string
		words []string
	}{
		{"PRICE", []string{"价格", "售价", "元", "块钱", "￥", "¥", "$", "币种"}},
		{"STOCK", []string{"库存", "有货", "现货", "售罄", "缺货", "可售"}},
		{"PROMOTION", []string{"优惠", "满减", "折扣", "促销", "减免", "赠送"}},
		{"DELIVERY", []string{"包邮", "配送", "发货", "送达"}},
	} {
		if hasAny(s, r.words...) {
			out = append(out, r.kind)
		}
	}
	if promotionToken.MatchString(s) && !hasAny(s, "优惠", "满减", "折扣", "促销", "减免", "赠送") {
		out = append(out, "PROMOTION")
	}
	return out
}
func Build(in Input, cfg Config, now time.Time) (c.PlanBundle, error) {
	var empty c.PlanBundle
	if e := cfg.Validate(); e != nil {
		return empty, e
	}
	if in.Run.RunId == "" || in.Run.TenantId == "" || in.Run.OwnerId == "" || in.PlanID == "" || in.Revision < 1 || in.Snapshot.ProductId == "" || in.Snapshot.SourceVersion == "" || in.Snapshot.Name == "" || in.Snapshot.Description == "" || in.Snapshot.Sizes == nil || len(in.Snapshot.Sizes) > 128 {
		return empty, fmt.Errorf("INVALID_ARGUMENT: plan identity/snapshot")
	}
	if in.Style != "" && in.Style != "natural" && in.Style != "concise" || in.TargetLength < 0 {
		return empty, fmt.Errorf("INVALID_ARGUMENT: planner style/length")
	}
	if in.Style == "concise" {
		cfg.Target = 2 * time.Second
	}
	version, e := Version(in.Snapshot)
	if e != nil {
		return empty, e
	}
	statements := in.Statements
	if len(statements) == 0 {
		statements = []Statement{{Text: "这款商品是" + in.Snapshot.Name + "。"}, {Text: in.Snapshot.Description}}
		if len(in.Snapshot.Sizes) > 0 {
			statements = append(statements, Statement{Text: "尺码有 " + strings.Join(in.Snapshot.Sizes, "、") + "。", Facts: []c.FactDependency{{Kind: "SIZE_OPTIONS", ProductId: in.Snapshot.ProductId, SourceVersion: in.Snapshot.SourceVersion, ValueHash: Hash(strings.Join(in.Snapshot.Sizes, "、")), ValidatedAt: Stamp(now), ExpiresAt: Stamp(now.Add(2 * time.Second))}}})
		}
	}
	b := c.PlanBundle{Plan: c.ContentPlan{TenantId: in.Run.TenantId, OwnerId: in.Run.OwnerId, RunId: in.Run.RunId, PlanId: in.PlanID, ProductId: in.Snapshot.ProductId, ProductSnapshotVersion: version, Revision: in.Revision, SegmentOrder: []string{}, GenerationSource: c.GenerationSource{Kind: "TEMPLATE", Reference: "trusted-product-v1"}, Snapshot: in.Snapshot, CreatedAt: Stamp(now), UpdatedAt: Stamp(now)}, Segments: []c.SpeechSegment{}}
	for _, st := range statements {
		for _, kind := range dynamicKinds(st.Text) {
			found := false
			for _, f := range st.Facts {
				if f.Kind == kind {
					found = true
				}
			}
			if !found {
				return empty, fmt.Errorf("INVALID_ARGUMENT: undeclared dynamic %s", kind)
			}
		}
		for _, f := range st.Facts {
			if f.ProductId != in.Snapshot.ProductId || f.SourceVersion != in.Snapshot.SourceVersion || f.ValueHash == "" {
				return empty, fmt.Errorf("PLAN_CHANGED: fact scope")
			}
			if e := Fresh(f, now); e != nil {
				return empty, e
			}
		}
		parts, e := cfg.Split(st.Text)
		if e != nil {
			return empty, e
		}
		for _, p := range parts {
			seq := int64(len(b.Segments) + 1)
			identity, _ := Version([]any{"durable-live-1", in.PlanID, seq, p})
			id := "seg_" + identity
			s := c.SpeechSegment{TenantId: in.Run.TenantId, OwnerId: in.Run.OwnerId, RunId: in.Run.RunId, SegmentId: id, PlanId: in.PlanID, Sequence: seq, Content: p, TextHash: Hash(p), State: "READY", IdempotencyKey: "segment:" + id + ":initial", CheckpointState: "PLANNED", EstimatedDurationMs: cfg.Estimate(p).Milliseconds(), FactDependencies: append([]c.FactDependency{}, st.Facts...), CreatedAt: Stamp(now), UpdatedAt: Stamp(now)}
			b.Segments = append(b.Segments, s)
			b.Plan.SegmentOrder = append(b.Plan.SegmentOrder, id)
		}
	}
	// Honor a requested plan budget only at independently complete segment
	// boundaries. If one semantic unit exceeds the budget, keep that whole unit.
	// Insufficient trusted facts produce a shorter plan, never fabricated padding.
	if in.TargetLength > 0 {
		total := time.Duration(0)
		keep := 0
		for _, seg := range b.Segments {
			d := time.Duration(seg.EstimatedDurationMs) * time.Millisecond
			if keep > 0 && total+d > in.TargetLength {
				break
			}
			total += d
			keep++
		}
		b.Segments = b.Segments[:keep]
		b.Plan.SegmentOrder = b.Plan.SegmentOrder[:keep]
	}
	if e := Validate(b); e != nil {
		return empty, e
	}
	return b, nil
}
