-- Additive v0.5 journal. IDs deliberately remain TEXT. No legacy state constraint changes.
CREATE TABLE v05_session_runs (
 session_id text NOT NULL REFERENCES live_sessions(id), run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 1 AND 9007199254740991),
 tenant_id text NOT NULL, user_id text NOT NULL, owner_id text NOT NULL, lease_token bigint NOT NULL,
 status text NOT NULL CHECK(status IN ('ACTIVE','STOPPING','SEALED','RECOVERY_REQUIRED')),
 provider_binding_id text NOT NULL REFERENCES session_provider_bindings(binding_id),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), sealed_at timestamptz,
 current_timeline_epoch bigint NOT NULL DEFAULT 1, current_command_seq bigint NOT NULL DEFAULT 0,
 current_event_seq bigint NOT NULL DEFAULT 0, control_barrier_seq bigint NOT NULL DEFAULT 0, generation_high_watermark bigint NOT NULL DEFAULT 0,
 required_sinks jsonb NOT NULL DEFAULT '[]', optional_sinks jsonb NOT NULL DEFAULT '[]',
 output_sample_rate integer NOT NULL DEFAULT 48000, current_committed_sample bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(session_id,run_epoch), FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals,
 UNIQUE(session_id,run_epoch,tenant_id,user_id)
);
CREATE TABLE v05_recovery_leases (
 session_id text PRIMARY KEY REFERENCES live_sessions(id), tenant_id text NOT NULL,user_id text NOT NULL,
 owner_id text NOT NULL,lease_token bigint NOT NULL CHECK(lease_token>0),run_epoch bigint NOT NULL,
 expires_at timestamptz NOT NULL,renewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE v05_outbox (
 command_id text PRIMARY KEY, tenant_id text NOT NULL,user_id text NOT NULL,session_id text NOT NULL,
 run_epoch bigint NOT NULL,command_seq bigint NOT NULL CHECK(command_seq BETWEEN 1 AND 9007199254740991),
 command_type text NOT NULL,idempotency_key text NOT NULL,request_fingerprint text NOT NULL,trace_id text NOT NULL,
 utterance_id text REFERENCES utterances(id),payload_envelope jsonb NOT NULL,
 delivery_state text NOT NULL DEFAULT 'PENDING' CHECK(delivery_state IN ('PENDING','CLAIMED','ACKED','UNKNOWN','CANCELLED','FAILED')),
 attempt_count integer NOT NULL DEFAULT 0,next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 valid_until timestamptz NOT NULL,last_error_code text,lease_owner text,lease_token bigint NOT NULL DEFAULT 0,lease_expires_at timestamptz,acked_at timestamptz,unknown_since timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id),
 UNIQUE(session_id,run_epoch,command_seq), UNIQUE(tenant_id,user_id,session_id,run_epoch,command_type,idempotency_key)
);
CREATE INDEX v05_outbox_pending ON v05_outbox(next_attempt_at) WHERE delivery_state IN ('PENDING','CLAIMED');
CREATE TABLE v05_inbox (
 session_id text NOT NULL,run_epoch bigint NOT NULL,command_id text NOT NULL REFERENCES v05_outbox(command_id),
 tenant_id text NOT NULL,user_id text NOT NULL,request_fingerprint text NOT NULL,command_type text NOT NULL,command_seq bigint NOT NULL,
 accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),operation_id text NOT NULL,
 execution_state text NOT NULL DEFAULT 'ACCEPTED' CHECK(execution_state IN ('ACCEPTED','STARTED','TERMINAL','UNKNOWN','CANCELLED')),
 execution_attempt_id text,executor_incarnation text,execution_lease_token bigint,execution_started_at timestamptz,
 generation_id bigint CHECK(generation_id BETWEEN 1 AND 9007199254740991),timeline_epoch bigint CHECK(timeline_epoch BETWEEN 1 AND 9007199254740991),
 terminal_at timestamptz,last_receipt_seq bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(session_id,run_epoch,command_id), UNIQUE(command_id), FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id)
);
CREATE TABLE v05_receipts (
 session_id text NOT NULL,run_epoch bigint NOT NULL,command_id text NOT NULL,receipt_seq bigint NOT NULL,
 tenant_id text NOT NULL,user_id text NOT NULL,attempt_id text,state text NOT NULL,
 outcome text,observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),producer_incarnation text NOT NULL,
 evidence_type text NOT NULL,evidence_ref text NOT NULL,range_sinks jsonb NOT NULL DEFAULT '{}',reason_code text,observation_hash text NOT NULL,
 PRIMARY KEY(session_id,run_epoch,command_id,receipt_seq),
 FOREIGN KEY(session_id,run_epoch,command_id) REFERENCES v05_inbox(session_id,run_epoch,command_id),
 FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals
);
CREATE TABLE v05_events (
 event_id text PRIMARY KEY,tenant_id text NOT NULL,user_id text NOT NULL,session_id text NOT NULL,run_epoch bigint NOT NULL,
 event_seq bigint NOT NULL,producer_incarnation text NOT NULL,producer_seq bigint NOT NULL CHECK(producer_seq BETWEEN 1 AND 9007199254740991),
 event_type text NOT NULL,command_id text REFERENCES v05_outbox(command_id),trace_id text NOT NULL,occurred_at timestamptz NOT NULL,
 envelope_hash text NOT NULL,envelope jsonb NOT NULL,
 processing_state text NOT NULL DEFAULT 'PENDING' CHECK(processing_state IN ('PENDING','APPLIED','STALE','DEAD')),
 failure_count integer NOT NULL DEFAULT 0,last_error_code text,next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id),
 UNIQUE(session_id,run_epoch,event_seq),UNIQUE(session_id,run_epoch,producer_incarnation,producer_seq)
);
CREATE TABLE v05_interaction_commands (
 session_id text NOT NULL,trace_id text NOT NULL,command_id text NOT NULL REFERENCES v05_outbox(command_id),
 PRIMARY KEY(session_id,trace_id),FOREIGN KEY(session_id,trace_id) REFERENCES interaction_receipts(session_id,trace_id)
);
CREATE TABLE v05_recovery_audit (
 id bigserial PRIMARY KEY,session_id text NOT NULL REFERENCES live_sessions(id),run_epoch bigint NOT NULL,
 action text NOT NULL,reason_code text NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX v05_events_pending ON v05_events(next_attempt_at,event_seq) WHERE processing_state='PENDING';
CREATE INDEX v05_outbox_reconcile ON v05_outbox(next_attempt_at) WHERE delivery_state IN ('UNKNOWN','ACKED');
CREATE INDEX v05_recovery_expired ON v05_recovery_leases(expires_at);
