package app

import (
	"astralive/backend/generated/dbgen"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/metrics"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/userconfig"
	"context"
	"github.com/jackc/pgx/v5"
	"time"
)

// AttachNarration shares App's existing durable whole-Session Stop transaction.
// A narration cannot be admitted without this captured-lifecycle safety hook.
func (s *Service) AttachNarration(c *narration.Controller) {
	s.Narration = c
	c.RetireCapturedSession = func(ctx context.Context, tx pgx.Tx, run durability.Run) error {
		_, e := s.durableControl(durability.WithBusinessTx(ctx, tx), run.SessionID, ids.New("trace"), "STOP_SESSION", "PRODUCT_VERSION_CHANGED")
		return e
	}
}

func (s *Service) durableSpeak(ctx context.Context, id, text string, priority int32, policy, source, trace string, platform *runtimeapi.PlatformContext, interaction bool) (dbgen.Utterance, error) {
	tx, e := durability.BeginBusiness(ctx, s.DB)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	defer tx.Rollback(ctx)
	r, e := s.Durable.Current(ctx, tx, id, false)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	q := s.Q.WithTx(tx)
	se, e := q.GetSession(ctx, id)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	if r.Status != "ACTIVE" || se.Status != "LIVE" && se.Status != "DEGRADED" {
		return dbgen.Utterance{}, ErrConflict
	}
	forceBarrier := false
	if s.Narration != nil {
		forceBarrier, e = s.Narration.AdmitOrdinary(ctx, tx, r, policy)
		if e != nil {
			return dbgen.Utterance{}, e
		}
	}
	if interaction {
		var old string
		e = tx.QueryRow(ctx, `SELECT COALESCE(utterance_id,'') FROM interaction_receipts WHERE session_id=$1 AND trace_id=$2`, id, trace).Scan(&old)
		if e == nil {
			if old == "" {
				return dbgen.Utterance{}, ErrConflict
			}
			return q.GetUtterance(ctx, old)
		}
		if e != pgx.ErrNoRows {
			return dbgen.Utterance{}, e
		}
		var busy bool
		er := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM utterances WHERE session_id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED') AND NOT (source='AUTO_SCRIPT' AND priority<$2 AND $3='INTERRUPT_LOWER_PRIORITY'))`, id, priority, policy).Scan(&busy)
		if er != nil {
			return dbgen.Utterance{}, er
		}
		if busy {
			return dbgen.Utterance{}, ErrConflict
		}
	}
	ro, e := q.GetRoom(ctx, se.RoomID)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	u, e := q.CreateUtterance(ctx, dbgen.CreateUtteranceParams{ID: ids.New("utt"), SessionID: id, Text: text, Priority: priority, InterruptPolicy: policy, Source: source, TraceID: trace})
	if e != nil {
		return u, e
	}
	req := runtimeapi.RuntimeUtteranceRequest{CommandId: ids.New("legacy_cmd"), TraceId: trace, UtteranceId: u.ID, Text: text, Priority: int(priority), InterruptPolicy: runtimeapi.InterruptPolicy(policy), Source: runtimeapi.UtteranceSource(source), PlatformContext: platform}
	req.Voice.VoiceId = ro.VoiceID
	c, e := s.Durable.Enqueue(ctx, tx, r, "SPEAK", u.ID, trace, u.ID, req)
	if e != nil {
		return u, e
	}
	if forceBarrier {
		if e = s.Durable.Barrier(ctx, tx, c); e != nil {
			return u, e
		}
	}
	if interaction {
		_, e = tx.Exec(ctx, `INSERT INTO interaction_receipts(session_id,trace_id,status,utterance_id) VALUES($1,$2,'RESERVED',$3)`, id, trace, u.ID)
		if e != nil {
			return u, e
		}
		_, e = tx.Exec(ctx, `INSERT INTO v05_interaction_commands(session_id,trace_id,command_id) VALUES($1,$2,$3)`, id, trace, c.CommandID)
		if e != nil {
			return u, e
		}
	}
	if e = tx.Commit(ctx); e == nil {
		metrics.UtteranceCount.Inc()
	}
	return u, e
}

