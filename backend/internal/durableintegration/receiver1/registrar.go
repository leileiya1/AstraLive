package receiver1

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"os"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

func ownedDirectory(st os.FileInfo) bool {
	s, ok := st.Sys().(*syscall.Stat_t)
	return ok && int(s.Uid) == os.Geteuid()
}
func document(m wire.Message) (authority.Document, error) {
	b, e := wire.Encode(m)
	if e != nil {
		return nil, e
	}
	var v authority.Document
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	e = d.Decode(&v)
	var integers func(any) any
	integers = func(x any) any {
		switch v := x.(type) {
		case json.Number:
			n, err := v.Int64()
			if err != nil {
				panic("validated noninteger")
			}
			return n
		case map[string]any:
			for k, w := range v {
				v[k] = integers(w)
			}
		case []any:
			for k, w := range v {
				v[k] = integers(w)
			}
		}
		return x
	}
	if e == nil {
		v = integers(v).(map[string]any)
	}
	return v, e
}
func bindingHash(b wire.ReceiverBootstrapBinding) string {
	raw, e := wire.Encode(&b)
	if e != nil {
		return ""
	}
	s := sha256.Sum256(raw)
	return hex.EncodeToString(s[:])
}

// PhysicalSource is a trusted supervisory adapter, not an RPC/enrollment body.
// It must independently observe the installed physical Session Generation and
// closed fence. OS liveness alone is insufficient. Nil always blocks Install.
// The current shared Session/media launcher does not yet supply this adapter.
type PhysicalSource interface {
	Observe(context.Context, wire.ReceiverBootstrapBinding, Identity, Identity) (wire.ReceiverPhysicalInstallation, error)
}
type installation struct {
	binding           wire.ReceiverBootstrapBinding
	runtime, guardian *Pin
	source            PhysicalSource
	registrar         authority.Actor
	settled           atomic.Bool
}

// Registry is the single command-dispatched InstallationSource on a Store.
// Entries are immutable and never recovered from Runtime/Guardian JSON.
type Registry struct {
	Store   *authority.Store
	mu      sync.RWMutex
	records map[string]*installation
}

func NewRegistry(s *authority.Store) (*Registry, error) {
	if s == nil || s.InstallationSource != nil {
		return nil, fault("STATE_CONFLICT")
	}
	r := &Registry{Store: s, records: make(map[string]*installation)}
	s.InstallationSource = r.VerifyInstallation
	return r, nil
}

