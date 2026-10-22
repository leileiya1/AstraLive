package receiver1

import (
	"context"
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
)

// ObserverPath is the single private route for a pinned OBSERVER process. It
// carries authority.Store.RecordDrainEvidence (a trusted repository seam), not
// a frozen durable-live-2 operation; no public router mounts it.
const ObserverPath = "/registrar/receiver-1/observer/drain-evidence"

// ObserverPin is a managed OBSERVER process plus the sink kinds it is able to
// observe (deployment configuration, never request JSON). An RTMP observer
// can never vouch for a WebRTC track and vice versa.
type ObserverPin struct {
	pin   *Pin
	kinds map[string]bool
}

func NewObserverPin(p *Pin, kinds ...string) (*ObserverPin, error) {
	if p == nil || p.actor.Role != "OBSERVER" || !p.Alive() || len(kinds) == 0 {
		return nil, denied()
	}
	allowed := map[string]bool{}
	for _, k := range kinds {
		if k != "RTMP_PIPE_WRITE" && k != "WEBRTC_TRACK_RECV" {
			return nil, fault("INVALID_ARGUMENT")
		}
		allowed[k] = true
	}
	return &ObserverPin{pin: p, kinds: allowed}, nil
}

// ObserverVerifier is the Store.Observer callback. It runs before the Store's
// own transaction (scope, registration, consumption latch, ranges, continuity).
func ObserverVerifier(pins ...*ObserverPin) func(context.Context, authority.Actor, authority.Document, authority.Document) error {
	byID := map[string]*ObserverPin{}
	for _, p := range pins {
		if p != nil {
			byID[p.pin.actor.ID] = p
		}
	}
	return func(_ context.Context, a authority.Actor, artifact, evidence authority.Document) error {
		p := byID[a.ID]
		if p == nil || !p.pin.Alive() || a != p.pin.actor {
			return denied()
		}
		if evidence["evidenceType"] != "ALL_REQUIRED_DRAIN" || artifact["artifactHash"] == nil {
			return fault("EVIDENCE_CONFLICT")
		}
		proofs, ok := evidence["sinkProofs"].([]any)
		if !ok || len(proofs) == 0 {
			return fault("EVIDENCE_CONFLICT")
		}
		for _, raw := range proofs {
			proof, ok := raw.(map[string]any)
			if !ok || proof["terminal"] != true || !p.kinds[textOf(proof["kind"])] {
				return fault("EVIDENCE_CONFLICT")
			}
		}
		return nil
	}
}

func textOf(v any) string { s, _ := v.(string); return s }

type ObserverServer struct {
	Store    *authority.Store
	pins     []*ObserverPin
	http     *http.Server
	listener net.Listener
	slots    chan struct{}
}

// NewObserverServer refuses to start unless the Store's verifier is installed;
// without it RecordDrainEvidence fails closed anyway.
func NewObserverServer(store *authority.Store, pins ...*ObserverPin) (*ObserverServer, error) {
	if store == nil || store.DB == nil || store.Observer == nil || len(pins) == 0 || len(pins) > 16 {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	for _, p := range pins {
		if p == nil || !p.pin.Alive() {
			return nil, denied()
		}
	}
	s := &ObserverServer{Store: store, pins: append([]*ObserverPin(nil), pins...), slots: make(chan struct{}, 4)}
	s.http = &http.Server{Handler: s, ReadHeaderTimeout: 250 * time.Millisecond, ReadTimeout: 500 * time.Millisecond, WriteTimeout: 2 * time.Second, IdleTimeout: time.Second, MaxHeaderBytes: 8192, ErrorLog: log.New(io.Discard, "", 0), ConnContext: peerContext}
	return s, nil
}

func (s *ObserverServer) Listen(path string) error {
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
	bounded := &limitedListener{Listener: l, tokens: make(chan struct{}, 4), done: make(chan struct{})}
	if e = os.Chmod(path, 0600); e != nil {
		l.Close()
		return e
	}
	s.listener = bounded
	go s.http.Serve(bounded)
	return nil
}

func (s *ObserverServer) Close() error { return s.http.Close() }

func observerReply(w http.ResponseWriter, status int, body map[string]any) {
	b, _ := json.Marshal(body)
	w.Header().Set("Content-Length", strconv.Itoa(len(b)))
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

func (s *ObserverServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Connection", "close")
	r.Close = true
	refuse := func(code string, status int) { observerReply(w, status, map[string]any{"code": code}) }
	if r.URL.Path != ObserverPath || r.Method != http.MethodPost || r.URL.RawQuery != "" {
		refuse("FORBIDDEN", 403)
		return
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		refuse("OVERLOADED", 429)
		return
	}
	peer, ok := r.Context().Value(peerKey{}).(connectionPeer)
	auth := r.Header.Get("Authorization")
	if !ok || len(r.Header.Values("Authorization")) != 1 || !strings.HasPrefix(auth, "Bearer ") || len(auth) > 256 ||
		len(r.TransferEncoding) != 0 || r.ContentLength <= 0 || r.ContentLength > 262144 {
		refuse("UNAUTHENTICATED", 401)
		return
	}
	var pin *ObserverPin
	for _, p := range s.pins {
		if p.pin.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
			pin = p
		}
	}
	if pin == nil {
		refuse("UNAUTHENTICATED", 401)
		return
	}
	raw, e := io.ReadAll(io.LimitReader(r.Body, 262145))
	if e != nil || len(raw) != int(r.ContentLength) {
		refuse("INVALID_ARGUMENT", 422)
		return
	}
	var q struct {
		CommandID  string             `json:"commandId"`
		ArtifactID string             `json:"artifactId"`
		Evidence   authority.Document `json:"evidence"`
	}
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.DisallowUnknownFields()
	d.UseNumber()
	if d.Decode(&q) != nil || q.CommandID == "" || q.ArtifactID == "" || q.Evidence == nil {
		refuse("INVALID_ARGUMENT", 422)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), time.Second)
	defer cancel()
	if e = s.Store.RecordDrainEvidence(ctx, pin.pin.actor, q.CommandID, q.ArtifactID, integerize(q.Evidence)); e != nil {
		code, status := "DEPENDENCY_UNAVAILABLE", 503
		var ae *authority.Error
		if errors.As(e, &ae) {
			code, status = ae.Code, 409
			if code == "UNAUTHENTICATED" || code == "FORBIDDEN" {
				status = 403
			}
		}
		refuse(code, status)
		return
	}
	if ctx.Err() != nil || !pin.pin.authenticate(peer.identity, strings.TrimPrefix(auth, "Bearer ")) {
		refuse("DEPENDENCY_UNAVAILABLE", 503) // recorded state is readable; never a false positive
		return
	}
	observerReply(w, 200, map[string]any{"recorded": true, "evidenceRef": q.Evidence["evidenceRef"]})
}

// integerize turns json.Number into int64/float64 as the Store's documents expect.
func integerize(v any) authority.Document {
	var walk func(any) any
	walk = func(x any) any {
		switch t := x.(type) {
		case map[string]any:
			for k, v := range t {
				t[k] = walk(v)
			}
			return t
		case []any:
			for i, v := range t {
				t[i] = walk(v)
			}
			return t
		case json.Number:
			if i, e := t.Int64(); e == nil {
				return i
			}
			f, _ := t.Float64()
			return f
		}
		return x
	}
	return walk(v).(map[string]any)
}
