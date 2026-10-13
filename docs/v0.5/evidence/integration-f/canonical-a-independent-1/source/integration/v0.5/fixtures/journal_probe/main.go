// F-owned negative seam fixture: real A Store/JournalRouter and PostgreSQL.
// It does not implement Narration or Timeline persistence, and never touches production data.
package main

import (
	"astralive/backend/db"
	"astralive/backend/internal/durability"
	"astralive/backend/internal/httpapi"
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"os"
	"time"
)

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func main() {
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, os.Getenv("F_PROBE_DATABASE_URL"))
	must(err)
	defer pool.Close()
	must(db.Migrate(ctx, pool))
	_, err = pool.Exec(ctx, `INSERT INTO config_principals VALUES('f-tenant','f-user');
 INSERT INTO avatars(id,name,engine) VALUES('f-avatar','fixture','MOCK');
 INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('f-voice','fixture','MOCK','mock');
 INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('f-room','fixture','f-avatar','f-voice','synthetic fixture');
 INSERT INTO live_sessions(id,room_id,status) VALUES('f-session','f-room','LIVE');
 INSERT INTO resource_owners VALUES('room','f-room','f-tenant','f-user'),('session','f-session','f-tenant','f-user');
 INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at)
 VALUES('f-session','f-tenant','f-user','f-binding','{}','{}',clock_timestamp()+interval '1 hour');`)
	must(err)
	store := durability.New(pool)
	tx, err := pool.Begin(ctx)
	must(err)
	_, err = store.InitialRun(ctx, tx, "f-session")
	must(err)
	must(tx.Commit(ctx))
	go func() {
		for range time.NewTicker(time.Second).C {
			_ = store.Renew(ctx)
		}
	}()
	mux := http.NewServeMux()
	mux.Handle("/internal/v0.5/durability/", http.StripPrefix("/internal/v0.5/durability", httpapi.JournalRouter(store, os.Getenv("RUNTIME_JOURNAL_TOKEN_FILE"))))
	mux.HandleFunc("/fixture/command", func(w http.ResponseWriter, r *http.Request) {
		// Fixture ingress is loopback-only in an owned disposable cluster; production roles use JournalRouter.
		var input struct {
			Kind    string          `json:"kind"`
			Epoch   int64           `json:"timelineEpoch"`
			Payload json.RawMessage `json:"payload"`
		}
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
			http.Error(w, "bad fixture", 422)
			return
		}
		tx, err := pool.Begin(ctx)
		if err != nil {
			http.Error(w, "database", 503)
			return
		}
		defer tx.Rollback(ctx)
		run, err := store.Current(ctx, tx, "f-session", true)
		must(err)
		c, err := store.Enqueue(ctx, tx, run, input.Kind, input.Kind, "f-trace-"+input.Kind, "", input.Payload)
		must(err)
		if input.Epoch > 0 {
			c.TimelineEpoch = input.Epoch
			c.NarrationID = json.RawMessage(`"f-narration"`)
			c.SegmentID = json.RawMessage(`"f-segment"`)
			c.Lane = "NARRATION"
			raw, _ := json.Marshal(c)
			c.RequestFingerprint, err = durability.Fingerprint(raw)
			must(err)
			raw, _ = json.Marshal(c)
			_, err = tx.Exec(ctx, `UPDATE v05_outbox SET payload_envelope=$2,request_fingerprint=$3 WHERE command_id=$1`, c.CommandID, raw, c.RequestFingerprint)
			must(err)
		}
		must(tx.Commit(ctx))
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(c)
	})
	mux.HandleFunc("/fixture/capabilities", func(w http.ResponseWriter, r *http.Request) {
		names := []string{"v05_narrations", "v05_segments", "v05_segment_attempts", "v05_interaction_turns", "v05_timeline_epochs", "v05_timeline_commits"}
		out := map[string]bool{}
		for _, name := range names {
			var present bool
			must(pool.QueryRow(ctx, `SELECT to_regclass($1) IS NOT NULL`, name).Scan(&present))
			out[name] = present
		}
		_ = json.NewEncoder(w).Encode(out)
	})
	fmt.Println("F_PROBE_READY")
	must(http.ListenAndServe(os.Getenv("F_PROBE_ADDR"), mux))
}
