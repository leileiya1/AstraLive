# AstraLive v1.1 integration stack

CPU-only local acceptance uses `scripts/run-local-v11.sh`. It builds Go, starts the Python integration Mock, Real Runtime with Mock AI, and an optional cumulative `light` mode (Mock LLM, real local TTS, lightweight Avatar, WebRTC). It reuses the dedicated PostgreSQL database and Redis DB configured in `backend/.env.integration`; the script starts SSH tunnels to `school-linux` and stops its local processes and tunnels on exit. Do not run it against shared production databases.

```sh
runtime/.venv/bin/python -m unittest tests.test_contracts -v
scripts/run-local-v11.sh               # mock, real, light
scripts/run-local-v11.sh real          # one mode
```

The script writes inspectable request/Tool evidence under `integration/evidence/`. Proxy logs omit authorization headers. It runs COMMENT, Context, SSE heartbeat, Product Tool, WebRTC signaling, a real Chrome browser check, and failure injection. The `real` mode sets `MOCK_MEDIA=false` so WebRTC is available without GPU. The `light` mode needs the local `TTS_MODEL_DIR` path embedded in the script.

Docker Compose remains available in `infra/compose.yaml` for self-contained infrastructure, but was not verified in the v1.1 run because the local Docker CLI is unavailable. Its all-Mock media mode returns a stable `503 WEBRTC_FAILED`, so browser preview requires the Real Runtime media adapter.

For browser ICE deployment, set `VITE_WEBRTC_STUN_URLS` and, if needed, `VITE_WEBRTC_TURN_URLS`, `VITE_WEBRTC_TURN_USERNAME`, and `VITE_WEBRTC_TURN_CREDENTIAL` in `infra/.env` before building the frontend image. Compose passes these as Vite build arguments; changing them requires a rebuild. Local same-host use can leave them empty. Cross-host or NAT use generally needs STUN; more restrictive NAT or blocked UDP may require TURN. A STUN server alone does not guarantee reachability. TURN credentials embedded in a static frontend build are appropriate only for MVP validation; use short-lived credentials in production.
