# ISSUE-004: Backend 附带 Go Mock Runtime 违反 v1.1 队列契约

- Status: CLOSED (2026-10-06, Contract v1.1 Integration Acceptance)
- Severity: P1（关闭前）
- Module: backend
- Reproduction: 旧 `backend/cmd/mock-runtime` 对 Context/source 与 priority/FIFO 缺少契约校验及队列实现。
- Expected: 仓库仅有一个受支持的 Contract Mock，且遵守 v1.1 行为。
- Actual before fix: Backend Go Mock 与 `integration/mock_runtime` 并存，Go Mock 以单个 active Utterance 覆盖当前讲话。
- Resolution: Backend Go Mock 实现文件已移除；`backend/cmd/mock-runtime` 仅是空目录，没有 Go package、可执行命令或受支持的启动入口。Backend README 和 Compose 指向 `integration/mock_runtime`，其 Dockerfile 只复制该 Python Mock。
- Verification: `go list ./cmd/...` 只返回 `astralive/backend/cmd/server`；`tests/test_acceptance_guards.py` 检查唯一 Mock 路径和受支持文档/Compose；`tests/test_contracts.py` 对 Python Mock 与 Real Runtime 执行相同 priority/FIFO 场景，通过。
- Contract Reference: `contracts/CONTRACTS.md` §8.1/8.3、§12；`architecture/ARCHITECTURE.md` §8。
- Suggested Fix: 已完成；勿重新增加独立 Mock 实现。
