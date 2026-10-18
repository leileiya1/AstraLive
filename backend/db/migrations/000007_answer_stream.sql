-- durable-live-2 / receiver-1, additive; deliberately no destructive down.
-- The Backend is the only writer. Runtime and Guardian receive no SQL grants.
-- Existing run/turn/attempt/outbox/session/lease remain the single business truth.
ALTER TABLE dl05_runs ADD COLUMN contract_revision text NOT NULL DEFAULT 'durable-live-1'
 CHECK(contract_revision IN ('durable-live-1','durable-live-2'));
CREATE FUNCTION dl05_v2_run_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.contract_revision<>NEW.contract_revision AND
 (OLD.contract_revision<>'durable-live-1' OR NEW.contract_revision<>'durable-live-2'
  OR EXISTS(SELECT 1 FROM dl05_attempts WHERE run_id=OLD.run_id)) THEN
  RAISE EXCEPTION 'cannot change an executing run revision' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_revision BEFORE UPDATE ON dl05_runs FOR EACH ROW EXECUTE FUNCTION dl05_v2_run_revision();
CREATE FUNCTION dl05_v2_command_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.envelope->>'contractRevision' IS DISTINCT FROM
 (SELECT contract_revision FROM dl05_runs WHERE run_id=NEW.run_id) THEN
  RAISE EXCEPTION 'command/run revision mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_command_revision BEFORE INSERT ON dl05_outbox FOR EACH ROW EXECUTE FUNCTION dl05_v2_command_revision();

CREATE TABLE dl05_v2_commands (
 command_id text PRIMARY KEY, tenant_id text NOT NULL, owner_id text NOT NULL, run_id text NOT NULL,
 attempt_id text NOT NULL, session_id text NOT NULL, room_id text NOT NULL,
 run_epoch bigint NOT NULL CHECK(run_epoch BETWEEN 1 AND 9007199254740991),
 producer text NOT NULL, request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 contract_revision text NOT NULL CHECK(contract_revision='durable-live-2'),
 command jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,owner_id,run_id,command_id), UNIQUE(command_id,attempt_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,command_id) REFERENCES dl05_outbox(tenant_id,owner_id,run_id,command_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,attempt_id) REFERENCES dl05_attempts(tenant_id,owner_id,run_id,attempt_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,session_id) REFERENCES dl05_run_sessions(tenant_id,owner_id,run_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,run_id,run_epoch) REFERENCES dl05_run_terms(tenant_id,owner_id,run_id,run_epoch),
 FOREIGN KEY(command_id) REFERENCES dl05_runtime_inbox(command_id)
);
CREATE FUNCTION dl05_v2_context_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM dl05_outbox o JOIN dl05_attempts a ON a.command_id=o.command_id
 JOIN dl05_runs r ON r.run_id=o.run_id
 WHERE o.command_id=NEW.command_id AND o.envelope=NEW.command AND o.run_id=NEW.run_id
 AND o.attempt_id=NEW.attempt_id AND o.session_id=NEW.session_id AND o.run_epoch=NEW.run_epoch
 AND r.room_id=NEW.room_id AND r.contract_revision=NEW.contract_revision
 AND NEW.command->>'requestHash'=NEW.request_hash AND NEW.command->>'contractRevision'=NEW.contract_revision) THEN
 RAISE EXCEPTION 'v2 command scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_context_scope BEFORE INSERT ON dl05_v2_commands FOR EACH ROW EXECUTE FUNCTION dl05_v2_context_scope();

