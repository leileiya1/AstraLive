# Stop with an outstanding staged pose ACK

Production candidate: `43771588c9b988fa1d30ad99e3fab7dafc6db6ba`. Only Runtime staging client private task scheduling, safe receive failure diagnostics and C-owned CPU tests change. A reviewed this exact source and found no blocking frozen-contract issue. No public DTO, receipt, Worker, sink, Go, lease, cap, timeout, feature default, Stop-proof cache or absence policy changes.

## Evidence and first cause

F's real hour7 source88a6824 ran3600.1805s and completed25 answers/resumes. Normal Stop remained STOPPING with its binding retained:322 commits COMPLETED and one UNKNOWN. The preserved Runtime traceback identifies STAGING_CONFLICT in receive_loop's unmatched ACK branch while Stop awaited StageFenced. The original ACK subtype was not logged, so it cannot be retrospectively declared observed as a pose ACK. This is unrelated to the old absence-proof cache limitation.

An immutable archive of the exact old88 source plus a new test-only CPU fixture reproduces the same receive-loop traceback: pose exchange sends its captured proof, its awaiting caller is cancelled, exchange removes its pending correlation, and the actual later pose ACK is rejected as unknown during Stop. This is real loopback TCP with a frozen-DTO software peer, not a native Worker/GPU test. Old source fails with STAGING_CONFLICT; new source passes the same positive case. Original real evidence remains unchanged at `/private/tmp/astralive-f-real-hour-tcp-7`.

## Minimal scheduling correction

The current Stage retains one private pose exchange task. Caller cancellation still fences publication immediately but does not cancel the bounded request or orphan its ACK correlation. Only that captured task may finish against the original exact identity and pose fingerprint. Its actual ACK is validated and applied to stage.pose before StageCancel/Release uses the consumed prefix. Release first fences, stops new renewal and drains existing bounded renewal and captured pose work. No new pose is planned, no command is replayed and no sink consumption is invented.

A post-arm StageReleased UNKNOWN/nonreusable remains UNKNOWN/nonreusable, even when it proves physical native cleanup. That safe boundary can close the physical adapter but never becomes a media COMPLETED receipt or permission to reuse the Worker. Foreign/unknown ACKs, wrong proof, late deadlines and uncertain cleanup stay failures and retain the binding. The existing pose ACK timeout5s, writer timeout2s, grant timeout2s, Cancel timeout10s, Release timeout15s and Session Stop budgets remain unchanged; the whole cleanup is not claimed to take only5s. A Stop budget exceeded can still conservatively remain pending.

Safe receive diagnostics record only static message type/code, pending/answered existence and fenced/released booleans. No packet body, pose ID, lease/token, Provider text or raw exception is logged; failure before a message is returned is classified OTHER rather than borrowing the previous packet type.

## Verification

39 focused CPU tests passed in26.926s: actual loopback cancelled-pose ACK drain→Cancel→UNKNOWN/nonreusable physical Release→adapter Stop/close; foreign identity, unsolicited ACK and wrong proof rejection; actual missing ACK expiry at the original5s with no false Release/reuse; old renewal, heartbeat, bound lifecycle and staging Runtime/TCP regressions. Baseline failure, final logs and safe original hour trace are recorded in C-owned evidence. The exact source full immutable software gate passed: owned Go/PostgreSQL/race/auth/outage exit0 (141.252s); Runtime314 tests with12 skips exit0 (39.810s); frontend40 tests/build exit0. [Evidence manifest](../../evidence/agent-c/pose-stop/manifest.json) records the actual commands, outcomes and raw-log hashes. New real GPU/Chrome/RTMP/hour Stop acceptance is NOT TESTED by C; F alone runs that verification.

Rollback disables staging for a newly authorized Session or reverts this private scheduling source; captured/UNKNOWN commands are never rewritten or blindly replayed.
