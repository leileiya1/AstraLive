-- Frozen v0.5 A/B/C seam. C owns state decisions and JSON business projections.
ALTER TABLE v05_session_runs ADD COLUMN timeline_revision bigint NOT NULL DEFAULT 0 CHECK(timeline_revision BETWEEN 0 AND 9007199254740991);
CREATE TABLE v05_narrations (
 narration_id text PRIMARY KEY,session_id text NOT NULL REFERENCES live_sessions(id),tenant_id text NOT NULL,user_id text NOT NULL,
 run_epoch bigint NOT NULL,revision bigint NOT NULL DEFAULT 0 CHECK(revision BETWEEN 0 AND 9007199254740991),
 state text NOT NULL CHECK(state IN ('IDLE','PLANNING','NARRATING','SUSPEND_REQUESTED','SUSPENDED','ANSWERING','BRIDGE_READY','RESUMING','STOPPING','STOPPED','RECOVERY_REQUIRED','FAILED')),
 script_version text NOT NULL,product_snapshot_hash text NOT NULL,
 plan_json jsonb NOT NULL,completion_cursor_json jsonb NOT NULL DEFAULT '{}',resume_point_json jsonb NOT NULL DEFAULT '{}',document_json jsonb NOT NULL DEFAULT '{}',
 stop_barrier boolean NOT NULL DEFAULT false,recovery_disposition text,updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(session_id,narration_id),UNIQUE(session_id,narration_id,tenant_id,user_id),
 FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id)
);
CREATE TABLE v05_segments (
 segment_id text PRIMARY KEY,narration_id text NOT NULL,session_id text NOT NULL,tenant_id text NOT NULL,user_id text NOT NULL,
 beat_id text NOT NULL,segment_ordinal bigint NOT NULL CHECK(segment_ordinal BETWEEN 0 AND 9007199254740991),
 text_hash text NOT NULL,fact_ids jsonb NOT NULL DEFAULT '[]',text text NOT NULL,product_version text NOT NULL,status text NOT NULL,
 document_json jsonb NOT NULL DEFAULT '{}',completed_at timestamptz,updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(narration_id,segment_ordinal),UNIQUE(session_id,segment_id),
 FOREIGN KEY(session_id,narration_id,tenant_id,user_id) REFERENCES v05_narrations(session_id,narration_id,tenant_id,user_id)
);
CREATE TABLE v05_interaction_turns (
 turn_id text PRIMARY KEY,narration_id text NOT NULL,session_id text NOT NULL,tenant_id text NOT NULL,user_id text NOT NULL,
 source_ids jsonb NOT NULL,question_hash text NOT NULL,question text NOT NULL,deadline timestamptz NOT NULL,state text NOT NULL,
 resume_point_revision bigint,answer_summary text,document_json jsonb NOT NULL DEFAULT '{}',updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(session_id,narration_id,tenant_id,user_id) REFERENCES v05_narrations(session_id,narration_id,tenant_id,user_id)
);
CREATE TABLE v05_timeline_epochs (
 session_id text NOT NULL,run_epoch bigint NOT NULL,timeline_epoch bigint NOT NULL CHECK(timeline_epoch BETWEEN 1 AND 9007199254740991),
 tenant_id text NOT NULL,user_id text NOT NULL,status text NOT NULL CHECK(status IN ('PREPARED','ACTIVE','SEALED')),
 reservation_token text NOT NULL UNIQUE,expected_previous_epoch bigint NOT NULL,origin_sample bigint NOT NULL CHECK(origin_sample BETWEEN 0 AND 9007199254740991),reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),activated_at timestamptz,sealed_at timestamptz,
 PRIMARY KEY(session_id,run_epoch,timeline_epoch),FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id)
);
CREATE UNIQUE INDEX v05_one_epoch_prepared ON v05_timeline_epochs(session_id,run_epoch) WHERE status='PREPARED';
CREATE UNIQUE INDEX v05_one_epoch_active ON v05_timeline_epochs(session_id,run_epoch) WHERE status='ACTIVE';
-- Existing runs keep epoch 1; no invented playback proof.
INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason,activated_at)
 SELECT session_id,run_epoch,current_timeline_epoch,tenant_id,user_id,CASE WHEN status IN ('ACTIVE','STOPPING') THEN 'ACTIVE' ELSE 'SEALED' END,
 'initial:'||session_id||':'||run_epoch,0,current_committed_sample,'INITIAL_RUN',clock_timestamp() FROM v05_session_runs;
