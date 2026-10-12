package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/fsm"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/metrics"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/sse"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Service struct {
	commands     sync.Mutex
	Durable      *durability.Store
	Narration    *narration.Controller
	sessionLocks sync.Map
	Interaction  *InteractionController
	Integration  SessionIntegration
	DB           *pgxpool.Pool
	Q            *dbgen.Queries
	Runtime      runtime.Client
	Hub          *sse.Hub
	Log          *slog.Logger
}

func New(db *pgxpool.Pool, rt runtime.Client, log *slog.Logger) *Service {
	return &Service{DB: db, Q: dbgen.New(db), Runtime: rt, Hub: sse.New(), Log: log}
}
func txt(v string) pgtype.Text { return pgtype.Text{String: v, Valid: v != ""} }

func providerFailureCode(err error) string {
	var integration interface{ IntegrationCode() string }
	if errors.As(err, &integration) {
		switch code := integration.IntegrationCode(); code {
		case "PROVIDER_BINDING_EXPIRED", "PROVIDER_BINDING_UNAVAILABLE", "CONFIG_NOT_VERIFIED", "WORKER_NOT_READY", "WORKER_UNAVAILABLE", "WORKER_UNREGISTERED", "PROVIDER_NOT_CONFIGURED", "PROVIDER_UNSUPPORTED", "PROVIDER_BINDING_INVALID":
			return code
		}
	}
	return "RUNTIME_UNAVAILABLE"
}

var ErrConflict = errors.New("invalid state transition")

