// Normative receiver-1 interface sample; NO routes, DB or media implementation.
// Schema validation (including closed objects/conditions) precedes decoding.
// Existing answer documents use RawMessage here; generate full production DTOs
// from the same schema only after approval. Principal comes from authenticated
// Context, never from caller JSON. Do not log or persist plaintext tickets.
package receivercontract

import (
	"context"
	"encoding/json"
)

type CommitReceiverConsumeRequest struct {
	ContractRevision             string                `json:"contractRevision"`
	ReceiverRevision             string                `json:"receiverRevision"`
	RequestId                    string                `json:"requestId"`
	References                   ReceiverReferences    `json:"references"`
	ConsumeRequestId             string                `json:"consumeRequestId"`
	RuntimePrincipalId           string                `json:"runtimePrincipalId"`
	ChannelBinding               string                `json:"channelBinding"`
	ExpectedRegistrationRevision int64                 `json:"expectedRegistrationRevision"`
	ConsumeTicket                ReceiverConsumeTicket `json:"consumeTicket"`
	RuntimeIncarnation           string                `json:"runtimeIncarnation"`
}

type CommitReceiverConsumeResponse struct {
	RequestId         string                     `json:"requestId"`
	ConsumeAuthorized bool                       `json:"consumeAuthorized"`
	Consumption       *ReceiverConsumption       `json:"consumption"`
	Summary           ReceiverConsumptionSummary `json:"summary"`
	ConsumeTiming     *ReceiverTiming            `json:"consumeTiming"`
}

type QueryReceiverAuthorityRequest struct {
	ContractRevision string             `json:"contractRevision"`
	ReceiverRevision string             `json:"receiverRevision"`
	RequestId        string             `json:"requestId"`
	References       ReceiverReferences `json:"references"`
}

type QueryReceiverAuthorityResponse struct {
	RequestId string                    `json:"requestId"`
	Snapshot  ReceiverAuthoritySnapshot `json:"snapshot"`
}

type QueryReceiverConsumptionRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	BootstrapId      string `json:"bootstrapId"`
	GrantId          string `json:"grantId"`
}

type QueryReceiverConsumptionResponse struct {
	RequestId string                     `json:"requestId"`
	Summary   ReceiverConsumptionSummary `json:"summary"`
}

type ReadReceiverPhysicalInstallationRequest struct {
	ContractRevision        string `json:"contractRevision"`
	ReceiverRevision        string `json:"receiverRevision"`
	RequestId               string `json:"requestId"`
	PhysicalInstallProofRef string `json:"physicalInstallProofRef"`
	ExpectedBindingHash     string `json:"expectedBindingHash"`
}

type ReadReceiverPhysicalInstallationResponse struct {
	RequestId    string                       `json:"requestId"`
	Installation ReceiverPhysicalInstallation `json:"installation"`
}

type ReceiverArtifactRegistration struct {
	BootstrapId  string `json:"bootstrapId"`
	AnswerId     string `json:"answerId"`
	ArtifactId   string `json:"artifactId"`
	ArtifactHash string `json:"artifactHash"`
	BindingHash  string `json:"bindingHash"`
	Sequence     int64  `json:"sequence"`
	CreatedAt    string `json:"createdAt"`
}

type ReceiverAuthoritySnapshot struct {
	Registration         ReceiverRegistration         `json:"registration"`
	ArtifactRegistration ReceiverArtifactRegistration `json:"artifactRegistration"`
	Artifact             json.RawMessage              `json:"artifact"`
	Grant                json.RawMessage              `json:"grant"`
	GrantState           string                       `json:"grantState"`
	Permit               json.RawMessage              `json:"permit"`
	Observation          json.RawMessage              `json:"observation"`
	Consumption          ReceiverConsumptionSummary   `json:"consumption"`
	AuthorityTime        string                       `json:"authorityTime"`
	ValidUntil           string                       `json:"validUntil"`
	Timing               ReceiverTiming               `json:"timing"`
}

type ReceiverBarrierState struct {
	State string `json:"state"`
}