CREATE TABLE dl05_v2_processes (
 principal_id text PRIMARY KEY, tenant_id text NOT NULL, owner_id text NOT NULL, room_id text NOT NULL REFERENCES live_rooms(id),
 role text NOT NULL CHECK(role IN ('REGISTERED_RUNTIME','OUTPUT_GUARDIAN','OBSERVER')),
 incarnation text NOT NULL UNIQUE, producer text, key_id text UNIQUE, public_key bytea,
 source_identity text NOT NULL, revoked_at timestamptz,
 UNIQUE(principal_id,incarnation),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES config_principals(tenant_id,user_id),
 CHECK((role='OUTPUT_GUARDIAN' AND length(public_key)=32 AND key_id IS NOT NULL) OR role<>'OUTPUT_GUARDIAN')
);
CREATE TABLE dl05_v2_installations (
 proof_id text PRIMARY KEY, command_id text NOT NULL REFERENCES dl05_v2_commands(command_id),
 binding jsonb NOT NULL, binding_hash text NOT NULL, installation_revision bigint NOT NULL CHECK(installation_revision>0),
 runtime_principal text NOT NULL REFERENCES dl05_v2_processes(principal_id),
 guardian_principal text NOT NULL REFERENCES dl05_v2_processes(principal_id),
 observed_by text NOT NULL, fence_ref text NOT NULL, retired_at timestamptz,
 UNIQUE(command_id,proof_id,binding_hash)
);
CREATE UNIQUE INDEX dl05_v2_current_install ON dl05_v2_installations(command_id) WHERE retired_at IS NULL;
CREATE TABLE dl05_v2_stage_challenges (
 challenge text PRIMARY KEY, command_id text NOT NULL, proof_id text NOT NULL, binding_hash text NOT NULL,
 run_revision bigint NOT NULL, lease_version bigint NOT NULL, issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '1 second'),
 FOREIGN KEY(command_id,proof_id,binding_hash) REFERENCES dl05_v2_installations(command_id,proof_id,binding_hash)
);
CREATE TABLE dl05_receiver_bootstraps (
 bootstrap_id text PRIMARY KEY, command_id text NOT NULL UNIQUE REFERENCES dl05_v2_commands(command_id),
 proof_id text NOT NULL, registration_hash text NOT NULL, binding jsonb NOT NULL, receipt jsonb NOT NULL,
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(command_id,bootstrap_id,registration_hash),
 FOREIGN KEY(command_id,proof_id,registration_hash) REFERENCES dl05_v2_installations(command_id,proof_id,binding_hash)
);
CREATE TABLE dl05_v2_registration_state (
 bootstrap_id text PRIMARY KEY REFERENCES dl05_receiver_bootstraps(bootstrap_id),
 state text NOT NULL CHECK(state IN ('ACTIVE','REVOKED')), revision bigint NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 9007199254740991),
 reason text, revoked_at timestamptz,
 CHECK((state='ACTIVE' AND revoked_at IS NULL) OR (state='REVOKED' AND revoked_at IS NOT NULL))
);
CREATE TABLE dl05_answer_streams (
 answer_id text PRIMARY KEY, command_id text NOT NULL UNIQUE REFERENCES dl05_v2_commands(command_id),
 state text NOT NULL CHECK(state IN ('OPEN','SEALED','COMPLETED','INTERRUPTED','UNKNOWN')),
 answer_revision bigint NOT NULL DEFAULT 1 CHECK(answer_revision BETWEEN 1 AND 9007199254740991),
 prepared_count integer NOT NULL CHECK(prepared_count BETWEEN 1 AND 32),
 drained_prefix integer NOT NULL DEFAULT 0, total_characters integer NOT NULL CHECK(total_characters BETWEEN 1 AND 2000),
 deadline timestamptz NOT NULL, final_hash text, manifest_hash text,
 CHECK(drained_prefix BETWEEN 0 AND prepared_count),
 CHECK(state NOT IN ('SEALED','COMPLETED') OR (final_hash IS NOT NULL AND manifest_hash IS NOT NULL)),
 UNIQUE(command_id,answer_id)
);
CREATE TABLE dl05_answer_segments (
 artifact_id text PRIMARY KEY, command_id text NOT NULL, answer_id text NOT NULL,
 sequence integer NOT NULL CHECK(sequence BETWEEN 1 AND 32),
 descriptor jsonb NOT NULL, artifact_hash text NOT NULL CHECK(artifact_hash ~ '^[0-9a-f]{64}$'),
 answer_text text NOT NULL CHECK(length(answer_text) BETWEEN 1 AND 240), text_hash text NOT NULL,
 previous_hash text, product_id text REFERENCES products(id), snapshot_version text, facts jsonb NOT NULL,
 prepare_receipt jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(text_hash=encode(sha256(convert_to(answer_text,'UTF8')),'hex')),
 CHECK((sequence=1 AND previous_hash IS NULL) OR (sequence>1 AND previous_hash IS NOT NULL)),
 CHECK(descriptor->>'artifactId'=artifact_id AND descriptor->>'commandId'=command_id AND descriptor->>'answerId'=answer_id
 AND descriptor->>'answerText'=answer_text AND descriptor->>'artifactHash'=artifact_hash
 AND descriptor->>'answerTextHash'=text_hash AND (descriptor->>'sequence')::integer=sequence
 AND descriptor->'factDependencies'=facts
 AND (descriptor->>'previousArtifactHash') IS NOT DISTINCT FROM previous_hash
 AND (descriptor->>'productId') IS NOT DISTINCT FROM product_id
 AND (descriptor->>'productSnapshotVersion') IS NOT DISTINCT FROM snapshot_version),
 UNIQUE(answer_id,sequence), UNIQUE(command_id,artifact_id,artifact_hash),
 FOREIGN KEY(command_id,answer_id) REFERENCES dl05_answer_streams(command_id,answer_id)
);
CREATE TABLE dl05_receiver_artifacts (
 artifact_id text PRIMARY KEY, command_id text NOT NULL, artifact_hash text NOT NULL,
 bootstrap_id text NOT NULL, registration_hash text NOT NULL,
 FOREIGN KEY(command_id,artifact_id,artifact_hash) REFERENCES dl05_answer_segments(command_id,artifact_id,artifact_hash),
 FOREIGN KEY(command_id,bootstrap_id,registration_hash) REFERENCES dl05_receiver_bootstraps(command_id,bootstrap_id,registration_hash)
);
CREATE TABLE dl05_answer_segment_execution (
 artifact_id text PRIMARY KEY REFERENCES dl05_answer_segments(artifact_id),
 state text NOT NULL CHECK(state IN ('PREPARED','STARTED','DRAINED','INTERRUPTED','UNKNOWN')),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), drain_evidence jsonb
);
CREATE TABLE dl05_answer_prepare_keys (
 tenant_id text NOT NULL, owner_id text NOT NULL, run_id text NOT NULL, command_id text NOT NULL,
 operation text NOT NULL CHECK(operation='JournalPrepareAnswer'), idempotency_key text NOT NULL,
 artifact_id text NOT NULL, artifact_hash text NOT NULL, receipt jsonb NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,run_id,command_id,operation,idempotency_key),
 FOREIGN KEY(tenant_id,owner_id,run_id,command_id) REFERENCES dl05_v2_commands(tenant_id,owner_id,run_id,command_id),
 FOREIGN KEY(command_id,artifact_id,artifact_hash) REFERENCES dl05_answer_segments(command_id,artifact_id,artifact_hash)
);
CREATE TABLE dl05_answer_fact_observations (
 observation_id text PRIMARY KEY, command_id text NOT NULL, artifact_id text NOT NULL, artifact_hash text NOT NULL,
 observation jsonb NOT NULL, verified_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
 CHECK(valid_until>verified_at AND valid_until<=verified_at+interval '2 seconds'),
 UNIQUE(command_id,artifact_id,observation_id),
 FOREIGN KEY(command_id,artifact_id,artifact_hash) REFERENCES dl05_answer_segments(command_id,artifact_id,artifact_hash)
);
CREATE TABLE dl05_v2_permits (
 permit_id text PRIMARY KEY, command_id text NOT NULL, artifact_id text NOT NULL, observation_id text NOT NULL,
 permit jsonb NOT NULL, issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '1 second'),
 UNIQUE(command_id,artifact_id,permit_id),
 FOREIGN KEY(command_id,artifact_id,observation_id) REFERENCES dl05_answer_fact_observations(command_id,artifact_id,observation_id)
);
CREATE TABLE dl05_answer_grants (
 grant_id text PRIMARY KEY, command_id text NOT NULL, artifact_id text NOT NULL UNIQUE,
 grant_body jsonb NOT NULL, ticket_verifier text NOT NULL CHECK(ticket_verifier ~ '^[0-9a-f]{64}$'),
 permit_id text NOT NULL, expires_at timestamptz NOT NULL,
 UNIQUE(command_id,artifact_id,grant_id),
 FOREIGN KEY(command_id,artifact_id,permit_id) REFERENCES dl05_v2_permits(command_id,artifact_id,permit_id)
);
CREATE TABLE dl05_v2_grant_state (
 grant_id text PRIMARY KEY REFERENCES dl05_answer_grants(grant_id),
 state text NOT NULL CHECK(state IN ('ISSUED','CONSUMED','EXPIRED','REVOKED','UNKNOWN'))
);
CREATE TABLE dl05_receiver_consumptions (
 execution_id text PRIMARY KEY, command_id text NOT NULL, artifact_id text NOT NULL, grant_id text NOT NULL UNIQUE,
 consume_nonce text NOT NULL, runtime_principal text NOT NULL REFERENCES dl05_v2_processes(principal_id),
 guardian_principal text NOT NULL REFERENCES dl05_v2_processes(principal_id),
 channel_binding text NOT NULL, consume_identity text NOT NULL, receipt_id text NOT NULL UNIQUE,
 registration_hash text NOT NULL, bootstrap_id text NOT NULL, registration_revision bigint NOT NULL CHECK(registration_revision>0),
 consumption jsonb NOT NULL, consumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(runtime_principal,consume_nonce),
 FOREIGN KEY(command_id,artifact_id,grant_id) REFERENCES dl05_answer_grants(command_id,artifact_id,grant_id),
 FOREIGN KEY(command_id,bootstrap_id,registration_hash) REFERENCES dl05_receiver_bootstraps(command_id,bootstrap_id,registration_hash)
);
CREATE TABLE dl05_v2_execution_state (
 execution_id text PRIMARY KEY REFERENCES dl05_receiver_consumptions(execution_id),
 command_id text NOT NULL REFERENCES dl05_v2_commands(command_id),
 state text NOT NULL CHECK(state IN ('ACTIVE','DRAINED','FENCED','UNKNOWN'))
);
CREATE UNIQUE INDEX dl05_v2_one_active_execution ON dl05_v2_execution_state(command_id) WHERE state='ACTIVE';
CREATE TABLE dl05_answer_drain_receipts (
 command_id text NOT NULL, idempotency_key text NOT NULL, artifact_id text NOT NULL, artifact_hash text NOT NULL,
 identity_hash text NOT NULL, identity_body jsonb NOT NULL, receipt jsonb NOT NULL,
 PRIMARY KEY(command_id,idempotency_key),
 FOREIGN KEY(command_id,artifact_id,artifact_hash) REFERENCES dl05_answer_segments(command_id,artifact_id,artifact_hash)
);
CREATE TABLE dl05_v2_observer_evidence (
 evidence_ref text PRIMARY KEY, command_id text NOT NULL, artifact_id text NOT NULL, artifact_hash text NOT NULL,
 observer_id text NOT NULL REFERENCES dl05_v2_processes(principal_id), evidence jsonb NOT NULL,
 FOREIGN KEY(command_id,artifact_id,artifact_hash) REFERENCES dl05_answer_segments(command_id,artifact_id,artifact_hash)
);
CREATE TABLE dl05_v2_audit (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, command_id text NOT NULL REFERENCES dl05_v2_commands(command_id),
 reason text NOT NULL, evidence_ref text NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(command_id,reason,evidence_ref)
);
-- No immutable row or dedup tombstone can be deleted to make a task playable.
CREATE FUNCTION dl05_v2_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable v2 evidence' USING ERRCODE='23514'; END $$;
CREATE TRIGGER dl05_v2_commands_immutable BEFORE UPDATE OR DELETE ON dl05_v2_commands FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_stage_challenges_immutable BEFORE UPDATE OR DELETE ON dl05_v2_stage_challenges FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_receiver_bootstraps_immutable BEFORE UPDATE OR DELETE ON dl05_receiver_bootstraps FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_segments_immutable BEFORE UPDATE OR DELETE ON dl05_answer_segments FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_receiver_artifacts_immutable BEFORE UPDATE OR DELETE ON dl05_receiver_artifacts FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_prepare_keys_immutable BEFORE UPDATE OR DELETE ON dl05_answer_prepare_keys FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_fact_observations_immutable BEFORE UPDATE OR DELETE ON dl05_answer_fact_observations FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_permits_immutable BEFORE UPDATE OR DELETE ON dl05_v2_permits FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_grants_immutable BEFORE UPDATE OR DELETE ON dl05_answer_grants FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_receiver_consumptions_immutable BEFORE UPDATE OR DELETE ON dl05_receiver_consumptions FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_drain_receipts_immutable BEFORE UPDATE OR DELETE ON dl05_answer_drain_receipts FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_observer_evidence_immutable BEFORE UPDATE OR DELETE ON dl05_v2_observer_evidence FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_audit_immutable BEFORE UPDATE OR DELETE ON dl05_v2_audit FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_process_identity BEFORE UPDATE ON dl05_v2_processes FOR EACH ROW EXECUTE FUNCTION dl05_immutable('principal_id','tenant_id','owner_id','room_id','role','incarnation','producer','key_id','public_key','source_identity');
CREATE TRIGGER dl05_v2_install_identity BEFORE UPDATE ON dl05_v2_installations FOR EACH ROW EXECUTE FUNCTION dl05_immutable('proof_id','command_id','binding','binding_hash','installation_revision','runtime_principal','guardian_principal','observed_by','fence_ref');
CREATE FUNCTION dl05_v2_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (TG_TABLE_NAME='dl05_v2_registration_state' AND OLD.state='REVOKED' AND NEW IS DISTINCT FROM OLD)
 OR (TG_TABLE_NAME='dl05_v2_grant_state' AND OLD.state IN ('CONSUMED','EXPIRED','REVOKED','UNKNOWN') AND NEW.state<>OLD.state)
 OR (TG_TABLE_NAME='dl05_v2_execution_state' AND OLD.state IN ('DRAINED','FENCED') AND NEW.state<>OLD.state)
 OR (TG_TABLE_NAME='dl05_v2_execution_state' AND OLD.state='UNKNOWN' AND NEW.state='ACTIVE')
 OR (TG_TABLE_NAME='dl05_answer_segment_execution' AND NEW.state<>OLD.state AND NOT
 ((OLD.state='PREPARED' AND NEW.state IN ('STARTED','INTERRUPTED'))
 OR (OLD.state='STARTED' AND NEW.state IN ('DRAINED','INTERRUPTED','UNKNOWN'))
 OR (OLD.state='UNKNOWN' AND NEW.state IN ('DRAINED','INTERRUPTED')))) THEN
 RAISE EXCEPTION 'v2 state cannot reauthorize' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_registration_state_guard BEFORE UPDATE ON dl05_v2_registration_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_state_guard();
