package contentplan

import (
	c "astralive/backend/internal/contentplan/contract"
	"encoding/json"
	"math"
	"os"
	"strings"
	"testing"
	"time"
)

var at = time.Date(2026, 10, 16, 0, 0, 0, 0, time.UTC)

func input() Input {
	return Input{Run: c.BroadcastRun{TenantId: "tenant", OwnerId: "owner", RunId: "run"}, Snapshot: c.ProductSnapshot{ProductId: "product", Name: "纯棉上衣", Description: "面料采用纯棉。穿着柔软舒适。", Sizes: []string{"XL", "XXL", "2XL"}, SourceVersion: "v1"}, PlanID: "plan", Revision: 1}
}
func TestTrustedPlanStableIdentity(t *testing.T) {
	a, e := Build(input(), DefaultConfig(), at)
	if e != nil {
		t.Fatal(e)
	}
	b, e := Build(input(), DefaultConfig(), at.Add(time.Second))
	if e != nil {
		t.Fatal(e)
	}
	for i, s := range a.Segments {
		if s.SegmentId != b.Segments[i].SegmentId || s.TextHash != Hash(s.Content) || s.Sequence != int64(i+1) || s.State != "READY" || s.UtteranceId != nil || s.EstimatedDurationMs > 6000 {
			t.Fatal(s)
		}
	}
	in := input()
	in.PlanID = "plan_v2"
	in.Revision = 2
	x, e := Build(in, DefaultConfig(), at)
	if e != nil || x.Segments[0].SegmentId == a.Segments[0].SegmentId {
		t.Fatal("new revision reused identity", e)
	}
	if a.Plan.ProductSnapshotVersion == "" || a.Plan.ProductSnapshotVersion != b.Plan.ProductSnapshotVersion {
		t.Fatal("unstable snapshot")
	}
}
func TestNaturalAtomicText(t *testing.T) {
	for _, s := range []string{
		"目前价格为129.90元。", "规格为500毫升。", "尺码有 XL、XXL、2XL。", "型号是AB-2XL-Pro。", "长度20 cm，容量5 L。", "满199减20，活动以工具为准。", "不是纯棉，而是混纺。", "不是所有尺码都有货。", "这款不是纯棉。", "如果选择XL，就按尺码表选购。", "只有符合条件，才支持优惠。", "这款不包邮，请确认地址。", "型号为V2.5-Pro。", "价格129,990.50元，数量2件。",
	} {
		t.Run(s, func(t *testing.T) {
			p, e := DefaultConfig().Split(s)
			if e != nil {
				t.Fatal(e)
			}
			if len(p) != 1 || p[0] != s {
				t.Fatal(p)
			}
		})
	}
}
func TestShortJoinAndLongReject(t *testing.T) {
	cfg := DefaultConfig()
	parts, e := cfg.Split("纯棉面料。柔软舒适。尺码有 XL、XXL、2XL。")
	if e != nil {
		t.Fatal(e)
	}
	if parts[0] != "纯棉面料。柔软舒适。" {
		t.Fatal(parts)
	}
	_, e = cfg.Split(strings.Repeat("这是一段不可拆开的中文商品介绍", 4) + "。")
	if e == nil || !strings.Contains(e.Error(), "SEGMENT_TOO_LONG") {
		t.Fatal(e)
	}
	_, e = cfg.Split("如果选择这个型号。")
	if e == nil {
		t.Fatal("accepted incomplete condition")
	}
}
func TestDynamicClaimsFailClosed(t *testing.T) {
	for _, s := range []string{"售价129.90元。", "库存还有5件。", "今天优惠。", "可以包邮。"} {
		in := input()
		in.Statements = []Statement{{Text: s}}
		if _, e := Build(in, DefaultConfig(), at); e == nil {
			t.Fatal("unbound assertion", s)
		}
	}
}
func TestFactExpiryAndUnsupportedTools(t *testing.T) {
	f := c.FactDependency{Kind: "PRICE", ProductId: "product", SourceVersion: "v1", ValueHash: Hash("129.90"), ValidatedAt: Stamp(at), ExpiresAt: Stamp(at.Add(2 * time.Second))}
	in := input()
	in.Statements = []Statement{{Text: "售价129.90元。", Facts: []c.FactDependency{f}}}
	if _, e := Build(in, DefaultConfig(), at); e != nil {
		t.Fatal(e)
	}
	for _, delta := range []time.Duration{-time.Millisecond, 2 * time.Second, 3 * time.Second} {
		if e := Fresh(f, at.Add(delta)); e == nil {
			t.Fatal(delta)
		}
	}
	f.Kind = "SKU_STOCK"
	if e := Fresh(f, at); e == nil {
		t.Fatal("invented SKU authority")
	}
	f.Kind = "PRICE"
	f.ExpiresAt = Stamp(at.Add(3 * time.Second))
	if e := Fresh(f, at); e == nil {
		t.Fatal("overlong cache")
	}
}
func TestBundleRejectsTampering(t *testing.T) {
	for _, change := range []func(*c.PlanBundle){
		func(b *c.PlanBundle) { b.Segments[0].Content += "促销" }, func(b *c.PlanBundle) { b.Plan.ProductSnapshotVersion = "wrong" }, func(b *c.PlanBundle) { b.Segments[0].Sequence = 2 }, func(b *c.PlanBundle) { b.Segments[0].EstimatedDurationMs = 6001 }, func(b *c.PlanBundle) { b.Segments[0].RunId = "other" },
	} {
		b, e := Build(input(), DefaultConfig(), at)
		if e != nil {
			t.Fatal(e)
		}
		change(&b)
		if Validate(b) == nil {
			t.Fatal("accepted tampering")
		}
	}
}
func TestCanonicalGoldenVectors(t *testing.T) {
	raw, e := os.ReadFile("../../../contracts/v0.5/durable-live/examples/hash-vectors.json")
	if e != nil {
		t.Fatal(e)
	}
	var vectors []struct {
		Name                  string
		Value                 json.RawMessage
		CanonicalUtf8, Sha256 string
	}
	if e = json.Unmarshal(raw, &vectors); e != nil {
		t.Fatal(e)
	}
	for _, v := range vectors {
		t.Run(v.Name, func(t *testing.T) {
			var val any
			d := json.NewDecoder(strings.NewReader(string(v.Value)))
			d.UseNumber()
			if e := d.Decode(&val); e != nil {
				t.Fatal(e)
			}
			b, e := Canonical(val)
			if e != nil || string(b) != v.CanonicalUtf8 || Hash(string(b)) != v.Sha256 {
				t.Fatalf("canonical mismatch %s %v", b, e)
			}
		})
	}
}
func TestCanonicalLiteralUnicodeAndBackslashes(t *testing.T) {
	for _, s := range []string{"<>&/\u2028\u2029", `\u2028\u2029`, "汉字\n"} {
		b, e := Canonical(map[string]string{"text": s})
		if e != nil {
			t.Fatal(e)
		}
		var v map[string]string
		if e = json.Unmarshal(b, &v); e != nil || v["text"] != s {
			t.Fatalf("roundtrip: %q %s %v", s, b, e)
		}
	}
	if _, e := Canonical(1.25); e == nil {
		t.Fatal("float accepted")
	}
}

