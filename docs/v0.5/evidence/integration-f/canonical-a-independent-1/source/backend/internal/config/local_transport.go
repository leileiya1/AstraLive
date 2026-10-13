package config

import (
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
)

// LocalTransport is captured at startup. No fallback is attempted after a send.
type LocalTransport struct{ Mode, SocketPath, Fallback string }

func LocalTransportFromEnv() (LocalTransport, error) {
	return ResolveLocalTransport(get("ASTRALIVE_LOCAL_TRANSPORT", "tcp"), os.Getenv("ASTRALIVE_RUNTIME_UDS_PATH"), get("ASTRALIVE_LOCAL_FALLBACK", "disabled"), runtime.GOOS)
}

// ResolveLocalTransport takes a platform for deterministic cross-platform validation.
func ResolveLocalTransport(mode, path, fallback, platform string) (LocalTransport, error) {
	c := LocalTransport{mode, path, fallback}
	if mode != "tcp" && mode != "uds" {
		return c, fmt.Errorf("ASTRALIVE_LOCAL_TRANSPORT must be tcp or uds")
	}
	if fallback != "disabled" && fallback != "tcp" {
		return c, fmt.Errorf("ASTRALIVE_LOCAL_FALLBACK must be disabled or tcp")
	}
	if mode == "tcp" {
		return c, nil
	}
	if platform != "linux" && platform != "darwin" {
		if fallback == "tcp" {
			c.Mode = "tcp"
			return c, nil
		}
		return c, fmt.Errorf("UDS unsupported on %s; explicitly configure tcp loopback", platform)
	}
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || len([]byte(path)) > 103 || path == string(filepath.Separator) {
		return c, fmt.Errorf("ASTRALIVE_RUNTIME_UDS_PATH must be a clean absolute path <=103 bytes")
	}
	return c, nil
}

// LoopbackURL validates fallback without DNS or proxy-based endpoint substitution.
func LoopbackURL(base string) error {
	u, e := url.Parse(base)
	if e != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || u.Host == "" {
		return fmt.Errorf("local TCP endpoint must be a plain loopback HTTP origin")
	}
	ip := net.ParseIP(u.Hostname())
	if u.Hostname() != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return fmt.Errorf("local TCP endpoint must use loopback")
	}
	port, e := strconv.Atoi(u.Port())
	if e != nil || port < 1 || port > 65535 {
		return fmt.Errorf("local TCP endpoint requires a port")
	}
	return nil
}
