// F independent adaptation of A lock/borrowed-transaction reproducer.
// Actual SQL and production scheduler/control hook; dispatcher never executes.
package app

import (
	"astralive/backend/db"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/platform"
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"os"
	"testing"
	"time"
)

type reviewDispatcher struct{}

func (reviewDispatcher) Dispatch(context.Context, interaction.Selection) (string, error) {
	return "", nil
}
func TestFReviewBorrowedRetirementSchedulerLock(t *testing.T) {
	ctx := context.Background()
	dsn := os.Getenv("DURABILITY_TEST_DATABASE_URL")
	if dsn == "" {
		t.Fatal("real isolated PG required")
	}
	base, e := pgxpool.New(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	defer base.Close()
	schema := ids.New("a_review")
	if _, e = base.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); e != nil {
		t.Fatal(e)
	}
	defer base.Exec(ctx, "DROP SCHEMA "+pgx.Identifier{schema}.Sanitize()+" CASCADE")
	config, e := pgxpool.ParseConfig(dsn)
	if e != nil {
		t.Fatal(e)
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema
	pool, e := pgxpool.NewWithConfig(ctx, config)
	if e != nil {
		t.Fatal(e)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		t.Fatal(e)
	}
	_, e = pool.Exec(ctx, `INSERT INTO config_principals VALUES('tenant','user');
 INSERT INTO avatars(id,name,engine) VALUES('a','avatar','MOCK');INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('v','voice','MOCK','mock');
 INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('room','room','a','v','prompt');
 INSERT INTO live_sessions(id,room_id,status) VALUES('s','room','LIVE');
 INSERT INTO resource_owners VALUES('room','room','tenant','user'),('session','s','tenant','user');
 INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES('s','tenant','user','binding','{}','{}',clock_timestamp()+interval '1 hour');`)
	if e != nil {
		t.Fatal(e)
	}
	store := durability.New(pool)
	initial, e := pool.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = store.InitialRun(ctx, initial, "s"); e != nil {
		t.Fatal(e)
	}
	if e = initial.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	service := New(pool, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	service.Durable = store
	controller := narration.New(store)
	service.AttachNarration(controller)
	service.Interaction = NewInteraction(ctx, service, nil, interaction.DefaultConfig())
	gateEntered := make(chan struct{})
	scheduler, e := interaction.New(interaction.DefaultConfig(), platform.Mapping{Platform: "mock", PlatformRoomID: "room", RoomID: "room", SessionID: "s"}, "", reviewDispatcher{}, func(gateCtx context.Context) (interaction.Gate, error) {
		close(gateEntered)
		active, may, err := controller.Gate(gateCtx, "s")
		return interaction.Gate{Running: true, ContinuityActive: active, ContinuityMaySuspend: may}, err
	}, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	_, cancelWorker := context.WithCancel(ctx)
	service.Interaction.entries["s"] = &interactionEntry{scheduler: scheduler, cancel: cancelWorker}
	outerCtx, cancel := context.WithTimeout(ctx, 400*time.Millisecond)
	defer cancel()
	tx, e := pool.Begin(outerCtx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	run, e := store.Current(outerCtx, tx, "s", false)
	if e != nil {
		t.Fatal(e)
	}
	gateCtx, cancelGate := context.WithTimeout(ctx, 800*time.Millisecond)
	defer cancelGate()
	gateDone := make(chan error, 1)
	go func() { gateDone <- scheduler.Tick(gateCtx) }()
	<-gateEntered
	hookDone := make(chan error, 1)
	started := time.Now()
	go func() { hookDone <- controller.RetireCapturedSession(outerCtx, tx, run) }()
	observedLock, hookFinished := false, false
	var hookErr error
observe:
	for time.Since(started) < 200*time.Millisecond {
		select {
		case hookErr = <-hookDone:
			hookFinished = true
			break observe
		default:
		}
		if !service.Interaction.mu.TryLock() {
			observedLock = true
			break
		}
		service.Interaction.mu.Unlock()
		time.Sleep(2 * time.Millisecond)
	}
	_ = observedLock
	snapshotDone := make(chan struct{})
	go func() { service.Interaction.Snapshot("another-room"); close(snapshotDone) }()
	blockedOtherRoom := false
	select {
	case <-snapshotDone:
	case <-time.After(50 * time.Millisecond):
		blockedOtherRoom = true
	}
	if !hookFinished {
		hookErr = <-hookDone
	}
	if hookErr != nil {
		t.Fatal(hookErr)
	}
	duration := time.Since(started)
	gateErr := <-gateDone
	<-snapshotDone
	// Force the outer transaction to roll back, even if the corrected hook is fast.
	// In-memory cancellation must be justified only by a committed control row.
	rollbackErr := tx.Rollback(ctx)
	_ = rollbackErr
	var state string
	if e = pool.QueryRow(ctx, `SELECT status FROM live_sessions WHERE id='s'`).Scan(&state); e != nil {
		t.Fatal(e)
	}
	stopped := scheduler.Snapshot().Stopped
	t.Logf("hook=%s gateError=%v SQLSession=%s schedulerStopped=%t blockedOtherRoom=%t", duration, gateErr, state, stopped, blockedOtherRoom)
	if duration > 200*time.Millisecond {
		t.Error("retirement waits on Scheduler.mu while its Gate waits on our SQL Session lock")
	}
	if state == "LIVE" && stopped {
		t.Error("borrowed transaction rollback left live SQL Session with stopped in-memory Scheduler")
	}
	if blockedOtherRoom {
		t.Error("InteractionController.mu held across wait blocks another room")
	}
}
