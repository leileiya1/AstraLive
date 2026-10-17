-- Run as a trusted DB administrator after provisioning guardian_reader and
-- durable-live-1. No migration, Outbox write, lease mutation or content write.
GRANT USAGE ON SCHEMA public TO guardian_reader;
GRANT SELECT ON dl05_runs, dl05_run_terms, dl05_run_leases, dl05_room_outputs,
 dl05_output_permits, dl05_attempts, dl05_runtime_inbox, dl05_run_slots
 TO guardian_reader;
-- Keep the trusted backend OUTPUT_GUARDIAN role/token separately registered;
-- an IPC token is not a backend journal token. Do not grant config credential
-- tables, UPDATE, superuser, role creation or replication to guardian_reader.
