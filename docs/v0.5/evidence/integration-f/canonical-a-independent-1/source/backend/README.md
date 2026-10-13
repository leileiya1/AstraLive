# AstraLive Go Control Plane

The module uses Go `net/http` and chi, PostgreSQL/pgx with sqlc generated queries, and go-redis. It requires no GPU. Migrations run at startup. Runtime events use consumer group `astralive-go` on `dh.runtime.events.v1`; successful event persistence and state transition precede ACK and SSE broadcast. Dead letters go to `dh.runtime.events.v1.dlq` after five failed processing attempts.

## Start with containers

For the repository's standard Mock stack, run `scripts/integration-test.sh mock` from the project root. It starts `integration/mock_runtime` through `infra/compose.yaml` alongside Backend, PostgreSQL, and Redis. The local Backend HTTP port defaults to `18080`.

The Backend-only `backend/compose.yaml` starts PostgreSQL, Redis, and Backend. If using it from `backend/`, set `ASTRALIVE_DB_PASSWORD`, `INTERNAL_API_TOKEN`, and `AI_RUNTIME_URL` before `docker compose up --build -d`. `AI_RUNTIME_URL` must point to an externally started Runtime address reachable from the Backend container; the Backend Compose stack does not start a Mock Runtime.

## Start from source

Set variables in `.env.example`, including `AI_RUNTIME_URL`, then run `go run ./cmd/server` from `backend/`. From the project root, `scripts/run-local-v11.sh mock` runs the standard `integration/mock_runtime` for local GPU-free acceptance; it requires the isolated PostgreSQL/Redis and SSH settings described in `infra/README.md`. Run `python3 tests/smoke.py` with `BACKEND_URL` and `INTERNAL_API_TOKEN` set for an existing stack. Run `go test ./...` from `backend/` for unit and frozen OpenAPI schema checks.

Generated files are committed under `generated/`. Regenerate SQL with `go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.30.0 generate`; regenerate OpenAPI types with `sh scripts/generate-openapi.sh`. The script generates types directly from the frozen `contracts/control-api.openapi.yaml` and `contracts/runtime-api.openapi.yaml`; the embedded Control spec is an unmodified copy used for request validation.

`/health/live` checks the process, `/health/ready` checks PostgreSQL and Redis, and `/metrics` exports Prometheus metrics. Internal product Tool routes require `Authorization: Bearer <INTERNAL_API_TOKEN>` and should only be reachable from the Runtime network.

Knowledge document upload remains deferred and non-Mock Avatar prepare and KnowledgeBase index jobs remain `PENDING` without an execution protocol. The standard Integration Mock does not provide WebRTC media; browser preview requires a capable Runtime.
