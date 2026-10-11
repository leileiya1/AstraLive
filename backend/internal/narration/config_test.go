package narration

import (
	"os"
	"testing"
)

func TestFrozenFlag(t *testing.T) {
	for _, env := range []string{"ASTRALIVE_CONTINUITY_ENABLED", "ASTRALIVE_NARRATION_CONTINUITY_ENABLED"} {
		v, ok := os.LookupEnv(env)
		os.Unsetenv(env)
		t.Cleanup(func() {
			if ok {
				os.Setenv(env, v)
			} else {
				os.Unsetenv(env)
			}
		})
	}
	if got, e := Enabled(); got || e != nil {
		t.Fatal("unset canonical flag", got, e)
	}
	for _, x := range []struct {
		v         string
		want, err bool
	}{{"", false, true}, {"false", false, false}, {"true", true, false}, {"0", false, false}, {"1", true, false}, {"invalid", false, true}} {
		t.Setenv("ASTRALIVE_CONTINUITY_ENABLED", x.v)
		got, e := Enabled()
		if got != x.want || (e != nil) != x.err {
			t.Fatal(x, got, e)
		}
	}
	for _, v := range []string{"false", "true"} {
		t.Setenv("ASTRALIVE_NARRATION_CONTINUITY_ENABLED", v)
		if _, e := Enabled(); e == nil {
			t.Fatal("unsupported alias accepted")
		}
	}
}
