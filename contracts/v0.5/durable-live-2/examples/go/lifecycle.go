// Trusted fixture timing/binding validator; NOT a production authorization service.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"time"
	"unicode/utf8"
)

type row = map[string]any

func str(r row, k string) string { return r[k].(string) }
func at(r row, k string) time.Time {
	t, e := time.Parse(time.RFC3339Nano, str(r, k))
	if e != nil {
		panic(e)
	}
	return t
}
func need(ok bool, why string) {
	if !ok {
		panic(why)
	}
}
func lifecycleCanonical(value any) ([]byte, error) {
	var b bytes.Buffer
	quote := func(s string) error {
		if !utf8.ValidString(s) {
			return fmt.Errorf("invalid UTF8")
		}
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
		return nil
	}
	var emit func(any) error
	emit = func(v any) error {
		switch x := v.(type) {
		case nil:
			b.WriteString("null")
		case bool:
			b.WriteString(strconv.FormatBool(x))
		case string:
			return quote(x)
		case json.Number:
			if !regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`).MatchString(x.String()) {
				return fmt.Errorf("noninteger")
			}
			n, e := x.Int64()
			if e != nil || n > 9007199254740991 || n < -9007199254740991 {
				return fmt.Errorf("unsafe integer")
			}
			b.WriteString(strconv.FormatInt(n, 10))
		case []any:
			b.WriteByte('[')
			for n, item := range x {
				if n > 0 {
					b.WriteByte(',')
				}
				if e := emit(item); e != nil {
					return e
				}
			}
			b.WriteByte(']')
		case map[string]any:
			keys := make([]string, 0, len(x))
			for key := range x {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			b.WriteByte('{')
			for n, key := range keys {
				if n > 0 {
					b.WriteByte(',')
				}
				if e := quote(key); e != nil {
					return e
				}
				b.WriteByte(':')
				if e := emit(x[key]); e != nil {
					return e
				}
			}
			b.WriteByte('}')
		default:
			return fmt.Errorf("noncanonical value %T", v)
		}
		return nil
	}
	if e := emit(value); e != nil {
		return nil, e
	}
	return b.Bytes(), nil
}

func main() {
	raw, e := os.ReadFile(os.Args[1])
	if e != nil {
		panic(e)
	}
	var trace struct {
		Registration     row   `json:"registration"`
		Grant            row   `json:"grant"`
		Consumption      row   `json:"consumption"`
		Observations     []row `json:"observations"`
		Permits          []row `json:"permits"`
		Handoffs         []row `json:"handoffs"`
		GlobalStartCount int   `json:"globalStartCount"`
		UnitGrantCount   int   `json:"unitGrantCount"`
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if e = d.Decode(&trace); e != nil {
		panic(e)
	}
	g, b := trace.Grant, trace.Consumption
	need(trace.Registration["state"] == "ACTIVE", "REGISTRATION_REVOKED")
	registered, ok := trace.Registration["binding"].(map[string]any)
	need(ok, "BOOTSTRAP_REQUIRED")
	canonical, err := lifecycleCanonical(registered)
	need(err == nil, "invalid registration canonical form")
	hash := sha256.Sum256(canonical)
	need(hex.EncodeToString(hash[:]) == trace.Registration["registrationHash"], "registration hash mismatch")
	for key, value := range registered {
		if current, exists := b[key]; exists {
			need(reflect.DeepEqual(value, current), "bootstrap identity mismatch")
		}
	}
	need(!at(trace.Registration, "registeredAt").After(at(b, "consumedAt")), "BOOTSTRAP_REQUIRED")
	issued, consumed, deadline := at(g, "issuedAt"), at(b, "consumedAt"), at(g, "expiresAt")
	need(!consumed.Before(issued) && consumed.Before(deadline), "GRANT_EXPIRED")
	need(str(g, "authorizationScope") == "UNIT_START_ONCE", "wrong scope")
	need(g["grantId"] == b["grantId"], "grant identity")
	keys := []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "producerIncarnation", "answerId", "artifactId", "artifactHash", "generationId"}
	for _, key := range keys {
		if value, ok := g[key]; ok {
			need(reflect.DeepEqual(value, b[key]), "grant binding")
		}
	}
	observations, permits := map[string]row{}, map[string]row{}
	for _, o := range trace.Observations {
		id := str(o, "observationId")
		need(observations[id] == nil, "duplicate observation")
		observations[id] = o
	}
	for _, p := range trace.Permits {
		id := str(p, "permitId")
		need(permits[id] == nil, "duplicate permit")
		permits[id] = p
	}
	first := observations[str(g, "factObservationId")]
	check := func(p row, t time.Time) row {
		o := observations[str(p, "factObservationId")]
		for _, r := range []row{p, o} {
			for _, key := range keys {
				need(reflect.DeepEqual(r[key], b[key]), "renewed identity mismatch")
			}
		}
		need(p["guardianIncarnation"] == b["guardianIncarnation"], "guardian restart")
		need(!t.Before(at(p, "issuedAt")) && t.Before(at(p, "expiresAt")), "permit expired")
		need(at(p, "expiresAt").Sub(at(p, "issuedAt")) <= time.Second, "unbounded permit")
		need(!t.Before(at(o, "verifiedAt")) && t.Before(at(o, "validUntil")), "FACT_EXPIRED")
		need(at(o, "validUntil").Sub(at(o, "verifiedAt")) <= 2*time.Second, "unbounded observation")
		for _, key := range []string{"productSnapshotVersion", "factSetHash"} {
			need(reflect.DeepEqual(o[key], first[key]), "facts changed")
		}
		return o
	}
	check(permits[str(g, "permitId")], consumed)
	previous := consumed
	for _, h := range trace.Handoffs {
		t := at(h, "at")
		need(!t.Before(previous) && h["executionId"] == b["executionId"], "execution changed")
		o := check(permits[str(h, "permitId")], t)
		need(o["observationId"] == h["factObservationId"], "observation mismatch")
		previous = t
	}
	need(trace.GlobalStartCount == 1 && trace.UnitGrantCount == 1, "repeated authorization")
	result := map[string]int64{"handoffs": int64(len(trace.Handoffs)), "lastOffsetMs": previous.Sub(issued).Milliseconds(), "initialConsumeWindowMs": deadline.Sub(issued).Milliseconds(), "globalStartCount": 1, "unitGrantCount": 1}
	if e = json.NewEncoder(os.Stdout).Encode(result); e != nil {
		panic(fmt.Sprint(e))
	}
}
