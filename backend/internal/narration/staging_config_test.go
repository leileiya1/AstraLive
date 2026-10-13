package narration

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestStagingCaptureFrozenProfiles(t *testing.T) {
	for _, tc := range []struct {
		flag, profile, gate string
		fail                bool
	}{
		{"false", "", "", false}, {"true", "", "", true}, {"1", "staging-short-1", "", false},
		{"true", "staging-segment-8s-1", "sha256:" + strings.Repeat("a", 64), false},
		{"true", "staging-short-gpu1g-1", "", false},
		{"true", "staging-segment-8s-gpu1g-1", "sha256:" + strings.Repeat("a", 64), false},
		{"true", "staging-short-gpu1g-1", "sha256:" + strings.Repeat("a", 64), true},
		{"true", "staging-segment-8s-gpu1g-1", "", true},
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

// Invoke the actual Python startup parser, not a duplicate Go/Python mock.
// Explicit Runtime Python is required so this check cannot silently use an
// unsupported system interpreter. There is no provider/network/media work.
func TestStagingEnvironmentGoPythonAgreement(t *testing.T) {
	python := os.Getenv("DURABILITY_TEST_PYTHON")
	if python == "" {
		t.Skip("DURABILITY_TEST_PYTHON not set; paired Runtime configuration NOT TESTED")
	}
	root, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	const flag = "ASTRALIVE_SOULX_STAGING_ENABLED"
	const profile = "ASTRALIVE_SOULX_STAGING_LIMITS_REVISION"
	const gate = "ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256"
	for _, tc := range []struct {
		name            string
		env             map[string]string
		reject          bool
		expectedProfile string
	}{
		{"default off", map[string]string{}, false, ""},
		{"disabled empty ignored", map[string]string{flag: "false", profile: "", gate: "invalid"}, false, ""},
		{"default off invalid dormant profile", map[string]string{profile: "invalid", gate: "invalid"}, false, ""},
		{"enabled absent original short", map[string]string{flag: "true"}, false, "staging-short-1"},
		{"enabled explicit empty", map[string]string{flag: "true", profile: ""}, true, ""},
		{"enabled whitespace", map[string]string{flag: "true", profile: " "}, true, ""},
		{"old short", map[string]string{flag: "1", profile: "staging-short-1"}, false, "staging-short-1"},
		{"new short explicit", map[string]string{flag: "true", profile: "staging-short-gpu1g-1"}, false, "staging-short-gpu1g-1"},
		{"old long gate", map[string]string{flag: "true", profile: "staging-segment-8s-1", gate: "sha256:" + strings.Repeat("a", 64)}, false, "staging-segment-8s-1"},
		{"new long gate", map[string]string{flag: "true", profile: "staging-segment-8s-gpu1g-1", gate: "sha256:" + strings.Repeat("a", 64)}, false, "staging-segment-8s-gpu1g-1"},
		{"long missing gate", map[string]string{flag: "true", profile: "staging-segment-8s-gpu1g-1"}, true, ""},
		{"invalid flag", map[string]string{flag: ""}, true, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, name := range []string{flag, profile, gate} {
				t.Setenv(name, "")
				if value, present := tc.env[name]; present {
					os.Setenv(name, value)
				} else {
					os.Unsetenv(name)
				}
			}
			settings, goError := StagingFromEnvironment()
			command := exec.Command(python, "-c", `import json
from app.staging_settings import StagingSettings
try: result={"accepted":True,"capture":StagingSettings.from_env().capture()}
except ValueError: result={"accepted":False}
print(json.dumps(result))`)
			command.Dir = root
			command.Env = []string{"PYTHONPATH=" + filepath.Join(root, "runtime"), "PYTHONNOUSERSITE=1"}
			for name, value := range tc.env {
				command.Env = append(command.Env, name+"="+value)
			}
			raw, err := command.Output()
			if err != nil {
				t.Fatal("actual Python configuration probe failed", err)
			}
			var actual struct {
				Accepted bool           `json:"accepted"`
				Capture  map[string]any `json:"capture"`
			}
			if err = json.Unmarshal(raw, &actual); err != nil {
				t.Fatal(err)
			}
			if (goError != nil) != tc.reject || actual.Accepted == tc.reject {
				t.Fatal("Go/Python admission mismatch", goError, actual.Accepted)
			}
			if !tc.reject {
				serialized, _ := json.Marshal(settings.Capture())
				var capture map[string]any
				json.Unmarshal(serialized, &capture)
				if !reflect.DeepEqual(capture, actual.Capture) {
					t.Fatal("cross-language captured profile mismatch", capture, actual.Capture)
				}
				if tc.expectedProfile != "" && (settings.LimitsRevision == nil || *settings.LimitsRevision != tc.expectedProfile) {
					t.Fatal("implicit default/promotion changed")
				}
				var flags map[string]json.RawMessage
				json.Unmarshal(serialized, &flags)
				// Captured run remains immutable after later environment changes.
				t.Setenv(profile, "")
				captured, err := CapturedStaging(flags)
				if err != nil || !reflect.DeepEqual(captured, settings) {
					t.Fatal("capture reread startup environment")
				}
			}
		})
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

func TestFrozenShortGroupsPreservePlannerAndMeasuredCap(t *testing.T) {
	for _, name := range []string{"staging-short-1", "staging-short-gpu1g-1"} {
		settings := StagingSettings{Enabled: true, LimitsRevision: &name}
		if !settings.ShortProfile() || settings.Validate() != nil {
			t.Fatal("frozen short profile not recognized")
		}
	}
	for _, name := range []string{"staging-segment-8s-1", "staging-segment-8s-gpu1g-1"} {
		gate := "sha256:" + strings.Repeat("a", 64)
		settings := StagingSettings{Enabled: true, LimitsRevision: &name, ShortGateSHA256: &gate}
		if settings.ShortProfile() || settings.Validate() != nil {
			t.Fatal("frozen long profile changed")
		}
	}
}
