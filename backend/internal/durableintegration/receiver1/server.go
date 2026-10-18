package receiver1

import (
	"context"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

type peerKey struct{}
type connectionPeer struct {
	identity Identity
	conn     net.Conn
}
type limitedListener struct {
	net.Listener
	tokens chan struct{}
	done   chan struct{}
	once   sync.Once
}
type limitedConn struct {
	net.Conn
	release func()
	once    sync.Once
}

func (c *limitedConn) Close() error { e := c.Conn.Close(); c.once.Do(c.release); return e }
func (l *limitedListener) Accept() (net.Conn, error) {
	select {
	case <-l.done:
		return nil, net.ErrClosed
	case l.tokens <- struct{}{}:
	}
	c, e := l.Listener.Accept()
	if e != nil {
		<-l.tokens
		return nil, e
	}
	return &limitedConn{Conn: c, release: func() { <-l.tokens }}, nil
}
func (l *limitedListener) Close() error {
	l.once.Do(func() { close(l.done) })
	return l.Listener.Close()
}

// Server exposes only the frozen three Guardian Backend operations and the
// separately targeted installation read. No public router mounts this server.
// Pins are provisioned in memory before Listen; no HTTP enrollment exists.
type Server struct {
	Store         *authority.Store
	Installations *Registry
	pins          []*Pin
	http          *http.Server
	listener      net.Listener
	slots         chan struct{}
	cancel        context.CancelFunc
	done          chan struct{}
}

func NewServer(store *authority.Store, installations *Registry, pins ...*Pin) (*Server, error) {
	if store == nil || store.DB == nil || installations == nil || len(pins) == 0 || len(pins) > 128 {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	s := &Server{Store: store, Installations: installations, pins: append([]*Pin(nil), pins...), slots: make(chan struct{}, 16)}
	for _, p := range pins {
		if p == nil || p.actor.Role != "OUTPUT_GUARDIAN" || !p.Alive() {
			return nil, denied()
		}
	}
	s.http = &http.Server{Handler: s, ReadHeaderTimeout: 250 * time.Millisecond, ReadTimeout: 500 * time.Millisecond, WriteTimeout: 250 * time.Millisecond, IdleTimeout: time.Second, MaxHeaderBytes: 8192, ErrorLog: log.New(io.Discard, "", 0), ConnContext: func(ctx context.Context, c net.Conn) context.Context {
		underlying := c
		if limited, ok := c.(*limitedConn); ok {
			underlying = limited.Conn
		}
		u, ok := underlying.(*net.UnixConn)
		if !ok {
			return ctx
		}
		raw, e := u.SyscallConn()
		if e != nil {
			return ctx
		}
		var p Identity
		var err error
		e = raw.Control(func(fd uintptr) { p, err = socketIdentity(int(fd)) })
		if e != nil || err != nil {
			return ctx
		}
		return context.WithValue(ctx, peerKey{}, connectionPeer{p, c})
	}}
	return s, nil
}

// Listen refuses stale sockets/symlinks and requires a private, owner-only
// directory. Cross-UID deployment needs a separately reviewed ACL profile.
func (s *Server) Listen(path string) error {
	if s.listener != nil {
		return fault("STATE_CONFLICT")
	}
	st, e := os.Lstat(filepath.Dir(path))
	if e != nil || !st.IsDir() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm() != 0700 {
		return denied()
	}
	owner, e := processIdentity(os.Getpid())
	if e != nil {
		return e
	}
	_ = owner
	// Opening the directory as the current user is insufficient; check ownership.
	if !ownedDirectory(st) {
		return denied()
	}
	if _, e = os.Lstat(path); !os.IsNotExist(e) {
		return denied()
	}
	l, e := net.Listen("unix", path)
	if e != nil {
		return e
	}
	bounded := &limitedListener{Listener: l, tokens: make(chan struct{}, 16), done: make(chan struct{})}
	s.listener = bounded
	if e = os.Chmod(path, 0600); e != nil {
		l.Close()
		return e
	}
	go s.http.Serve(bounded)
	ctx, cancel := context.WithCancel(context.Background())
	s.cancel = cancel
	s.done = make(chan struct{})
	go func() { defer close(s.done); s.Installations.supervise(ctx) }()
	return nil
}
func (s *Server) Close() error {
	if s.cancel != nil {
		s.cancel()
	}
	e := s.http.Close()
	if s.done != nil {
		<-s.done
	}
	return e
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Connection", "close")
	r.Close = true
	// Preserve only fixed error codes; no raw JSON/headers/SQL errors in logs.
	op, ok := operationForPath(r.URL.Path)
	if !ok || r.Method != "POST" || r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		s.replyError(w, op, "transport_error", "FORBIDDEN")
		return
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		s.replyError(w, op, "transport_error", "OVERLOADED")
		return
	}
	peer, ok := r.Context().Value(peerKey{}).(connectionPeer)
	if !ok || len(r.Header.Values("Authorization")) != 1 || len(r.TransferEncoding) != 0 || r.ContentLength <= 0 || r.ContentLength > int64(op.MaxBodyBytes) {
		s.replyError(w, op, "transport_error", "UNAUTHENTICATED")
		return
	}
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") || len(auth) > 256 {
		s.replyError(w, op, "transport_error", "UNAUTHENTICATED")
		return
	}
	var pin *Pin
	for _, p := range s.pins {
		if p.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
			if pin != nil {
				s.replyError(w, op, "transport_error", "UNAUTHENTICATED")
				return
			}
			pin = p
		}
	}
	if pin == nil {
		s.replyError(w, op, "transport_error", "UNAUTHENTICATED")
		return
	}
	raw, e := io.ReadAll(io.LimitReader(r.Body, int64(op.MaxBodyBytes)+1))
	if e != nil || len(raw) != int(r.ContentLength) {
		s.replyError(w, op, "transport_error", "INVALID_ARGUMENT")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 200*time.Millisecond)
	defer cancel()
	wc := wire.RequestContext{Role: wire.RoleOutputGuardian, Target: op.Target, Method: r.Method, RouteTemplate: op.Path}
	q, e := wire.DecodeRequest(op.ID, wc, raw)
	if e != nil {
		s.replyError(w, op, "transport_error", "INVALID_ARGUMENT")
		return
	}
	requestID := wire.ID("transport_error")
	switch x := q.(type) {
	case *wire.QueryReceiverAuthorityRequest:
		requestID = x.RequestID
	case *wire.CommitReceiverConsumeRequest:
		requestID = x.RequestID
	case *wire.QueryReceiverConsumptionRequest:
		requestID = x.RequestID
	case *wire.ReadReceiverPhysicalInstallationRequest:
		requestID = x.RequestID
	}
	if e = scopeRequest(pin, q); e != nil {
		s.replyError(w, op, string(requestID), "FORBIDDEN")
		return
	}
	if op.ID != wire.OpQueryReceiverConsumption {
		if e = s.Installations.eligible(ctx, pin); e != nil {
			code := "DEPENDENCY_UNAVAILABLE"
			var ae *authority.Error
			if errors.As(e, &ae) {
				code = ae.Code
			}
			s.replyError(w, op, string(requestID), code)
			return
		}
	}
	var out wire.Message
	if op.ID == wire.OpReadReceiverPhysicalInstallation {
		if s.Installations == nil {
			e = fault("OUTPUT_FENCE_UNPROVEN")
		} else {
			out, e = s.Installations.Read(ctx, pin, q.(*wire.ReadReceiverPhysicalInstallationRequest))
		}
	} else {
		out, e = s.Store.Handle(ctx, pin.actor, op.ID, wc, raw)
	}
	if e != nil {
		code := "DEPENDENCY_UNAVAILABLE"
		var ae *authority.Error
		if errors.As(e, &ae) {
			code = ae.Code
		}
		s.replyError(w, op, string(requestID), code)
		return
	}
	body, e := wire.EncodeResponse(op.ID, op.SuccessStatus, out)
	// DB Commit may already have happened. Never replace a lost/late response by
	// another true result. Client also subtracts all elapsed time before returning.
	if e != nil || ctx.Err() != nil || !pin.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
		s.replyError(w, op, string(requestID), "CONSUMPTION_UNKNOWN")
		return
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(op.SuccessStatus)
	_, _ = w.Write(body)
}

