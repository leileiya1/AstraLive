package durability_test

import (
	"astralive/backend/internal/durability"
	"astralive/backend/internal/recovery"
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"sync"
	"testing"
)

func seedNarration(t *testing.T, ctx context.Context, p *pgxpool.Pool, s *durability.Store) durability.Run {
	t.Helper()
	r := run(t, ctx, p, s, "s")
	_, e := p.Exec(ctx, `INSERT INTO v05_narrations(narration_id,session_id,tenant_id,user_id,run_epoch,state,script_version,product_snapshot_hash,plan_json,document_json) VALUES('n','s','tenant','user',1,'PLANNING','script1','facts1','{"beats":["b1"]}','{"state":"PLANNING","narrationRevision":0,"cursor":{"nextOrdinal":0}}');
 INSERT INTO v05_segments(segment_id,narration_id,session_id,tenant_id,user_id,beat_id,segment_ordinal,text_hash,text,product_version,status) VALUES('seg1','n','s','tenant','user','b1',0,'text1','test','facts1','PLANNED'),('seg2','n','s','tenant','user','b1',1,'text2','test2','facts1','PLANNED');`)
	if e != nil {
		t.Fatal(e)
	}
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	if e = s.ConfigureTimelineOutput(ctx, tx, r, 16000, []string{"preview"}, []string{}); e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	return r
}
func mediaCommand(t *testing.T, ctx context.Context, p *pgxpool.Pool, s *durability.Store, r durability.Run, seg, attempt string, revision int64) durability.Command {
	t.Helper()
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	c, e := s.EnqueueNarration(ctx, tx, r, "COMMIT_SEGMENT", attempt, "trace", "", map[string]any{"attemptId": attempt, "utteranceId": "u" + seg, "leaseToken": r.Token, "expectedTimelineRevision": revision, "expectedNarrationRevision": 0, "text": "test", "factVersion": "facts1", "textHash": "text1", "requiredSinks": []string{"preview"}}, durability.MediaMetadata{NarrationID: "n", SegmentID: seg, TimelineEpoch: r.TimelineEpoch, Lane: "NARRATION"})
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	return c
}
func acceptStart(t *testing.T, ctx context.Context, s *durability.Store, c durability.Command, token int64) {
	t.Helper()
	raw, _ := json.Marshal(c)
	if _, e := s.Accept(ctx, raw); e != nil {
		t.Fatal(e)
	}
	if _, e := s.StartAttempt(ctx, c.SessionID, c.CommandID, "runtime", token); e != nil {
		t.Fatal(e)
	}
}
func record(t *testing.T, ctx context.Context, s *durability.Store, c durability.Command, op string, proof any) json.RawMessage {
	t.Helper()
	raw, _ := json.Marshal(proof)
	out, e := s.RecordTimeline(ctx, durability.TimelineRecord{Command: c, Producer: "runtime", Operation: op, Proof: raw})
	if e != nil {
		t.Fatalf("%s: %v", op, e)
	}
	return out
}
func TestContinuityProofAndCursorAtomic(t *testing.T) {
	ctx, p, s := pg(t)
	r := seedNarration(t, ctx, p, s)
	c := mediaCommand(t, ctx, p, s, r, "seg1", "a1", 0)
	acceptStart(t, ctx, s, c, r.Token)
	_, generation, e := s.StartMedia(ctx, "s", c.CommandID, "runtime", 0)
	if e != nil {
		t.Fatal(e)
	}
	descriptor := map[string]any{"sampleCount": 640, "contentHash": "fixture-pcm-hash", "finalMarker": true, "requiredSinks": []string{"preview"}, "utteranceId": "useg1", "textHash": "text1", "factVersion": "facts1"}
	record(t, ctx, s, c, "SEGMENT_READY", map[string]any{"attemptId": "a1", "generationId": generation, "descriptor": descriptor})
	identity := durability.TimelineIdentity{SessionID: "s", RunEpoch: 1, TimelineEpoch: 1, GenerationID: generation, SegmentID: "seg1", UtteranceID: "useg1", Lane: "NARRATION"}
	commit := map[string]any{"identity": identity, "attemptId": "a1", "descriptor": descriptor, "start": 0, "end": 640, "command": c, "consumed": map[string]any{}, "completed": false, "completion_proof": nil}
	intent := record(t, ctx, s, c, "COMMIT_INTENT", map[string]any{"commit": commit, "revision": 0})
	var state string
	var cursor int64
	_ = p.QueryRow(ctx, `SELECT status FROM v05_timeline_commits WHERE command_id=$1`, c.CommandID).Scan(&state)
	_ = p.QueryRow(ctx, `SELECT current_committed_sample FROM v05_session_runs WHERE session_id='s'`).Scan(&cursor)
	if state != "PENDING_INSTALL" || cursor != 0 {
		t.Fatalf("intent exposed media: %s %d %s", state, cursor, intent)
	}
	record(t, ctx, s, c, "COMMIT_INSTALLED", map[string]any{"commit": commit})
	receipts := []durability.SinkReceipt{}
	for _, media := range []string{"audio", "video"} {
		receipts = append(receipts, durability.SinkReceipt{SinkID: "preview", Media: media, Start: 0, End: 640, Final: true, Identity: identity, EvidenceType: "sink_consumed", EvidenceRef: "fixture-observation:" + media})
	}
	proof := map[string]any{"identity": identity, "finalPosition": durability.TimelinePosition{SessionID: "s", RunEpoch: 1, TimelineEpoch: 1, SampleIndex: 640, SampleRate: 16000}, "sinkReceipts": receipts, "evidenceType": "sink_consumed", "audienceAudible": false}
	raw, _ := json.Marshal(proof)
	request := durability.TimelineRecord{Command: c, Producer: "runtime", Operation: "SEGMENT_COMPLETED", Proof: raw}
	for _, kind := range []string{"missing-video", "gap", "wrong-generation"} {
		broken := append([]durability.SinkReceipt{}, receipts...)
		switch kind {
		case "missing-video":
			broken = broken[:1]
		case "gap":
			broken[1].Start = 1
		case "wrong-generation":
			broken[1].Identity.GenerationID++
		}
		proof["sinkReceipts"] = broken
		bad, _ := json.Marshal(proof)
		if _, err := s.RecordTimeline(ctx, durability.TimelineRecord{Command: c, Producer: "runtime", Operation: "SEGMENT_COMPLETED", Proof: bad}); !errors.Is(err, durability.ErrConflict) {
			t.Fatalf("invalid %s proof: %v", kind, err)
		}
	}
	proof["sinkReceipts"] = receipts
	if _, e = s.RecordTimeline(ctx, request); !errors.Is(e, durability.ErrProjectionUnavailable) {
		t.Fatalf("completed without C projection: %v", e)
	}
	calls := 0
	rollback := errors.New("injected after cursor CAS")
	s.TimelineProjection = func(ctx context.Context, tx pgx.Tx, _ durability.Command, _ json.RawMessage) error {
		calls++
		_, e := tx.Exec(ctx, `UPDATE v05_narrations SET revision=revision+1,completion_cursor_json='{"nextOrdinal":1}',document_json=jsonb_set(document_json,'{cursor}','{"nextOrdinal":1}') WHERE narration_id='n' AND revision=0`)
		if e != nil {
			return e
		}
		rr, er := s.Current(ctx, tx, "s", false)
		if er != nil {
			return er
		}
		_, er = s.EnqueueNarration(ctx, tx, rr, "COMMIT_SEGMENT", "rolled-back-next", "trace", "", map[string]any{"attemptId": "rolled-back-a2", "utteranceId": "useg2", "leaseToken": rr.Token, "expectedTimelineRevision": 1}, durability.MediaMetadata{NarrationID: "n", SegmentID: "seg2", TimelineEpoch: 1, Lane: "NARRATION"})
		if er != nil {
			return er
		}
		return rollback
	}
	if _, e = s.RecordTimeline(ctx, request); !errors.Is(e, rollback) {
		t.Fatal(e)
	}
	var revision int64
	var next int
	_ = p.QueryRow(ctx, `SELECT revision,COALESCE((completion_cursor_json->>'nextOrdinal')::int,0) FROM v05_narrations WHERE narration_id='n'`).Scan(&revision, &next)
	_ = p.QueryRow(ctx, `SELECT play_state FROM v05_timeline_commits WHERE command_id=$1`, c.CommandID).Scan(&state)
	if revision != 0 || next != 0 || state != "UNKNOWN" {
		t.Fatalf("proof/cursor rollback escaped: %d %d %s", revision, next, state)
	}
	var outboxCount int
	_ = p.QueryRow(ctx, `SELECT count(*) FROM v05_outbox`).Scan(&outboxCount)
	if outboxCount != 1 {
		t.Fatalf("projection outbox escaped rollback: %d", outboxCount)
	}
	calls = 0
	s.TimelineProjection = func(ctx context.Context, tx pgx.Tx, _ durability.Command, raw json.RawMessage) error {
		calls++
		var operation struct {
			Operation string `json:"operation"`
		}
		_ = json.Unmarshal(raw, &operation)
		if operation.Operation != "SEGMENT_COMPLETED" {
			t.Fatal(operation.Operation)
		}
		tag, e := tx.Exec(ctx, `UPDATE v05_narrations SET revision=revision+1,completion_cursor_json='{"nextOrdinal":1}',document_json=document_json || '{"narrationRevision":1,"cursor":{"nextOrdinal":1}}' WHERE narration_id='n' AND revision=0`)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return durability.ErrConflict
		}
		return nil
	}
	first, e := s.RecordTimeline(ctx, request)
	if e != nil {
		t.Fatal(e)
	}
	again, e := s.RecordTimeline(ctx, request)
	if e != nil || !equalJSONTest(first, again) || calls != 1 {
		t.Fatalf("replayed cursor: %s %s %d %v", first, again, calls, e)
	}
	proof["sinkReceipts"] = receipts[:1]
	request.Proof, _ = json.Marshal(proof)
	if _, e = s.RecordTimeline(ctx, request); !errors.Is(e, durability.ErrConflict) {
		t.Fatalf("changed proof accepted: %v", e)
	}
	_ = p.QueryRow(ctx, `SELECT revision FROM v05_narrations WHERE narration_id='n'`).Scan(&revision)
	if revision != 1 {
		t.Fatal(revision)
	}
	// The database interval trigger also rejects direct repository overlap under the run lock.
	c2 := mediaCommand(t, ctx, p, s, r, "seg2", "a2", 1)
	_, e = p.Exec(ctx, `INSERT INTO v05_timeline_commits SELECT session_id,run_epoch,timeline_epoch,'seg2','a2',tenant_id,user_id,$1,generation_id,100,500,sample_rate,identity_json,descriptor_json,required_sinks,optional_sinks,'PENDING_INSTALL','UNKNOWN','[]',NULL,clock_timestamp(),NULL,NULL FROM v05_timeline_commits WHERE command_id=$2`, c2.CommandID, c.CommandID)
	if e == nil {
		t.Fatal("database accepted overlapping run interval")
	}
	if _, err := p.Exec(ctx, `UPDATE v05_narrations SET plan_json='{"altered":true}',revision=revision+1 WHERE narration_id='n'`); err == nil {
		t.Fatal("captured plan changed")
	}
	if _, err := p.Exec(ctx, `UPDATE v05_segments SET text='tampered' WHERE segment_id='seg1'`); err == nil {
		t.Fatal("captured segment changed")
	}
	tx, er := p.Begin(ctx)
	if er != nil {
		t.Fatal(er)
	}
	control, er := s.Enqueue(ctx, tx, r, "FORCE_INTERRUPT", "force", "trace", "", map[string]any{})
	if er != nil {
		t.Fatal(er)
	}
	if er = s.Barrier(ctx, tx, control); er != nil {
		t.Fatal(er)
	}
	if er = tx.Commit(ctx); er != nil {
		t.Fatal(er)
	}
	request.Proof = raw
	if _, er = s.RecordTimeline(ctx, request); !errors.Is(er, durability.ErrFence) {
		t.Fatalf("old durable ACK bypassed FORCE barrier: %v", er)
	}
	tx, er = p.Begin(ctx)
	if er != nil {
		t.Fatal(er)
	}
	if er = s.Seal(ctx, tx, r); er != nil {
		t.Fatal(er)
	}
	if er = tx.Commit(ctx); er != nil {
		t.Fatal(er)
	}
	var cursorRaw []byte
	var narrationState string
	var barrier bool
	_ = p.QueryRow(ctx, `SELECT state,stop_barrier,completion_cursor_json FROM v05_narrations WHERE narration_id='n'`).Scan(&narrationState, &barrier, &cursorRaw)
	if narrationState != "STOPPING" || !barrier || !equalJSONTest(cursorRaw, []byte(`{"nextOrdinal":1}`)) {
		t.Fatalf("Stop lost cursor/tombstone: %s %t %s", narrationState, barrier, cursorRaw)
	}
	request.Proof = raw
	if _, er = s.RecordTimeline(ctx, request); !errors.Is(er, durability.ErrFence) {
		t.Fatalf("Stop allowed late proof mutation: %v", er)
	}
}
func equalJSONTest(a, b []byte) bool {
	ha, ea := durability.EventHash(a)
	hb, eb := durability.EventHash(b)
	return ea == nil && eb == nil && ha == hb
}
func TestPreparedEpochTokenAndActivation(t *testing.T) {
	ctx, p, s := pg(t)
	r := seedNarration(t, ctx, p, s)
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	reservation, e := s.ReserveTimelineEpoch(ctx, tx, r, 1, 0, "answer")
	if e != nil {
		t.Fatal(e)
	}
	origin := durability.TimelinePosition{SessionID: "s", RunEpoch: 1, TimelineEpoch: 1, SampleIndex: 0, SampleRate: 16000}
	payload := map[string]any{"leaseToken": r.Token, "expectedTimelineRevision": 0, "expectedNarrationRevision": 0, "expectedPreviousEpoch": 1, "newEpoch": 2, "reservationToken": reservation.ReservationToken, "originPosition": origin, "reason": "answer"}
	c, e := s.EnqueueNarration(ctx, tx, r, "BEGIN_EPOCH", "epoch2", "trace", "", payload, durability.MediaMetadata{NarrationID: "n", TimelineEpoch: 2, Lane: "NARRATION"})
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	tx, e = p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.EnqueueNarration(ctx, tx, r, "COMMIT_SEGMENT", "future", "trace", "", map[string]any{"attemptId": "bad", "utteranceId": "u"}, durability.MediaMetadata{NarrationID: "n", SegmentID: "seg1", TimelineEpoch: 2, Lane: "NARRATION"})
	_ = tx.Rollback(ctx)
	if !errors.Is(e, durability.ErrFence) {
		t.Fatalf("ordinary future epoch accepted: %v", e)
	}
	// A different command cannot use a guessed reservation token.
	tx, e = p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	wrong := map[string]any{}
	for k, v := range payload {
		wrong[k] = v
	}
	wrong["reservationToken"] = "wrong-token"
	_, e = s.EnqueueNarration(ctx, tx, r, "BEGIN_EPOCH", "bad-token", "trace", "", wrong, durability.MediaMetadata{NarrationID: "n", TimelineEpoch: 2, Lane: "NARRATION"})
	_ = tx.Rollback(ctx)
	if !errors.Is(e, durability.ErrFence) {
		t.Fatalf("guessed reservation accepted: %v", e)
	}
	acceptStart(t, ctx, s, c, r.Token)
	proof := map[string]any{"expectedPreviousEpoch": 1, "newEpoch": 2, "originPosition": origin, "reason": "answer"}
	record(t, ctx, s, c, "BEGIN_EPOCH_PREPARED", proof)
	var current int64
	_ = p.QueryRow(ctx, `SELECT current_timeline_epoch FROM v05_session_runs WHERE session_id='s'`).Scan(&current)
	if current != 1 {
		t.Fatal("PREPARED activated media")
	}
	record(t, ctx, s, c, "BEGIN_EPOCH_ACTIVE", proof)
	_ = p.QueryRow(ctx, `SELECT current_timeline_epoch FROM v05_session_runs WHERE session_id='s'`).Scan(&current)
	if current != 2 {
		t.Fatal(current)
	}
	record(t, ctx, s, c, "BEGIN_EPOCH_ACTIVE", proof) // same immutable proof has a stable result
	envelope, _ := json.Marshal(c)
	if receipt, err := s.Accept(ctx, envelope); err != nil || receipt.Execute || receipt.ExecutionState != "TERMINAL" {
		t.Fatalf("terminal epoch command replay changed: %+v %v", receipt, err)
	}
	tx, e = p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.ReserveTimelineEpoch(ctx, tx, r, 1, 0, "stale"); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("stale reservation accepted: %v", e)
	}
	_ = tx.Rollback(ctx)
}

