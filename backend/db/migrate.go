package db

import (
	"context"
	"embed"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql
var migrations embed.FS

func Migrate(ctx context.Context, p *pgxpool.Pool) error {
	// One pinned connection owns the deployment lock across all additive migrations.
	conn, e := p.Acquire(ctx)
	if e != nil {
		return e
	}
	defer conn.Release()
	if _, e = conn.Exec(ctx, "SELECT pg_advisory_lock(7300516001)"); e != nil {
		return e
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		if _, err := conn.Exec(cleanup, "SELECT pg_advisory_unlock(7300516001)"); err != nil {
			_ = conn.Hijack().Close(cleanup) // never return a locked connection to the pool
		}
	}()

	_, e = conn.Exec(ctx, "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
	if e != nil {
		return e
	}
	files, e := migrations.ReadDir("migrations")
	if e != nil {
		return e
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Name() < files[j].Name() })
	for _, f := range files {
		if f.IsDir() {
			continue
		}
		name := f.Name()
		var exists bool
		e = conn.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE name=$1)", name).Scan(&exists)
		if e != nil {
			return e
		}
		if exists {
			continue
		}
		sql, e := migrations.ReadFile("migrations/" + name)
		if e != nil {
			return e
		}
		tx, e := conn.Begin(ctx)
		if e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, string(sql)); e != nil {
			tx.Rollback(ctx)
			return fmt.Errorf("migration %s: %w", name, e)
		}
		if _, e = tx.Exec(ctx, "INSERT INTO schema_migrations(name) VALUES($1)", name); e != nil {
			tx.Rollback(ctx)
			return e
		}
		if e = tx.Commit(ctx); e != nil {
			return e
		}
	}
	return nil
}
