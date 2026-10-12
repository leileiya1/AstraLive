package narration_test

import (
	"astralive/backend/internal/durability"
	"astralive/backend/internal/narration"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

// Real PG policy/transaction tests with explicit Suspended document fixture;
// no native media/sink proof, Runtime authorization or acoustic claim.
func TestPostgresCapturedSpokenCNYAdmissionAndReceiptPolicy(t *testing.T) {
	for _, scenario := range []string{"success", "amount-forgery", "fact-forgery", "currency-change", "flags-off"} {
		t.Run(scenario, func(t *testing.T) {
			ctx, p, store, c := setup(t)
			if scenario != "flags-off" {
				revision := "staging-segment-8s-gpu1g-1"
				gate := "sha256:" + strings.Repeat("a", 64)
				c.StagingSettings = narration.StagingSettings{Enabled: true, LimitsRevision: &revision, ShortGateSHA256: &gate}
				tx, e := p.Begin(ctx)
				if e != nil {
					t.Fatal(e)
				}
				run, e := store.Current(ctx, tx, "s", false)
				if e != nil {
					t.Fatal(e)
				}
				_, e = store.Enqueue(ctx, tx, run, "BEGIN_RUN", "spoken-capture", "trace", "", map[string]any{"featureFlags": c.StagingSettings.Capture()})
				if e != nil {
					tx.Rollback(ctx)
					t.Fatal(e)
				}
				if e = tx.Commit(ctx); e != nil {
					t.Fatal(e)
				}
			}
			doc, e := c.Start(ctx, "s", "trace", plan())
			if e != nil {
				t.Fatal(e)
			}
			oldRevision := doc.Revision
			doc.Revision++
			doc.State = narration.Suspended
			doc.TimelineEpoch = 2
			doc.Turn = &narration.Turn{ID: "turn-spoken-fixture", Question: "多少钱？", QuestionHash: narration.Hash("多少钱？"), ProductHash: doc.Plan.ProductHash, Deadline: time.Now().Add(time.Minute), Status: "SUSPENDED", SourceIDs: []string{"comment-fixture"}}
			doc.Resume = &narration.ResumePoint{Revision: doc.Revision, NextBeatID: doc.Plan.Beats[0].ID, NextSegmentID: doc.Plan.Segments[0].ID, Boundary: narration.Checkpoint{Identity: narration.Identity{TimelineEpoch: 1}}}
			raw, _ := json.Marshal(doc)
			_, e = p.Exec(ctx, `UPDATE v05_narrations SET state='SUSPENDED',revision=$2,document_json=$1 WHERE session_id='s' AND revision=$3`, raw, doc.Revision, oldRevision)
			if e != nil {
				t.Fatal(e)
			}
			if _, e = p.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id='s' AND timeline_epoch=1; INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason,activated_at) SELECT session_id,run_epoch,2,tenant_id,user_id,'ACTIVE','policy-fixture-price-epoch2',1,0,'policy-fixture',clock_timestamp() FROM v05_session_runs WHERE session_id='s'; UPDATE v05_session_runs SET current_timeline_epoch=2 WHERE session_id='s'`); e != nil {
				t.Fatal(e)
			}
			// Explicit fixture assumption: earlier control/media admissions resolved.
			// This is policy-state setup, not an A execution or sink receipt.
			if _, e = p.Exec(ctx, `UPDATE v05_outbox SET delivery_state='ACKED' WHERE session_id='s'`); e != nil {
				t.Fatal(e)
			}
			if e = c.Drive(ctx, "s"); e != nil {
				t.Fatal(e)
			}
			var commandRaw []byte
			if e = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_type='START_AUDIENCE_ANSWER'`).Scan(&commandRaw); e != nil {
				t.Fatal(e)
			}
			var command durability.Command
			json.Unmarshal(commandRaw, &command)
			var payload map[string]any
			json.Unmarshal(command.Payload, &payload)
			want := "这款目前价格是人民币99.00元。"
			if scenario == "flags-off" {
				want = "这款目前价格是 99.00 CNY。"
			}
			if payload["answerText"] != want {
				t.Fatal("captured renderer wrong", payload["answerText"])
			}
			text := want
			if scenario == "amount-forgery" {
				text = "这款目前价格是人民币9.00元。"
			}
			if scenario == "fact-forgery" {
				payload["factIds"] = []string{"stock"}
				command.Payload, _ = json.Marshal(payload)
			}
			if scenario == "currency-change" {
				if _, e = p.Exec(ctx, `UPDATE products SET currency='USD' WHERE id='p'`); e != nil {
					t.Fatal(e)
				}
			}
			proof, _ := json.Marshal(map[string]any{"operation": "ANSWER_PREPARED", "proof": map[string]any{"text": text, "productSnapshotHash": doc.Plan.ProductHash, "factIds": []string{"price"}}})
			tx, e := p.Begin(ctx)
			if e != nil {
				t.Fatal(e)
			}
			defer tx.Rollback(ctx)
			e = c.Project(ctx, tx, command, proof)
			if scenario == "success" || scenario == "flags-off" {
				if e != nil {
					t.Fatal(e)
				}
				if e = tx.Commit(ctx); e != nil {
					t.Fatal(e)
				}
				var answerRaw []byte
				if e = p.QueryRow(ctx, `SELECT payload_envelope->'payload' FROM v05_outbox WHERE command_type='COMMIT_SEGMENT' AND payload_envelope->>'lane'='AUDIENCE_ANSWER'`).Scan(&answerRaw); e != nil {
					t.Fatal(e)
				}
				var answer map[string]any
				json.Unmarshal(answerRaw, &answer)
				if answer["text"] != want || answer["productSnapshotHash"] != doc.Plan.ProductHash || answer["factVersion"] != doc.Plan.ProductVersion {
					t.Fatal("version/amount changed")
				}
				if scenario == "success" && (answer["interactionTurnId"] != doc.Turn.ID || answer["maxDurationMs"] != float64(8000)) {
					t.Fatal("captured lane metadata changed")
				}
			} else {
				if !errors.Is(e, narration.ErrProduct) {
					t.Fatal("forged/stale proof accepted", e)
				}
				tx.Rollback(ctx)
				var count int
				p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='COMMIT_SEGMENT' AND payload_envelope->>'lane'='AUDIENCE_ANSWER'`).Scan(&count)
				if count != 0 {
					t.Fatal("rejected price published")
				}
			}
		})
	}
}