CREATE TRIGGER dl05_v2_grant_state_guard BEFORE UPDATE ON dl05_v2_grant_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_state_guard();
CREATE TRIGGER dl05_v2_execution_state_guard BEFORE UPDATE ON dl05_v2_execution_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_state_guard();
CREATE TRIGGER dl05_answer_segment_execution_guard BEFORE UPDATE ON dl05_answer_segment_execution FOR EACH ROW EXECUTE FUNCTION dl05_v2_state_guard();
-- Also invalidate v2 authorities when the existing CONTROL Stop path wins.
CREATE FUNCTION dl05_v2_stop_projection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.stop_revision>OLD.stop_revision OR (NEW.desired_state='STOPPED' AND OLD.desired_state<>'STOPPED') THEN
 UPDATE dl05_v2_registration_state s SET state='REVOKED',revision=revision+1,reason='STOP',revoked_at=clock_timestamp()
 FROM dl05_receiver_bootstraps b JOIN dl05_v2_commands c USING(command_id)
 WHERE b.bootstrap_id=s.bootstrap_id AND c.run_id=NEW.run_id AND s.state='ACTIVE';
 UPDATE dl05_v2_grant_state s SET state='REVOKED' FROM dl05_answer_grants g JOIN dl05_v2_commands c USING(command_id)
 WHERE s.grant_id=g.grant_id AND c.run_id=NEW.run_id AND s.state='ISSUED';
 UPDATE dl05_v2_execution_state s SET state='UNKNOWN' FROM dl05_v2_commands c
 WHERE s.command_id=c.command_id AND c.run_id=NEW.run_id AND s.state='ACTIVE';
 INSERT INTO dl05_v2_audit(command_id,reason,evidence_ref)
 SELECT c.command_id,'STOP','stop-revision:'||NEW.stop_revision FROM dl05_v2_commands c
 WHERE c.run_id=NEW.run_id ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_stop_projection AFTER UPDATE ON dl05_runs FOR EACH ROW EXECUTE FUNCTION dl05_v2_stop_projection();
