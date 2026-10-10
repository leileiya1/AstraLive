package userconfig

import (
	"errors"
	"net/url"
	"os"
	"strings"
)

// FromEnvironment is opt-in; absent origin keeps accepted development stacks unchanged.
// These are operator bootstrap settings, never end-user Provider keys.
func FromEnvironment(db DB) (*Service, error) {
	origin := os.Getenv("CONFIG_PUBLIC_ORIGIN")
	if origin == "" {
		return nil, nil
	}
	u, e := url.Parse(origin)
	if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || u.Opaque != "" {
		return nil, errors.New("invalid configuration origin")
	}
	s := &Service{DB: db, Vault: Vault{os.Getenv("CONFIG_KEYRING_FILE")}, Origin: origin, Hosts: map[string]bool{"api.deepseek.com": true}, IdentityTokenFile: os.Getenv("CONFIG_IDENTITY_TOKEN_FILE"), WorkerTokenFile: os.Getenv("CONFIG_WORKER_TOKEN_FILE")}
	s.Workers, e = loadWorkerRegistry(os.Getenv("GPU_WORKER_REGISTRY_FILE"))
	if e != nil {
		return nil, e
	}
	if _, e = s.Vault.load(); e != nil {
		return nil, errors.New("configuration keyring unavailable")
	}
	for _, h := range strings.Split(os.Getenv("CONFIG_LLM_HOSTS"), ",") {
		h = strings.TrimSpace(strings.ToLower(h))
		if h != "" {
			if strings.ContainsAny(h, "/:@ ") || strings.HasSuffix(h, ".") {
				return nil, errors.New("invalid configuration hostname")
			}
			s.Hosts[h] = true
		}
	}
	return s, nil
}
