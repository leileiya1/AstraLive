package receiver1

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

// JournalPin is the RUNTIME_JOURNAL capability of an already managed Runtime
// process: same principal/incarnation and OS identity as its REGISTERED_RUNTIME
// pin (the START ticket verifier is bound to that principal), but a distinct
// credential. It is created by trusted deployment code, never from JSON, and
// stops authenticating as soon as the Runtime pin is retired or its process ends.
type JournalPin struct {
	runtime *Pin
	actor   authority.Actor
	digest  [32]byte
}

// NewJournalPin returns the pin and its one-time plaintext credential, which the
// caller must hand to that process over a private channel and then drop.
func NewJournalPin(runtime *Pin) (*JournalPin, string, error) {
	if runtime == nil || runtime.actor.Role != "REGISTERED_RUNTIME" || !runtime.Alive() {
		return nil, "", denied()
	}
	var seed [32]byte
	if _, e := rand.Read(seed[:]); e != nil {
		return nil, "", e
	}
	token := base64.RawURLEncoding.EncodeToString(seed[:])
	actor := runtime.actor
	actor.Role = "RUNTIME_JOURNAL"
	return &JournalPin{runtime: runtime, actor: actor, digest: sha256.Sum256([]byte(token))}, token, nil
}

func (p *JournalPin) Actor() authority.Actor { return p.actor }
func (p *JournalPin) authenticate(i Identity, credential string) bool {
	d := sha256.Sum256([]byte(credential))
	return p.runtime.Alive() && i == p.runtime.identity && subtle.ConstantTimeCompare(d[:], p.digest[:]) == 1
}

// JournalServer exposes exactly the frozen RUNTIME_JOURNAL Backend operations
// to pinned Runtime processes over a private AF_UNIX socket. Every request is
// delegated to authority.Store.Handle, which enforces role, scope and state.
// No public router mounts it; there is no enrollment or fallback route.
type JournalServer struct {
	Store    *authority.Store
	pins     []*JournalPin
	http     *http.Server
	listener net.Listener
	slots    chan struct{}
	timeout  time.Duration
}

