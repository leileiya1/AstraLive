package durablelive

import (
	"context"
	"strings"

	"github.com/jackc/pgx/v5"
)

// ProductView reads the same product table as the existing Product Tools. The
// source version covers all mutable facts, not credentials or Provider config.
type ProductView struct {
	Snapshot        ProductSnapshot
	SnapshotVersion string
	ValueHashes     map[string]string
}

func productView(ctx context.Context, tx pgx.Tx, p Principal, r Object) (out ProductView, err error) {
	var id string
	err = tx.QueryRow(ctx, `SELECT COALESCE(active_product_id,'') FROM live_rooms WHERE id=$1`, r["roomId"]).Scan(&id)
	if err != nil {
		return out, err
	}
	if id == "" {
		return out, fault("PLAN_CHANGED")
	}
	if err = owner(ctx, tx, p, "product", id); err != nil {
		return out, err
	}
	var name, description, price, currency, updated string
	var stock int64
	var sizes []string
	err = tx.QueryRow(ctx, `SELECT name,description,price::text,currency,stock,sizes,dl05_stamp(updated_at) FROM products WHERE id=$1 FOR SHARE`, id).Scan(&name, &description, &price, &currency, &stock, &sizes, &updated)
	if err != nil {
		return out, err
	}
	values := Object{"productId": id, "name": name, "description": description, "price": price, "currency": currency, "stock": stock, "sizes": stringArray(sizes), "updatedAt": updated}
	out.Snapshot = ProductSnapshot{ProductId: id, Name: name, Description: description, Sizes: sizes, SourceVersion: hash(values)}
	out.SnapshotVersion = hash(wire(out.Snapshot))
	out.ValueHashes = map[string]string{
		"PRICE":        hash(Object{"price": price, "currency": currency}),
		"STOCK":        hash(stock),
		"AVAILABILITY": hash(stock > 0),
		"SIZE_OPTIONS": textHash(strings.Join(sizes, "、")),
	}
	return out, nil
}

func stringArray(a []string) []any {
	out := make([]any, len(a))
	for i, v := range a {
		out[i] = v
	}
	return out
}

// ReadProduct is an in-process authorized Tool projection. It never returns a
// transaction to policy code and is also valid before a physical Session exists.
func (s *Store) ReadProduct(ctx context.Context, p Principal, runID string) (out ProductView, err error) {
	if p.Role != "CONTROL" && p.Role != "RUNTIME_JOURNAL" {
		return out, fault("FORBIDDEN")
	}
	tx, err := s.begin(ctx)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(context.Background())
	r, err := loadRun(ctx, tx, runID, true)
	if err != nil {
		return out, normErr(err)
	}
	if err = authorize(p, r); err != nil {
		return out, err
	}
	if err = owner(ctx, tx, p, "room", str(r, "roomId")); err != nil {
		return out, err
	}
	if p.Role == "RUNTIME_JOURNAL" {
		if err = boundProducer(ctx, tx, p, r); err != nil {
			return out, err
		}
	}
	out, err = productView(ctx, tx, p, r)
	if err != nil {
		return out, err
	}
	return out, tx.Commit(ctx)
}
