package httpapi

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/app"
	"astralive/backend/internal/runtime"
	"github.com/jackc/pgx/v5"
	"github.com/pashagolub/pgxmock/v4"
)

func sessionRow(status string) *pgxmock.Rows {
	return pgxmock.NewRows([]string{"id", "room_id", "status", "runtime_operation_id", "failure_code", "failure_message", "created_at", "updated_at", "started_at", "ended_at"}).AddRow("session_1", "room_1", status, nil, nil, nil, time.Now(), time.Now(), nil, nil)
}

func TestWebRTCOfferRouting(t *testing.T) {
	for _, tc := range []struct {
		status      string
		want        int
		callRuntime bool
	}{{"missing", 404, false}, {"READY", 409, false}, {"LIVE", 200, true}, {"DEGRADED", 200, true}} {
		t.Run(tc.status, func(t *testing.T) {
			mock, err := pgxmock.NewPool()
			if err != nil {
				t.Fatal(err)
			}
			defer mock.Close()
			calls := 0
			rt := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.URL.Path != "/internal/v1/sessions/session_1/webrtc/offer" {
					t.Errorf("path %s", r.URL.Path)
				}
				var offer map[string]any
				_ = json.NewDecoder(r.Body).Decode(&offer)
				if offer["type"] != "offer" || offer["sdp"] != "complete-sdp" {
					t.Errorf("offer: %#v", offer)
				}
				_, _ = w.Write([]byte(`{"type":"answer","sdp":"answer-sdp"}`))
			}))
			defer rt.Close()
			if tc.status == "missing" {
				mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnError(pgx.ErrNoRows)
			} else {
				mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnRows(sessionRow(tc.status))
			}
			h := &Server{S: &app.Service{Q: dbgen.New(mock), Runtime: runtime.New(rt.URL)}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
			w := httptest.NewRecorder()
			req := httptest.NewRequest("POST", "/api/v1/live-sessions/session_1/webrtc/offer", strings.NewReader(`{"type":"offer","sdp":"complete-sdp"}`))
			req.Header.Set("Content-Type", "application/json")
			h.Router().ServeHTTP(w, req)
			if w.Code != tc.want {
				t.Fatalf("status %d body %s", w.Code, w.Body.String())
			}
			if tc.callRuntime && calls != 1 || !tc.callRuntime && calls != 0 {
				t.Fatalf("runtime calls: %d", calls)
			}
			if tc.want == 200 {
				var response struct {
					Data struct{ Type, Sdp string } `json:"data"`
				}
				if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil || response.Data.Type != "answer" || response.Data.Sdp != "answer-sdp" {
					t.Fatalf("response: %s err=%v", w.Body.String(), err)
				}
			}
			if err := mock.ExpectationsWereMet(); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestHeartbeatFrame(t *testing.T) {
	w := httptest.NewRecorder()
	writeHeartbeat(w, time.Date(2026, 10, 6, 5, 30, 22, 0, time.FixedZone("TST", 8*3600)))
	if got := w.Body.String(); got != "event: heartbeat\ndata: {\"timestamp\":\"2026-10-05T21:30:22Z\"}\n\n" {
		t.Fatalf("heartbeat: %q", got)
	}
}
func TestDevCommentNoRunningSession(t *testing.T) {
	mock, err := pgxmock.NewPool()
	if err != nil {
		t.Fatal(err)
	}
	defer mock.Close()
	room := pgxmock.NewRows([]string{"id", "name", "avatar_id", "voice_id", "knowledge_base_id", "system_prompt", "created_at", "updated_at", "active_product_id"}).AddRow("room_1", "room", "avatar_1", "voice_1", nil, "prompt", time.Now(), time.Now(), nil)
	mock.ExpectQuery("SELECT .* FROM live_rooms WHERE id").WithArgs("room_1").WillReturnRows(room)
	mock.ExpectQuery("SELECT .* FROM live_sessions WHERE room_id").WithArgs("room_1").WillReturnError(pgx.ErrNoRows)
	h := &Server{S: &app.Service{Q: dbgen.New(mock)}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/dev/platform-events", strings.NewReader(`{"eventType":"COMMENT","roomId":"room_1","user":{"externalId":"user_1","nickname":"visitor"},"payload":{"text":"stock?"}}`))
	req.Header.Set("Content-Type", "application/json")
	h.Router().ServeHTTP(w, req)
	if w.Code != 409 || !strings.Contains(w.Body.String(), "SESSION_NOT_RUNNING") {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
func TestDevCommentQueuesPlatformUtterance(t *testing.T) {
	mock, err := pgxmock.NewPool()
	if err != nil {
		t.Fatal(err)
	}
	defer mock.Close()
	var sent map[string]any
	rt := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/sessions/session_1/utterances" {
			t.Errorf("runtime path %s", r.URL.Path)
		}
		_ = json.NewDecoder(r.Body).Decode(&sent)
		w.WriteHeader(202)
		_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_1"}`))
	}))
	defer rt.Close()
	roomRows := func() *pgxmock.Rows {
		return pgxmock.NewRows([]string{"id", "name", "avatar_id", "voice_id", "knowledge_base_id", "system_prompt", "created_at", "updated_at", "active_product_id"}).AddRow("room_1", "room", "avatar_1", "voice_1", nil, "prompt", time.Now(), time.Now(), nil)
	}
	mock.ExpectQuery("SELECT .* FROM live_rooms WHERE id").WithArgs("room_1").WillReturnRows(roomRows())
	mock.ExpectQuery("SELECT .* FROM live_sessions WHERE room_id").WithArgs("room_1").WillReturnRows(sessionRow("LIVE"))
	mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnRows(sessionRow("LIVE"))
	mock.ExpectQuery("SELECT .* FROM live_rooms WHERE id").WithArgs("room_1").WillReturnRows(roomRows())
	utterance := pgxmock.NewRows([]string{"id", "session_id", "source", "text", "priority", "interrupt_policy", "status", "trace_id", "failure_code", "created_at", "updated_at", "started_at", "completed_at"}).AddRow("utt_1", "session_1", "PLATFORM_EVENT", "stock?", int32(80), "INTERRUPT_LOWER_PRIORITY", "QUEUED", "trace_1", nil, time.Now(), time.Now(), nil, nil)
	mock.ExpectQuery("INSERT INTO utterances").WithArgs(pgxmock.AnyArg(), "session_1", "PLATFORM_EVENT", "stock?", int32(80), "INTERRUPT_LOWER_PRIORITY", pgxmock.AnyArg()).WillReturnRows(utterance)
	h := &Server{S: &app.Service{Q: dbgen.New(mock), Runtime: runtime.New(rt.URL)}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/dev/platform-events", strings.NewReader(`{"eventType":"COMMENT","roomId":"room_1","user":{"externalId":"user_1","nickname":"visitor"},"payload":{"text":"stock?"}}`))
	req.Header.Set("Content-Type", "application/json")
	h.Router().ServeHTTP(w, req)
	if w.Code != 202 || !strings.Contains(w.Body.String(), `"status":"QUEUED"`) {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	if sent["source"] != "PLATFORM_EVENT" || sent["priority"] != float64(80) || sent["interruptPolicy"] != "INTERRUPT_LOWER_PRIORITY" || sent["text"] != "stock?" {
		t.Fatalf("runtime utterance: %#v", sent)
	}
	platform, _ := sent["platformContext"].(map[string]any)
	if platform["eventType"] != "COMMENT" {
		t.Fatalf("platformContext: %#v", platform)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
