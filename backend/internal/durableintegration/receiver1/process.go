// Package receiver1 supplies unmounted, default-closed trusted composition.
// Deployment calls these APIs, never Runtime request JSON. No media is started.
package receiver1

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"

	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
)

func denied() error           { return &authority.Error{Code: "UNAUTHENTICATED"} }
func fault(code string) error { return &authority.Error{Code: code} }
func fresh(prefix string) string {
	var b [24]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic(e)
	}
	return prefix + hex.EncodeToString(b[:])
}

type Identity struct {
	PID, UID int
	Birth    string
}

func InspectProcess(pid int) (Identity, error) { return processIdentity(pid) }

// Pin is a deployment-created process capability. Its secret is never exported,
// logged, in argv/env or accepted from the wire. Fresh process = fresh pin/key.
type Pin struct {
	actor    authority.Actor
	identity Identity
	binding  wire.ReceiverBootstrapBinding
	digest   [32]byte
	retired  atomic.Bool
	public   ed25519.PublicKey
	keyID    string
}

func (p *Pin) Actor() authority.Actor { return p.actor }
func (p *Pin) Identity() Identity     { return p.identity }
func (p *Pin) sourceIdentity() string {
	return fmt.Sprintf("unix:%d:%d:%s", p.identity.UID, p.identity.PID, p.identity.Birth)
}
func (p *Pin) Binding() wire.ReceiverBootstrapBinding { return p.binding }
func (p *Pin) Retire()                                { p.retired.Store(true) }
func (p *Pin) Alive() bool {
	if p == nil || p.retired.Load() {
		return false
	}
	v, e := processIdentity(p.identity.PID)
	return e == nil && v == p.identity
}
func (p *Pin) authenticate(i Identity, credential string) bool {
	d := sha256.Sum256([]byte(credential))
	return p.Alive() && i == p.identity && subtle.ConstantTimeCompare(d[:], p.digest[:]) == 1
}

// Managed must be launched by the trusted co-located supervisory composition.
// cmd/actor/binding come from deployment + authorized Session control, not JSON.
// Physical installation is NOT inferred from starting this process.
type Managed struct {
	Cmd  *exec.Cmd
	Pin  *Pin
	once sync.Once
	err  error
	stop func() bool
}

func StartManaged(ctx context.Context, cmd *exec.Cmd, actor authority.Actor, binding wire.ReceiverBootstrapBinding, controls ...*ControlChannel) (*Managed, error) {
	if e := ctx.Err(); e != nil {
		return nil, e
	}
	if actor.Role != "OUTPUT_GUARDIAN" && actor.Role != "REGISTERED_RUNTIME" {
		return nil, denied()
	}
	if len(controls) > 1 || (len(controls) > 0 && actor.Role != "OUTPUT_GUARDIAN") {
		return nil, denied()
	}
	if actor.Tenant == "" || actor.Owner == "" || actor.Room == "" || actor.Tenant != string(binding.TenantID) || actor.Owner != string(binding.OwnerID) || actor.Room != string(binding.RoomID) {
		return nil, denied()
	}
	if actor.Role == "REGISTERED_RUNTIME" && actor.Producer != string(binding.ProducerIncarnation) {
		return nil, denied()
	}
	// Never inherit the Backend's environment/DB/provider/publishing credentials.
	// Additional process dependencies need an explicitly reviewed launcher profile.
	allowed := map[string]bool{"PATH": true, "PYTHONPATH": true, "PYTHONDONTWRITEBYTECODE": true, "PYTHONNOUSERSITE": true, "LANG": true, "LC_ALL": true}
	clean := []string{"PYTHONNOUSERSITE=1", "PYTHONDONTWRITEBYTECODE=1"}
	for _, entry := range cmd.Env {
		k, _, _ := strings.Cut(entry, "=")
		if allowed[k] {
			clean = append(clean, entry)
		}
	}
	cmd.Env = clean
	actor.ID = fresh("principal_")
	actor.Incarnation = fresh("process_")
	var seed [32]byte
	if _, e := rand.Read(seed[:]); e != nil {
		return nil, e
	}
	token := base64.RawURLEncoding.EncodeToString(seed[:])
	p := &Pin{actor: actor, binding: binding, digest: sha256.Sum256([]byte(token))}
	var key ed25519.PrivateKey
	if actor.Role == "OUTPUT_GUARDIAN" {
		pub, priv, e := ed25519.GenerateKey(rand.Reader)
		if e != nil {
			return nil, e
		}
		p.public, key, p.keyID = pub, priv, fresh("key_")
	}
	r, w, e := os.Pipe()
	if e != nil {
		return nil, e
	}
	defer r.Close()
	defer w.Close()
	// Exactly one inherited bootstrap FD; no persistent credential file.
	if len(cmd.ExtraFiles) != 0 {
		return nil, errors.New("bootstrap FD must be exclusive")
	}
	cmd.ExtraFiles = []*os.File{r}
	if e = cmd.Start(); e != nil {
		return nil, e
	}
	p.identity, e = processIdentity(cmd.Process.Pid)
	if e != nil {
		cmd.Process.Kill()
		cmd.Wait()
		return nil, e
	}
	bootstrap := map[string]any{"credential": token, "principalId": actor.ID, "incarnation": actor.Incarnation, "role": actor.Role, "keyId": p.keyID, "privateKey": base64.StdEncoding.EncodeToString(key), "binding": binding}
	parent, e := processIdentity(os.Getpid())
	if e != nil {
		cmd.Process.Kill()
		cmd.Wait()
		return nil, e
	}
	bootstrap["processIdentity"] = p.identity
	bootstrap["parentIdentity"] = parent
	if len(controls) == 1 {
		c := controls[0]
		if c == nil || c.actor.Tenant != actor.Tenant || c.actor.Owner != actor.Owner || c.actor.Room != actor.Room {
			cmd.Process.Kill()
			cmd.Wait()
			return nil, denied()
		}
		bootstrap["controlProvisioning"] = c.provision()
	}
	if e = json.NewEncoder(w).Encode(bootstrap); e != nil {
		cmd.Process.Kill()
		cmd.Wait()
		return nil, e
	}
	m := &Managed{Cmd: cmd, Pin: p}
	ready := make(chan struct{})
	m.stop = context.AfterFunc(ctx, func() { <-ready; m.Close() })
	close(ready)
	return m, nil
}
func (m *Managed) Close() error {
	m.once.Do(func() {
		m.Pin.Retire()
		if m.stop != nil {
			m.stop()
		}
		if m.Cmd.Process == nil {
			return
		}
		// Never kill a replaced PID. Wait reaps only this Cmd's own child.
		now, e := processIdentity(m.Pin.identity.PID)
		if e == nil && now == m.Pin.identity {
			m.err = m.Cmd.Process.Kill()
		}
		m.Cmd.Wait()
	})
	return m.err
}
