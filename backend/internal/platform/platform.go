// Package platform defines trusted room mapping and normalized untrusted audience data.
package platform

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

type EventType string

const (
	Comment EventType = "COMMENT"
	Like    EventType = "LIKE"
	Gift    EventType = "GIFT"
	Follow  EventType = "FOLLOW"
	Enter   EventType = "ENTER"
)

type Event struct {
	EventID         string     `json:"eventId"`
	Platform        string     `json:"platform"`
	SourceEventID   string     `json:"sourceEventId,omitempty"`
	PlatformRoomID  string     `json:"platformRoomId"`
	InternalRoomID  string     `json:"internalRoomId"`
	SessionID       string     `json:"sessionId"`
	EventType       EventType  `json:"eventType"`
	UserExternalID  string     `json:"userExternalId"`
	Nickname        string     `json:"nickname"`
	Content         string     `json:"content"`
	SourceTimestamp *time.Time `json:"sourceTimestamp,omitempty"`
	ReceivedAt      time.Time  `json:"receivedAt"`
	TraceID         string     `json:"traceId"`
	Transport       string     `json:"transport"`
}
type Capabilities struct {
	Types          []EventType
	Transports     []string
	Reconnect      bool
	SourceIdentity bool
}
type Connection struct {
	State      string `json:"state"`
	Received   int    `json:"received"`
	Reconnects int    `json:"reconnects"`
	ErrorClass string `json:"errorClass,omitempty"`
	Heartbeats int    `json:"heartbeats"`
}
type EventSink interface {
	Receive(context.Context, Event) error
}
type Adapter interface {
	Start(context.Context, EventSink) error
	Stop()
	Health() Connection
	Capabilities() Capabilities
}
type ErrorClass string

const (
	Unauthorized ErrorClass = "UNAUTHORIZED"
	Invalid      ErrorClass = "INVALID"
	Unsupported  ErrorClass = "UNSUPPORTED"
	Transient    ErrorClass = "TRANSIENT"
	Cancelled    ErrorClass = "CANCELLED"
)

type Error struct{ Class ErrorClass }

func (e *Error) Error() string { return string(e.Class) }
func Classify(err error) ErrorClass {
	if errors.Is(err, context.Canceled) {
		return Cancelled
	}
	var e *Error
	if errors.As(err, &e) {
		return e.Class
	}
	return Transient
}

type Mapping struct{ Platform, PlatformRoomID, RoomID, SessionID string }

// Normalize ignores caller timestamps/trace IDs/internal IDs except for validating mapping.
// Source IDs are never invented. EventID is explicitly an internal stable receipt identity.
func Normalize(e Event, m Mapping, now time.Time) (Event, error) {
	if m.Platform == "" || m.PlatformRoomID == "" || m.RoomID == "" || m.SessionID == "" {
		return Event{}, &Error{Invalid}
	}
	if e.Platform != m.Platform || e.PlatformRoomID != m.PlatformRoomID || e.InternalRoomID != m.RoomID || e.SessionID != m.SessionID {
		return Event{}, &Error{Unauthorized}
	}
	if e.EventType != Comment {
		return Event{}, &Error{Unsupported}
	}
	if !utf8.ValidString(e.Content) || len(e.Content) > 2048 || len(e.Nickname) > 128 || len(e.UserExternalID) > 128 || len(e.SourceEventID) > 256 || e.UserExternalID == "" || (e.Transport == "" || len(e.Transport) > 32) {
		return Event{}, &Error{Invalid}
	}
	e.Content = strings.TrimSpace(strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return -1
		}
		return r
	}, e.Content))
	if e.Content == "" {
		return Event{}, &Error{Invalid}
	}
	e.ReceivedAt = now
	e.TraceID = ""
	e.EventID = ""
	if e.SourceEventID != "" {
		sum := sha256.Sum256([]byte(strings.Join([]string{m.Platform, m.PlatformRoomID, m.RoomID, m.SessionID, e.SourceEventID}, "\x00")))
		e.EventID = "receipt_" + hex.EncodeToString(sum[:])
		e.TraceID = "interaction_" + hex.EncodeToString(sum[:])
	}
	return e, nil
}
