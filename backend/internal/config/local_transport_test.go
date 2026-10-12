package config

import (
	"reflect"
	"testing"
)

func TestLocalTransportPlatforms(t *testing.T) {
	for _, p := range []string{"linux", "darwin"} {
		c, e := ResolveLocalTransport("uds", "/run/astralive/runtime.sock", "disabled", p)
		if e != nil || c.Mode != "uds" {
			t.Fatal(c, e)
		}
	}
	c, e := ResolveLocalTransport("uds", "", "tcp", "windows")
	if e != nil || c.Mode != "tcp" {
		t.Fatal(c, e)
	}
	if _, e = ResolveLocalTransport("uds", "/s", "disabled", "windows"); e == nil {
		t.Fatal("Windows uds accepted")
	}
	for _, v := range []LocalTransport{{"auto", "/s", "disabled"}, {"uds", "relative", "disabled"}, {"uds", "/a/../s", "disabled"}, {"tcp", "", "auto"}} {
		if _, e := ResolveLocalTransport(v.Mode, v.SocketPath, v.Fallback, "linux"); e == nil {
			t.Fatal(v)
		}
	}
	t.Setenv("ASTRALIVE_LOCAL_TRANSPORT", "")
	t.Setenv("ASTRALIVE_RUNTIME_UDS_PATH", "")
	t.Setenv("ASTRALIVE_LOCAL_FALLBACK", "")
	got, e := LocalTransportFromEnv()
	if e != nil || !reflect.DeepEqual(got, LocalTransport{"tcp", "", "disabled"}) {
		t.Fatal(got, e)
	}
}
func TestLoopbackURL(t *testing.T) {
	for _, u := range []string{"http://127.0.0.1:8000", "http://[::1]:8000", "http://localhost:8000"} {
		if e := LoopbackURL(u); e != nil {
			t.Fatal(e)
		}
	}
	for _, u := range []string{"http://0.0.0.0:8000", "http://runtime:8000", "http://127.0.0.1:8000/x", "https://127.0.0.1:8000"} {
		if LoopbackURL(u) == nil {
			t.Fatal(u)
		}
	}
}
