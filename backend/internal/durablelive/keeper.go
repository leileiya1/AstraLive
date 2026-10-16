package durablelive

import (
	"context"
	"time"
)

// LeaseKeeper renews only leases already owned by this authenticated process.
// It never takes over another incarnation or revives an expired/stopped term.
type LeaseKeeper struct {
	Store     *Store
	Principal Principal
}

func (k *LeaseKeeper) Tick(ctx context.Context) error {
	p := k.Principal
	if p.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	rows, e := k.Store.DB.Query(ctx, `SELECT l.run_id,l.run_epoch,l.lease_version FROM dl05_run_leases l JOIN dl05_runs r USING(run_id) WHERE l.tenant_id=$1 AND l.owner_id=$2 AND l.lease_owner=$3 AND l.phase IN ('ACTIVE','PENDING_INSTALL') AND l.lease_expires_at>clock_timestamp() AND r.stop_revision=0 AND r.desired_state='LIVE' AND r.status NOT IN ('FAILED','STOPPED','STOPPING') ORDER BY l.lease_expires_at LIMIT 64`, p.TenantID, p.OwnerID, p.InstanceID)
	if e != nil {
		return e
	}
	type term struct {
		id             string
		epoch, version int64
	}
	terms := []term{}
	for rows.Next() {
		var t term
		if e = rows.Scan(&t.id, &t.epoch, &t.version); e != nil {
			rows.Close()
			return e
		}
		terms = append(terms, t)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, t := range terms {
		if _, e = k.Store.RenewLease(ctx, p, t.id, t.epoch, t.version); e != nil {
			if f, ok := e.(*Fault); ok && (f.Code == "LEASE_LOST" || f.Code == "RUN_STOPPED") {
				continue
			}
			return e
		}
	}
	return nil
}
func (k *LeaseKeeper) Run(ctx context.Context) error { return runLoop(ctx, 5*time.Second, k.Tick) }