REVOKE ALL ON dl05_v2_commands,dl05_v2_processes,dl05_v2_installations,dl05_v2_stage_challenges,
 dl05_receiver_bootstraps,dl05_v2_registration_state,dl05_answer_streams,dl05_answer_segments,
 dl05_receiver_artifacts,dl05_answer_segment_execution,dl05_answer_prepare_keys,dl05_answer_fact_observations,
 dl05_v2_permits,dl05_answer_grants,dl05_v2_grant_state,dl05_receiver_consumptions,dl05_v2_execution_state,
 dl05_answer_drain_receipts,dl05_v2_observer_evidence,dl05_v2_audit FROM PUBLIC;
CREATE TABLE dl05_v2_receipts (
 command_id text NOT NULL REFERENCES dl05_v2_commands(command_id), operation text NOT NULL,
 idempotency_key text NOT NULL, identity_hash text NOT NULL, receipt jsonb NOT NULL,
 PRIMARY KEY(command_id,operation,idempotency_key)
);
CREATE TRIGGER dl05_v2_receipts_immutable BEFORE UPDATE OR DELETE ON dl05_v2_receipts FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
REVOKE ALL ON dl05_v2_receipts FROM PUBLIC;
-- Identity and denial projections cannot be reassigned/deleted to regain authority.
CREATE TRIGGER dl05_v2_process_no_delete BEFORE DELETE ON dl05_v2_processes FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_install_no_delete BEFORE DELETE ON dl05_v2_installations FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_registration_identity BEFORE UPDATE ON dl05_v2_registration_state FOR EACH ROW EXECUTE FUNCTION dl05_immutable('bootstrap_id');
CREATE TRIGGER dl05_v2_grant_identity BEFORE UPDATE ON dl05_v2_grant_state FOR EACH ROW EXECUTE FUNCTION dl05_immutable('grant_id');
CREATE TRIGGER dl05_v2_execution_identity BEFORE UPDATE ON dl05_v2_execution_state FOR EACH ROW EXECUTE FUNCTION dl05_immutable('execution_id','command_id');
CREATE TRIGGER dl05_v2_unit_identity BEFORE UPDATE ON dl05_answer_segment_execution FOR EACH ROW EXECUTE FUNCTION dl05_immutable('artifact_id');
CREATE TRIGGER dl05_v2_stream_identity BEFORE UPDATE ON dl05_answer_streams FOR EACH ROW EXECUTE FUNCTION dl05_immutable('answer_id','command_id','deadline');
CREATE FUNCTION dl05_v2_stream_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.answer_revision<OLD.answer_revision OR (OLD.state<>'OPEN' AND (NEW.prepared_count<>OLD.prepared_count OR NEW.total_characters<>OLD.total_characters)) OR NEW.prepared_count<OLD.prepared_count OR NEW.drained_prefix<OLD.drained_prefix OR NEW.total_characters<OLD.total_characters
 OR (OLD.state<>'OPEN' AND NEW.state='OPEN')
 OR (OLD.state IN ('COMPLETED','INTERRUPTED') AND NEW.state<>OLD.state)
 OR (OLD.state='UNKNOWN' AND NEW.state NOT IN ('UNKNOWN','COMPLETED','INTERRUPTED'))
 OR (OLD.final_hash IS NOT NULL AND (NEW.final_hash IS DISTINCT FROM OLD.final_hash OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash)) THEN
 RAISE EXCEPTION 'answer knowledge cannot rewind' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_stream_guard BEFORE UPDATE ON dl05_answer_streams FOR EACH ROW EXECUTE FUNCTION dl05_v2_stream_guard();
