# Agent 2 验收

验收对象是 `durable-live-1` 独占存储/执行组件及独立共享补丁。正式入口尚未应用补丁，新功能默认关闭。最终统计和原始输出位于 `agent-2-evidence/final/`，以 `acceptance.json` 的退出码为准；初次失败另行保留，不能混算通过次数。

## 可复现命令

准备独立 Python venv，安装 `tests/requirements.txt`、`runtime/requirements.txt`、pytest、pytest-asyncio；运行既有媒体回归还需 numpy、Pillow、av、aiortc。需要本机 PostgreSQL >=16、Redis、Go 工具；不需要 GPU 或云服务。

```sh
python scripts/durable-live/run_isolated_acceptance.py \
  --python /absolute/path/to/test-venv/bin/python \
  --evidence-dir docs/v0.5/agent-2-evidence/reproduction
```

Runner 首先确认 55462 / 56382 没有监听者，再创建 `/tmp/astralive-agent2-*` 独立实例、测试数据库及 owner marker。拒绝使用业务数据库名字或共享实例；故障注入只能操作带 marker 的实例和父测试创建的 Go/Python 子进程。finally 停止自建服务，保留可销毁数据；不读取业务 `.env`，不删除录像、日志或模型。

Runner 执行：

- `go test -race ./internal/durablelive -count=1 -v -timeout 120s`，包含真实 SQL、进程故障和服务停启。
- `go test ./... -count=1`，legacy 环境依赖用例可能 skip，不能据此声称真实 Provider 通过。
- `pytest runtime/tests/test_durable_live_journal.py -q`。
- `PYTHONPATH=runtime python -m unittest discover -s runtime/tests -p 'test_*.py' -v`；真实服务 opt-in skips 单列。
- 冻结契约 validator、既有 v1.1 + v0.5 unittest、临时快照共享补丁回归。

## 接受边界

Go/Python 规范 hash、Schema、真实 PostgreSQL FK/unique/CAS/事务、一次性 START、实际进程 SIGKILL 和 Redis 交付语义是组件验收对象。具名文件 sink 只验证本地 handoff 与 effect 计数。

生产 Guardian 独占凭据/连接、精确文本合成接线、评论实际回答跨进程日志接线、真实 Session 重建、真实 Worker/双 GPU Publisher、Chrome/WebRTC、RTMP 与官方观众端为 **NOT TESTED / 待 Agent 4 集成**。PostgreSQL 本轮为本机 17；16 的部署回归待集成环境验证。

不得将组件通过描述成整场直播已经可靠无缝恢复，也不得宣称外部 exactly-once 播放。未知播放进度以 UNKNOWN 和人工路径呈现。


最终验收源码：`26ebe57b06356cbe83b76055583014947f7c043e`。隔离 PostgreSQL 17.11、Redis 8.10.2、真实 Go/Python 子进程与文件 sink。Durable Go race：35 PASS、0 FAIL、1 helper SKIP；该 helper 已由父进程测试调用。Python Journal 11 PASS；既有 Runtime 159 项，148 PASS、11 opt-in SKIP；冻结 v1.1/v0.5 契约 unittest 17 PASS；全 Go 回归、44 文件 hash validator、临时快照共享补丁检查均退出 0。
