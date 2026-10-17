# Agent 4 review — PR #9 and PR #10 (2026-10-17)

Overall: **ASTRALIVE V0.5 BLOCKED**. Current worktree/branch retained; no new Git worktree, no main merge, no durable LIVE enablement, no GPU run. Temporary git-archive copies were used for pinned pre-merge review only.

## PR #9 — ACK withheld

Reviewed head `4f4c95278e581bccc025323ed8534d0b2db1023e`, normative code ancestor `c2f8c65304ece65f2818cdd828f38091b787e552`. Independently recomputed all 12 normative file hashes and digest `aff229823418408e843d962e332ba3c8f71e20d5e25465bf54f5b3d37d5e4744`. Candidate validator and 36 combined contract tests passed. Candidate was not merged or registered.

[Explicit Agent 4 blocking review](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6227008824):

1. Normal slow LLM ordering is rejected: prepare/start unit1 → confirm unit1 drain → unit2 arrives → prepare unit2 with current revisions/chain returns ANSWER_GAP. Normative paragraph 11 and oracle line 86 require previous unit STARTED, excluding an already proven DRAINED unit. Allow same-live-executor preparation after a reliable drain, retaining all CAS/window/UNKNOWN/authority guards; test the prepare/drain race. No replay/new Turn is acceptable.
2. Specify consumed Grant lifetime across Permit/fact renewal. The immutable Grant pins permit/fact observation and an example expires at 800ms, while a unit may last 6s. Define whether that expiry is a once-only consume/start deadline or a continuing output deadline and how fresh Permit/FactObservation relates to an already consumed Grant. Require a >1s unit trace with renewal, old-artifact/expiry/ACK-loss denial, without minting or replaying execution authority.

Single global START, atomic unit1 grant, false/null duplicate grants, exact committed text/hash, one Turn, version-isolated route/body/stored revision and conservative UNKNOWN are retained requirements. Added lost-continuation-ACK probe confirms false/null and globalStartCount=1. Existing Runtime callback is still v1; no actual v2 executor, migration or cross-process v2 implementation has passed. Current real v1 ASGI handler rejects v2 body with 422 and unregistered v2 route with 404 before any Journal/media callbacks; this CPU handler probe is not a new v2 service test.

Agent 2/3 ACKs and Agent 1 final approval remain required; this Agent 4 blocking opinion supplies no ACK. Any normative change needs a new digest and re-review. Active revision remains durable-live-1 and COMMENT fail-closed.

## PR #10 — disabled stage integrated

Reviewed and merged original head `84738b37c2ee39cc4b8f3a1d449802171ba0a7e0` via `a286198d2a1ef46a2e197995756b4447cf662806`. All original 40 files are additive. The current worktree now contains independent Room Guardian, SQL authority reader, publisher/decoder/supervisor/RTMP relay, WebRTC peer owner, private Unix adapter, templates and original evidence. No production entrypoint imports/enables it.

Source review covers authenticated CONTROL/producer separation, run/Session/epoch/output binding/Attempt/generation matching, SQL session advisory lock, short local/child deadlines, publication-secret custody, real server kick/absence observation, startup closed, fsynced Stop barrier, stale process/pipe identity and all-required completion refusal. The current private IPC/SQL guard is v1 Attempt-scoped; it is **not compatible with the proposed v2 artifact/grant guard without further work**.

Pre-merge pinned archive tests: 22 PASS with dedicated PG/MediaMTX. First post-merge suite: 21 PASS / 1 FAIL. The failing SIGKILL case got supervisor exit74 from group-cleanup EPERM, rather than expected70. The original failure, JUnit and command are retained. An independent owned-process probe reproduced Darwin EPERM for an unreaped zombie-only group; no test expectation or timeout was relaxed.

Corrective commit `5fb16e6315b56ad8c5398e4417456b21d4c7eaff` adds a complete process-group census only after EPERM. No live members may remain; inaccessible/unknown census still exits74. It never signals census-discovered PIDs. Three tests distinguish live owned group, actual unreaped zombie group and permission-denied census. Original three SIGKILL/restart scenarios plus the whole suite now give **25 PASS**. Scope is local synthetic CPU media, real isolated processes/network sinks/SQL, not deployed production isolation.

## Evidence and acceptance layers

Raw commands, pre/post/final JUnit, exact source manifests, resource/environment data, original failure, digest verification and reproducible review probes: `evidence/agent-4/pr-review-2026-10-17/`. Final full regression: `final-regression/acceptance.json`; final Guardian command: `pr10-final-command.json`. Tested source is `5fb16e6315b56ad8c5398e4417456b21d4c7eaff`; subsequent changes are reports/evidence only.

- Go and race: each 142 top-level PASS / 0 FAIL / 3 documented SKIP on dedicated PG/Redis; vet passes.
- Runtime: 158 PASS / 11 explicit opt-in SKIP; Journal pytest 11 PASS; frozen contracts/schema 17 PASS; frontend 45 PASS/build passes.
- Guardian final: 25 PASS / 0 FAIL / 0 SKIP; real local finite zero-origin RTMP decode, Unix adapter, Peer shutdown, permit/PG/Stop faults and three SIGKILL/restarts. Required WebRTC completion remains UNKNOWN.
- PR9: 36 contract/oracle PASS and candidate hash/schema validator PASS; two substantive review blockers remain. No v2 SQL/race/executor/media PASS.
- GPU/Chrome/external platform/official viewer: NOT TESTED. Busy-speaker latency samples remain zero.

## Remaining release blockers

Production OUTPUT GUARDIAN remains **BLOCKED** / OUTPUT_FENCE_UNPROVEN. Linux separate-UID/container egress and secret/port isolation have not been exercised; existing external publisher keys/connections have not been revoked/proven isolated. Formal Session/Binding/registrar/checkpoint/Generation/Credit bridge is not connected. Finite per-Attempt publishing does not support the required short segments or continuous Session PCM/PTS origin; nonzero initial PTS rejects, and the 400ms case stays UNKNOWN. Trusted decoded WebRTC range receipt and external ICE/Chrome are missing. The Room service's retained stopped/used-attempt identities and recordings also need a durable, bounded retention/lifecycle plan before long-running enablement; do not clear Stop/dedup state merely to bound memory.

The production guards in Backend and Runtime, frozen v1/v1.1 contracts, original Session/output pipeline and GPU/Worker wire/PTS/Credit remain unchanged. PR #10's code merge does not change any release-gate status to production PASS. See RELEASE-GATES.md; final conclusion stays BLOCKED.
