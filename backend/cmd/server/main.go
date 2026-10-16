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
	"astralive/backend/internal/durablelive"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
)

func main() {
	// Refuse before creating services or touching the database. A durable flag
	// cannot authorize an unproven production publisher.
	if e := durablelive.CheckLiveAdmission(os.Getenv("ASTRALIVE_DURABLE_LIVE_ENABLED")); e != nil {
		panic(e)
	}
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
	rt := runtime.New(c.RuntimeURL)
	s := app.New(pool, rt, log)
	// Always recognize persistent mode membership after restart/rollback. This
	// store has no sinks/dispatcher; it cannot admit media through legacy paths.
	s.Durable = durablelive.New(pool, nil)
	cfg, e := userconfig.FromEnvironment(pool)
	if e != nil {
		log.Error("configuration setup failed", "reason", e.Error())
		os.Exit(1)
	}
	if c.Env == "production" && (cfg == nil || !cfg.IntegrationEnabled) {
		log.Error("production requires authenticated Session integration")
		os.Exit(1)
	}
	if cfg != nil && cfg.IntegrationEnabled {
		s.Integration = cfg
		rt.Client.Transport = userconfig.TokenTransport{Path: cfg.RuntimeControlTokenFile, Base: &http.Transport{Proxy: nil}}
		rt.Client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
		go func() {
			tick := time.NewTicker(15 * time.Second)
			defer tick.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-tick.C:
					if err := cfg.Reconcile(ctx); err != nil {
						log.Error("binding reconciliation pending")
					}
				}
			}
		}()
	}
	interactionConfig, err := interaction.FromEnvironment()
	if err != nil {
		log.Error("invalid interaction configuration")
		os.Exit(1)
	}
	s.Interaction = app.NewInteraction(ctx, s, cfg, interactionConfig)
	prometheus.MustRegister(prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "interaction_candidate_queue_length", Help: "Aggregate bounded candidate count; no identity labels."}, s.Interaction.QueueLength))
	h := &httpapi.Server{S: s, Redis: rc, Env: c.Env, Token: c.InternalToken, Log: log, Config: cfg}
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
