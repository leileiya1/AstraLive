-- Additive durable-live-1 only. Legacy rows are never claimed or rewritten.
-- PostgreSQL >=16 (NULLS NOT DISTINCT); migrations are serialized by db.Migrate.

CREATE TABLE dl05_runs (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 run_id text PRIMARY KEY,
 room_id text NOT NULL REFERENCES live_rooms(id),
 status text NOT NULL CHECK(status IN ('CREATED','PREPARING','LIVE','RECOVERING','PAUSED','STOPPING','STOPPED','FAILED')),
 desired_state text NOT NULL CHECK(desired_state IN ('LIVE','PAUSED','STOPPED')),
 recovery_policy text NOT NULL CHECK(recovery_policy IN ('MANUAL_ON_UNKNOWN','SAFE_SCRIPT_NEXT_BOUNDARY')),
 run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991) DEFAULT 0,
 current_session_id text, current_plan_id text,
 started_at timestamptz, ended_at timestamptz,
 stopped_at timestamptz, stop_revision bigint NOT NULL DEFAULT 0 CHECK(stop_revision>=0),
 state_revision bigint NOT NULL DEFAULT 1 CHECK(state_revision>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(tenant_id,owner_id,run_id)
);

CREATE UNIQUE INDEX dl05_one_run_room ON dl05_runs(room_id) WHERE status NOT IN ('STOPPED','FAILED');

CREATE TABLE dl05_run_terms (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 run_id text NOT NULL, run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 1 AND 9007199254740991),
 lease_owner text NOT NULL, phase text NOT NULL CHECK(phase IN ('PENDING_INSTALL','ACTIVE','SEALED')),
 previous_epoch bigint NOT NULL CHECK(previous_epoch>=0 AND previous_epoch<run_epoch),
 allocated_at timestamptz NOT NULL DEFAULT clock_timestamp(), activated_at timestamptz, sealed_at timestamptz,
 required_sinks jsonb NOT NULL CHECK(jsonb_typeof(required_sinks)='array' AND jsonb_array_length(required_sinks)>0),
 output_fence_proof text, producer_incarnation text, guardian_id text, fence_receipt_id text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,PRIMARY KEY(run_id,run_epoch), UNIQUE(tenant_id,owner_id,run_id,run_epoch), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_run_sessions (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 run_session_id text PRIMARY KEY,
 run_id text NOT NULL, session_id text NOT NULL UNIQUE REFERENCES live_sessions(id),
 binding_id text NOT NULL REFERENCES session_provider_bindings(binding_id),
 introduced_epoch bigint NOT NULL, retired_at timestamptz, output_fenced_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(tenant_id,owner_id,run_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id), FOREIGN KEY(tenant_id,owner_id,run_id,introduced_epoch) REFERENCES dl05_run_terms(tenant_id,owner_id,run_id,run_epoch)
);

