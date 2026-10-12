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
	"astralive/backend/internal/durability"
	"astralive/backend/internal/eventbus"
	"astralive/backend/internal/httpapi"
	"astralive/backend/internal/interaction"
	"astralive/backend/internal/narration"
	"astralive/backend/internal/recovery"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/userconfig"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
)

func main() {
	c, e := config.Load()
	if e != nil {
		panic(e)
	}
	continuity, e := narration.Enabled()
	if e != nil {
		panic(e)
	}
	if continuity && !c.DurabilityEnabled {
		panic("continuity requires PostgreSQL durability")
	}
	timeline, e := narration.TimelineEnabled()
	if e != nil {
		panic(e)
	}
	if continuity && !timeline {
		panic("continuity requires MediaTimeline")
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
	var rc *redis.Client
	if c.EventMode == "legacy_redis" {
		opts, err := redis.ParseURL(c.RedisURL)
		if err != nil {
			log.Error("redis URL invalid")
			os.Exit(1)
		}
		rc = redis.NewClient(opts)
		defer rc.Close()
	}
	localOptions, e := config.LocalTransportFromEnv()
	if e != nil {
		log.Error("local transport configuration invalid", "error", e)
		os.Exit(1)
	}
	rt, e := runtime.NewLocal(c.RuntimeURL, localOptions)
	if e != nil {
		log.Error("local transport setup failed", "error", e)
		os.Exit(1)
	}
	log.Info("Runtime control transport configured", "transport", localOptions.Mode, "fallback", localOptions.Fallback)
	if localOptions.Mode == "uds" || localOptions.Fallback == "tcp" {
		path := os.Getenv("RUNTIME_CONTROL_TOKEN_FILE")
		if _, e := userconfig.ReadServiceToken(path); e != nil {
			log.Error("local transport requires private Runtime control token")
			os.Exit(1)
		}
		rt.Client.Transport = userconfig.TokenTransport{Path: path, Base: rt.Client.Transport}
		rt.Client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	}
	s := app.New(pool, rt, log)
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
		// Capture one transport for commands and protected provider probes. The
		// authentication wrapper remains outside the UDS dialer.
		rt.Client.Transport = userconfig.TokenTransport{Path: cfg.RuntimeControlTokenFile, Base: cfg.RuntimeTransport}
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
	if c.DurabilityEnabled {
		if cfg == nil || !cfg.IntegrationEnabled {
			log.Error("durability requires authenticated Session integration")
			os.Exit(1)
		}
		journal, err := userconfig.ReadServiceToken(c.JournalTokenFile)
		if err != nil {
			log.Error("journal token unavailable")
			os.Exit(1)
		}
		for _, path := range []string{cfg.RuntimeControlTokenFile, cfg.WorkerTokenFile, cfg.IdentityTokenFile} {
			if path != "" {
				token, err := userconfig.ReadServiceToken(path)
				if err != nil || token == journal {
					log.Error("journal role must have a distinct valid token")
					os.Exit(1)
				}
			}
		}
		if journal == c.InternalToken {
			log.Error("journal token must differ from Tool token")
			os.Exit(1)
		}
		s.Durable = durability.New(pool)
		if continuity {
			s.AttachNarration(narration.New(s.Durable))
			go s.Narration.Run(ctx)
		}
		dispatcher := &durability.Dispatcher{Store: s.Durable, Remote: rt, Log: log}
		go dispatcher.Run(ctx)
		go (&recovery.Coordinator{Store: s.Durable, Dispatcher: dispatcher, Log: log}).Run(ctx)
		go eventbus.RunPostgres(ctx, s, log)
	}
	interactionConfig, err := interaction.FromEnvironment()
	if err != nil {
		log.Error("invalid interaction configuration")
		os.Exit(1)
	}
	s.Interaction = app.NewInteraction(ctx, s, cfg, interactionConfig)
	prometheus.MustRegister(prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "interaction_candidate_queue_length", Help: "Aggregate bounded candidate count; no identity labels."}, s.Interaction.QueueLength))
	h := &httpapi.Server{S: s, Redis: rc, Env: c.Env, Token: c.InternalToken, Log: log, Config: cfg, JournalTokenFile: c.JournalTokenFile}
	if rc != nil && !c.DurabilityEnabled {
		go func() {
			if err := eventbus.New(rc, s, c.EventStream, log).Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("event consumer stopped", "error", err)
				stop()
			}
		}()
	}
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
