package fsm

import "testing"

func TestSessionTransitions(t *testing.T) {
	for _, v := range [][3]any{{"CREATED", "PREPARING", true}, {"PREPARING", "READY", true}, {"READY", "STARTING", true}, {"STARTING", "LIVE", true}, {"LIVE", "STOPPING", true}, {"STOPPING", "ENDED", true}, {"CREATED", "LIVE", false}, {"READY", "LIVE", false}, {"ENDED", "LIVE", false}, {"LIVE", "LIVE", false}} {
		got := Session(v[0].(string), v[1].(string))
		if got != v[2].(bool) {
			t.Errorf("%s -> %s: %v", v[0], v[1], got)
		}
	}
}
func TestUtteranceTransitions(t *testing.T) {
	for _, v := range [][3]any{{"QUEUED", "GENERATING", true}, {"GENERATING", "SYNTHESIZING", true}, {"PLAYING", "COMPLETED", true}, {"RENDERING", "INTERRUPTED", true}, {"QUEUED", "CANCELLED", true}, {"QUEUED", "PLAYING", false}, {"COMPLETED", "FAILED", false}} {
		got := Utterance(v[0].(string), v[1].(string))
		if got != v[2].(bool) {
			t.Errorf("%s -> %s: %v", v[0], v[1], got)
		}
	}
}
