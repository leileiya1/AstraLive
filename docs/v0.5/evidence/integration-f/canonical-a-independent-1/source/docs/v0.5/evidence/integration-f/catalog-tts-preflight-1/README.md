# Catalog preflight evidence

This folder is an actual local CPU TTS/production BuildPlan precheck, not a live Golden run. Two independent synthesis passes remain separate. `first-measurement.json` preserves the initial140-sentence run; `repeat-measurement.json` comes from the archived `tts-preflight.py`, with complete native stdout/stderr in `tts.log`. PCM SHA256 identifies pre-pad16000Hz samples; padSamples/paddedSamples determine the source artifact duration. Short10-sentence duration reuses the corresponding measured rows, and is not an independently rendered Session.

Reproduction from F repository root using the installed environment/model:

```
PYTHONPATH=runtime /private/tmp/astralive-f-media-venv-1/bin/python docs/v0.5/evidence/integration-f/catalog-tts-preflight-1/tts-preflight.py
```

The script uses explicit cached CPU provider and speaker0/speed1/2threads. It reads no keys and starts no Backend/Runtime/GPU. Re-run writes repeat-measurement.json; preserve existing artifact first if collecting another independent run. Native warning `Ignore OOV 'CNY'` is a real price-answer pronunciation gap, not removed to pass duration checks.

`buildplan-probe.go` was placed only into a temporary immutable git archive's backend/internal/catalog_plan_review, then executed with `go run ./internal/catalog_plan_review <absolute long fixture> <absolute smoke fixture>`. Its actual source SHA/command/exit and archived model.go SHA are in buildplan-result.json; raw output is buildplan.log. No production file or planner was edited. Source/artifact hash inventory is manifest.json. The F-owned fixture README explains transport replay, fact IDs, measured caps and acceptance limits.