ALTER TABLE dl05_answer_segments ADD CHECK(descriptor ?& ARRAY['artifactId','commandId','answerId','answerText','answerTextHash','artifactHash','sequence','previousArtifactHash','productId','productSnapshotVersion','factDependencies']);
CREATE TRIGGER dl05_v2_registration_state_no_delete BEFORE DELETE ON dl05_v2_registration_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_grant_state_no_delete BEFORE DELETE ON dl05_v2_grant_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_v2_execution_state_no_delete BEFORE DELETE ON dl05_v2_execution_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_segment_execution_no_delete BEFORE DELETE ON dl05_answer_segment_execution FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
CREATE TRIGGER dl05_answer_streams_no_delete BEFORE DELETE ON dl05_answer_streams FOR EACH ROW EXECUTE FUNCTION dl05_v2_append_only();
-- Scope is enforced even on repository SQL mistakes, beyond RPC validation.
ALTER TABLE dl05_receiver_consumptions ADD UNIQUE(execution_id,command_id);
ALTER TABLE dl05_v2_execution_state ADD FOREIGN KEY(execution_id,command_id) REFERENCES dl05_receiver_consumptions(execution_id,command_id);
CREATE FUNCTION dl05_v2_mirror_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM dl05_v2_commands c
 JOIN dl05_v2_processes r ON r.principal_id=NEW.runtime_principal
 JOIN dl05_v2_processes g ON g.principal_id=NEW.guardian_principal
 WHERE c.command_id=NEW.command_id
 AND r.tenant_id=c.tenant_id AND r.owner_id=c.owner_id AND r.room_id=c.room_id AND r.role='REGISTERED_RUNTIME'
 AND g.tenant_id=c.tenant_id AND g.owner_id=c.owner_id AND g.room_id=c.room_id AND g.role='OUTPUT_GUARDIAN') THEN
 RAISE EXCEPTION 'receiver principal scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_install_scope BEFORE INSERT ON dl05_v2_installations FOR EACH ROW EXECUTE FUNCTION dl05_v2_mirror_scope();
