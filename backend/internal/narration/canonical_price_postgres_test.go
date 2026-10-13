package narration_test

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"astralive/backend/internal/durability"
	"astralive/backend/internal/narration"
	"github.com/jackc/pgx/v5"
)

// Actual PG + production A admission/hash/receipt/projection transactions.
// Boundary state and sink receipts are controlled policy fixtures, not GPU,
// Runtime physical consumption or audience speech acceptance.
func TestPostgresCanonicalCNYPriceDecisionAndCoverage(t *testing.T) {
	for _, scenario := range []string{"success", "answer-wording", "duplicate", "rollback", "controller-reload", "flags-off", "USD", "qualifier", "extra-claim", "category", "custom-label", "multi-claim", "old-plan", "old-exact-plan", "partial", "UNKNOWN", "stale-epoch", "price-change", "currency-change", "Stop", "decision-conflict"} {
		t.Run(scenario, func(t *testing.T) {
			ctx, p, store, c := setup(t)
			if scenario != "flags-off" {
				revision := "staging-segment-8s-gpu1g-1"
				gate := "sha256:" + strings.Repeat("a", 64)
				c.StagingSettings = narration.StagingSettings{Enabled: true, LimitsRevision: &revision, ShortGateSHA256: &gate}
				tx, err := p.Begin(ctx)
				if err != nil {
					t.Fatal(err)
				}
				run, err := store.Current(ctx, tx, "s", false)
				if err != nil {
					t.Fatal(err)
				}
				_, err = store.Enqueue(ctx, tx, run, "BEGIN_RUN", "canonical-capture", "trace", "", map[string]any{"featureFlags": c.StagingSettings.Capture()})
				if err != nil {
					t.Fatal(err)
				}
				if err = tx.Commit(ctx); err != nil {
					t.Fatal(err)
				}
			}
			if scenario == "USD" {
				if _, err := p.Exec(ctx, `UPDATE products SET currency='USD' WHERE id='p'`); err != nil {
					t.Fatal(err)
				}
			}
			input := plan()
			input.Beats = input.Beats[:1]
			text := "本商品当前标价是人民币{{price}}元。"
			facts := []string{"price"}
			switch scenario {
			case "answer-wording":
				text = "这款目前价格是人民币{{price}}元。"
			case "qualifier":
				text = "本商品优惠标价是人民币{{price}}元。"
			case "extra-claim":
				text += "购买后保证有效。"
			case "category":
				text = "这份电子说明书，当前标价是人民币{{price}}元。"
			case "old-plan":
				text = "这款目前价格是 {{price}} CNY。"
			case "custom-label":
				facts = []string{"custom_price"}
			case "multi-claim":
				text += "库存{{stock}}份。"
				facts = []string{"price", "stock"}
			}
			input.Beats = append(input.Beats, narration.BeatInput{Title: "购买说明", RequiredFactIDs: facts, Statements: []narration.Statement{{Text: text, FactIDs: facts}}}, narration.BeatInput{Title: "下一项讲解内容", RequiredFactIDs: []string{}, Statements: []narration.Statement{{Text: "接下来继续讲解使用方法。", FactIDs: []string{}}}})
			doc, err := c.Start(ctx, "s", "trace", input)
			if err != nil {
				t.Fatal(err)
			}
			if scenario == "old-exact-plan" {
				// Reconstruct only this owned test's bootstrap rows in the legacy
				// typed JSON format: same captured staging, exact new pure wording,
				// but no historical private policy. No trigger is disabled/altered.
				legacyPlan, _ := json.Marshal(doc.Plan)
				legacyDoc, _ := json.Marshal(doc)
				if _, err = p.Exec(ctx, `DELETE FROM v05_segment_attempts WHERE session_id='s'; DELETE FROM v05_outbox WHERE session_id='s' AND command_type='COMMIT_SEGMENT'; DELETE FROM v05_segments WHERE session_id='s'; DELETE FROM v05_narrations WHERE session_id='s'`); err != nil {
					t.Fatal(err)
				}
				if _, err = p.Exec(ctx, `INSERT INTO v05_narrations(narration_id,session_id,tenant_id,user_id,run_epoch,revision,state,script_version,product_snapshot_hash,plan_json,document_json) SELECT $1,session_id,tenant_id,user_id,run_epoch,$2,$3,$4,$5,$6,$7 FROM v05_session_runs WHERE session_id='s'`, doc.Plan.ID, doc.Revision, doc.State, doc.Plan.ScriptVersion, doc.Plan.ProductHash, legacyPlan, legacyDoc); err != nil {
					t.Fatal(err)
				}
				for _, segment := range doc.Plan.Segments {
					segmentJSON, _ := json.Marshal(segment)
					factJSON, _ := json.Marshal(segment.FactIDs)
					if _, err = p.Exec(ctx, `INSERT INTO v05_segments(segment_id,narration_id,session_id,tenant_id,user_id,beat_id,segment_ordinal,text_hash,fact_ids,text,product_version,status,document_json) SELECT $1,narration_id,session_id,tenant_id,user_id,$3,$4,$5,$6,$7,$8,$9,$10 FROM v05_narrations WHERE narration_id=$2`, segment.ID, doc.Plan.ID, segment.BeatID, segment.Ordinal, segment.TextHash, factJSON, segment.Text, doc.Plan.ProductVersion, segment.Status, segmentJSON); err != nil {
						t.Fatal(err)
					}
				}
			}
			// Explicit completed first boundary, preceding suspend/epoch fixtures;
			// this does not claim physical media was played in this test.
			doc.Revision++
			doc.State = narration.Suspended
			doc.TimelineEpoch = 2
			doc.Plan.Segments[0].Status = "COMPLETED"
			doc.Cursor.NextOrdinal = 1
			doc.Cursor.CompletedSegments = []string{doc.Plan.Segments[0].ID}
			doc.Cursor.CompletedFacts = []string{"name"}
			doc.Turn = &narration.Turn{ID: "canonical-turn", Question: "多少钱？", QuestionHash: narration.Hash("多少钱？"), ProductHash: doc.Plan.ProductHash, Deadline: time.Now().Add(time.Minute), Status: "SUSPENDED", SourceIDs: []string{"fixture-comment"}}
			doc.Resume = &narration.ResumePoint{Revision: doc.Revision, NextBeatID: doc.Plan.Segments[1].BeatID, NextSegmentID: doc.Plan.Segments[1].ID, Boundary: narration.Checkpoint{Identity: narration.Identity{TimelineEpoch: 1}}, Cursor: doc.Cursor}
			raw, _ := json.Marshal(doc)
			if _, err = p.Exec(ctx, `UPDATE v05_narrations SET state='SUSPENDED',revision=$2,document_json=$1 WHERE session_id='s'`, raw, doc.Revision); err != nil {
				t.Fatal(err)
			}
			if _, err = p.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id='s' AND timeline_epoch=1; INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason,activated_at) SELECT session_id,run_epoch,2,tenant_id,user_id,'ACTIVE','canonical-fixture-epoch2',1,0,'policy-fixture',clock_timestamp() FROM v05_session_runs WHERE session_id='s'; UPDATE v05_session_runs SET current_timeline_epoch=2 WHERE session_id='s'; UPDATE v05_outbox SET delivery_state='ACKED' WHERE session_id='s'`); err != nil {
				t.Fatal(err)
			}
			if err = c.Drive(ctx, "s"); err != nil {
				t.Fatal(err)
			}
			commandFor := func(kind, lane string) durability.Command {
				t.Helper()
				var data []byte
				if err := p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_type=$1 AND ($2='' OR payload_envelope->>'lane'=$2) ORDER BY command_seq DESC LIMIT 1`, kind, lane).Scan(&data); err != nil {
					t.Fatal(err)
				}
				var command durability.Command
				if err := json.Unmarshal(data, &command); err != nil {
					t.Fatal(err)
				}
				return command
			}
			start := func(command durability.Command) {
				t.Helper()
				raw, _ := json.Marshal(command)
				if _, err := store.Accept(ctx, raw); err != nil {
					t.Fatal(err)
				}
				var token int64
				if err := p.QueryRow(ctx, `SELECT lease_token FROM v05_recovery_leases WHERE session_id='s'`).Scan(&token); err != nil {
					t.Fatal(err)
				}
				if _, err := store.StartAttempt(ctx, "s", command.CommandID, "canonical-runtime-fixture", token); err != nil {
					t.Fatal(err)
				}
			}
			record := func(command durability.Command, operation string, proof any) (json.RawMessage, error) {
				raw, _ := json.Marshal(proof)
				return store.RecordTimeline(ctx, durability.TimelineRecord{Command: command, Producer: "canonical-runtime-fixture", Operation: operation, Proof: raw})
			}
			prepared := commandFor("START_AUDIENCE_ANSWER", "")
			start(prepared)
			var payload struct {
				Text  string   `json:"answerText"`
				Facts []string `json:"factIds"`
			}
			json.Unmarshal(prepared.Payload, &payload)
			if _, err = record(prepared, "ANSWER_PREPARED", map[string]any{"text": payload.Text, "factIds": payload.Facts, "productSnapshotHash": doc.Plan.ProductHash}); err != nil {
				t.Fatal("prepared", err)
			}
			if _, err = p.Exec(ctx, `UPDATE v05_outbox SET delivery_state='ACKED' WHERE command_id=$1`, prepared.CommandID); err != nil {
				t.Fatal(err)
			}
			if scenario == "controller-reload" {
				settings := c.StagingSettings
				c = narration.New(store)
				c.StagingSettings = settings
			}
			answer := commandFor("COMMIT_SEGMENT", "AUDIENCE_ANSWER")
			start(answer)
			var metadata struct {
				Attempt   string `json:"attemptId"`
				Utterance string `json:"utteranceId"`
				Hash      string `json:"textHash"`
				Version   string `json:"factVersion"`
			}
			json.Unmarshal(answer.Payload, &metadata)
			_, generation, err := store.StartMedia(ctx, "s", answer.CommandID, "canonical-runtime-fixture", 0)
			if err != nil {
				t.Fatal(err)
			}
			descriptor := map[string]any{"sampleCount": 48000, "sourceSampleCount": 16000, "sourceSampleRate": 16000, "videoHash": "controlled-sink-video-fixture", "videoFrameCount": 25, "factIds": payload.Facts, "contentHash": "controlled-sink-pcm-fixture", "finalMarker": true, "requiredSinks": input.RequiredSinks, "utteranceId": metadata.Utterance, "textHash": metadata.Hash, "factVersion": metadata.Version}
			if _, err = record(answer, "SEGMENT_READY", map[string]any{"attemptId": metadata.Attempt, "generationId": generation, "descriptor": descriptor}); err != nil {
				t.Fatal("ready", err)
			}
			var segment string
			json.Unmarshal(answer.SegmentID, &segment)
			identity := durability.TimelineIdentity{SessionID: "s", RunEpoch: answer.RunEpoch, TimelineEpoch: 2, GenerationID: generation, SegmentID: segment, UtteranceID: metadata.Utterance, Lane: "AUDIENCE_ANSWER"}
			commit := map[string]any{"identity": identity, "attemptId": metadata.Attempt, "descriptor": descriptor, "start": 0, "end": 48000, "command": answer}
			if _, err = record(answer, "COMMIT_INTENT", map[string]any{"commit": commit, "revision": 0}); err != nil {
				t.Fatal("intent", err)
			}
			if _, err = record(answer, "COMMIT_INSTALLED", map[string]any{"commit": commit}); err != nil {
				t.Fatal("installed", err)
			}
			receipts := []durability.SinkReceipt{}
			for _, sink := range input.RequiredSinks {
				for _, medium := range []string{"audio", "video"} {
					receipts = append(receipts, durability.SinkReceipt{SinkID: sink, Media: medium, Start: 0, End: 48000, Final: true, Identity: identity, EvidenceType: "sink_consumed", EvidenceRef: "controlled-policy-fixture:" + sink + ":" + medium})
				}
			}
			finalPTS := int64(1000000)
			proof := map[string]any{"identity": identity, "finalPosition": durability.TimelinePosition{SessionID: "s", RunEpoch: answer.RunEpoch, TimelineEpoch: 2, SampleIndex: 48000, SampleRate: 48000, PTSUS: &finalPTS}, "sinkReceipts": receipts, "evidenceType": "sink_consumed", "audienceAudible": false}
			switch scenario {
			case "partial":
				proof["sinkReceipts"] = receipts[:1]
			case "stale-epoch":
				bad := identity
				bad.TimelineEpoch = 1
				proof["identity"] = bad
			case "price-change":
				if _, err = p.Exec(ctx, `UPDATE products SET price=9 WHERE id='p'`); err != nil {
					t.Fatal(err)
				}
			case "currency-change":
				if _, err = p.Exec(ctx, `UPDATE products SET currency='USD' WHERE id='p'`); err != nil {
					t.Fatal(err)
				}
			case "decision-conflict":
				if _, err = p.Exec(ctx, `UPDATE v05_interaction_turns SET document_json=jsonb_set(document_json,'{_cnyPriceCoverageDecision,answerTextHash}','"wrong"')`); err != nil {
					t.Fatal(err)
				}
			case "Stop":
				tx, er := p.Begin(ctx)
				if er != nil {
					t.Fatal(er)
				}
				run, er := store.Current(ctx, tx, "s", false)
				if er != nil {
					t.Fatal(er)
				}
				if er = c.Control(ctx, tx, run, "STOP_SESSION"); er != nil {
					t.Fatal(er)
				}
				if er = tx.Commit(ctx); er != nil {
					t.Fatal(er)
				}
			case "UNKNOWN":
				if _, err = record(answer, "UNKNOWN", map[string]any{"reason": "controlled-unknown"}); err != nil {
					t.Fatal(err)
				}
			}
			if scenario == "rollback" {
				original := store.TimelineProjection
				marker := errors.New("intentional projection rollback")
				store.TimelineProjection = func(ctx context.Context, tx pgx.Tx, command durability.Command, raw json.RawMessage) error {
					if err := original(ctx, tx, command, raw); err != nil {
						return err
					}
					return marker
				}
				if _, err = record(answer, "SEGMENT_COMPLETED", proof); !errors.Is(err, marker) {
					t.Fatal("missing atomic rollback", err)
				}
				var phase, play string
				p.QueryRow(ctx, `SELECT document_json->'_cnyPriceCoverageDecision'->>'phase' FROM v05_interaction_turns`).Scan(&phase)
				p.QueryRow(ctx, `SELECT play_state FROM v05_timeline_commits`).Scan(&play)
				if phase != "PREPARED" || play != "UNKNOWN" {
					t.Fatal("rollback leaked decision", phase, play)
				}
				store.TimelineProjection = original
			}
			ack, err := record(answer, "SEGMENT_COMPLETED", proof)
			invalid := scenario == "partial" || scenario == "stale-epoch" || scenario == "price-change" || scenario == "currency-change" || scenario == "Stop" || scenario == "decision-conflict" || scenario == "UNKNOWN"
			if invalid {
				if err == nil {
					t.Fatal("invalid completion accepted")
				}
			} else if err != nil {
				t.Fatal("completed", err)
			}
			if scenario == "duplicate" {
				again, er := record(answer, "SEGMENT_COMPLETED", proof)
				firstHash, _ := durability.Hash(ack)
				againHash, _ := durability.Hash(again)
				if er != nil || againHash != firstHash {
					t.Fatal("actual duplicate changed ACK", er)
				}
			}
			snapshot, err := c.Snapshot(ctx, "s")
			if err != nil {
				t.Fatal(err)
			}
			wantSkip := scenario == "success" || scenario == "answer-wording" || scenario == "duplicate" || scenario == "rollback" || scenario == "controller-reload"
			if (snapshot.Plan.Segments[1].Status == "SATISFIED_BY_ANSWER") != wantSkip {
				t.Fatal("unsafe coverage", snapshot.Plan.Segments[1].Status)
			}
			if wantSkip {
				if _, err = p.Exec(ctx, `UPDATE v05_narrations SET plan_json=plan_json-'_cnyPriceCoveragePolicy'`); err == nil {
					t.Fatal("immutable recorded policy could be removed")
				}
				if snapshot.Cursor.NextOrdinal != 2 || snapshot.Resume.NextSegmentID != snapshot.Plan.Segments[2].ID {
					t.Fatal("resume did not bypass completed price")
				}
				var decisionRaw []byte
				if err = p.QueryRow(ctx, `SELECT document_json->'_cnyPriceCoverageDecision' FROM v05_interaction_turns`).Scan(&decisionRaw); err != nil {
					t.Fatal(err)
				}
				var decision struct {
					Phase         string `json:"phase"`
					PreparedHash  string `json:"answerPreparedObservationHash"`
					CompletedHash string `json:"completionProofHash"`
				}
				json.Unmarshal(decisionRaw, &decision)
				var firstHash, finalHash string
				p.QueryRow(ctx, `SELECT observation_hash FROM v05_timeline_observations WHERE command_id=$1 AND operation='ANSWER_PREPARED'`, prepared.CommandID).Scan(&firstHash)
				p.QueryRow(ctx, `SELECT observation_hash FROM v05_timeline_observations WHERE command_id=$1 AND operation='SEGMENT_COMPLETED'`, answer.CommandID).Scan(&finalHash)
				if decision.Phase != "FULFILLED" || decision.PreparedHash != firstHash || decision.CompletedHash != finalHash || firstHash == "" || finalHash == "" {
					t.Fatal("private decision not bound to actual A hashes")
				}
				// An ordinary subsequent save/Stop must preserve only the reserved decision.
				tx, er := p.Begin(ctx)
				if er != nil {
					t.Fatal(er)
				}
				run, er := store.Current(ctx, tx, "s", false)
				if er != nil {
					t.Fatal(er)
				}
				if er = c.Control(ctx, tx, run, "STOP_SESSION"); er != nil {
					t.Fatal(er)
				}
				if er = tx.Commit(ctx); er != nil {
					t.Fatal(er)
				}
				var after []byte
				p.QueryRow(ctx, `SELECT document_json->'_cnyPriceCoverageDecision' FROM v05_interaction_turns`).Scan(&after)
				if string(after) != string(decisionRaw) {
					t.Fatal("save/Stop lost or recomputed durable decision")
				}
			}
		})
	}
}
