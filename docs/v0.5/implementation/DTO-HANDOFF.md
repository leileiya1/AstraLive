# Agent4 v2 wire implementation handoff

本轮交付唯一生成器及Go/Python生产契约包，未接入生产路由、Session、SQL或媒体。Source baseline为 `e98d8cf53d1aa5518f9c908785b7a5feae5117f8`；本次DTO完整交付SHA由Agent4在PR8定版通知发布，消费者固定该SHA，不从浮动main或其他Agent复制Schema。唯一维护者仍为Agent4。

冻结来源保持 `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`，22文件digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。原manifest与22文件无字节变更。生成器先验证固定manifest自身hash、22文件hash和总digest，再读取Schema/Protocol生成；失败不写输出、不刷新冻结文件。

## 生成与维护

```sh
python3 scripts/durable-live/generate_v2_wire.py
python3 scripts/durable-live/generate_v2_wire.py --check
```

输入为唯一冻结规范；实现模板在 `scripts/durable-live/templates/`，只由Agent4维护。输出为 `backend/internal/durablelivev2/wire/` 和 `astralive_contracts/durable_live_v2/`；不要手改生成文件，也不要改旧durablelive DTO/spec/生成器。`generated-manifest.json`列出每个生成文件hash。`--check`检测文件缺失/手改/额外未登记的Go或Python模块；手写Go测试与testdata不属于生成输出。工具版本见 `scripts/durable-live/v2-wire-toolchain.json`；生成器/SDK运行依赖仅标准库，gofmt使用记录的Go版本保证逐字节一致。已有Go模块锁和v1测试依赖不变。

132个冻结definitions全有具名类型，源中的两个alias保留alias；数组内嵌对象另生成 `AnswerLifecycleTraceHandoffsItem` 具名辅助类型，**不是新规范definition或新wire字段**。DTO字段无RawMessage/any/dict回退；内部Schema解释器与canonical utility使用私有JSON树，不是可任意扩展的传输DTO。

## Go使用

```go
import "astralive/backend/internal/durablelivev2/wire"

// 这些metadata来自已认证的私有transport/router；SDK不负责认证。
ctx := wire.RequestContext{
    Role: wire.RoleOutputGuardian, Target: wire.TargetBackend,
    Method: "POST", RouteTemplate: wire.PathCommitReceiverConsume,
}
msg, err := wire.DecodeRequest(wire.OpCommitReceiverConsume, ctx, rawBody)
if err != nil { /* 映射到冻结错误响应，不记录rawBody */ }
req := msg.(*wire.CommitReceiverConsumeRequest)
_ = req.RuntimePrincipalID
body, err := wire.EncodeRequest(wire.OpCommitReceiverConsume, ctx, req)
_ = body // 仅发往私有transport；不要记录wire正文。
```

`Decode<Type>`返回具体指针；`Decode(schemaName, bytes)`返回只含生成DTO的Message。每个生成类型也实现严格 `UnmarshalJSON` 与验证型 `MarshalJSON`；`Encode/Decode`为独立definition工具，最大9MiB，实际接口须用operation wrapper执行262144-byte控制/9437184-byte媒体限制与角色/target/method/route模板匹配。`ReadRequest`在读取前校验metadata，并仅读取操作上限+1；调用方提供网络读超时。

所有字段required：缺失拒绝；nullable字段为 `*T`，nil必须编码为显式null；空数组应构造 `[]T{}`，nil slice编码null会按Schema拒绝。0/false不省略。失败解码不改变已有对象，显式null清除旧指针。`LookupOperation`返回副本，不可修改全局表。传入未登记的嵌入wrapper不是合法DTO，Encode拒绝。

## Python使用

仓库根目录在PYTHONPATH时可直接import；未来Runtime/Guardian镜像COPY和包部署由Agent4统一处理，本轮不改Docker/生产launcher。

```python
from astralive_contracts import durable_live_v2 as wire
op = wire.OPERATIONS['ReceiverConsume']
context = dict(role=op.roles[0], target=op.target,
               method=op.method, route_template=op.path)
request = wire.decode_request(op.id, raw_body_bytes, **context)
assert isinstance(request, wire.ReceiverConsumeRequest)
outgoing = wire.encode_request(op.id, request, **context)
```

