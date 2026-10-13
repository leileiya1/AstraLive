package app

import (
	"testing"
	"time"
)

func TestEventValidation(t *testing.T) {
	id := "utt_1"
	base := Event{SchemaVersion: "1.0", EventID: "evt_1", EventType: "UTTERANCE_PLAYING", SessionID: "session_1", UtteranceID: &id, TraceID: "trace_1", OccurredAt: time.Now().UTC(), Source: "AI_RUNTIME", Payload: map[string]any{}}
	if e := base.Validate(); e != nil {
		t.Fatal(e)
	}
	base.UtteranceID = nil
	if base.Validate() == nil {
		t.Fatal("missing utteranceId accepted")
	}
	base.EventType = "UNKNOWN"
	if base.Validate() == nil {
		t.Fatal("unknown event accepted")
	}
}
