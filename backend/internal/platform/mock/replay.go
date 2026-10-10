// Package mock implements reproducible synthetic rooms; it is never a real platform.
package mock

import (
	"astralive/backend/internal/platform"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"time"
)

type Record struct {
	SourceTimestamp *time.Time `json:"sourceTimestamp,omitempty"`
	AfterMS         int        `json:"afterMs"`
	SourceEventID   string     `json:"sourceEventId"`
	User            string     `json:"user"`
	Content         string     `json:"content"`
	Heartbeat       bool       `json:"heartbeat,omitempty"`
	Disconnect      bool       `json:"disconnect,omitempty"`
	Transport       string     `json:"transport,omitempty"`
}
type WaitFunc func(context.Context, time.Duration) error

func Wait(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

type Adapter struct {
	Mapping       platform.Mapping
	Records       []Record
	Wait          WaitFunc
	mu            sync.Mutex
	cancel        context.CancelFunc
	health        platform.Connection
	running       bool
	stopRequested bool
}

func Load(r io.Reader) ([]Record, error) {
	var rows []Record
	d := json.NewDecoder(io.LimitReader(r, 1<<20))
	d.DisallowUnknownFields()
	if e := d.Decode(&rows); e != nil {
		return nil, e
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return nil, &platform.Error{Class: platform.Invalid}
	}
	if len(rows) > 1000 {
		return nil, &platform.Error{Class: platform.Invalid}
	}
	for _, row := range rows {
		if row.AfterMS < 0 || row.AfterMS > 60000 || (!row.Disconnect && !row.Heartbeat && row.SourceEventID == "") {
			return nil, &platform.Error{Class: platform.Invalid}
		}
	}
	return rows, nil
}
func (a *Adapter) Capabilities() platform.Capabilities {
	return platform.Capabilities{Types: []platform.EventType{platform.Comment}, Transports: []string{"MOCK_REPLAY", "MOCK_BACKUP"}, Reconnect: true, SourceIdentity: true}
}
func (a *Adapter) Health() platform.Connection { a.mu.Lock(); defer a.mu.Unlock(); return a.health }
func (a *Adapter) Stop() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.stopRequested = true
	if a.cancel != nil {
		a.cancel()
	}
}
func (a *Adapter) Start(parent context.Context, sink platform.EventSink) error {
	a.mu.Lock()
	if a.stopRequested {
		a.mu.Unlock()
		return context.Canceled
	}
	if a.running {
		a.mu.Unlock()
		return fmt.Errorf("already running")
	}
	if a.Mapping.Platform != "mock" || len(a.Records) > 1000 {
		a.mu.Unlock()
		return &platform.Error{Class: platform.Invalid}
	}
	ctx, cancel := context.WithCancel(parent)
	a.cancel = cancel
	a.running = true
	a.health = platform.Connection{State: "CONNECTED"}
	a.mu.Unlock()
	defer func() { cancel(); a.mu.Lock(); a.running = false; a.health.State = "STOPPED"; a.mu.Unlock() }()
	wait := a.Wait
	if wait == nil {
		wait = Wait
	}
	for _, r := range a.Records {
		if r.AfterMS < 0 || r.AfterMS > 60000 {
			return &platform.Error{Class: platform.Invalid}
		}
		if err := wait(ctx, time.Duration(r.AfterMS)*time.Millisecond); err != nil {
			return err
		}
		if r.Heartbeat {
			a.mu.Lock()
			a.health.Heartbeats++
			a.mu.Unlock()
			continue
		}
		if r.Disconnect {
			a.mu.Lock()
			a.health.State = "RECONNECTING"
			a.mu.Unlock()
			if err := wait(ctx, 100*time.Millisecond); err != nil {
				return err
			}
			a.mu.Lock()
			a.health.Reconnects++
			a.health.State = "CONNECTED"
			a.mu.Unlock()
			continue
		}
		transport := r.Transport
		if transport == "" {
			transport = "MOCK_REPLAY"
		}
		if transport != "MOCK_REPLAY" && transport != "MOCK_BACKUP" {
			return &platform.Error{Class: platform.Invalid}
		}
		e := platform.Event{Platform: "mock", PlatformRoomID: a.Mapping.PlatformRoomID, InternalRoomID: a.Mapping.RoomID, SessionID: a.Mapping.SessionID, SourceEventID: r.SourceEventID, EventType: platform.Comment, UserExternalID: r.User, Nickname: "模拟观众", Content: r.Content, Transport: transport, SourceTimestamp: r.SourceTimestamp}
		if err := sink.Receive(ctx, e); err != nil {
			a.mu.Lock()
			a.health.ErrorClass = string(platform.Classify(err))
			a.mu.Unlock()
			return err
		}
		a.mu.Lock()
		a.health.Received++
		a.mu.Unlock()
	}
	return nil
}
func Scenario(rate, count int) []Record {
	rows := make([]Record, 0, count)
	for i := 0; i < count; i++ {
		delay := 0
		if rate > 0 {
			delay = 1000 / rate
		}
		questions := []string{"有 XL 吗？", "主播 XL 码有吗？", "XL 有没有库存？", "商品还有库存吗？", "多少钱？", "你好主播", "材质是什么？"}
		rows = append(rows, Record{AfterMS: delay, SourceEventID: fmt.Sprintf("replay-%d", i), User: fmt.Sprintf("viewer-%d", i%31), Content: questions[i%len(questions)]})
	}
	return rows
}