CREATE TABLE v05_segment_attempts (
 attempt_id text PRIMARY KEY,session_id text NOT NULL,run_epoch bigint NOT NULL,timeline_epoch bigint NOT NULL,tenant_id text NOT NULL,user_id text NOT NULL,
 narration_id text NOT NULL,segment_id text NOT NULL,command_id text NOT NULL UNIQUE REFERENCES v05_outbox(command_id),
 utterance_id text NOT NULL,lane text NOT NULL CHECK(lane IN ('NARRATION','AUDIENCE_ANSWER','RESUME_BRIDGE','OPERATOR','SYSTEM')),worker_ref_json jsonb NOT NULL DEFAULT '{}',
 generation_id bigint CHECK(generation_id BETWEEN 1 AND 9007199254740991),worker_epoch text,worker_generation_id bigint,
 status text NOT NULL DEFAULT 'PLANNED' CHECK(status IN ('PLANNED','STARTED','READY','COMMITTED','COMPLETED','INTERRUPTED','UNKNOWN','CANCELLED')),
 descriptor_json jsonb NOT NULL DEFAULT '{}',document_json jsonb NOT NULL DEFAULT '{}',updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(session_id,narration_id,tenant_id,user_id) REFERENCES v05_narrations(session_id,narration_id,tenant_id,user_id),
 FOREIGN KEY(session_id,segment_id) REFERENCES v05_segments(session_id,segment_id),
 FOREIGN KEY(session_id,run_epoch,timeline_epoch) REFERENCES v05_timeline_epochs,
 CHECK((worker_epoch IS NULL)=(worker_generation_id IS NULL))
);
CREATE TABLE v05_timeline_commits (
 session_id text NOT NULL,run_epoch bigint NOT NULL,timeline_epoch bigint NOT NULL,segment_id text NOT NULL,attempt_id text NOT NULL REFERENCES v05_segment_attempts(attempt_id),
 tenant_id text NOT NULL,user_id text NOT NULL,command_id text NOT NULL UNIQUE REFERENCES v05_outbox(command_id),
 generation_id bigint NOT NULL CHECK(generation_id BETWEEN 1 AND 9007199254740991),start_sample bigint NOT NULL CHECK(start_sample>=0),end_sample bigint NOT NULL CHECK(end_sample>start_sample AND end_sample<=9007199254740991),sample_rate integer NOT NULL CHECK(sample_rate>0),
 identity_json jsonb NOT NULL,descriptor_json jsonb NOT NULL,required_sinks jsonb NOT NULL,optional_sinks jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('PENDING_INSTALL','ELIGIBLE','SEALED')),play_state text NOT NULL DEFAULT 'UNKNOWN' CHECK(play_state IN ('UNKNOWN','COMPLETED','INTERRUPTED')),
 sink_receipts jsonb NOT NULL DEFAULT '[]',completion_hash text,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),installed_at timestamptz,completed_at timestamptz,
 PRIMARY KEY(session_id,run_epoch,timeline_epoch,segment_id,attempt_id),
 FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id),
 FOREIGN KEY(session_id,run_epoch,timeline_epoch) REFERENCES v05_timeline_epochs,
 FOREIGN KEY(session_id,segment_id) REFERENCES v05_segments(session_id,segment_id)
);
CREATE TABLE v05_timeline_observations (
 command_id text NOT NULL REFERENCES v05_outbox(command_id),operation text NOT NULL,observation_hash text NOT NULL,proof_json jsonb NOT NULL,response_json jsonb NOT NULL,
 session_id text NOT NULL,run_epoch bigint NOT NULL,tenant_id text NOT NULL,user_id text NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(command_id,operation),FOREIGN KEY(session_id,run_epoch,tenant_id,user_id) REFERENCES v05_session_runs(session_id,run_epoch,tenant_id,user_id)
);
-- Serialize interval checks even for repository writes; audio intervals are immutable.
CREATE FUNCTION v05_commit_interval_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM v05_session_runs WHERE session_id=NEW.session_id AND run_epoch=NEW.run_epoch FOR UPDATE;
 IF TG_OP='UPDATE' AND (OLD.session_id,OLD.run_epoch,OLD.timeline_epoch,OLD.segment_id,OLD.attempt_id,OLD.start_sample,OLD.end_sample,OLD.sample_rate,OLD.identity_json,OLD.descriptor_json,OLD.required_sinks) IS DISTINCT FROM (NEW.session_id,NEW.run_epoch,NEW.timeline_epoch,NEW.segment_id,NEW.attempt_id,NEW.start_sample,NEW.end_sample,NEW.sample_rate,NEW.identity_json,NEW.descriptor_json,NEW.required_sinks) THEN
  RAISE EXCEPTION 'immutable timeline commit' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM v05_timeline_commits c WHERE c.session_id=NEW.session_id AND c.run_epoch=NEW.run_epoch AND c.start_sample<NEW.end_sample AND NEW.start_sample<c.end_sample) THEN
  RAISE EXCEPTION 'overlapping timeline interval' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER v05_commit_interval BEFORE INSERT OR UPDATE ON v05_timeline_commits FOR EACH ROW EXECUTE FUNCTION v05_commit_interval_guard();
