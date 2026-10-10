package userconfig

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"astralive/backend/internal/ids"
	"github.com/jackc/pgx/v5"
)

type Service struct {
	OperatorFile                       string
	IntegrationEnabled                 bool
	RuntimeStatusURL                   string
	RuntimeControlTokenFile            string
	DB                                 DB
	Vault                              Vault
	Origin                             string
	Hosts                              map[string]bool
	IdentityTokenFile, WorkerTokenFile string
	Client                             *http.Client
	Workers                            map[string]WorkerEndpoint
}

const selectProfiles = `SELECT p.id,p.kind,p.name,p.provider,p.config,p.version,p.enabled,p.is_default,(c.profile_id IS NOT NULL),p.verification,p.error_code,CASE WHEN p.kind='GPU_WORKER' AND (p.health_at IS NULL OR p.health_at < now()-interval '60 seconds') THEN 'UNKNOWN' ELSE p.health END,p.updated_at FROM config_profiles p LEFT JOIN provider_credentials c ON c.tenant_id=p.tenant_id AND c.user_id=p.user_id AND c.profile_id=p.id WHERE p.tenant_id=$1 AND p.user_id=$2`

func scanProfile(r interface{ Scan(...any) error }) (Profile, error) {
	var p Profile
	e := r.Scan(&p.ID, &p.Kind, &p.Name, &p.Provider, &p.Config, &p.Version, &p.Enabled, &p.Default, &p.CredentialConfigured, &p.Verification, &p.ErrorCode, &p.Health, &p.UpdatedAt)
	p.UpdatedAt = p.UpdatedAt.UTC()
	return p, e
}
func (s *Service) List(ctx context.Context, scope Scope) ([]Profile, error) {
	rows, e := s.DB.Query(ctx, selectProfiles+" ORDER BY p.updated_at,p.id", scope.TenantID, scope.UserID)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Profile{}
	for rows.Next() {
		p, e := scanProfile(rows)
		if e != nil {
			return nil, e
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
func (s *Service) Get(ctx context.Context, scope Scope, id string) (Profile, error) {
	return scanProfile(s.DB.QueryRow(ctx, selectProfiles+" AND p.id=$3", scope.TenantID, scope.UserID, id))
}
func (s *Service) transaction(ctx context.Context, scope Scope, fn func(pgx.Tx) error) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var user string
	e = tx.QueryRow(ctx, "SELECT user_id FROM config_principals WHERE tenant_id=$1 AND user_id=$2 FOR UPDATE", scope.TenantID, scope.UserID).Scan(&user)
	if e != nil {
		return e
	}
	if e = fn(tx); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Service) Create(ctx context.Context, scope Scope, in Input) (Profile, error) {
	if in.ExpectedVersion != 0 {
		return Profile{}, ErrInvalid
	}
	if e := validateInput(in, s.Hosts); e != nil {
		return Profile{}, e
	}
	id := ids.New("profile")
	var secret storedSecret
	var e error
	if in.Secret != "" {
		secret, e = s.Vault.Seal(scope, id, in.Secret)
		if e != nil {
			return Profile{}, e
		}
	}
	e = s.transaction(ctx, scope, func(tx pgx.Tx) error {
		if e := validateReferences(ctx, tx, scope, in); e != nil {
			return e
		}
		_, e := tx.Exec(ctx, `INSERT INTO config_profiles(tenant_id,user_id,id,kind,name,provider,config) VALUES($1,$2,$3,$4,$5,$6,$7)`, scope.TenantID, scope.UserID, id, in.Kind, in.Name, in.Provider, in.Config)
		if e != nil {
			return e
		}
		if in.Secret != "" {
			_, e = tx.Exec(ctx, `INSERT INTO provider_credentials(tenant_id,user_id,profile_id,key_id,ciphertext) VALUES($1,$2,$3,$4,$5)`, scope.TenantID, scope.UserID, id, secret.KeyID, secret.Ciphertext)
		}
		return e
	})
	if e != nil {
		return Profile{}, e
	}
	return s.Get(ctx, scope, id)
}
func (s *Service) Mutate(ctx context.Context, scope Scope, id, action string, in Input) (Profile, error) {
	if in.ExpectedVersion < 1 {
		return Profile{}, ErrInvalid
	}
	e := s.transaction(ctx, scope, func(tx pgx.Tx) error {
		p, e := scanProfile(tx.QueryRow(ctx, selectProfiles+" AND p.id=$3", scope.TenantID, scope.UserID, id))
		if e != nil {
			return e
		}
		if p.Version != in.ExpectedVersion {
			return ErrConflict
		}
		switch action {
		case "update":
			in.Kind = p.Kind
			in.Provider = p.Provider
			in.Secret = ""
			if e = validateInput(in, s.Hosts); e != nil {
				return e
			}
			if e = validateReferences(ctx, tx, scope, in); e != nil {
				return e
			}
			_, e = tx.Exec(ctx, `UPDATE config_profiles SET name=$4,config=$5,version=version+1,enabled=true,is_default=false,verification='UNTESTED',error_code='',health='UNKNOWN',health_at=NULL,updated_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id, in.Name, in.Config)
		case "credential", "remove-credential":
			if p.Kind != "LLM" && p.Kind != "LIVE_PLATFORM" {
				return ErrInvalid
			}
			if action == "credential" {
				if !validSecret(in.Secret) {
					return ErrInvalid
				}
				secret, e := s.Vault.Seal(scope, id, in.Secret)
				if e != nil {
					return e
				}
				_, e = tx.Exec(ctx, `INSERT INTO provider_credentials(tenant_id,user_id,profile_id,key_id,ciphertext) VALUES($1,$2,$3,$4,$5) ON CONFLICT(tenant_id,user_id,profile_id) DO UPDATE SET key_id=EXCLUDED.key_id,ciphertext=EXCLUDED.ciphertext`, scope.TenantID, scope.UserID, id, secret.KeyID, secret.Ciphertext)
				if e != nil {
					return e
				}
			} else {
				_, e = tx.Exec(ctx, `DELETE FROM provider_credentials WHERE tenant_id=$1 AND user_id=$2 AND profile_id=$3`, scope.TenantID, scope.UserID, id)
				if e != nil {
					return e
				}
			}
			_, e = tx.Exec(ctx, `UPDATE config_profiles SET version=version+1,is_default=false,verification='UNTESTED',error_code='',health='UNKNOWN',health_at=NULL,updated_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id)
		case "default":
			if !p.Enabled {
				return fault(409, "CONFIG_DISABLED", "save the configuration to enable it")
			}
			if p.Kind == "LLM" && (!p.CredentialConfigured || p.Verification != "VERIFIED") {
				return fault(409, "CONFIG_NOT_VERIFIED", "verify current configuration first")
			}
			if p.Kind == "LIVE_PLATFORM" {
				return fault(409, "CONFIG_STORAGE_ONLY", "live platform configuration is storage only")
			}
			_, e = tx.Exec(ctx, `UPDATE config_profiles SET is_default=false WHERE tenant_id=$1 AND user_id=$2 AND kind=$3 AND is_default`, scope.TenantID, scope.UserID, p.Kind)
			if e != nil {
				return e
			}
			_, e = tx.Exec(ctx, `UPDATE config_profiles SET is_default=true,updated_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id)
		case "disable":
			_, e = tx.Exec(ctx, `UPDATE config_profiles SET enabled=false,is_default=false,version=version+1,verification='UNTESTED',error_code='',health='UNKNOWN',health_at=NULL,updated_at=now() WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id)
		case "delete":
			_, e = tx.Exec(ctx, `DELETE FROM config_profiles WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id)
		default:
			return ErrInvalid
		}
		return e
	})
	if e != nil {
		return Profile{}, e
	}
	if action == "delete" {
		return Profile{}, nil
	}
	return s.Get(ctx, scope, id)
}
func (s *Service) Test(ctx context.Context, scope Scope, id string, expected int64) (Profile, error) {
	p, e := s.Get(ctx, scope, id)
	if e != nil {
		return Profile{}, e
	}
	if expected < 1 {
		return Profile{}, ErrInvalid
	}
	if p.Version != expected {
		return Profile{}, ErrConflict
	}
	if !p.Enabled {
		return Profile{}, fault(409, "CONFIG_DISABLED", "configuration disabled")
	}
	if p.Kind != "LLM" {
		return s.testLocalProvider(ctx, scope, p)
	}
	if !p.CredentialConfigured {
		return Profile{}, fault(409, "CREDENTIAL_NOT_CONFIGURED", "save a credential first")
	}
	var key string
	e = s.transaction(ctx, scope, func(tx pgx.Tx) error {
		var version int64
		if e := tx.QueryRow(ctx, `SELECT version FROM config_profiles WHERE tenant_id=$1 AND user_id=$2 AND id=$3`, scope.TenantID, scope.UserID, id).Scan(&version); e != nil {
			return e
		}
		if version != expected {
			return ErrConflict
		}
		tag, e := tx.Exec(ctx, `INSERT INTO config_test_attempts(tenant_id,user_id,attempted_at) VALUES($1,$2,now()) ON CONFLICT(tenant_id,user_id) DO UPDATE SET attempted_at=now() WHERE config_test_attempts.attempted_at < now()-interval '5 seconds'`, scope.TenantID, scope.UserID)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return fault(429, "RATE_LIMITED", "wait five seconds before another connection test")
		}
		c := storedSecret{ProfileID: id}
		e = tx.QueryRow(ctx, `SELECT key_id,ciphertext FROM provider_credentials WHERE tenant_id=$1 AND user_id=$2 AND profile_id=$3`, scope.TenantID, scope.UserID, id).Scan(&c.KeyID, &c.Ciphertext)
		if e != nil {
			return e
		}
		key, e = s.Vault.Open(scope, c)
		return e
	})
	if e != nil {
		return Profile{}, e
	}
	client := s.Client
	if client == nil {
		client = safeClient(s.Hosts)
		defer client.CloseIdleConnections()
	}
	probeErr := probeLLM(ctx, p, key, client, s.Hosts)
	key = ""
	return s.saveProbeResult(ctx, scope, p, probeErr)
}
func (s *Service) Settings(ctx context.Context, scope Scope) (Settings, error) {
	out := Settings{Version: 0, Policy: Policy{100, "STOP"}, Effect: "NEXT_SESSION"}
	var raw []byte
	e := s.DB.QueryRow(ctx, `SELECT version,policy FROM user_settings WHERE tenant_id=$1 AND user_id=$2`, scope.TenantID, scope.UserID).Scan(&out.Version, &raw)
	if errors.Is(e, pgx.ErrNoRows) {
		return out, nil
	}
	if e != nil {
		return out, e
	}
	e = json.Unmarshal(raw, &out.Policy)
	return out, e
}
func (s *Service) SaveSettings(ctx context.Context, scope Scope, expected int64, p Policy) (Settings, error) {
	if expected < 0 || p.MaxQueue < 1 || p.MaxQueue > 100 || p.FailurePolicy != "STOP" {
		return Settings{}, ErrInvalid
	}
	raw, _ := json.Marshal(p)
	e := s.transaction(ctx, scope, func(tx pgx.Tx) error {
		var version int64
		e := tx.QueryRow(ctx, `SELECT version FROM user_settings WHERE tenant_id=$1 AND user_id=$2`, scope.TenantID, scope.UserID).Scan(&version)
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if version != expected {
			return ErrConflict
		}
		_, e = tx.Exec(ctx, `INSERT INTO user_settings(tenant_id,user_id,version,policy) VALUES($1,$2,1,$3) ON CONFLICT(tenant_id,user_id) DO UPDATE SET version=user_settings.version+1,policy=EXCLUDED.policy`, scope.TenantID, scope.UserID, raw)
		return e
	})
	if e != nil {
		return Settings{}, e
	}
	return s.Settings(ctx, scope)
}
func tokenHash(token string) string {
	digest := sha256.Sum256([]byte(token))
	return hex.EncodeToString(digest[:])
}
func validScope(s Scope) bool {
	return logicalID.MatchString(s.TenantID) && logicalID.MatchString(s.UserID)
}
func (s *Service) IssueSession(ctx context.Context, scope Scope) (string, error) {
	if !validScope(scope) {
		return "", ErrInvalid
	}
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", e
	}
	token := base64.RawURLEncoding.EncodeToString(b)
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return "", e
	}
	defer tx.Rollback(ctx)
	_, e = tx.Exec(ctx, `INSERT INTO config_principals(tenant_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, scope.TenantID, scope.UserID)
	if e != nil {
		return "", e
	}
	_, e = tx.Exec(ctx, `INSERT INTO config_auth_sessions(token_hash,tenant_id,user_id,expires_at) VALUES($1,$2,$3,now()+interval '12 hours')`, tokenHash(token), scope.TenantID, scope.UserID)
	if e != nil {
		return "", e
	}
	return token, tx.Commit(ctx)
}
func (s *Service) Authenticate(ctx context.Context, token string) (Scope, error) {
	var scope Scope
	if len(token) != 43 {
		return scope, fault(401, "UNAUTHENTICATED", "sign in to manage configuration")
	}
	e := s.DB.QueryRow(ctx, `SELECT tenant_id,user_id FROM config_auth_sessions WHERE token_hash=$1 AND expires_at>now()`, tokenHash(token)).Scan(&scope.TenantID, &scope.UserID)
	if errors.Is(e, pgx.ErrNoRows) {
		return scope, fault(401, "UNAUTHENTICATED", "sign in to manage configuration")
	}
	return scope, e
}
func (s *Service) Capture(ctx context.Context, scope Scope) (Binding, error) {
	if !validScope(scope) {
		return Binding{}, ErrInvalid
	}
	snap := snapshot{Binding: Binding{ID: ids.New("binding"), ContractVersion: "0.3.0", Profiles: []Profile{}, Settings: Settings{0, Policy{100, "STOP"}, "NEXT_SESSION"}, ExpiresAt: time.Now().UTC().Add(24 * time.Hour)}, Secrets: []storedSecret{}}
	e := s.transaction(ctx, scope, func(tx pgx.Tx) error {
		rows, e := tx.Query(ctx, selectProfiles+" AND p.enabled AND p.is_default ORDER BY p.kind", scope.TenantID, scope.UserID)
		if e != nil {
			return e
		}
		for rows.Next() {
			p, e := scanProfile(rows)
			if e != nil {
				rows.Close()
				return e
			}
			snap.Binding.Profiles = append(snap.Binding.Profiles, p)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		for _, p := range snap.Binding.Profiles {
			if p.CredentialConfigured {
				c := storedSecret{ProfileID: p.ID}
				if e = tx.QueryRow(ctx, `SELECT key_id,ciphertext FROM provider_credentials WHERE tenant_id=$1 AND user_id=$2 AND profile_id=$3`, scope.TenantID, scope.UserID, p.ID).Scan(&c.KeyID, &c.Ciphertext); e != nil {
					return e
				}
				snap.Secrets = append(snap.Secrets, c)
			}
		}
		var raw []byte
		e = tx.QueryRow(ctx, `SELECT version,policy FROM user_settings WHERE tenant_id=$1 AND user_id=$2`, scope.TenantID, scope.UserID).Scan(&snap.Binding.Settings.Version, &raw)
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if e == nil {
			if e = json.Unmarshal(raw, &snap.Binding.Settings.Policy); e != nil {
				return e
			}
		}
		b, _ := json.Marshal(snap)
		_, e = tx.Exec(ctx, `INSERT INTO provider_bindings(id,tenant_id,user_id,snapshot,expires_at) VALUES($1,$2,$3,$4,$5)`, snap.Binding.ID, scope.TenantID, scope.UserID, b, snap.Binding.ExpiresAt)
		return e
	})
	return snap.Binding, e
}
func (s *Service) Resolve(ctx context.Context, scope Scope, id string) (Binding, map[string]string, error) {
	var raw []byte
	e := s.DB.QueryRow(ctx, `SELECT snapshot FROM provider_bindings WHERE id=$1 AND tenant_id=$2 AND user_id=$3 AND expires_at>now()`, id, scope.TenantID, scope.UserID).Scan(&raw)
	if e != nil {
		return Binding{}, nil, e
	}
	var snap snapshot
	if e = json.Unmarshal(raw, &snap); e != nil {
		return Binding{}, nil, e
	}
	keys := map[string]string{}
	for _, c := range snap.Secrets {
		key, e := s.Vault.Open(scope, c)
		if e != nil {
			return Binding{}, nil, e
		}
		keys[c.ProfileID] = key
	}
	return snap.Binding, keys, nil
}

func validateReferences(ctx context.Context, tx pgx.Tx, scope Scope, in Input) error {
	var c providerConfig
	if json.Unmarshal(in.Config, &c) != nil {
		return ErrInvalid
	}
	if c.WorkerProfileID != "" {
		var found string
		e := tx.QueryRow(ctx, `SELECT id FROM config_profiles WHERE tenant_id=$1 AND user_id=$2 AND id=$3 AND kind='GPU_WORKER'`, scope.TenantID, scope.UserID, c.WorkerProfileID).Scan(&found)
		if e != nil {
			return e
		}
	}
	return nil
}
