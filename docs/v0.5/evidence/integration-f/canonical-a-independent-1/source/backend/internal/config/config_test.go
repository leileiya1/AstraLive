package config

import "testing"

func TestDurabilityModes(t *testing.T) {
	t.Setenv("DATABASE_URL", "synthetic-db")
	t.Setenv("INTERNAL_API_TOKEN", "synthetic")
	t.Setenv("ASTRALIVE_DURABILITY_ENABLED", "false")
	t.Setenv("ASTRALIVE_EVENT_MODE", "postgres_only")
	if _, e := Load(); e == nil {
		t.Fatal("postgres_only without durability")
	}
	t.Setenv("ASTRALIVE_DURABILITY_ENABLED", "true")
	t.Setenv("RUNTIME_JOURNAL_TOKEN_FILE", "/private/token")
	if c, e := Load(); e != nil || c.EventMode != "postgres_only" {
		t.Fatal(c, e)
	}
	t.Setenv("ASTRALIVE_EVENT_MODE", "typo")
	if _, e := Load(); e == nil {
		t.Fatal("invalid mode")
	}
}
