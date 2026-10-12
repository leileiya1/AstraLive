# A scoped review: captured CNY speech policy

Decision: scoped ACK for immutable source `99382b1fcaed3eb7e8ec8383016400241f2edf7c`; production change `0adaf42fbee52ec543f55a29adbeb7c5ef6374b0`. No new P0/P1 found in this delta. This review did not modify C, F, production code, the database contract, or SSH/GPU hosts.

## Findings

- `Drive` reads immutable BEGIN_RUN staging configuration and fresh owned product facts inside its existing business transaction. Only enabled staging with currency exactly CNY changes price speech to `人民币` + the unchanged SQL decimal string + `元`. Original amount, price fact ID, product hash/version, and stable command creation remain intact. USD and flags-off preserve their previous text.
- `ANSWER_PREPARED` retains revision/run/Stop/fresh-snapshot validation. Enabled staging additionally checks the immutable prepared answer text and fact IDs against a fresh deterministic renderer before saving/enqueuing the answer in the same transaction. No request fingerprint, command ID, receipt state, recovery authorization, UNKNOWN, SQL migration, A journal hash, or original contract change occurs in this delta.
- Audit instrumentation adds only encoded packet byte count/hash and browser performance time origin. Native RGB, decoded RGB, emitted RGB and ordered H264 hash domains remain distinct. The production TCP client validates the mandatory packet hash before the observer; the observer's compatibility fallback is not the protocol validator. Audit files contain hashes rather than encoded media or credentials. Viewer audibility is still unproven.

## Independent validation

Source was read from an immutable `git archive`, without using C's working tree. Owned local PostgreSQL 17.11 served the focused Go `-race -count=1` test command recorded in `result.json`: four top-level tests PASS, including the five real-PG CNY policy cases (success, amount forgery, fact forgery, currency change, flags-off) and four capture/restart mismatch cases. Runtime staging module: 10 CPU/software-fixture cases PASS. Owned PostgreSQL was stopped successfully.

The policy fixture explicitly creates a Suspended narration and earlier-command resolution assumptions, then calls C.Project directly. It is a real PostgreSQL transaction/policy test, **not** authenticated A journal/native GPU, actual audience playback, or full end-to-end recovery acceptance. These results do not substitute for F's business Golden run or C's separately reported full module gate.

The first infrastructure attempt failed because the generated macOS UNIX socket path exceeded PostgreSQL's 103-byte limit. Raw startup failure and result are preserved. The same archived candidate then passed using a TCP-only owned PostgreSQL instance. The initial system-Python extraction attempt rejected the `filter` keyword before tests; the declared media-venv Python was used for the actual archive and gates.

## Compatibility limitation

Already persisted, enabled-staging CNY prepared commands containing the old currency-code text may fail the new fresh text check. Do not mutate durable commands or replay uncertain media to bypass it. This is fail-closed behavior; no unauthorized replay or speech retry is introduced. The scope does not establish human pronunciation, 10-minute narration, real GPU/browser/RTMP, or latency targets.

## Reproduction

Archive the exact SHA; create an independently owned local PostgreSQL database and set DURABILITY_TEST_DATABASE_URL. Run the exact Go selector recorded in result.json from archive/backend, then `PYTHONPATH=<archive>/runtime:<archive> /private/tmp/astralive-f-media-venv-1/bin/python -m unittest discover -s tests -p test_staging_runtime.py -v` from archive/runtime. Stop the owned database. No provider secrets are required for these focused checks.
