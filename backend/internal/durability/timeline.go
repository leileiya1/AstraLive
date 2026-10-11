package durability

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"math/big"
	"sort"
)

var ErrProjectionUnavailable = errors.New("CONTINUITY_PROJECTION_UNAVAILABLE")

type TimelineRecord struct {
	Operation string          `json:"operation"`
	Command   Command         `json:"command"`
	Proof     json.RawMessage `json:"proof"`
	Producer  string          `json:"producerIncarnation"`
}
type TimelineIdentity struct {
	SessionID          string  `json:"sessionId"`
	RunEpoch           int64   `json:"runEpoch"`
	TimelineEpoch      int64   `json:"timelineEpoch"`
	GenerationID       int64   `json:"generationId"`
	SegmentID          string  `json:"segmentId"`
	UtteranceID        string  `json:"utteranceId"`
	Lane               string  `json:"lane"`
	WorkerEpoch        *string `json:"workerEpoch"`
	WorkerGenerationID *int64  `json:"workerGenerationId"`
}
type TimelinePosition struct {
	SessionID     string `json:"sessionId"`
	RunEpoch      int64  `json:"runEpoch"`
	TimelineEpoch int64  `json:"timelineEpoch"`
	SampleIndex   int64  `json:"sampleIndex"`
	SampleRate    int    `json:"sampleRate"`
	PTSUS         *int64 `json:"ptsUs,omitempty"`
}
type timelineCommit struct {
	Identity   TimelineIdentity `json:"identity"`
	AttemptID  string           `json:"attemptId"`
	Descriptor json.RawMessage  `json:"descriptor"`
	Start      int64            `json:"start"`
	End        int64            `json:"end"`
	Command    Command          `json:"command"`
}
type timelineDescriptor struct {
	Count              int64    `json:"sampleCount"`
	Hash               string   `json:"contentHash"`
	Final              bool     `json:"finalMarker"`
	Required           []string `json:"requiredSinks"`
	UtteranceID        string   `json:"utteranceId"`
	TextHash           string   `json:"textHash"`
	FactVersion        string   `json:"factVersion"`
	WorkerEpoch        *string  `json:"workerEpoch"`
	WorkerGenerationID *int64   `json:"workerGenerationId"`
}
type SinkReceipt struct {
	SinkID       string           `json:"sinkId"`
	Media        string           `json:"media"`
	Start        int64            `json:"startSample"`
	End          int64            `json:"endSample"`
	Final        bool             `json:"finalMarker"`
	Identity     TimelineIdentity `json:"identity"`
	EvidenceType string           `json:"evidenceType"`
	EvidenceRef  string           `json:"evidenceRef"`
}

func equalJSON(a, b any) bool {
	aa, _ := json.Marshal(a)
	bb, _ := json.Marshal(b)
	ha, ea := EventHash(aa)
	hb, eb := EventHash(bb)
	return ea == nil && eb == nil && ha == hb
}
func matchPosition(p TimelinePosition, r Run, epoch, cursor int64, rate int) bool {
	return p.SessionID == r.SessionID && p.RunEpoch == r.Epoch && p.TimelineEpoch == epoch && p.SampleIndex == cursor && p.SampleRate == rate && (p.PTSUS == nil || validPTS(cursor, rate, *p.PTSUS))
}

