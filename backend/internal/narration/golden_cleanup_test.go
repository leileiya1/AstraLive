package narration_test

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// F-only teardown observation. It issues no command and projects no receipt.
// The real observer's original error always remains the Golden verdict.
func goldenFailureCleanupState(ctx context.Context, pool *pgxpool.Pool) (bool, error) {
	var complete bool
	err := pool.QueryRow(ctx, `SELECT count(*)=1 AND COALESCE(bool_and(
 s.status='ENDED'
 AND EXISTS(SELECT 1 FROM v05_session_runs r WHERE r.session_id=s.id)
 AND NOT EXISTS(SELECT 1 FROM v05_session_runs r WHERE r.session_id=s.id AND (r.status<>'SEALED' OR r.sealed_at IS NULL))
 AND EXISTS(SELECT 1 FROM session_provider_bindings b WHERE b.session_id=s.id AND b.released_at IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM session_provider_bindings b WHERE b.session_id=s.id AND b.released_at IS NULL)
 ),false) FROM live_sessions s`).Scan(&complete)
	return complete, err
}

type goldenCleanupObservation struct {
	Scope     string `json:"scope"`
	Complete  bool   `json:"complete"`
	Code      string `json:"code"`
	ElapsedMS int64  `json:"elapsedMs"`
}

func observeGoldenFailureCleanup(pool *pgxpool.Pool) goldenCleanupObservation {
	started := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	result := goldenCleanupObservation{Scope: "read-only owned SQL teardown observation; original observer failure retained", Code: "PENDING"}
	for {
		complete, err := goldenFailureCleanupState(ctx, pool)
		result.ElapsedMS = time.Since(started).Milliseconds()
		if err != nil {
			result.Code = "SQL_OBSERVATION_FAILED"
			if ctx.Err() != nil {
				result.Code = "TERMINAL_STATE_NOT_OBSERVED"
			}
			return result
		}
		if complete {
			result.Complete = true
			result.Code = "ENDED_SEALED_BINDING_RELEASED"
			return result
		}
		select {
		case <-ctx.Done():
			result.Code = "TERMINAL_STATE_NOT_OBSERVED"
			result.ElapsedMS = time.Since(started).Milliseconds()
			return result
		case <-time.After(100 * time.Millisecond):
		}
	}
}

// Predicate tests use explicitly controlled owned rows. They are not Runtime
// Stop/recovery or physical-media cleanup proof.
func TestPostgresGoldenFailureCleanupPredicate(t *testing.T) {
	ctx, p, _, _ := setup(t)
	assertComplete := func(want bool) {
		t.Helper()
		got, err := goldenFailureCleanupState(ctx, p)
		if err != nil || got != want {
			t.Fatalf("cleanup observation complete=%v want=%v error=%v", got, want, err)
		}
	}
	assertComplete(false)
	if _, err := p.Exec(ctx, `UPDATE live_sessions SET status='ENDED' WHERE id='s'`); err != nil {
		t.Fatal(err)
	}
	assertComplete(false)
	if _, err := p.Exec(ctx, `UPDATE v05_session_runs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id='s'`); err != nil {
		t.Fatal(err)
	}
	assertComplete(false)
	if _, err := p.Exec(ctx, `UPDATE session_provider_bindings SET released_at=clock_timestamp() WHERE session_id='s'`); err != nil {
		t.Fatal(err)
	}
	assertComplete(true)
	if _, err := p.Exec(ctx, `INSERT INTO live_sessions(id,room_id,status) VALUES('extra','room','ENDED')`); err != nil {
		t.Fatal(err)
	}
	assertComplete(false)
	if _, err := p.Exec(ctx, `DELETE FROM live_sessions WHERE id='extra';DELETE FROM v05_timeline_epochs WHERE session_id='s';DELETE FROM v05_session_runs WHERE session_id='s'`); err != nil {
		t.Fatal(err)
	}
	assertComplete(false)
	if _, err := p.Exec(ctx, `DELETE FROM session_provider_bindings WHERE session_id='s';DELETE FROM live_sessions WHERE id='s'`); err != nil {
		t.Fatal(err)
	}
	assertComplete(false)
}