func TestNarrationAdmissionTransactionAndIdempotency(t *testing.T) {
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	var first durability.Command
	for _, commit := range []bool{false, true} {
		tx, e := p.Begin(ctx)
		if e != nil {
			t.Fatal(e)
		}
		_, e = tx.Exec(ctx, `INSERT INTO v05_narrations(narration_id,session_id,tenant_id,user_id,run_epoch,state,script_version,product_snapshot_hash,plan_json) VALUES('n','s','tenant','user',1,'PLANNING','v1','hash','{}');
  INSERT INTO v05_segments(segment_id,narration_id,session_id,tenant_id,user_id,beat_id,segment_ordinal,text_hash,text,product_version,status) VALUES('seg1','n','s','tenant','user','b1',0,'text1','test','v1','PLANNED');
  INSERT INTO v05_interaction_turns(turn_id,narration_id,session_id,tenant_id,user_id,source_ids,question_hash,question,deadline,state) VALUES('turn','n','s','tenant','user','[]','qhash','question',clock_timestamp()+interval '10 seconds','SELECTED');
  UPDATE v05_narrations SET revision=2,completion_cursor_json='{"nextOrdinal":0}',document_json='{"narrationRevision":2}' WHERE narration_id='n' AND revision=0;`)
		if e != nil {
			t.Fatal(e)
		}
		c, e := s.EnqueueNarration(ctx, tx, r, "COMMIT_SEGMENT", "logical1", "trace", "", map[string]any{"attemptId": "a1", "utteranceId": "u1", "leaseToken": 1, "expectedTimelineRevision": 0}, durability.MediaMetadata{NarrationID: "n", SegmentID: "seg1", TimelineEpoch: 1, Lane: "NARRATION"})
		if e != nil {
			t.Fatal(e)
		}
		if commit {
			first = c
			e = tx.Commit(ctx)
		} else {
			e = tx.Rollback(ctx)
		}
		if e != nil {
			t.Fatal(e)
		}
		var count int
		e = p.QueryRow(ctx, `SELECT (SELECT count(*) FROM v05_narrations)+(SELECT count(*) FROM v05_segments)+(SELECT count(*) FROM v05_interaction_turns)+(SELECT count(*) FROM v05_outbox)+(SELECT count(*) FROM v05_segment_attempts)`).Scan(&count)
		if e != nil {
			t.Fatal(e)
		}
		expected := 0
		if commit {
			expected = 5
		}
		if count != expected {
			t.Fatalf("split admission: %d != %d", count, expected)
		}
	}
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	same, e := s.EnqueueNarration(ctx, tx, r, "COMMIT_SEGMENT", "logical1", "another-trace", "", map[string]any{"attemptId": "a1", "utteranceId": "u1", "leaseToken": 1, "expectedTimelineRevision": 0}, durability.MediaMetadata{NarrationID: "n", SegmentID: "seg1", TimelineEpoch: 1, Lane: "NARRATION"})
	if e != nil || same.CommandID != first.CommandID {
		t.Fatalf("metadata replay: %v", e)
	}
	_, e = s.EnqueueNarration(ctx, tx, r, "COMMIT_SEGMENT", "logical1", "trace", "", map[string]any{"attemptId": "a1", "utteranceId": "changed", "leaseToken": 1}, durability.MediaMetadata{NarrationID: "n", SegmentID: "seg1", TimelineEpoch: 1, Lane: "NARRATION"})
	if !errors.Is(e, durability.ErrConflict) {
		t.Fatalf("semantic metadata conflict: %v", e)
	}
}

