//go:build !linux && !darwin

package runtime

import (
	"fmt"
	"os"
	goruntime "runtime"
)

func localPlatform() string { return goruntime.GOOS }
func secureParent(string) (os.FileInfo, error) {
	return nil, fmt.Errorf("UDS unsupported; use authenticated loopback TCP")
}
func secureSocket(string) (os.FileInfo, error) {
	return nil, fmt.Errorf("UDS unsupported; use authenticated loopback TCP")
}