// FORCE on a bound output cancels automatic continuation, but cannot feed
// untimed legacy media to that output. The existing FAILED result and control
// command share the public idempotency transaction; no SPEAK is enqueued.
func (s *Service) failedNarrationForce(ctx context.Context, id, text string, priority int32, source, trace string) (dbgen.Utterance, error) {
	tx, e := durability.BeginBusiness(ctx, s.DB)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	defer tx.Rollback(ctx)
	run, e := s.Durable.Current(ctx, tx, id, false)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	q := s.Q.WithTx(tx)
	session, e := q.GetSession(ctx, id)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	if run.Status != "ACTIVE" || session.Status != "LIVE" && session.Status != "DEGRADED" {
		return dbgen.Utterance{}, ErrConflict
	}
	u, e := q.CreateUtterance(ctx, dbgen.CreateUtteranceParams{ID: ids.New("utt"), SessionID: id, Text: text, Priority: priority, InterruptPolicy: "FORCE", Source: source, TraceID: trace})
	if e != nil {
		return u, e
	}
	_, e = tx.Exec(ctx, `UPDATE utterances SET status='FAILED',failure_code='DEPENDENCY_UNAVAILABLE',completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=$1`, u.ID)
	if e != nil {
		return u, e
	}
	command, e := s.Durable.Enqueue(ctx, tx, run, "FORCE_INTERRUPT", u.ID+":unsupported-force", trace, "", map[string]any{"reason": "OPERATOR_FORCE"})
	if e != nil {
		return u, e
	}
	if e = s.Durable.Barrier(ctx, tx, command); e != nil {
		return u, e
	}
	if e = s.Narration.Control(ctx, tx, run, "FORCE_INTERRUPT"); e != nil {
		return u, e
	}
	u, e = q.GetUtterance(ctx, u.ID)
	if e != nil {
		return u, e
	}
	return u, tx.Commit(ctx)
}
func (s *Service) durableControl(ctx context.Context, id, trace, kind, reason string) (string, error) {
	tx, e := durability.BeginBusiness(ctx, s.DB)
	if e != nil {
		return "", e
	}
	defer tx.Rollback(ctx)
	var r durability.Run
	if kind == "STOP_SESSION" {
		r, e = s.Durable.CleanupRun(ctx, tx, id)
	} else {
		r, e = s.Durable.Current(ctx, tx, id, false)
	}
	if e != nil {
		return "", e
	}
	q := s.Q.WithTx(tx)
	se, e := q.GetSession(ctx, id)
	if e != nil {
		return "", e
	}
	if kind == "STOP_SESSION" {
		if se.Status != "LIVE" && se.Status != "DEGRADED" && se.Status != "STOPPING" {
			return "", ErrConflict
		}
		if e = s.Durable.Seal(ctx, tx, r); e != nil {
			return "", e
		}
		r.Status = "STOPPING"
		_, e = tx.Exec(ctx, `UPDATE live_sessions SET status='STOPPING',updated_at=clock_timestamp() WHERE id=$1`, id)
		if e != nil {
			return "", e
		}
	} else if r.Status != "ACTIVE" || se.Status != "LIVE" && se.Status != "DEGRADED" {
		return "", ErrConflict
	}
	key := ids.New("control")
	if kind == "STOP_SESSION" {
		key = "stop"
	}
	c, e := s.Durable.Enqueue(ctx, tx, r, kind, key, trace, "", map[string]any{"reason": reason})
	if e != nil {
		return "", e
	}
	if e = s.Durable.Barrier(ctx, tx, c); e != nil {
		return "", e
	}
	if s.Narration != nil {
		if e = s.Narration.Control(ctx, tx, r, kind); e != nil {
			return "", e
		}
	}
	if e = tx.Commit(ctx); e != nil {
		return "", e
	}
	if s.Interaction != nil {
		if kind == "STOP_SESSION" {
			s.Interaction.Stop(id)
		} else {
			s.Interaction.Override(id)
		}
	}
	return c.CommandID, nil
}
func (s *Service) durableStart(ctx context.Context, id, trace string) (string, error) {
	se, e := s.Q.GetSession(ctx, id)
	if e != nil {
		return "", e
	}
	if se.Status != "CREATED" {
		return "", ErrConflict
	}
	ro, e := s.Q.GetRoom(ctx, se.RoomID)
	if e != nil {
		return "", e
	}
	av, e := s.Q.GetAvatar(ctx, ro.AvatarID)
	if e != nil {
		return "", e
	}
	vo, e := s.Q.GetVoice(ctx, ro.VoiceID)
	if e != nil {
		return "", e
	}
	req := runtimeapi.CreateRuntimeSessionRequest{CommandId: ids.New("legacy_cmd"), TraceId: trace, SessionId: id}
	req.Avatar.AvatarId, req.Avatar.Engine = av.ID, av.Engine
	req.Voice.VoiceId, req.Voice.Provider = vo.ID, vo.Provider
	req.Config.Fps, req.Config.Preview.Type = 25, runtimeapi.WEBRTC
	req.Context.RoomId, req.Context.SystemPrompt = ro.ID, ro.SystemPrompt
	if ro.ActiveProductID.Valid {
		req.Context.ActiveProductId = &ro.ActiveProductID.String
	}
	if ro.KnowledgeBaseID.Valid {
		req.Context.KnowledgeBaseId = &ro.KnowledgeBaseID.String
	}
	if s.Integration == nil {
		return "", durability.ErrFence
	}
	if e = s.Integration.Prepare(ctx, id, &req); e != nil {
		return "", e
	}
	tx, e := durability.BeginBusiness(ctx, s.DB)
	if e != nil {
		return "", e
	}
	defer tx.Rollback(ctx)
	r, e := s.Durable.InitialRun(ctx, tx, id)
	if e != nil {
		return "", e
	}
	tag, e := tx.Exec(ctx, `UPDATE live_sessions SET status='PREPARING',updated_at=clock_timestamp() WHERE id=$1 AND status='CREATED'`, id)
	if e != nil {
		return "", e
	}
	if tag.RowsAffected() != 1 {
		return "", ErrConflict
	}
	c, e := s.Durable.Enqueue(ctx, tx, r, "BEGIN_RUN", "initial", trace, "", map[string]any{"expectedPreviousEpoch": 0, "createSession": req, "featureFlags": map[string]any{"contractRevision": "v0.5-frozen-1", "continuityEnabled": s.Narration != nil, "durabilityEnabled": true}})
	if e != nil {
		return "", e
	}
	_, e = tx.Exec(ctx, `UPDATE live_sessions SET runtime_operation_id=$2 WHERE id=$1`, id, c.CommandID)
	if e != nil {
		return "", e
	}
	return c.CommandID, tx.Commit(ctx)
}

// EmergencyStop is available only after authenticated Session/Room authorization in this request.
// It never reports durable acceptance while PostgreSQL is unavailable.
func (s *Service) EmergencyStop(ctx context.Context, id string) error {
	scope := userconfig.ScopeFromContext(ctx)
	if s.Integration == nil || scope.TenantID == "" || scope.UserID == "" {
		return durability.ErrFence
	}
	local, ok := s.Runtime.(interface {
		EmergencyStop(context.Context, string) error
	})
	if !ok {
		return durability.ErrFence
	}
	bounded, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	return local.EmergencyStop(bounded, id)
}
