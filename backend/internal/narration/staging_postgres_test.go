package narration_test

import (
	"astralive/backend/internal/narration"
	"encoding/json"
	"testing"
)

// Uses real owned PostgreSQL authority; no Runtime/provider/media side effects.
func TestPostgresCapturedStagingImmutableProfileAndSegmentMetadata(t *testing.T) {
	for _, mismatch := range []bool{false, true} {
		t.Run(map[bool]string{false: "capture", true: "restart-mismatch"}[mismatch], func(t *testing.T) {
			ctx, p, store, controller := setup(t)
			profile := "staging-short-1"
			settings := narration.StagingSettings{Enabled: true, LimitsRevision: &profile}
			tx, err := p.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			run, err := store.Current(ctx, tx, "s", false)
			if err != nil {
				t.Fatal(err)
			}
			_, err = store.Enqueue(ctx, tx, run, "BEGIN_RUN", "capture", "trace", "", map[string]any{"featureFlags": settings.Capture()})
			if err != nil {
				tx.Rollback(ctx)
				t.Fatal(err)
			}
			if err = tx.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			controller.StagingSettings = settings
			if mismatch {
				revision := "staging-segment-8s-1"
				gate := "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
				controller.StagingSettings = narration.StagingSettings{Enabled: true, LimitsRevision: &revision, ShortGateSHA256: &gate}
			}
			_, err = controller.Start(ctx, "s", "trace", plan())
			if mismatch {
				if err == nil {
					t.Fatal("restart reconfigured a captured profile")
				}
				var count int
				p.QueryRow(ctx, `SELECT count(*) FROM v05_narrations`).Scan(&count)
				if count != 0 {
					t.Fatal("mismatch committed business plan")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			var raw []byte
			if err = p.QueryRow(ctx, `SELECT payload_envelope->'payload' FROM v05_outbox WHERE command_type='COMMIT_SEGMENT'`).Scan(&raw); err != nil {
				t.Fatal(err)
			}
			var payload map[string]any
			json.Unmarshal(raw, &payload)
			if payload["maxDurationMs"] != float64(1920) || payload["beatId"] == "" || payload["beatId"] == nil || payload["interactionTurnId"] != nil {
				t.Fatal("immutable staging segment metadata missing")
			}
		})
	}
}