CREATE TRIGGER dl05_v2_consumption_scope BEFORE INSERT ON dl05_receiver_consumptions FOR EACH ROW EXECUTE FUNCTION dl05_v2_mirror_scope();
CREATE FUNCTION dl05_v2_tombstone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.contract_revision='durable-live-2' AND
 (NEW.stop_revision<OLD.stop_revision OR NEW.run_epoch<OLD.run_epoch OR NEW.state_revision<OLD.state_revision
 OR (OLD.stop_revision>0 AND (NEW.desired_state<>'STOPPED' OR NEW.stopped_at IS DISTINCT FROM OLD.stopped_at))) THEN
 RAISE EXCEPTION 'run tombstone cannot rewind' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_run_tombstone BEFORE UPDATE ON dl05_runs FOR EACH ROW EXECUTE FUNCTION dl05_v2_tombstone();
CREATE FUNCTION dl05_v2_process_tombstone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='dl05_v2_processes' THEN
 IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN RAISE EXCEPTION 'revoked process' USING ERRCODE='23514'; END IF;
 ELSE
 IF OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN RAISE EXCEPTION 'retired installation' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_process_tombstone BEFORE UPDATE ON dl05_v2_processes FOR EACH ROW EXECUTE FUNCTION dl05_v2_process_tombstone();