func (s *Service) transitionSession(ctx context.Context, id, to string) error {
	cur, e := s.Q.GetSession(ctx, id)
	if e != nil {
		return e
	}
	if !fsm.Session(cur.Status, to) {
		return ErrConflict
	}
	n, e := s.Q.TransitionSession(ctx, dbgen.TransitionSessionParams{ID: id, Status: cur.Status, Status_2: to})
	if e != nil {
		return e
	}
	if n != 1 {
		return ErrConflict
	}
	return nil
}
func (s *Service) Start(ctx context.Context, id, trace string) (string, error) {
	if s.Durable != nil {
		return s.durableStart(ctx, id, trace)
	}
	se, e := s.Q.GetSession(ctx, id)
	if e != nil {
		return "", e
	}
	if !fsm.Session(se.Status, "PREPARING") {
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
	if s.Integration == nil && av.Status != "READY" && av.Engine != "MOCK" {
		return "", fmt.Errorf("AVATAR_NOT_READY")
	}
	vo, e := s.Q.GetVoice(ctx, ro.VoiceID)
	if e != nil {
		return "", e
	}
	if e = s.transitionSession(ctx, id, "PREPARING"); e != nil {
		return "", e
	}
	req := runtimeapi.CreateRuntimeSessionRequest{CommandId: ids.New("cmd"), TraceId: trace, SessionId: id}
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
	if s.Integration != nil {
		if e = s.Integration.Prepare(ctx, id, &req); e != nil {
			_, _ = s.Q.FailSession(ctx, dbgen.FailSessionParams{ID: id, FailureCode: txt(providerFailureCode(e)), FailureMessage: txt("provider binding unavailable"), Status: "PREPARING"})
			_ = s.release(id)
			return "", e
		}
	}
	op, e := s.Runtime.CreateSession(ctx, req)
	if e != nil {
		_, _ = s.Q.FailSession(ctx, dbgen.FailSessionParams{ID: id, FailureCode: txt(providerFailureCode(e)), FailureMessage: txt("runtime command failed"), Status: "PREPARING"})
		_ = s.release(id)
		return "", e
	}
	_, e = s.Q.SetRuntimeOperation(ctx, dbgen.SetRuntimeOperationParams{ID: id, RuntimeOperationID: txt(op.OperationID)})
	return op.OperationID, e
}
func (s *Service) Stop(ctx context.Context, id, trace string) (string, error) {
	if s.Durable != nil {
		return s.durableControl(ctx, id, trace, "STOP_SESSION", "")
	}
	unlock := s.lockCommands(id)
	defer unlock()
	if e := s.transitionSession(ctx, id, "STOPPING"); e != nil {
		return "", e
	}
	if s.Interaction != nil {
		s.Interaction.Stop(id)
	}
	op, e := s.Runtime.StopSession(ctx, id, map[string]any{"commandId": ids.New("cmd"), "traceId": trace})
	if e != nil {
		_, _ = s.Q.FailSession(ctx, dbgen.FailSessionParams{ID: id, FailureCode: txt("RUNTIME_UNAVAILABLE"), FailureMessage: txt("runtime command failed"), Status: "STOPPING"})
		_ = s.release(id)
		return "", e
	}
	return op.OperationID, nil
}

// Interrupt shares the command boundary with automatic admission and Stop.
func (s *Service) Interrupt(ctx context.Context, id, trace, reason string) (runtime.Operation, error) {
	if s.Durable != nil {
		op, e := s.durableControl(ctx, id, trace, "FORCE_INTERRUPT", reason)
		return runtime.Operation{Accepted: e == nil, OperationID: op}, e
	}
	unlock := s.lockCommands(id)
	defer unlock()
	if s.Interaction != nil {
		s.Interaction.Override(id)
	}
	return s.Runtime.Interrupt(ctx, id, map[string]any{"commandId": ids.New("cmd"), "traceId": trace, "reason": reason})
}

func (s *Service) Speak(ctx context.Context, id, text string, priority int32, policy, source, trace string, platform *runtimeapi.PlatformContext) (dbgen.Utterance, error) {
	unlock := s.lockCommands(id)
	defer unlock()
	if s.Narration != nil {
		// Timeline binding lasts for the captured run, including before the first
		// narration command and after finish. There is no approved legacy handoff.
		if policy == "FORCE" {
			return s.failedNarrationForce(ctx, id, text, priority, source, trace)
		}
		return dbgen.Utterance{}, ErrConflict
	}
	if source == "OPERATOR" && s.Interaction != nil {
		s.Interaction.Override(id)
	}
	return s.speak(ctx, id, text, priority, policy, source, trace, platform)
}

func (s *Service) speak(ctx context.Context, id, text string, priority int32, policy, source, trace string, platform *runtimeapi.PlatformContext) (dbgen.Utterance, error) {
	if s.Durable != nil {
		return s.durableSpeak(ctx, id, text, priority, policy, source, trace, platform, false)
	}
	se, e := s.Q.GetSession(ctx, id)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	if se.Status != "LIVE" && se.Status != "DEGRADED" {
		return dbgen.Utterance{}, ErrConflict
	}
	ro, e := s.Q.GetRoom(ctx, se.RoomID)
	if e != nil {
		return dbgen.Utterance{}, e
	}
	u, e := s.Q.CreateUtterance(ctx, dbgen.CreateUtteranceParams{ID: ids.New("utt"), SessionID: id, Text: text, Priority: priority, InterruptPolicy: policy, Source: source, TraceID: trace})
	if e != nil {
		return u, e
	}
	metrics.UtteranceCount.Inc()
	req := runtimeapi.RuntimeUtteranceRequest{CommandId: ids.New("cmd"), TraceId: trace, UtteranceId: u.ID, Text: text, Priority: int(priority), InterruptPolicy: runtimeapi.InterruptPolicy(policy), Source: runtimeapi.UtteranceSource(source), PlatformContext: platform}
	req.Voice.VoiceId = ro.VoiceID
	_, e = s.Runtime.Speak(ctx, id, req)
	if e != nil {
		_, _ = s.Q.FailUtterance(ctx, dbgen.FailUtteranceParams{ID: u.ID, FailureCode: txt("RUNTIME_UNAVAILABLE")})
		metrics.UtteranceFailedCount.Inc()
		return u, e
	}
	return u, nil
}

type Event struct {
	SchemaVersion string         `json:"schemaVersion"`
	EventID       string         `json:"eventId"`
	EventType     string         `json:"eventType"`
	SessionID     string         `json:"sessionId"`
	UtteranceID   *string        `json:"utteranceId"`
	TraceID       string         `json:"traceId"`
	OccurredAt    time.Time      `json:"occurredAt"`
	Source        string         `json:"source"`
	Payload       map[string]any `json:"payload"`
}

var eventNames = map[string]string{"SESSION_PREPARING": "session.preparing", "SESSION_READY": "session.ready", "SESSION_STARTED": "session.live", "SESSION_DEGRADED": "session.degraded", "SESSION_ENDED": "session.ended", "SESSION_FAILED": "session.failed", "UTTERANCE_QUEUED": "utterance.queued", "UTTERANCE_GENERATING": "utterance.generating", "UTTERANCE_SYNTHESIZING": "utterance.synthesizing", "UTTERANCE_RENDERING": "utterance.rendering", "UTTERANCE_PLAYING": "utterance.playing", "UTTERANCE_COMPLETED": "utterance.completed", "UTTERANCE_INTERRUPTED": "utterance.interrupted", "UTTERANCE_FAILED": "utterance.failed", "MEDIA_READY": "media.ready", "RUNTIME_WARNING": "runtime.warning", "RUNTIME_ERROR": "runtime.error", "MEDIA_FAILED": "media.failed", "SESSION_STOPPING": "session.stopping"}

func SSEName(eventType string) string { return eventNames[eventType] }

func (e Event) Validate() error {
	if e.SchemaVersion != "1.0" || e.EventID == "" || e.SessionID == "" || e.TraceID == "" || e.Source != "AI_RUNTIME" || e.OccurredAt.IsZero() || e.OccurredAt.Location() != time.UTC || e.Payload == nil {
		return fmt.Errorf("invalid runtime event envelope")
	}
	if _, ok := eventNames[e.EventType]; !ok {
		return fmt.Errorf("unknown event type %q", e.EventType)
	}
	if len(e.EventType) >= 10 && e.EventType[:10] == "UTTERANCE_" && (e.UtteranceID == nil || *e.UtteranceID == "") {
		return fmt.Errorf("utteranceId required")
	}
	return nil
}

// ApplyEvent makes legacy event storage and FSM transitions atomic.
func (s *Service) ApplyEvent(ctx context.Context, e Event) (bool, error) {
	if err := e.Validate(); err != nil {
		return false, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)
	applied, err := s.applyEventTx(ctx, tx, e)
	if err != nil || !applied {
		return applied, err
	}
	if err = tx.Commit(ctx); err != nil {
		return false, err
	}
	return true, s.afterEvent(ctx, e)
}
func (s *Service) applyEventTx(ctx context.Context, tx pgx.Tx, e Event) (bool, error) {
	b, _ := json.Marshal(e)
	var err error
	q := s.Q.WithTx(tx)
	var uid pgtype.Text
	if e.UtteranceID != nil {
		uid = txt(*e.UtteranceID)
	}
	_, err = q.InsertRuntimeEvent(ctx, dbgen.InsertRuntimeEventParams{EventID: e.EventID, SessionID: e.SessionID, EventType: e.EventType, UtteranceID: uid, TraceID: e.TraceID, OccurredAt: pgtype.Timestamptz{Time: e.OccurredAt, Valid: true}, Envelope: b})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var target string
	switch e.EventType {
	case "SESSION_PREPARING":
		target = "PREPARING"
	case "SESSION_READY":
		target = "READY"
	case "SESSION_STARTED":
		target = "LIVE"
	case "SESSION_DEGRADED":
		target = "DEGRADED"
	case "SESSION_STOPPING":
		target = "STOPPING"
	case "SESSION_ENDED":
		target = "ENDED"
	case "SESSION_FAILED":
		target = "FAILED"
	}
	if target != "" {
		cur, er := q.GetSession(ctx, e.SessionID)
		if er != nil {
			return false, er
		}
		if cur.Status == target && (e.EventType == "SESSION_PREPARING" || e.EventType == "SESSION_STOPPING") {
			// Confirmation of a transition already made by Go.
		} else if s.Durable != nil && (cur.Status == "ENDED" || cur.Status == "FAILED" || cur.Status == "STOPPING" && target != "ENDED" && target != "FAILED") {
			// Late event is audit-only.
		} else if !fsm.Session(cur.Status, target) {
			return false, ErrConflict
		} else {
			n, er := q.TransitionSession(ctx, dbgen.TransitionSessionParams{ID: e.SessionID, Status: cur.Status, Status_2: target})
			if er != nil {
				return false, er
			}
			if n != 1 {
				return false, ErrConflict
			}
		}
	}
	if e.EventType == "SESSION_FAILED" {
		code, _ := e.Payload["code"].(string)
		switch code {
		case "WORKER_NOT_READY", "PROVIDER_BINDING_EXPIRED", "PROVIDER_START_FAILED", "PROVIDER_PREPARE_FAILED", "PROVIDER_AUTH_FAILED", "LLM_FAILED":
		default:
			code = "PROVIDER_UNAVAILABLE"
		}
		if _, er := tx.Exec(ctx, `UPDATE live_sessions SET failure_code=$2,failure_message='provider session failed' WHERE id=$1`, e.SessionID, code); er != nil {
			return false, er
		}
	}
	switch e.EventType {
	case "UTTERANCE_QUEUED":
		target = "QUEUED"
	case "UTTERANCE_GENERATING":
		target = "GENERATING"
	case "UTTERANCE_SYNTHESIZING":
		target = "SYNTHESIZING"
	case "UTTERANCE_RENDERING":
		target = "RENDERING"
	case "UTTERANCE_PLAYING":
		target = "PLAYING"
	case "UTTERANCE_COMPLETED":
		target = "COMPLETED"
	case "UTTERANCE_INTERRUPTED":
		target = "INTERRUPTED"
	case "UTTERANCE_FAILED":
		target = "FAILED"
	default:
		target = ""
	}
	if target != "" {
		cur, er := q.GetUtterance(ctx, *e.UtteranceID)
		if er != nil {
			return false, er
		}
		if s.Durable != nil && cur.SessionID == e.SessionID && obsoleteUtterance(cur.Status, target) {
			target = cur.Status
		}
		if cur.SessionID != e.SessionID || (cur.Status != target && !fsm.Utterance(cur.Status, target)) {
			return false, ErrConflict
		}
		if cur.Status != target {
			n, er := q.TransitionUtterance(ctx, dbgen.TransitionUtteranceParams{ID: cur.ID, Status: cur.Status, Status_2: target})
			if er != nil {
				return false, er
			}
			if n != 1 {
				return false, ErrConflict
			}
		}
	}
	if s.Durable != nil && e.EventType == "SESSION_READY" {
		se, er := q.GetSession(ctx, e.SessionID)
		if er != nil {
			return false, er
		}
		if se.Status == "READY" {
			r, er := s.Durable.Current(ctx, tx, e.SessionID, false)
			if er != nil {
				return false, er
			}
			if r.Status == "ACTIVE" {
				if _, er = tx.Exec(ctx, `UPDATE live_sessions SET status='STARTING' WHERE id=$1 AND status='READY'`, e.SessionID); er != nil {
					return false, er
				}
				if _, er = s.Durable.Enqueue(ctx, tx, r, "START_SESSION", "start", e.TraceID, "", map[string]any{}); er != nil {
					return false, er
				}
			}
		}
	}
	if s.Durable != nil && s.Narration != nil && e.EventType == "SESSION_ENDED" {
		if err := s.Narration.FinalizeStop(ctx, tx, e.SessionID); err != nil {
			return false, err
		}
	}
	return true, nil
}
func (s *Service) afterEvent(ctx context.Context, e Event) error {
	var err error
	b, _ := json.Marshal(e)
	if e.EventType == "UTTERANCE_FAILED" {
		metrics.UtteranceFailedCount.Inc()
	}
	if e.EventType == "SESSION_ENDED" || e.EventType == "SESSION_FAILED" {
		if s.Interaction != nil {
			s.Interaction.Stop(e.SessionID)
		}
		if er := s.release(e.SessionID); er != nil {
			s.Log.Error("binding cleanup pending", "sessionId", e.SessionID)
		}
	}
	s.Hub.Publish(e.SessionID, sse.Message{Name: eventNames[e.EventType], Data: b})
	if s.Durable == nil && e.EventType == "SESSION_READY" {
		if err = s.transitionSession(ctx, e.SessionID, "STARTING"); err != nil {
			return err
		}
		_, err = s.Runtime.StartSession(ctx, e.SessionID, map[string]any{"commandId": ids.New("cmd"), "traceId": e.TraceID})
		if err != nil {
			s.Log.Error("runtime start failed", "sessionId", e.SessionID)
			_, _ = s.Q.FailSession(ctx, dbgen.FailSessionParams{ID: e.SessionID, FailureCode: txt("RUNTIME_UNAVAILABLE"), FailureMessage: txt("runtime command failed"), Status: "STARTING"})
			_ = s.release(e.SessionID)
		}
	}
	return err
}

func (s *Service) release(id string) error {
	if s.Integration == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return s.Integration.Release(ctx, id)
}

func (s *Service) lockCommands(id string) func() {
	if s.Durable == nil {
		s.commands.Lock()
		return s.commands.Unlock
	}
	v, _ := s.sessionLocks.LoadOrStore(id, &sync.Mutex{})
	m := v.(*sync.Mutex)
	m.Lock()
	return m.Unlock
}
