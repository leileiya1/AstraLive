package durability_test

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestOwnedPostgresOutage(t *testing.T) {
	data, ctl, owner := os.Getenv("DURABILITY_OWNED_PGDATA"), os.Getenv("DURABILITY_PG_CTL"), os.Getenv("DURABILITY_PG_OWNER")
	if data == "" || ctl == "" || owner == "" {
		t.Skip("owned temporary PostgreSQL cluster required")
	}
	marker, e := os.ReadFile(filepath.Join(data, ".astralive-durability-owned"))
	if e != nil || string(marker) != owner || !strings.HasPrefix(filepath.Base(data), "astralive-pg-chaos.") {
		t.Fatal("refusing unowned PostgreSQL fault")
	}
	ctx, p, s := pg(t)
	r := run(t, ctx, p, s, "s")
	cmd := enqueue(t, ctx, p, s, r, "outage")
	raw, _ := json.Marshal(cmd)
	control := func(action string) {
		t.Helper()
		command := exec.Command(ctl, "-D", data, "-l", filepath.Join(data, "postgres.log"), "-m", "fast", action)
		if b, e := command.CombinedOutput(); e != nil {
			t.Fatalf("owned PostgreSQL %s failed: %v %s", action, e, b)
		}
	}
	control("stop")
	stopped := true
	defer func() {
		if stopped {
			control("start")
		}
	}()
	if _, e = s.Accept(ctx, raw); e == nil {
		t.Fatal("accepted a command while PostgreSQL was stopped")
	}
	control("start")
	stopped = false
	eventually(t, 3*time.Second, func() bool { return p.Ping(context.Background()) == nil })
	accepted, e := s.Accept(ctx, raw)
	if e != nil || !accepted.Execute {
		t.Fatalf("journal did not recover: %v", e)
	}
	duplicate, e := s.Accept(ctx, raw)
	if e != nil || duplicate.OperationID != accepted.OperationID {
		t.Fatal("outage lost idempotency")
	}
	t.Log("owned PostgreSQL fast stop/restart: failed closed during outage, durable acceptance restored without duplicate command")
}