func TestPreparedEpochConcurrentStop(t *testing.T) {
	ctx, p, s := pg(t)
	r := seedNarration(t, ctx, p, s)
	tx, e := p.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	reservation, e := s.ReserveTimelineEpoch(ctx, tx, r, 1, 0, "answer")
	if e != nil {
		t.Fatal(e)
	}
	origin := durability.TimelinePosition{SessionID: "s", RunEpoch: 1, TimelineEpoch: 1, SampleIndex: 0, SampleRate: 16000}
	payload := map[string]any{"leaseToken": r.Token, "expectedTimelineRevision": 0, "expectedPreviousEpoch": 1, "newEpoch": 2, "reservationToken": reservation.ReservationToken, "originPosition": origin, "reason": "answer"}
	c, e := s.EnqueueNarration(ctx, tx, r, "BEGIN_EPOCH", "epoch2", "trace", "", payload, durability.MediaMetadata{NarrationID: "n", TimelineEpoch: 2, Lane: "NARRATION"})
	if e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	acceptStart(t, ctx, s, c, r.Token)
	proof := map[string]any{"expectedPreviousEpoch": 1, "newEpoch": 2, "originPosition": origin, "reason": "answer"}
	record(t, ctx, s, c, "BEGIN_EPOCH_PREPARED", proof)
	raw, _ := json.Marshal(proof)
	gate := make(chan struct{})
	var group sync.WaitGroup
	group.Add(2)
	go func() {
		defer group.Done()
		<-gate
		tx, err := p.Begin(ctx)
		if err != nil {
			t.Error(err)
			return
		}
		defer tx.Rollback(ctx)
		run, err := s.Current(ctx, tx, "s", false)
		if err != nil {
			t.Error(err)
			return
		}
		if err = s.Seal(ctx, tx, run); err != nil {
			t.Error(err)
			return
		}
		if err = tx.Commit(ctx); err != nil {
			t.Error(err)
		}
	}()
	go func() {
		defer group.Done()
		<-gate
		_, err := s.RecordTimeline(ctx, durability.TimelineRecord{Command: c, Producer: "runtime", Operation: "BEGIN_EPOCH_ACTIVE", Proof: raw})
		if err != nil && !errors.Is(err, durability.ErrFence) && !errors.Is(err, durability.ErrSealed) {
			t.Error(err)
		}
	}()
	close(gate)
	group.Wait()
	var barrier bool
	var active int
	if e = p.QueryRow(ctx, `SELECT stop_barrier FROM v05_narrations WHERE narration_id='n'`).Scan(&barrier); e != nil {
		t.Fatal(e)
	}
	if e = p.QueryRow(ctx, `SELECT count(*) FROM v05_timeline_epochs WHERE status<>'SEALED'`).Scan(&active); e != nil {
		t.Fatal(e)
	}
	if !barrier || active != 0 {
		t.Fatalf("activation resurrected Stop: barrier=%t epochs=%d", barrier, active)
	}
	if _, e = s.RecordTimeline(ctx, durability.TimelineRecord{Command: c, Producer: "runtime", Operation: "BEGIN_EPOCH_ACTIVE", Proof: raw}); !errors.Is(e, durability.ErrFence) {
		t.Fatalf("late activation after Stop: %v", e)
	}
}
func TestTerminalSessionSealsContinuity(t *testing.T) {
	ctx, p, s := pg(t)
	seedNarration(t, ctx, p, s)
	if _, e := p.Exec(ctx, `UPDATE live_sessions SET status='ENDED' WHERE id='s'`); e != nil {
		t.Fatal(e)
	}
	coordinator := recovery.Coordinator{Store: s, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if e := coordinator.SealTerminal(ctx); e != nil {
		t.Fatal(e)
	}
	var barrier bool
	var status string
	if e := p.QueryRow(ctx, `SELECT n.stop_barrier,te.status FROM v05_narrations n JOIN v05_timeline_epochs te USING(session_id,run_epoch) WHERE n.narration_id='n'`).Scan(&barrier, &status); e != nil {
		t.Fatal(e)
	}
	if !barrier || status != "SEALED" {
		t.Fatalf("terminal Session left media active: %t %s", barrier, status)
	}
}