type ReceiverBootstrapBinding struct {
	BootstrapId             string `json:"bootstrapId"`
	TenantId                string `json:"tenantId"`
	OwnerId                 string `json:"ownerId"`
	RoomId                  string `json:"roomId"`
	RunId                   string `json:"runId"`
	SessionId               string `json:"sessionId"`
	ProducerIncarnation     string `json:"producerIncarnation"`
	AttemptId               string `json:"attemptId"`
	CommandId               string `json:"commandId"`
	TurnId                  string `json:"turnId"`
	UtteranceId             string `json:"utteranceId"`
	GuardianId              string `json:"guardianId"`
	GuardianIncarnation     string `json:"guardianIncarnation"`
	RuntimePrincipalId      string `json:"runtimePrincipalId"`
	PhysicalInstallProofRef string `json:"physicalInstallProofRef"`
	RunEpoch                int64  `json:"runEpoch"`
	GenerationId            int64  `json:"generationId"`
	OutputBindingVersion    int64  `json:"outputBindingVersion"`
	ContractRevision        string `json:"contractRevision"`
	ReceiverRevision        string `json:"receiverRevision"`
	RuntimeIncarnation      string `json:"runtimeIncarnation"`
}

type ReceiverBootstrapState struct {
	State string `json:"state"`
}

type ReceiverConsumeRequest struct {
	ContractRevision             string                `json:"contractRevision"`
	ReceiverRevision             string                `json:"receiverRevision"`
	RequestId                    string                `json:"requestId"`
	References                   ReceiverReferences    `json:"references"`
	ConsumeRequestId             string                `json:"consumeRequestId"`
	ExpectedGenerationId         int64                 `json:"expectedGenerationId"`
	ExpectedGuardianIncarnation  string                `json:"expectedGuardianIncarnation"`
	ExpectedRegistrationRevision int64                 `json:"expectedRegistrationRevision"`
	ConsumeTicket                ReceiverConsumeTicket `json:"consumeTicket"`
}

type ReceiverConsumeResponse struct {
	RequestId         string                     `json:"requestId"`
	ConsumeAuthorized bool                       `json:"consumeAuthorized"`
	Consumption       *ReceiverConsumption       `json:"consumption"`
	Summary           ReceiverConsumptionSummary `json:"summary"`
	ConsumeTiming     *ReceiverTiming            `json:"consumeTiming"`
}

type ReceiverConsumeTicket string
type ReceiverConsumption struct {
	ReceiptId            string          `json:"receiptId"`
	BootstrapId          string          `json:"bootstrapId"`
	ConsumeRequestId     string          `json:"consumeRequestId"`
	RuntimePrincipalId   string          `json:"runtimePrincipalId"`
	GuardianPrincipalId  string          `json:"guardianPrincipalId"`
	ChannelBinding       string          `json:"channelBinding"`
	RegistrationHash     string          `json:"registrationHash"`
	RegistrationRevision int64           `json:"registrationRevision"`
	Binding              json.RawMessage `json:"binding"`
	ConsumeIdentityHash  string          `json:"consumeIdentityHash"`
	RuntimeIncarnation   string          `json:"runtimeIncarnation"`
}

type ReceiverConsumptionState struct {
	State string `json:"state"`
}

type ReceiverConsumptionSummary struct {
	State     string  `json:"state"`
	ReceiptId *string `json:"receiptId"`
}

type ReceiverErrorResponse struct {
	RequestId string `json:"requestId"`
	Code      string `json:"code"`
}

type ReceiverFinishUnitRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	ExecutionId      string `json:"executionId"`
	ArtifactId       string `json:"artifactId"`
	ArtifactHash     string `json:"artifactHash"`
}

type ReceiverFinishUnitResponse struct {
	RequestId    string          `json:"requestId"`
	State        string          `json:"state"`
	ExecutionId  string          `json:"executionId"`
	ArtifactId   string          `json:"artifactId"`
	ArtifactHash string          `json:"artifactHash"`
	Evidence     json.RawMessage `json:"evidence"`
}

type ReceiverMediaRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	ExecutionId      string `json:"executionId"`
	PermitId         string `json:"permitId"`
	Kind             string `json:"kind"`
	Sequence         int64  `json:"sequence"`
	PtsUs            *int64 `json:"ptsUs"`
	Payload          string `json:"payload"`
	ArtifactId       string `json:"artifactId"`
	ArtifactHash     string `json:"artifactHash"`
}

type ReceiverMediaResponse struct {
	RequestId string `json:"requestId"`
	Accepted  bool   `json:"accepted"`
}

type ReceiverPhysicalInstallation struct {
	Binding               ReceiverBootstrapBinding `json:"binding"`
	InstallationRevision  int64                    `json:"installationRevision"`
	ObservedByPrincipalId string                   `json:"observedByPrincipalId"`
	GuardianPrincipalId   string                   `json:"guardianPrincipalId"`
	ClosedFenceProofRef   string                   `json:"closedFenceProofRef"`
	State                 string                   `json:"state"`
}

type ReceiverQueryConsumptionRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	BootstrapId      string `json:"bootstrapId"`
	GrantId          string `json:"grantId"`
}

type ReceiverQueryConsumptionResponse struct {
	RequestId string                     `json:"requestId"`
	Summary   ReceiverConsumptionSummary `json:"summary"`
}

type ReceiverReferences struct {
	BootstrapId  string `json:"bootstrapId"`
	ArtifactId   string `json:"artifactId"`
	GrantId      string `json:"grantId"`
	PermitId     string `json:"permitId"`
	ArtifactHash string `json:"artifactHash"`
}

type ReceiverRegistration struct {
	Binding          ReceiverBootstrapBinding `json:"binding"`
	RegistrationHash string                   `json:"registrationHash"`
	Revision         int64                    `json:"revision"`
	State            string                   `json:"state"`
	RegisteredAt     string                   `json:"registeredAt"`
	StageReceiptId   string                   `json:"stageReceiptId"`
}

type ReceiverRenewRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	ExecutionId      string `json:"executionId"`
	PermitId         string `json:"permitId"`
	ArtifactId       string `json:"artifactId"`
	ArtifactHash     string `json:"artifactHash"`
}

type ReceiverRenewResponse struct {
	RequestId   string          `json:"requestId"`
	State       string          `json:"state"`
	Permit      json.RawMessage `json:"permit"`
	Observation json.RawMessage `json:"observation"`
	Timing      ReceiverTiming  `json:"timing"`
}

type ReceiverStageReceipt struct {
	StageReceiptId       string `json:"stageReceiptId"`
	Challenge            string `json:"challenge"`
	GuardianPrincipalId  string `json:"guardianPrincipalId"`
	GuardianIncarnation  string `json:"guardianIncarnation"`
	KeyId                string `json:"keyId"`
	BindingHash          string `json:"bindingHash"`
	ValidUntil           string `json:"validUntil"`
	State                string `json:"state"`
	Signature            string `json:"signature"`
	AuthorityIssuedAt    string `json:"authorityIssuedAt"`
	ContractRevision     string `json:"contractRevision"`
	ReceiverRevision     string `json:"receiverRevision"`
	InstallationRevision int64  `json:"installationRevision"`
}

type ReceiverStageRequest struct {
	ContractRevision   string                   `json:"contractRevision"`
	ReceiverRevision   string                   `json:"receiverRevision"`
	RequestId          string                   `json:"requestId"`
	Binding            ReceiverBootstrapBinding `json:"binding"`
	Challenge          string                   `json:"challenge"`
	ChallengeIssuedAt  string                   `json:"challengeIssuedAt"`
	ChallengeExpiresAt string                   `json:"challengeExpiresAt"`
}

type ReceiverStageResponse struct {
	RequestId string               `json:"requestId"`
	Receipt   ReceiverStageReceipt `json:"receipt"`
}

type ReceiverStopRequest struct {
	ContractRevision string `json:"contractRevision"`
	ReceiverRevision string `json:"receiverRevision"`
	RequestId        string `json:"requestId"`
	RunId            string `json:"runId"`
}

