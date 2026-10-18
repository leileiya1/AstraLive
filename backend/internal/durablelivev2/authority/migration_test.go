package authority

import (
	"astralive/backend/db"
	"context"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"testing"
)

func isolatedEmptyDB(t *testing.T) *pgxpool.Pool {
	t.Helper()
	root := testDB(t)
	cfg := root.Config().Copy()
	name := id("agent2_v2_upgrade")
	if _, e := root.Exec(context.Background(), "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()); e != nil {
		t.Fatal(e)
	}
	cfg.ConnConfig.Database = name
	p, e := pgxpool.NewWithConfig(context.Background(), cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		p.Close()
		_, e := root.Exec(context.Background(), "DROP DATABASE "+pgx.Identifier{name}.Sanitize())
		if e != nil {
			t.Error(e)
		}
	})
	return p
}
func TestMigrationUpgradeRepeatConcurrentPreservesV1(t *testing.T) {
	p := isolatedEmptyDB(t)
	ctx := context.Background()
	files, e := filepath.Glob("../../../db/migrations/00000[1-6]*.sql")
	if e != nil || len(files) != 6 {
		t.Fatal(files, e)
	}
	sort.Strings(files)
	if _, e = p.Exec(ctx, "CREATE TABLE schema_migrations(name text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now())"); e != nil {
		t.Fatal(e)
	}
	for _, name := range files {
		b, e := os.ReadFile(name)
		if e != nil {
			t.Fatal(e)
		}
		tx, e := p.Begin(ctx)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = tx.Exec(ctx, string(b)); e != nil {
			t.Fatal(name, e)
		}
		if _, e = tx.Exec(ctx, "INSERT INTO schema_migrations(name) VALUES($1)", filepath.Base(name)); e != nil {
			t.Fatal(e)
		}
		if e = tx.Commit(ctx); e != nil {
			t.Fatal(e)
		}
	}
	for _, sql := range []string{"INSERT INTO config_principals VALUES('preserved-tenant','preserved-owner')", "INSERT INTO avatars(id,name,engine) VALUES('preserved-avatar','v1','MOCK')", "INSERT INTO voices(id,name,provider,provider_voice_id) VALUES('preserved-voice','v1','mock','v1')", "INSERT INTO products(id,name,description,price,currency,stock) VALUES('preserved-product','v1','保持原字节',1,'CNY',9)", "INSERT INTO live_rooms(id,name,avatar_id,voice_id,system_prompt) VALUES('preserved-room','v1','preserved-avatar','preserved-voice','v1')", "INSERT INTO resource_owners VALUES('room','preserved-room','preserved-tenant','preserved-owner')", "INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy) VALUES('preserved-tenant','preserved-owner','preserved-run','preserved-room','CREATED','LIVE','MANUAL_ON_UNKNOWN')"} {
		if _, e = p.Exec(ctx, sql); e != nil {
			t.Fatal(e)
		}
	}
	var before string
	if e = p.QueryRow(ctx, "SELECT to_jsonb(p)::text FROM products p WHERE id='preserved-product'").Scan(&before); e != nil {
		t.Fatal(e)
	}
	const n = 4
	var wg sync.WaitGroup
	errCh := make(chan error, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); errCh <- db.Migrate(ctx, p) }()
	}
	wg.Wait()
	close(errCh)
	for e := range errCh {
		if e != nil {
			t.Fatal(e)
		}
	}
	var after, revision string
	var count int
	if e = p.QueryRow(ctx, "SELECT to_jsonb(p)::text FROM products p WHERE id='preserved-product'").Scan(&after); e != nil {
		t.Fatal(e)
	}
	if before != after {
		t.Fatal("v1 row changed")
	}
	if e = p.QueryRow(ctx, "SELECT contract_revision FROM dl05_runs WHERE run_id='preserved-run'").Scan(&revision); e != nil || revision != "durable-live-1" {
		t.Fatal(revision, e)
	}
	if e = p.QueryRow(ctx, "SELECT count(*) FROM schema_migrations").Scan(&count); e != nil || count != 7 {
		t.Fatal(count, e)
	}
	t.Log("000006 -> 000007; original v1 product bytes preserved; 4 concurrent runners; migrations=7")
	// Actual SQL privilege denial using an isolated NOLOGIN role. No role is granted business tables.
	role := id("agent2_v2_denied")
	if _, e = p.Exec(ctx, "CREATE ROLE "+pgx.Identifier{role}.Sanitize()+" NOLOGIN"); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		_, e := p.Exec(ctx, "DROP ROLE "+pgx.Identifier{role}.Sanitize())
		if e != nil {
			t.Error(e)
		}
	})
	for _, sql := range []string{"SELECT * FROM dl05_receiver_consumptions", "INSERT INTO dl05_v2_grant_state VALUES('bad','ISSUED')"} {
		tx, e := p.Begin(ctx)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = tx.Exec(ctx, "SET LOCAL ROLE "+pgx.Identifier{role}.Sanitize()); e != nil {
			t.Fatal(e)
		}
		_, e = tx.Exec(ctx, sql)
		tx.Rollback(ctx)
		if e == nil {
			t.Fatal("unprivileged SQL allowed", sql)
		}
		t.Log(fmt.Sprint("restricted SQL denied: ", sql))
	}
}
