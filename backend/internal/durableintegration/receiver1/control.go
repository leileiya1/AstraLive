package receiver1

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

// ControlChannel is the co-located Registrar's distinct process credential.
// Only its verifier and OS pin go to Guardian's private deployment bootstrap.
// Runtime never receives this credential or CONTROL provisioning record.
type ControlChannel struct {
	actor    authority.Actor
	identity Identity
	token    string
	digest   [32]byte
}

// ProducerProvision is deployment-only verifier metadata for Guardian IPC.
// It is neither a Runtime enrollment API nor a reusable producer credential.
func ProducerProvision(pin *Pin) (map[string]any, error) {
	if pin == nil || !pin.Alive() || pin.actor.Role != "REGISTERED_RUNTIME" {
		return nil, denied()
	}
	return map[string]any{"principalId": pin.actor.ID, "incarnation": pin.actor.Incarnation, "role": "REGISTERED_RUNTIME", "scope": []string{pin.actor.Tenant, pin.actor.Owner, pin.actor.Room}, "identity": pin.identity, "credentialHash": hex.EncodeToString(pin.digest[:])}, nil
}

func (c *ControlChannel) String() string             { return "ControlChannel{redacted}" }
func (c *ControlChannel) GoString() string           { return c.String() }
func (c *ControlChannel) Format(s fmt.State, _ rune) { fmt.Fprint(s, c.String()) }
func (c *ControlChannel) LogValue() slog.Value       { return slog.StringValue(c.String()) }

func NewControlChannel(p authority.Actor) (*ControlChannel, error) {
	if p.Role != "CONTROL_REGISTRAR" || p.ID == "" || p.Incarnation == "" || p.Tenant == "" || p.Owner == "" || p.Room == "" {
		return nil, denied()
	}
	native, e := processIdentity(os.Getpid())
	if e != nil {
		return nil, e
	}
	var seed [32]byte
	if _, e = rand.Read(seed[:]); e != nil {
		return nil, e
	}
	token := base64.RawURLEncoding.EncodeToString(seed[:])
	return &ControlChannel{p, native, token, sha256.Sum256([]byte(token))}, nil
}
func (c *ControlChannel) provision() map[string]any {
	return map[string]any{"principalId": c.actor.ID, "incarnation": c.actor.Incarnation, "role": "CONTROL_REGISTRAR", "scope": []string{c.actor.Tenant, c.actor.Owner, c.actor.Room}, "identity": c.identity, "credentialHash": hex.EncodeToString(c.digest[:])}
}

// Stage only uses the frozen CONTROL→Guardian operation; no generic RPC or
// Register/lease/media capability is available to a Guardian or Runtime caller.
func (c *ControlChannel) Stage(ctx context.Context, path string, guardian *Pin, q *wire.ReceiverStageRequest) (*wire.ReceiverStageResponse, error) {
	native, e := processIdentity(os.Getpid())
	if e != nil || native != c.identity || guardian == nil || !guardian.Alive() || guardian.actor.Role != "OUTPUT_GUARDIAN" || c.actor.Tenant != guardian.actor.Tenant || c.actor.Owner != guardian.actor.Owner || c.actor.Room != guardian.actor.Room {
		return nil, denied()
	}
	in := guardian.installation
	if in == nil || in.registrar != c.actor || bindingHash(q.Binding) != bindingHash(in.binding) {
		return nil, fault("BOOTSTRAP_REQUIRED")
	}
	release, e := in.gate.acquire(ctx)
	if e != nil {
		return nil, e
	}
	defer release()
	if _, e = in.registry.observe(ctx, in); e != nil {
		return nil, e
	}
	if e = in.registry.checkMirror(ctx, in); e != nil {
		return nil, e
	}
	parent, e := os.Lstat(filepath.Dir(path))
	if e != nil || !parent.IsDir() || parent.Mode().Perm() != 0700 || !ownedDirectory(parent) {
		return nil, denied()
	}
	op, _ := wire.LookupOperation(wire.OpReceiverStage)
	wc := wire.RequestContext{Role: wire.RoleControlRegistrar, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	body, e := wire.EncodeRequest(op.ID, wc, q)
	if e != nil {
		return nil, e
	}
	bound, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
	defer cancel()
	tr := &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		conn, e := (&net.Dialer{}).DialContext(ctx, "unix", path)
		if e != nil {
			return nil, e
		}
		raw, e := conn.(*net.UnixConn).SyscallConn()
		if e != nil {
			conn.Close()
			return nil, e
		}
		var who Identity
		var pe error
		e = raw.Control(func(fd uintptr) { who, pe = socketIdentity(int(fd)) })
		if e != nil || pe != nil || who != guardian.identity || !guardian.Alive() {
			conn.Close()
			return nil, denied()
		}
		return conn, nil
	}}
	defer tr.CloseIdleConnections()
	client := &http.Client{Transport: tr, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	req, e := http.NewRequestWithContext(bound, "POST", "http://private"+op.Path, strings.NewReader(string(body)))
	if e != nil {
		return nil, e
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.token)
	res, e := client.Do(req)
	if e != nil {
		return nil, fault("CONSUMPTION_UNKNOWN")
	}
	defer res.Body.Close()
	raw, e := io.ReadAll(io.LimitReader(res.Body, int64(op.MaxBodyBytes)+1))
	if e != nil || len(raw) > op.MaxBodyBytes || !guardian.Alive() {
		return nil, fault("CONSUMPTION_UNKNOWN")
	}
	decoded, e := wire.DecodeResponse(op.ID, res.StatusCode, raw)
	if e != nil {
		return nil, fault("INVALID_ARGUMENT")
	}
	if failed, ok := decoded.(*wire.ReceiverErrorResponse); ok {
		return nil, fault(string(failed.Code))
	}
	out := decoded.(*wire.ReceiverStageResponse)
	if out.RequestID != q.RequestID {
		return nil, fault("CONSUMPTION_UNKNOWN")
	}
	if _, e = in.registry.observe(ctx, in); e != nil {
		return nil, e
	}
	if !in.gate.valid() || out.Receipt.InstallationRevision != in.gate.snapshot.InstallationRevision || out.Receipt.GuardianPrincipalID != wire.ID(guardian.actor.ID) || out.Receipt.KeyID != wire.ID(guardian.keyID) || out.Receipt.BindingHash != wire.Hash(bindingHash(in.binding)) {
		return nil, fault("EVIDENCE_CONFLICT")
	}
	return out, nil
}
