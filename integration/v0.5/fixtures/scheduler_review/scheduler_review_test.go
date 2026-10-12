// F-owned probes copied into an isolated C snapshot, never into the owner worktree.
package interaction

import (
	"context"
	"testing"
	"time"
)

func TestFContinuityBusySelectsBoundaryWithoutLegacyPreemption(t *testing.T) {
	s, _, d, gate := fixture(t)
	gate.Busy, gate.ContinuityActive, gate.ContinuityMaySuspend = true, true, true
	receive(t, s, event("f-boundary", "f-user", "多少钱？"))
	if err := s.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(d.items) != 1 || d.items[0].Policy != "AT_BOUNDARY" || s.Snapshot().Counters.Force != 0 {
		t.Fatal("expected one natural suspension and no FORCE", d.items, s.Snapshot())
	}
}

func TestFContinuityAnswerDefersButStillExpiresCandidates(t *testing.T) {
	s, now, d, gate := fixture(t)
	gate.Busy, gate.ContinuityActive = true, true
	receive(t, s, event("f-expiry", "f-user", "多少钱？"))
	if err := s.Tick(context.Background()); err != nil || len(d.items) != 0 {
		t.Fatal("answer recursively interrupted", err, d.items)
	}
	*now = now.Add(21 * time.Second)
	if err := s.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	snap := s.Snapshot()
	if snap.Candidates != 0 || snap.Counters.Expired != 1 || len(d.items) != 0 {
		t.Fatal("deferred candidate escaped TTL", snap, d.items)
	}
}

func TestFLegacyBusyGateStillDefersWithContinuityOff(t *testing.T) {
	s, _, d, gate := fixture(t)
	gate.Busy = true
	receive(t, s, event("f-legacy", "f-user", "多少钱？"))
	if err := s.Tick(context.Background()); err != nil || len(d.items) != 0 {
		t.Fatal("legacy busy admission changed", err, d.items)
	}
}

func TestFContinuityGateCannotOverrideProductSwitchOrOperator(t *testing.T) {
	t.Run("operator", func(t *testing.T) {
		s, _, d, gate := fixture(t)
		gate.Busy, gate.ContinuityActive, gate.ContinuityMaySuspend = true, true, true
		receive(t, s, event("f-operator", "f-user", "多少钱？"))
		if err := s.SetMode(OperatorOverride); err != nil {
			t.Fatal(err)
		}
		if err := s.Tick(context.Background()); err != nil || len(d.items) != 0 {
			t.Fatal("operator override ignored", err, d.items)
		}
	})
	t.Run("product", func(t *testing.T) {
		s, _, d, gate := fixture(t)
		gate.Busy, gate.ContinuityActive, gate.ContinuityMaySuspend = true, true, true
		receive(t, s, event("f-product", "f-user", "多少钱？"))
		gate.ProductID = "other-product"
		if err := s.Tick(context.Background()); err != nil || len(d.items) != 0 {
			t.Fatal("old product admitted", err, d.items)
		}
	})
}
