# durable-live-1

这是 main `cf6540bdcc788c037929836480812dfaa78362a2` 的新增设计契约，不修改 Frozen v1.1，也不替代实验分支的 `v0.5-frozen-1`。实现、权限与事务条件见 [架构](../../../docs/v0.5/ARCHITECTURE.md)、[执行合约](../../../docs/v0.5/DURABLE-EXECUTION-CONTRACT.md)、[交接](../../../docs/v0.5/AGENT-OWNERSHIP.md)。

- `schema.json`：JSON Schema 2020-12；根是RuntimeCommand，其余对象通过 `$defs` refs验证；所有依赖本地闭包，无网络解析。
- `protocol.json`：操作、HTTP目标/路径/角色、请求响应schema refs、成功状态和错误码。内部RPC统一POST（只读query/restore无副作用），不接浏览器cookie。
- `state-machines.json`：合法转换与guard标识；guard真实条件以STATE-MACHINES.md为准。
- `examples/objects.json`：稳定对象和SCRIPT/COMMENT示例。
- `examples/protocol.json`：每个operation完整请求/响应；各例子是独立快照，不是按文件顺序执行的集成日志。
- `examples/hash-vectors.json`：跨Go/Python规范字节与sha256 golden vectors。
- `baseline-sha256.json`：既有冻结契约/DTO、migration及明确保护的Runtime文件哈希，防止设计PR混入行为变更。

验证（在仓库根目录）：

```sh
python3 -m pip install -r tests/requirements.txt
python3 scripts/validate-durable-live-contracts.py
python3 -m unittest tests.test_durable_live_contracts -v
```

fixture validator还检查scope、计划顺序、文本/命令hash、全required sink范围。它不证明实际身份授权、SQL原子性、Runtime输出隔离、生产者证据真实性或外部audibility，后者必须由实现与真实验收证明。baseline哈希文件不得在功能开发中自动重新生成以绕过freeze；实施Agent按owner新增文件，集成CCR另行批准保护文件变更。
