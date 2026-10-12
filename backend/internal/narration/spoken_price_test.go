package narration

import "testing"

func TestCapturedStagingSpokenCNYPreservesAmountAndFactID(t *testing.T) {
	for _, amount := range []string{"0.00", "99.00", "99.50", "123456789.01"} {
		facts := map[string]string{"price": amount, "currency": "CNY"}
		spoken, ids := factAnswerForSpeech("多少钱？", facts, true)
		if spoken != "这款目前价格是人民币"+amount+"元。" || !sameSet(ids, []string{"price"}) || facts["price"] != amount {
			t.Fatal("amount/ID changed", spoken, ids)
		}
		old, _ := factAnswer("多少钱？", facts)
		if old != "这款目前价格是 "+amount+" CNY。" {
			t.Fatal("flags-off old path changed", old)
		}
		facts["currency"] = "USD"
		usd, _ := factAnswerForSpeech("多少钱？", facts, true)
		if usd != "这款目前价格是 "+amount+" USD。" {
			t.Fatal("unapproved currency conversion", usd)
		}
	}
}
