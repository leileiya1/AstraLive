package config

import (
	"fmt"
	"os"
)

type Config struct{ Env, Addr, DatabaseURL, RedisURL, EventStream, RuntimeURL, InternalToken, LogLevel, MinioEndpoint, MinioAccessKey, MinioSecretKey, OTELEndpoint string }

func get(k, fallback string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return fallback
}
func Load() (Config, error) {
	c := Config{get("APP_ENV", "development"), get("HTTP_ADDR", ":8080"), os.Getenv("DATABASE_URL"), get("REDIS_URL", "redis://localhost:6379"), get("REDIS_RUNTIME_EVENT_STREAM", "dh.runtime.events.v1"), get("AI_RUNTIME_URL", "http://localhost:8000"), os.Getenv("INTERNAL_API_TOKEN"), get("LOG_LEVEL", "info"), os.Getenv("MINIO_ENDPOINT"), os.Getenv("MINIO_ACCESS_KEY"), os.Getenv("MINIO_SECRET_KEY"), os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")}
	if c.DatabaseURL == "" {
		return c, fmt.Errorf("DATABASE_URL is required")
	}
	if c.InternalToken == "" {
		return c, fmt.Errorf("INTERNAL_API_TOKEN is required")
	}
	return c, nil
}
