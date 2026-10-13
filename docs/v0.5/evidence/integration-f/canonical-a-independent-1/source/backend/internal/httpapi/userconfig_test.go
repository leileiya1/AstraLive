package httpapi

import (
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"

	"astralive/backend/internal/userconfig"
)

func TestConfigurationRouteIsAuthenticatedAndSeparate(t *testing.T) {
	h := &Server{Config: &userconfig.Service{}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/v0.3/config/profiles", strings.NewReader(`{"secret":"synthetic-key"}`))
	r.Header.Set("Content-Type", "application/json")
	h.Router().ServeHTTP(w, r)
	if w.Code != 401 || !strings.Contains(w.Body.String(), "UNAUTHENTICATED") || strings.Contains(w.Body.String(), "synthetic-key") {
		t.Fatal("config route bypasses authentication", w.Code)
	}
}