func TestLengthBudgetNeverCutsOrPadsFacts(t *testing.T) {
	in := input()
	in.Snapshot.Sizes = []string{}
	in.TargetLength = 2 * time.Second
	short, e := Build(in, DefaultConfig(), at)
	if e != nil {
		t.Fatal(e)
	}
	in.PlanID = "long"
	in.TargetLength = time.Minute
	long, e := Build(in, DefaultConfig(), at)
	if e != nil {
		t.Fatal(e)
	}
	if len(short.Segments) >= len(long.Segments) {
		t.Fatal("length budget ignored")
	}
	for _, seg := range short.Segments {
		if !strings.HasSuffix(seg.Content, "。") {
			t.Fatal("cut semantic sentence")
		}
	}
	if len(long.Segments) > 3 {
		t.Fatal("fabricated padding")
	}
}

func TestPlannerRejectsInvalidScalarShapes(t *testing.T) {
	for _, change := range []func(*Input){func(in *Input) { in.PlanID = "bad/id" }, func(in *Input) { in.Snapshot.Name = strings.Repeat("名", 2001) }, func(in *Input) { in.Snapshot.SourceVersion = "bad version" }, func(in *Input) { in.Revision = c.MaxInteger + 1 }} {
		in := input()
		in.Statements = []Statement{{Text: "纯棉面料。"}}
		change(&in)
		if _, e := Build(in, DefaultConfig(), at); e == nil {
			t.Fatal("invalid schema shape admitted")
		}
	}
	cfg := DefaultConfig()
	cfg.UnitsPerSecond = math.NaN()
	if cfg.Validate() == nil {
		t.Fatal("NaN rate")
	}
}
