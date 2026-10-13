package runtime

import (
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/metrics"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Operation struct {
	Accepted    bool   `json:"accepted"`
	OperationID string `json:"operationId"`
}
type Health struct {
	Status         string `json:"status"`
	RuntimeVersion string `json:"runtimeVersion"`
	GPU            struct {
		Available bool `json:"available"`
	} `json:"gpu"`
	ActiveSessions int            `json:"activeSessions"`
	Providers      map[string]any `json:"providers"`
}
type Client interface {
	CreateSession(context.Context, any) (Operation, error)
	StartSession(context.Context, string, any) (Operation, error)
	Speak(context.Context, string, any) (Operation, error)
	WebRTCOffer(context.Context, string, runtimeapi.WebRTCOffer) (runtimeapi.WebRTCAnswer, error)
	Interrupt(context.Context, string, any) (Operation, error)
	StopSession(context.Context, string, any) (Operation, error)
	Health(context.Context) (Health, error)
}
type HTTP struct {
	Base   string
	Client *http.Client
}

func New(base string) *HTTP {
	return &HTTP{strings.TrimRight(base, "/"), &http.Client{Timeout: 8 * time.Second}}
}

type Error struct {
	Status int
	Code   string
}

func (e *Error) Error() string { return fmt.Sprintf("runtime status %d: %s", e.Status, e.Code) }
func MapError(err error) (int, string) {
	var e *Error
	if errors.As(err, &e) {
		switch e.Status {
		case 429:
			if knownCode(e.Code) {
				return 429, e.Code
			}
			return 429, "RUNTIME_OVERLOADED"
		case 503:
			if knownCode(e.Code) {
				return 503, e.Code
			}
			return 503, "RUNTIME_UNAVAILABLE"
		case 404:
			if knownCode(e.Code) {
				return 404, e.Code
			}
			return 404, "SESSION_NOT_FOUND"
		case 409:
			if knownCode(e.Code) {
				return 409, e.Code
			}
			return 409, "CONFLICT"
		}
		if e.Status >= 400 && e.Status <= 599 && knownCode(e.Code) {
			return e.Status, e.Code
		}
	}
	return 503, "RUNTIME_UNAVAILABLE"
}
func knownCode(code string) bool {
	switch code {
	case "INVALID_ARGUMENT", "RESOURCE_NOT_FOUND", "CONFLICT", "SESSION_NOT_FOUND", "SESSION_NOT_READY", "SESSION_ALREADY_RUNNING", "SESSION_NOT_RUNNING", "AVATAR_NOT_FOUND", "AVATAR_NOT_READY", "VOICE_NOT_FOUND", "ROOM_NOT_FOUND", "PRODUCT_NOT_FOUND", "RUNTIME_UNAVAILABLE", "RUNTIME_OVERLOADED", "GPU_OUT_OF_MEMORY", "LLM_FAILED", "TTS_FAILED", "AVATAR_RENDER_FAILED", "MEDIA_OUTPUT_FAILED", "WEBRTC_FAILED", "INTERRUPT_FAILED", "EVENT_PUBLISH_FAILED", "INTERNAL_ERROR":
		return true
	}
	return false
}
func (h *HTTP) call(ctx context.Context, method, path string, body any, out any) (err error) {
	op := "create"
	if path == "/internal/v1/health" {
		op = "health"
	} else if strings.HasSuffix(path, "/start") {
		op = "start"
	} else if strings.HasSuffix(path, "/stop") {
		op = "stop"
	} else if strings.HasSuffix(path, "/interrupt") {
		op = "interrupt"
	} else if strings.HasSuffix(path, "/utterances") {
		op = "speak"
	} else if strings.HasSuffix(path, "/webrtc/offer") {
		op = "webrtc"
	}
	begin := time.Now()
	metrics.RuntimeRequests.WithLabelValues(op).Inc()
	defer func() {
		metrics.RuntimeDuration.WithLabelValues(op).Observe(float64(time.Since(begin).Milliseconds()))
		if err != nil {
			metrics.RuntimeErrors.WithLabelValues(op).Inc()
		}
	}()
	var rd io.Reader
	if body != nil {
		b, e := json.Marshal(body)
		if e != nil {
			return e
		}
		rd = bytes.NewReader(b)
	}
	req, e := http.NewRequestWithContext(ctx, method, h.Base+path, rd)
	if e != nil {
		return e
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, e := h.Client.Do(req)
	if e != nil {
		return e
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var x struct {
			Code string `json:"code"`
		}
		_ = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&x)
		return &Error{resp.StatusCode, x.Code}
	}
	if (method == "POST" && resp.StatusCode != 202 && !(strings.HasSuffix(path, "/webrtc/offer") && resp.StatusCode == 200)) || (method == "GET" && resp.StatusCode != 200) {
		return &Error{resp.StatusCode, "INVALID_ARGUMENT"}
	}
	if out != nil {
		return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out)
	}
	return nil
}
func (h *HTTP) command(ctx context.Context, path string, body any) (Operation, error) {
	var op Operation
	e := h.call(ctx, "POST", path, body, &op)
	if e == nil && (!op.Accepted || op.OperationID == "") {
		e = errors.New("runtime returned invalid accepted response")
	}
	return op, e
}
func (h *HTTP) CreateSession(ctx context.Context, v any) (Operation, error) {
	return h.command(ctx, "/internal/v1/sessions", v)
}
func path(id, suffix string) string { return "/internal/v1/sessions/" + url.PathEscape(id) + suffix }
func (h *HTTP) StartSession(ctx context.Context, id string, v any) (Operation, error) {
	return h.command(ctx, path(id, "/start"), v)
}
func (h *HTTP) Speak(ctx context.Context, id string, v any) (Operation, error) {
	return h.command(ctx, path(id, "/utterances"), v)
}
func (h *HTTP) WebRTCOffer(ctx context.Context, id string, offer runtimeapi.WebRTCOffer) (runtimeapi.WebRTCAnswer, error) {
	var answer runtimeapi.WebRTCAnswer
	// Non-trickle signaling waits for Runtime ICE gathering, which may exceed command latency.
	requestClient := *h.Client
	requestClient.Timeout = 30 * time.Second
	requestHTTP := *h
	requestHTTP.Client = &requestClient
	err := requestHTTP.call(ctx, "POST", path(id, "/webrtc/offer"), offer, &answer)
	if err == nil && (answer.Type != runtimeapi.Answer || answer.Sdp == "") {
		err = &Error{Status: 503, Code: "WEBRTC_FAILED"}
	}
	return answer, err
}
func (h *HTTP) Interrupt(ctx context.Context, id string, v any) (Operation, error) {
	return h.command(ctx, path(id, "/interrupt"), v)
}
func (h *HTTP) StopSession(ctx context.Context, id string, v any) (Operation, error) {
	return h.command(ctx, path(id, "/stop"), v)
}
func (h *HTTP) Health(ctx context.Context) (Health, error) {
	var v Health
	e := h.call(ctx, "GET", "/internal/v1/health", nil, &v)
	return v, e
}

// v0.5 remains separate from the frozen v1 interface and DTOs.
func (h *HTTP) Deliver(ctx context.Context, id string, envelope json.RawMessage) error {
	var receipt struct {
		Accepted    bool   `json:"accepted"`
		OperationID string `json:"operationId"`
	}
	err := h.call(ctx, "POST", "/internal/v0.5/sessions/"+url.PathEscape(id)+"/commands", envelope, &receipt)
	if err == nil && (!receipt.Accepted || receipt.OperationID == "") {
		return errors.New("invalid durable acceptance")
	}
	return err
}
func (h *HTTP) Reconcile(ctx context.Context, id, commandID string) (json.RawMessage, error) {
	var raw json.RawMessage
	err := h.call(ctx, "GET", "/internal/v0.5/sessions/"+url.PathEscape(id)+"/commands/"+url.PathEscape(commandID)+"/receipt", nil, &raw)
	return raw, err
}

// EmergencyStop returns a non-durable error even when the local fence was applied.
func (h *HTTP) EmergencyStop(ctx context.Context, id string) error {
	return h.call(ctx, "POST", "/internal/v0.5/sessions/"+url.PathEscape(id)+"/emergency-stop", map[string]any{}, nil)
}
