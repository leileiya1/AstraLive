-- Additive owner mapping; legacy rows are intentionally unclaimed.
CREATE TABLE resource_owners (
 kind text NOT NULL CHECK(kind IN ('avatar','voice','product','knowledge','room','session','job')),
 resource_id text NOT NULL,
 tenant_id text NOT NULL, user_id text NOT NULL,
 PRIMARY KEY(kind,resource_id),
 FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals
);
CREATE INDEX resource_owners_scope ON resource_owners(tenant_id,user_id,kind);
CREATE TABLE session_provider_bindings (
 session_id text PRIMARY KEY REFERENCES live_sessions(id) ON DELETE CASCADE,
 tenant_id text NOT NULL,user_id text NOT NULL,
 binding_id text NOT NULL UNIQUE,
 room_snapshot jsonb NOT NULL,
 summary jsonb NOT NULL,
 captured_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 released_at timestamptz,
 FOREIGN KEY(tenant_id,user_id) REFERENCES config_principals
);
CREATE TABLE operator_login_attempts (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 window_at timestamptz NOT NULL, attempts integer NOT NULL
);
