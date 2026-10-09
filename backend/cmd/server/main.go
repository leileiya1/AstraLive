package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"astralive/backend/db"
	"astralive/backend/internal/app"
	"astralive/backend/internal/config"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/runtime"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

func main() {
	c, e := config.Load()
	if e != nil {
		panic(e)
	}
	level := slog.LevelInfo
	if c.LogLevel == "debug" {
		level = slog.LevelDebug
	}
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level}))
	slog.SetDefault(log)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	pool, e := pgxpool.New(ctx, c.DatabaseURL)
	if e != nil {
		log.Error("postgres setup failed", "error", e)
		os.Exit(1)
	}
	defer pool.Close()
	if e = db.Migrate(ctx, pool); e != nil {
		log.Error("migration failed", "error", e)
		os.Exit(1)
	}
	opts, e := redis.ParseURL(c.RedisURL)
	if e != nil {
		log.Error("redis URL invalid", "error", e)
		os.Exit(1)
	}
	rc := redis.NewClient(opts)
	defer rc.Close()
	s := app.New(pool, runtime.New(c.RuntimeURL), log)
	h := &httpapi.Server{S: s, Redis: rc, Env: c.Env, Token: c.InternalToken, Log: log}
	go func() {
		if err := eventbus.New(rc, s, c.EventStream, log).Run(ctx); err != nil && ctx.Err() == nil {
			log.Error("event consumer stopped", "error", err)
			stop()
		}
	}()
	srv := &http.Server{Addr: c.Addr, Handler: h.Router(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdown)
	}()
	log.Info("backend listening", "addr", c.Addr)
	if e = srv.ListenAndServe(); e != nil && !errors.Is(e, http.ErrServerClosed) {
		log.Error("server failed", "error", e)
		os.Exit(1)
	}
}
