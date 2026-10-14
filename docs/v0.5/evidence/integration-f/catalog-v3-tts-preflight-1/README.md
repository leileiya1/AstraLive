# Fresh complete V3 CPU speech preflight

Source `609ee76cec0924a44d683152d8e3d0285966a4ea`; all140 statements were newly
synthesized in this run. Actual cached XiaoYa CPU speaker0/speed1/threads2,
production StreamingVoiceAdapter/PCM16kConverter, native22050Hz to16000Hz mono
s16le. Product template substitutions are fixed fixture expectations, not proof
of a live SQL product capture or LLM response.

PASS only for CPU duration/framing:140/140,750.2934375 original seconds,
753.2 seconds after640-sample zero-padding; every segment4.12–6.36s, no failures
or8s oversize. Canonical price answer3.92s, nonempty approved bridges3.64/5.40s.
No historical time or extras were added to the narration sum. This is no
continuous live session, GPU, Chrome/RTMP, audible-content or naturalness result.

`summary.json` records all artifact hashes and the exact source/fixture/model
hashes. `result.json` and `tts.log` retain per-statement original/pad samples,
timed chunk positions, PCM hashes and generation/sequence checks. PCM files
were not retained for this duration gate; their hashes alone do not establish
audience sound. Earlier partial preflights remain separately preserved.

Reproduce in a new temporary output directory, never inside this archive:

```sh
task_out=$(mktemp -d /private/tmp/astralive-v3-cpu-repro.XXXXXX)
mkdir "$task_out/source"
cp docs/v0.5/evidence/integration-f/catalog-v3-tts-preflight-1/tts_preflight.py "$task_out/"
git archive 609ee76cec0924a44d683152d8e3d0285966a4ea runtime/app integration/v0.5/fixtures/real_golden_catalog.json | tar -x -C "$task_out/source"
/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python "$task_out/tts_preflight.py" > "$task_out/tts.log" 2>&1
```

The script pins the existing local model directory and source; no downloads or
SSH/GPU are performed. Dependencies/model availability must match the manifest;
other machines need an explicitly reviewed path adjustment and separate result.
