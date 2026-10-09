CREATE TABLE config_principals (
 tenant_id text NOT NULL, user_id text NOT NULL,
 PRIMARY KEY (tenant_id,user_id)
);
CREATE TABLE config_auth_sessions (
 token_hash text PRIMARY KEY,
 tenant_id text NOT NULL, user_id text NOT NULL,
 expires_at timestamptz NOT NULL,
 FOREIGN KEY (tenant_id,user_id) REFERENCES config_principals
);
CREATE TABLE user_settings (
 tenant_id text NOT NULL, user_id text NOT NULL,
 version bigint NOT NULL CHECK (version > 0),
 policy jsonb NOT NULL,
 PRIMARY KEY (tenant_id,user_id),
 FOREIGN KEY (tenant_id,user_id) REFERENCES config_principals
);
CREATE TABLE config_profiles (
 tenant_id text NOT NULL, user_id text NOT NULL, id text NOT NULL,
 kind text NOT NULL CHECK (kind IN ('LLM','TTS','AVATAR','GPU_WORKER','LIVE_PLATFORM')),
 name text NOT NULL, provider text NOT NULL, config jsonb NOT NULL,
 version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
 enabled boolean NOT NULL DEFAULT true,
 is_default boolean NOT NULL DEFAULT false CHECK (NOT is_default OR enabled),
 verification text NOT NULL DEFAULT 'UNTESTED' CHECK (verification IN ('UNTESTED','VERIFIED','FAILED')),
 error_code text NOT NULL DEFAULT '',
 health text NOT NULL DEFAULT 'UNKNOWN' CHECK (health IN ('UNKNOWN','UP','DOWN')),
 health_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,user_id,id),
 FOREIGN KEY (tenant_id,user_id) REFERENCES config_principals
);
CREATE UNIQUE INDEX config_one_default ON config_profiles(tenant_id,user_id,kind) WHERE is_default AND enabled;
CREATE TABLE provider_credentials (
 tenant_id text NOT NULL, user_id text NOT NULL, profile_id text NOT NULL,
 key_id text NOT NULL, ciphertext bytea NOT NULL,
 PRIMARY KEY(tenant_id,user_id,profile_id),
 FOREIGN KEY(tenant_id,user_id,profile_id) REFERENCES config_profiles ON DELETE CASCADE
);
CREATE TABLE provider_bindings (
 id text PRIMARY KEY, tenant_id text NOT NULL, user_id text NOT NULL,
 snapshot jsonb NOT NULL, expires_at timestamptz NOT NULL,
 FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals
);
CREATE INDEX config_sessions_expiry ON config_auth_sessions(expires_at);
CREATE INDEX provider_bindings_expiry ON provider_bindings(expires_at);
CREATE VIEW llm_profiles AS SELECT * FROM config_profiles WHERE kind='LLM';
CREATE VIEW tts_profiles AS SELECT * FROM config_profiles WHERE kind='TTS';
CREATE VIEW avatar_profiles AS SELECT * FROM config_profiles WHERE kind='AVATAR';
CREATE VIEW gpu_worker_profiles AS SELECT * FROM config_profiles WHERE kind='GPU_WORKER';
CREATE VIEW live_platform_profiles AS SELECT * FROM config_profiles WHERE kind='LIVE_PLATFORM';
CREATE TABLE config_test_attempts (
 tenant_id text NOT NULL,user_id text NOT NULL, attempted_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,user_id),
 FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals
);
