package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"astralive/backend/generated/runtimeapi"
)

func TestRuntimeClientCreateSessionWithHTTPStub(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/sessions" || r.Method != "POST" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		w.WriteHeader(202)
		_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_mock"}`))
	}))
	defer ts.Close()
	req := runtimeapi.CreateRuntimeSessionRequest{SessionId: "session_1", Context: runtimeapi.RuntimeSessionContext{RoomId: "room_1", SystemPrompt: "host"}}
	op, e := New(ts.URL).CreateSession(context.Background(), req)
	if e != nil || op.OperationID != "op_mock" {
		t.Fatalf("op=%+v err=%v", op, e)
	}
}
func TestV11RuntimePayloadsAndWebRTC(t *testing.T) {
	var gotCreate, gotSpeak map[string]any
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/internal/v1/sessions":
			_ = json.NewDecoder(r.Body).Decode(&gotCreate)
			w.WriteHeader(202)
			_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_1"}`))
		case "/internal/v1/sessions/session_1/utterances":
			_ = json.NewDecoder(r.Body).Decode(&gotSpeak)
			w.WriteHeader(202)
			_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_2"}`))
		case "/internal/v1/sessions/session_1/webrtc/offer":
			var offer runtimeapi.WebRTCOffer
			_ = json.NewDecoder(r.Body).Decode(&offer)
			if offer.Type != runtimeapi.Offer || offer.Sdp != "complete-sdp" {
				t.Errorf("offer: %+v", offer)
			}
			_, _ = w.Write([]byte(`{"type":"answer","sdp":"answer-sdp"}`))
		default:
			t.Errorf("unexpected route: %s", r.URL.Path)
		}
	}))
	defer ts.Close()
	c := New(ts.URL)
	product, kb := "product_1", "kb_1"
	create := runtimeapi.CreateRuntimeSessionRequest{Context: runtimeapi.RuntimeSessionContext{RoomId: "room_1", SystemPrompt: "host", ActiveProductId: &product, KnowledgeBaseId: &kb}}
	if _, err := c.CreateSession(context.Background(), create); err != nil {
		t.Fatal(err)
	}
	ctx, ok := gotCreate["context"].(map[string]any)
	if !ok || ctx["roomId"] != "room_1" || ctx["systemPrompt"] != "host" || ctx["activeProductId"] != product || ctx["knowledgeBaseId"] != kb {
		t.Fatalf("context = %#v", gotCreate["context"])
	}
	speak := runtimeapi.RuntimeUtteranceRequest{Source: runtimeapi.OPERATOR}
	if _, err := c.Speak(context.Background(), "session_1", speak); err != nil {
		t.Fatal(err)
	}
	if gotSpeak["source"] != "OPERATOR" {
		t.Fatalf("source = %#v", gotSpeak["source"])
	}
	answer, err := c.WebRTCOffer(context.Background(), "session_1", runtimeapi.WebRTCOffer{Type: runtimeapi.Offer, Sdp: "complete-sdp"})
	if err != nil || answer.Type != runtimeapi.Answer || answer.Sdp != "answer-sdp" {
		t.Fatalf("answer=%+v err=%v", answer, err)
	}
}
func TestRuntimeErrors(t *testing.T) {
	for _, v := range []struct {
		status     int
		code       string
		wantStatus int
		wantCode   string
	}{{429, "RUNTIME_OVERLOADED", 429, "RUNTIME_OVERLOADED"}, {503, "RUNTIME_UNAVAILABLE", 503, "RUNTIME_UNAVAILABLE"}, {404, "SESSION_NOT_FOUND", 404, "SESSION_NOT_FOUND"}, {409, "SESSION_NOT_READY", 409, "SESSION_NOT_READY"}, {404, "AVATAR_NOT_FOUND", 404, "AVATAR_NOT_FOUND"}} {
		s, c := MapError(&Error{v.status, v.code})
		if s != v.wantStatus || c != v.wantCode {
			t.Errorf("%d %s => %d %s", v.status, v.code, s, c)
		}
	}
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(50 * time.Millisecond) }))
	defer ts.Close()
	c := New(ts.URL)
	c.Client.Timeout = time.Millisecond
	_, e := c.Health(context.Background())
	s, code := MapError(e)
	if s != 503 || code != "RUNTIME_UNAVAILABLE" {
		t.Fatalf("timeout => %d %s", s, code)
	}
}
