# ISSUE-001: COMMENT 曾无法到达 Runtime（v1.0，已解决）

- Severity: P1（历史）
- Module: backend
- Reproduction: v1.0 向 `POST /api/v1/dev/platform-events` 发送 COMMENT，得到 `422 INVALID_ARGUMENT`。
- Expected: 标准化为 `source=PLATFORM_EVENT`、priority 80、`INTERRUPT_LOWER_PRIORITY` 的 Utterance。
- Actual: v1.0 返回 422；Contract v1.1 和 Backend Migration 已修复。2026-10-06 集成 E2E 在 Full Mock、Real Runtime + Mock AI、轻量 Avatar 链路观察到 202、Runtime QUEUED 和 COMPLETED；无活动 Session 为 409。
- Contract Reference: `contracts/CONTRACTS.md` §7.9。
- Suggested Fix: 无；保留作历史记录。
