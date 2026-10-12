package narration

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestStagingCaptureFrozenProfiles(t *testing.T) {
	for _, tc := range []struct {
		flag, profile, gate string
		fail                bool
	}{
		{"false", "", "", false}, {"true", "", "", false}, {"1", "staging-short-1", "", false},
		{"true", "staging-segment-8s-1", "sha256:" + strings.Repeat("a", 64), false},
		{"oops", "", "", true}, {"true", "staging-segment-8s-1", "", true}, {"true", "unknown", "", true},
		{"true", "staging-short-1", "sha256:" + strings.Repeat("a", 64), true}} {
		t.Run(tc.flag+tc.profile+tc.gate, func(t *testing.T) {
			t.Setenv("ASTRALIVE_SOULX_STAGING_ENABLED", tc.flag)
			t.Setenv("ASTRALIVE_SOULX_STAGING_LIMITS_REVISION", tc.profile)
			t.Setenv("ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256", tc.gate)
			s, e := StagingFromEnvironment()
			if (e != nil) != tc.fail {
				t.Fatalf("unexpected validation: %v", e)
			}
			if e == nil {
				raw, _ := json.Marshal(s.Capture())
				var flags map[string]json.RawMessage
				json.Unmarshal(raw, &flags)
				got, e := CapturedStaging(flags)
				if e != nil || got.Enabled != s.Enabled {
					t.Fatal("capture mismatch")
				}
			}
		})
	}
	for _, raw := range []string{`{"soulxStagingEnabled":true}`, `{"soulxStagingEnabled":null,"soulxStagingLimitsRevision":null,"soulxStagingShortGateSHA256":null}`, `{"soulxStagingEnabled":false,"soulxStagingLimitsRevision":"staging-short-1","soulxStagingShortGateSHA256":null}`} {
		var flags map[string]json.RawMessage
		json.Unmarshal([]byte(raw), &flags)
		if _, e := CapturedStaging(flags); e == nil {
			t.Fatal("malformed capture accepted")
		}
	}
}
func TestShortAuthoredPlanDoesNotPackOrCutStatements(t *testing.T) {
	input := []BeatInput{{Title: "欢迎", Statements: []Statement{{Text: "欢迎。"}, {Text: "请看。"}}}}
	old, e := BuildPlan("n", "s", "v", "p", "v", "h", "自然", AtBoundary, []string{"sink"}, input)
	if e != nil {
		t.Fatal(e)
	}
	short, e := buildPlan("n", "s", "v", "p", "v", "h", "自然", AtBoundary, []string{"sink"}, input, 0)
	if e != nil {
		t.Fatal(e)
	}
	if len(old.Segments) != 1 || len(short.Segments) != 2 || short.Segments[0].Text != "欢迎。" || short.Segments[1].Text != "请看。" {
		t.Fatal("authored semantic packing mismatch")
	}
}
