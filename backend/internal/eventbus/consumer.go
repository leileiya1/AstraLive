package eventbus

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"astralive/backend/internal/app"
	"astralive/backend/internal/metrics"
	"github.com/redis/go-redis/v9"
)

type Consumer struct {
	Redis               *redis.Client
	Service             *app.Service
	Stream, Group, Name string
	Log                 *slog.Logger
	failures            map[string]int
}

func New(r *redis.Client, s *app.Service, stream string, l *slog.Logger) *Consumer {
	return &Consumer{Redis: r, Service: s, Stream: stream, Group: "astralive-go", Name: fmt.Sprintf("backend-%d", time.Now().UnixNano()), Log: l, failures: map[string]int{}}
}
func (c *Consumer) Run(ctx context.Context) error {
	e := c.Redis.XGroupCreateMkStream(ctx, c.Stream, c.Group, "0").Err()
	if e != nil && !strings.Contains(e.Error(), "BUSYGROUP") {
		return e
	}
	for ctx.Err() == nil {
		msgs, _, e := c.Redis.XAutoClaim(ctx, &redis.XAutoClaimArgs{Stream: c.Stream, Group: c.Group, Consumer: c.Name, MinIdle: 15 * time.Second, Start: "0-0", Count: 20}).Result()
		if e == nil {
			for _, m := range msgs {
				c.handle(ctx, m)
			}
		} else if e != redis.Nil {
			c.Log.Warn("claim events failed", "error", e)
		}
		streams, e := c.Redis.XReadGroup(ctx, &redis.XReadGroupArgs{Group: c.Group, Consumer: c.Name, Streams: []string{c.Stream, ">"}, Count: 20, Block: 2 * time.Second}).Result()
		if e == redis.Nil {
			continue
		}
		if e != nil {
			if ctx.Err() != nil {
				return nil
			}
			c.Log.Warn("read events failed", "error", e)
			time.Sleep(time.Second)
			continue
		}
		for _, st := range streams {
			for _, m := range st.Messages {
				c.handle(ctx, m)
			}
		}
	}
	return nil
}
func (c *Consumer) handle(ctx context.Context, m redis.XMessage) {
	var raw []byte
	if s, ok := m.Values["data"].(string); ok {
		raw = []byte(s)
	} else if s, ok := m.Values["event"].(string); ok {
		raw = []byte(s)
	} else {
		raw, _ = json.Marshal(m.Values)
	}
	var ev app.Event
	e := json.Unmarshal(raw, &ev)
	if e == nil {
		if !ev.OccurredAt.IsZero() {
			metrics.RedisEventLag.Set(time.Since(ev.OccurredAt).Seconds())
		}
		_, e = c.Service.ApplyEvent(ctx, ev)
	}
	if e == nil {
		_ = c.Redis.XAck(ctx, c.Stream, c.Group, m.ID).Err()
		delete(c.failures, m.ID)
		return
	}
	c.failures[m.ID]++
	c.Log.Error("runtime event rejected", "streamId", m.ID, "eventId", ev.EventID, "attempt", c.failures[m.ID], "error", e)
	if c.failures[m.ID] >= 5 {
		if err := c.Redis.XAdd(ctx, &redis.XAddArgs{Stream: c.Stream + ".dlq", Values: map[string]any{"data": string(raw), "reason": e.Error(), "streamId": m.ID}}).Err(); err == nil {
			_ = c.Redis.XAck(ctx, c.Stream, c.Group, m.ID).Err()
			delete(c.failures, m.ID)
		}
	}
}
