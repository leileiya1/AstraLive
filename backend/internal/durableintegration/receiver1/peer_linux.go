//go:build linux

package receiver1

import (
	"fmt"
	"golang.org/x/sys/unix"
	"os"
	"strconv"
	"strings"
)

func processIdentity(pid int) (Identity, error) {
	b, e := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if e != nil {
		return Identity{}, e
	}
	at := strings.LastIndex(string(b), ") ")
	if at < 0 {
		return Identity{}, denied()
	}
	f := strings.Fields(string(b)[at+2:])
	if len(f) < 20 || f[0] == "Z" {
		return Identity{}, denied()
	}
	boot, e := os.ReadFile("/proc/sys/kernel/random/boot_id")
	if e != nil {
		return Identity{}, e
	}
	st := &unix.Stat_t{}
	if e = unix.Stat(fmt.Sprintf("/proc/%d", pid), st); e != nil {
		return Identity{}, e
	}
	if _, e = strconv.ParseUint(f[19], 10, 64); e != nil {
		return Identity{}, e
	}
	return Identity{PID: pid, UID: int(st.Uid), Birth: strings.TrimSpace(string(boot)) + ":" + f[19]}, nil
}
func socketIdentity(fd int) (Identity, error) {
	c, e := unix.GetsockoptUcred(fd, unix.SOL_SOCKET, unix.SO_PEERCRED)
	if e != nil {
		return Identity{}, e
	}
	p, e := processIdentity(int(c.Pid))
	if e != nil || p.UID != int(c.Uid) {
		return Identity{}, denied()
	}
	return p, nil
}