func operationForPath(path string) (wire.Operation, bool) {
	for _, id := range []wire.OperationID{wire.OpQueryReceiverAuthority, wire.OpCommitReceiverConsume, wire.OpQueryReceiverConsumption, wire.OpReadReceiverPhysicalInstallation} {
		o, _ := wire.LookupOperation(id)
		if o.Path == path {
			return o, true
		}
	}
	return wire.Operation{}, false
}
func (s *Server) replyError(w http.ResponseWriter, op wire.Operation, id, code string) {
	if op.ID == "" {
		op, _ = wire.LookupOperation(wire.OpQueryReceiverAuthority)
	}
	status, ok := op.ErrorCodes[code]
	if !ok {
		code = "DEPENDENCY_UNAVAILABLE"
		status = 503
	}
	b, e := wire.Encode(&wire.ReceiverErrorResponse{RequestID: wire.ID(id), Code: wire.ReceiverErrorResponseCode(code)})
	if e != nil {
		w.WriteHeader(503)
		return
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(b)))
	w.WriteHeader(status)
	_, _ = w.Write(b)
}
func scopeRequest(p *Pin, m wire.Message) error {
	var refs *wire.ReceiverReferences
	switch q := m.(type) {
	case *wire.QueryReceiverAuthorityRequest:
		refs = &q.References
	case *wire.CommitReceiverConsumeRequest:
		refs = &q.References
		if q.RuntimePrincipalID != p.binding.RuntimePrincipalID || q.RuntimeIncarnation != p.binding.RuntimeIncarnation {
			return denied()
		}
	case *wire.QueryReceiverConsumptionRequest:
		if q.BootstrapID != p.binding.BootstrapID {
			return denied()
		}
	case *wire.ReadReceiverPhysicalInstallationRequest:
		if q.PhysicalInstallProofRef != p.binding.PhysicalInstallProofRef {
			return denied()
		}
	default:
		return denied()
	}
	if refs != nil && refs.BootstrapID != p.binding.BootstrapID {
		return denied()
	}
	return nil
}
