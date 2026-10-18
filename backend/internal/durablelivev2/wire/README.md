# durable-live-2 wire (Agent4 only)

Generated from the approved immutable contract. Use DecodeRequest/ReadRequest and
EncodeRequest with authenticated transport metadata, or response wrappers with
operation/status. DTO decode is not authentication, a fact check, or execution
permission. This package registers no handlers and imports no SQL/media runtime.

Regenerate/check from repository root with
`python3 scripts/durable-live/generate_v2_wire.py [--check]`.
See `docs/v0.5/implementation/DTO-HANDOFF.md` for examples, null/omitted semantics,
secret logging rules, toolchain and acceptance limits. Do not edit generated
files or copy them into another owner's package.
