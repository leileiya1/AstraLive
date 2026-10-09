package fsm

var sessions = map[string][]string{
	"CREATED": {"PREPARING"}, "PREPARING": {"READY", "FAILED"},
	"READY": {"STARTING", "FAILED"}, "STARTING": {"LIVE", "FAILED"},
	"LIVE":     {"DEGRADED", "STOPPING", "FAILED"},
	"DEGRADED": {"LIVE", "STOPPING", "FAILED"}, "STOPPING": {"ENDED", "FAILED"},
}
var utterances = map[string][]string{
	"QUEUED":       {"GENERATING", "INTERRUPTED", "FAILED", "CANCELLED"},
	"GENERATING":   {"SYNTHESIZING", "INTERRUPTED", "FAILED"},
	"SYNTHESIZING": {"RENDERING", "INTERRUPTED", "FAILED"},
	"RENDERING":    {"PLAYING", "INTERRUPTED", "FAILED"},
	"PLAYING":      {"COMPLETED", "INTERRUPTED", "FAILED"},
}

func allowed(m map[string][]string, from, to string) bool {
	for _, v := range m[from] {
		if v == to {
			return true
		}
	}
	return false
}
func Session(from, to string) bool   { return allowed(sessions, from, to) }
func Utterance(from, to string) bool { return allowed(utterances, from, to) }
