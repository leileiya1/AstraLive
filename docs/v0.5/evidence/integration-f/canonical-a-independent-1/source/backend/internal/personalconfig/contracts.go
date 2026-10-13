// Package personalconfig defines the frozen v0.3.1 personal-media handoff.
// It defines interfaces and DTOs, not deployed HTTP handlers or model engines.
package personalconfig

import (
	"context"
	"encoding/json"
	"io"
	"time"
)

const ContractVersion = "0.3.1"

type Scope struct {
	TenantID string `json:"tenantId"`
	UserID   string `json:"userId"`
}
type ConsentInput struct {
	Accepted        string `json:"accepted"`
	RightsConfirmed bool   `json:"rightsConfirmed"`
}
type ConsentReceipt struct {
	PolicyVersion string    `json:"policyVersion"`
	AcceptedAt    time.Time `json:"acceptedAt"`
}
type Asset struct {
	ID                   string         `json:"assetId"`
	Purpose              string         `json:"purpose"`
	State                string         `json:"state"`
	Version              int64          `json:"version"`
	ByteLength           int64          `json:"byteLength"`
	SHA256               string         `json:"sha256"`
	MediaType            string         `json:"mediaType"`
	PreprocessingVersion string         `json:"preprocessingVersion"`
	SourceAssetID        string         `json:"sourceAssetId,omitempty"`
	ErrorCode            string         `json:"errorCode"`
	CreatedAt            time.Time      `json:"createdAt"`
	Consent              ConsentReceipt `json:"consent"`
}
type UploadInput struct {
	Purpose       string       `json:"purpose"`
	ByteLength    int64        `json:"byteLength"`
	SHA256        string       `json:"sha256"`
	MediaType     string       `json:"mediaType"`
	ReferenceText string       `json:"referenceText,omitempty"`
	Consent       ConsentInput `json:"consent"`
}
type UploadTicket struct {
	UploadID  string    `json:"uploadId"`
	Asset     Asset     `json:"asset"`
	ExpiresAt time.Time `json:"expiresAt"`
}
type AvatarConfig struct {
	Provider             string `json:"provider"`
	PhotoAssetID         string `json:"photoAssetId"`
	WorkerProfileID      string `json:"workerProfileId"`
	ModelRef             string `json:"modelRef"`
	PreprocessingVersion string `json:"preprocessingVersion"`
}
type XiaoYaVoiceConfig struct {
	Provider string  `json:"provider"`
	VoiceID  string  `json:"voiceId"`
	ModelRef string  `json:"modelRef"`
	Speed    float64 `json:"speed"`
	Volume   float64 `json:"volume"`
}
type ReferenceVoiceConfig struct {
	Provider         string  `json:"provider"`
	ModelRef         string  `json:"modelRef"`
	ReferenceAssetID string  `json:"referenceAssetId"`
	ReferenceText    string  `json:"referenceText"`
	Speed            float64 `json:"speed"`
	Volume           float64 `json:"volume"`
}
type VoiceCapabilities struct {
	ReferenceAudio bool `json:"referenceAudio"`
	IncrementalPCM bool `json:"incrementalPCM"`
	Speed          bool `json:"speed"`
	Volume         bool `json:"volume"`
}
type Readiness struct {
	Mode                 string    `json:"mode"`
	CheckedAt            time.Time `json:"checkedAt"`
	ModelRevision        string    `json:"modelRevision"`
	PreprocessingVersion string    `json:"preprocessingVersion"`
	InputSHA256          string    `json:"inputSHA256"`
	CacheID              string    `json:"cacheId"`
	WorkerProfileVersion int64     `json:"workerProfileVersion"`
	WarmupFrames         int64     `json:"warmupFrames"`
	EncoderReady         bool      `json:"encoderReady"`
}
type AvatarProfile struct {
	ID                     string       `json:"avatarProfileId"`
	Name                   string       `json:"name"`
	Version                int64        `json:"version"`
	State                  string       `json:"state"`
	Enabled                bool         `json:"enabled"`
	IsDefault              bool         `json:"isDefault"`
	Config                 AvatarConfig `json:"config"`
	NormalizedPhotoAssetID string       `json:"normalizedPhotoAssetId,omitempty"`
	Readiness              *Readiness   `json:"readiness,omitempty"`
	ErrorCode              string       `json:"errorCode"`
	CreatedAt              time.Time    `json:"createdAt"`
	UpdatedAt              time.Time    `json:"updatedAt"`
}
type VoiceProfile struct {
	ID        string `json:"voiceProfileId"`
	Name      string `json:"name"`
	Version   int64  `json:"version"`
	State     string `json:"state"`
	Enabled   bool   `json:"enabled"`
	IsDefault bool   `json:"isDefault"`
	// Config must be schema-validated VoiceConfig, never an arbitrary provider bag.
	Config                 json.RawMessage   `json:"config"`
	NormalizedAudioAssetID string            `json:"normalizedAudioAssetId,omitempty"`
	Capabilities           VoiceCapabilities `json:"capabilities"`
	ErrorCode              string            `json:"errorCode"`
	CreatedAt              time.Time         `json:"createdAt"`
	UpdatedAt              time.Time         `json:"updatedAt"`
}
type Job struct {
	ID             string    `json:"jobId"`
	Kind           string    `json:"kind"`
	Action         string    `json:"action"`
	State          string    `json:"state"`
	Attempt        int64     `json:"attempt"`
	ProfileVersion int64     `json:"profileVersion,omitempty"`
	ErrorCode      string    `json:"errorCode"`
	OutputAssetIDs []string  `json:"outputAssetIds"`
	CreatedAt      time.Time `json:"createdAt"`
	ExpiresAt      time.Time `json:"expiresAt"`
}
type AssetDescriptor struct {
	ID                   string `json:"assetId"`
	Purpose              string `json:"purpose"`
	SHA256               string `json:"sha256"`
	ByteLength           int64  `json:"byteLength"`
	MediaType            string `json:"mediaType"`
	PreprocessingVersion string `json:"preprocessingVersion"`
	SourceAssetID        string `json:"sourceAssetId,omitempty"`
}
type RevisionRef struct {
	ProfileID string `json:"profileId"`
	Version   int64  `json:"version"`
}
type PersonalBinding struct {
	ID                string            `json:"bindingId"`
	SessionID         string            `json:"sessionId"`
	ContractVersion   string            `json:"contractVersion"`
	Avatar            RevisionRef       `json:"avatar"`
	Voice             RevisionRef       `json:"voice"`
	ProviderBindingID string            `json:"providerBindingId"`
	Assets            []AssetDescriptor `json:"assets"`
	ExpiresAt         time.Time         `json:"expiresAt"`
}

