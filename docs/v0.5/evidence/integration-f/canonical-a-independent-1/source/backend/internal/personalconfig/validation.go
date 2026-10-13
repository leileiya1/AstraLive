package personalconfig

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strings"
	"unicode/utf8"
)

var (
	ErrInvalidArgument       = errors.New("INVALID_ARGUMENT")
	ErrCapabilityUnsupported = errors.New("CAPABILITY_UNSUPPORTED")
	ErrWorkerNotReady        = errors.New("WORKER_NOT_READY")
	idPattern                = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`)
	digestPattern            = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

// decodeConfig rejects duplicate keys, unknown fields and trailing JSON before
// any adapter consumes provider parameters. Errors never include user input.
func decodeConfig(raw []byte, target any, required []string) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	first, err := d.Token()
	if err != nil || first != json.Delim('{') {
		return ErrInvalidArgument
	}
	seen := make(map[string]bool)
	for d.More() {
		token, err := d.Token()
		key, ok := token.(string)
		if err != nil || !ok || seen[key] {
			return ErrInvalidArgument
		}
		seen[key] = true
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return ErrInvalidArgument
		}
	}
	if _, err = d.Token(); err != nil {
		return ErrInvalidArgument
	}
	var trailing any
	if d.Decode(&trailing) != io.EOF {
		return ErrInvalidArgument
	}
	for _, key := range required {
		if !seen[key] {
			return ErrInvalidArgument
		}
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(target) != nil {
		return ErrInvalidArgument
	}
	return nil
}

// ValidateVoiceConfig validates the frozen provider-specific parameter boundary.
// Installed-model, ownership and actual synthesis checks remain service duties.
func ValidateVoiceConfig(raw json.RawMessage) (VoiceCapabilities, error) {
	var header struct {
		Provider string `json:"provider"`
	}
	if json.Unmarshal(raw, &header) != nil {
		return VoiceCapabilities{}, ErrInvalidArgument
	}
	switch header.Provider {
	case "xiaoya":
		var c XiaoYaVoiceConfig
		if decodeConfig(raw, &c, []string{"provider", "voiceId", "modelRef", "speed", "volume"}) != nil || c.VoiceID != "xiao_ya" || c.ModelRef != "xiaoya-default" {
			return VoiceCapabilities{}, ErrInvalidArgument
		}
		if c.Speed != 1 || c.Volume != 1 {
			return VoiceCapabilities{}, ErrCapabilityUnsupported
		}
		return VoiceCapabilities{IncrementalPCM: true}, nil
	case "cosyvoice":
		var c ReferenceVoiceConfig
		if decodeConfig(raw, &c, []string{"provider", "modelRef", "referenceAssetId", "referenceText", "speed", "volume"}) != nil || !idPattern.MatchString(c.ModelRef) || !idPattern.MatchString(c.ReferenceAssetID) {
			return VoiceCapabilities{}, ErrInvalidArgument
		}
		n := utf8.RuneCountInString(strings.TrimSpace(c.ReferenceText))
		if n < 1 || n > 1000 || strings.ContainsRune(c.ReferenceText, 0) {
			return VoiceCapabilities{}, ErrInvalidArgument
		}
		if c.Speed != 1 || c.Volume < 0 || c.Volume > 2 {
			return VoiceCapabilities{}, ErrCapabilityUnsupported
		}
		return VoiceCapabilities{ReferenceAudio: true, IncrementalPCM: true, Volume: true}, nil
	default:
		return VoiceCapabilities{}, ErrCapabilityUnsupported
	}
}

// ReadinessIdentity is taken from the immutable job/registered model, not browser
// JSON. Acceptance does not replace an actual Worker probe or health TTL check.
type ReadinessIdentity struct {
	InputSHA256          string
	ModelRevision        string
	PreprocessingVersion string
	WorkerProfileVersion int64
}

func AcceptReadiness(proof Readiness, expected ReadinessIdentity) error {
	if proof.Mode != "REAL" || !proof.EncoderReady || proof.WarmupFrames < 3 || proof.CheckedAt.IsZero() || !idPattern.MatchString(proof.CacheID) || !digestPattern.MatchString(proof.InputSHA256) || expected.WorkerProfileVersion < 1 || expected.ModelRevision == "" || expected.PreprocessingVersion == "" {
		return ErrWorkerNotReady
	}
	if proof.InputSHA256 != expected.InputSHA256 || proof.ModelRevision != expected.ModelRevision || proof.PreprocessingVersion != expected.PreprocessingVersion || proof.WorkerProfileVersion != expected.WorkerProfileVersion {
		return ErrWorkerNotReady
	}
	return nil
}
