package app

import (
	"astralive/backend/internal/durability"
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"strings"
)

func obsoleteUtterance(from, to string) bool {
	if from == "COMPLETED" || from == "INTERRUPTED" || from == "FAILED" || from == "CANCELLED" {
		return true
	}
	ranks := map[string]int{"QUEUED": 1, "GENERATING": 2, "SYNTHESIZING": 3, "RENDERING": 4, "PLAYING": 5}
	return ranks[to] > 0 && ranks[from] >= ranks[to]
}

// ApplyNextDurable locks Inbox work and commits its cursor, legacy event and FSM in one transaction.
func (s *Service) ApplyNextDurable(ctx context.Context) (bool, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return false, e
	}
	defer tx.Rollback(ctx)
	var raw []byte
	var eventID string
	var failures int
	e = tx.QueryRow(ctx, `SELECT event_id,envelope,failure_count FROM v05_events WHERE processing_state='PENDING' AND next_attempt_at<=clock_timestamp() ORDER BY event_seq FOR UPDATE SKIP LOCKED LIMIT 1`).Scan(&eventID, &raw, &failures)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	var d durability.DurableEvent
	if e = json.Unmarshal(raw, &d); e != nil {
		return false, e
	}
	// Session lock orders events, Stop and recovery. Historical/fenced events are retained but never projected.
	var epoch int64
	var status string
	var expired bool
	e = tx.QueryRow(ctx, `SELECT l.run_epoch,r.status,l.expires_at<=clock_timestamp() FROM live_sessions se JOIN v05_recovery_leases l ON l.session_id=se.id JOIN v05_session_runs r USING(session_id,run_epoch) WHERE se.id=$1 FOR UPDATE OF se,l,r`, d.SessionID).Scan(&epoch, &status, &expired)
	if e != nil {
		return false, e
	}
	projection := "APPLIED"
	if epoch != d.RunEpoch || expired && status == "ACTIVE" || status == "SEALED" || status == "RECOVERY_REQUIRED" {
		projection = "STALE"
	} else {
		var p struct {
			Legacy Event `json:"legacy"`
		}
		e = json.Unmarshal(d.Payload, &p)
		if e == nil {
			e = p.Legacy.Validate()
		}
		if e == nil && (p.Legacy.EventID != eventID || p.Legacy.SessionID != d.SessionID || p.Legacy.EventType != d.EventType || p.Legacy.TraceID != d.TraceID) {
			e = durability.ErrConflict
		}
		if e == nil && p.Legacy.UtteranceID != nil {
			var uid string
			e = tx.QueryRow(ctx, `SELECT COALESCE(utterance_id,'') FROM v05_outbox WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3`, d.CommandID, d.SessionID, d.RunEpoch).Scan(&uid)
			if e == nil && uid != *p.Legacy.UtteranceID {
				e = durability.ErrConflict
			}
		}
		if e == nil {
			if _, e = tx.Exec(ctx, "SAVEPOINT event_projection"); e != nil {
				return false, e
			}
			_, e = s.applyEventTx(ctx, tx, p.Legacy)
			if e != nil {
				if _, er := tx.Exec(ctx, "ROLLBACK TO SAVEPOINT event_projection"); er != nil {
					return false, er
				}
			}
		}
		if e != nil {
			code := "PREREQUISITE_MISSING"
			if e == durability.ErrConflict {
				code = "COMMAND_CONFLICT"
			}
			next := "PENDING"
			if failures >= 29 || code == "COMMAND_CONFLICT" {
				next = "DEAD"
			}
			_, er := tx.Exec(ctx, `UPDATE v05_events SET failure_count=failure_count+1,processing_state=$2,last_error_code=$3,next_attempt_at=clock_timestamp()+interval '1 second' WHERE event_id=$1`, eventID, next, code)
			if er != nil {
				return false, er
			}
			return true, tx.Commit(ctx)
		}
		if strings.HasPrefix(d.EventType, "UTTERANCE_") {
			state := "generating"
			if d.EventType == "UTTERANCE_QUEUED" {
				state = "accepted"
			}
			if d.EventType == "UTTERANCE_INTERRUPTED" {
				state = "interrupted"
			}
			if d.EventType == "UTTERANCE_COMPLETED" || d.EventType == "UTTERANCE_FAILED" {
				state = "unknown"
			}
			_, e = tx.Exec(ctx, `WITH revision AS (UPDATE v05_inbox SET last_receipt_seq=last_receipt_seq+1 WHERE command_id=$1 RETURNING *)
   INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,attempt_id,state,producer_incarnation,evidence_type,evidence_ref,observation_hash)
   SELECT session_id,run_epoch,command_id,last_receipt_seq,tenant_id,user_id,execution_attempt_id,$2,executor_incarnation,'legacy_runtime_stage',$3,$4 FROM revision`, d.CommandID, state, d.EventType, eventID)
			if e != nil {
				return false, e
			}

			terminal := d.EventType == "UTTERANCE_COMPLETED" || d.EventType == "UTTERANCE_INTERRUPTED" || d.EventType == "UTTERANCE_FAILED"
			if terminal {
				// v1 completion is explicitly media-drain evidence, NOT v0.5 SegmentCompleted/all-sink proof.
				_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='TERMINAL',terminal_at=clock_timestamp() WHERE command_id=$1 AND execution_state IN ('STARTED','UNKNOWN')`, d.CommandID)
				if e != nil {
					return false, e
				}
			}
		}
		if d.EventType == "SESSION_ENDED" || d.EventType == "SESSION_FAILED" {
			_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state='CANCELLED',last_error_code='SESSION_TERMINATED_BY_EVENT' WHERE session_id=$1 AND run_epoch=$2 AND delivery_state='PENDING'`, d.SessionID, d.RunEpoch)
			if e != nil {
				return false, e
			}
			_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2`, d.SessionID, d.RunEpoch)
			if e != nil {
				return false, e
			}
		}
		_, e = tx.Exec(ctx, `UPDATE interaction_receipts ir SET status='ACCEPTED' FROM v05_interaction_commands ic WHERE ic.session_id=ir.session_id AND ic.trace_id=ir.trace_id AND ic.command_id=$1 AND ir.status='RESERVED'`, d.CommandID)
		if e != nil {
			return false, e
		}
	}
	_, e = tx.Exec(ctx, `UPDATE v05_events SET processing_state=$2 WHERE event_id=$1`, eventID, projection)
	if e != nil {
		return false, e
	}
	if e = tx.Commit(ctx); e != nil {
		return false, e
	}
	if projection == "APPLIED" {
		var p struct {
			Legacy Event `json:"legacy"`
		}
		_ = json.Unmarshal(d.Payload, &p)
		_ = s.afterEvent(ctx, p.Legacy)
	}
	return true, nil
}
