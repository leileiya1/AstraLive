// Operator-only bootstrap. Never changes existing secrets or imports experiment keys.
package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

func random() string {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		panic("random source unavailable")
	}
	return base64.StdEncoding.EncodeToString(b)
}
func main() {
	dir := flag.String("dir", "", "absolute directory outside repository for operator secrets")
	flag.Parse()
	if !filepath.IsAbs(*dir) {
		fmt.Fprintln(os.Stderr, "--dir must be absolute")
		os.Exit(1)
	}
	if e := os.MkdirAll(*dir, 0700); e != nil {
		fmt.Fprintln(os.Stderr, "cannot create secret directory")
		os.Exit(1)
	}
	info, e := os.Stat(*dir)
	if e != nil || info.Mode().Perm()&0077 != 0 {
		fmt.Fprintln(os.Stderr, "secret directory must be owner-only")
		os.Exit(1)
	}
	ring, _ := json.Marshal(map[string]any{"activeKeyId": "initial", "keys": map[string]string{"initial": random()}})
	files := map[string][]byte{"keyring.json": ring, "identity-token": []byte(random()), "worker-token": []byte(random())}
	// Check all targets first; O_EXCL also prevents overwrite if a concurrent bootstrap races.
	for name := range files {
		if _, e = os.Lstat(filepath.Join(*dir, name)); !os.IsNotExist(e) {
			fmt.Fprintln(os.Stderr, "refusing to overwrite existing secrets")
			os.Exit(1)
		}
	}
	for name, data := range files {
		f, e := os.OpenFile(filepath.Join(*dir, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			fmt.Fprintln(os.Stderr, "cannot write secret file")
			os.Exit(1)
		}
		_, e = f.Write(data)
		closeErr := f.Close()
		if e != nil || closeErr != nil {
			fmt.Fprintln(os.Stderr, "secret write failed")
			os.Exit(1)
		}
	}
	fmt.Println("Created owner-only keyring and separate identity/worker token files; no secret values printed.")
}
