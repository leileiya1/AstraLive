package userconfig

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testVault(t *testing.T) Vault {
	t.Helper()
	path := filepath.Join(t.TempDir(), "keyring.json")
	writeRing(t, path, "a", map[string]string{"a": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("a", 32)))})
	return Vault{path}
}
func writeRing(t *testing.T, path, active string, keys map[string]string) {
	t.Helper()
	b, _ := json.Marshal(Keyring{active, keys})
	if e := os.WriteFile(path, b, 0600); e != nil {
		t.Fatal(e)
	}
}
func TestVaultTamperIsolationAndRotation(t *testing.T) {
	v := testVault(t)
	scope := Scope{"tenant-a", "user-a"}
	c, e := v.Seal(scope, "profile-a", "synthetic-test-credential")
	if e != nil {
		t.Fatal(e)
	}
	if strings.Contains(string(c.Ciphertext), "synthetic-test-credential") {
		t.Fatal("plaintext ciphertext")
	}
	for _, other := range []Scope{{"tenant-b", "user-a"}, {"tenant-a", "user-b"}} {
		if _, e = v.Open(other, c); e == nil {
			t.Fatal("cross scope decryption")
		}
	}
	bad := c
	bad.Ciphertext = append([]byte{}, c.Ciphertext...)
	bad.Ciphertext[len(bad.Ciphertext)-1] ^= 1
	if _, e = v.Open(scope, bad); e == nil {
		t.Fatal("tampered credential accepted")
	}
	writeRing(t, v.Path, "b", map[string]string{"a": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("a", 32))), "b": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("b", 32)))})
	rotated, e := v.Seal(scope, "profile-a", "new-synthetic-credential")
	if e != nil || rotated.KeyID != "b" {
		t.Fatal("hot master key rotation", e)
	}
	if p, e := v.Open(scope, c); e != nil || p != "synthetic-test-credential" {
		t.Fatal("old key unavailable", e)
	}
	if e = os.Chmod(v.Path, 0644); e != nil {
		t.Fatal(e)
	}
	if _, e = v.Open(scope, c); e == nil {
		t.Fatal("unsafe permissions accepted")
	}
}
func TestEndpointAndAddressPolicy(t *testing.T) {
	hosts := map[string]bool{"api.deepseek.com": true, "allowed.example": true, "127.0.0.1": true}
	for _, raw := range []string{"http://api.deepseek.com", "https://127.0.0.1", "https://api.deepseek.com:444", "https://user:pass@api.deepseek.com", "https://allowed.example?key=hidden", "https://allowed.example/#hidden", "https://allowed.example/metadata", "https://not-allowed.example", "https://[::1]"} {
		if _, e := endpoint(raw, hosts); e == nil {
			t.Fatalf("endpoint accepted: %s", raw)
		}
	}
	if _, e := endpoint("https://api.deepseek.com", hosts); e != nil {
		t.Fatal(e)
	}
	for _, ip := range []string{"127.0.0.1", "10.1.1.1", "172.16.1.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "192.0.2.1", "198.18.0.1", "224.1.1.1", "::", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "64:ff9b::a00:1", "2002:a00:1::1"} {
		if publicIP(netip.MustParseAddr(ip)) {
			t.Fatalf("unsafe IP %s", ip)
		}
	}
	for _, ip := range []string{"8.8.8.8", "2606:4700:4700::1111"} {
		if !publicIP(netip.MustParseAddr(ip)) {
			t.Fatalf("public IP blocked %s", ip)
		}
	}
	c := safeClient(map[string]bool{"localhost": true})
	r, _ := http.NewRequest("GET", "https://localhost/", nil)
	if _, e := c.Do(r); e == nil {
		t.Fatal("private DNS target accepted")
	}
	if e := c.CheckRedirect(nil, nil); e != http.ErrUseLastResponse {
		t.Fatal("redirects permitted")
	}
}
func TestProviderSpecificValidation(t *testing.T) {
	hosts := map[string]bool{"api.deepseek.com": true}
	for _, raw := range []string{`{"model":"deepseek-flash","maxTokens":256,"apiKey":"hidden"}`, `{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default","endpoint":"https://api.deepseek.com"}`, `{"model":"deepseek-flash","maxTokens":256,"endpoint":"https://api.deepseek.com"}`} {
		kind, provider := "LLM", "deepseek"
		if strings.Contains(raw, "voiceId") {
			kind, provider = "TTS", "xiaoya"
		}
		if e := validateInput(Input{Kind: kind, Provider: provider, Name: "test", Config: json.RawMessage(raw)}, hosts); e == nil {
			t.Fatal("unsupported provider config accepted")
		}
	}
	if e := validateInput(Input{Kind: "TTS", Provider: "xiaoya", Name: "test", Config: json.RawMessage(`{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}`)}, hosts); e != nil {
		t.Fatal(e)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestProviderFailuresAreSanitized(t *testing.T) {
	p := Profile{Kind: "LLM", Provider: "deepseek", Config: json.RawMessage(`{"model":"deepseek-flash","maxTokens":256}`)}
	for _, tc := range []struct {
		status     int
		body, code string
	}{{401, `{"error":"synthetic-private-key"}`, "PROVIDER_AUTH_FAILED"}, {403, "synthetic-private-key", "PROVIDER_AUTH_FAILED"}, {429, "synthetic-private-key", "PROVIDER_RATE_LIMITED"}, {200, `{"choices":[]}`, "PROVIDER_TEST_FAILED"}, {200, `{"choices":[{"message":{"content":""}}]}`, "PROVIDER_TEST_FAILED"}, {200, `{"error":"synthetic-private-key","choices":[{"message":{"content":"Hi"}}]}`, "PROVIDER_TEST_FAILED"}, {200, `{"choices":[{"message":{"content":"Hi"}}]}`, ""}} {
		client := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.Header.Get("Authorization") != "Bearer synthetic-private-key" {
				t.Fatal("missing key")
			}
			return &http.Response{StatusCode: tc.status, Body: io.NopCloser(strings.NewReader(tc.body)), Header: http.Header{}}, nil
		})}
		e := probeLLM(context.Background(), p, "synthetic-private-key", client, map[string]bool{"api.deepseek.com": true})
		if tc.code == "" {
			if e != nil {
				t.Fatal(e)
			}
			continue
		}
		if e == nil || publicError(e).Code != tc.code {
			t.Fatalf("failure mapping %v", e)
		}
		w := httptest.NewRecorder()
		write(w, httptest.NewRequest("POST", "/", nil), 200, nil, e)
		if w.Code == 200 || strings.Contains(w.Body.String(), "synthetic-private-key") {
			t.Fatal("secret leak or silent success")
		}
	}
}
func TestNoSessionAndNoServiceTokenFailClosed(t *testing.T) {
	s := &Service{}
	w := httptest.NewRecorder()
	s.PublicRouter().ServeHTTP(w, httptest.NewRequest("GET", "/profiles", nil))
	if w.Code != 401 {
		t.Fatal(w.Code)
	}
	w = httptest.NewRecorder()
	s.InternalRouter().ServeHTTP(w, httptest.NewRequest("POST", "/provider-bindings", strings.NewReader(`{"tenantId":"t","userId":"u"}`)))
	if w.Code != 401 {
		t.Fatal(w.Code)
	}
}

