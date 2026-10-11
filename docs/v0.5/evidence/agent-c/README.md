# Agent C delivery evidence

**CONDITIONAL implementation, v0.5-frozen-1.** This is a committed Go/PostgreSQL
orchestrator and Python segmented execution candidate, not contract-only ACK,
main merge, default-enable or complete product acceptance. See
[implementation and rollback](../../NARRATION-CONTINUITY.md) and
[manifest/source/dependency hashes](manifest.json).

## Recorded gates

| Gate | Evidence and result | Scope |
| --- | --- | --- |
| Final full Go race | [log](delivery-go-race.log), exit0 | Actual owned PostgreSQL; A durability/process helpers, C product/Stop/FORCE/expiry/Runtime SIGKILL tests and legacy packages |
| C detailed source gate | [log](product-retirement.log), exit0 | Separate changed-price and changed-product retirement, SQL Stop envelope, protected Cookie/Origin FORCE transaction and five crash windows |
| Full Runtime discovery | [gzip log](runtime-regression.log.gz), exit0, 210 tests / 11 skipped | Default regression plus segment/cancellation/config tests; skipped real-service opt-ins remain skipped |
| Frozen v1.1 validator | [log](delivery-contract.log), exit0 | Contracts unchanged from5a244781; does not prove media behavior |
| Current short native fixture | [log](native-short/run.log), PASS69.19s | 20×3-second authored source plan, comment around10s, real headless Chrome and local FFmpeg RTMP, 21 media commits |
| Seeded long native fixture | [gzip log](native-random/run.log.gz), PASS660.69s | 200×3-second plan, seed20261011, five selected comments at ordinals4/111/113/150/151, 209 media commits, normal Stop |
| Previous fixed-position long fixture | [gzip log](prior-fixed-long.log.gz), PASS657.60s | Independent continuous run, not time aggregated with random repeat |
| Focused old-epoch execution | [log](execution.log), exit0 | Late audio/video use old epoch with unchanged generation; invalidated media rejected independent of task cancellation |

Environment: macOS ARM, owned PostgreSQL17 at localhost54339, dependency Python
`/tmp/astralive-v05-b-venv/bin/python`, native headless Chrome154.0.8037.98,
ffmpeg/ffprobe, Lightweight2D160×160/25fps, synthetic3-second pulse audio. Private
fixture authentication credentials are not archived. A's migrations and B's
Timeline/sinks are consumed through the exact cherry-pick map in the manifest;
C changes no Worker wire format, sink implementation or database migration.

Full Go commands, from `backend` with an owned database and the dependency Python:

```sh
DURABILITY_TEST_DATABASE_URL="$OWNED_TEST_DSN" \
NARRATION_TEST_PYTHON="$DEPENDENCY_PYTHON" \
DURABILITY_TEST_PYTHON="$DEPENDENCY_PYTHON" \
go test -race -count=1 -timeout=5m ./...
```

Runtime and schema checks, from repository root:

```sh
PYTHONPATH=.:runtime "$DEPENDENCY_PYTHON" -m unittest discover -s runtime/tests
"$DEPENDENCY_PYTHON" contracts/validate_v1_1.py
```

Native short / long commands, from `backend`:

```sh
DURABILITY_TEST_DATABASE_URL="$OWNED_TEST_DSN" \
NARRATION_TEST_PYTHON="$DEPENDENCY_PYTHON" NARRATION_REAL_SINKS=true \
NARRATION_MEDIA_EVIDENCE_DIR="$OWNED_EVIDENCE_DIR" \
go test -timeout=5m -count=1 -v ./internal/narration \
-run '^TestPostgresNativeChromeRTMPContinuity$'

DURABILITY_TEST_DATABASE_URL="$OWNED_TEST_DSN" \
NARRATION_TEST_PYTHON="$DEPENDENCY_PYTHON" NARRATION_REAL_SINKS=true \
NARRATION_TEN_MINUTE=true NARRATION_MEDIA_EVIDENCE_DIR="$OWNED_EVIDENCE_DIR" \
go test -timeout=20m -count=1 -v ./internal/narration \
-run '^TestPostgresTenMinuteFiveQuestions$'
```

The20-minute value is the test harness deadline for a whole10-minute fixture,
not an increased service/sink timeout. Five-window SIGKILL runs assert persisted
phase before killing the actual Runtime child. A new recovery owner preserves
completed cursor bytes, retires stale effects and admits no automatic replay.
Protected public FORCE tests verify same-key response, changed-body409, SQL
response insertion failure rollback, Stop winning and six lifecycle placements.
202/FAILED proves durable disposition, not asynchronous sink cleanup completion.

