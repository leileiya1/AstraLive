# Answer Router v0.4

The existing `FactAnswerResolver`, `_fact_context`, `required_product_facts`, ToolClient, LLMProvider and priority RuntimeSession are reused. No per-comment LLM classification or second streaming engine is added.

Selected utterances use the captured Session `activeProductId`, never a comment-supplied product ID. The trusted Go Product Tool returns product/name/description/sizes, price and aggregate inventory. Deterministic price, offered size, name/details and overall stock bypass LLM. SKU stock is explicitly unavailable; aggregate27 is never interpreted as XL27. Missing product/tool facts give a natural unavailable answer and TOOL_FAILED warning. Short deterministic replies stay one TTS segment, preserving previous guards; long tool descriptions pass bounded sentence splitting.

Open chat/complex questions not resolved by the existing fact resolver continue the existing DeepSeek token stream → incremental sentences → incremental XiaoYa PCM. Existing simple product-description answers remain deterministic to preserve accepted fact behavior. Complex introductions remain subject to the existing resolver's conservative capability boundary; a dedicated natural-description routing expansion needs fact guard coverage before broadening it.

No credential/default/binding choice changes. BoundDeepSeek's accepted STOP failure policy still fails the Session for upstream failures. The legacy unbound failure fallback now speaks an explicit unavailable answer rather than echoing raw user input; partial-response failures still fail the Utterance. Fake401/429/ReadTimeout tests verify the comment is never synthesized as a successful answer. No real upstream401/429/timeout is induced.

Validation: existing deterministic TTS-boundary guards with a disobedient LLM, Tool failures and current Runtime tests, plus new fault injection. Real DeepSeek/XiaoYa/SoulX is NOT TESTED in Agent B; earlier Agent A acceptance is not substituted.

## Real follow-up (2026-10-10)

[Actual selected replies](AGENT-B-REAL-ACCEPTANCE.md) validate price, XL option, overall inventory and unavailable XL-only inventory through the accepted Tools/resolver, and chat/open requests through real DeepSeek streaming. The directed-request scheduler classification is independent from answer generation. Test fixture dialogue is not a production preset. A Chinese-letter pronunciation conversion lives only at XiaoYa's synthesis boundary; it does not alter resolved facts or pretend to supply size-stock quantities. Human listening remains pending.
