// Package durability implements the opt-in v0.5 PostgreSQL command journal.
package durability

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strconv"
)

const MaxEpoch int64 = 9007199254740991

var ErrConflict = errors.New("COMMAND_CONFLICT")
var ErrFence = errors.New("LEASE_LOST")
var ErrSealed = errors.New("RUN_SEALED")

type Command struct {
	SchemaVersion      string          `json:"schemaVersion"`
	CommandID          string          `json:"commandId"`
	SessionID          string          `json:"sessionId"`
	RunEpoch           int64           `json:"runEpoch"`
	TraceID            string          `json:"traceId"`
	CommandType        string          `json:"commandType"`
	IdempotencyKey     string          `json:"idempotencyKey"`
	RequestFingerprint string          `json:"requestFingerprint"`
	CommandSeq         int64           `json:"commandSeq"`
	CreatedAt          string          `json:"createdAt"`
	Payload            json.RawMessage `json:"payload"`
	NarrationID        json.RawMessage `json:"narrationId,omitempty"`
	SegmentID          json.RawMessage `json:"segmentId,omitempty"`
	TimelineEpoch      int64           `json:"timelineEpoch,omitempty"`
	Lane               string          `json:"lane,omitempty"`
}

// Canonical rejects duplicate keys, floating point numbers and integers outside JSON's safe range.
// Unlike encoding/json's default encoder, Unicode and HTML characters remain unescaped.
func Canonical(raw []byte) ([]byte, error) { return canonical(raw, true) }
func canonical(raw []byte, strict bool) ([]byte, error) {
	return canonicalDomain(raw, strict, false)
}

// TimelineCanonical permits the frozen Worker wire integer only in typed proof
// carriers. Command/payload and every other integer keep the business JSON bound.
func TimelineCanonical(raw []byte) ([]byte, error) { return canonicalDomain(raw, true, true) }
func timelineWorkerPath(path []any) bool {
	if len(path) == 3 && path[0] == "proof" && (path[1] == "identity" || path[1] == "descriptor") && path[2] == "workerGenerationId" {
		return true
	}
	if len(path) == 4 && path[0] == "proof" && path[1] == "commit" && (path[2] == "identity" || path[2] == "descriptor") && path[3] == "workerGenerationId" {
		return true
	}
	if len(path) == 5 && path[0] == "proof" && path[1] == "sinkReceipts" && path[3] == "identity" && path[4] == "workerGenerationId" {
		_, index := path[2].(int)
		return index
	}
	return false
}
func canonicalDomain(raw []byte, strict, workerProof bool) ([]byte, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var parse func([]any) (any, error)
	parse = func(path []any) (any, error) {
		t, e := d.Token()
		if e != nil {
			return nil, e
		}
		if workerProof && timelineWorkerPath(path) && t != nil {
			number, ok := t.(json.Number)
			if !ok {
				return nil, ErrConflict
			}
			n, err := strconv.ParseInt(string(number), 10, 64)
			if err != nil || n < 1 {
				return nil, ErrConflict
			}
			return json.Number(strconv.FormatInt(n, 10)), nil
		}
		switch v := t.(type) {
		case json.Delim:
			if v == '{' {
				m := map[string]any{}
				for d.More() {
					k, e := d.Token()
					if e != nil {
						return nil, e
					}
					s, ok := k.(string)
					if !ok {
						return nil, ErrConflict
					}
					if _, ok = m[s]; ok {
						return nil, ErrConflict
					}
					m[s], e = parse(append(path, s))
					if e != nil {
						return nil, e
					}
				}
				_, e = d.Token()
				return m, e
			}
			if v == '[' {
				a := []any{}
				for d.More() {
					x, e := parse(append(path, len(a)))
					if e != nil {
						return nil, e
					}
					a = append(a, x)
				}
				_, e = d.Token()
				return a, e
			}
			return nil, ErrConflict
		case json.Number:
			n, e := strconv.ParseInt(string(v), 10, 64)
			if strict && (e != nil || n > MaxEpoch || n < -MaxEpoch) {
				return nil, ErrConflict
			}
			if strict {
				return json.Number(strconv.FormatInt(n, 10)), nil
			}
			return v, nil
		default:
			return v, nil
		}
	}
	v, e := parse(nil)
	if e != nil {
		return nil, e
	}
	if _, e = d.Token(); e != io.EOF {
		return nil, ErrConflict
	}
	var b bytes.Buffer
	var encode func(any)
	quote := func(s string) {
		b.WriteByte('"')
		for _, r := range s {
			switch r {
			case '"':
				b.WriteString(`\"`)
			case '\\':
				b.WriteString(`\\`)
			case '\b':
				b.WriteString(`\b`)
			case '\f':
				b.WriteString(`\f`)
			case '\n':
				b.WriteString(`\n`)
			case '\r':
				b.WriteString(`\r`)
			case '\t':
				b.WriteString(`\t`)
			default:
				if r < 32 {
					fmt.Fprintf(&b, `\u%04x`, r)
				} else {
					b.WriteRune(r)
				}
			}
		}
		b.WriteByte('"')
	}
	encode = func(v any) {
		switch x := v.(type) {
		case map[string]any:
			keys := make([]string, 0, len(x))
			for k := range x {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			b.WriteByte('{')
			for i, k := range keys {
				if i > 0 {
					b.WriteByte(',')
				}
				quote(k)
				b.WriteByte(':')
				encode(x[k])
			}
			b.WriteByte('}')
		case []any:
			b.WriteByte('[')
			for i, v := range x {
				if i > 0 {
					b.WriteByte(',')
				}
				encode(v)
			}
			b.WriteByte(']')
		case string:
			quote(x)
		case json.Number:
			b.WriteString(string(x))
		case bool:
			b.WriteString(strconv.FormatBool(x))
		case nil:
			b.WriteString("null")
		}
	}
	encode(v)
	return b.Bytes(), nil
}
func Hash(raw []byte) (string, error) {
	b, e := Canonical(raw)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(h[:]), nil
}
func Fingerprint(raw []byte) (string, error) {
	if _, e := Canonical(raw); e != nil {
		return "", e
	}
	var m map[string]json.RawMessage
	if e := json.Unmarshal(raw, &m); e != nil {
		return "", e
	}
	filtered := map[string]json.RawMessage{}
	for _, k := range []string{"schemaVersion", "sessionId", "runEpoch", "commandType", "narrationId", "segmentId", "timelineEpoch", "lane", "payload"} {
		if v, ok := m[k]; ok {
			filtered[k] = v
		}
	}
	b, e := json.Marshal(filtered)
	if e != nil {
		return "", e
	}
	return Hash(b)
}
func (c Command) Validate() error {
	if c.SchemaVersion != "0.5" || c.CommandID == "" || c.SessionID == "" || c.TraceID == "" || c.IdempotencyKey == "" || c.CommandSeq < 1 || c.CommandSeq > MaxEpoch || c.RunEpoch < 1 || c.RunEpoch > MaxEpoch || len(c.Payload) == 0 {
		return fmt.Errorf("invalid command")
	}
	return nil
}

func EventHash(raw []byte) (string, error) {
	b, e := canonical(raw, false)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(h[:]), nil
}

func TimelineHash(raw []byte) (string, error) {
	b, e := TimelineCanonical(raw)
	if e != nil {
		return "", e
	}
	hash := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(hash[:]), nil
}