// Provision precedes JournalAccept. It only mirrors already launched OS pins;
// this is not enrollment and confers no registration/START/media authority.
func (r *Registry) Provision(ctx context.Context, p authority.Actor, pins ...*Pin) error {
	if p.Role != "CONTROL_REGISTRAR" || p.ID == "" || p.Incarnation == "" {
		return denied()
	}
	for _, pin := range pins {
		if pin == nil || !pin.Alive() || pin.actor.Tenant != p.Tenant || pin.actor.Owner != p.Owner || pin.actor.Room != p.Room {
			return denied()
		}
		var role, inc, producer, keyID, source string
		var key []byte
		var revoked bool
		e := r.Store.DB.QueryRow(ctx, `SELECT role,incarnation,COALESCE(producer,''),COALESCE(key_id,''),source_identity,public_key,revoked_at IS NOT NULL FROM dl05_v2_processes WHERE principal_id=$1 AND tenant_id=$2 AND owner_id=$3 AND room_id=$4`, pin.actor.ID, p.Tenant, p.Owner, p.Room).Scan(&role, &inc, &producer, &keyID, &source, &key, &revoked)
		if e == nil {
			if revoked || role != pin.actor.Role || inc != pin.actor.Incarnation || producer != pin.actor.Producer || keyID != pin.keyID || source != pin.sourceIdentity() || !bytes.Equal(key, pin.public) {
				return denied()
			}
			continue
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if e = r.Store.ProvisionProcess(ctx, p, pin.actor.ID, pin.actor.Role, pin.actor.Incarnation, pin.actor.Producer, pin.keyID, pin.sourceIdentity(), pin.public); e != nil {
			return e
		}
	}
	return nil
}

// Install is co-located CONTROL code. The binding starts with the trusted
// Session control descriptor, then pins exact newly launched process identities.
// It does not allocate another Generation or infer old-output isolation.
func (r *Registry) Install(ctx context.Context, p authority.Actor, runtime, guardian *Pin, source PhysicalSource) (wire.ReceiverBootstrapBinding, error) {
	if source == nil {
		return wire.ReceiverBootstrapBinding{}, fault("OUTPUT_FENCE_UNPROVEN")
	}
	if p.Role != "CONTROL_REGISTRAR" || p.ID == "" || p.Incarnation == "" || runtime == nil || guardian == nil || !runtime.Alive() || !guardian.Alive() || runtime.actor.Role != "REGISTERED_RUNTIME" || guardian.actor.Role != "OUTPUT_GUARDIAN" {
		return wire.ReceiverBootstrapBinding{}, denied()
	}
	b := runtime.binding
	// Each process was launched for exactly the same trusted Session context.
	if bindingHash(b) == "" || bindingHash(b) != bindingHash(guardian.binding) || p.Tenant != string(b.TenantID) || p.Owner != string(b.OwnerID) || p.Room != string(b.RoomID) {
		return b, denied()
	}
	b.RuntimePrincipalID = wire.ID(runtime.actor.ID)
	b.RuntimeIncarnation = wire.ID(runtime.actor.Incarnation)
	b.GuardianIncarnation = wire.ID(guardian.actor.Incarnation)
	in := &installation{binding: b, runtime: runtime, guardian: guardian, source: source, registrar: p}
	// Observe before mirroring process/install rows, and again from RecordInstallation.
	if _, e := r.observe(ctx, in); e != nil {
		return b, fmt.Errorf("initial independent observation: %w", e)
	}
	r.mu.Lock()
	if len(r.records) >= 1024 {
		r.mu.Unlock()
		return b, fault("OVERLOADED")
	}
	if _, exists := r.records[string(b.CommandID)]; exists {
		r.mu.Unlock()
		return b, fault("STATE_CONFLICT")
	}
	r.records[string(b.CommandID)] = in
	r.mu.Unlock()
	// The process pins are not exposed by a listener until Install returns.
	runtime.binding = b
	guardian.binding = b
	if e := r.Provision(ctx, p, runtime, guardian); e != nil {
		return b, e
	}
	if e := r.Store.RecordInstallation(ctx, p, mustDocument(&b)); e != nil {
		return b, fmt.Errorf("record installation: %w", e)
	}
	return b, nil
}
func mustDocument(m wire.Message) authority.Document { v, _ := document(m); return v }
func (r *Registry) observe(ctx context.Context, in *installation) (wire.ReceiverPhysicalInstallation, error) {
	if in.settled.Load() || !in.runtime.Alive() || !in.guardian.Alive() {
		return wire.ReceiverPhysicalInstallation{}, fault("REGISTRATION_REVOKED")
	}
	actual, e := in.source.Observe(ctx, in.binding, in.runtime.identity, in.guardian.identity)
	if e != nil {
		return actual, e
	}
	if _, e = wire.Encode(&actual); e != nil {
		return actual, fault("OUTPUT_FENCE_UNPROVEN")
	}
	if bindingHash(actual.Binding) != bindingHash(in.binding) || actual.GuardianPrincipalID != wire.ID(in.guardian.actor.ID) || actual.ObservedByPrincipalID != wire.ID(in.registrar.ID) || actual.State != "CLOSED_INSTALLED" {
		return actual, fault("OUTPUT_FENCE_UNPROVEN")
	}
	// Read current durable Session/Binding/term independently of the source.
	var valid bool
	e = r.Store.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runs r
 JOIN dl05_run_leases l USING(run_id) JOIN dl05_run_terms t ON t.run_id=r.run_id AND t.run_epoch=r.run_epoch
 JOIN live_sessions s ON s.id=r.current_session_id
 JOIN session_provider_bindings b ON b.session_id=s.id
 JOIN live_rooms room ON room.id=r.room_id
 JOIN dl05_room_outputs o ON o.room_id=r.room_id
 JOIN dl05_run_slots slot ON slot.run_id=r.run_id
 WHERE r.run_id=$1 AND r.tenant_id=$2 AND r.owner_id=$3 AND r.room_id=$4
 AND r.current_session_id=$5 AND r.run_epoch=$6 AND r.stop_revision=0 AND r.desired_state='LIVE'
 AND l.phase='ACTIVE' AND l.run_epoch=r.run_epoch AND l.lease_expires_at>clock_timestamp()
 AND t.producer_incarnation=$7 AND slot.active_attempt_id=$8
 AND b.tenant_id=r.tenant_id AND b.user_id=r.owner_id AND b.released_at IS NULL AND b.expires_at>clock_timestamp()
 AND s.status IN ('LIVE','DEGRADED') AND room.active_product_id IS NOT DISTINCT FROM NULLIF(b.room_snapshot->>'activeProductId','')
 AND o.active_run_id=r.run_id AND o.guardian_id=$9 AND o.output_binding_version=$10 AND o.expires_at>clock_timestamp()
 AND o.fence_proof_ref=$11)`, string(in.binding.RunID), in.registrar.Tenant, in.registrar.Owner, in.registrar.Room, string(in.binding.SessionID), int64(in.binding.RunEpoch), string(in.binding.ProducerIncarnation), string(in.binding.AttemptID), string(in.binding.GuardianID), int64(in.binding.OutputBindingVersion), string(actual.ClosedFenceProofRef)).Scan(&valid)
	if e != nil {
		return actual, e
	}
	if !valid || !in.runtime.Alive() || !in.guardian.Alive() {
		return actual, fault("OUTPUT_FENCE_UNPROVEN")
	}
	return actual, nil
}

// VerifyInstallation is installed once as Store.InstallationSource. There is no
// last-session-wins callback and no default-success physical observation.
func (r *Registry) VerifyInstallation(ctx context.Context, p authority.Actor, b authority.Document) (authority.Document, error) {
	command, _ := b["commandId"].(string)
	r.mu.RLock()
	in := r.records[command]
	r.mu.RUnlock()
	if in == nil || p != in.registrar {
		return nil, denied()
	}
	raw, e := json.Marshal(b)
	if e != nil {
		return nil, e
	}
	v, e := wire.Decode("ReceiverBootstrapBinding", raw)
	if e != nil {
		return nil, e
	}
	if bindingHash(*v.(*wire.ReceiverBootstrapBinding)) != bindingHash(in.binding) {
		return nil, denied()
	}
	actual, e := r.observe(ctx, in)
	if e != nil {
		return nil, e
	}
	return document(&actual)
}
func (r *Registry) Read(ctx context.Context, pin *Pin, q *wire.ReadReceiverPhysicalInstallationRequest) (wire.Message, error) {
	r.mu.RLock()
	var in *installation
	for _, v := range r.records {
		if v.binding.PhysicalInstallProofRef == q.PhysicalInstallProofRef {
			in = v
			break
		}
	}
	r.mu.RUnlock()
	if in == nil || pin != in.guardian || q.ExpectedBindingHash != wire.Hash(bindingHash(in.binding)) {
		return nil, denied()
	}
	actual, e := r.observe(ctx, in)
	if e != nil {
		return nil, e
	}
	return &wire.ReadReceiverPhysicalInstallationResponse{RequestID: q.RequestID, Installation: actual}, nil
}

// Register accepts the signed closed-stage receipt, not any new identity/key.
// On ACK ambiguity the caller uses Confirm only, never regenerates a bootstrap.
func (r *Registry) Register(ctx context.Context, p authority.Actor, b wire.ReceiverBootstrapBinding, receipt wire.ReceiverStageReceipt) (wire.Message, error) {
	if _, e := r.VerifyInstallation(ctx, p, mustDocument(&b)); e != nil {
		return nil, e
	}
	var rev, lease int64
	e := r.Store.DB.QueryRow(ctx, `SELECT r.state_revision,l.lease_version FROM dl05_runs r JOIN dl05_run_leases l USING(run_id) WHERE r.run_id=$1 AND r.tenant_id=$2 AND r.owner_id=$3 AND r.room_id=$4`, string(b.RunID), p.Tenant, p.Owner, p.Room).Scan(&rev, &lease)
	if e != nil {
		return nil, e
	}
	q := &wire.RegisterReceiverBootstrapRequest{ContractRevision: "durable-live-2", ReceiverRevision: "receiver-1", RequestID: wire.ID(fresh("register_")), Binding: b, Receipt: receipt, ExpectedRunRevision: wire.Revision(rev), ExpectedLeaseVersion: wire.Revision(lease), ExpectedRegistrationRevision: 0}
	op, _ := wire.LookupOperation(wire.OpRegisterReceiverBootstrap)
	wc := wire.RequestContext{Role: wire.RoleControlRegistrar, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	raw, e := wire.EncodeRequest(op.ID, wc, q)
	if e != nil {
		return nil, e
	}
	return r.Store.Handle(ctx, p, op.ID, wc, raw)
}

func (r *Registry) StageRequest(ctx context.Context, p authority.Actor, b wire.ReceiverBootstrapBinding) (*wire.ReceiverStageRequest, error) {
	if _, e := r.VerifyInstallation(ctx, p, mustDocument(&b)); e != nil {
		return nil, e
	}
	if _, e := r.Store.ReadRegistration(ctx, p, string(b.BootstrapID)); e == nil {
		return nil, fault("STATE_CONFLICT")
	} else {
		var ae *authority.Error
		if !errors.As(e, &ae) || ae.Code != "RESOURCE_NOT_FOUND" {
			return nil, e
		}
	}
	ch, e := r.Store.IssueStageChallenge(ctx, p, mustDocument(&b))
	if e != nil {
		return nil, e
	}
	q := map[string]any{"contractRevision": "durable-live-2", "receiverRevision": "receiver-1", "requestId": fresh("stage_"), "binding": b, "challenge": ch["challenge"], "challengeIssuedAt": ch["challengeIssuedAt"], "challengeExpiresAt": ch["challengeExpiresAt"]}
	raw, e := json.Marshal(q)
	if e != nil {
		return nil, e
	}
	m, e := wire.Decode("ReceiverStageRequest", raw)
	if e != nil {
		return nil, e
	}
	return m.(*wire.ReceiverStageRequest), nil
}
func (r *Registry) Confirm(ctx context.Context, p authority.Actor, b wire.ReceiverBootstrapBinding) (authority.Document, error) {
	// Historical metadata is deliberately not authorization to stage/consume.
	known, e := r.Store.ReadRegistration(ctx, p, string(b.BootstrapID))
	if e != nil {
		return nil, e
	}
	if known["registrationHash"] != bindingHash(b) {
		return nil, fault("EVIDENCE_CONFLICT")
	}
	return known, nil
}

// ReconcileDead is called by the trusted Session supervisor, not by Runtime.
// Revocation uses the existing frozen CAS operation, never deletes/reissues a
// latch. Database outage returns an error; process pins remain denied locally.
func (r *Registry) ReconcileDead(ctx context.Context, command string) error {
	r.mu.RLock()
	in := r.records[command]
	r.mu.RUnlock()
	if in == nil {
		return fault("RESOURCE_NOT_FOUND")
	}
	if in.settled.Load() {
		return nil
	}
	if in.runtime.Alive() && in.guardian.Alive() {
		return fault("STATE_CONFLICT")
	}
	if !in.runtime.Alive() {
		in.runtime.Retire()
	}
	if !in.guardian.Alive() {
		in.guardian.Retire()
	}
	registration, e := r.Store.ReadRegistration(ctx, in.registrar, string(in.binding.BootstrapID))
	if e != nil {
		return e
	}
	if registration["state"] == "REVOKED" {
		in.settled.Store(true)
		return nil
	}
	n, ok := registration["revision"].(int64)
	if !ok {
		return fault("DEPENDENCY_UNAVAILABLE")
	}
	q := &wire.RevokeReceiverBootstrapRequest{ContractRevision: "durable-live-2", ReceiverRevision: "receiver-1", RequestID: wire.ID(fresh("revoke_")), BootstrapID: in.binding.BootstrapID, ExpectedRegistrationRevision: wire.Revision(n), Reason: "SESSION_REPLACED"}
	op, _ := wire.LookupOperation(wire.OpRevokeReceiverBootstrap)
	wc := wire.RequestContext{Role: wire.RoleControlRegistrar, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	raw, e := wire.EncodeRequest(op.ID, wc, q)
	if e != nil {
		return e
	}
	_, e = r.Store.Handle(ctx, in.registrar, op.ID, wc, raw)
	if e != nil {
		// Concurrent supervisors may lose CAS; accept only durable revoked knowledge.
		known, readErr := r.Store.ReadRegistration(ctx, in.registrar, string(in.binding.BootstrapID))
		if readErr == nil && known["state"] == "REVOKED" {
			in.settled.Store(true)
			return nil
		}
	} else {
		in.settled.Store(true)
	}
	return e
}

func (r *Registry) eligible(ctx context.Context, pin *Pin) error {
	r.mu.RLock()
	var in *installation
	for _, v := range r.records {
		if v.guardian == pin {
			in = v
			break
		}
	}
	r.mu.RUnlock()
	if in == nil {
		return fault("BOOTSTRAP_REQUIRED")
	}
	if !in.runtime.Alive() || !in.guardian.Alive() {
		_ = r.ReconcileDead(ctx, string(in.binding.CommandID))
		return fault("REGISTRATION_REVOKED")
	}
	_, e := r.observe(ctx, in)
	return e
}

// Supervise is owned by the private server lifetime. It only reconciles dead
// managed pins using the existing CAS revoke, without touching shared processes.
// SQL failure leaves local admission closed and the next bounded poll retries.
func (r *Registry) supervise(ctx context.Context) {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		r.mu.RLock()
		all := make([]*installation, 0, len(r.records))
		for _, in := range r.records {
			all = append(all, in)
		}
		r.mu.RUnlock()
		for _, in := range all {
			if ctx.Err() != nil {
				return
			}
			if in.settled.Load() || in.runtime.Alive() && in.guardian.Alive() {
				continue
			}
			one, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
			_ = r.ReconcileDead(one, string(in.binding.CommandID))
			cancel()
		}
	}
}
