package durablelive

import (
	"context"
	"time"
)

// FactVerifier re-reads authoritative dependencies using existing Tool/Provider
// services. It must compare source version and valueHash; nil fails closed.
// The repository invokes it BEFORE Begin; a proof is request-local, <=2 seconds.
type FactVerifier func(context.Context, Principal, ExecutePayload) error
type factApprovalKey struct{}
type factApproval struct {
	hash string
	at   time.Time
}

func (s *Store) preflightFacts(ctx context.Context, p Principal, name string, q Object) (context.Context, error) {
	// Idempotent receipts and repeated START do not require refreshed effect facts.
	var exists bool
	if key := str(q, "idempotencyKey"); key != "" {
		e := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_requests WHERE run_id=$1 AND operation=$2 AND idempotency_key=$3 AND tenant_id=$4 AND owner_id=$5)`, q["runId"], name, key, p.TenantID, p.OwnerID).Scan(&exists)
		if e != nil {
			return ctx, e
		}
		if exists {
			return ctx, nil
		}
	}
	var payload Object
	switch name {
	case "ClaimNextTurn":
		var b []byte
		e := s.DB.QueryRow(ctx, `SELECT jsonb_build_object('mode','SCRIPT_TEXT','text',s.content,'textHash',s.text_hash,'productId',p.product_id,'planId',s.plan_id,'segmentId',s.segment_id,'factDependencies',s.fact_dependencies,'expiresAt',dl05_stamp(clock_timestamp()+interval '2 seconds'),'requiredSinks',jsonb_build_array('validation-only')) FROM dl05_turns t JOIN dl05_segments s ON s.segment_id=t.source_segment_id JOIN dl05_plans p ON p.plan_id=s.plan_id WHERE t.turn_id=$1 AND t.run_id=$2 AND t.tenant_id=$3 AND t.owner_id=$4`, q["candidateTurnId"], q["runId"], p.TenantID, p.OwnerID).Scan(&b)
		if e != nil {
			return ctx, nil
		}
		payload, e = Decode(b)
		if e != nil {
			return ctx, e
		}
	case "JournalStart", "JournalAccept":
		commandID := str(q, "commandId")
		if name == "JournalAccept" {
			commandID = str(obj(q, "command"), "commandId")
		}
		if e := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runtime_inbox WHERE command_id=$1 AND tenant_id=$2 AND owner_id=$3 AND ($4='JournalAccept' OR status<>'ACCEPTED'))`, commandID, p.TenantID, p.OwnerID, name).Scan(&exists); e != nil {
			return ctx, e
		}
		if exists {
			return ctx, nil
		}
		{
			var b []byte
			e := s.DB.QueryRow(ctx, `SELECT envelope->'payload' FROM dl05_outbox WHERE command_id=$1 AND run_id=$2 AND tenant_id=$3 AND owner_id=$4`, commandID, q["runId"], p.TenantID, p.OwnerID).Scan(&b)
			if e != nil {
				return ctx, nil
			}
			payload, e = Decode(b)
			if e != nil {
				return ctx, e
			}
		}
	default:
		return ctx, nil
	}
	if len(arr(payload, "factDependencies")) == 0 {
		return ctx, nil
	}
	if s.Facts == nil {
		return ctx, fault("DEPENDENCY_UNAVAILABLE")
	}
	var typed ExecutePayload
	if e := decodeInto(mustEncode(payload), &typed); e != nil {
		return ctx, e
	}
	if e := s.Facts(ctx, p, typed); e != nil {
		return ctx, e
	}
	return context.WithValue(ctx, factApprovalKey{}, factApproval{hash(arr(payload, "factDependencies")), time.Now()}), nil
}
func mustEncode(v any) []byte {
	b, e := Canonical(v)
	if e != nil {
		panic(e)
	}
	return b
}
