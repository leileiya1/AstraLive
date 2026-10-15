package durablelive

import (
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

//go:embed spec/*.json
var specs embed.FS

const RevisionName = "durable-live-1"
const MaxBody = 256 * 1024
const maxInteger = int64(9007199254740991)

type Object = map[string]any

var schemaOnce sync.Once
var compiled = map[string]*jsonschema.Schema{}
var schemaErr error
var integerPattern = regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`)

func fault(code string) error { return &Fault{Code: code} }

type Fault struct{ Code string }

func (e *Fault) Error() string { return e.Code }

// Decode rejects duplicate keys, floats, nonfinite values and unsafe integers
// before JSON Schema sees a value. Go's normal Unmarshal silently accepts duplicates.
func Decode(raw []byte) (Object, error) {
	if len(raw) > MaxBody || !utf8.Valid(raw) {
		return nil, fault("INVALID_ARGUMENT")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	v, e := readValue(d)
	if e != nil {
		return nil, e
	}
	if _, e = d.Token(); e != io.EOF {
		return nil, fault("INVALID_ARGUMENT")
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, fault("INVALID_ARGUMENT")
	}
	return m, nil
}
func readValue(d *json.Decoder) (any, error) {
	t, e := d.Token()
	if e != nil {
		return nil, fault("INVALID_ARGUMENT")
	}
	switch v := t.(type) {
	case json.Delim:
		if v == '{' {
			m := Object{}
			for d.More() {
				k, e := d.Token()
				if e != nil {
					return nil, e
				}
				key, ok := k.(string)
				if !ok {
					return nil, fault("INVALID_ARGUMENT")
				}
				if _, ok = m[key]; ok {
					return nil, fault("INVALID_ARGUMENT")
				}
				x, e := readValue(d)
				if e != nil {
					return nil, e
				}
				m[key] = x
			}
			_, e = d.Token()
			return m, e
		}
		if v == '[' {
			a := []any{}
			for d.More() {
				x, e := readValue(d)
				if e != nil {
					return nil, e
				}
				a = append(a, x)
			}
			_, e = d.Token()
			return a, e
		}
		return nil, fault("INVALID_ARGUMENT")
	case json.Number:
		if !integerPattern.MatchString(string(v)) {
			return nil, fault("INVALID_ARGUMENT")
		}
		n, e := v.Int64()
		if e != nil || n > maxInteger || n < -maxInteger {
			return nil, fault("INVALID_ARGUMENT")
		}
		return v, nil
	default:
		return v, nil
	}
}
func validate(def string, v any) error {
	schemaOnce.Do(func() {
		c := jsonschema.NewCompiler()
		c.AssertFormat = true
		b, _ := specs.ReadFile("spec/schema.json")
		var root Object
		_ = json.Unmarshal(b, &root)
		schemaErr = c.AddResource("https://astralive.local/schema.json", bytes.NewReader(b))
		if schemaErr != nil {
			return
		}
		for k := range root["$defs"].(map[string]any) {
			s, e := c.Compile("https://astralive.local/schema.json#/$defs/" + k)
			if e != nil {
				schemaErr = e
				return
			}
			compiled[k] = s
		}
	})
	if schemaErr != nil {
		return schemaErr
	}
	s, ok := compiled[def]
	if !ok {
		return fmt.Errorf("unknown schema %s", def)
	}
	if e := s.Validate(v); e != nil {
		return fault("INVALID_ARGUMENT")
	}
	return nil
}

// Canonical uses Unicode codepoint key ordering and exact UTF-8, without HTML,
// slash, U+2028/2029 escaping or string normalization. It matches frozen vectors.
func Canonical(v any) ([]byte, error) {
	var b bytes.Buffer
	var emit func(any) error
	quote := func(s string) {
		q, _ := json.Marshal(s)
		q = bytes.ReplaceAll(q, []byte(`\u003c`), []byte("<"))
		q = bytes.ReplaceAll(q, []byte(`\u003e`), []byte(">"))
		q = bytes.ReplaceAll(q, []byte(`\u0026`), []byte("&"))
		q = bytes.ReplaceAll(q, []byte(`\u2028`), []byte("\u2028"))
		q = bytes.ReplaceAll(q, []byte(`\u2029`), []byte("\u2029"))
		b.Write(q)
	}
	emit = func(x any) error {
		switch t := x.(type) {
		case nil:
			b.WriteString("null")
		case bool:
			if t {
				b.WriteString("true")
			} else {
				b.WriteString("false")
			}
		case string:
			quote(t)
		case json.Number:
			if !integerPattern.MatchString(string(t)) {
				return fault("INVALID_ARGUMENT")
			}
			n, e := t.Int64()
			if e != nil || n > maxInteger || n < -maxInteger {
				return fault("INVALID_ARGUMENT")
			}
			b.WriteString(strconv.FormatInt(n, 10))
		case int64:
			return emit(json.Number(strconv.FormatInt(t, 10)))
		case int:
			return emit(int64(t))
		case []any:
			b.WriteByte('[')
			for i, v := range t {
				if i > 0 {
					b.WriteByte(',')
				}
				if e := emit(v); e != nil {
					return e
				}
			}
			b.WriteByte(']')
		case map[string]any:
			keys := make([]string, 0, len(t))
			for k := range t {
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
				if e := emit(t[k]); e != nil {
					return e
				}
			}
			b.WriteByte('}')
		default:
			return fmt.Errorf("non canonical type %T", x)
		}
		return nil
	}
	if e := emit(v); e != nil {
		return nil, e
	}
	return b.Bytes(), nil
}
func hash(v any) string {
	b, e := Canonical(v)
	if e != nil {
		panic(e)
	}
	return textHash(string(b))
}
func textHash(v string) string { h := sha256.Sum256([]byte(v)); return hex.EncodeToString(h[:]) }
func commandHash(m Object) string {
	c := Object{}
	for k, v := range m {
		if k != "requestHash" {
			c[k] = v
		}
	}
	return hash(c)
}
func str(m Object, k string) string { v, _ := m[k].(string); return v }
func num(m Object, k string) int64 {
	switch v := m[k].(type) {
	case json.Number:
		n, _ := v.Int64()
		return n
	case int64:
		return v
	case int:
		return int64(v)
	}
	return 0
}
func obj(m Object, k string) Object { v, _ := m[k].(map[string]any); return v }
func arr(m Object, k string) []any  { v, _ := m[k].([]any); return v }
func stamp(t time.Time) string      { return t.UTC().Format("2006-01-02T15:04:05.000000Z") }
func instant(v any) time.Time       { s, _ := v.(string); t, _ := time.Parse(time.RFC3339Nano, s); return t }
func wire(v any) Object {
	b, _ := json.Marshal(v)
	m, e := Decode(b)
	if e != nil {
		panic(e)
	}
	return m
}
func contains(a []any, v string) bool {
	for _, x := range a {
		if x == v {
			return true
		}
	}
	return false
}
func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func staticMessage(code string) string { return strings.ReplaceAll(code, "_", " ") }
