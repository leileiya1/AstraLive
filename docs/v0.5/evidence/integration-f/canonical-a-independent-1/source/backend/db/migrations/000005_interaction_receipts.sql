-- At-most-once automatic dispatch across controller restarts. Contains no comment/user data.
CREATE TABLE interaction_receipts (
 session_id text NOT NULL REFERENCES live_sessions(id),
 trace_id text NOT NULL,
 status text NOT NULL CHECK (status IN ('RESERVED','ACCEPTED','FAILED')),
 utterance_id text REFERENCES utterances(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(session_id,trace_id)
);
