package userconfig

import (
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/getkin/kin-openapi/openapi3"
)

func TestConfigurationSpecification(t *testing.T) {
	doc, e := openapi3.NewLoader().LoadFromFile(filepath.Join("..", "..", "..", "contracts", "user-config", "schema.json"))
	if e != nil {
		t.Fatal(e)
	}
	if e = doc.Validate(t.Context()); e != nil {
		t.Fatal(e)
	}
	p := Profile{ID: "profile-a", Kind: "TTS", Name: "XiaoYa", Provider: "xiaoya", Config: json.RawMessage(`{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}`), Version: 1, Enabled: true, Verification: "UNTESTED", Health: "UNKNOWN", UpdatedAt: time.Now().UTC()}
	raw, _ := json.Marshal(p)
	var instance any
	_ = json.Unmarshal(raw, &instance)
	if e = doc.Components.Schemas["Profile"].Value.VisitJSON(instance); e != nil {
		t.Fatal("safe profile schema", e)
	}
	// The machine schema excludes credential fields from public profile DTOs.
	instance.(map[string]any)["secret"] = "synthetic-key"
	if e = doc.Components.Schemas["Profile"].Value.VisitJSON(instance); e == nil {
		t.Fatal("plaintext response field allowed")
	}
}
