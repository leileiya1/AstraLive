# Staging environment profile agreement

Source: `0ccc25c0cfc0c25cb0f723e04949fcc1e83978a7`, a separate configuration increment after the completed canonical-price source `c076588`. C owns the startup configuration helper and its tests. F owns final merge; D reviews compatibility. No transport/main, frozen DTO/schema/helper, authentication, hash, profile name, memory budget, lease or provider algorithm changes.

D found that enabled Go treated an explicitly empty `ASTRALIVE_SOULX_STAGING_LIMITS_REVISION` as default short, while Python correctly rejected it. Go now uses LookupEnv: only an absent variable selects the original short profile; explicit empty is passed to existing Validate and rejected. Python production parsing already distinguishes absence and empty and is unchanged.

| Staging enabled | Profile environment | Result in both runtimes |
| --- | --- | --- |
| absent/false/0 | absent/empty/invalid dormant value | disabled capture, profile/gate null |
| true/1 | absent | original `staging-short-1`, null gate |
| true/1 | explicit empty or whitespace | startup rejection |
| true/1 | explicit valid short | exact requested short; no implicit GPU-budget promotion |
| true/1 | explicit valid 8s plus reviewed gate hash | exact requested profile/gate |
| true/1 | 8s without gate or invalid profile | startup rejection |

The frozen staging contract §11.1 keeps defaults OFF/short, exact captured profile matching and rejection of invalid capture. This correction implements those existing rules and aligns the actual runtimes; it does not amend the freeze. A settings object/captured BEGIN_RUN does not reread a later environment mutation.

Validation: the actual Go helper invokes the actual Python `StagingSettings.from_env` in an isolated local subprocess. Twelve paired cases, capture equality, default/no-promotion and capture-immutability checks PASS under Go race; five Python capture cases PASS. The fixed baseline `c4ddc43` with only the candidate test overlaid reproduces FAIL for enabled explicit empty (Go accepted, Python rejected). This negative evidence is retained.

Exact immutable-source full module gate PASS: Go tests/race/owned PostgreSQL migrations/authentication/ownership/outage and existing interactions, Runtime 274 tests (12 skips), frontend 40 tests/build. Evidence/commands/hashes are under `evidence/agent-c/staging-explicit-profile/`. Reproduce using the recorded `module_gate.py --source 0ccc25c0cfc0c25cb0f723e04949fcc1e83978a7` arguments, or run `DURABILITY_TEST_PYTHON=<media-python> go -C backend test -race ./internal/narration -run 'TestStagingEnvironmentGoPythonAgreement|TestStagingCaptureFrozenProfiles' -v -count=1` and `PYTHONPATH=runtime:runtime/tests <media-python> -m unittest test_staging_runtime.CaptureTests -v`.

This local continuation made no SSH/GPU calls. New native GPU/Chrome/RTMP/business Golden acceptance: NOT TESTED. Existing default-off behavior remains unchanged. Operator correction for an invalid empty profile is to unset it for the original short default or explicitly set a valid reviewed profile/gate; do not automatically select a larger profile. Reverting this helper would restore the known Go/Python mismatch, so keep it documented if rolling back.
