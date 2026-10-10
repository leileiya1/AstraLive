package app

import (
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	mockplatform "astralive/backend/internal/platform/mock"
	"astralive/backend/internal/userconfig"
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"sync"
	"time"
)

type InteractionController struct {
	service  *Service
	config   *userconfig.Service
	root     context.Context
	mu       sync.Mutex
	entries  map[string]*interactionEntry
	limiter  interaction.Limiter
	settings interaction.Config
}
type interactionEntry struct {
	scheduler     *interaction.Scheduler
	cancel        context.CancelFunc
	replay        *mockplatform.Adapter
	scope         userconfig.Scope
	roomID        string
	touched       time.Time
	replayRunning bool
}
type InteractionSnapshot struct {
	interaction.Snapshot
	Adapter  platform.Connection `json:"adapter"`
	Platform string              `json:"platform"`
}

func NewInteraction(ctx context.Context, s *Service, cfg *userconfig.Service, c interaction.Config) *InteractionController {
	return &InteractionController{service: s, config: cfg, root: ctx, entries: map[string]*interactionEntry{}, settings: c}
}
func (c *InteractionController) Ensure(ctx context.Context, scope userconfig.Scope, sid string) (*interaction.Scheduler, error) {
	if c.config == nil {
		return nil, errors.New("authentication required")
	}
	if err := c.config.CheckOwner(ctx, scope, "session", sid); err != nil {
		return nil, err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if e := c.entries[sid]; e != nil {
		if e.scope != scope {
			return nil, ErrConflict
		}
		return e.scheduler, nil
	}
	for id, e := range c.entries {
		if e.scheduler.Snapshot().Stopped && time.Since(e.touched) > time.Minute {
			delete(c.entries, id)
		}
	}
	if len(c.entries) >= 64 {
		return nil, errors.New("interaction capacity reached")
	}
	se, err := c.service.Q.GetSession(ctx, sid)
	if err != nil {
		return nil, err
	}
	if se.Status != "LIVE" && se.Status != "DEGRADED" {
		return nil, ErrConflict
	}
	for _, entry := range c.entries {
		if entry.roomID == se.RoomID && !entry.scheduler.Snapshot().Stopped {
			return nil, ErrConflict
		}
	}
	room, err := c.service.Q.GetRoom(ctx, se.RoomID)
	if err != nil {
		return nil, err
	}
	if err = c.config.CheckOwner(ctx, scope, "room", se.RoomID); err != nil {
		return nil, err
	}
	product := room.ActiveProductID.String
	if c.config.IntegrationEnabled {
		var pinned string
		err = c.service.DB.QueryRow(ctx, `SELECT COALESCE(room_snapshot->>'activeProductId','') FROM session_provider_bindings WHERE session_id=$1 AND released_at IS NULL`, sid).Scan(&pinned)
		if err != nil {
			return nil, err
		}
		if pinned != product {
			return nil, ErrConflict
		}
	}
	d := &interactionDispatcher{controller: c, scope: scope, sid: sid, room: se.RoomID}
	gate := func(ctx context.Context) (interaction.Gate, error) { return c.gate(ctx, sid, se.RoomID) }
	scheduler, err := interaction.New(c.settings, platform.Mapping{Platform: "mock", PlatformRoomID: se.RoomID, RoomID: se.RoomID, SessionID: sid}, product, d, gate, nil, &c.limiter)
	if err != nil {
		return nil, err
	}
	workerCtx, cancel := context.WithCancel(c.root)
	c.entries[sid] = &interactionEntry{scheduler: scheduler, cancel: cancel, scope: scope, roomID: se.RoomID, touched: time.Now()}
	go func() {
		tick := time.NewTicker(c.settings.Interval)
		defer tick.Stop()
		for {
			select {
			case <-workerCtx.Done():
				scheduler.Stop()
				return
			case <-tick.C:
				ctx, done := context.WithTimeout(workerCtx, 8*time.Second)
				_ = scheduler.Tick(ctx)
				done()
				if scheduler.Snapshot().Stopped {
					return
				}
			}
		}
	}()
	return scheduler, nil
}
func (c *InteractionController) gate(ctx context.Context, sid, roomID string) (interaction.Gate, error) {
	se, err := c.service.Q.GetSession(ctx, sid)
	if err != nil {
		return interaction.Gate{}, err
	}
	ro, err := c.service.Q.GetRoom(ctx, roomID)
	if err != nil {
		return interaction.Gate{}, err
	}
	gate := interaction.Gate{Running: se.RoomID == roomID && (se.Status == "LIVE" || se.Status == "DEGRADED"), ProductID: ro.ActiveProductID.String}
	err = c.service.DB.QueryRow(ctx, `SELECT id,source,priority FROM utterances WHERE session_id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED') ORDER BY created_at LIMIT 1`, sid).Scan(&gate.CurrentUtteranceID, &gate.CurrentSource, &gate.CurrentPriority)
	if errors.Is(err, pgx.ErrNoRows) {
		err = nil
	} else if err == nil {
		gate.Busy = true
	}
	return gate, err
}

type interactionDispatcher struct {
	controller *InteractionController
	scope      userconfig.Scope
	sid, room  string
}

func (d *interactionDispatcher) Dispatch(ctx context.Context, v interaction.Selection) (string, error) {
	s := d.controller.service
	// Serialize Stop/operator/Speak admission. Separate schedulers cannot race the busy check.
	s.commands.Lock()
	defer s.commands.Unlock()
	s.Log.Info("interaction_trace", "traceId", v.Event.TraceID, "sessionId", d.sid, "stage", "comment_received", "clockDomain", "go_monotonic", "elapsedMs", 0)
	s.Log.Info("interaction_trace", "traceId", v.Event.TraceID, "sessionId", d.sid, "stage", "scheduler_selected", "clockDomain", "go_monotonic", "elapsedMs", float64(v.SelectedAt.Sub(v.Event.ReceivedAt).Microseconds())/1000)
	if v.Event.SessionID != d.sid || v.Event.InternalRoomID != d.room {
		return "", ErrConflict
	}
	if err := d.controller.config.CheckOwner(ctx, d.scope, "session", d.sid); err != nil {
		return "", err
	}
	gate, err := d.controller.gate(ctx, d.sid, d.room)
	if err != nil {
		return "", err
	}
	if d.controller.Snapshot(d.sid).Mode == interaction.OperatorOverride || !gate.Running || (gate.Busy && !(v.Policy == "INTERRUPT_LOWER_PRIORITY" && gate.CurrentSource == "AUTO_SCRIPT" && v.Priority > gate.CurrentPriority)) || gate.ProductID != v.ProductID {
		return "", ErrConflict
	}
	tag, err := s.DB.Exec(ctx, `INSERT INTO interaction_receipts(session_id,trace_id,status) VALUES($1,$2,'RESERVED') ON CONFLICT DO NOTHING`, d.sid, v.Event.TraceID)
	if err != nil {
		return "", err
	}
	if tag.RowsAffected() != 1 {
		return "", ErrConflict
	}
	platformContext := &runtimeapi.PlatformContext{EventType: runtimeapi.COMMENT}
	platformContext.User.ExternalId = v.Event.UserExternalID
	platformContext.User.Nickname = v.Event.Nickname
	u, err := s.speak(ctx, d.sid, v.Event.Content, int32(v.Priority), v.Policy, "PLATFORM_EVENT", v.Event.TraceID, platformContext)
	if err == nil {
		s.Log.Info("interaction_trace", "traceId", v.Event.TraceID, "sessionId", d.sid, "utteranceId", u.ID, "stage", "utterance_accepted", "clockDomain", "go_monotonic", "elapsedMs", float64(time.Since(v.Event.ReceivedAt).Microseconds())/1000)
	}
	status := "ACCEPTED"
	if err != nil {
		status = "FAILED"
	}
	_, persistErr := s.DB.Exec(ctx, `UPDATE interaction_receipts SET status=$3,utterance_id=NULLIF($4,'') WHERE session_id=$1 AND trace_id=$2`, d.sid, v.Event.TraceID, status, u.ID)
	if err != nil {
		return u.ID, err
	}
	return u.ID, persistErr
}
func (c *InteractionController) Stop(sid string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if e := c.entries[sid]; e != nil {
		e.cancel()
		e.scheduler.Stop()
		if e.replay != nil {
			e.replay.Stop()
		}
		e.touched = time.Now()
	}
}
func (c *InteractionController) Override(sid string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if e := c.entries[sid]; e != nil {
		_ = e.scheduler.SetMode(interaction.OperatorOverride)
	}
}
func (c *InteractionController) Snapshot(sid string) InteractionSnapshot {
	c.mu.Lock()
	defer c.mu.Unlock()
	v := InteractionSnapshot{Platform: "mock", Adapter: platform.Connection{State: "DISCONNECTED"}}
	if e := c.entries[sid]; e != nil {
		v.Snapshot = e.scheduler.Snapshot()
		if e.replay != nil {
			v.Adapter = e.replay.Health()
		}
	}
	return v
}
func (c *InteractionController) Replay(sid string, rows []mockplatform.Record) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	e := c.entries[sid]
	if e == nil || e.scheduler.Snapshot().Stopped {
		return ErrConflict
	}
	if e.replayRunning {
		return ErrConflict
	}
	se, err := c.service.Q.GetSession(c.root, sid)
	if err != nil {
		return err
	}
	a := &mockplatform.Adapter{Mapping: platform.Mapping{Platform: "mock", PlatformRoomID: se.RoomID, RoomID: se.RoomID, SessionID: sid}, Records: rows}
	e.replay = a
	e.replayRunning = true
	go func() { _ = a.Start(c.root, e.scheduler); c.mu.Lock(); e.replayRunning = false; c.mu.Unlock() }()
	return nil
}
func (c *InteractionController) StopReplay(sid string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if e := c.entries[sid]; e != nil && e.replay != nil {
		e.replay.Stop()
	}
}

// QueueLength projects an aggregate without exposing identity in metric labels.
func (c *InteractionController) QueueLength() float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	n := 0
	for _, e := range c.entries {
		n += e.scheduler.Snapshot().Candidates
	}
	return float64(n)
}