## Native media and proof audit

Short: [raw Chrome/RTMP JSON](native-short/media.json.gz),
[recording](native-short/continuity.flv), [raw SQL proof](native-short/sql-proof.json.gz),
[receipt audit](native-short/receipt-audit.json).
The SQL export retains21 commits and84 exact named media receipts. Each commit
has both audio and video for `peer_84f7824830304ceeb26744d810941e2f` AND `rtmp:1`,
matching full identity, range and final marker. Terminal range is
`[2880000,3024000)` at48000Hz, run1/epoch3/generation22. SQL commit statuses are
SEALED5 / ELIGIBLE16; A stores semantic completion via validated observations and
sink receipts, not a fabricated `status=COMPLETED` column value. The completed
semantic document contains20 distinct required facts, STOPPED/FINISHED.

Random long: [raw JSON](native-random/media.json.gz),
[recording](native-random/continuity.flv), [metrics](native-random/metrics.json).
All209 unique Chrome video markers and209 chronological synthetic audio pulses
were observed; all five questions resumed, all200 required narration facts were
accounted for. One exact pending price statement was satisfied by its committed
answer. Repeating current price/stock when a viewer asks again is intentional;
this is narration-ledger coverage, not proof of no repeated spoken claim.
The Go test asserts209 validated completion observations. A full per-commit SQL
export was added later and is retained only for the short run; long raw209 SQL
receipts were **not retained**. The final RTMP source endpoint is30096000 at48000Hz;
31350 audio chunks and15675 video frames were consumed, no queue drops/write
failures or late-video drops. Independent fanout queues remain20/10 and the RTMP
sink's own queues40/20; they were not enlarged. Output-clock idle silence/holds
remain visible in diagnostics and are not claimed as source content.

Five same-Chrome-clock selected-comment proxies: audio P50=3284.2ms,
P95=3300.5ms; decoded video P50=3276.9ms, P95=3288.9ms. These five synthetic samples
are **not busy SLA acceptance**. Audio pulses have no unique audio identifier;
chronological pairing is permitted only with equal complete pulse/video coverage.
RTMP independently reports zero duplicate/regressing audio/video packet PTS;
209 decoded onset pairs have absolute drift P50=21ms / P95=40ms / max=51ms.
Metrics can be regenerated after decompressing the raw JSON:

```sh
"$DEPENDENCY_PYTHON" runtime/tests/narration_metrics.py media.json metrics.json
```

The manifest distinguishes final delivery hashes from native-run launch state.
Long native testing preceded the final App whole-Session retirement hook,
generic-answer hardening and A's final Worker integer-domain fix. Its exercised
price/stock path is unchanged. Short native testing covers that A fix but precedes
the final App hook. Final full Go/race covers the hook. Exact launch source-hash
manifests were not captured for those native runs; final hashes do not replace
them retroactively.

## Retained failures and limits

[burst2](failures/burst-2.log), [burst3](failures/burst-3.log) and
[early soak](failures/early-soak.log) failed required-sink tail proof before C's
source-clock pacing correction. They did not advance an unproved semantic cursor.
[Default Go deadline failure](failures/go-default-timeout.log) is an incomplete
600-second random attempt; it contributes no duration to the successful run.
[SQL export failure](failures/sql-export-column.log) completed short playback but
failed the test on a nonexistent `created_at` column. The export was fixed and
short rerun passed. [Runtime path failure](failures/runtime-path.log.gz) used the
wrong import path; the correct full regression above passed.
[Validator environment failure](failures/validator-environment.log) lacked YAML in
system Python; the dependency-environment validator passed. No failed run is
relabelled PASS.

The default authenticated bound bundle constructs StrictSoulX, whose complete
video staging is unavailable; it fails closed before TTS/commit. The working CPU
bundle is injected by the fixture/library path. CCR-BC-001 is NOT APPROVED.
Default bound production Continuity is therefore **not executable just by enabling
flags**. Real LLM/TTS/SoulX, human naturalness/relevance/fact quality, physical
audibility, official-platform/remote/Windows/transport matrix, busy SLA,30–60-minute
load, global resource admission, production semantic metrics, process resources
and real-GPU stale-frame counter are NOT ACCEPTED / NOT TESTED. Ambiguous-tail
reconciliation/continuation API/UI and automatic safe recovery bridge remain
unimplemented. Product-change tests prove SQL STOPPING/barrier; combined new
captured Session publication after old Runtime cleanup/release is not accepted.
Public browser FORCE + provider/sinks combined acceptance is also pending.
