package turnmanager

import (
	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"fmt"
	"sort"
	"time"
)

type State string

const (
	Idle             State = "IDLE"
	Explaining       State = "EXPLAINING"
	YieldPending     State = "YIELD_PENDING"
	Answering        State = "ANSWERING"
	Resuming         State = "RESUMING"
	OperatorOverride State = "OPERATOR_OVERRIDE"
	Recovering       State = "RECOVERING"
	Stopped          State = "STOPPED"
)

type Config struct {
	MaxConsecutiveAnswers                         int
	MaxAnswerOccupancy, MaxScriptWait, CommentTTL time.Duration
}

func DefaultConfig() Config { return Config{2, 8 * time.Second, 12 * time.Second, 20 * time.Second} }
func (c Config) Validate() error {
	if c.MaxConsecutiveAnswers < 1 || c.MaxConsecutiveAnswers > 2 || c.MaxAnswerOccupancy <= 0 || c.MaxAnswerOccupancy > 8*time.Second || c.MaxScriptWait <= 0 || c.MaxScriptWait >= c.CommentTTL || c.CommentTTL <= 6*time.Second {
		return fmt.Errorf("INVALID_ARGUMENT: turn budget (wait < ingress TTL)")
	}
	return nil
}

type Choice struct {
	State              State            `json:"state"`
	Source             string           `json:"source"`
	Reason             string           `json:"reason,omitempty"`
	Segment            *c.SpeechSegment `json:"segment,omitempty"`
	Comment            *c.Turn          `json:"comment,omitempty"`
	Current            *c.Turn          `json:"current,omitempty"`
	Pending            int              `json:"pending"`
	ConsecutiveAnswers int              `json:"consecutiveAnswers"`
	AnswerOccupancyMS  int64            `json:"answerOccupancyMs"`
}

func scopeTurn(t c.Turn, r c.BroadcastRun) bool {
	return t.RunId == r.RunId && t.TenantId == r.TenantId && t.OwnerId == r.OwnerId
}
func timestamp(s string) (time.Time, error) { return time.Parse(time.RFC3339Nano, s) }
func eligible(t c.Turn, s c.RestoreSnapshot, now time.Time) bool {
	if !scopeTurn(t, s.Run) || t.TurnType != "COMMENT" || t.PlanId == nil || s.Run.CurrentPlanId == nil || *t.PlanId != *s.Run.CurrentPlanId || (t.State != "READY" && t.State != "WAITING") || t.ExpiresAt == nil || len(t.SourceIdentities) == 0 {
		return false
	}
	expiry, e := timestamp(*t.ExpiresAt)
	return e == nil && now.Before(expiry)
}

