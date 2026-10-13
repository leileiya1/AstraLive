package sse

import "testing"

func TestHub(t *testing.T) {
	h := New()
	ch, done := h.Subscribe("s1")
	h.Publish("s2", Message{Name: "other"})
	h.Publish("s1", Message{Name: "session.live"})
	select {
	case m := <-ch:
		if m.Name != "session.live" {
			t.Fatal(m.Name)
		}
	default:
		t.Fatal("missing event")
	}
	done()
}
