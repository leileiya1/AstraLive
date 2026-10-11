package durability

import (
	"astralive/backend/internal/ids"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
)

// MediaMetadata is authority metadata, not a change to the frozen v1 utterance DTO.
type MediaMetadata struct {
	NarrationID   string
	SegmentID     string
	TimelineEpoch int64
	Lane          string
}

func nullableID(id string) json.RawMessage {
	if id == "" {
		return json.RawMessage("null")
	}
	b, _ := json.Marshal(id)
	return b
}
func decodedID(raw json.RawMessage) string { var id string; _ = json.Unmarshal(raw, &id); return id }
func (s *Store) EnqueueNarration(ctx context.Context, tx pgx.Tx, r Run, kind, key, trace, uid string, payload any, m MediaMetadata) (Command, error) {
	switch kind {
	case "BEGIN_RUN", "START_SESSION", "SPEAK", "FORCE_INTERRUPT", "STOP_SESSION", "SUSPEND_AT_BOUNDARY", "INVALIDATE_AFTER", "BEGIN_EPOCH", "COMMIT_SEGMENT", "START_NARRATION", "PLAN_NEXT_SEGMENT", "REQUEST_SUSPEND", "COMMIT_RESUME_POINT", "START_AUDIENCE_ANSWER", "COMPLETE_AUDIENCE_ANSWER", "PREPARE_RESUME_BRIDGE", "RESUME_NARRATION", "STOP_NARRATION":
	default:
		return Command{}, ErrConflict
	}
	// Caller must have obtained Current within THIS transaction. Recheck the run before any write.
	current, e := s.Current(ctx, tx, r.SessionID, false)
	if e != nil {
		return Command{}, e
	}
	if current.Epoch != r.Epoch || current.Token != r.Token || current.Status != "ACTIVE" {
		return Command{}, ErrFence
	}
	c, e := s.enqueue(ctx, tx, current, kind, key, trace, uid, payload, &m)
	if e != nil {
		return c, e
	}
	if kind == "COMMIT_SEGMENT" {
		var p struct {
			AttemptID   string `json:"attemptId"`
			UtteranceID string `json:"utteranceId"`
		}
		if json.Unmarshal(c.Payload, &p) != nil || p.AttemptID == "" || p.UtteranceID == "" || m.NarrationID == "" || m.SegmentID == "" {
			return c, ErrConflict
		}
		// One frozen COMMIT_SEGMENT command owns one immutable attempt.
		_, e = tx.Exec(ctx, `INSERT INTO v05_segment_attempts(attempt_id,session_id,run_epoch,timeline_epoch,tenant_id,user_id,narration_id,segment_id,command_id,utterance_id,lane) SELECT $1,session_id,run_epoch,$3,tenant_id,user_id,$4,$5,$6,$8,$9 FROM v05_session_runs WHERE session_id=$2 AND run_epoch=$7 ON CONFLICT(attempt_id) DO NOTHING`, p.AttemptID, c.SessionID, m.TimelineEpoch, m.NarrationID, m.SegmentID, c.CommandID, c.RunEpoch, p.UtteranceID, c.Lane)
		if e != nil {
			return c, e
		}
		var matches bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_segment_attempts WHERE attempt_id=$1 AND session_id=$2 AND run_epoch=$3 AND timeline_epoch=$4 AND narration_id=$5 AND segment_id=$6 AND utterance_id=$7 AND lane=$8 AND command_id=$9)`, p.AttemptID, c.SessionID, c.RunEpoch, m.TimelineEpoch, m.NarrationID, m.SegmentID, p.UtteranceID, c.Lane, c.CommandID).Scan(&matches)
		if e != nil {
			return c, e
		}
		if !matches {
			return c, ErrConflict
		}
	}
	return c, nil
}
func (s *Store) checkMediaMetadata(ctx context.Context, tx pgx.Tx, r Run, c Command) error {
	if c.TimelineEpoch < 1 || c.TimelineEpoch > MaxEpoch {
		return ErrFence
	}
	switch c.Lane {
	case "NARRATION", "AUDIENCE_ANSWER", "RESUME_BRIDGE", "OPERATOR", "SYSTEM":
	default:
		return ErrConflict
	}
	nid, sid := decodedID(c.NarrationID), decodedID(c.SegmentID)
	if nid != "" {
		var ok bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_narrations n JOIN v05_session_runs r USING(session_id,run_epoch,tenant_id,user_id) WHERE n.narration_id=$1 AND n.session_id=$2 AND n.run_epoch=$3 AND NOT n.stop_barrier AND n.state NOT IN ('STOPPING','STOPPED','FAILED','RECOVERY_REQUIRED') AND ($4='' OR EXISTS(SELECT 1 FROM v05_segments x WHERE x.segment_id=$4 AND x.narration_id=n.narration_id AND x.session_id=n.session_id)))`, nid, c.SessionID, r.Epoch, sid).Scan(&ok)
		if e != nil {
			return e
		}
		if !ok {
			return ErrSealed
		}
	} else if sid != "" {
		return ErrConflict
	}
	return s.checkCommandEpoch(ctx, tx, r, c)
}
func (s *Store) checkCommandEpoch(ctx context.Context, tx pgx.Tx, r Run, c Command) error {
	if c.TimelineEpoch == 0 {
		return nil
	}
	if c.CommandType == "BEGIN_EPOCH" {
		var payload struct {
			Previous int64  `json:"expectedPreviousEpoch"`
			New      int64  `json:"newEpoch"`
			Token    string `json:"reservationToken"`
		}
		if json.Unmarshal(c.Payload, &payload) != nil || payload.Token == "" || payload.Previous != r.TimelineEpoch || payload.New != r.TimelineEpoch+1 || c.TimelineEpoch != payload.New {
			return ErrFence
		}
		var ok bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_timeline_epochs WHERE session_id=$1 AND run_epoch=$2 AND timeline_epoch=$3 AND expected_previous_epoch=$4 AND reservation_token=$5 AND status='PREPARED')`, c.SessionID, c.RunEpoch, payload.New, payload.Previous, payload.Token).Scan(&ok)
		if e != nil {
			return e
		}
		if !ok {
			return ErrFence
		}
		return nil
	}
	if c.TimelineEpoch != r.TimelineEpoch {
		return ErrFence
	}
	if c.CommandType == "SPEAK" || c.CommandType == "COMMIT_SEGMENT" {
		var pending bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_timeline_epochs WHERE session_id=$1 AND run_epoch=$2 AND status='PREPARED')`, c.SessionID, c.RunEpoch).Scan(&pending)
		if e != nil {
			return e
		}
		if pending {
			return ErrFence
		}
	}
	return nil
}

