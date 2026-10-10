// Operator-only bootstrap for the single-operator login adapter.
package main

import (
	"astralive/backend/internal/userconfig"
	"encoding/json"
	"flag"
	"fmt"
	"golang.org/x/crypto/bcrypt"
	"io"
	"os"
	"strings"
)

func main() {
	path := flag.String("out", "", "new private operator file")
	username := flag.String("username", "operator", "operator login name")
	tenant := flag.String("tenant", "operator", "existing tenant scope")
	user := flag.String("user", "operator", "existing user scope")
	flag.Parse()
	// Password via stdin only; no argv, shell history or output. No overwrite.
	raw, e := io.ReadAll(io.LimitReader(os.Stdin, 74))
	if e != nil {
		panic("password input failed")
	}
	password := strings.TrimSuffix(strings.TrimSuffix(string(raw), "\n"), "\r")
	if *path == "" || len(password) < 12 || len(password) > 72 {
		fmt.Fprintln(os.Stderr, "provide 12..72 byte password on stdin and --out")
		os.Exit(1)
	}
	hash, e := bcrypt.GenerateFromPassword([]byte(password), 12)
	password = ""
	clear(raw)
	if e != nil {
		panic("hash failed")
	}
	f, e := os.OpenFile(*path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		panic("private operator file could not be created")
	}
	defer f.Close()
	op := userconfig.OperatorLogin{Username: *username, PasswordHash: string(hash), Scope: userconfig.Scope{TenantID: *tenant, UserID: *user}}
	if e = json.NewEncoder(f).Encode(op); e != nil {
		panic("private operator file write failed")
	}
	fmt.Println("single operator adapter created; no credentials printed")
}
