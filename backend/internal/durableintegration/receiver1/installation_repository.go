package receiver1

import (
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

func physicalHash(v wire.ReceiverPhysicalInstallation) string {
	b, e := wire.Encode(&v)
	if e != nil {
		return ""
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func (r *Registry) hold(ctx context.Context, p authority.Actor, b wire.ReceiverBootstrapBinding) (*installation, func(), error) {
	r.mu.RLock()
	in := r.records[string(b.CommandID)]
	r.mu.RUnlock()
	if in == nil || in.registrar != p || bindingHash(in.binding) != bindingHash(b) {
		return nil, nil, denied()
	}
	release, e := in.gate.acquire(ctx)
	return in, release, e
}

// checkMirror checks the complete immutable SQL mirror, native process identity
// and pinned key. It is outside the Authority transaction; the source gate stays
// held through Handle's SQL commit. Retirement takes the same Run-first lock
// order as Authority, with no physical read/IPC/fsync under that lock.
func (r *Registry) checkMirror(ctx context.Context, in *installation) error {
	v := in.gate.snapshot
	var good bool
	e := r.Store.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_v2_installations i
 JOIN dl05_v2_processes rt ON rt.principal_id=i.runtime_principal
 JOIN dl05_v2_processes g ON g.principal_id=i.guardian_principal
 WHERE i.proof_id=$1 AND i.command_id=$2 AND i.binding_hash=$3 AND i.binding=$4
 AND i.installation_revision=$5 AND i.observed_by=$6 AND i.guardian_principal=$7
 AND i.runtime_principal=$8 AND i.fence_ref=$9 AND i.retired_at IS NULL
 AND rt.tenant_id=$10 AND rt.owner_id=$11 AND rt.room_id=$12 AND g.tenant_id=$10 AND g.owner_id=$11 AND g.room_id=$12
 AND rt.role='REGISTERED_RUNTIME' AND g.role='OUTPUT_GUARDIAN' AND rt.incarnation=$13 AND g.incarnation=$14 AND rt.source_identity=$15 AND g.source_identity=$16
 AND g.key_id=$17 AND g.public_key=$18 AND rt.revoked_at IS NULL AND g.revoked_at IS NULL)`,
		string(in.binding.PhysicalInstallProofRef), string(in.binding.CommandID), bindingHash(in.binding), mustDocument(&in.binding), int64(v.InstallationRevision), in.registrar.ID, in.guardian.actor.ID, in.runtime.actor.ID, string(v.ClosedFenceProofRef), in.registrar.Tenant, in.registrar.Owner, in.registrar.Room, in.runtime.actor.Incarnation, in.guardian.actor.Incarnation, in.runtime.sourceIdentity(), in.guardian.sourceIdentity(), in.guardian.keyID, in.guardian.public).Scan(&good)
	if e != nil {
		return e
	}
	if !good {
		in.gate.CloseAdmission()
		return fault("OUTPUT_FENCE_UNPROVEN")
	}
	return nil
}

// RetireInstallation is the trusted host lifecycle's BEFORE-change barrier.
// Close is immediate; wait happens outside SQL. Existing SQL readers finish
// against the still-unchanged physical revision, then Run-locked retirement
// denies all later Authority operations, including callers bypassing this IPC.
// Frozen Revoke CAS preserves latches/audit/UNKNOWN. On error physical changes
// must not proceed; the gate never reopens. No immutable tuple is rewritten.
func (r *Registry) RetireInstallation(ctx context.Context, p authority.Actor, command string) error {
	r.mu.RLock()
	in := r.records[command]
	r.mu.RUnlock()
	if in == nil || p != in.registrar {
		return denied()
	}
	in.gate.CloseAdmission()
	if e := in.gate.wait(ctx); e != nil {
		return e
	}
	if in.settled.Load() {
		return nil
	}
	tx, e := r.Store.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	var run string
	e = tx.QueryRow(ctx, `SELECT run_id FROM dl05_runs WHERE run_id=$1 AND tenant_id=$2 AND owner_id=$3 AND room_id=$4 FOR UPDATE`, string(in.binding.RunID), p.Tenant, p.Owner, p.Room).Scan(&run)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_v2_installations SET retired_at=COALESCE(retired_at,clock_timestamp()) WHERE command_id=$1 AND proof_id=$2 AND binding_hash=$3 AND installation_revision=$4`, command, string(in.binding.PhysicalInstallProofRef), bindingHash(in.binding), int64(in.gate.snapshot.InstallationRevision))
	if e != nil {
		return e
	}
	if e = tx.Commit(ctx); e != nil {
		return e
	}
	known, e := r.Store.ReadRegistration(ctx, p, string(in.binding.BootstrapID))
	if e != nil {
		var ae *authority.Error
		if errors.As(e, &ae) && ae.Code == "RESOURCE_NOT_FOUND" {
			in.settled.Store(true)
			return nil
		}
		return e
	}
	if known["state"] == "REVOKED" {
		in.settled.Store(true)
		return nil
	}
	rev, ok := known["revision"].(int64)
	if !ok {
		return fault("DEPENDENCY_UNAVAILABLE")
	}
	q := &wire.RevokeReceiverBootstrapRequest{ContractRevision: "durable-live-2", ReceiverRevision: "receiver-1", RequestID: wire.ID(fresh("retire_")), BootstrapID: in.binding.BootstrapID, ExpectedRegistrationRevision: wire.Revision(rev), Reason: "SESSION_REPLACED"}
	op, _ := wire.LookupOperation(wire.OpRevokeReceiverBootstrap)
	wc := wire.RequestContext{Role: wire.RoleControlRegistrar, Target: op.Target, Method: op.Method, RouteTemplate: op.Path}
	raw, e := wire.EncodeRequest(op.ID, wc, q)
	if e != nil {
		return e
	}
	_, e = r.Store.Handle(ctx, p, op.ID, wc, raw)
	if e != nil {
		known, readErr := r.Store.ReadRegistration(ctx, p, string(in.binding.BootstrapID))
		if readErr != nil || known["state"] != "REVOKED" {
			return e
		}
	}
	in.settled.Store(true)
	return nil
}
func (r *Registry) holdPin(ctx context.Context, pin *Pin) (*installation, func(), error) {
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
		return nil, nil, fault("BOOTSTRAP_REQUIRED")
	}
	release, e := in.gate.acquire(ctx)
	if e != nil {
		return nil, nil, e
	}
	if _, e = r.observe(ctx, in); e == nil {
		e = r.checkMirror(ctx, in)
	}
	if e != nil {
		release()
		return nil, nil, e
	}
	return in, release, nil
}
