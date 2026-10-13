# ISSUE-003: Product 尺码事实未经过输出侧校验

- Status: CLOSED (2026-10-06, Contract v1.1 Integration Acceptance)
- Severity: P1（关闭前）
- Module: runtime
- Reproduction: Product `sizes=[M,L,XL]`、aggregate `stock=27`，提问“XL 还有库存吗？”，并注入故意输出“XL有27件”的 Bad LLM。
- Expected: 最终送入 TTS 的文本区分商品总库存与 XL 单独库存；不能把 27 件归给 XL。
- Actual before fix: Tool Facts 包含安全提示，但 LLM 的生成文本没有确定性输出保证。
- Resolution: `runtime/app/fact_answer.py` 的确定性商品回答由 `runtime/app/session.py` 在 TTS 之前调用。所测商品事实问题不调用 LLM；无匹配事实时沿用 Tool 失败降级。
- Verification: `tests/test_acceptance_guards.py` 使用 Bad LLM 和 Capturing TTS，确认 Bad LLM 在普通聊天可返回“XL有27件”，而三个商品问题均未调用它。TTS 实际输入及 Tool 调用保存在 [`integration/evidence/fact-safety-v1.1.json`](../evidence/fact-safety-v1.1.json)：XL 库存回答为“这款有 XL 尺码，目前商品整体还有库存，但暂时没有 XL 单独库存数据。”。Runtime 原有 `test_deterministic_product_answers_reach_tts_without_llm` 同样通过。
- Contract Reference: `contracts/CONTRACTS.md` §7.3 Product、§8.7 Speak、§15 Tool Result；`architecture/ARCHITECTURE.md` §6.2。
- Suggested Fix: 已完成；如将来扩展新的商品事实问法，需让新路由也经过确定性回答或同等级输出校验。
