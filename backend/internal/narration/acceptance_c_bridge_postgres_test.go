package narration_test

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"

	"astralive/backend/internal/durability"
	"astralive/backend/internal/narration"
)

// Real PG / original journal; boundary/answer completion is an explicit state
// fixture. This tests no-media bridge orchestration, not physical acceptance.
func TestPostgresAcceptanceCNoBridgeRestartDuplicate(t *testing.T) {
	ctx, p, store, c := setup(t)
	doc, err := c.Start(ctx, "s", "trace", plan())
	if err != nil {
		t.Fatal(err)
	}
	doc.State = narration.Answering
	doc.Revision++
	doc.TimelineEpoch = 3
	doc.Plan.Segments[0].Status = "COMPLETED"
	doc.Cursor.NextOrdinal = 1
	doc.Cursor.CompletedSegments = []string{doc.Plan.Segments[0].ID}
	doc.Cursor.CompletedFacts = []string{"name"}
	doc.Turn = &narration.Turn{ID: "acceptance-no-bridge-turn", Status: "COMPLETED", Question: "接着说吧？", QuestionHash: narration.Hash("接着说吧？"), ProductHash: doc.Plan.ProductHash, Deadline: time.Now().Add(time.Minute), SourceIDs: []string{"fixture-comment"}, AnswerText: "好的。"}
	doc.Resume = &narration.ResumePoint{Revision: doc.Revision, NextBeatID: doc.Plan.Segments[1].BeatID, NextSegmentID: doc.Plan.Segments[1].ID, Boundary: narration.Checkpoint{Identity: narration.Identity{TimelineEpoch: 1}}, Cursor: doc.Cursor}
	raw, _ := json.Marshal(doc)
	if _, err = p.Exec(ctx, `UPDATE v05_narrations SET state='ANSWERING',revision=$2,document_json=$1 WHERE session_id='s'`, raw, doc.Revision); err != nil {
		t.Fatal(err)
	}
	if _, err = p.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id='s' AND timeline_epoch=1; INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason,activated_at) SELECT session_id,run_epoch,3,tenant_id,user_id,'ACTIVE','no-bridge-fixture-epoch3',2,0,'controlled-no-bridge-boundary',clock_timestamp() FROM v05_session_runs WHERE session_id='s'; UPDATE v05_session_runs SET current_timeline_epoch=3 WHERE session_id='s'; UPDATE v05_outbox SET delivery_state='ACKED' WHERE session_id='s'`); err != nil {
		t.Fatal(err)
	}
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	var envelope []byte
	if err = p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_type='PREPARE_RESUME_BRIDGE'`).Scan(&envelope); err != nil {
		t.Fatal(err)
	}
	var command durability.Command
	if err = json.Unmarshal(envelope, &command); err != nil {
		t.Fatal(err)
	}
	if _, err = store.Accept(ctx, envelope); err != nil {
		t.Fatal(err)
	}
	var token int64
	if err = p.QueryRow(ctx, `SELECT lease_token FROM v05_recovery_leases WHERE session_id='s'`).Scan(&token); err != nil {
		t.Fatal(err)
	}
	if _, err = store.StartAttempt(ctx, "s", command.CommandID, "no-bridge-runtime-fixture", token); err != nil {
		t.Fatal(err)
	}
	record := durability.TimelineRecord{Command: command, Producer: "no-bridge-runtime-fixture", Operation: "RESUME_PREPARED", Proof: json.RawMessage(`{"choice":0}`)}
	original, err := store.RecordTimeline(ctx, record)
	if err != nil {
		t.Fatal(err)
	}
	snapshot, err := c.Snapshot(ctx, "s")
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.Bridge == nil || snapshot.Bridge.Text != "" || snapshot.Bridge.FactIDs == nil || len(snapshot.Bridge.FactIDs) != 0 || snapshot.State != narration.BridgeReady {
		t.Fatal("no-bridge facts/state", snapshot.Bridge, snapshot.State)
	}
	var count int
	if err = p.QueryRow(ctx, `SELECT count(*) FROM v05_segments WHERE document_json->>'lane'='RESUME_BRIDGE'`).Scan(&count); err != nil || count != 0 {
		t.Fatal("empty choice created segment", count, err)
	}
	if _, err = p.Exec(ctx, `UPDATE v05_outbox SET delivery_state='ACKED' WHERE command_id=$1`, command.CommandID); err != nil {
		t.Fatal(err)
	}
	// Restart only the Go controller, preserving actual durable state/identity.
	c = narration.New(store)
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	var bridgeCommands, nextCommands int
	var nextID string
	if err = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox WHERE command_type='COMMIT_SEGMENT' AND payload_envelope->>'lane'='RESUME_BRIDGE'`).Scan(&bridgeCommands); err != nil {
		t.Fatal(err)
	}
	if err = p.QueryRow(ctx, `SELECT count(*),min(payload_envelope->>'segmentId') FROM v05_outbox WHERE command_type='COMMIT_SEGMENT' AND payload_envelope->>'segmentId'=$1`, doc.Plan.Segments[1].ID).Scan(&nextCommands, &nextID); err != nil {
		t.Fatal(err)
	}
	if bridgeCommands != 0 || nextCommands != 1 || nextID != doc.Resume.NextSegmentID {
		t.Fatal("wrong or duplicate resume command", bridgeCommands, nextCommands, nextID)
	}
	again, err := store.RecordTimeline(ctx, record)
	var beforeValue, afterValue any
	_ = json.Unmarshal(original, &beforeValue)
	_ = json.Unmarshal(again, &afterValue)
	if err != nil || !reflect.DeepEqual(beforeValue, afterValue) {
		t.Fatal("exact preparation duplicate changed", err)
	}
	bad := record
	bad.Proof = json.RawMessage(`{"choice":1}`)
	if _, err = store.RecordTimeline(ctx, bad); err == nil {
		t.Fatal("changed same-command choice accepted")
	}
	final, err := c.Snapshot(ctx, "s")
	if err != nil {
		t.Fatal(err)
	}
	if final.Cursor.NextOrdinal != 1 || len(final.Cursor.CompletedFacts) != 1 || final.Cursor.CompletedFacts[0] != "name" {
		t.Fatal("empty bridge moved or satisfied facts", final.Cursor)
	}
	var facts string
	if err = p.QueryRow(ctx, `SELECT document_json->'bridge'->'factIds' FROM v05_narrations WHERE session_id='s'`).Scan(&facts); err != nil || facts != "[]" {
		t.Fatal("reloaded empty bridge facts changed", facts, err)
	}
	t.Log("no bridge: exact [] document, zero bridge segment/media, restart+duplicate same response, exactly one correct next narration, changed duplicate rejected, no fabricated fact completion")
}
