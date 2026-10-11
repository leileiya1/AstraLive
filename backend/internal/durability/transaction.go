package durability

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type businessTxKey struct{}

// WithBusinessTx lets the public idempotency response and business Outbox share one commit.
func WithBusinessTx(ctx context.Context, tx pgx.Tx) context.Context {
	return context.WithValue(ctx, businessTxKey{}, tx)
}

type borrowedTx struct{ pgx.Tx }

func (b borrowedTx) Commit(context.Context) error   { return nil }
func (b borrowedTx) Rollback(context.Context) error { return nil }
func BeginBusiness(ctx context.Context, pool *pgxpool.Pool) (pgx.Tx, error) {
	if tx, ok := ctx.Value(businessTxKey{}).(pgx.Tx); ok {
		return borrowedTx{tx}, nil
	}
	return pool.Begin(ctx)
}
