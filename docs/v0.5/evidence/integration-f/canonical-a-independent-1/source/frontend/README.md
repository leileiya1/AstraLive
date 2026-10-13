# AstraLive Frontend

React + Vite + TypeScript 7 native preview + Bun control console. All business requests use the Go public Control API. WebRTC media is isolated in `useLivePreview`.

## Run

```sh
cd frontend
bun install
cp .env.example .env.local
bun run dev
```

Set `VITE_API_BASE_URL` to the Go Control Plane origin. Leave it empty when the UI and Go API share an origin or a proxy serves `/api/v1` and `/health`. Set `VITE_ENABLE_DEV_PLATFORM_EVENTS=true` for the developer COMMENT panel; it is only rendered in development builds.

## WebRTC ICE deployment

`useLivePreview()` creates the browser peer using `VITE_WEBRTC_*` values at Vite build time. For local same-host development, leave all ICE values empty. For a browser and Runtime on different hosts or behind NAT, configure a reachable STUN server, for example `VITE_WEBRTC_STUN_URLS=stun:stun.l.google.com:19302`. This is an example, not a required provider. STUN does not cover every NAT or firewall. If UDP paths or NAT traversal still fail, deploy a TURN relay and configure `VITE_WEBRTC_TURN_URLS`, `VITE_WEBRTC_TURN_USERNAME`, and `VITE_WEBRTC_TURN_CREDENTIAL`. Separate multiple URLs with commas, for example `turn:relay.example:3478?transport=udp,turns:relay.example:5349?transport=tcp`. A TURN username and credential must be supplied together. Invalid ICE URLs are ignored; check browser warnings if a connection fails.

These are public browser build values. Static TURN credentials in a browser bundle are suitable only for MVP validation; production should issue short-lived TURN credentials. Rebuild the frontend after changing them. In Compose, set the same values in `infra/.env`; its frontend build passes them into Vite.

```sh
bun run build
bun run test
```

`bun run build` regenerates `src/api/generated.ts` from `../contracts/control-api.openapi.yaml`. The committed `bun.lock` pins dependencies.

## Contract boundaries

The browser sends its complete SDP offer through `POST /api/v1/live-sessions/{sessionId}/webrtc/offer`. Go forwards signaling to Runtime; media flows directly between Browser and Runtime. The frontend never calls `/internal/v1/**`.

The current contract has no KnowledgeBase query route or creation fields. The room form accepts an existing KnowledgeBase ID. Dashboard runtime health, active session count, and aggregate recent errors have no public API yet; the console shows errors for its active session from SSE.
