package narration_test

import (
	"context"
	"net"
	"os"
	"strconv"
)

// Only the explicitly enabled real Golden test process uses this owned DNS
// relay. Production validatedDial still rejects all non-public DNS answers,
// pins the validated address and verifies normal provider TLS/SNI.
func init() {
	address := os.Getenv("ASTRALIVE_GOLDEN_REAL_DNS_ADDRESS")
	if address == "" {
		return
	}
	host, port, err := net.SplitHostPort(address)
	n, portErr := strconv.Atoi(port)
	if os.Getenv("ASTRALIVE_GOLDEN_REAL") != "true" || err != nil || host != "127.0.0.1" || portErr != nil || n < 1 || n > 65535 {
		panic("invalid owned real Golden DNS relay configuration")
	}
	net.DefaultResolver = &net.Resolver{PreferGo: true, Dial: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "udp", address)
	}}
}