// AssetGrant is internal authorization input, never a serializable browser DTO.
// Implementations must resolve the lease and authenticated processor identity;
// constructing this value is not proof of authorization.
type AssetGrant struct {
	ProcessorRef string `json:"-"`
	BindingID    string `json:"-"`
	JobID        string `json:"-"`
	ClaimToken   string `json:"-"`
}

// AssetStorage enforces scope, leases, digest, state and quota on every call.
// Byte limits apply while streaming; no unrestricted path/URL access exists.
type AssetStorage interface {
	CreateUpload(context.Context, Scope, UploadInput, string) (UploadTicket, error)
	PutUpload(context.Context, Scope, string, io.Reader) error
	CompleteUpload(context.Context, Scope, string) (Job, error)
	AbortUpload(context.Context, Scope, string) error
	Get(context.Context, Scope, string) (Asset, error)
	List(context.Context, Scope) ([]Asset, error)
	OpenPreview(context.Context, Scope, string) (AssetDescriptor, io.ReadCloser, error)
	Delete(context.Context, Scope, string, int64) (Asset, error)
	OpenInput(context.Context, AssetGrant, string) (AssetDescriptor, io.ReadCloser, error)
}

// PersonalBindingStore captures media + Provider snapshots in ONE transaction.
// Implementations must not compose two separately committed capture operations.
type PersonalBindingStore interface {
	Capture(context.Context, Scope, string, string) (PersonalBinding, error)
	Resolve(context.Context, Scope, string) (ResolvedPersonalBinding, error)
	Renew(context.Context, Scope, string) (PersonalBinding, error)
	Release(context.Context, Scope, string) error
}

