package contentplan

import (
	c "astralive/backend/internal/contentplan/contract"
	"encoding/json"
	"fmt"
	"regexp"
	"time"
	"unicode/utf8"
)

var idRE = regexp.MustCompile(c.IDPattern)
var hashRE = regexp.MustCompile(c.HashPattern)
var stampRE = regexp.MustCompile(c.TimestampPattern)

func ValidID(s string) bool { return idRE.MatchString(s) }
func validTime(s string) bool {
	if !stampRE.MatchString(s) {
		return false
	}
	_, e := time.Parse(time.RFC3339Nano, s)
	return e == nil
}
func textOK(s string) bool {
	return utf8.ValidString(s) && utf8.RuneCountInString(s) >= 1 && utf8.RuneCountInString(s) <= 2000
}
func factShape(f c.FactDependency) bool {
	return ValidID(f.ProductId) && ValidID(f.SourceVersion) && hashRE.MatchString(f.ValueHash) && validTime(f.ValidatedAt) && validTime(f.ExpiresAt)
}
func Fresh(f c.FactDependency, now time.Time) error {
	switch f.Kind {
	case "PRICE", "STOCK", "AVAILABILITY", "SIZE_OPTIONS":
	default:
		return fmt.Errorf("INVALID_ARGUMENT: unsupported authoritative Product Tool fact")
	}
	if !factShape(f) {
		return fmt.Errorf("INVALID_ARGUMENT: fact shape")
	}
	v, _ := time.Parse(time.RFC3339Nano, f.ValidatedAt)
	x, _ := time.Parse(time.RFC3339Nano, f.ExpiresAt)
	if v.After(now) || !now.Before(x) || x.After(v.Add(2*time.Second)) || now.Sub(v) >= 2*time.Second {
		return fmt.Errorf("PLAN_CHANGED: expired fact")
	}
	return nil
}
func Validate(b c.PlanBundle) error {
	p := b.Plan
	for _, id := range []string{p.PlanId, p.RunId, p.TenantId, p.OwnerId, p.ProductId, p.Snapshot.SourceVersion, p.GenerationSource.Reference} {
		if !ValidID(id) {
			return fmt.Errorf("INVALID_ARGUMENT: plan ID")
		}
	}
	for _, id := range []*string{p.GenerationSource.ModelVersion, p.GenerationSource.PromptVersion} {
		if id != nil && !ValidID(*id) {
			return fmt.Errorf("INVALID_ARGUMENT: generation version")
		}
	}
	if p.GenerationSource.Kind != "TEMPLATE" && p.GenerationSource.Kind != "OPERATOR" && p.GenerationSource.Kind != "LLM" {
		return fmt.Errorf("INVALID_ARGUMENT: generation kind")
	}
	if !validTime(p.CreatedAt) || !validTime(p.UpdatedAt) || p.ProductId != p.Snapshot.ProductId || p.Revision < 1 || p.Revision > c.MaxInteger || len(b.Segments) < 1 || len(b.Segments) > 1000 || len(p.SegmentOrder) != len(b.Segments) || !textOK(p.Snapshot.Name) || !textOK(p.Snapshot.Description) || p.Snapshot.Sizes == nil || len(p.Snapshot.Sizes) > 128 {
		return fmt.Errorf("INVALID_ARGUMENT: plan bundle")
	}
	for _, size := range p.Snapshot.Sizes {
		if !textOK(size) {
			return fmt.Errorf("INVALID_ARGUMENT: size")
		}
	}
	v, e := Version(p.Snapshot)
	if e != nil || v != p.ProductSnapshotVersion {
		return fmt.Errorf("PLAN_CHANGED: snapshot hash")
	}
	seen := map[string]bool{}
	states := map[string]bool{"READY": true, "ACTIVE": true, "COMPLETED": true, "INTERRUPTED": true, "UNKNOWN": true, "INVALIDATED": true}
	checkpoints := map[string]bool{"PLANNED": true, "DISPATCHED": true, "RUNTIME_ACCEPTED": true, "PLAYING": true, "LOCAL_MEDIA_DRAINED": true, "COMPLETED": true, "INTERRUPTED": true, "UNKNOWN": true}
	for i, s := range b.Segments {
		if s.TenantId != p.TenantId || s.OwnerId != p.OwnerId || s.RunId != p.RunId || s.PlanId != p.PlanId || s.Sequence != int64(i+1) || !ValidID(s.SegmentId) || p.SegmentOrder[i] != s.SegmentId || seen[s.SegmentId] || s.TextHash != Hash(s.Content) || s.IdempotencyKey != "segment:"+s.SegmentId+":initial" || !ValidID(s.IdempotencyKey) || s.EstimatedDurationMs < 1 || s.EstimatedDurationMs > 6000 || !textOK(s.Content) || s.FactDependencies == nil || len(s.FactDependencies) > 32 || !validTime(s.CreatedAt) || !validTime(s.UpdatedAt) || !states[s.State] || !checkpoints[s.CheckpointState] || s.UtteranceId != nil && !ValidID(*s.UtteranceId) {
			return fmt.Errorf("INVALID_ARGUMENT: segment bundle")
		}
		if (s.State == "COMPLETED" || s.State == "UNKNOWN" || s.State == "INTERRUPTED") && s.CheckpointState != s.State {
			return fmt.Errorf("RECOVERY_UNKNOWN: segment/checkpoint mismatch")
		}
		seen[s.SegmentId] = true
		for _, f := range s.FactDependencies {
			if f.ProductId != p.ProductId || f.SourceVersion != p.Snapshot.SourceVersion || !factShape(f) {
				return fmt.Errorf("PLAN_CHANGED: dependency")
			}
		}
	}
	raw, e := json.Marshal(b)
	if e != nil || len(raw) > 250*1024 {
		return fmt.Errorf("INVALID_ARGUMENT: plan request size")
	}
	return nil
}