type EpochReservation struct {
	TimelineEpoch         int64  `json:"timelineEpoch"`
	ExpectedPreviousEpoch int64  `json:"expectedPreviousEpoch"`
	ReservationToken      string `json:"reservationToken"`
	OriginSample          int64  `json:"originSample"`
}

// ReserveTimelineEpoch does not activate the epoch or admit any media. C writes its CAS and BEGIN_EPOCH in this tx.
func (s *Store) ReserveTimelineEpoch(ctx context.Context, tx pgx.Tx, r Run, expected, origin int64, reason string) (EpochReservation, error) {
	current, e := s.Current(ctx, tx, r.SessionID, false)
	if e != nil {
		return EpochReservation{}, e
	}
	if current.Epoch != r.Epoch || current.Token != r.Token || current.Status != "ACTIVE" || current.TimelineEpoch != expected || expected >= MaxEpoch || origin < 0 || origin > MaxEpoch {
		return EpochReservation{}, ErrFence
	}
	var cursor int64
	e = tx.QueryRow(ctx, `SELECT current_committed_sample FROM v05_session_runs WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch).Scan(&cursor)
	if e != nil {
		return EpochReservation{}, e
	}
	if origin != cursor {
		return EpochReservation{}, ErrConflict
	}
	out := EpochReservation{expected + 1, expected, ids.New("reservation"), origin}
	var previous int64
	var oldReason string
	e = tx.QueryRow(ctx, `SELECT timeline_epoch,expected_previous_epoch,reservation_token,origin_sample,reason FROM v05_timeline_epochs WHERE session_id=$1 AND run_epoch=$2 AND status='PREPARED'`, r.SessionID, r.Epoch).Scan(&out.TimelineEpoch, &previous, &out.ReservationToken, &out.OriginSample, &oldReason)
	if e == nil {
		if previous != expected || out.OriginSample != origin || oldReason != reason {
			return out, ErrConflict
		}
		out.ExpectedPreviousEpoch = previous
		return out, nil
	}
	if e != pgx.ErrNoRows {
		return out, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason) SELECT session_id,run_epoch,$3,tenant_id,user_id,'PREPARED',$4,$5,$6,$7 FROM v05_session_runs WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch, out.TimelineEpoch, out.ReservationToken, expected, origin, reason)
	return out, e
}

// ConfigureTimelineOutput captures a fixed output clock and required/optional sink identities before media work.
func (s *Store) ConfigureTimelineOutput(ctx context.Context, tx pgx.Tx, r Run, rate int, required, optional []string) error {
	if rate < 1 || rate > 192000 || len(required) == 0 {
		return ErrConflict
	}
	seen := map[string]bool{}
	for _, id := range append(append([]string{}, required...), optional...) {
		if id == "" || seen[id] {
			return ErrConflict
		}
		seen[id] = true
	}
	rr, e := s.Current(ctx, tx, r.SessionID, false)
	if e != nil {
		return e
	}
	if rr.Epoch != r.Epoch || rr.Token != r.Token || rr.Status != "ACTIVE" {
		return ErrFence
	}
	if optional == nil {
		optional = []string{}
	}
	req, _ := json.Marshal(required)
	opt, _ := json.Marshal(optional)
	var matches, unused bool
	e = tx.QueryRow(ctx, `SELECT output_sample_rate=$3 AND required_sinks=$4::jsonb AND optional_sinks=$5::jsonb,current_committed_sample=0 AND NOT EXISTS(SELECT 1 FROM v05_timeline_commits c WHERE c.session_id=r.session_id AND c.run_epoch=r.run_epoch) AND required_sinks='[]'::jsonb FROM v05_session_runs r WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch, rate, req, opt).Scan(&matches, &unused)
	if e != nil {
		return e
	}
	if matches {
		return nil
	}
	if !unused {
		return ErrConflict
	}
	_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET output_sample_rate=$3,required_sinks=$4,optional_sinks=$5 WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch, rate, req, opt)
	return e
}

