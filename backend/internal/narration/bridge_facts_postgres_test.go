package narration_test

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"astralive/backend/internal/durability"
	"astralive/backend/internal/narration"
)

// Actual PG/A admission/projection + child production Runtime executor READY.
// Boundary/epoch/bootstrap, TTS/avatar/sinks are labelled CPU fixtures, not GPU.
func TestPostgresNewResumeBridgeEmptyFactsCanonical(t *testing.T) {
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
	answer := narration.Segment{ID: "bridge-fixture-answer", Text: "当前价格是99元。", TextHash: narration.Hash("当前价格是99元。"), FactIDs: []string{"price"}, Lane: "AUDIENCE_ANSWER", Boundary: "SENTENCE_END", Status: "COMPLETED"}
	doc.Turn = &narration.Turn{ID: "bridge-empty-facts-turn", Status: "COMPLETED", Question: "多少钱？", QuestionHash: narration.Hash("多少钱？"), ProductHash: doc.Plan.ProductHash, Deadline: time.Now().Add(time.Minute), SourceIDs: []string{"fixture-comment"}, Answer: &answer, AnswerText: answer.Text, AnswerFacts: answer.FactIDs}
	doc.Resume = &narration.ResumePoint{Revision: doc.Revision, NextBeatID: doc.Plan.Segments[1].BeatID, NextSegmentID: doc.Plan.Segments[1].ID, Boundary: narration.Checkpoint{Identity: narration.Identity{TimelineEpoch: 1}}, Cursor: doc.Cursor}
	raw, _ := json.Marshal(doc)
	if _, err = p.Exec(ctx, `UPDATE v05_narrations SET state='ANSWERING',revision=$2,document_json=$1 WHERE session_id='s'`, raw, doc.Revision); err != nil {
		t.Fatal(err)
	}
	if _, err = p.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id='s' AND timeline_epoch=1; INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason,activated_at) SELECT session_id,run_epoch,3,tenant_id,user_id,'ACTIVE','bridge-fixture-epoch3',2,0,'controlled-bridge-boundary',clock_timestamp() FROM v05_session_runs WHERE session_id='s'; UPDATE v05_session_runs SET current_timeline_epoch=3 WHERE session_id='s'; UPDATE v05_outbox SET delivery_state='ACKED' WHERE session_id='s'`); err != nil {
		t.Fatal(err)
	}
	// An owned historical nil-fact row remains exactly JSON null; no trigger,
	// old row, descriptor or oracle is upgraded to make this new test pass.
	if _, err = p.Exec(ctx, `INSERT INTO v05_segments(segment_id,narration_id,session_id,tenant_id,user_id,beat_id,segment_ordinal,text_hash,fact_ids,text,product_version,status,document_json) SELECT 'legacy-nil-bridge',narration_id,session_id,tenant_id,user_id,'',1000000,'old-text-hash','null'::jsonb,'旧桥段。',$1,'PLANNED','{"factIds":null}' FROM v05_narrations WHERE session_id='s'`, doc.Plan.ProductVersion); err != nil {
		t.Fatal(err)
	}
	commandFor := func(kind, lane string) durability.Command {
		t.Helper()
		var raw []byte
		if err := p.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE command_type=$1 AND payload_envelope->>'lane'=$2 ORDER BY command_seq DESC LIMIT 1`, kind, lane).Scan(&raw); err != nil {
			t.Fatal(err)
		}
		var command durability.Command
		if err := json.Unmarshal(raw, &command); err != nil {
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
		if _, err := store.StartAttempt(ctx, "s", command.CommandID, "bridge-runtime-fixture", token); err != nil {
			t.Fatal(err)
		}
	}
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	prepared := commandFor("PREPARE_RESUME_BRIDGE", "RESUME_BRIDGE")
	start(prepared)
	record := durability.TimelineRecord{Command: prepared, Producer: "bridge-runtime-fixture", Operation: "RESUME_PREPARED", Proof: json.RawMessage(`{"choice":1}`)}
	if _, err = store.RecordTimeline(ctx, record); err != nil {
		t.Fatal(err)
	}
	snapshot, err := c.Snapshot(ctx, "s")
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.Bridge == nil || snapshot.Bridge.Text == "" {
		t.Fatal("expected spoken bridge")
	}
	var facts, segmentDocFacts, narrationDocFacts string
	if err = p.QueryRow(ctx, `SELECT fact_ids::text,document_json->'factIds' FROM v05_segments WHERE segment_id=$1`, snapshot.Bridge.ID).Scan(&facts, &segmentDocFacts); err != nil {
		t.Fatal(err)
	}
	if err = p.QueryRow(ctx, `SELECT document_json->'bridge'->'factIds' FROM v05_narrations WHERE session_id='s'`).Scan(&narrationDocFacts); err != nil {
		t.Fatal(err)
	}
	if facts != "[]" || segmentDocFacts != "[]" || narrationDocFacts != "[]" {
		t.Fatalf("new bridge empty facts are not canonical SQL=%s segmentDocument=%s narrationDocument=%s", facts, segmentDocFacts, narrationDocFacts)
	}
	if snapshot.Bridge.FactIDs == nil {
		t.Fatal("reloaded new bridge facts nil")
	}
	if _, err = store.RecordTimeline(ctx, record); err != nil {
		t.Fatal("exact prepared duplicate", err)
	}
	if _, err = p.Exec(ctx, `UPDATE v05_outbox SET delivery_state='ACKED' WHERE command_id=$1`, prepared.CommandID); err != nil {
		t.Fatal(err)
	}
	c = narration.New(store)
	if err = c.Drive(ctx, "s"); err != nil {
		t.Fatal(err)
	}
	bridge := commandFor("COMMIT_SEGMENT", "RESUME_BRIDGE")
	var payload map[string]json.RawMessage
	if err = json.Unmarshal(bridge.Payload, &payload); err != nil {
		t.Fatal(err)
	}
	if string(payload["factIds"]) != "[]" {
		t.Fatal("wire facts", string(payload["factIds"]))
	}
	start(bridge)
	_, generation, err := store.StartMedia(ctx, "s", bridge.CommandID, "bridge-runtime-fixture", 0)
	if err != nil {
		t.Fatal(err)
	}
	python := os.Getenv("NARRATION_TEST_PYTHON")
	if python == "" {
		python = os.Getenv("DURABILITY_TEST_PYTHON")
	}
	if python == "" {
		t.Fatal("set NARRATION_TEST_PYTHON for real CPU Runtime proof")
	}
	input, _ := json.Marshal(map[string]any{"command": bridge, "generation": generation})
	child := exec.Command(python, filepath.Join("..", "..", "..", "runtime", "tests", "narration_bridge_fact_proof.py"))
	child.Stdin = bytes.NewReader(input)
	output, err := child.CombinedOutput()
	if err != nil {
		t.Fatalf("CPU Runtime proof failed: %v %s", err, output)
	}
	var result struct {
		Scope string          `json:"scope"`
		Proof json.RawMessage `json:"proof"`
	}
	if err = json.Unmarshal(output, &result); err != nil {
		t.Fatal(err)
	}
	if result.Scope != "CPU_RUNTIME_READY_PROOF_NOT_NATIVE" {
		t.Fatal("unlabelled proof")
	}
	var ready struct {
		Descriptor map[string]json.RawMessage `json:"descriptor"`
	}
	if err = json.Unmarshal(result.Proof, &ready); err != nil {
		t.Fatal(err)
	}
	if string(ready.Descriptor["factIds"]) != "[]" {
		t.Fatal("Runtime READY fact IDs", string(ready.Descriptor["factIds"]))
	}
	readyRecord := durability.TimelineRecord{Command: bridge, Producer: "bridge-runtime-fixture", Operation: "SEGMENT_READY", Proof: result.Proof}
	if _, err = store.RecordTimeline(ctx, readyRecord); err != nil {
		t.Fatal("actual Runtime READY admission", err)
	}
	if _, err = store.RecordTimeline(ctx, readyRecord); err != nil {
		t.Fatal("exact READY duplicate", err)
	}
	var storedReady, oldFacts, narrationFacts, answerFacts string
	if err = p.QueryRow(ctx, `SELECT descriptor_json->'factIds' FROM v05_segment_attempts WHERE command_id=$1`, bridge.CommandID).Scan(&storedReady); err != nil {
		t.Fatal(err)
	}
	if err = p.QueryRow(ctx, `SELECT fact_ids::text FROM v05_segments WHERE segment_id='legacy-nil-bridge'`).Scan(&oldFacts); err != nil {
		t.Fatal(err)
	}
	if err = p.QueryRow(ctx, `SELECT fact_ids::text FROM v05_segments WHERE segment_id=$1`, doc.Plan.Segments[0].ID).Scan(&narrationFacts); err != nil {
		t.Fatal(err)
	}
	if err = p.QueryRow(ctx, `SELECT fact_ids::text FROM v05_segments WHERE segment_id=$1`, answer.ID).Scan(&answerFacts); err != nil {
		t.Fatal(err)
	}
	if storedReady != "[]" || oldFacts != "null" || narrationFacts != `["name"]` || answerFacts != `["price"]` {
		t.Fatal("canonical/legacy/nonempty proof boundary", storedReady, oldFacts, narrationFacts, answerFacts)
	}
	t.Log("actual PG bridge facts/segment document/narration document/COMMIT payload/child Runtime READY/duplicate/reload all []; historical nil remains null; nonempty facts unchanged; no physical GPU claim")
}
