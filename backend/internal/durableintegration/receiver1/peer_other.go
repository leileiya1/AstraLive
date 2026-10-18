//go:build !darwin && !linux

package receiver1

func processIdentity(pid int) (Identity, error) { return Identity{}, denied() }
func socketIdentity(fd int) (Identity, error)   { return Identity{}, denied() }