// FenceTimeline preserves known completions/cursors and makes ambiguous media non-replayable.
// Caller holds the Session lock; C's document keys are the acknowledged Document seam.
func (s *Store) FenceTimeline(ctx context.Context, tx pgx.Tx, r Run, reason string, stop bool) error {
	_, e := tx.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2 AND (status='PREPARED' OR $3)`, r.SessionID, r.Epoch, stop || reason == "RUN_RETIRED_UNKNOWN")
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET status='SEALED' WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_segment_attempts SET status=CASE WHEN status='PLANNED' THEN 'CANCELLED' ELSE 'UNKNOWN' END,updated_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2 AND status IN ('PLANNED','STARTED','READY','COMMITTED')`, r.SessionID, r.Epoch)
	if e != nil {
		return e
	}
	state := "RECOVERY_REQUIRED"
	if stop {
		state = "STOPPING"
	}
	_, e = tx.Exec(ctx, `UPDATE v05_narrations SET state=$3,revision=revision+1,stop_barrier=stop_barrier OR $4,recovery_disposition=$5,
 document_json=document_json || jsonb_build_object('state',$3::text,'narrationRevision',revision+1,'stopBarrier',stop_barrier OR $4,'reason',$5::text) || CASE WHEN $5='OPERATOR_FORCE' THEN '{"operatorOverride":true}'::jsonb ELSE '{}'::jsonb END,
 updated_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2 AND state NOT IN ('STOPPED','FAILED') AND (state<>$3 OR NOT stop_barrier AND $4)`, r.SessionID, r.Epoch, state, stop, reason)
	return e
}
