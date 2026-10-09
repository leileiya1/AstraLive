package tests

import (
	"context"
	"io"
	"log/slog"
	"os"
	"testing"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/app"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/runtime"
	"github.com/jackc/pgx/v5/pgxpool"
)

type fakeRuntime struct{}

func (fakeRuntime) CreateSession(context.Context, any) (runtime.Operation, error) {
	return runtime.Operation{Accepted: true, OperationID: "op"}, nil
}
func (fakeRuntime) StartSession(context.Context, string, any) (runtime.Operation, error) {
	return runtime.Operation{Accepted: true, OperationID: "op"}, nil
}
func (fakeRuntime) Speak(context.Context, string, any) (runtime.Operation, error) {
	return runtime.Operation{Accepted: true, OperationID: "op"}, nil
}
func (fakeRuntime) WebRTCOffer(context.Context, string, runtimeapi.WebRTCOffer) (runtimeapi.WebRTCAnswer, error) {
	return runtimeapi.WebRTCAnswer{Type: runtimeapi.Answer, Sdp: "answer"}, nil
}
func (fakeRuntime) Interrupt(context.Context, string, any) (runtime.Operation, error) {
	return runtime.Operation{Accepted: true, OperationID: "op"}, nil
}
func (fakeRuntime) StopSession(context.Context, string, any) (runtime.Operation, error) {
	return runtime.Operation{Accepted: true, OperationID: "op"}, nil
}
func (fakeRuntime) Health(context.Context) (runtime.Health, error) {
	return runtime.Health{Status: "UP"}, nil
}
func TestEventDedupAndStateUpdateWithPostgres(t *testing.T) {
	url := os.Getenv("DATABASE_URL")
	if url == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, e := pgxpool.New(ctx, url)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	s := app.New(pool, fakeRuntime{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	id := ids.New("session")
	a, e := s.Q.CreateAvatar(ctx, dbgen.CreateAvatarParams{ID: ids.New("avatar"), Name: "test", Engine: "MOCK"})
	if e != nil {
		t.Fatal(e)
	}
	v, e := s.Q.CreateVoice(ctx, dbgen.CreateVoiceParams{ID: ids.New("voice"), Name: "test", Provider: "MOCK", ProviderVoiceID: "mock"})
	if e != nil {
		t.Fatal(e)
	}
	room, e := s.Q.CreateRoom(ctx, dbgen.CreateRoomParams{ID: ids.New("room"), Name: "test", AvatarID: a.ID, VoiceID: v.ID})
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.Q.CreateSession(ctx, dbgen.CreateSessionParams{ID: id, RoomID: room.ID})
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.Q.TransitionSession(ctx, dbgen.TransitionSessionParams{ID: id, Status: "CREATED", Status_2: "PREPARING"})
	if e != nil {
		t.Fatal(e)
	}
	ev := app.Event{SchemaVersion: "1.0", EventID: ids.New("evt"), EventType: "SESSION_READY", SessionID: id, TraceID: ids.New("trace"), OccurredAt: time.Now().UTC(), Source: "AI_RUNTIME", Payload: map[string]any{}}
	first, e := s.ApplyEvent(ctx, ev)
	if e != nil || !first {
		t.Fatalf("first: %v %v", first, e)
	}
	second, e := s.ApplyEvent(ctx, ev)
	if e != nil || second {
		t.Fatalf("duplicate: %v %v", second, e)
	}
	se, e := s.Q.GetSession(ctx, id)
	if e != nil || se.Status != "STARTING" {
		t.Fatalf("state: %+v %v", se, e)
	}
	var count int
	e = pool.QueryRow(ctx, "SELECT count(*) FROM runtime_events WHERE event_id=$1", ev.EventID).Scan(&count)
	if e != nil || count != 1 {
		t.Fatalf("event count %d %v", count, e)
	}
	ev.EventID = ids.New("evt")
	ev.EventType = "SESSION_STARTED"
	first, e = s.ApplyEvent(ctx, ev)
	if e != nil || !first {
		t.Fatalf("started: %v %v", first, e)
	}
	se, e = s.Q.GetSession(ctx, id)
	if e != nil || se.Status != "LIVE" {
		t.Fatalf("live: %+v %v", se, e)
	}
}
