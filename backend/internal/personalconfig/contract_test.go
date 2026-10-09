package personalconfig

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/getkin/kin-openapi/openapi3"
)

func specification(t *testing.T) *openapi3.T {
	t.Helper()
	doc, err := openapi3.NewLoader().LoadFromFile(filepath.Join("..", "..", "..", "contracts", "personal-assets", "schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err = doc.Validate(t.Context()); err != nil {
		t.Fatal(err)
	}
	return doc
}
func asJSON(t *testing.T, value any) any {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	var result any
	if err = json.Unmarshal(raw, &result); err != nil {
		t.Fatal(err)
	}
	return result
}
func TestSharedDTOsAndPublicSecretExclusion(t *testing.T) {
	doc := specification(t)
	now := time.Date(2026, 10, 9, 0, 0, 0, 0, time.UTC)
	sha := strings.Repeat("a", 64)
	asset := Asset{ID: "asset-photo", Purpose: "NORMALIZED_PHOTO", State: "READY", Version: 1, ByteLength: 512, SHA256: sha, MediaType: "image/png", PreprocessingVersion: "photo-face512-v1", SourceAssetID: "asset-source", ErrorCode: "NONE", CreatedAt: now, Consent: ConsentReceipt{PolicyVersion: "PERSONAL_MEDIA_PROCESSING_V1", AcceptedAt: now}}
	avatar := AvatarProfile{ID: "avatar-personal", Name: "Personal", Version: 1, State: "CREATED", Enabled: true, Config: AvatarConfig{Provider: "soulx_lite", PhotoAssetID: "asset-source", WorkerProfileID: "worker-profile", ModelRef: "soulx-flashhead-lite", PreprocessingVersion: "photo-face512-v1"}, ErrorCode: "NONE", CreatedAt: now, UpdatedAt: now}
	voice := VoiceProfile{ID: "voice-preset", Name: "XiaoYa", Version: 1, State: "CREATED", Enabled: true, Config: json.RawMessage(`{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1,"volume":1}`), Capabilities: VoiceCapabilities{IncrementalPCM: true}, ErrorCode: "NONE", CreatedAt: now, UpdatedAt: now}
	job := Job{ID: "job-photo", Kind: "VALIDATE_PHOTO", Action: "VALIDATE", State: "QUEUED", OutputAssetIDs: []string{}, ErrorCode: "NONE", CreatedAt: now, ExpiresAt: now.Add(time.Minute)}
	binding := PersonalBinding{ID: "binding-one", SessionID: "session-one", ContractVersion: ContractVersion, Avatar: RevisionRef{ProfileID: "avatar-personal", Version: 1}, Voice: RevisionRef{ProfileID: "voice-preset", Version: 1}, ProviderBindingID: "provider-binding", Assets: []AssetDescriptor{{ID: "asset-photo", Purpose: "NORMALIZED_PHOTO", SHA256: sha, ByteLength: 512, MediaType: "image/png", PreprocessingVersion: "photo-face512-v1"}}, ExpiresAt: now.Add(24 * time.Hour)}
	for name, value := range map[string]any{"Asset": asset, "AvatarProfile": avatar, "VoiceProfile": voice, "Job": job, "PersonalBinding": binding} {
		t.Run(name, func(t *testing.T) {
			schema := doc.Components.Schemas[name].Value
			instance := asJSON(t, value)
			if err := schema.VisitJSON(instance); err != nil {
				t.Fatal(err)
			}
			for _, forbidden := range []string{"secret", "apiKey", "storageKey", "tenantId", "serverPath", "claimToken"} {
				altered := asJSON(t, value).(map[string]any)
				altered[forbidden] = "private-value"
				if err := schema.VisitJSON(altered); err == nil {
					t.Fatalf("%s allowed in %s", forbidden, name)
				}
			}
		})
	}
	if raw, _ := json.Marshal(AssetGrant{ClaimToken: "internal-claim", ProcessorRef: "worker", JobID: "job"}); string(raw) != "{}" {
		t.Fatal("internal authorization serializes publicly")
	}
}
func TestUploadAndProviderSchemaNegativeCases(t *testing.T) {
	doc := specification(t)
	valid := `{"purpose":"AVATAR_PHOTO","byteLength":12,"sha256":"` + strings.Repeat("a", 64) + `","mediaType":"image/png","consent":{"accepted":"PERSONAL_MEDIA_PROCESSING_V1","rightsConfirmed":true}}`
	schema := doc.Components.Schemas["CreateUpload"].Value
	cases := []struct {
		name, raw string
		valid     bool
	}{
		{"valid", valid, true},
		{"oversize", strings.Replace(valid, `"byteLength":12`, `"byteLength":10485761`, 1), false},
		{"svg", strings.Replace(valid, "image/png", "image/svg+xml", 1), false},
		{"derivative injection", strings.Replace(valid, "AVATAR_PHOTO", "NORMALIZED_PHOTO", 1), false},
		{"consent false", strings.Replace(valid, `"rightsConfirmed":true`, `"rightsConfirmed":false`, 1), false},
		{"scope injection", strings.Replace(valid, `"purpose":`, `"tenantId":"other","purpose":`, 1), false},
		{"path injection", strings.Replace(valid, `"purpose":`, `"serverPath":"/etc/passwd","purpose":`, 1), false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var value any
			if json.Unmarshal([]byte(c.raw), &value) != nil {
				t.Fatal("bad fixture")
			}
			if err := schema.VisitJSON(value); (err == nil) != c.valid {
				t.Fatalf("expected valid=%v, got %v", c.valid, err)
			}
		})
	}
	// Parameter differences cannot be flattened into an unrestricted config bag.
	for _, raw := range []string{`{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1.2,"volume":1}`, `{"provider":"cosyvoice","modelRef":"installed","referenceAssetId":"asset","referenceText":"test","speed":2,"volume":1}`, `{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1,"volume":1,"endpoint":"http://127.0.0.1"}`} {
		var value any
		_ = json.Unmarshal([]byte(raw), &value)
		if doc.Components.Schemas["VoiceConfig"].Value.VisitJSON(value) == nil {
			t.Fatal("unsupported config accepted")
		}
	}
}
func TestEveryRouteHasExplicitAuthorizationAndImplementationState(t *testing.T) {
	doc := specification(t)
	for path, item := range doc.Paths.Map() {
		for method, op := range item.Operations() {
			if op.Security == nil || len(*op.Security) != 1 {
				t.Fatalf("auth missing %s %s", method, path)
			}
			wanted := "cookie"
			if strings.HasPrefix(path, "/internal/") {
				wanted = "processor"
				if strings.Contains(path, "personal-session-bindings") && !strings.Contains(path, "/content") {
					wanted = "orchestrator"
				}
			}
			if _, ok := (*op.Security)[0][wanted]; !ok {
				t.Fatalf("wrong auth %s %s", method, path)
			}
			if op.Extensions["x-implementation-status"] != "CONTRACT_ONLY" {
				t.Fatalf("coverage missing %s", path)
			}
			if wanted == "cookie" && method != "GET" {
				found := false
				for _, p := range op.Parameters {
					if p.Value.Name == "Origin" && p.Value.In == "header" && p.Value.Required {
						found = true
					}
				}
				if !found {
					t.Fatalf("CSRF origin missing %s", path)
				}
			}
		}
	}
}
func TestProviderCapabilitiesEnforced(t *testing.T) {
	good := json.RawMessage(`{"provider":"cosyvoice","modelRef":"installed-model","referenceAssetId":"audio-one","referenceText":"参考音频文本","speed":1,"volume":0}`)
	caps, err := ValidateVoiceConfig(good)
	if err != nil || !caps.ReferenceAudio || !caps.Volume || caps.Speed {
		t.Fatalf("caps %v err %v", caps, err)
	}
	for _, raw := range []string{
		`{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":2,"volume":1}`,
		`{"provider":"cosyvoice","modelRef":"installed","referenceAssetId":"audio","referenceText":"test","speed":1.5,"volume":1}`,
	} {
		if _, err := ValidateVoiceConfig(json.RawMessage(raw)); !errors.Is(err, ErrCapabilityUnsupported) {
			t.Fatalf("unsupported capability error: %v", err)
		}
	}
	for _, raw := range []string{
		`{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1,"volume":1,"secret":"key"}`,
		`{"provider":"xiaoya","provider":"cosyvoice","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1,"volume":1}`,
		`{"provider":"xiaoya","voiceId":"xiao_ya","modelRef":"xiaoya-default","speed":1}`,
		`{"provider":"cosyvoice","modelRef":"installed","referenceAssetId":"audio","referenceText":"  ","speed":1,"volume":1}`,
		`{"provider":"cosyvoice","modelRef":"installed","referenceAssetId":"audio","referenceText":"a\u0000b","speed":1,"volume":1}`,
	} {
		if _, err := ValidateVoiceConfig(json.RawMessage(raw)); err == nil {
			t.Fatal("invalid config accepted")
		}
	}
}
func TestSimulationAndMismatchedReadinessCannotPass(t *testing.T) {
	expected := ReadinessIdentity{InputSHA256: strings.Repeat("a", 64), ModelRevision: "pinned-revision", PreprocessingVersion: "soulx-lite-512-seed42-v1", WorkerProfileVersion: 3}
	proof := Readiness{Mode: "REAL", CheckedAt: time.Now().UTC(), ModelRevision: expected.ModelRevision, PreprocessingVersion: expected.PreprocessingVersion, InputSHA256: expected.InputSHA256, CacheID: "cache-123", WorkerProfileVersion: 3, WarmupFrames: 3, EncoderReady: true}
	if err := AcceptReadiness(proof, expected); err != nil {
		t.Fatal(err)
	}
	variants := []Readiness{proof, proof, proof, proof, proof, proof}
	variants[0].Mode = "SIMULATION"
	variants[1].InputSHA256 = strings.Repeat("b", 64)
	variants[2].WorkerProfileVersion = 4
	variants[3].ModelRevision = "other"
	variants[4].WarmupFrames = 2
	variants[5].EncoderReady = false
	for _, v := range variants {
		if err := AcceptReadiness(v, expected); !errors.Is(err, ErrWorkerNotReady) {
			t.Fatalf("invalid readiness passed: %v", err)
		}
	}
}

