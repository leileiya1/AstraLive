# Natural Interruption — 接纳与媒体执行分离

普通问题到达时继续复用 `interaction.Scheduler`：Normalize、去重、topic合并、TTL、用户公平评分和限流全部保留。`SelectionAdapter`只把已选问题提交Agent2 AdmitTurn，成功后才返回持久turnId；这里不是UtteranceId。旧Scheduler UI称它utterance的字段需要Agent4在durable模式正确标注。

示例：第1段ACTIVE → XL问题被选中且持久接纳WAITING → 场控YIELD_PENDING → 当前段全required drain + BUSINESS_COMMIT → YieldAtSegmentBoundary → 再查TTL/商品/Stop → 认领COMMENT → 原Tool/DeepSeek/XiaoYa/SoulX回答 → 完成检查点 → 下一SCRIPT（第2段）。COMMENT不推进script cursor。

边界前重复Tick不会认领第二个媒体任务。重复checkpoint不能释放新话轮slot。评论在等待或事实查询期间过期则不Claim；Claim和Runtime开始副作用时还须再次校验。普通问题失效后应由Agent2关闭WAITING Turn为INTERRUPTED(EXPIRED)，Agent3不写SQL或伪造媒体中断证明。

共享Scheduler尚无完整合并身份导出，且旧busy gate等待整个Utterance。Agent3未直接编辑共享文件；提供[未应用补丁](agent-3/scheduler-members.patch)：保留最多128条规范source成员，超限计drop，新增仅供durable准入dispatcher的SelectionOnly gate。补丁不改评分/TTL算法，不允许legacy Runtime dispatcher使用SelectionOnly。补丁已在一次性CPU树测试：忙SCRIPT中3个相同XL问题→一次选择、保留3个来源、当前claim仍1。Agent4必须替换legacy投递路径，禁止一Session双调度。

FORCE由操作员显式触发既有机制；先立即关闭自动准入并持久暂停run，等待旧输出fence。不得把FORCE当作普通评论的延迟优化。Manager.Override只是本地即时屏障，不能替代Agent2持久Pause/Recovery；重启必须从持久投影还原override。明确Resume仅写恢复意图，待Agent2隔离和激活成功后才允许新段。

连续高负载最多2次问答后讲1段；一个观众公平性、重复问题合并继续由原Scheduler负责。没有问题时持续完成计划，不等待空评论。SCRIPT/COMMENT失败均不假装完成；评论确认中断后可回到原script下一段，脚本本身被中断则进入人工恢复，不盲目重播。