CREATE INDEX v05_narrations_recovery ON v05_narrations(session_id,run_epoch) WHERE state NOT IN ('STOPPED','FAILED');
CREATE INDEX v05_attempts_recovery ON v05_segment_attempts(session_id,run_epoch) WHERE status IN ('STARTED','READY','COMMITTED','UNKNOWN');
CREATE UNIQUE INDEX v05_one_narration_active ON v05_narrations(session_id) WHERE state NOT IN ('STOPPED','FAILED');
CREATE FUNCTION v05_narration_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.narration_id,OLD.session_id,OLD.tenant_id,OLD.user_id,OLD.script_version,OLD.product_snapshot_hash,OLD.plan_json) IS DISTINCT FROM (NEW.narration_id,NEW.session_id,NEW.tenant_id,NEW.user_id,NEW.script_version,NEW.product_snapshot_hash,NEW.plan_json) OR OLD.stop_barrier AND NOT NEW.stop_barrier THEN
  RAISE EXCEPTION 'immutable narration authority/plan or stop barrier' USING ERRCODE='23514';
 END IF;
 IF NEW.revision<OLD.revision OR NEW.revision=OLD.revision AND (OLD.run_epoch,OLD.state,OLD.completion_cursor_json,OLD.resume_point_json,OLD.document_json,OLD.stop_barrier) IS DISTINCT FROM (NEW.run_epoch,NEW.state,NEW.completion_cursor_json,NEW.resume_point_json,NEW.document_json,NEW.stop_barrier) THEN
  RAISE EXCEPTION 'narration revision CAS required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER v05_narration_immutable BEFORE UPDATE ON v05_narrations FOR EACH ROW EXECUTE FUNCTION v05_narration_guard();
CREATE FUNCTION v05_segment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.segment_id,OLD.narration_id,OLD.session_id,OLD.tenant_id,OLD.user_id,OLD.beat_id,OLD.segment_ordinal,OLD.text_hash,OLD.fact_ids,OLD.text,OLD.product_version) IS DISTINCT FROM (NEW.segment_id,NEW.narration_id,NEW.session_id,NEW.tenant_id,NEW.user_id,NEW.beat_id,NEW.segment_ordinal,NEW.text_hash,NEW.fact_ids,NEW.text,NEW.product_version) OR OLD.status='COMPLETED' AND NEW.status<>'COMPLETED' THEN
  RAISE EXCEPTION 'immutable segment plan or completion' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER v05_segment_immutable BEFORE UPDATE ON v05_segments FOR EACH ROW EXECUTE FUNCTION v05_segment_guard();
CREATE FUNCTION v05_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.attempt_id,OLD.session_id,OLD.run_epoch,OLD.timeline_epoch,OLD.narration_id,OLD.segment_id,OLD.command_id,OLD.tenant_id,OLD.user_id,OLD.utterance_id,OLD.lane) IS DISTINCT FROM (NEW.attempt_id,NEW.session_id,NEW.run_epoch,NEW.timeline_epoch,NEW.narration_id,NEW.segment_id,NEW.command_id,NEW.tenant_id,NEW.user_id,NEW.utterance_id,NEW.lane) OR OLD.generation_id IS NOT NULL AND OLD.generation_id IS DISTINCT FROM NEW.generation_id OR OLD.descriptor_json<>'{}'::jsonb AND OLD.descriptor_json IS DISTINCT FROM NEW.descriptor_json OR OLD.worker_epoch IS NOT NULL AND (OLD.worker_epoch,OLD.worker_generation_id,OLD.worker_ref_json) IS DISTINCT FROM (NEW.worker_epoch,NEW.worker_generation_id,NEW.worker_ref_json) OR OLD.status='COMPLETED' AND NEW.status<>'COMPLETED' THEN
  RAISE EXCEPTION 'immutable segment attempt or completion' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER v05_attempt_immutable BEFORE UPDATE ON v05_segment_attempts FOR EACH ROW EXECUTE FUNCTION v05_attempt_guard();
CREATE FUNCTION v05_turn_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.turn_id,OLD.narration_id,OLD.session_id,OLD.tenant_id,OLD.user_id,OLD.source_ids,OLD.question_hash,OLD.question,OLD.deadline) IS DISTINCT FROM (NEW.turn_id,NEW.narration_id,NEW.session_id,NEW.tenant_id,NEW.user_id,NEW.source_ids,NEW.question_hash,NEW.question,NEW.deadline) THEN
  RAISE EXCEPTION 'immutable captured interaction turn' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER v05_turn_immutable BEFORE UPDATE ON v05_interaction_turns FOR EACH ROW EXECUTE FUNCTION v05_turn_guard();
