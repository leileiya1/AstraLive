package durableintegration

import (
	"context"
	"errors"
	"time"

	"astralive/backend/internal/contentplan"
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/durablelive"
)

// Facts reuses the authoritative Product Tool SQL source. No cached timestamp
// or LLM output can validate a changed assertion. Unsupported SKU/promotion/
// delivery facts deliberately have no value hash.
type Facts struct {
	Store     *durablelive.Store
	Principal durablelive.Principal
	RunID     string
}

var _ turnmanagerFacts = Facts{}

type turnmanagerFacts interface {
	Revalidate(context.Context, c.ContentPlan, []c.FactDependency) ([]c.FactDependency, error)
}

func (f Facts) Revalidate(ctx context.Context, plan c.ContentPlan, deps []c.FactDependency) ([]c.FactDependency, error) {
	if f.Store == nil || plan.RunId != f.RunID || plan.TenantId != f.Principal.TenantID || plan.OwnerId != f.Principal.OwnerID {
		return nil, errors.New("FORBIDDEN")
	}
	v, err := f.Store.ReadProduct(ctx, f.Principal, f.RunID)
	if err != nil {
		return nil, err
	}
	if v.SnapshotVersion != plan.ProductSnapshotVersion {
		return nil, &durablelive.Fault{Code: "PLAN_CHANGED"}
	}
	out := append([]c.FactDependency{}, deps...)
	now := time.Now()
	for i, d := range deps {
		if d.ProductId != v.Snapshot.ProductId || d.SourceVersion != v.Snapshot.SourceVersion || v.ValueHashes[d.Kind] == "" || d.ValueHash != v.ValueHashes[d.Kind] {
			return nil, &durablelive.Fault{Code: "PLAN_CHANGED"}
		}
		out[i].ValidatedAt = contentplan.Stamp(now)
		out[i].ExpiresAt = contentplan.Stamp(now.Add(2 * time.Second))
	}
	return out, nil
}

// VerifyPayload is installed once as Store.Facts by the trusted composition
// root. It is called by Store before opening the effect-start transaction.
func VerifyPayload(store *durablelive.Store) durablelive.FactVerifier {
	return func(ctx context.Context, p durablelive.Principal, payload durablelive.ExecutePayload) error {
		if payload.ProductId == nil || payload.PlanId == nil {
			return &durablelive.Fault{Code: "PLAN_CHANGED"}
		}
		// Resolve the authorized run from the immutable plan, never caller JSON.
		var runID string
		err := store.DB.QueryRow(ctx, `SELECT run_id FROM dl05_plans WHERE plan_id=$1 AND product_id=$2 AND tenant_id=$3 AND owner_id=$4`, *payload.PlanId, *payload.ProductId, p.TenantID, p.OwnerID).Scan(&runID)
		if err != nil {
			return err
		}
		v, err := store.ReadProduct(ctx, p, runID)
		if err != nil {
			return err
		}
		var version string
		if err = store.DB.QueryRow(ctx, `SELECT product_snapshot_version FROM dl05_plans WHERE plan_id=$1 AND run_id=$2 AND tenant_id=$3 AND owner_id=$4`, *payload.PlanId, runID, p.TenantID, p.OwnerID).Scan(&version); err != nil {
			return err
		}
		if v.SnapshotVersion != version {
			return &durablelive.Fault{Code: "PLAN_CHANGED"}
		}
		for _, d := range payload.FactDependencies {
			if d.ProductId != v.Snapshot.ProductId || d.SourceVersion != v.Snapshot.SourceVersion || v.ValueHashes[d.Kind] == "" || d.ValueHash != v.ValueHashes[d.Kind] {
				return &durablelive.Fault{Code: "PLAN_CHANGED"}
			}
		}
		return nil
	}
}
