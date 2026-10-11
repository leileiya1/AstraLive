-- Read-side queries for operators/coordinators. Mutations in internal/durability use pgx.Tx
-- explicitly so the business transaction owns the Session lock and fencing CAS.
-- name: GetDurableCommand :one
SELECT o.command_id,o.session_id,o.run_epoch,o.command_type,o.delivery_state,o.attempt_count,o.last_error_code,
 i.execution_state,i.operation_id,i.last_receipt_seq
FROM v05_outbox o LEFT JOIN v05_inbox i USING(session_id,run_epoch,command_id)
WHERE o.command_id=$1 AND o.session_id=$2 AND o.tenant_id=$3 AND o.user_id=$4;
-- name: ListRecoveryRequiredRuns :many
SELECT session_id,run_epoch,status,started_at,sealed_at FROM v05_session_runs
WHERE tenant_id=$1 AND user_id=$2 AND status='RECOVERY_REQUIRED' ORDER BY started_at LIMIT $3;
-- name: ListDeadDurableEvents :many
SELECT event_id,session_id,run_epoch,event_type,failure_count,last_error_code FROM v05_events
WHERE tenant_id=$1 AND user_id=$2 AND processing_state='DEAD' ORDER BY created_at LIMIT $3;
-- name: GetInteractionCommandState :one
SELECT ir.session_id,ir.trace_id,ir.status,ir.utterance_id,o.command_id,o.delivery_state,i.execution_state
FROM interaction_receipts ir JOIN v05_interaction_commands ic USING(session_id,trace_id)
JOIN v05_outbox o ON o.command_id=ic.command_id LEFT JOIN v05_inbox i ON i.session_id=o.session_id AND i.run_epoch=o.run_epoch AND i.command_id=o.command_id
WHERE ir.session_id=$1 AND ir.trace_id=$2 AND o.tenant_id=$3 AND o.user_id=$4;
