# ISSUE-007: One-hour browser-connected soak lost Ubuntu Runtime host

Status: **OPEN — ONE-HOUR ACCEPTANCE FAIL**. Discovered 2026-10-07 during the independent 60-minute acceptance run.

Follow-up at 02:22 UTC: the user reported that Ubuntu had briefly lost network access and is now reachable. Read-only host verification confirms the previous boot's journal ended at approximately 10:13:01 CST (02:13:01 UTC) and a new boot began at 10:21:24 CST. This confirms a host boot boundary coincident with the failed run; the journal excerpt does not establish why the host restarted or whether network loss was the initiating cause. The failed run remains FAIL. A new run, if made, must have separate evidence.

The Mac Chrome peer stayed `connectionState=connected` and `iceConnectionState=connected` through the 02:13:05 UTC sample. At 02:13:35 UTC, before normal Session Stop, it reported `connectionState=failed` and `iceConnectionState=disconnected`. The browser monitor had run 3,632 seconds and observed 87 completed business cycles with growing audio/video counters through the preceding sample. The final browser sample did not meet the continuous-connection gate.

Near that boundary, the minute resource sampler's Ubuntu SSH probe timed out at approximately 02:13:09 UTC, and the long-lived SSH process running Ubuntu Runtime later logged `Connection to 10.65.13.94 closed by remote host`. Subsequent SSH probes closed or timed out; the local Go/Frontend stack was then cleaned up by its supervisor. The Runtime driver was terminated (exit 143) before it could write its final summary or perform its own Stop; the browser runner attempted public Stop, but cleanup could not be verified. Redis contains no `SESSION_STOPPING` or `SESSION_ENDED` for this Session. The initiating cause of the host/SSH loss is **not established**. Do not infer an application crash or spontaneous reboot without host logs.

Evidence: [browser media and failure](../evidence/browser-connected-soak-60m.json), [60-second resource samples](../evidence/browser-connected-system-60m.json), [Redis audit](../evidence/browser-connected-audit-60m.json), [Tool proxy](../evidence/browser-connected-runtime-tool-60m.jsonl), [Runtime log](../evidence/browser-connected-runtime-60m.log), [Backend log](../evidence/browser-connected-backend-60m.log), and [driver cycles](../evidence/browser-connected-driver-60m.jsonl). The 30-minute accepted evidence remains intact.

Acceptance impact: **FAIL**. A 3,600-second browser monitor duration alone is insufficient because ICE failed before normal Stop, and `STOPPING → ENDED` plus Runtime cleanup were not proved. Do not mark `ASTRALIVE V0.1 CORE MVP ACCEPTED` from this run.

Follow-up: preserve host boot/network logs if the host becomes reachable, distinguish reboot/network/SSH/service failure, and repeat an uninterrupted one-hour acceptance only after the cause is addressed. Production module changes require separate authorization and are outside this acceptance session.
