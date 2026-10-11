package durability_test

import (
	"astralive/backend/db"
	"astralive/backend/internal/ids"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"path/filepath"
	"testing"
)

func TestContinuityUpgradeFrom006(t *testing.T) {
	ctx, base, _ := pg(t)
	schema := ids.New("upgrade")
	if _, e := base.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); e != nil {
		t.Fatal(e)
	}
	cfg := base.Config().Copy()
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	p, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { p.Close(); _, _ = base.Exec(ctx, "DROP SCHEMA "+pgx.Identifier{schema}.Sanitize()+" CASCADE") })
	_, e = p.Exec(ctx, `CREATE TABLE schema_migrations(name text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now())`)
	if e != nil {
		t.Fatal(e)
	}
	files, e := filepath.Glob("../../db/migrations/00000[1-6]_*.sql")
	if e != nil || len(files) != 6 {
		t.Fatalf("baseline migrations %v %v", files, e)
	}
	for _, name := range files {
		raw, e := os.ReadFile(name)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = p.Exec(ctx, string(raw)); e != nil {
			t.Fatal(e)
		}
		if _, e = p.Exec(ctx, `INSERT INTO schema_migrations(name) VALUES($1)`, filepath.Base(name)); e != nil {
			t.Fatal(e)
		}
	}
	_, e = p.Exec(ctx, `INSERT INTO config_principals VALUES('tenant','user');
 INSERT INTO avatars(id,name,engine) VALUES('a','a','MOCK');INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('v','v','MOCK','mock');
 INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('room','room','a','v','prompt');INSERT INTO live_sessions(id,room_id,status) VALUES('s','room','LIVE');
 INSERT INTO resource_owners VALUES('room','room','tenant','user'),('session','s','tenant','user');
 INSERT INTO session_provider_bindings(session_id,tenant_id,user_id,binding_id,room_snapshot,summary,expires_at) VALUES('s','tenant','user','binding','{}','{}',clock_timestamp()+interval '1 hour');
 INSERT INTO v05_session_runs(session_id,run_epoch,tenant_id,user_id,owner_id,lease_token,status,provider_binding_id,current_committed_sample) VALUES('s',1,'tenant','user','owner',1,'ACTIVE','binding',640);
 INSERT INTO utterances(id,session_id,text,priority,interrupt_policy,source,trace_id,status) VALUES('u','s','completed task',40,'NONE','OPERATOR','trace','COMPLETED');`)
	if e != nil {
		t.Fatal(e)
	}
	if e = db.Migrate(ctx, p); e != nil {
		t.Fatal(e)
	}
	var origin int64
	var status, utterance string
	if e = p.QueryRow(ctx, `SELECT status,origin_sample FROM v05_timeline_epochs WHERE session_id='s' AND run_epoch=1 AND timeline_epoch=1`).Scan(&status, &origin); e != nil {
		t.Fatal(e)
	}
	_ = p.QueryRow(ctx, `SELECT status FROM utterances WHERE id='u'`).Scan(&utterance)
	if status != "ACTIVE" || origin != 640 || utterance != "COMPLETED" {
		t.Fatalf("upgrade lost existing facts: %s %d %s", status, origin, utterance)
	}
}
