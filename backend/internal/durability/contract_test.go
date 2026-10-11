package durability

import (
	"encoding/json"
	"os"
	"testing"
)

func TestCanonicalFingerprint(t *testing.T) {
	raw := []byte(`{"schemaVersion":"0.5","sessionId":"s","runEpoch":1,"commandType":"SPEAK","payload":{"text":"你好<&","n":4},"commandId":"c","traceId":"t"}`)
	got, e := Fingerprint(raw)
	if e != nil {
		t.Fatal(e)
	}
	canonical, e := Canonical([]byte(`{"z":null,"x":"你好<&","a":[1,true]}`))
	if e != nil || string(canonical) != `{"a":[1,true],"x":"你好<&","z":null}` {
		t.Fatalf("%s %v", canonical, e)
	}
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	m["commandId"] = "retry"
	m["traceId"] = "other"
	b, _ := json.Marshal(m)
	other, e := Fingerprint(b)
	if e != nil || got != other {
		t.Fatal("correlation affected semantics")
	}
	for _, raw := range []string{`{"a":1,"a":1}`, `{"a":1.0}`, `{"a":9007199254740992}`, `{"a":true} false`} {
		if _, e = Canonical([]byte(raw)); e == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
}
func TestSharedGoldenVectors(t *testing.T) {
	raw, e := os.ReadFile("testdata/fingerprint-v05.json")
	if e != nil {
		t.Fatal(e)
	}
	var vectors []struct {
		Name        string
		Command     json.RawMessage
		Canonical   string
		Fingerprint string
	}
	if e = json.Unmarshal(raw, &vectors); e != nil {
		t.Fatal(e)
	}
	for _, v := range vectors {
		got, e := Fingerprint(v.Command)
		if e != nil || got != v.Fingerprint {
			t.Fatalf("%s: %s vs %s %v", v.Name, got, v.Fingerprint, e)
		}
	}
}