func TestMixedDNSAndPinnedDial(t *testing.T) {
	hosts := map[string]bool{"approved.example": true}
	dialed := ""
	lookups := 0
	resolve := func(context.Context, string, string) ([]netip.Addr, error) {
		lookups++
		return []netip.Addr{netip.MustParseAddr("8.8.8.8"), netip.MustParseAddr("10.0.0.1")}, nil
	}
	dial := func(_ context.Context, _ string, address string) (net.Conn, error) { dialed = address; return nil, nil }
	if _, e := validatedDial(t.Context(), "tcp", "approved.example:443", hosts, resolve, dial); e == nil || dialed != "" {
		t.Fatal("mixed DNS connected")
	}
	lookups = 0
	resolve = func(context.Context, string, string) ([]netip.Addr, error) {
		lookups++
		if lookups > 1 {
			return []netip.Addr{netip.MustParseAddr("10.0.0.1")}, nil
		}
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	if _, e := validatedDial(t.Context(), "tcp", "approved.example:443", hosts, resolve, dial); e != nil || lookups != 1 || dialed != "8.8.8.8:443" {
		t.Fatal("validated address not pinned")
	}
}

func TestRuntimeIntegrationFaultProjection(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control-token")
	if err := os.WriteFile(path, []byte(strings.Repeat("c", 40)), 0600); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("c", 40) {
			t.Error("missing control identity")
		}
		w.WriteHeader(503)
		_, _ = io.WriteString(w, `{"code":"RUNTIME_UNAVAILABLE","message":"untrusted synthetic-secret","details":{"integrationCode":"WORKER_UNAVAILABLE"}}`)
	}))
	defer server.Close()
	client := &http.Client{Transport: TokenTransport{Path: path, Base: server.Client().Transport}}
	_, err := client.Get(server.URL)
	if f := SafeFault(err); f.Code != "WORKER_UNAVAILABLE" || strings.Contains(f.Message, "synthetic-secret") {
		t.Fatal("safe fault projection", f.Code)
	}
}
