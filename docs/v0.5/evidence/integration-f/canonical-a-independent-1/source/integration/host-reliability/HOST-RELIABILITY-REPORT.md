# Ubuntu Live Host Reliability Investigation

Collected 2026-10-07 from `ubuntu-server`, the Ubuntu RTX 2060 Runtime host. Host timezone is CST (UTC+08:00); incident times below are **UTC**. No AstraLive business code or Ubuntu configuration was changed.

The incident boot is **`045b841be4de482b9f72c9c515c2d0d9`**. At collection time it was `-3`, so using `journalctl -b -1` would have inspected the wrong boot. The next boot is **`8e9df85f6f9e466db8e710e08b055374`**. All previous-boot searches below used the explicit incident boot ID.

## Confirmed Facts

- [Boot history](boot-history.txt): incident boot began **2026-10-06 23:59:26 UTC**, its journal ended **2026-10-07 02:13:01 UTC**, and the next boot began **02:21:24 UTC**. `who -b` and `uptime -s` show the **later current boot at 05:55 UTC**, because the host rebooted again after the incident. `last -x` is not installed. The boot list, not `last`, establishes the boundary.
- The incident [full journal error extract](previous-boot-errors.txt) ends with ordinary service status requests at **02:13:01 UTC**. The [kernel journal](previous-boot-kernel.txt) ends earlier, at **02:12:05 UTC**, with a routine UFW block. No orderly `systemd` reboot/shutdown sequence, kernel panic/oops, fatal watchdog, or power-button event appears near the incident boundary. The next boot kernel logs **EXT4 orphan cleanup**, consistent with an unclean stop; this does not identify its cause.
- The [local system sampler](../evidence/browser-connected-system-60m.json) last reached Ubuntu at **02:12:08 UTC**, then its **02:13:09 UTC** sample timed out over SSH. The [browser trace](../evidence/browser-connected-soak-60m.json) remained connected at **02:13:05 UTC** and sampled `failed/disconnected` at **02:13:35 UTC**. The [network/SSH evidence](network.txt) shows a successful SSH session at **02:12:49 UTC** and no NetworkManager carrier loss, DHCP failure, or disconnect entry near 02:13. NetworkManager's last recorded event for this boot was a successful Wi-Fi connection at **01:17:50 UTC**.
- [OOM evidence](oom.txt): no OOM kill or `Killed process` entry in this boot's full journal. Current RAM is 30 GiB with 26 GiB available; 8 GiB swap is present and unused. Current readings cannot establish memory state at 02:13. The last test sample showed Runtime RSS **1,266,120 KiB**.
- [NVIDIA evidence](nvidia-errors.txt): no **`NVRM: Xid`** in this boot's kernel journal. The `r8169 ... XID 541` line is a **Realtek network-controller identifier**, not an NVIDIA error. NVIDIA startup logged an ACPI callback failure and an I²C timeout at **23:59:31–32 UTC**, over two hours before the incident; no causal link is established. The last sampled GPU temperature before loss was **43°C** with 4 MiB VRAM used. `sensors` is not installed. Current sysfs temperature readings were CPU 67.25°C, NVMe 35.85–39.85°C, Wi-Fi 48°C, and integrated AMD GPU 44°C; these are **post-reboot** measurements.
- The root filesystem is **34%** used (`148G/468G`); the incident kernel journal contains no I/O error, EXT4 error, or NVMe timeout/reset near the boundary. Sleep, suspend, hibernate and hybrid-sleep targets are all **masked and inactive** now. The previous boot has no suspend/hibernate entry near the boundary. No configuration change was needed.
- The next boot's kernel startup has **no reported AMD previous-reset reason** for this specific 02:13 event. The incident boot's startup *does* record `an uncorrected error caused a data fabric sync flood event`; that describes the **earlier** reset preceding the incident boot, not the 02:13 reset. Later boots also occurred, with different reset-reason messages. This pattern warrants separate hardware/firmware review but cannot be assigned as this incident's root cause.

## Suspected Causes

- **LIKELY unclean host stop/reset:** abrupt journal ending, missing normal shutdown chain, boot boundary, and subsequent EXT4 orphan cleanup support this. The initiating mechanism remains unconfirmed.
- **UNCONFIRMED hardware, firmware, power, thermal, or watchdog fault:** a previous AMD data-fabric sync-flood reset reason raises concern about host-level reliability, but belongs to another boot. No matching machine-check or thermal shutdown entry was captured for 02:13.
- **UNCONFIRMED external network/tunnel failure:** there is no NetworkManager loss recorded before the journal ends. The network might have vanished as a consequence of the host stop, or a separate network failure might have preceded it without a journal entry.

