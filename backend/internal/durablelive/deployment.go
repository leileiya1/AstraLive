package durablelive

import (
	"context"
	"golang.org/x/sync/errgroup"
	"net/http"
	"time"
)

// Deployment connects the owned modules. Agent 4 supplies registered principals,
// real Provider/Worker adapters, protected transport and guardian-owned sinks.
// Nothing starts by package import; the existing main is deliberately unchanged.
type Deployment struct {
	Store       *Store
	Handler     http.Handler
	Credentials []Credential
	Sender      Sender
}

func NewDeployment(s *Store, credentials []Credential, sender Sender) (*Deployment, error) {
	if s == nil || s.DB == nil || sender == nil || len(s.RequiredSinks) == 0 {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	h, e := NewHandler(s, credentials)
	if e != nil {
		return nil, e
	}
	return &Deployment{s, h, append([]Credential(nil), credentials...), sender}, nil
}
func (d *Deployment) Run(ctx context.Context) error {
	group, ctx := errgroup.WithContext(ctx)
	seen := map[string]bool{}
	for _, c := range d.Credentials {
		p := c.Principal
		if p.Role != "CONTROL" || seen[p.TenantID+"/"+p.OwnerID+"/"+p.InstanceID] {
			continue
		}
		seen[p.TenantID+"/"+p.OwnerID+"/"+p.InstanceID] = true
		group.Go(func() error { return (&Dispatcher{d.Store, p, d.Sender, 16}).Run(ctx, 250*time.Millisecond) })
		group.Go(func() error { return (&Coordinator{d.Store, p, 32}).Run(ctx, time.Second) })
	}
	return group.Wait()
}
