package runtime

import (
	"astralive/backend/internal/config"
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"
)

// NewLocal keeps Client's HTTP/JSON interface and command/error handling intact.
// The caller composes TokenTransport OUTSIDE Client.Transport.
func NewLocal(base string, options config.LocalTransport) (*HTTP, error) {
	checked, e := config.ResolveLocalTransport(options.Mode, options.SocketPath, options.Fallback, localPlatform())
	if e != nil {
		return nil, e
	}
	options = checked
	if options.Mode == "tcp" {
		if options.Fallback == "tcp" {
			if e := config.LoopbackURL(base); e != nil {
				return nil, e
			}
		}
		return New(base), nil // feature off restores original client/URL/timeout
	}
	if options.Mode != "uds" {
		return nil, fmt.Errorf("invalid local transport mode")
	}
	parent, e := secureParent(options.SocketPath)
	if e != nil {
		return nil, e
	}
	dialer := &net.Dialer{Timeout: 8 * time.Second, KeepAlive: 30 * time.Second}
	// Pool defaults match the protected baseline transport. Timeout stays on
	// http.Client so WebRTC can retain its existing30s exception.
	t := &http.Transport{Proxy: nil}
	t.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) {
		current, e := secureParent(options.SocketPath)
		if e != nil {
			return nil, e
		}
		if !os.SameFile(parent, current) {
			return nil, fmt.Errorf("runtime UDS parent replaced")
		}
		before, e := secureSocket(options.SocketPath)
		if e != nil {
			return nil, e
		}
		conn, e := dialer.DialContext(ctx, "unix", options.SocketPath)
		if e != nil {
			return nil, fmt.Errorf("runtime UDS dial: %w", e)
		}
		after, e := secureSocket(options.SocketPath)
		if e != nil || !os.SameFile(before, after) {
			conn.Close()
			return nil, fmt.Errorf("runtime UDS replaced during connect")
		}
		return conn, nil
	}
	h := New("http://runtime.local")
	h.Client.Transport = LocalDiagnostics{Base: t, Mode: "uds"}
	h.Client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return h, nil
}

// LocalDiagnostics logs no token, payload, trace values, or raw server error body.
// net errors retain an operator-owned socket path for actionable diagnostics.
type LocalDiagnostics struct {
	Base http.RoundTripper
	Mode string
}

func (t LocalDiagnostics) RoundTrip(r *http.Request) (*http.Response, error) {
	resp, e := t.Base.RoundTrip(r)
	if e != nil {
		slog.ErrorContext(r.Context(), "runtime control transport failed", "transport", t.Mode, "error", e)
	} else if resp.StatusCode >= 400 {
		slog.WarnContext(r.Context(), "runtime control rejected", "transport", t.Mode, "status", resp.StatusCode)
	}
	return resp, e
}
func (t LocalDiagnostics) CloseIdleConnections() {
	if c, ok := t.Base.(interface{ CloseIdleConnections() }); ok {
		c.CloseIdleConnections()
	}
}