// RecordTimeline commits proof, receipt and C projection atomically. No physical side effect occurs here.
func (s *Store) RecordTimeline(ctx context.Context, x TimelineRecord) (json.RawMessage, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	result, e := s.RecordTimelineTx(ctx, tx, x)
	if e != nil {
		return nil, e
	}
	return result, tx.Commit(ctx)
}
func (s *Store) RecordTimelineTx(ctx context.Context, tx pgx.Tx, x TimelineRecord) (json.RawMessage, error) {
	c := x.Command
	if c.Validate() != nil || x.Producer == "" || len(x.Proof) == 0 {
		return nil, ErrConflict
	}
	encoded, _ := json.Marshal(c)
	hash, e := Fingerprint(encoded)
	if e != nil || hash != c.RequestFingerprint {
		return nil, ErrConflict
	}
	r, e := s.Current(ctx, tx, c.SessionID, false)
	if e != nil {
		return nil, e
	}
	if r.Epoch != c.RunEpoch || r.Status != "ACTIVE" {
		return nil, ErrFence
	}
	var stored []byte
	var producer, state string
	var token int64
	e = tx.QueryRow(ctx, `SELECT o.payload_envelope,COALESCE(i.executor_incarnation,''),i.execution_state,COALESCE(i.execution_lease_token,0) FROM v05_outbox o JOIN v05_inbox i USING(session_id,run_epoch,command_id) WHERE o.command_id=$1 AND o.session_id=$2 AND o.run_epoch=$3`, c.CommandID, c.SessionID, c.RunEpoch).Scan(&stored, &producer, &state, &token)
	if e != nil {
		return nil, e
	}
	hs, _ := Hash(stored)
	hc, _ := Hash(encoded)
	if hs != hc || producer != x.Producer || token != r.Token {
		return nil, ErrConflict
	}
	raw, e := json.Marshal(x)
	if e != nil {
		return nil, e
	}
	observationHash, e := EventHash(raw)
	if e != nil {
		return nil, e
	}
	var existingHash string
	var response []byte
	e = tx.QueryRow(ctx, `SELECT observation_hash,response_json FROM v05_timeline_observations WHERE command_id=$1 AND operation=$2`, c.CommandID, x.Operation).Scan(&existingHash, &response)
	if e == nil {
		if existingHash != observationHash {
			return nil, ErrConflict
		}
		return response, nil
	}
	if e != pgx.ErrNoRows {
		return nil, e
	}
	if state != "STARTED" || c.CommandSeq < r.BarrierSeq {
		return nil, ErrFence
	}
	var payload struct {
		LeaseToken       int64  `json:"leaseToken"`
		ExpectedRevision *int64 `json:"expectedTimelineRevision"`
		LegacyRevision   *int64 `json:"expectedRevision"`
	}
	if json.Unmarshal(c.Payload, &payload) != nil || payload.LeaseToken != r.Token {
		return nil, ErrFence
	}
	if payload.ExpectedRevision == nil {
		payload.ExpectedRevision = payload.LegacyRevision
	} else if payload.LegacyRevision != nil && *payload.LegacyRevision != *payload.ExpectedRevision {
		return nil, ErrConflict
	}
	if x.Operation != "SEGMENT_COMPLETED" {
		if e = s.checkCommandEpoch(ctx, tx, r, c); e != nil {
			return nil, e
		}
	}
	var revision, cursor int64
	var rate int
	var requiredRaw, optionalRaw []byte
	e = tx.QueryRow(ctx, `SELECT timeline_revision,current_committed_sample,output_sample_rate,required_sinks,optional_sinks FROM v05_session_runs WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, c.RunEpoch).Scan(&revision, &cursor, &rate, &requiredRaw, &optionalRaw)
	if e != nil {
		return nil, e
	}
	nextState := "accepted"
	switch x.Operation {
	case "SEGMENT_READY":
		if c.CommandType != "COMMIT_SEGMENT" {
			return nil, ErrConflict
		}
		var p struct {
			AttemptID    string          `json:"attemptId"`
			GenerationID int64           `json:"generationId"`
			Descriptor   json.RawMessage `json:"descriptor"`
		}
		var d timelineDescriptor
		if json.Unmarshal(x.Proof, &p) != nil || json.Unmarshal(p.Descriptor, &d) != nil || p.AttemptID == "" || p.GenerationID < 1 || !d.Final || d.Count < 1 || d.Hash == "" || d.UtteranceID == "" || d.TextHash == "" || d.FactVersion == "" || (d.WorkerEpoch == nil) != (d.WorkerGenerationID == nil) {
			return nil, ErrConflict
		}
		var required []string
		_ = json.Unmarshal(requiredRaw, &required)
		if len(required) == 0 || !equalJSON(required, d.Required) {
			return nil, ErrConflict
		}
		tag, err := tx.Exec(ctx, `UPDATE v05_segment_attempts a SET status='READY',descriptor_json=$5,worker_epoch=$6,worker_generation_id=$7,worker_ref_json=jsonb_build_object('workerEpoch',$6::text,'workerGenerationId',$7::bigint),updated_at=clock_timestamp() FROM v05_inbox i,v05_segments seg WHERE seg.session_id=a.session_id AND seg.segment_id=a.segment_id AND seg.text_hash=$9 AND seg.product_version=$10 AND a.utterance_id=$8 AND a.attempt_id=$1 AND a.command_id=$2 AND a.generation_id=$3 AND a.segment_id=$4 AND a.status='STARTED' AND i.command_id=a.command_id AND i.generation_id=a.generation_id`, p.AttemptID, c.CommandID, p.GenerationID, decodedID(c.SegmentID), p.Descriptor, d.WorkerEpoch, d.WorkerGenerationID, d.UtteranceID, d.TextHash, d.FactVersion)
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() != 1 {
			return nil, ErrFence
		}
		nextState = "ready"
	case "ANSWER_PREPARED", "RESUME_PREPARED":
		if s.TimelineProjection == nil {
			return nil, ErrProjectionUnavailable
		}
		if decodedID(c.NarrationID) == "" {
			return nil, ErrConflict
		}
		// C validates commandType, captured facts/text and expectedNarrationRevision,
		// writes its CAS and resulting COMMIT_SEGMENT Outbox in this same tx.
		nextState = "ready"
	case "COMMIT_INTENT", "COMMIT_INSTALLED":
		if c.CommandType != "COMMIT_SEGMENT" || decodedID(c.SegmentID) == "" || decodedID(c.NarrationID) == "" {
			return nil, ErrConflict
		}
		var proof struct {
			Commit   timelineCommit `json:"commit"`
			Revision *int64         `json:"revision"`
		}
		if json.Unmarshal(x.Proof, &proof) != nil {
			return nil, ErrConflict
		}
		commit := proof.Commit
		var descriptor timelineDescriptor
		if json.Unmarshal(commit.Descriptor, &descriptor) != nil || !descriptor.Final || descriptor.Hash == "" || descriptor.Count < 1 || commit.Start < 0 || commit.End > MaxEpoch || commit.End-commit.Start != descriptor.Count || commit.Identity.UtteranceID != descriptor.UtteranceID || !equalJSON(commit.Command, c) {
			return nil, ErrConflict
		}
		identity := commit.Identity
		if identity.SessionID != c.SessionID || identity.RunEpoch != r.Epoch || identity.TimelineEpoch != c.TimelineEpoch || identity.SegmentID != decodedID(c.SegmentID) || identity.GenerationID < 1 || identity.GenerationID > MaxEpoch || identity.Lane != c.Lane {
			return nil, ErrFence
		}
		if (identity.WorkerEpoch == nil) != (identity.WorkerGenerationID == nil) {
			return nil, ErrConflict
		}
		var required []string
		_ = json.Unmarshal(requiredRaw, &required)
		if len(required) == 0 || !equalJSON(required, descriptor.Required) {
			return nil, ErrConflict
		}
		var bound bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_segment_attempts a JOIN v05_segments s USING(session_id,segment_id) WHERE a.attempt_id=$1 AND a.session_id=$2 AND a.run_epoch=$3 AND a.timeline_epoch=$4 AND a.segment_id=$5 AND a.narration_id=$6 AND a.generation_id=$7 AND a.status IN ('READY','COMMITTED') AND s.narration_id=a.narration_id AND a.worker_epoch IS NOT DISTINCT FROM $8::text AND a.worker_generation_id IS NOT DISTINCT FROM $9::bigint AND a.descriptor_json=$10::jsonb AND a.utterance_id=$11 AND a.lane=$12 AND a.command_id=$13)`, commit.AttemptID, c.SessionID, r.Epoch, c.TimelineEpoch, identity.SegmentID, decodedID(c.NarrationID), identity.GenerationID, identity.WorkerEpoch, identity.WorkerGenerationID, commit.Descriptor, identity.UtteranceID, identity.Lane, c.CommandID).Scan(&bound)
		if e != nil {
			return nil, e
		}
		if !bound {
			return nil, ErrFence
		}
		identityRaw, _ := json.Marshal(identity)
		if x.Operation == "COMMIT_INTENT" {
			nextState = "ready"
			if payload.ExpectedRevision == nil || *payload.ExpectedRevision != revision || proof.Revision == nil || *proof.Revision != revision || commit.Start != cursor {
				return nil, ErrConflict
			}
			_, e = tx.Exec(ctx, `INSERT INTO v05_timeline_commits(session_id,run_epoch,timeline_epoch,segment_id,attempt_id,tenant_id,user_id,command_id,generation_id,start_sample,end_sample,sample_rate,identity_json,descriptor_json,required_sinks,optional_sinks,status) SELECT session_id,run_epoch,$3,$4,$5,tenant_id,user_id,$6,$7,$8,$9,$10,$11,$12,required_sinks,optional_sinks,'PENDING_INSTALL' FROM v05_session_runs WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, r.Epoch, c.TimelineEpoch, identity.SegmentID, commit.AttemptID, c.CommandID, identity.GenerationID, commit.Start, commit.End, rate, identityRaw, commit.Descriptor)
		} else {
			var oldIdentity, oldDescriptor []byte
			var start, end int64
			var status string
			e = tx.QueryRow(ctx, `SELECT identity_json,descriptor_json,start_sample,end_sample,status FROM v05_timeline_commits WHERE command_id=$1 FOR UPDATE`, c.CommandID).Scan(&oldIdentity, &oldDescriptor, &start, &end, &status)
			if e != nil {
				return nil, e
			}
			if !equalJSON(json.RawMessage(oldIdentity), identity) || !equalJSON(json.RawMessage(oldDescriptor), commit.Descriptor) || start != commit.Start || end != commit.End || status != "PENDING_INSTALL" || cursor != start || payload.ExpectedRevision == nil || *payload.ExpectedRevision != revision {
				return nil, ErrConflict
			}
			_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET status='ELIGIBLE',installed_at=clock_timestamp() WHERE command_id=$1`, c.CommandID)
			if e == nil {
				_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET current_committed_sample=$3,timeline_revision=timeline_revision+1 WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, r.Epoch, end)
			}
			if e == nil {
				_, e = tx.Exec(ctx, `UPDATE v05_segment_attempts SET status='COMMITTED' WHERE attempt_id=$1`, commit.AttemptID)
			}
			revision++
			nextState = "committed"
		}
	case "BEGIN_EPOCH_PREPARED", "BEGIN_EPOCH_ACTIVE":
		if c.CommandType != "BEGIN_EPOCH" {
			return nil, ErrConflict
		}
		var p struct {
			Previous int64            `json:"expectedPreviousEpoch"`
			New      int64            `json:"newEpoch"`
			Token    string           `json:"reservationToken"`
			Origin   TimelinePosition `json:"originPosition"`
			Reason   string           `json:"reason"`
		}
		var proof struct {
			Previous int64            `json:"expectedPreviousEpoch"`
			New      int64            `json:"newEpoch"`
			Origin   TimelinePosition `json:"originPosition"`
			Reason   string           `json:"reason"`
		}
		if json.Unmarshal(c.Payload, &p) != nil || json.Unmarshal(x.Proof, &proof) != nil || p.Token == "" || p.Previous != proof.Previous || p.New != proof.New || p.Reason != proof.Reason || !equalJSON(p.Origin, proof.Origin) || !matchPosition(proof.Origin, r, r.TimelineEpoch, cursor, rate) || payload.ExpectedRevision == nil || *payload.ExpectedRevision != revision {
			return nil, ErrConflict
		}
		var ok bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_timeline_epochs WHERE session_id=$1 AND run_epoch=$2 AND timeline_epoch=$3 AND expected_previous_epoch=$4 AND reservation_token=$5 AND origin_sample=$6 AND reason=$7 AND status='PREPARED')`, c.SessionID, r.Epoch, p.New, p.Previous, p.Token, cursor, p.Reason).Scan(&ok)
		if e != nil {
			return nil, e
		}
		if !ok {
			return nil, ErrFence
		}
		if x.Operation == "BEGIN_EPOCH_ACTIVE" {
			var prepared bool
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_timeline_observations WHERE command_id=$1 AND operation='BEGIN_EPOCH_PREPARED')`, c.CommandID).Scan(&prepared)
			if e != nil {
				return nil, e
			}
			if !prepared {
				return nil, ErrConflict
			}
			_, e = tx.Exec(ctx, `UPDATE v05_timeline_epochs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2 AND status='ACTIVE'`, c.SessionID, r.Epoch)
			if e == nil {
				_, e = tx.Exec(ctx, `UPDATE v05_timeline_epochs SET status='ACTIVE',activated_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2 AND timeline_epoch=$3`, c.SessionID, r.Epoch, p.New)
			}
			if e == nil {
				_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET current_timeline_epoch=$3,timeline_revision=timeline_revision+1 WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, r.Epoch, p.New)
			}
			if e == nil {
				_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET status='SEALED' WHERE session_id=$1 AND run_epoch=$2 AND timeline_epoch<>$3`, c.SessionID, r.Epoch, p.New)
			}
			revision++
			nextState = "committed"
		}
	case "SUSPEND_REQUESTED", "INVALIDATE_AFTER":
		expectedKind := "SUSPEND_AT_BOUNDARY"
		if x.Operation == "INVALIDATE_AFTER" {
			expectedKind = "INVALIDATE_AFTER"
		}
		if c.CommandType != expectedKind || payload.ExpectedRevision == nil || *payload.ExpectedRevision != revision {
			return nil, ErrConflict
		}
		if x.Operation == "SUSPEND_REQUESTED" {
			var proof struct {
				SegmentID string `json:"segmentId"`
			}
			if json.Unmarshal(x.Proof, &proof) != nil || proof.SegmentID == "" {
				return nil, ErrConflict
			}
			var valid bool
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_timeline_commits WHERE session_id=$1 AND run_epoch=$2 AND timeline_epoch=$3 AND segment_id=$4 AND end_sample=$5 AND installed_at IS NOT NULL AND status='ELIGIBLE')`, c.SessionID, r.Epoch, c.TimelineEpoch, proof.SegmentID, cursor).Scan(&valid)
			if e != nil {
				return nil, e
			}
			if !valid {
				return nil, ErrConflict
			}
		} else {
			var proof struct {
				Cut TimelinePosition `json:"retainedPrefix"`
			}
			if json.Unmarshal(x.Proof, &proof) != nil || !matchPosition(proof.Cut, r, r.TimelineEpoch, cursor, rate) {
				return nil, ErrConflict
			}
			_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET status='SEALED' WHERE session_id=$1 AND run_epoch=$2 AND status='PENDING_INSTALL'`, c.SessionID, r.Epoch)
			nextState = "interrupted"
		}
		if e == nil {
			_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET timeline_revision=timeline_revision+1 WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, r.Epoch)
		}
		revision++
	case "SEGMENT_COMPLETED":
		if c.CommandType != "COMMIT_SEGMENT" {
			return nil, ErrConflict
		}
		var proof struct {
			Identity TimelineIdentity `json:"identity"`
			Final    TimelinePosition `json:"finalPosition"`
			Receipts []SinkReceipt    `json:"sinkReceipts"`
			Evidence string           `json:"evidenceType"`
			Audible  bool             `json:"audienceAudible"`
		}
		if json.Unmarshal(x.Proof, &proof) != nil || proof.Evidence != "sink_consumed" || proof.Audible {
			return nil, ErrConflict
		}
		var identityRaw, required []byte
		var start, end, tl int64
		var commitRate int
		var installed bool
		var attempt string
		e = tx.QueryRow(ctx, `SELECT identity_json,required_sinks,start_sample,end_sample,sample_rate,timeline_epoch,installed_at IS NOT NULL,attempt_id FROM v05_timeline_commits WHERE command_id=$1 FOR UPDATE`, c.CommandID).Scan(&identityRaw, &required, &start, &end, &commitRate, &tl, &installed, &attempt)
		if e != nil {
			return nil, e
		}
		if !installed || end > cursor || !equalJSON(json.RawMessage(identityRaw), proof.Identity) || !matchPosition(proof.Final, r, tl, end, commitRate) {
			return nil, ErrFence
		}
		var sinks []string
		_ = json.Unmarshal(required, &sinks)
		if !completeSinks(sinks, proof.Receipts, proof.Identity, start, end) {
			return nil, ErrConflict
		}
		if decodedID(c.NarrationID) != "" && s.TimelineProjection == nil {
			return nil, ErrProjectionUnavailable
		}
		sinkRaw, _ := json.Marshal(proof.Receipts)
		_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET play_state='COMPLETED',sink_receipts=$2,completion_hash=$3,completed_at=clock_timestamp() WHERE command_id=$1`, c.CommandID, sinkRaw, observationHash)
		if e == nil {
			_, e = tx.Exec(ctx, `UPDATE v05_segment_attempts SET status='COMPLETED',updated_at=clock_timestamp() WHERE attempt_id=$1`, attempt)
		}
		nextState = "completed"
	case "UNKNOWN":
		_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='UNKNOWN' WHERE command_id=$1 AND execution_state='STARTED'`, c.CommandID)
		if e == nil {
			_, e = tx.Exec(ctx, `UPDATE v05_timeline_commits SET play_state='UNKNOWN' WHERE command_id=$1 AND play_state<>'COMPLETED'`, c.CommandID)
		}
		nextState = "unknown"
	default:
		return nil, ErrConflict
	}
	if e != nil {
		return nil, e
	}
	var seq int64
	e = tx.QueryRow(ctx, `UPDATE v05_inbox SET last_receipt_seq=last_receipt_seq+1 WHERE command_id=$1 RETURNING last_receipt_seq`, c.CommandID).Scan(&seq)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,attempt_id,state,producer_incarnation,evidence_type,evidence_ref,range_sinks,observation_hash) SELECT session_id,run_epoch,command_id,$2,tenant_id,user_id,execution_attempt_id,$3,$4,$5,$6,$7,$8 FROM v05_inbox WHERE command_id=$1`, c.CommandID, seq, nextState, x.Producer, "timeline_journal", x.Operation, x.Proof, observationHash)
	if e != nil {
		return nil, e
	}
	projection, _ := json.Marshal(map[string]any{"operation": x.Operation, "proof": x.Proof, "receiptSeq": seq})
	if s.TimelineProjection != nil {
		if e = s.TimelineProjection(ctx, tx, c, projection); e != nil {
			return nil, e
		}
	}
	if nextState == "completed" || x.Operation == "BEGIN_EPOCH_ACTIVE" {
		_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='TERMINAL',terminal_at=clock_timestamp() WHERE command_id=$1`, c.CommandID)
		if e != nil {
			return nil, e
		}
	}
	response, _ = json.Marshal(map[string]any{"durable": true, "state": nextState, "revision": revision, "receiptSeq": seq})
	_, e = tx.Exec(ctx, `INSERT INTO v05_timeline_observations(command_id,operation,observation_hash,proof_json,response_json,session_id,run_epoch,tenant_id,user_id) SELECT $1,$2,$3,$4,$5,session_id,run_epoch,tenant_id,user_id FROM v05_inbox WHERE command_id=$1`, c.CommandID, x.Operation, observationHash, x.Proof, response)
	return response, e
}
func completeSinks(required []string, receipts []SinkReceipt, identity TimelineIdentity, start, end int64) bool {
	if len(required) == 0 || len(receipts) == 0 {
		return false
	}
	grouped := map[string][]SinkReceipt{}
	for _, p := range receipts {
		if p.EvidenceType != "sink_consumed" || p.EvidenceRef == "" || p.SinkID == "" || (p.Media != "audio" && p.Media != "video") || p.Start < start || p.End > end || p.Start >= p.End || !equalJSON(p.Identity, identity) {
			return false
		}
		grouped[p.SinkID+"\x00"+p.Media] = append(grouped[p.SinkID+"\x00"+p.Media], p)
	}
	for _, sink := range required {
		for _, media := range []string{"audio", "video"} {
			items := grouped[sink+"\x00"+media]
			sort.Slice(items, func(i, j int) bool { return items[i].Start < items[j].Start })
			cursor := start
			for i, p := range items {
				if p.Start != cursor || p.Final && i != len(items)-1 {
					return false
				}
				cursor = p.End
			}
			if cursor != end || len(items) == 0 || !items[len(items)-1].Final {
				return false
			}
		}
	}
	return true
}

func validPTS(samples int64, rate int, pts int64) bool {
	if rate < 1 || pts < 0 || pts > MaxEpoch {
		return false
	}
	v := new(big.Int).Mul(big.NewInt(samples), big.NewInt(1000000))
	v.Quo(v, big.NewInt(int64(rate)))
	return v.IsInt64() && v.Int64() == pts
}
