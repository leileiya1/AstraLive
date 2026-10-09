package userconfig

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type providerConfig struct {
	Model           string   `json:"model,omitempty"`
	MaxTokens       int      `json:"maxTokens,omitempty"`
	Temperature     *float64 `json:"temperature,omitempty"`
	Endpoint        string   `json:"endpoint,omitempty"`
	VoiceID         string   `json:"voiceId,omitempty"`
	Speed           float64  `json:"speed,omitempty"`
	ModelRef        string   `json:"modelRef,omitempty"`
	AvatarRef       string   `json:"avatarRef,omitempty"`
	WorkerProfileID string   `json:"workerProfileId,omitempty"`
	WorkerRef       string   `json:"workerRef,omitempty"`
	Platform        string   `json:"platform,omitempty"`
}

var logicalID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`)

func strictJSON(raw []byte, v any) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(v) != nil {
		return ErrInvalid
	}
	if d.Decode(new(any)) != io.EOF {
		return ErrInvalid
	}
	return nil
}
func validateInput(in Input, hosts map[string]bool) error {
	if len(in.Name) == 0 || len(in.Name) > 128 || strings.TrimSpace(in.Name) != in.Name || strings.ContainsAny(in.Name, "\r\n") || strings.Contains(in.Name, "sk-") {
		return ErrInvalid
	}
	var c providerConfig
	if strictJSON(in.Config, &c) != nil {
		return ErrInvalid
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(in.Config, &fields) != nil {
		return ErrInvalid
	}
	allowed := map[string]bool{}
	allow := func(keys ...string) {
		for _, k := range keys {
			allowed[k] = true
		}
	}
	switch in.Kind + "/" + in.Provider {
	case "LLM/deepseek", "LLM/openai-compatible":
		allow("model", "maxTokens", "temperature")
		if !logicalID.MatchString(c.Model) || c.MaxTokens < 1 || c.MaxTokens > 8192 {
			return ErrInvalid
		}
		if c.Temperature != nil && (*c.Temperature < 0 || *c.Temperature > 2) {
			return ErrInvalid
		}
		if in.Provider == "openai-compatible" {
			allow("endpoint")
			if _, e := endpoint(c.Endpoint, hosts); e != nil {
				return e
			}
		}
	case "TTS/xiaoya":
		allow("voiceId", "speed", "modelRef")
		if c.VoiceID != "xiao_ya" || c.ModelRef != "xiaoya-default" || c.Speed < 0.5 || c.Speed > 2 {
			return ErrInvalid
		}
	case "AVATAR/mock", "AVATAR/lightweight", "AVATAR/soulx":
		allow("avatarRef", "workerProfileId")
		if !logicalID.MatchString(c.AvatarRef) || (c.WorkerProfileID != "" && !logicalID.MatchString(c.WorkerProfileID)) {
			return ErrInvalid
		}
	case "GPU_WORKER/soulx":
		allow("workerRef")
		if !logicalID.MatchString(c.WorkerRef) {
			return ErrInvalid
		}
	case "LIVE_PLATFORM/generic":
		allow("platform")
		if !logicalID.MatchString(c.Platform) {
			return ErrInvalid
		}
	default:
		return ErrInvalid
	}
	for k, v := range fields {
		if !allowed[k] || string(v) == "null" {
			return ErrInvalid
		}
	}
	if in.Secret != "" && (in.Kind != "LLM" && in.Kind != "LIVE_PLATFORM" || !validSecret(in.Secret)) {
		return ErrInvalid
	}
	return nil
}
func validSecret(s string) bool {
	return len(s) > 0 && len(s) <= 4096 && !strings.ContainsAny(s, "\r\n\x00")
}
func endpoint(raw string, hosts map[string]bool) (*url.URL, error) {
	u, e := url.Parse(raw)
	if e != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.ForceQuery || u.Opaque != "" || (u.Port() != "" && u.Port() != "443") || (u.Path != "" && u.Path != "/" && u.Path != "/v1" && u.Path != "/v1/") || u.RawPath != "" {
		return nil, fault(422, "ENDPOINT_BLOCKED", "endpoint not permitted")
	}
	h := strings.ToLower(u.Hostname())
	if net.ParseIP(h) != nil || !hosts[h] || strings.HasSuffix(h, ".") {
		return nil, fault(422, "ENDPOINT_BLOCKED", "endpoint not permitted")
	}
	return u, nil
}

var blockedPrefixes = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"), netip.MustParsePrefix("10.0.0.0/8"), netip.MustParsePrefix("100.64.0.0/10"), netip.MustParsePrefix("127.0.0.0/8"), netip.MustParsePrefix("169.254.0.0/16"), netip.MustParsePrefix("172.16.0.0/12"), netip.MustParsePrefix("192.0.0.0/24"), netip.MustParsePrefix("192.0.2.0/24"), netip.MustParsePrefix("192.88.99.0/24"), netip.MustParsePrefix("192.168.0.0/16"), netip.MustParsePrefix("198.18.0.0/15"), netip.MustParsePrefix("198.51.100.0/24"), netip.MustParsePrefix("203.0.113.0/24"), netip.MustParsePrefix("224.0.0.0/3"), netip.MustParsePrefix("::/96"), netip.MustParsePrefix("64:ff9b::/96"), netip.MustParsePrefix("64:ff9b:1::/48"), netip.MustParsePrefix("100::/64"), netip.MustParsePrefix("2001::/23"), netip.MustParsePrefix("2002::/16"), netip.MustParsePrefix("fc00::/7"), netip.MustParsePrefix("fe80::/10"), netip.MustParsePrefix("ff00::/8"),
}

func publicIP(ip netip.Addr) bool {
	ip = ip.Unmap()
	if !ip.Is4() && !netip.MustParsePrefix("2000::/3").Contains(ip) {
		return false
	}
	if !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() {
		return false
	}
	for _, p := range blockedPrefixes {
		if p.Contains(ip) {
			return false
		}
	}
	return true
}
func safeClient(hosts map[string]bool) *http.Client {
	tr := &http.Transport{Proxy: nil, MaxResponseHeaderBytes: 16384, TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: 10 * time.Second,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			return validatedDial(ctx, network, address, hosts, net.DefaultResolver.LookupNetIP, (&net.Dialer{Timeout: 5 * time.Second}).DialContext)
		}}
	return &http.Client{Transport: tr, Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

// Validate every DNS answer and dial the exact validated address, without a second lookup.
func validatedDial(ctx context.Context, network, address string, hosts map[string]bool,
	resolve func(context.Context, string, string) ([]netip.Addr, error), dial func(context.Context, string, string) (net.Conn, error)) (net.Conn, error) {
	host, port, e := net.SplitHostPort(address)
	if e != nil || port != "443" || !hosts[strings.ToLower(host)] {
		return nil, errors.New("endpoint blocked")
	}
	ips, e := resolve(ctx, "ip", host)
	if e != nil || len(ips) == 0 {
		return nil, errors.New("endpoint unavailable")
	}
	for _, ip := range ips {
		if !publicIP(ip) {
			return nil, errors.New("endpoint blocked")
		}
	}
	return dial(ctx, network, net.JoinHostPort(ips[0].String(), port))
}

func probeLLM(ctx context.Context, p Profile, key string, client *http.Client, hosts map[string]bool) error {
	var c providerConfig
	if strictJSON(p.Config, &c) != nil {
		return ErrInvalid
	}
	target := "https://api.deepseek.com"
	if p.Provider == "openai-compatible" {
		target = c.Endpoint
	}
	u, e := endpoint(target, hosts)
	if e != nil {
		return e
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/chat/completions"
	payload := map[string]any{"model": c.Model, "max_tokens": c.MaxTokens, "stream": false, "messages": []map[string]string{{"role": "user", "content": "Reply with a brief greeting."}}}
	if c.Temperature != nil {
		payload["temperature"] = *c.Temperature
	}
	b, _ := json.Marshal(payload)
	r, e := http.NewRequestWithContext(ctx, "POST", u.String(), bytes.NewReader(b))
	if e != nil {
		return ErrInvalid
	}
	r.Header.Set("Authorization", "Bearer "+key)
	r.Header.Set("Content-Type", "application/json")
	res, e := client.Do(r)
	if e != nil {
		return fault(502, "PROVIDER_TEST_FAILED", "provider connection failed")
	}
	defer res.Body.Close()
	if res.StatusCode == 401 || res.StatusCode == 403 {
		return fault(502, "PROVIDER_AUTH_FAILED", "provider rejected credential (401/403)")
	}
	if res.StatusCode == 429 {
		return fault(502, "PROVIDER_RATE_LIMITED", "provider rate limit exceeded")
	}
	if res.StatusCode != 200 {
		return fault(502, "PROVIDER_TEST_FAILED", "provider request failed ("+strconv.Itoa(res.StatusCode)+")")
	}
	var reply struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Error json.RawMessage `json:"error"`
	}
	raw, e := io.ReadAll(io.LimitReader(res.Body, 65537))
	if e != nil || len(raw) > 65536 || json.Unmarshal(raw, &reply) != nil || len(reply.Choices) == 0 || strings.TrimSpace(reply.Choices[0].Message.Content) == "" || len(reply.Error) > 0 && string(reply.Error) != "null" {
		return fault(502, "PROVIDER_TEST_FAILED", "provider did not return a valid reply")
	}
	return nil
}