func NewJournalServer(store *authority.Store, pins ...*JournalPin) (*JournalServer, error) {
	if store == nil || store.DB == nil || len(pins) == 0 || len(pins) > 128 {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	for _, p := range pins {
		if p == nil || p.actor.Role != "RUNTIME_JOURNAL" || !p.runtime.Alive() {
			return nil, denied()
		}
	}
	s := &JournalServer{Store: store, pins: append([]*JournalPin(nil), pins...), slots: make(chan struct{}, 16), timeout: time.Second}
	s.http = &http.Server{Handler: s, ReadHeaderTimeout: 250 * time.Millisecond, ReadTimeout: 500 * time.Millisecond, WriteTimeout: 2 * time.Second, IdleTimeout: time.Second, MaxHeaderBytes: 8192, ErrorLog: log.New(io.Discard, "", 0), ConnContext: peerContext}
	return s, nil
}

// peerContext attaches the kernel-reported peer identity of an accepted
// AF_UNIX connection; anything else carries no identity and is refused.
func peerContext(ctx context.Context, c net.Conn) context.Context {
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
	if e = raw.Control(func(fd uintptr) { p, err = socketIdentity(int(fd)) }); e != nil || err != nil {
		return ctx
	}
	return context.WithValue(ctx, peerKey{}, connectionPeer{p, c})
}

func (s *JournalServer) Listen(path string) error {
	if s.listener != nil {
		return fault("STATE_CONFLICT")
	}
	st, e := os.Lstat(filepath.Dir(path))
	if e != nil || !st.IsDir() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm() != 0700 || !ownedDirectory(st) {
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
	if e = os.Chmod(path, 0600); e != nil {
		l.Close()
		return e
	}
	s.listener = bounded
	go s.http.Serve(bounded)
	return nil
}

func (s *JournalServer) Close() error { return s.http.Close() }

// journalRoute resolves the route template with its single {runId}/{sessionId}
// segment; the body must name the same run, so the URL cannot widen scope.
func journalRoute(urlPath string) (wire.Operation, string, bool) {
	for _, id := range []wire.OperationID{
		wire.OpJournalAccept, wire.OpJournalStart, wire.OpAcquireOutputPermit, wire.OpConfirmRunFence,
		wire.OpJournalPrepareAnswer, wire.OpJournalStartAnswerSegment, wire.OpJournalConfirmAnswerSegment,
		wire.OpJournalSealAnswer, wire.OpJournalQueryAnswer, wire.OpConfirmCheckpoint, wire.OpQueryExecutionStatus,
	} {
		o, _ := wire.LookupOperation(id)
		prefix, suffix, ok := strings.Cut(o.Path, "{runId}")
		if !ok || !strings.HasPrefix(urlPath, prefix) || !strings.HasSuffix(urlPath, suffix) {
			continue
		}
		run := strings.TrimSuffix(strings.TrimPrefix(urlPath, prefix), suffix)
		if run != "" && !strings.ContainsAny(run, "/?#%") {
			return o, run, true
		}
	}
	return wire.Operation{}, "", false
}

func (s *JournalServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Connection", "close")
	r.Close = true
	op, run, ok := journalRoute(r.URL.Path)
	if !ok || r.Method != op.Method || r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		journalError(w, op, "transport_error", "FORBIDDEN")
		return
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		journalError(w, op, "transport_error", "OVERLOADED")
		return
	}
	peer, ok := r.Context().Value(peerKey{}).(connectionPeer)
	auth := r.Header.Get("Authorization")
	if !ok || len(r.Header.Values("Authorization")) != 1 || !strings.HasPrefix(auth, "Bearer ") || len(auth) > 256 ||
		len(r.TransferEncoding) != 0 || r.ContentLength <= 0 || r.ContentLength > int64(op.MaxBodyBytes) {
		journalError(w, op, "transport_error", "UNAUTHENTICATED")
		return
	}
	var pin *JournalPin
	for _, p := range s.pins {
		if p.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
			if pin != nil {
				journalError(w, op, "transport_error", "UNAUTHENTICATED")
				return
			}
			pin = p
		}
	}
	if pin == nil {
		journalError(w, op, "transport_error", "UNAUTHENTICATED")
		return
	}
	raw, e := io.ReadAll(io.LimitReader(r.Body, int64(op.MaxBodyBytes)+1))
	if e != nil || len(raw) != int(r.ContentLength) {
		journalError(w, op, "transport_error", "INVALID_ARGUMENT")
		return
	}
	var envelope struct {
		RequestID string `json:"requestId"`
		RunID     string `json:"runId"`
	}
	if json.Unmarshal(raw, &envelope) != nil || envelope.RequestID == "" {
		journalError(w, op, "transport_error", "INVALID_ARGUMENT")
		return
	}
	if envelope.RunID != run {
		journalError(w, op, envelope.RequestID, "FORBIDDEN")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.timeout)
	defer cancel()
	wc := wire.RequestContext{Role: wire.Role("RUNTIME_JOURNAL"), Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	out, e := s.Store.Handle(ctx, pin.actor, op.ID, wc, raw)
	if e != nil {
		code := "DEPENDENCY_UNAVAILABLE"
		var ae *authority.Error
		if errors.As(e, &ae) {
			code = ae.Code
		}
		journalError(w, op, envelope.RequestID, code)
		return
	}
	body, e := wire.EncodeResponse(op.ID, op.SuccessStatus, out)
	// A committed START may be lost here; never substitute another true reply.
	// The Runtime treats any non-success as UNKNOWN for that command.
	if e != nil || ctx.Err() != nil || !pin.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
		journalError(w, op, envelope.RequestID, "DEPENDENCY_UNAVAILABLE")
		return
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(op.SuccessStatus)
	_, _ = w.Write(body)
}

func journalError(w http.ResponseWriter, op wire.Operation, id, code string) {
	if op.ID == "" {
		op, _ = wire.LookupOperation(wire.OpJournalQueryAnswer)
	}
	status, ok := op.ErrorCodes[code]
	if !ok {
		code, status = "DEPENDENCY_UNAVAILABLE", 503
	}
	b, e := wire.Encode(&wire.Error{RequestID: wire.ID(id), Code: wire.ErrorCode(code), Message: code, Retryable: false})
	if e != nil {
		w.WriteHeader(503)
		return
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(b)))
	w.WriteHeader(status)
	_, _ = w.Write(b)
}
