package httpapi

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/getkin/kin-openapi/openapi3"
)

func TestFrozenOpenAPIValidation(t *testing.T) {
	loader := openapi3.NewLoader()
	doc, e := loader.LoadFromFile("../../../contracts/control-api.openapi.yaml")
	if e != nil {
		t.Fatal(e)
	}
	if e = doc.Validate(context.Background()); e != nil {
		t.Fatal(e)
	}
	utterance := doc.Components.Schemas["CreateUtteranceRequest"].Value
	good := map[string]any{"text": "Hello", "priority": float64(100), "interruptPolicy": "FORCE", "source": "OPERATOR"}
	if e = utterance.VisitJSON(good); e != nil {
		t.Fatal(e)
	}
	bad := map[string]any{"text": "Hello", "priority": float64(100), "interruptPolicy": "NOW", "source": "OPERATOR"}
	if utterance.VisitJSON(bad) == nil {
		t.Fatal("invalid enum passed")
	}
	response := doc.Components.Schemas["SessionStartResponse"].Value
	valid := map[string]any{"code": "OK", "message": "accepted", "data": map[string]any{"operationId": "op_1", "sessionId": "session_1", "status": "PREPARING"}, "requestId": "req_1", "timestamp": "2026-10-06T05:30:22Z"}
	if e = response.VisitJSON(valid); e != nil {
		t.Fatal(e)
	}
	delete(valid["data"].(map[string]any), "operationId")
	if response.VisitJSON(valid) == nil {
		t.Fatal("missing operationId passed")
	}
	w := httptest.NewRecorder()
	respond(w, httptest.NewRequest("POST", "/api/v1/live-sessions/session_1/start", nil), 202, map[string]any{"operationId": "op_1", "sessionId": "session_1", "status": "PREPARING"})
	var actual any
	if e = json.Unmarshal(w.Body.Bytes(), &actual); e != nil {
		t.Fatal(e)
	}
	if e = response.VisitJSON(actual); e != nil {
		t.Fatalf("actual start response: %v", e)
	}
	w = httptest.NewRecorder()
	failure(w, httptest.NewRequest("GET", "/api/v1/products/missing", nil), 404, "PRODUCT_NOT_FOUND", "not found")
	if e = json.Unmarshal(w.Body.Bytes(), &actual); e != nil {
		t.Fatal(e)
	}
	if e = doc.Components.Schemas["ErrorResponse"].Value.VisitJSON(actual); e != nil {
		t.Fatalf("actual error response: %v", e)
	}
}