CREATE TRIGGER dl05_v2_install_tombstone BEFORE UPDATE ON dl05_v2_installations FOR EACH ROW EXECUTE FUNCTION dl05_v2_process_tombstone();

CREATE FUNCTION dl05_v2_artifact_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM dl05_v2_commands c WHERE c.command_id=NEW.command_id
 AND NEW.descriptor->>'tenantId'=c.tenant_id AND NEW.descriptor->>'ownerId'=c.owner_id
 AND NEW.descriptor->>'runId'=c.run_id AND NEW.descriptor->>'attemptId'=c.attempt_id
 AND NEW.descriptor->>'sessionId'=c.session_id AND NEW.descriptor->>'runEpoch'=c.run_epoch::text
 AND NEW.descriptor->>'producerIncarnation'=c.producer AND NEW.descriptor->>'requestHash'=c.request_hash
 AND NEW.descriptor->>'contractRevision'='durable-live-2') THEN
 RAISE EXCEPTION 'artifact scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_artifact_scope BEFORE INSERT ON dl05_answer_segments FOR EACH ROW EXECUTE FUNCTION dl05_v2_artifact_scope();

CREATE FUNCTION dl05_v2_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.revision<OLD.revision THEN RAISE EXCEPTION 'revision cannot rewind' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='dl05_answer_segment_execution' THEN
 IF OLD.drain_evidence IS NOT NULL AND NEW.drain_evidence IS DISTINCT FROM OLD.drain_evidence THEN RAISE EXCEPTION 'immutable drain proof' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dl05_v2_registration_revision BEFORE UPDATE ON dl05_v2_registration_state FOR EACH ROW EXECUTE FUNCTION dl05_v2_revision_guard();
CREATE TRIGGER dl05_v2_unit_revision BEFORE UPDATE ON dl05_answer_segment_execution FOR EACH ROW EXECUTE FUNCTION dl05_v2_revision_guard();
CREATE INDEX dl05_v2_recovery_scope ON dl05_v2_commands(tenant_id,owner_id,room_id,run_id,command_id);
