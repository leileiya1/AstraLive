更新：本文件下面记录的网络限制已解除，新端口实际连接和恢复成功。新的终止原因是浏览器音画门禁 `BLOCKED — LATENCY`，见 [当前报告](SOULX-LIVE-RETRY-2026-10-09.md)。

# 一小时实测重启：连接预检

状态：`BLOCKED — TRANSPORT`。用户已授权使用新GPU实例执行一小时实测，但当前执行会话网络受限、审批策略never。新实例SSH地址无法解析；school-linux明确返回Operation not permitted。未启动Session，连续验收计时0秒；新GPU硬件、文件和环境均未核实。未保存用户提供的密码。

新连接端口45713；不能沿用20541或假定旧实例文件仍存在。待允许SSH的执行环境可用后，先核对实际GPU/模型/官方commit/已验证独立环境，再验证上次未完成的浏览器严格代际显示、录制音画同步、Public COMMENT与双Sink短测。通过后使用同一Session连续3600秒，记录90/300/900/1800/3600秒检查点、正常Stop和资源清理。

旧阶段A/B结论及归档不覆盖，本次失败不是GPU故障或模型推理失败的证据。详见../streaming/evidence/one-hour-retry-2026-10-09/preflight.json。
