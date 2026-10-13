package httpapi

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/generated/runtimeapi"
	"astralive/backend/internal/app"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/metrics"
	"astralive/backend/internal/runtime"
	"astralive/backend/internal/sse"
	"astralive/backend/internal/userconfig"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
)

func (h *Server) createSession(w http.ResponseWriter, r *http.Request) {
	var v struct {
		RoomID string `json:"roomId"`
	}
	if !decode(w, r, &v) {
		return
	}
	if !valid(v.RoomID) {
		failure(w, r, 422, "INVALID_ARGUMENT", "roomId required")
		return
	}
	if _, e := h.S.Q.GetRoom(r.Context(), v.RoomID); e != nil {
		dbFail(w, r, e, "ROOM_NOT_FOUND")
		return
	}
	var x dbgen.LiveSession
	var e error
	if h.Config != nil && h.Config.IntegrationEnabled {
		x, e = h.Config.CreateBusinessSession(r.Context(), userconfig.ScopeFromContext(r.Context()), v.RoomID)
	} else {
		x, e = h.S.Q.CreateSession(r.Context(), dbgen.CreateSessionParams{ID: ids.New("session"), RoomID: v.RoomID})
		if e == nil && !h.claim(w, r, "session", x.ID) {
			return
		}
	}
	if e != nil {
		if h.Config != nil {
			configFailure(w, r, e)
		} else {
			dbFail(w, r, e, "")
		}
		return
	}

	metrics.LiveSessionCount.Inc()
	respond(w, r, 201, session(x))
}
func (h *Server) getSession(w http.ResponseWriter, r *http.Request) {
	x, e := h.S.Q.GetSession(r.Context(), chi.URLParam(r, "sessionId"))
	if e != nil {
		dbFail(w, r, e, "SESSION_NOT_FOUND")
		return
	}
	respond(w, r, 200, session(x))
}
func (h *Server) startSession(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "sessionId")
	op, e := h.S.Start(r.Context(), id, ids.New("trace"))
	if e != nil {
		runtimeFail(w, r, e)
		return
	}
	respond(w, r, 202, map[string]any{"operationId": op, "sessionId": id, "status": "PREPARING"})
}
func (h *Server) stopSession(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "sessionId")
	op, e := h.S.Stop(r.Context(), id, ids.New("trace"))
	if e != nil {
		runtimeFail(w, r, e)
		return
	}
	respond(w, r, 202, map[string]any{"operationId": op, "sessionId": id})
}
func (h *Server) createUtterance(w http.ResponseWriter, r *http.Request) {
	var v struct {
		Text            string `json:"text"`
		Priority        int32  `json:"priority"`
		InterruptPolicy string `json:"interruptPolicy"`
		Source          string `json:"source"`
	}
	if !decode(w, r, &v) {
		return
	}
	if !valid(v.Text) || !oneOf(v.InterruptPolicy, "NONE", "INTERRUPT_LOWER_PRIORITY", "FORCE") || !oneOf(v.Source, "OPERATOR", "PLATFORM_EVENT", "AUTO_SCRIPT", "SYSTEM") {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid utterance")
		return
	}
	u, e := h.S.Speak(r.Context(), chi.URLParam(r, "sessionId"), v.Text, v.Priority, v.InterruptPolicy, v.Source, ids.New("trace"), nil)
	if e != nil {
		runtimeFail(w, r, e)
		return
	}
	respond(w, r, 202, map[string]any{"utteranceId": u.ID, "status": u.Status})
}
func (h *Server) webrtcOffer(w http.ResponseWriter, r *http.Request) {
	var offer runtimeapi.WebRTCOffer
	if !decode(w, r, &offer) {
		return
	}
	if offer.Type != runtimeapi.Offer || !valid(offer.Sdp) {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid WebRTC offer")
		return
	}
	id := chi.URLParam(r, "sessionId")
	se, err := h.S.Q.GetSession(r.Context(), id)
	if err != nil {
		dbFail(w, r, err, "SESSION_NOT_FOUND")
		return
	}
	if se.Status != "LIVE" && se.Status != "DEGRADED" {
		failure(w, r, 409, "SESSION_NOT_RUNNING", "session is not running")
		return
	}
	answer, err := h.S.Runtime.WebRTCOffer(r.Context(), id, offer)
	if err != nil {
		status := 503
		if re, ok := err.(*runtime.Error); ok && re.Status >= 500 && re.Status != 503 {
			status = 500
		}
		failure(w, r, status, "WEBRTC_FAILED", "WebRTC negotiation failed")
		return
	}
	respond(w, r, 200, answer)
}
func oneOf(v string, values ...string) bool {
	for _, x := range values {
		if v == x {
			return true
		}
	}
	return false
}
func (h *Server) interrupt(w http.ResponseWriter, r *http.Request) {
	var v struct {
		Reason string `json:"reason"`
	}
	if !decode(w, r, &v) {
		return
	}
	if !valid(v.Reason) {
		failure(w, r, 422, "INVALID_ARGUMENT", "reason required")
		return
	}
	id := chi.URLParam(r, "sessionId")
	se, e := h.S.Q.GetSession(r.Context(), id)
	if e != nil {
		dbFail(w, r, e, "SESSION_NOT_FOUND")
		return
	}
	if se.Status != "LIVE" && se.Status != "DEGRADED" {
		failure(w, r, 409, "SESSION_NOT_RUNNING", "session is not running")
		return
	}
	op, e := h.S.Interrupt(r.Context(), id, ids.New("trace"), v.Reason)
	if e != nil {
		runtimeFail(w, r, e)
		return
	}
	respond(w, r, 202, map[string]any{"operationId": op.OperationID, "sessionId": id})
}
func (h *Server) events(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "sessionId")
	se, e := h.S.Q.GetSession(r.Context(), id)
	if e != nil {
		dbFail(w, r, e, "SESSION_NOT_FOUND")
		return
	}
	fl, ok := w.(http.Flusher)
	if !ok {
		failure(w, r, 500, "INTERNAL_ERROR", "stream unsupported")
		return
	}
	ch, cancel := h.S.Hub.Subscribe(id)
	defer cancel()
	metrics.SSEConnections.Inc()
	defer metrics.SSEConnections.Dec()
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(200)
	snapshot, _ := json.Marshal(map[string]any{"sessionId": id, "status": se.Status})
	_, _ = fmt.Fprintf(w, "event: snapshot\ndata: %s\n\n", snapshot)
	fl.Flush()
	// Persisted recent events bridge the gap between the snapshot query and subscription.
	recent, e := h.S.Q.RecentEvents(r.Context(), dbgen.RecentEventsParams{SessionID: id, Limit: 20})
	if e == nil {
		for i := len(recent) - 1; i >= 0; i-- {
			var ev struct {
				EventType string `json:"eventType"`
			}
			if json.Unmarshal(recent[i], &ev) == nil {
				n := app.SSEName(ev.EventType)
				_, _ = fmt.Fprintf(w, "event: %s\ndata: %s\n\n", n, recent[i])
			}
		}
		fl.Flush()
	}
	tick := time.NewTicker(15 * time.Second)
	defer tick.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case m := <-ch:
			writeEvent(w, m)
			fl.Flush()
		case <-tick.C:
			if h.Config != nil {
				cookie, err := r.Cookie(userconfig.ProductCookie)
				if err != nil {
					return
				}
				if _, err = h.Config.Authenticate(r.Context(), cookie.Value); err != nil {
					return
				}
			}
			writeHeartbeat(w, time.Now())
			fl.Flush()
		}
	}
}
func writeHeartbeat(w http.ResponseWriter, at time.Time) {
	data, _ := json.Marshal(map[string]string{"timestamp": at.UTC().Format(time.RFC3339Nano)})
	_, _ = fmt.Fprintf(w, "event: heartbeat\ndata: %s\n\n", data)
}
func writeEvent(w http.ResponseWriter, m sse.Message) {
	_, _ = fmt.Fprintf(w, "event: %s\ndata: %s\n\n", m.Name, m.Data)
}
func (h *Server) devPlatformEvent(w http.ResponseWriter, r *http.Request) {
	var v struct {
		EventType string `json:"eventType"`
		RoomID    string `json:"roomId"`
		User      struct {
			ExternalID string `json:"externalId"`
			Nickname   string `json:"nickname"`
		} `json:"user"`
		Payload struct {
			Text string `json:"text"`
		} `json:"payload"`
	}
	if !decode(w, r, &v) {
		return
	}
	if v.EventType != "COMMENT" || !valid(v.RoomID) || !valid(v.User.ExternalID) || !valid(v.User.Nickname) || !valid(v.Payload.Text) {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid platform event")
		return
	}
	if _, err := h.S.Q.GetRoom(r.Context(), v.RoomID); err != nil {
		dbFail(w, r, err, "ROOM_NOT_FOUND")
		return
	}
	se, err := h.S.Q.GetLatestLiveSessionByRoom(r.Context(), v.RoomID)
	if err == pgx.ErrNoRows {
		failure(w, r, 409, "SESSION_NOT_RUNNING", "no running session for room")
		return
	}
	if err != nil {
		dbFail(w, r, err, "")
		return
	}
	platform := &runtimeapi.PlatformContext{EventType: runtimeapi.COMMENT}
	platform.User.ExternalId = v.User.ExternalID
	platform.User.Nickname = v.User.Nickname
	u, err := h.S.Speak(r.Context(), se.ID, v.Payload.Text, 80, "INTERRUPT_LOWER_PRIORITY", "PLATFORM_EVENT", ids.New("trace"), platform)
	if err != nil {
		runtimeFail(w, r, err)
		return
	}
	respond(w, r, 202, map[string]any{"utteranceId": u.ID, "status": u.Status})
}
