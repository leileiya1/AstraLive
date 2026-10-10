package app

import (
	"astralive/backend/db"
	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/platform"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Real disposable SQL and loopback Fake Runtime; never uses a merchant DB or GPU.
func TestAuditSelectionExpiresWhileWaitingForCommandLock(t *testing.T) {
	url := os.Getenv("CONFIG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("explicit disposable SQL required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err = db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	var requests atomic.Int32
	var loseAck atomic.Bool
	rt := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if loseAck.Load() {
			// Fake Runtime admitted the task, but acknowledgement is lost.
			time.Sleep(150 * time.Millisecond)
			return
		}
		w.WriteHeader(202)
		_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_fake"}`))
	}))
	defer rt.Close()
	s := New(pool, runtime.New(rt.URL), slog.New(slog.NewTextHandler(io.Discard, nil)))
	av, err := s.Q.CreateAvatar(ctx, dbgen.CreateAvatarParams{ID: ids.New("avatar"), Name: "audit", Engine: "MOCK"})
	if err != nil {
		t.Fatal(err)
	}
	vo, err := s.Q.CreateVoice(ctx, dbgen.CreateVoiceParams{ID: ids.New("voice"), Name: "audit", Provider: "MOCK", ProviderVoiceID: "fake"})
	if err != nil {
		t.Fatal(err)
	}
	ro, err := s.Q.CreateRoom(ctx, dbgen.CreateRoomParams{ID: ids.New("room"), Name: "audit", AvatarID: av.ID, VoiceID: vo.ID, SystemPrompt: "audit"})
	if err != nil {
		t.Fatal(err)
	}
	se, err := s.Q.CreateSession(ctx, dbgen.CreateSessionParams{ID: ids.New("session"), RoomID: ro.ID})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, `UPDATE live_sessions SET status='LIVE' WHERE id=$1`, se.ID); err != nil {
		t.Fatal(err)
	}
	scope := userconfig.Scope{TenantID: ids.New("audit"), UserID: "operator"}
	cfg := &userconfig.Service{DB: pool}
	if _, err = cfg.IssueSession(ctx, scope); err != nil {
		t.Fatal(err)
	}
	for kind, id := range map[string]string{"room": ro.ID, "session": se.ID} {
		if err = cfg.Own(ctx, scope, kind, id); err != nil {
			t.Fatal(err)
		}
	}
	settings := interaction.DefaultConfig()
	settings.Interval = time.Hour // manual Tick only
	settings.TTL = 200 * time.Millisecond
	s.Interaction = NewInteraction(ctx, s, cfg, settings)
	scheduler, err := s.Interaction.Ensure(ctx, scope, se.ID)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Interaction.Stop(se.ID)
	e := platform.Event{Platform: "mock", PlatformRoomID: ro.ID, InternalRoomID: ro.ID, SessionID: se.ID, SourceEventID: "audit-ttl", EventType: platform.Comment, UserExternalID: "viewer", Content: "多少钱？", Transport: "MOCK_REPLAY"}
	if err = scheduler.Receive(ctx, e); err != nil {
		t.Fatal(err)
	}
	s.commands.Lock()
	done := make(chan error, 1)
	go func() { done <- scheduler.Tick(ctx) }()
	deadline := time.Now().Add(time.Second)
	for scheduler.Snapshot().Counters.Selected == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if scheduler.Snapshot().Counters.Selected != 1 {
		s.commands.Unlock()
		t.Fatal("selection not reserved")
	}
	time.Sleep(250 * time.Millisecond)
	s.commands.Unlock()
	if err = <-done; err == nil {
		t.Error("expired selection dispatched successfully")
	}
	var count int
	if err = pool.QueryRow(ctx, `SELECT count(*) FROM utterances WHERE session_id=$1`, se.ID).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 0 || requests.Load() != 0 {
		t.Fatalf("expired selection created %d utterances / %d Runtime calls", count, requests.Load())
	}
	// Subsequent fault cases test receipts rather than a second TTL boundary.
	s.Interaction.settings.TTL = 20 * time.Second
	d := &interactionDispatcher{controller: s.Interaction, scope: scope, sid: se.ID, room: ro.ID}
	selection := func(source string) interaction.Selection {
		e.SourceEventID = source
		now := time.Now()
		normalized, err := platform.Normalize(e, platform.Mapping{Platform: "mock", PlatformRoomID: ro.ID, RoomID: ro.ID, SessionID: se.ID}, now)
		if err != nil {
			t.Fatal(err)
		}
		return interaction.Selection{Event: normalized, Priority: 80, Policy: "NONE", SelectedAt: now}
	}
	for _, status := range []string{"RESERVED", "ACCEPTED", "FAILED"} {
		t.Run(status+"_restart_no_retry", func(t *testing.T) {
			v := selection("audit-" + status)
			if _, err = pool.Exec(ctx, `INSERT INTO interaction_receipts(session_id,trace_id,status) VALUES($1,$2,$3)`, se.ID, v.Event.TraceID, status); err != nil {
				t.Fatal(err)
			}
			if _, err = d.Dispatch(ctx, v); err != ErrConflict {
				t.Fatalf("duplicate receipt admitted: %v", err)
			}
			if requests.Load() != 0 {
				t.Fatal("receipt suppression sent Runtime request")
			}
		})
	}
	t.Run("runtime_admitted_ack_lost", func(t *testing.T) {
		v := selection("audit-lost-ack")
		loseAck.Store(true)
		s.Runtime.(*runtime.HTTP).Client.Timeout = 60 * time.Millisecond
		if _, err = d.Dispatch(ctx, v); err == nil {
			t.Fatal("lost acknowledgement was success")
		}
		if requests.Load() != 1 {
			t.Fatal("Fake Runtime did not admit exactly one request")
		}
		var receipt string
		if err = pool.QueryRow(ctx, `SELECT status FROM interaction_receipts WHERE session_id=$1 AND trace_id=$2`, se.ID, v.Event.TraceID).Scan(&receipt); err != nil {
			t.Fatal(err)
		}
		if receipt != "FAILED" {
			t.Fatal("ambiguous dispatch must be retained", receipt)
		}
		if _, err = d.Dispatch(ctx, v); err != ErrConflict {
			t.Fatal("ambiguous task retried", err)
		}
		if requests.Load() != 1 {
			t.Fatal("duplicate Runtime admission")
		}
	})
	t.Run("cached_controller_rechecks_room_ownership", func(t *testing.T) {
		v := selection("audit-room-revoked")
		if _, err = pool.Exec(ctx, `DELETE FROM resource_owners WHERE kind='room' AND resource_id=$1`, ro.ID); err != nil {
			t.Fatal(err)
		}
		defer func() {
			if err := cfg.Own(ctx, scope, "room", ro.ID); err != nil {
				t.Error(err)
			}
		}()
		if _, err = s.Interaction.Ensure(ctx, scope, se.ID); err != userconfig.ErrNotFound {
			t.Errorf("cached controller bypassed Room ownership: %v", err)
		}
		if _, err = d.Dispatch(ctx, v); err != userconfig.ErrNotFound {
			t.Errorf("selected dispatch bypassed Room ownership: %v", err)
		}
		if requests.Load() != 1 {
			t.Fatal("unowned Room reached Runtime")
		}
	})
	t.Run("stop_wins_before_dispatch", func(t *testing.T) {
		v := selection("audit-after-stop")
		if _, err = pool.Exec(ctx, `UPDATE live_sessions SET status='STOPPING' WHERE id=$1`, se.ID); err != nil {
			t.Fatal(err)
		}
		s.Interaction.Stop(se.ID)
		if _, err = d.Dispatch(ctx, v); err != ErrConflict {
			t.Fatal("Stop admitted speech", err)
		}
		if requests.Load() != 1 {
			t.Fatal("Runtime called after Stop")
		}
	})
}
