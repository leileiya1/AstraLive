# Agent 2 证据索引

- `final/`：最终代码的完整隔离验收；所有命令、退出码和原始输出在 `acceptance.json` 与文本中。
- `initial-isolated-run/`：首次完整隔离运行失败，子进程解释器误解开 venv 符号链接，未到达 PLAYING；禁止算作通过。
- `venv-diagnostic-run/`：加入诊断后确认是全局 Python 缺少 httpx；保存原始 traceback，修复为保留 venv 入口，而非扩大 timeout。
- `pre-audit-pass/`、`fsm-audit-pass/`、`semantic-audit-pass/`：中间代码版本的通过记录，不能替代 final，也不累计成连续运行时长。
- `runtime-missing-dependencies-initial.txt`：初次旧 Runtime 回归缺 numpy/Pillow/av 的环境失败；随后仅在独立 venv 补齐依赖。
- 其余 development 文本只供追查阶段结果，以 final 为交付依据。

测试 PID、临时目录和 test IDs 均为隔离资源。没有生产凭据、云 GPU、实际 Session、用户数据或观众端验收内容。最终 runner 在 finally 停止自己创建的 PostgreSQL/Redis，保留临时数据供人工核查；未删除任何实际业务文件。
