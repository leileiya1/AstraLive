//go:build darwin

package receiver1

import (
	"fmt"
	"golang.org/x/sys/unix"
)

func processIdentity(pid int) (Identity, error) {
	p, e := unix.SysctlKinfoProc("kern.proc.pid", pid)
	if e != nil || p.Proc.P_pid != int32(pid) || p.Proc.P_stat == 5 {
		return Identity{}, denied()
	}
	return Identity{PID: pid, UID: int(p.Eproc.Ucred.Uid), Birth: fmt.Sprintf("darwin:%d:%d", p.Proc.P_starttime.Sec, p.Proc.P_starttime.Usec)}, nil
}
func socketIdentity(fd int) (Identity, error) {
	pid, e := unix.GetsockoptInt(fd, 0, 2) // SOL_LOCAL / LOCAL_PEERPID, selected by kernel.
	if e != nil {
		return Identity{}, e
	}
	p, e := processIdentity(pid)
	if e != nil {
		return p, e
	}
	u, e := unix.GetsockoptXucred(fd, 0, 1) // LOCAL_PEERCRED independently binds UID.
	if e != nil || int(u.Uid) != p.UID {
		return Identity{}, denied()
	}
	return p, nil
}
