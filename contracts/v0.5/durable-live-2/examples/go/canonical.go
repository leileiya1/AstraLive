// Normative CCR hash-vector runner, NOT a production decoder or journal.
// Run: go run contracts/v0.5/durable-live-2/examples/go/canonical.go <vectors.json>
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"sort"
	"strconv"
	"unicode/utf8"
)

// Canonical matches exact Unicode, control escaping and integer rules in v2.
func Canonical(value any) ([]byte, error) {
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

func run(path string) error {
	raw, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	var rows []struct {
		Name          string `json:"name"`
		Value         any    `json:"value"`
		CanonicalUTF8 string `json:"canonicalUtf8"`
		SHA256        string `json:"sha256"`
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if e = decoder.Decode(&rows); e != nil {
		return e
	}
	if _, e = decoder.Token(); e != io.EOF {
		return fmt.Errorf("trailing input")
	}
	result := map[string]string{}
	for _, r := range rows {
		b, e := Canonical(r.Value)
		if e != nil {
			return e
		}
		h := sha256.Sum256(b)
		hash := hex.EncodeToString(h[:])
		if string(b) != r.CanonicalUTF8 || hash != r.SHA256 {
			return fmt.Errorf("vector mismatch: %s", r.Name)
		}
		result[r.Name] = hash
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
func main() {
	if len(os.Args) != 2 {
		panic("supply trusted hash-vectors.json")
	}
	if e := run(os.Args[1]); e != nil {
		panic(e)
	}
}
