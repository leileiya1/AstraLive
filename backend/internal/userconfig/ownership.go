package userconfig

import (
	"context"
)

func (s *Service) Own(ctx context.Context, scope Scope, kind, id string) error {
	if !validScope(scope) {
		return ErrInvalid
	}
	_, e := s.DB.Exec(ctx, `INSERT INTO resource_owners(kind,resource_id,tenant_id,user_id) VALUES($1,$2,$3,$4)`, kind, id, scope.TenantID, scope.UserID)
	return e
}
func (s *Service) CheckOwner(ctx context.Context, scope Scope, kind, id string) error {
	var found bool
	e := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM resource_owners WHERE kind=$1 AND resource_id=$2 AND tenant_id=$3 AND user_id=$4)`, kind, id, scope.TenantID, scope.UserID).Scan(&found)
	if e != nil {
		return e
	}
	if !found {
		return ErrNotFound
	}
	return nil
}
func (s *Service) OwnedIDs(ctx context.Context, scope Scope, kind string) (map[string]bool, error) {
	rows, e := s.DB.Query(ctx, `SELECT resource_id FROM resource_owners WHERE kind=$1 AND tenant_id=$2 AND user_id=$3`, kind, scope.TenantID, scope.UserID)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			return nil, e
		}
		out[id] = true
	}
	return out, rows.Err()
}

// Release is idempotent and also removes the immutable encrypted snapshot.
func (s *Service) Release(ctx context.Context, id string) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	_, e = tx.Exec(ctx, `DELETE FROM provider_bindings b USING session_provider_bindings m WHERE m.session_id=$1 AND b.id=m.binding_id AND b.tenant_id=m.tenant_id AND b.user_id=m.user_id`, id)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE session_provider_bindings SET released_at=COALESCE(released_at,now()) WHERE session_id=$1`, id)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