type ReceiverStopResponse struct {
	RequestId string `json:"requestId"`
	State     string `json:"state"`
	RunId     string `json:"runId"`
}

type ReceiverTiming struct {
	RemainingGrantMs int64 `json:"remainingGrantMs"`
	RemainingProofMs int64 `json:"remainingProofMs"`
	SafetyMarginMs   int64 `json:"safetyMarginMs"`
}

type RegisterReceiverBootstrapRequest struct {
	ContractRevision             string                   `json:"contractRevision"`
	ReceiverRevision             string                   `json:"receiverRevision"`
	RequestId                    string                   `json:"requestId"`
	Binding                      ReceiverBootstrapBinding `json:"binding"`
	Receipt                      ReceiverStageReceipt     `json:"receipt"`
	ExpectedRegistrationRevision int64                    `json:"expectedRegistrationRevision"`
	ExpectedRunRevision          int64                    `json:"expectedRunRevision"`
	ExpectedLeaseVersion         int64                    `json:"expectedLeaseVersion"`
}

type RegisterReceiverBootstrapResponse struct {
	RequestId    string               `json:"requestId"`
	Registration ReceiverRegistration `json:"registration"`
}

type RevokeReceiverBootstrapRequest struct {
	ContractRevision             string `json:"contractRevision"`
	ReceiverRevision             string `json:"receiverRevision"`
	RequestId                    string `json:"requestId"`
	BootstrapId                  string `json:"bootstrapId"`
	ExpectedRegistrationRevision int64  `json:"expectedRegistrationRevision"`
	Reason                       string `json:"reason"`
}

type RevokeReceiverBootstrapResponse struct {
	RequestId    string               `json:"requestId"`
	Registration ReceiverRegistration `json:"registration"`
}

type RegistrarPrivate interface {
	ReadReceiverPhysicalInstallation(context.Context, ReadReceiverPhysicalInstallationRequest) (ReadReceiverPhysicalInstallationResponse, error)
}

type BackendPrivate interface {
	RegisterReceiverBootstrap(context.Context, RegisterReceiverBootstrapRequest) (RegisterReceiverBootstrapResponse, error)
	RevokeReceiverBootstrap(context.Context, RevokeReceiverBootstrapRequest) (RevokeReceiverBootstrapResponse, error)
	QueryReceiverAuthority(context.Context, QueryReceiverAuthorityRequest) (QueryReceiverAuthorityResponse, error)
	CommitReceiverConsume(context.Context, CommitReceiverConsumeRequest) (CommitReceiverConsumeResponse, error)
	QueryReceiverConsumption(context.Context, QueryReceiverConsumptionRequest) (QueryReceiverConsumptionResponse, error)
}

type GuardianPrivate interface {
	ReceiverStage(context.Context, ReceiverStageRequest) (ReceiverStageResponse, error)
	ReceiverConsume(context.Context, ReceiverConsumeRequest) (ReceiverConsumeResponse, error)
	ReceiverRenew(context.Context, ReceiverRenewRequest) (ReceiverRenewResponse, error)
	ReceiverQueryConsumption(context.Context, ReceiverQueryConsumptionRequest) (ReceiverQueryConsumptionResponse, error)
	ReceiverMedia(context.Context, ReceiverMediaRequest) (ReceiverMediaResponse, error)
	ReceiverFinishUnit(context.Context, ReceiverFinishUnitRequest) (ReceiverFinishUnitResponse, error)
	ReceiverStop(context.Context, ReceiverStopRequest) (ReceiverStopResponse, error)
}

// Backend-owned internal repository interface. Co-located CONTROL Registrar
// allocates a persisted DB-time challenge after trusted installation preflight.
// An independently deployed Registrar is not supported by an invented RPC.
type StageChallenge struct {
	Nonce             string
	BindingHash       string
	AuthorityIssuedAt string
	ExpiresAt         string
}
type RegistrarRepository interface {
	IssueStageChallenge(context.Context, ReceiverBootstrapBinding, int64, int64) (StageChallenge, error)
}
