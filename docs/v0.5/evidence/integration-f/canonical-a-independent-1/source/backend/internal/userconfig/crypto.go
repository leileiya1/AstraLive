package userconfig

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
)

type Keyring struct {
	Active string            `json:"activeKeyId"`
	Keys   map[string]string `json:"keys"`
}
type Vault struct{ Path string }

func (v Vault) load() (Keyring, error) {
	var k Keyring
	f, e := os.Open(v.Path)
	if e != nil {
		return k, errors.New("keyring unavailable")
	}
	defer f.Close()
	info, e := f.Stat()
	if e != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 65536 {
		return k, errors.New("invalid keyring permissions or size")
	}
	d := json.NewDecoder(f)
	d.DisallowUnknownFields()
	if d.Decode(&k) != nil || k.Active == "" {
		return k, errors.New("invalid keyring")
	}
	if _, e = keyAEAD(k, k.Active); e != nil {
		return k, e
	}
	return k, nil
}
func keyAEAD(k Keyring, id string) (cipher.AEAD, error) {
	b, e := base64.StdEncoding.DecodeString(k.Keys[id])
	if e != nil || len(b) != 32 {
		return nil, errors.New("encryption key unavailable")
	}
	block, e := aes.NewCipher(b)
	if e != nil {
		return nil, errors.New("encryption unavailable")
	}
	return cipher.NewGCM(block)
}
func aad(s Scope, id string) []byte {
	b, _ := json.Marshal([]string{"astralive-config-v0.3", s.TenantID, s.UserID, id})
	return b
}
func (v Vault) Seal(s Scope, id, secret string) (storedSecret, error) {
	k, e := v.load()
	if e != nil {
		return storedSecret{}, e
	}
	a, e := keyAEAD(k, k.Active)
	if e != nil {
		return storedSecret{}, e
	}
	nonce := make([]byte, a.NonceSize())
	if _, e = rand.Read(nonce); e != nil {
		return storedSecret{}, errors.New("encryption unavailable")
	}
	return storedSecret{id, k.Active, a.Seal(nonce, nonce, []byte(secret), aad(s, id))}, nil
}
func (v Vault) Open(s Scope, secret storedSecret) (string, error) {
	k, e := v.load()
	if e != nil {
		return "", e
	}
	a, e := keyAEAD(k, secret.KeyID)
	if e != nil {
		return "", e
	}
	n := a.NonceSize()
	if len(secret.Ciphertext) < n {
		return "", errors.New("credential unavailable")
	}
	plain, e := a.Open(nil, secret.Ciphertext[:n], secret.Ciphertext[n:], aad(s, secret.ProfileID))
	if e != nil {
		return "", errors.New("credential unavailable")
	}
	return string(plain), nil
}
