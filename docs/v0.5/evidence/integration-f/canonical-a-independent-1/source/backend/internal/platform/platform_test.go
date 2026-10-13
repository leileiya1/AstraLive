package platform

import (
	"testing"
	"time"
)

func TestNormalize(t *testing.T) {
	m := Mapping{"mock", "external", "room", "session"}
	e := Event{Platform: "mock", PlatformRoomID: "external", InternalRoomID: "room", SessionID: "session", EventType: Comment, UserExternalID: "a", Content: "\x00 你好 ", SourceEventID: "source-1", Transport: "MOCK_REPLAY", TraceID: "untrusted"}
	now := time.Now()
	v, err := Normalize(e, m, now)
	if err != nil || v.Content != "你好" || v.SourceEventID != "source-1" || v.TraceID == "untrusted" || !v.ReceivedAt.Equal(now) || v.SourceTimestamp != nil {
		t.Fatal(v, err)
	}
	e.Transport = "MOCK_BACKUP"
	w, _ := Normalize(e, m, now)
	if v.EventID != w.EventID {
		t.Fatal("transport identity")
	}
	e.SourceEventID = ""
	w, _ = Normalize(e, m, now)
	if w.SourceEventID != "" || w.EventID != "" {
		t.Fatal("invented source")
	}
	e.SessionID = "foreign"
	if _, err = Normalize(e, m, now); err == nil {
		t.Fatal("mapping bypass")
	}
	e.SessionID = m.SessionID
	e.EventType = Gift
	if _, err = Normalize(e, m, now); err == nil {
		t.Fatal("unsupported")
	}
	e.EventType = Comment
	e.Content = string(make([]byte, 2049))
	if _, err = Normalize(e, m, now); err == nil {
		t.Fatal("length")
	}
}