## Ruled Out

- A **network-only** explanation for the whole incident: a new boot is independently documented.
- A logged **OOM kill**, **NVIDIA `NVRM: Xid`**, **normal systemd reboot/shutdown**, **suspend/hibernate transition**, **near-boundary disk I/O error**, or **NetworkManager disconnect** as the observed trigger: none appears in the retained journal for the incident boot. Their absence does not rule out an unlogged failure or lost journal writes.
- GPU overheating **at the last sample**: 43°C at 02:12:08 UTC. This does not rule out an abrupt later thermal or power event.
- Unattended upgrades as a **documented** trigger: only the normal unattended-upgrades shutdown service startup is present; no update-triggered reboot sequence appears near 02:13.

## Root Cause

**UNCONFIRMED — ROOT CAUSE UNCONFIRMED.**

1. **Why did the network first become unreachable?** The first measured SSH failure was the 02:13:09 UTC sampler timeout. There is no preceding NetworkManager carrier/DHCP loss in the available host journal. It is **LIKELY** that the host stop affected connectivity, but the ordering within the 02:13:01–02:13:09 UTC gap is not observable. Network cause: **UNCONFIRMED**.
2. **Why did Ubuntu enter a new boot?** The previous boot stopped without an orderly shutdown record and the next boot required EXT4 orphan cleanup. The specific trigger—power, firmware, CPU/RAM, watchdog, hard reset, or another mechanism—is **UNCONFIRMED**. No evidence attributes it to AstraLive.

## Recommended Fix

1. Preserve the explicit boot-ID journals and any firmware evidence before rotation. Check `/sys/fs/pstore`, kdump, BMC/firmware event logs, and UPS/power history with appropriate host access. `/sys/fs/pstore` was permission denied to the unprivileged SSH account; no privileged inspection or host change was performed.
2. Review the earlier AMD `data fabric sync flood` reset separately, then correlate firmware/BIOS, RAM diagnostics, power adapter/battery, CPU and GPU thermal history, and reset-reason registers with the **02:13 UTC** stop. Treat the earlier message as a lead, not proof of this incident.
3. If recurring abrupt boots continue, reproduce with independent host-only monitoring and a local console or out-of-band recorder. Capture CPU/RAM/temperature/power, journal tail, boot ID and network carrier around each event. Apply a hardware or configuration fix only after a matching fault is identified.
4. Do not modify AstraLive Runtime to hide a host loss. The [one-hour acceptance report](../ONE-HOUR-SOAK-REPORT.md) also documents a separate application failure on a later retry; that belongs to a different investigation.

## Reboot Prevention / Monitoring

- Retain/forward kernel, SSH, NetworkManager, OOM, thermal, machine-check, NVIDIA Xid, and shutdown records to another machine so they survive an unclean stop. Check existing retention policy before changing it.
- Monitor UTC heartbeat **and boot ID** from outside the host, plus SSH reachability and Wi-Fi carrier separately. A network alarm alone must not be labeled a reboot.
- Keep the already masked sleep/suspend/hibernate targets as recorded; no repeated masking is needed. The current root filesystem has ample free space; no disk cleanup is indicated.

## Safe To Retry One-hour Soak?

**NO.** The incident's host reset mechanism remains unconfirmed, further boots occurred on the same day, and the failed one-hour run cannot be counted. First establish host stability and review the host-level evidence above. Reassess the separate application failure before a new acceptance run.

## Saved Evidence

| File | Scope |
| --- | --- |
| [boot-history.txt](boot-history.txt) | `who -b`, `uptime -s`, recent `journalctl --list-boots`; `last` missing. |
| [previous-boot-kernel.txt](previous-boot-kernel.txt) | Full incident-boot kernel journal, UTC, redacted. |
| [previous-boot-errors.txt](previous-boot-errors.txt) | Incident-boot priority errors, focused searches, final journal lines. |
| [nvidia-errors.txt](nvidia-errors.txt) | NVIDIA/NVRM lines; explicit distinction from Realtek XID 541. |
| [oom.txt](oom.txt) | OOM search and current memory/swap. |
| [network.txt](network.txt) | Previous-boot NetworkManager/SSH tail and current NIC status, redacted. |

IP and MAC addresses, username, hostname, and SSH key fingerprint were redacted from saved extracts. Boot IDs and UTC timestamps were retained for correlation.