func TestInternalProcessorDTOsMatchSharedSchema(t *testing.T) {
	doc := specification(t)
	now := time.Now().UTC()
	job := Job{ID: "job-a", Kind: "VALIDATE_PHOTO", Action: "VALIDATE", State: "RUNNING", Attempt: 1, ErrorCode: "NONE", OutputAssetIDs: []string{}, CreatedAt: now, ExpiresAt: now.Add(time.Minute)}
	claim := JobClaim{Job: job, Scope: Scope{TenantID: "tenant-a", UserID: "identity@example.test"}, ClaimToken: strings.Repeat("c", 40), LeaseExpiresAt: now.Add(time.Minute), InputAssets: []AssetDescriptor{{ID: "asset-a", Purpose: "AVATAR_PHOTO", SHA256: strings.Repeat("a", 64), ByteLength: 1024, MediaType: "image/png", PreprocessingVersion: ""}}}
	input := OutputUploadInput{ClaimToken: claim.ClaimToken, Attempt: 1, Purpose: "NORMALIZED_PHOTO", ByteLength: 512, SHA256: strings.Repeat("b", 64), MediaType: "image/png"}
	ticket := OutputTicket{UploadID: "upload-output", AssetID: "asset-output", ExpiresAt: now.Add(time.Minute)}
	for name, value := range map[string]any{"JobClaim": claim, "OutputUploadInput": input, "OutputTicket": ticket} {
		if err := doc.Components.Schemas[name].Value.VisitJSON(asJSON(t, value)); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
	}
}
