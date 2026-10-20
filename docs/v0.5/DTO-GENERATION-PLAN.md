# durable-live-2 DTO generation plan

当前实施状态：生成器、Go/Python严格DTO与operation codec已交付；使用方法/最终证据见 [DTO-HANDOFF](implementation/DTO-HANDOFF.md)。以下为原获批后计划，唯一Owner和冻结输入规则继续适用。

Owner / 唯一维护者：Agent4。此文件是实施方案，不是新的授权协议；当前尚未交付生产DTO或生成器。

## 固定输入与输出

输入仅来自获批 `c7fd46209d3cbc6f58541dba8b4e1c85609c823e` 的 `contracts/v0.5/durable-live-2/{schema,protocol,receiver-protocol,state-machines}.json`，以manifest的22文件hash和digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1` 为前置校验。生成器对输入漂移报错，不重算/刷新冻结manifest。治理审批从FINAL-APPROVAL读取，不能修改规范中的历史approvalStatus来使生成通过。

| 保留路径 | 内容 / owner |
| --- | --- |
| `scripts/durable-live/generate_v2_wire.py` | Agent4独占的确定性Go/Python生成器；生成及`--check`模式，精确版本检查 |
| `backend/internal/durablelivev2/wire/` | Agent4生成的完整Go DTO、请求/响应、operation/role/path常量、只读嵌入Schema及strict decode；无Store/SQL/路由注册 |
| `astralive_contracts/durable_live_v2/` | Agent4生成的Python纯契约包，Runtime与Guardian共用；完整DTO、严格validator/operation常量/只读Schema；无Runtime/Guardian副作用 |
| `tests/test_durable_live_v2_wire.py`、Go wire包测试 | Agent4跨语言一致性、非法输入、再生成无diff、secret不进入诊断的验证 |

Python包安装/镜像COPY/PYTHONPATH由Agent4在公共入口接线阶段统一处理，Runtime和Guardian不得复制各自一份。生成代码不手改；13接口的Go样例RawMessage不是正式完整DTO。保留v1 `contract_generated.go`、v1生成器和旧Python Journal接口，不覆盖或给v1结构追加v2可选字段。

## 编码与验证义务

- 输出覆盖132 definitions及25+13 operations，显式区分 required/null/omitted、enum/const/union和嵌套additionalProperties=false；Go不以omitempty丢掉必需null/零值，Python不做宽松类型强制转换。不可支持的Schema构造须显式失败，不静默变为任意dict/RawMessage。
- DTO只是表示层；冻结Schema与跨字段语义校验仍在解码/受信操作边界执行。拒绝未知/重复JSON字段、重复键、非整数身份、不安全整数、非法UTF-8、版本/路由/角色错配和超限body。运算Hash遵循冻结canonical JSON规则，不能直接依赖Go默认HTML escaping或浮点往返。
- 输出携带源commit/digest provenance；内嵌Schema为原字节镜像并校验hash，唯一技术源仍为冻结目录。协议25/13接口来自同一输入，不能另造endpoint/授权操作。authenticated principal/incarnation/channel通过受信Context提供，不能从JSON字段升级成权限。
- consumeTicket用只在合法首次响应内出现的秘密字段；生成repr/String/日志诊断默认遮蔽，不缓存true响应、不写ticket明文到日志。DTO不会产生/消费执行授权，业务事务和Receiver仍实施原有校验。
- Go与Python运行13个Golden Vectors、全部固定request/response及68消息/Stop trace；wrong revision、额外字段、null/false授权条件、边界整数/中文正文Hash分别做负例。生成两次无diff，`--check`检测任何手改。

交付须包含完整SHA、可复现生成命令、精确工具依赖锁定、137契约/11Journal/v1回归与新wire测试。仅type generation不注册生产路由、不启用LIVE。Agent2/3/5可以先做域逻辑，生产共享wire imports与相关PR合入等待Agent4该提交，禁止开三套生成器。技术规范缺口回到CCR，不能在生成器私补授权语义。