消费实际transport派生的context，不得以JSON中的角色/Generation等值代替认证权威。模型是frozen/slots dataclass，数组为tuple；required nullable显式传None，没有用默认值把omitted补成null。构造器同样严格校验，不把bool、float、numeric string转换为整数。`decode_response/encode_response`对照成功status或该operation允许的错误code/status；WireError是内部诊断，handler必须映射冻结协议错误，不能把所有内部字符串原样发送为新wire错误码。

## Secret、Hash与边界

Go fmt `%v/%+v/%#v/%q`及slog LogValuer默认脱敏；Python DTO repr/str脱敏，consumeTicket为不透明SecretString，单独repr/str/f-string脱敏，普通json.dumps不能序列化其明文。将同一typed ticket从首次响应传给下一请求字段，无需转普通字符串。**Encode、MarshalJSON、canonical_json都是有意的wire/plaintext序列化，不能作为日志API；显式转成普通字符串/字节或绕过SDK自行JSON记录不在脱敏承诺内。** 不缓存true响应或ticket明文。

跨语言canonical工具拒绝float/exponent/unsafe integers、重复键和非法Unicode，保留原中文/组合字符，不做NFC或HTML改写。`CanonicalJSON/DigestJSON`（Go）、`canonical_json/digest`（Python）遵守13个Golden Vectors。它们计算精确字节，不证明Artifact断言完整、事实新鲜、源可信或签名有效。`VerifyAnswerArtifactHashes`（Go）/`verify_answer_artifact_hashes`（Python）按冻结公式显式验证正文Hash与descriptorHash，中文正文/两个Hash篡改均拒绝；在持久化/执行边界必须调用，结构decode本身不是Hash/事实验证器。

解析器对未知/重复键、类型/const/enum、allOf条件、唯一数组/长度/范围、版本、非法UTF-8/未配对surrogate、非法数字、尾随JSON及超限body拒绝。实现仅支持本冻结Schema所用子集，生成时遇未支持构造直接失败；不是任意JSON Schema通用引擎。contentEncoding为Schema annotation；实际媒体base64/codec、签名验签、当前事实/Permit、nonce/channel、SQL CAS/latch和Stop/barrier必须在各受信实现边界执行。本包不提供执行授权。

## 现有Agent消费依赖

| Owner | 使用与后续责任 |
| --- | --- |
| Agent2 | import Go wire包，实现SQL/Authority。SDK的schema通过不代替scope/facts/hash/expiry、短事务、唯一latch、ticket verifier及Stop。不要新增第二套DTO，公共HTTP入口由Agent4接线 |
| Agent3 | import Go wire及必要Python共享包，生成真实Artifact，复用canonical工具；语义/完整事实/hash/Prepare/Continuation/Seal协调仍归本模块。不要以typed对象构造成功替代完整事实核验 |
| Agent5 | 共用Python包，严格IPC+当前权威+真实短gate和输出lineage；两个ACK/真实fsync、Publisher/Decoder/Sink隔离与drain不由DTO证明。Runtime客户端改动交给Agent4 |

## 验收证据与限制

新增测试覆盖全部132个definition有效见证、258组typed往返（含38接口、68消息Trace、3个Stop场景）、13向量、3934个缺失/额外/错误类型变体、378个条件变体、版本/角色/路由、控制/媒体body上下限、非法Unicode/数字、secret诊断、22项单文件漂移/manifest漂移和手工输出漂移。两次生成零diff，--check通过。保留137契约、11Journal、v1与Go/race/vet。具体最终结果和资源/skip在 `docs/v0.5/evidence/agent-4/v2-dto-2026-10-17/`，其中早期失败复现单列，最终命令不能掩盖它们。

最终结果：新增Python跨语言13 PASS，保留契约137 PASS，Journal 11 PASS；Go test与race各103个顶层测试PASS（含子测试171 PASS）、0 FAIL、50 SKIP，vet通过。[汇总及完整skip列表](../evidence/agent-4/v2-dto-2026-10-17/summary.json)与[实际命令/资源记录](../evidence/agent-4/v2-dto-2026-10-17/commands.json)独立保存。未配置专用SQL/Redis服务，跳过项不计作真实服务验收；Go缓存结果不计作新故障注入。

源码/CPU跨语言通过不等于生产SQL、认证IPC、Guardian物理fencing、fsync崩溃、媒体/观众或GPU验收。当前公共生产入口、默认false及显式true拒绝OUTPUT_FENCE_UNPROVEN、Frozen v1.1/durable-live-1、GPU Binary Wire/PCM/PTS/Credit均未改变；无v2路由注册，无LIVE/GPU启动。整体v0.5仍BLOCKED。