// NextSegment verifies the contiguous prefix and never crosses an unresolved
// segment. Only an explicit, durable operator gap may change the resume cursor.
func NextSegment(s c.RestoreSnapshot, p Projection) (*c.SpeechSegment, error) {
	if s.Bundle == nil {
		return nil, nil
	}
	b := *s.Bundle
	if e := contentplan.Validate(b); e != nil {
		return nil, e
	}
	if b.Plan.RunId != s.Run.RunId || b.Plan.TenantId != s.Run.TenantId || b.Plan.OwnerId != s.Run.OwnerId || s.Run.CurrentPlanId == nil || *s.Run.CurrentPlanId != b.Plan.PlanId {
		return nil, fmt.Errorf("PLAN_CHANGED")
	}
	prefix := int64(0)
	for _, seg := range b.Segments {
		if seg.State != "COMPLETED" {
			break
		}
		prefix++
	}
	if prefix != s.CompletedPrefix {
		return nil, fmt.Errorf("RECOVERY_UNKNOWN: inconsistent prefix")
	}
	var next *c.SpeechSegment
	resume := int64(len(b.Segments) + 1)
	for i := int(prefix); i < len(b.Segments); i++ {
		seg := b.Segments[i]
		if seg.State == "COMPLETED" {
			return nil, fmt.Errorf("RECOVERY_UNKNOWN: noncontiguous completion")
		}
		if id := p.GapDecisions[seg.SegmentId]; id != "" {
			valid := false
			for _, d := range s.Decisions {
				if d.DecisionId == id && d.Action == "SKIP_WITH_GAP" && d.OperatorId != "" && d.AttemptId != "" {
					valid = true
				}
			}
			if !valid {
				return nil, fmt.Errorf("RECOVERY_UNKNOWN: invalid gap decision")
			}
			continue
		}
		resume = seg.Sequence
		if seg.State != "READY" {
			return nil, fmt.Errorf("RECOVERY_UNKNOWN: %s segment", seg.State)
		}
		next = &seg
		break
	}
	if s.ResumeSequence != resume {
		return nil, fmt.Errorf("RECOVERY_UNKNOWN: inconsistent resume cursor")
	}
	return next, nil
}
func Decide(s c.RestoreSnapshot, p Projection, cfg Config, now time.Time) (Choice, error) {
	out := Choice{State: Idle}
	if e := cfg.Validate(); e != nil {
		return out, e
	}
	r := s.Run
	if r.DesiredState == "STOPPED" || r.StopRevision > 0 || r.Status == "STOPPING" || r.Status == "STOPPED" || r.Status == "FAILED" {
		out.State = Stopped
		return out, nil
	}
	if !p.HistoryComplete || p.RunRevision != r.Revision {
		return Choice{State: Recovering, Reason: "CONSISTENT_POLICY_PROJECTION_REQUIRED"}, nil
	}
	if p.OperatorOverride {
		out.State = OperatorOverride
		return out, nil
	}
	if r.Status != "LIVE" || r.DesiredState != "LIVE" || r.RunEpoch < 1 || r.CurrentSessionId == nil || !p.ProviderReady {
		out.State = Recovering
		out.Reason = "RUN_OR_PROVIDER_NOT_READY"
		return out, nil
	}
	if s.Bundle != nil && s.Bundle.Plan.ProductSnapshotVersion != p.ProductSnapshotVersion {
		out.State = Recovering
		out.Reason = "PLAN_CHANGED"
		return out, nil
	}
	var comments []c.Turn
	for _, t := range p.Candidates {
		if eligible(t, s, now) {
			comments = append(comments, t)
		}
	}
	sort.SliceStable(comments, func(i, j int) bool {
		a, _ := timestamp(comments[i].ScheduledAt)
		b, _ := timestamp(comments[j].ScheduledAt)
		return a.Before(b)
	}) // no scoring/dedup: Scheduler owns that
	out.Pending = len(comments)
	for _, a := range s.UnresolvedAttempts {
		if a.RunEpoch != r.RunEpoch || a.LastCheckpoint == "UNKNOWN" {
			out.State = Recovering
			out.Reason = "UNRESOLVED_ATTEMPT"
			return out, nil
		}
	}
	if s.Slot.ActiveAttemptId != nil {
		out.State = Recovering
		for _, a := range s.UnresolvedAttempts {
			if a.AttemptId != *s.Slot.ActiveAttemptId {
				continue
			}
			for _, t := range p.History {
				if t.TurnId != a.TurnId || !scopeTurn(t, r) {
					continue
				}
				v := t
				out.Current = &v
				out.Source = t.TurnType
				switch t.TurnType {
				case "SCRIPT":
					out.State = Explaining
					if len(comments) > 0 {
						out.State = YieldPending
					}
				case "COMMENT":
					out.State = Answering
				default:
					out.State = OperatorOverride
				}
			}
		}
		return out, nil // ACTIVE slot is authoritative; never dispatch a second task
	}
	if len(s.UnresolvedAttempts) > 0 {
		return Choice{State: Recovering, Reason: "UNRESOLVED_ATTEMPT"}, nil
	}
	segment, e := NextSegment(s, p)
	if e != nil {
		return Choice{State: Recovering, Reason: e.Error()}, nil
	}
	out.Segment = segment
	// Read persisted terminal history. A fresh Manager after crash gets the same
	// fairness budget; it does not reset counters in local memory.
	history := append([]c.Turn{}, p.History...)
	sort.SliceStable(history, func(i, j int) bool { return finish(history[i]).After(finish(history[j])) })
	lastScript := time.Time{}
	if s.Bundle != nil {
		lastScript, _ = timestamp(s.Bundle.Plan.CreatedAt)
	}
	occupancy := time.Duration(0)
	for _, t := range history {
		if !scopeTurn(t, r) || t.PlanId == nil || r.CurrentPlanId == nil || *t.PlanId != *r.CurrentPlanId || t.FinishedAt == nil {
			continue
		}
		if t.TurnType == "SCRIPT" && t.State == "COMPLETED" {
			lastScript, _ = timestamp(*t.FinishedAt)
			break
		}
		if t.TurnType == "COMMENT" && t.StartedAt != nil && (t.State == "COMPLETED" || t.State == "INTERRUPTED") {
			st, e1 := timestamp(*t.StartedAt)
			end, e2 := timestamp(*t.FinishedAt)
			if e1 != nil || e2 != nil || end.Before(st) {
				return Choice{State: Recovering, Reason: "INVALID_HISTORY"}, nil
			}
			out.ConsecutiveAnswers++
			occupancy += end.Sub(st)
		}
	}
	out.AnswerOccupancyMS = occupancy.Milliseconds()
	scriptDue := segment != nil && (out.ConsecutiveAnswers >= cfg.MaxConsecutiveAnswers || occupancy >= cfg.MaxAnswerOccupancy || lastScript.IsZero() || now.Sub(lastScript) >= cfg.MaxScriptWait)
	if len(comments) > 0 && !scriptDue {
		v := comments[0]
		out.Comment = &v
		out.Source = "COMMENT"
		out.State = Answering
		return out, nil
	}
	if segment != nil {
		out.Source = "SCRIPT"
		out.State = Explaining
		if out.ConsecutiveAnswers > 0 {
			out.State = Resuming
		}
		return out, nil
	}
	return out, nil
}
func finish(t c.Turn) time.Time {
	if t.FinishedAt != nil {
		v, _ := timestamp(*t.FinishedAt)
		return v
	}
	return time.Time{}
}