CREATE TABLE dl05_plans (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 plan_id text PRIMARY KEY,
 run_id text NOT NULL, product_id text NOT NULL REFERENCES products(id),
 product_snapshot_version text NOT NULL CHECK(product_snapshot_version ~ '^[0-9a-f]{64}$'), snapshot jsonb NOT NULL,
 revision bigint NOT NULL CHECK(revision>0), generation_source jsonb NOT NULL,
 segment_order jsonb NOT NULL CHECK(jsonb_typeof(segment_order)='array' AND jsonb_array_length(segment_order) BETWEEN 1 AND 1000),
 document jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(run_id,revision), UNIQUE(tenant_id,owner_id,run_id,plan_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_segments (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 segment_id text PRIMARY KEY,
 run_id text NOT NULL, plan_id text NOT NULL, sequence bigint NOT NULL CHECK(sequence>0),
 content text NOT NULL CHECK(length(content) BETWEEN 1 AND 2000), text_hash text NOT NULL CHECK(text_hash ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('READY','ACTIVE','COMPLETED','INTERRUPTED','UNKNOWN','INVALIDATED')),
 utterance_id text REFERENCES utterances(id), idempotency_key text NOT NULL,
 checkpoint_state text NOT NULL CHECK(checkpoint_state IN ('PLANNED','DISPATCHED','RUNTIME_ACCEPTED','PLAYING','LOCAL_MEDIA_DRAINED','COMPLETED','INTERRUPTED','UNKNOWN')),
 fact_dependencies jsonb NOT NULL, estimated_duration_ms bigint NOT NULL CHECK(estimated_duration_ms BETWEEN 1 AND 6000), document jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(plan_id,sequence), UNIQUE(run_id,idempotency_key), UNIQUE(tenant_id,owner_id,run_id,plan_id,segment_id),
 UNIQUE(tenant_id,owner_id,run_id,segment_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,plan_id) REFERENCES dl05_plans(tenant_id,owner_id,run_id,plan_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_turns (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 turn_id text PRIMARY KEY,
 run_id text NOT NULL, plan_id text,
 turn_type text NOT NULL CHECK(turn_type IN ('SCRIPT','COMMENT','OPERATOR','SYSTEM')), source_segment_id text, source_comment_trace_id text,
 priority integer NOT NULL CHECK(priority BETWEEN 0 AND 100),
 state text NOT NULL CHECK(state IN ('READY','WAITING','DISPATCHING','PLAYING','COMPLETED','INTERRUPTED','UNKNOWN')),
 scheduled_at timestamptz NOT NULL, started_at timestamptz, finished_at timestamptz, expires_at timestamptz,
 input_text text NOT NULL CHECK(length(input_text) BETWEEN 1 AND 2000), idempotency_key text NOT NULL,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), document jsonb NOT NULL,
 CHECK((turn_type='SCRIPT' AND source_segment_id IS NOT NULL AND plan_id IS NOT NULL AND source_comment_trace_id IS NULL)
 OR (turn_type='COMMENT' AND source_segment_id IS NULL AND source_comment_trace_id IS NOT NULL AND expires_at IS NOT NULL)
 OR (turn_type IN ('OPERATOR','SYSTEM') AND source_segment_id IS NULL AND source_comment_trace_id IS NULL)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(run_id,idempotency_key), UNIQUE(tenant_id,owner_id,run_id,turn_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,plan_id) REFERENCES dl05_plans(tenant_id,owner_id,run_id,plan_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,plan_id,source_segment_id) REFERENCES dl05_segments(tenant_id,owner_id,run_id,plan_id,segment_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_comment_sources (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 source_receipt_id text PRIMARY KEY,
 run_id text NOT NULL, platform text NOT NULL, platform_room_id text NOT NULL, source_event_id text NOT NULL,
 trace_id text NOT NULL, turn_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(tenant_id,owner_id,run_id,platform,platform_room_id,source_event_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,turn_id) REFERENCES dl05_turns(tenant_id,owner_id,run_id,turn_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_attempts (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 attempt_id text PRIMARY KEY,
 run_id text NOT NULL, turn_id text NOT NULL, segment_id text, session_id text NOT NULL,
 run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991), utterance_id text NOT NULL UNIQUE REFERENCES utterances(id), command_id text NOT NULL UNIQUE,
 attempt_number bigint NOT NULL CHECK(attempt_number>0), executor_incarnation text,
 last_checkpoint text NOT NULL CHECK(last_checkpoint IN ('PLANNED','DISPATCHED','RUNTIME_ACCEPTED','PLAYING','LOCAL_MEDIA_DRAINED','COMPLETED','INTERRUPTED','UNKNOWN')),
 answer_text_hash text CHECK(answer_text_hash ~ '^[0-9a-f]{64}$'),
 required_sinks jsonb NOT NULL CHECK(jsonb_array_length(required_sinks)>0), range_proof jsonb, document jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(turn_id,attempt_number), UNIQUE(tenant_id,owner_id,run_id,attempt_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,turn_id) REFERENCES dl05_turns(tenant_id,owner_id,run_id,turn_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,segment_id) REFERENCES dl05_segments(tenant_id,owner_id,run_id,segment_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,run_epoch) REFERENCES dl05_run_terms(tenant_id,owner_id,run_id,run_epoch), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_run_slots (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 run_id text PRIMARY KEY,
 active_attempt_id text, boundary_checkpoint_id text, slot_version bigint NOT NULL DEFAULT 1 CHECK(slot_version>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,FOREIGN KEY(tenant_id,owner_id,run_id,active_attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_outbox (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 intent_id text PRIMARY KEY,
 run_id text NOT NULL, session_id text, utterance_id text REFERENCES utterances(id), command_id text NOT NULL UNIQUE,
 attempt_id text, turn_id text, idempotency_key text NOT NULL, run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991),
 operation text NOT NULL CHECK(operation IN ('EXECUTE_TURN','STOP_RUN','INSTALL_FENCE')), request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 envelope jsonb NOT NULL, status text NOT NULL CHECK(status IN ('PENDING','CLAIMED','ACCEPTED','RECONCILING','COMPLETED','FAILED','UNKNOWN')),
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(), claimed_by text, lease_expires_at timestamptz,
 claim_version bigint NOT NULL DEFAULT 0 CHECK(claim_version>=0), send_started_at timestamptz,
 attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0), last_error_code text,
 CHECK((operation='EXECUTE_TURN' AND session_id IS NOT NULL AND attempt_id IS NOT NULL AND turn_id IS NOT NULL AND utterance_id IS NOT NULL AND run_epoch>0)
 OR (operation IN ('STOP_RUN','INSTALL_FENCE') AND attempt_id IS NULL AND turn_id IS NULL AND utterance_id IS NULL AND (run_epoch>0 OR (operation='STOP_RUN' AND session_id IS NULL)))),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE NULLS NOT DISTINCT(run_id,turn_id,operation,idempotency_key), UNIQUE(tenant_id,owner_id,run_id,command_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,turn_id) REFERENCES dl05_turns(tenant_id,owner_id,run_id,turn_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

ALTER TABLE dl05_attempts ADD FOREIGN KEY(tenant_id,owner_id,run_id,command_id) REFERENCES dl05_outbox(tenant_id,owner_id,run_id,command_id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE dl05_runtime_inbox (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 command_id text PRIMARY KEY,
 run_id text NOT NULL, attempt_id text, run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991), request_hash text NOT NULL,
 status text NOT NULL CHECK(status IN ('ACCEPTED','STARTED','TERMINAL','NOT_EXECUTED','UNKNOWN')), receipt_id text NOT NULL UNIQUE,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), producer_incarnation text NOT NULL,
 started_at timestamptz, terminal_at timestamptz, result_hash text, executor_sealed_at timestamptz, no_effect_proof text,
 CHECK(status<>'NOT_EXECUTED' OR (executor_sealed_at IS NOT NULL AND no_effect_proof IS NOT NULL)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,FOREIGN KEY(tenant_id,owner_id,run_id,command_id) REFERENCES dl05_outbox(tenant_id,owner_id,run_id,command_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_checkpoints (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 checkpoint_id text PRIMARY KEY,
 run_id text NOT NULL, session_id text NOT NULL, attempt_id text NOT NULL, command_id text NOT NULL,
 run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991), event_id text NOT NULL UNIQUE, producer_incarnation text NOT NULL, producer_seq bigint NOT NULL CHECK(producer_seq>0),
 state text NOT NULL CHECK(state IN ('PLANNED','DISPATCHED','RUNTIME_ACCEPTED','PLAYING','LOCAL_MEDIA_DRAINED','COMPLETED','INTERRUPTED','UNKNOWN')),
 last_known_state text, evidence_type text NOT NULL, evidence_ref text NOT NULL, evidence_hash text NOT NULL,
 occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(), envelope jsonb NOT NULL,
 content_hash text NOT NULL, projection_status text NOT NULL CHECK(projection_status IN ('PENDING','APPLIED','QUARANTINED','HISTORICAL')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(attempt_id,producer_incarnation,producer_seq), UNIQUE(tenant_id,owner_id,run_id,checkpoint_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,command_id) REFERENCES dl05_outbox(tenant_id,owner_id,run_id,command_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

ALTER TABLE dl05_run_slots ADD FOREIGN KEY(tenant_id,owner_id,run_id,boundary_checkpoint_id) REFERENCES dl05_checkpoints(tenant_id,owner_id,run_id,checkpoint_id);

CREATE TABLE dl05_run_leases (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 run_id text PRIMARY KEY,
 lease_owner text NOT NULL, lease_expires_at timestamptz NOT NULL, fencing_token bigint NOT NULL,
 run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991), lease_version bigint NOT NULL CHECK(lease_version>0), phase text NOT NULL CHECK(phase IN ('PENDING_INSTALL','ACTIVE','SEALED')), CHECK(fencing_token=run_epoch),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,FOREIGN KEY(tenant_id,owner_id,run_id,run_epoch) REFERENCES dl05_run_terms(tenant_id,owner_id,run_id,run_epoch), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_room_outputs (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 room_id text PRIMARY KEY REFERENCES live_rooms(id),
 active_run_id text, output_binding_version bigint NOT NULL DEFAULT 1 CHECK(output_binding_version>0),
 guardian_id text NOT NULL, expires_at timestamptz NOT NULL, fence_proof_ref text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(room_id,output_binding_version),
 FOREIGN KEY(tenant_id,owner_id,active_run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_output_permits (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 permit_id text PRIMARY KEY,
 run_id text NOT NULL, session_id text NOT NULL, run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 0 AND 9007199254740991), lease_version bigint NOT NULL CHECK(lease_version>0),
 producer_incarnation text NOT NULL, guardian_id text NOT NULL, issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, fence_proof_ref text NOT NULL, room_id text NOT NULL, output_binding_version bigint NOT NULL,
 CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '1 second'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,FOREIGN KEY(tenant_id,owner_id,run_id,run_epoch) REFERENCES dl05_run_terms(tenant_id,owner_id,run_id,run_epoch),
 FOREIGN KEY(tenant_id,owner_id,run_id,session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id),
  FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_output_bindings (
 room_id text NOT NULL REFERENCES live_rooms(id), output_binding_version bigint NOT NULL CHECK(output_binding_version>0),
 tenant_id text NOT NULL, owner_id text NOT NULL, run_id text NOT NULL, guardian_id text NOT NULL, fence_proof_ref text NOT NULL,
 PRIMARY KEY(room_id,output_binding_version),
 FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id));
ALTER TABLE dl05_output_permits ADD FOREIGN KEY(room_id,output_binding_version) REFERENCES dl05_output_bindings(room_id,output_binding_version);

CREATE TABLE dl05_plan_progress (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 plan_id text PRIMARY KEY,
 run_id text NOT NULL, completed_prefix bigint NOT NULL DEFAULT 0 CHECK(completed_prefix>=0),
 resume_sequence bigint NOT NULL DEFAULT 1 CHECK(resume_sequence>completed_prefix), revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,FOREIGN KEY(tenant_id,owner_id,run_id,plan_id) REFERENCES dl05_plans(tenant_id,owner_id,run_id,plan_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

CREATE TABLE dl05_decisions (
 tenant_id text NOT NULL, owner_id text NOT NULL,
 decision_id text PRIMARY KEY,
 run_id text NOT NULL, plan_id text, attempt_id text, operator_id text NOT NULL,
 action text NOT NULL, reason text NOT NULL, expected_revision bigint NOT NULL, document jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id)
 ,UNIQUE(run_id,decision_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id), FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id)
);

ALTER TABLE dl05_runs ADD FOREIGN KEY(tenant_id,owner_id,run_id,current_session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE dl05_runs ADD FOREIGN KEY(tenant_id,owner_id,run_id,current_plan_id) REFERENCES dl05_plans(tenant_id,owner_id,run_id,plan_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE dl05_requests (
 tenant_id text NOT NULL, owner_id text NOT NULL, run_id text NOT NULL, operation text NOT NULL, idempotency_key text NOT NULL,
 request_hash text NOT NULL, response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(run_id,operation,idempotency_key),
 FOREIGN KEY(tenant_id,owner_id,run_id) REFERENCES dl05_runs(tenant_id,owner_id,run_id));
CREATE TABLE dl05_recovery_audit (
 audit_id bigserial PRIMARY KEY, run_id text, session_id text, utterance_id text, reason_code text NOT NULL,
 evidence_ref text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE NULLS NOT DISTINCT(run_id,session_id,utterance_id,reason_code,evidence_ref));
CREATE TABLE dl05_notifications (
 notification_id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES dl05_runs(run_id), checkpoint_id text NOT NULL UNIQUE REFERENCES dl05_checkpoints(checkpoint_id),
 published_at timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE dl05_yields (
 run_id text NOT NULL REFERENCES dl05_runs(run_id), boundary_checkpoint_id text NOT NULL REFERENCES dl05_checkpoints(checkpoint_id),
 idempotency_key text NOT NULL, slot_version bigint NOT NULL,
 PRIMARY KEY(run_id,boundary_checkpoint_id), UNIQUE(run_id,idempotency_key));
CREATE INDEX dl05_pending ON dl05_outbox(next_attempt_at,run_id,intent_id) WHERE status='PENDING';
CREATE INDEX dl05_claim_expiry ON dl05_outbox(lease_expires_at) WHERE status='CLAIMED';
CREATE INDEX dl05_outbox_reconcile ON dl05_outbox(run_id,run_epoch,status);
CREATE INDEX dl05_turn_ready ON dl05_turns(run_id,state,priority DESC,scheduled_at,turn_id);
CREATE INDEX dl05_comment_expiry ON dl05_turns(expires_at) WHERE turn_type='COMMENT' AND state IN ('READY','WAITING');
CREATE INDEX dl05_checkpoint_attempt ON dl05_checkpoints(attempt_id,producer_seq);
CREATE INDEX dl05_checkpoint_run ON dl05_checkpoints(run_id,received_at);
CREATE INDEX dl05_run_active ON dl05_runs(status,updated_at);
CREATE INDEX dl05_lease_expiry ON dl05_run_leases(lease_expires_at);
CREATE INDEX dl05_decision_run ON dl05_decisions(run_id,created_at);
CREATE INDEX dl05_notifications_pending ON dl05_notifications(notification_id) WHERE published_at IS NULL;

-- Immutable identity/content fields are enforced even outside the Go repository.
CREATE FUNCTION dl05_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text;
BEGIN
 FOREACH key IN ARRAY TG_ARGV LOOP
  IF to_jsonb(OLD)->key IS DISTINCT FROM to_jsonb(NEW)->key THEN
   RAISE EXCEPTION 'immutable durable field %', key USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;

CREATE TRIGGER dl05_runs_immutable BEFORE UPDATE ON dl05_runs FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','room_id','recovery_policy');

CREATE TRIGGER dl05_plans_immutable BEFORE UPDATE ON dl05_plans FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','plan_id','product_id','product_snapshot_version','snapshot','revision','generation_source','segment_order','document');

CREATE TRIGGER dl05_segments_immutable BEFORE UPDATE ON dl05_segments FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','plan_id','segment_id','sequence','content','text_hash','idempotency_key','fact_dependencies','estimated_duration_ms','document');

CREATE TRIGGER dl05_outbox_immutable BEFORE UPDATE ON dl05_outbox FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','intent_id','command_id','session_id','utterance_id','attempt_id','turn_id','operation','idempotency_key','run_epoch','request_hash','envelope');

CREATE TRIGGER dl05_attempts_immutable BEFORE UPDATE ON dl05_attempts FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','attempt_id','turn_id','segment_id','session_id','utterance_id','command_id','run_epoch','attempt_number','required_sinks','document');

CREATE TRIGGER dl05_checkpoints_immutable BEFORE UPDATE ON dl05_checkpoints FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','checkpoint_id','event_id','attempt_id','command_id','run_epoch','session_id','producer_incarnation','producer_seq','state','last_known_state','evidence_type','evidence_ref','evidence_hash','occurred_at','received_at','envelope','content_hash');

CREATE TRIGGER dl05_decisions_immutable BEFORE UPDATE ON dl05_decisions FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','decision_id','plan_id','attempt_id','operator_id','action','reason','expected_revision','document');

CREATE TRIGGER dl05_comment_sources_immutable BEFORE UPDATE ON dl05_comment_sources FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','platform','platform_room_id','source_event_id','trace_id','turn_id','source_receipt_id');

CREATE TRIGGER dl05_run_sessions_immutable BEFORE UPDATE ON dl05_run_sessions FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','run_id','run_session_id','session_id','binding_id','introduced_epoch');

CREATE TRIGGER dl05_output_bindings_immutable BEFORE UPDATE ON dl05_output_bindings FOR EACH ROW EXECUTE FUNCTION dl05_immutable('tenant_id','owner_id','room_id','output_binding_version','run_id','guardian_id','fence_proof_ref');

CREATE FUNCTION dl05_check_plan() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pid text; actual jsonb; expected jsonb; n bigint; lo bigint; hi bigint;
BEGIN
 pid := COALESCE(NEW.plan_id, OLD.plan_id);
 SELECT segment_order INTO expected FROM dl05_plans WHERE plan_id=pid;
 IF expected IS NULL THEN RETURN NULL; END IF;
 SELECT jsonb_agg(segment_id ORDER BY sequence),count(*),min(sequence),max(sequence) INTO actual,n,lo,hi FROM dl05_segments WHERE plan_id=pid;
 IF expected IS DISTINCT FROM actual OR lo<>1 OR hi<>n THEN RAISE EXCEPTION 'invalid segment order' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER dl05_plan_order AFTER INSERT OR UPDATE ON dl05_plans DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dl05_check_plan();
CREATE CONSTRAINT TRIGGER dl05_segment_order AFTER INSERT OR UPDATE OR DELETE ON dl05_segments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dl05_check_plan();
CREATE FUNCTION dl05_check_session() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM dl05_runs r JOIN live_sessions s ON s.id=NEW.session_id AND s.room_id=r.room_id
 JOIN session_provider_bindings b ON b.session_id=s.id AND b.binding_id=NEW.binding_id AND b.tenant_id=NEW.tenant_id AND b.user_id=NEW.owner_id
 JOIN resource_owners o ON o.kind='session' AND o.resource_id=s.id AND o.tenant_id=NEW.tenant_id AND o.user_id=NEW.owner_id
 WHERE r.run_id=NEW.run_id AND r.tenant_id=NEW.tenant_id AND r.owner_id=NEW.owner_id) THEN
 RAISE EXCEPTION 'session scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_session_scope BEFORE INSERT ON dl05_run_sessions FOR EACH ROW EXECUTE FUNCTION dl05_check_session();
CREATE FUNCTION dl05_check_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM utterances u JOIN dl05_turns t ON t.turn_id=NEW.turn_id AND t.run_id=NEW.run_id
 WHERE u.id=NEW.utterance_id AND u.session_id=NEW.session_id AND t.source_segment_id IS NOT DISTINCT FROM NEW.segment_id) THEN
 RAISE EXCEPTION 'attempt scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_attempt_scope BEFORE INSERT ON dl05_attempts FOR EACH ROW EXECUTE FUNCTION dl05_check_attempt();
CREATE FUNCTION dl05_check_segment_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.utterance_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM dl05_attempts WHERE utterance_id=NEW.utterance_id AND segment_id=NEW.segment_id AND run_id=NEW.run_id) THEN
 RAISE EXCEPTION 'segment attempt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER dl05_segment_attempt AFTER INSERT OR UPDATE ON dl05_segments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dl05_check_segment_attempt();

CREATE FUNCTION dl05_stamp(timestamptz) RETURNS text LANGUAGE sql STABLE AS $$
SELECT to_char($1 AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') $$;

CREATE FUNCTION dl05_check_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.envelope->>'tenantId' IS DISTINCT FROM NEW.tenant_id
 OR NEW.envelope->>'ownerId' IS DISTINCT FROM NEW.owner_id
 OR NEW.envelope->>'runId' IS DISTINCT FROM NEW.run_id
 OR NEW.envelope->>'commandId' IS DISTINCT FROM NEW.command_id
 OR NEW.envelope->>'intentId' IS DISTINCT FROM NEW.intent_id
 OR NEW.envelope->>'sessionId' IS DISTINCT FROM NEW.session_id
 OR NEW.envelope->>'operation' IS DISTINCT FROM NEW.operation
 OR NEW.envelope->>'requestHash' IS DISTINCT FROM NEW.request_hash
 OR (NEW.envelope->>'runEpoch')::bigint IS DISTINCT FROM NEW.run_epoch THEN
 RAISE EXCEPTION 'outbox envelope identity mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.operation='EXECUTE_TURN' AND NOT EXISTS(
 SELECT 1 FROM dl05_attempts a WHERE a.attempt_id=NEW.attempt_id AND a.run_id=NEW.run_id AND a.session_id=NEW.session_id
 AND a.utterance_id=NEW.utterance_id AND a.turn_id=NEW.turn_id AND a.command_id=NEW.command_id AND a.run_epoch=NEW.run_epoch
 AND NEW.envelope->>'attemptId'=a.attempt_id AND NEW.envelope->>'turnId'=a.turn_id AND NEW.envelope->>'utteranceId'=a.utterance_id) THEN
 RAISE EXCEPTION 'outbox attempt mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_outbox_scope BEFORE INSERT ON dl05_outbox FOR EACH ROW EXECUTE FUNCTION dl05_check_outbox();
CREATE FUNCTION dl05_check_resource_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rid text;
BEGIN
 rid:=to_jsonb(NEW)->>TG_ARGV[1];
 IF NOT EXISTS(SELECT 1 FROM resource_owners WHERE kind=TG_ARGV[0] AND resource_id=rid AND tenant_id=NEW.tenant_id AND user_id=NEW.owner_id) THEN
 RAISE EXCEPTION 'resource owner mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_run_room_scope BEFORE INSERT ON dl05_runs FOR EACH ROW EXECUTE FUNCTION dl05_check_resource_scope('room','room_id');
CREATE TRIGGER dl05_plan_product_scope BEFORE INSERT ON dl05_plans FOR EACH ROW EXECUTE FUNCTION dl05_check_resource_scope('product','product_id');
CREATE TABLE dl05_answer_artifacts (
 command_id text PRIMARY KEY REFERENCES dl05_runtime_inbox(command_id),
 answer_text text NOT NULL CHECK(length(answer_text) BETWEEN 1 AND 2000),
 text_hash text NOT NULL CHECK(text_hash ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TRIGGER dl05_answer_immutable BEFORE UPDATE ON dl05_answer_artifacts FOR EACH ROW EXECUTE FUNCTION dl05_immutable('command_id','answer_text','text_hash','created_at');
-- Prevent the legacy and durable schedulers from controlling one Session. A
-- Session row FOR UPDATE during Attach serializes with Utterance FK admission.
CREATE FUNCTION dl05_utterance_mode() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM dl05_run_sessions WHERE session_id=NEW.session_id)
 AND NOT EXISTS(SELECT 1 FROM dl05_attempts WHERE utterance_id=NEW.id AND session_id=NEW.session_id) THEN
 RAISE EXCEPTION 'durable Session requires atomic attempt/outbox' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER dl05_utterance_mode AFTER INSERT ON utterances DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dl05_utterance_mode();
ALTER TABLE dl05_segments ADD CHECK(text_hash=encode(sha256(convert_to(content,'UTF8')),'hex'));
ALTER TABLE dl05_runs ADD CHECK(state_revision<=9007199254740991 AND stop_revision<=9007199254740991);
ALTER TABLE dl05_run_leases ADD CHECK(lease_version<=9007199254740991);
ALTER TABLE dl05_run_slots ADD CHECK(slot_version<=9007199254740991);
ALTER TABLE dl05_outbox ADD CHECK(claim_version<=9007199254740991);
ALTER TABLE dl05_runtime_inbox ADD CHECK(revision<=9007199254740991);
ALTER TABLE dl05_plans ADD CHECK(revision<=9007199254740991);
ALTER TABLE dl05_segments ADD CHECK(sequence<=9007199254740991);
ALTER TABLE dl05_turns ADD CHECK(revision<=9007199254740991);
ALTER TABLE dl05_attempts ADD CHECK(attempt_number<=9007199254740991);
ALTER TABLE dl05_checkpoints ADD CHECK(producer_seq<=9007199254740991);
ALTER TABLE dl05_plan_progress ADD CHECK(revision<=9007199254740991 AND resume_sequence<=9007199254740991);
ALTER TABLE dl05_room_outputs ADD CHECK(output_binding_version<=9007199254740991);
