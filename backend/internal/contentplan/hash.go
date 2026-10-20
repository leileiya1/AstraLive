// Package contentplan builds immutable trusted-product plans; it never outputs media.
package contentplan

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

func Hash(s string) string     { h := sha256.Sum256([]byte(s)); return hex.EncodeToString(h[:]) }
func Stamp(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

// Canonical accepts in-process values (not untrusted raw JSON), with sorted keys,
// literal Unicode, no HTML escaping and integer numbers, per durable-live-1.
func Canonical(value any) ([]byte, error) {
	raw, e := json.Marshal(value)
	if e != nil {
		return nil, e
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v any
	if e = d.Decode(&v); e != nil {
		return nil, e
	}
	var check func(any) error
	check = func(x any) error {
		switch n := x.(type) {
		case json.Number:
			if _, e := n.Int64(); e != nil {
				return fmt.Errorf("integer required")
			}
		case map[string]any:
			for _, y := range n {
				if e := check(y); e != nil {
					return e
				}
			}
		case []any:
			for _, y := range n {
				if e := check(y); e != nil {
					return e
				}
			}
		}
		return nil
	}
	if e = check(v); e != nil {
		return nil, e
	}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if e = enc.Encode(v); e != nil {
		return nil, e
	}
	s := strings.TrimSuffix(b.String(), "\n")
	var out strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+1 < len(s) {
			if s[i+1] == '\\' {
				out.WriteString(s[i : i+2])
				i++
				continue
			}
			if i+6 <= len(s) && (s[i:i+6] == `\u2028` || s[i:i+6] == `\u2029`) {
				if s[i+5] == '8' {
					out.WriteRune('\u2028')
				} else {
					out.WriteRune('\u2029')
				}
				i += 5
				continue
			}
		}
		out.WriteByte(s[i])
	}
	return []byte(out.String()), nil
}
func Version(v any) (string, error) {
	b, e := Canonical(v)
	if e != nil {
		return "", e
	}
	return Hash(string(b)), nil
}
