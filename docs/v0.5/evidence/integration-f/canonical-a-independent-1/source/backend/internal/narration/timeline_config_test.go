package narration

import (
	"os"
	"testing"
)

func TestTimelineConfiguration(t *testing.T) {
	for _, name := range []string{"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED", "ASTRALIVE_MEDIA_TIMELINE_ENABLED"} {
		value, present := os.LookupEnv(name)
		os.Unsetenv(name)
		t.Cleanup(func() {
			if present {
				os.Setenv(name, value)
			} else {
				os.Unsetenv(name)
			}
		})
	}
	for _, tc := range []struct {
		name           string
		primary, alias *string
		want, fail     bool
	}{
		{name: "unset"},
		{name: "primary only", primary: stringPointer("TRUE"), want: true},
		{name: "alias only", alias: stringPointer("1"), want: true},
		{name: "primary off", primary: stringPointer("false")},
		{name: "equal", primary: stringPointer("true"), alias: stringPointer("1"), want: true},
		{name: "equal off", primary: stringPointer("0"), alias: stringPointer("FALSE")},
		{name: "conflict", primary: stringPointer("true"), alias: stringPointer("false"), fail: true},
		{name: "reverse conflict", primary: stringPointer("0"), alias: stringPointer("1"), fail: true},
		{name: "primary empty", primary: stringPointer(""), fail: true},
		{name: "alias empty", alias: stringPointer(""), fail: true},
		{name: "invalid ignored alias", primary: stringPointer("1"), alias: stringPointer("yes"), fail: true},
		{name: "whitespace", primary: stringPointer(" true "), fail: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for name, v := range map[string]*string{"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": tc.primary, "ASTRALIVE_MEDIA_TIMELINE_ENABLED": tc.alias} {
				if v != nil {
					t.Setenv(name, *v)
				}
			}
			got, err := TimelineEnabled()
			if got != tc.want || (err != nil) != tc.fail {
				t.Fatalf("got %v, %v; want %v, failure=%v", got, err, tc.want, tc.fail)
			}
		})
	}
}

func stringPointer(value string) *string { return &value }
