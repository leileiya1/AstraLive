# durable-live-2 Python contracts (Agent4 only)

Pure standard-library, closed typed DTOs and strict operation codecs. Import
`from astralive_contracts import durable_live_v2 as wire` with the repository root
on PYTHONPATH. Pass raw UTF8 bytes to decode_request; use encode_request as the
intentional wire serializer. Do not JSON-log wire bytes or convert secret values
to plaintext for diagnostics. No database, network or media API is activated.

See `docs/v0.5/implementation/DTO-HANDOFF.md` for API/interop examples and limits.
Do not copy Schema/types; consume the Agent4 pinned delivery.
