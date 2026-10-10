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
	t.Run("idle_comment_admitted_without_two_second_poll_wait", func(t *testing.T) {
		idleConfig := interaction.DefaultConfig()
		idleConfig.PollInterval = time.Hour // receipt should wake admission immediately
		cc := NewInteraction(ctx, s, cfg, idleConfig)
		s.Interaction = cc
		idle, err := cc.Ensure(ctx, scope, se.ID)
		if err != nil {
			t.Fatal(err)
		}
		defer func() {
			cc.Stop(se.ID)
			requests.Store(0)
			_, _ = pool.Exec(ctx, `DELETE FROM utterances WHERE session_id=$1`, se.ID)
			_, _ = pool.Exec(ctx, `DELETE FROM interaction_receipts WHERE session_id=$1`, se.ID)
		}()
		if err = idle.Receive(ctx, platform.Event{Platform: "mock", PlatformRoomID: ro.ID, InternalRoomID: ro.ID, SessionID: se.ID, SourceEventID: "idle-latency", EventType: platform.Comment, UserExternalID: "idle-viewer", Content: "多少钱？", Transport: "MOCK_REPLAY"}); err != nil {
			t.Fatal(err)
		}
		deadline := time.Now().Add(500 * time.Millisecond)
		for requests.Load() == 0 && time.Now().Before(deadline) {
			time.Sleep(5 * time.Millisecond)
		}
		if requests.Load() != 1 {
			t.Fatal("idle comment waited for 2-second polling cadence despite available speech consumer")
		}
	})
	settings := interaction.DefaultConfig()
	settings.PollInterval = time.Hour // receipt wake only
	settings.TTL = 200 * time.Millisecond
	s.Interaction = NewInteraction(ctx, s, cfg, settings)
	scheduler, err := s.Interaction.Ensure(ctx, scope, se.ID)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Interaction.Stop(se.ID)
	e := platform.Event{Platform: "mock", PlatformRoomID: ro.ID, InternalRoomID: ro.ID, SessionID: se.ID, SourceEventID: "audit-ttl", EventType: platform.Comment, UserExternalID: "viewer", Content: "多少钱？", Transport: "MOCK_REPLAY"}
	s.commands.Lock()
	if err = scheduler.Receive(ctx, e); err != nil {
		s.commands.Unlock()
		t.Fatal(err)
	}
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
	deadline = time.Now().Add(time.Second)
	for scheduler.Snapshot().Counters.Failed == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if scheduler.Snapshot().Counters.Failed != 1 {
		t.Fatal("expired selection was not rejected after receipt wake")
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
	t.Run("bound_product_switch_rejects_cached_admission", func(t *testing.T) {
		newProduct := ids.New("product")
		if _, err = pool.Exec(ctx, `INSERT INTO products(id,name,description,price,currency,stock) VALUES($1,'new','audit',399,'CNY',5)`, newProduct); err != nil {
			t.Fatal(err)
		}
		if _, err = pool.Exec(ctx, `INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES($1,$2,$3,$4,'{}','{}',now()+interval '1 hour')`, se.ID, scope.TenantID, scope.UserID, ids.New("binding")); err != nil {
			t.Fatal(err)
		}
		if _, err = pool.Exec(ctx, `UPDATE live_rooms SET active_product_id=$2 WHERE id=$1`, ro.ID, newProduct); err != nil {
			t.Fatal(err)
		}
		cfg.IntegrationEnabled = true
		defer func() {
			cfg.IntegrationEnabled = false
			_ = scheduler.SetMode(interaction.Idle)
			_, _ = pool.Exec(ctx, `UPDATE live_rooms SET active_product_id=NULL WHERE id=$1`, ro.ID)
		}()
		loseAck.Store(false)
		s.Runtime.(*runtime.HTTP).Client.Timeout = time.Second
		v := selection("audit-bound-product-switch")
		// Selections retain the captured product, never the new room product.
		if _, err = s.Interaction.Ensure(ctx, scope, se.ID); err != nil {
			t.Fatal(err)
		}
		switchConfig := interaction.DefaultConfig()
		switchScheduler, err := interaction.New(switchConfig, platform.Mapping{Platform: "mock", PlatformRoomID: ro.ID, RoomID: ro.ID, SessionID: se.ID}, "", d, func(ctx context.Context) (interaction.Gate, error) { return s.Interaction.gate(ctx, se.ID, ro.ID) }, time.Now, nil)
		if err != nil {
			t.Fatal(err)
		}
		defer switchScheduler.Stop()
		e.SourceEventID = "audit-switch-comment"
		if err = switchScheduler.Receive(ctx, e); err != nil {
			t.Fatal(err)
		}
		if err = switchScheduler.Tick(ctx); err != nil {
			t.Fatal(err)
		}
		if got := switchScheduler.Snapshot(); got.Mode != interaction.OperatorOverride || got.LastError != "PRODUCT_CHANGED_NEW_SESSION_REQUIRED" {
			t.Fatalf("product switch not fenced: %+v", got)
		}
		if _, err = d.Dispatch(ctx, v); err != ErrConflict {
			t.Errorf("dispatch sends new-product comment to old bound Runtime: %v", err)
		}
		if requests.Load() != 1 {
			t.Fatal("mismatched product reached Runtime")
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
