package app

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/runtime"
	"github.com/pashagolub/pgxmock/v4"
)

func TestStartStopInvalidState(t *testing.T) {
	for _, tc := range []struct{ status, action string }{{"LIVE", "start"}, {"CREATED", "stop"}} {
		mock, e := pgxmock.NewPool()
		if e != nil {
			t.Fatal(e)
		}
		rows := pgxmock.NewRows([]string{"id", "room_id", "status", "runtime_operation_id", "failure_code", "failure_message", "created_at", "updated_at", "started_at", "ended_at"}).AddRow("session_1", "room_1", tc.status, nil, nil, nil, time.Now(), time.Now(), nil, nil)
		mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnRows(rows)
		s := &Service{Q: dbgen.New(mock), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
		if tc.action == "start" {
			_, e = s.Start(context.Background(), "session_1", "trace_1")
		} else {
			_, e = s.Stop(context.Background(), "session_1", "trace_1")
		}
		if !errors.Is(e, ErrConflict) {
			t.Errorf("%s %s: %v", tc.action, tc.status, e)
		}
		if e = mock.ExpectationsWereMet(); e != nil {
			t.Error(e)
		}
		mock.Close()
	}
}
func TestStartSendsRoomContext(t *testing.T) {
	mock, err := pgxmock.NewPool()
	if err != nil {
		t.Fatal(err)
	}
	defer mock.Close()
	var contextBody map[string]any
	rt := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		contextBody, _ = body["context"].(map[string]any)
		w.WriteHeader(202)
		_, _ = w.Write([]byte(`{"accepted":true,"operationId":"op_1"}`))
	}))
	defer rt.Close()
	se := func() *pgxmock.Rows {
		return pgxmock.NewRows([]string{"id", "room_id", "status", "runtime_operation_id", "failure_code", "failure_message", "created_at", "updated_at", "started_at", "ended_at"}).AddRow("session_1", "room_1", "CREATED", nil, nil, nil, time.Now(), time.Now(), nil, nil)
	}
	room := pgxmock.NewRows([]string{"id", "name", "avatar_id", "voice_id", "knowledge_base_id", "system_prompt", "created_at", "updated_at", "active_product_id"}).AddRow("room_1", "room", "avatar_1", "voice_1", "kb_1", "host prompt", time.Now(), time.Now(), "product_1")
	avatar := pgxmock.NewRows([]string{"id", "name", "engine", "status", "created_at", "updated_at"}).AddRow("avatar_1", "avatar", "MOCK", "CREATED", time.Now(), time.Now())
	voice := pgxmock.NewRows([]string{"id", "name", "provider", "provider_voice_id", "created_at", "updated_at"}).AddRow("voice_1", "voice", "MOCK", "mock", time.Now(), time.Now())
	mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnRows(se())
	mock.ExpectQuery("SELECT .* FROM live_rooms WHERE id").WithArgs("room_1").WillReturnRows(room)
	mock.ExpectQuery("SELECT .* FROM avatars WHERE id").WithArgs("avatar_1").WillReturnRows(avatar)
	mock.ExpectQuery("SELECT .* FROM voices WHERE id").WithArgs("voice_1").WillReturnRows(voice)
	mock.ExpectQuery("SELECT .* FROM live_sessions WHERE id").WithArgs("session_1").WillReturnRows(se())
	mock.ExpectExec("UPDATE live_sessions SET status").WithArgs("session_1", "CREATED", "PREPARING").WillReturnResult(pgxmock.NewResult("UPDATE", 1))
	mock.ExpectExec("UPDATE live_sessions SET runtime_operation_id").WithArgs("session_1", pgxmock.AnyArg()).WillReturnResult(pgxmock.NewResult("UPDATE", 1))
	s := &Service{Q: dbgen.New(mock), Runtime: runtime.New(rt.URL), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if _, err := s.Start(context.Background(), "session_1", "trace_1"); err != nil {
		t.Fatal(err)
	}
	if contextBody["roomId"] != "room_1" || contextBody["systemPrompt"] != "host prompt" || contextBody["activeProductId"] != "product_1" || contextBody["knowledgeBaseId"] != "kb_1" {
		t.Fatalf("context: %#v", contextBody)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
