# Canonical trusted builtin fixture correction, preflight 2

The updated fixtures use canonical builtin fact IDs name/price/stock/sizes and each corresponding trusted {{field}} placeholder. Original product.* IDs were authoring aliases and did not exercise public Controller.Start's trusted builtin validation or answer-summary IDs. New fixtureVersion/scriptVersion identify this change. Product remains exactly the confirmed demo SKU, price99/CNY/stock20/sizes电子版; expected PostgreSQL price::text is99.00.

Only the first four statements and those IDs/fact dictionary/question oracle IDs changed. Remaining136 statement objects retain exact content/fact IDs; no additional repetitions or removed required facts. Historical fixture bytes and SHA256 are retained here, and original catalog-tts-preflight-1 with754.88/753.88 second full synthesis measurements is untouched. New facts map retains140 unique complete facts; questions remain list[str]. TrustedBuiltinPreview is test expectation metadata, not client or SQL authority.

Actual new CPU TTS, through production StreamingVoiceAdapter to16000Hz mono s16le and640-sample pad:

| Case | Padded seconds |
| --- | --- |
| {{name}} rendered as桌面整理指南 |4.00|
| {{price}} rendered as99.00 |5.24|
| {{stock}} rendered as20 |5.52|
| {{sizes}} rendered as电子版 |4.76|
| Current Go price-answer text |3.16|
| Current Go stock-answer text |5.72|
| Current Go name-answer text |2.32|
| Nonempty approved bridge choice1 |3.80|
| Nonempty approved bridge choice2 |5.20|

All nine actual sample measurements are <=8s; max5.72s, no truncation/provider speed change. Empty bridge choice is valid and creates no TTS segment, so no invented empty synthesis duration. Current price answer still emits native Ignore OOV CNY, retained in tts.log; fixture narration explicitly says人民币, but this does not fix production answer pronunciation. Texts are the current source-defined answers and bridge choices, not live LLM/public API output.

This was a partial preflight of exactly four changed statements, three canonical answers and two nonempty bridge choices. The other136 rows remain historical measurements. newFullNarrationSeconds=null: no new whole-catalog total is claimed, no summing historical and new runs into a continuous session. No public Go Controller.Start trusted-placeholder/ownership transaction, GPU, Chrome, RTMP, fact coverage, audience hearing or natural continuation acceptance was performed here. F will execute actual public Start and real GPU Golden independently.

Reproduce from F root with PYTHONPATH=runtime and the installed CPU environment running tts-preflight.py. It reads fixed fixture expectations and cached local model only, never credentials. result.json contains per-case exact resampled samples/pad/prepad PCM SHA256; manifest.json pins current/historical fixture and artifacts plus current Go source hashes. Only F performs commit; no production/contract file was changed.
