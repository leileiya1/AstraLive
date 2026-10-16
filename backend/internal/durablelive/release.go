package durablelive

// CheckLiveAdmission is deliberately closed in this integration. The deployment
// still lets Runtime own RTMP/FFmpeg and WebRTC peers. No token, boolean config
// assertion, database epoch or test sink can prove physical output isolation.
// Replace this gate only together with a reviewed Guardian deployment and its
// real failover acceptance. Default-off legacy execution remains available.
func CheckLiveAdmission(enabled string) error {
	switch enabled {
	case "", "false":
		return nil
	case "true":
		return fault("OUTPUT_FENCE_UNPROVEN")
	default:
		return fault("INVALID_ARGUMENT")
	}
}
