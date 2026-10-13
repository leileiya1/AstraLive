//go:build linux || darwin

package runtime

import (
	"fmt"
	"os"
	"path/filepath"
	goruntime "runtime"
	"syscall"
)

func localPlatform() string { return goruntime.GOOS }
func owned(info os.FileInfo) bool {
	s, ok := info.Sys().(*syscall.Stat_t)
	return ok && s.Uid == uint32(os.Geteuid())
}
func secureParent(path string) (os.FileInfo, error) {
	dir := filepath.Dir(path)
	info, e := os.Lstat(dir)
	if e != nil {
		return nil, fmt.Errorf("runtime UDS private parent: %w", e)
	}
	if !info.IsDir() || !owned(info) || info.Mode().Perm() != 0700 {
		return nil, fmt.Errorf("runtime UDS parent must be an owned0700 directory")
	}
	// Check every ancestor. Root-owned sticky temp dirs are allowed; final dir is private.
	for p := dir; ; p = filepath.Dir(p) {
		st, e := os.Lstat(p)
		if e != nil {
			return nil, e
		}
		if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("runtime UDS parent chain contains symlink/non-directory")
		}
		if st.Mode().Perm()&0022 != 0 && !(st.Mode()&os.ModeSticky != 0 && st.Sys().(*syscall.Stat_t).Uid == 0) {
			return nil, fmt.Errorf("runtime UDS parent chain is writable by other users")
		}
		if p == filepath.Dir(p) {
			break
		}
	}
	return info, nil
}
func secureSocket(path string) (os.FileInfo, error) {
	info, e := os.Lstat(path)
	if e != nil {
		return nil, fmt.Errorf("runtime UDS unavailable: %w", e)
	}
	if info.Mode()&os.ModeSocket == 0 || !owned(info) || info.Mode().Perm() != 0600 {
		return nil, fmt.Errorf("runtime UDS must be an owned0600 socket (no symlinks)")
	}
	return info, nil
}
