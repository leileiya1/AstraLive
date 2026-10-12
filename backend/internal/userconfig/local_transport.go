package userconfig

import (
	"astralive/backend/internal/config"
	rt "astralive/backend/internal/runtime"
	"net/http"
	"time"
)

func (s *Service) captureLocalRuntimeTransport() error {
	options, e := config.LocalTransportFromEnv()
	if e != nil {
		return e
	}
	h, e := rt.NewLocal(s.RuntimeStatusURL, options)
	if e != nil {
		return e
	}
	s.RuntimeTransport = h.Client.Transport
	if s.RuntimeTransport == nil {
		s.RuntimeTransport = rt.LocalDiagnostics{Mode: "tcp", Base: &http.Transport{Proxy: nil}}
	}
	return nil
}
func (s *Service) localRuntimeHTTP(timeout time.Duration) (*http.Client, error) {
	base := s.RuntimeTransport
	if base == nil {
		base = &http.Transport{Proxy: nil}
	} // legacy test/manual Service constructors
	return &http.Client{Timeout: timeout, Transport: TokenTransport{Path: s.RuntimeControlTokenFile, Base: base}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, nil
}
