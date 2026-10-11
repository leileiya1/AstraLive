# F premerge integration harness

This package reproduces missing A/B/C seams before any branch merge. It is a negative gate, not an implementation of Narration or a real-media acceptance test. It makes no change to frozen contracts or owner worktrees.

`premerge_probe.py` archives exact A/B commits into owned disposable directories, copies F's Go fixture into the **temporary A checkout**, migrates an owned PostgreSQL cluster, runs actual Go journal and Python HTTP Runtime with CPU fixture providers, checks missing schema/handlers/receipt adapter, and calls B's Timeline. No durable ACK is faked. Known core gaps yield exit1/result FAIL and are retained. C has no implementation to exercise. Production Backend auth/public-resource/Session creation is not emulated as passed; the fixture seeds a known owned test run directly.

Requirements: local installed PostgreSQL binaries, Go, Python3.12+ with Runtime dependencies, and both source SHAs in the Git object store. Existing validated Runtime Python can be borrowed without installing/changing dependencies. Never supply a production DB; the script creates its own local cluster automatically.

```sh
/path/to/runtime-python integration/v0.5/premerge_probe.py \
  --a-sha e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 \
  --b-sha cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1 \
  --pg-bin /opt/homebrew/opt/postgresql@17/bin \
  --output /tmp/new-unique-f-output
```

Output must not already exist. All child processes/cluster are owned by this run and cleaned in finally. Secrets are freshly generated private files in the disposable directory, never serialized in the result. Logs contain static fixture text/IDs only. A future version must add real C plan/cursor tests and a genuine persistence adapter; do not turn these failures green by returning `{durable:true}` from a test double.

Independent module checks use an isolated archive of each pin so concurrent owner edits cannot invalidate evidence:

```sh
mkdir /tmp/new-unique-a-source
# Substitute B or D SHA for their respective checks; never overlay implementation files.
git archive e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 \
  backend runtime contracts gpu_worker tests integration | tar -x -C /tmp/new-unique-a-source
# From this archive, run exact commands in docs/v0.5/CHAOS-TEST-REPORT.md.
```

Do not run old scripts that write historical docs/v0.4 outputs without redirecting/isolating their evidence. No branch merge occurs in this harness. More Golden fixtures/faults/Chrome/RTMP measurements are pending C and actual integration; unexecuted cases are NOT TESTED.