// ProfileService takes identity from authenticated middleware, never JSON input.
// Config mutations create immutable revisions and require expectedVersion.
type ProfileService interface {
	CreateAvatar(context.Context, Scope, string, AvatarConfig, string) (AvatarProfile, error)
	GetAvatar(context.Context, Scope, string) (AvatarProfile, error)
	ListAvatars(context.Context, Scope) ([]AvatarProfile, error)
	UpdateAvatar(context.Context, Scope, string, int64, string, AvatarConfig) (AvatarProfile, error)
	CreateVoice(context.Context, Scope, string, json.RawMessage, string) (VoiceProfile, error)
	GetVoice(context.Context, Scope, string) (VoiceProfile, error)
	ListVoices(context.Context, Scope) ([]VoiceProfile, error)
	UpdateVoice(context.Context, Scope, string, int64, string, json.RawMessage) (VoiceProfile, error)
	// kind is AVATAR or VOICE; all IDs and versions must be owner-scoped.
	Prepare(context.Context, Scope, string, string, int64, string) (Job, error)
	PreviewAvatar(context.Context, Scope, string, int64, string, string) (Job, error)
	PreviewVoice(context.Context, Scope, string, int64, string, string) (Job, error)
	SetDefault(context.Context, Scope, string, string, int64) error
	Disable(context.Context, Scope, string, string, int64) error
	Delete(context.Context, Scope, string, string, int64) error
}

type JobClaim struct {
	Job            Job               `json:"job"`
	Scope          Scope             `json:"scope"`
	ClaimToken     string            `json:"claimToken"`
	LeaseExpiresAt time.Time         `json:"leaseExpiresAt"`
	InputAssets    []AssetDescriptor `json:"inputAssets"`
	Avatar         *AvatarProfile    `json:"avatar,omitempty"`
	Voice          *VoiceProfile     `json:"voice,omitempty"`
	PreviewText    string            `json:"previewText,omitempty"`
	ReferenceText  string            `json:"referenceText,omitempty"`
}
type OutputUploadInput struct {
	ClaimToken string `json:"claimToken"`
	Attempt    int64  `json:"attempt"`
	Purpose    string `json:"purpose"`
	ByteLength int64  `json:"byteLength"`
	SHA256     string `json:"sha256"`
	MediaType  string `json:"mediaType"`
}
type OutputTicket struct {
	UploadID  string    `json:"uploadId"`
	AssetID   string    `json:"assetId"`
	ExpiresAt time.Time `json:"expiresAt"`
}

// ProcessorIdentity is resolved from registered bearer credentials, not a body.
type ProcessorIdentity struct {
	WorkerRef       string   `json:"-"`
	AllowedJobKinds []string `json:"-"`
}

// ProcessorProtocol must enforce assignment, claim lease/attempt, immutable input
// ownership and output validity. Result is the closed JobResultInput union.
// Caller identity alone never authorizes another user's job/assets.
type ProcessorProtocol interface {
	Claim(context.Context, ProcessorIdentity, Scope, string) (JobClaim, error)
	Heartbeat(context.Context, ProcessorIdentity, string, string, int64) (JobClaim, error)
	ReserveOutput(context.Context, ProcessorIdentity, string, OutputUploadInput) (OutputTicket, error)
	PutOutput(context.Context, ProcessorIdentity, string, string, io.Reader) error
	Result(context.Context, ProcessorIdentity, string, json.RawMessage) (Job, error)
}

type WorkerSelection struct {
	ProfileID string `json:"profileId"`
	Version   int64  `json:"version"`
	WorkerRef string `json:"workerRef"`
}
type ResolvedPersonalBinding struct {
	Binding PersonalBinding `json:"binding"`
	Avatar  AvatarProfile   `json:"avatar"`
	Voice   VoiceProfile    `json:"voice"`
	Worker  WorkerSelection `json:"worker"`
}
type JobService interface {
	Get(context.Context, Scope, string) (Job, error)
	Cancel(context.Context, Scope, string) (Job, error)
}
