# 08 — 合入 main（本地，经仓库所有者授权）

## 授权与边界

2026-10-20，仓库所有者在本会话中明确授权：“给你所有的权限，可以先合并一点到 main，后续弄好了继续合并，直到全部成功之后推送到主分支”。据此：

- 本地 `main` 已合并，**未推送**。推送在“全部成功”后进行（见下文“推送条件”）。
- `service.py` / `process.py` 的保护哈希按所有者授权登记，审计记录 `docs/v0.5/implementation/protection-changes/RESCUE-GUARDIAN-LIFECYCLE.json` 明确写明**不是 Agent4 独立审核**（`independentAgent4Review: false`）。仍建议 Agent4 事后复核。
- 没有修改 `integration/v05-durable-live`、`feat/v05-output-guardian` 等其他分支引用，也没有修改任何 Agent 目录。

## 合并内容

| 步骤 | 提交 |
| --- | --- |
| rescue ← `origin/integration/v05-durable-live`（`e4292ac`，仅 Agent4 文档） | `0505d67` |
| 保护登记（所有者授权） | `0d0988d` |
| 证据日志 whitespace 属性（沿用 agent-2/integration 惯例） | `b712636` |
| Linux 镜像加 ffmpeg/git；完整回归脚本 | `ad3a741`、`f96dab2` |
| **main ← rescue `f96dab2`**（`--no-ff`） | **`7d56d16`** |

`origin/main`（`7fe5d24`）是 rescue 的祖先，无冲突；合并树与 rescue `f96dab2` 的树逐字节相同（`git diff --cached --quiet` 已验证）。

## 在该合并树上的实际结果（`evidence/main-merge-7d56d16/`）

| 检查 | 结果 |
| --- | --- |
| Guardian v1+lifecycle+v2（Mac） | 219 PASS / 0 FAIL / 1 SKIP（Linux cgroup） |
| 契约 137 | OK |
| validator v1 / v2 | PASS / PASS（313 项保护全部匹配） |
| 生成代码 `--check` | PASS（`3c0c317e…`） |
| `git diff --check` | PASS |
| Go vet | PASS |
| Go race（私有 PG + Redis，`-p 1`） | 228 PASS / 0 FAIL / 52 SKIP |
| Runtime `unittest discover`（`PYTHONPATH=runtime`） | 169 OK（11 skipped）。首次未设 `PYTHONPATH` 时 22 个导入错误，为调用方式问题 |
| gpu_worker（模拟，`.venv-gpusim`） | 21 PASS + live_acceptance 2 PASS。首次缺 torch/PIL 依赖失败，日志保留 |
| frontend `bun install/test/build` | OK |
| school-linux 容器（`ad3a741` 镜像，bridge） | 218 PASS / 0 FAIL / 2 SKIP；`--network none` 仅 WebRTC 1 FAIL（需非回环网卡） |

Durable LIVE：`ASTRALIVE_DURABLE_LIVE_ENABLED=true` 时 Backend 拒绝启动并返回 `OUTPUT_FENCE_UNPROVEN`（`backend/internal/durablelive/release.go`），由 `durableintegration/integration_test.go:401-405` 固定，已包含在上面的 Go race 通过结果中。

## 52 个 Go SKIP 与未覆盖项

- receiver1 36：需要 Agent4 专用数据库标记文件与 PR11 归档（`AGENT4_RECEIVER1_*`）。
- answerstream 8：需要 Agent3 专用 streaming 库。
- 其余：浏览器、owned 子进程助手、显式 opt-in。

## 推送条件（“全部成功”的定义，供你确认）

当前合并是“阶段 1 完成”的状态，已经可以推送，但按你的指示暂不推送。建议的推送门槛：

1. 本文件表格全部保持绿色（每次合并后用 `docs/rescue-out/evidence/run_full_regression.sh` 重跑）。
2. receiver1/answerstream 专用库套件补跑通过（需要复用 Agent3/Agent4 的库配置）。
3. 后续阶段 2–4、6 的 CPU 部分逐个合入并保持绿色。
4. 阶段 5（专用 Linux 隔离主机）与阶段 7（GPU）需要你提供的机器；**不在共享 school-linux 上做 cgroup 变更**。

如果你希望现在就先推送阶段 1，只需确认一句即可。
