package durablelive

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"
	"time"
)

// ObserveLegacyEvent archives v1 observations for managed utterances. Their wire
// envelope has no run epoch or full drain proof, so it cannot change dl05 state.
// Return managed=true to prevent the legacy FSM from independently projecting it.
func (s *Store) ObserveLegacyEvent(ctx context.Context, raw []byte) (bool, error) {
	ev, e := Decode(raw)
	if e != nil {
		return false, e
	}
	if str(ev, "schemaVersion") != "1.0" || str(ev, "source") != "AI_RUNTIME" {
		return false, fault("INVALID_ARGUMENT")
	}
	var runID string
	e = s.DB.QueryRow(ctx, `SELECT run_id FROM dl05_attempts WHERE session_id=$1 AND utterance_id=$2`, ev["sessionId"], ev["utteranceId"]).Scan(&runID)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return true, e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return true, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO runtime_events(event_id,session_id,event_type,utterance_id,trace_id,occurred_at,envelope) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(event_id) DO NOTHING`, ev["eventId"], ev["sessionId"], ev["eventType"], ev["utteranceId"], ev["traceId"], ev["occurredAt"], ev)
	if e != nil {
		return true, e
	}
	a := Object{"sessionId": ev["sessionId"], "utteranceId": ev["utteranceId"]}
	if e = audit(ctx, tx, r, a, "LEGACY_OBSERVATION_ONLY", str(ev, "eventId")); e != nil {
		return true, e
	}
	return true, tx.Commit(ctx)
}

// ProjectNotification treats Redis as a hint for ALREADY persisted evidence.
// A Redis payload cannot create a journal fact or self-assert sink completion.
func (s *Store) ProjectNotification(ctx context.Context, p Principal, checkpointID string) error {
	if p.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	var runID string
	e := s.DB.QueryRow(ctx, `SELECT run_id FROM dl05_checkpoints WHERE checkpoint_id=$1 AND tenant_id=$2 AND owner_id=$3`, checkpointID, p.TenantID, p.OwnerID).Scan(&runID)
	if e != nil {
		return normErr(e)
	}
	return s.recoverRun(ctx, p, runID)
}

type RedisNotifications struct {
	Store               *Store
	Principal           Principal
	Redis               *redis.Client
	Stream, Group, Name string
}

func (c *RedisNotifications) Init(ctx context.Context) error {
	e := c.Redis.XGroupCreateMkStream(ctx, c.Stream, c.Group, "0").Err()
	if e != nil && e.Error() != "BUSYGROUP Consumer Group name already exists" {
		return e
	}
	return nil
}
func (c *RedisNotifications) Tick(ctx context.Context) error {
	msgs, _, e := c.Redis.XAutoClaim(ctx, &redis.XAutoClaimArgs{Stream: c.Stream, Group: c.Group, Consumer: c.Name, MinIdle: 15 * time.Second, Start: "0-0", Count: 20}).Result()
	if e != nil {
		return e
	}
	for _, m := range msgs {
		if e = c.message(ctx, m); e != nil {
			return e
		}
	}
	streams, e := c.Redis.XReadGroup(ctx, &redis.XReadGroupArgs{Group: c.Group, Consumer: c.Name, Streams: []string{c.Stream, ">"}, Count: 20, Block: 100 * time.Millisecond}).Result()
	if e == redis.Nil {
		return nil
	}
	if e != nil {
		return e
	}
	for _, stream := range streams {
		for _, m := range stream.Messages {
			if e = c.message(ctx, m); e != nil {
				return e
			}
		}
	}
	return nil
}
func (c *RedisNotifications) message(ctx context.Context, m redis.XMessage) error {
	id, _ := m.Values["checkpointId"].(string)
	e := c.Store.ProjectNotification(ctx, c.Principal, id)
	if e == nil {
		return c.Redis.XAck(ctx, c.Stream, c.Group, m.ID).Err()
	}
	// Database outages are retried without ACK or false DLQ classification.
	var f *Fault
	if !errors.As(e, &f) {
		return e
	}
	key := c.Stream + ":failure:" + m.ID
	count, err := c.Redis.Incr(ctx, key).Result()
	if err != nil {
		return err
	}
	_ = c.Redis.Expire(ctx, key, 24*time.Hour).Err()
	if count < 5 {
		return nil
	}
	if err = c.Redis.XAdd(ctx, &redis.XAddArgs{Stream: c.Stream + ":dlq", Values: map[string]any{"messageId": m.ID, "checkpointId": id, "code": f.Code}}).Err(); err != nil {
		return err
	}
	if _, err = c.Store.DB.Exec(ctx, `INSERT INTO dl05_recovery_audit(reason_code,evidence_ref) VALUES('REDIS_DLQ',$1) ON CONFLICT DO NOTHING`, c.Stream+":"+m.ID); err != nil {
		return err
	}
	return c.Redis.XAck(ctx, c.Stream, c.Group, m.ID).Err()
}

func (s *Store) IsManagedSession(ctx context.Context, sessionID string) (bool, error) {
	var yes bool
	e := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_sessions WHERE session_id=$1)`, sessionID).Scan(&yes)
	return yes, e
}
