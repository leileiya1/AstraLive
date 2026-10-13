from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AvatarConfig(BaseModel):
    avatarId: str
    engine: str


class VoiceConfig(BaseModel):
    voiceId: str
    provider: str | None = None


class CreateVoiceConfig(BaseModel):
    voiceId: str
    provider: str


class PreviewConfig(BaseModel):
    type: str = Field(pattern="^WEBRTC$")


class SessionConfig(BaseModel):
    fps: int = Field(ge=1)
    preview: PreviewConfig


class RuntimeSessionContext(StrictModel):
    roomId: str = Field(min_length=1)
    systemPrompt: str
    activeProductId: str | None = Field(default=None, min_length=1)
    knowledgeBaseId: str | None = Field(default=None, min_length=1)


class Command(StrictModel):
    commandId: str = Field(min_length=1)
    traceId: str = Field(min_length=1)


class CreateSession(Command):
    sessionId: str = Field(min_length=1)
    avatar: AvatarConfig
    voice: CreateVoiceConfig
    config: SessionConfig
    context: RuntimeSessionContext


class InterruptPolicy(str, Enum):
    NONE = "NONE"
    INTERRUPT_LOWER_PRIORITY = "INTERRUPT_LOWER_PRIORITY"
    FORCE = "FORCE"


class UtteranceSource(str, Enum):
    OPERATOR = "OPERATOR"
    PLATFORM_EVENT = "PLATFORM_EVENT"
    AUTO_SCRIPT = "AUTO_SCRIPT"
    SYSTEM = "SYSTEM"


class PlatformUser(StrictModel):
    externalId: str = Field(min_length=1)
    nickname: str = Field(min_length=1)


class PlatformContext(StrictModel):
    eventType: Literal["COMMENT"]
    user: PlatformUser


class Utterance(Command):
    utteranceId: str = Field(min_length=1)
    text: str = Field(min_length=1)
    priority: int
    interruptPolicy: InterruptPolicy
    source: UtteranceSource
    platformContext: PlatformContext | None = None
    voice: VoiceConfig


class WebRTCOffer(StrictModel):
    type: Literal["offer"]
    sdp: str = Field(min_length=1)


class Interrupt(Command):
    reason: str = Field(min_length=1)


class SpeechPlan(StrictModel):
    action: str = Field(pattern="^SPEAK$")
    text: str = Field(min_length=1)
    priority: int
    emotion: str | None = None
    gesture: str | None = None
    interrupt: bool | None = None
    uiAction: dict[str, Any] | None = None


class Accepted(StrictModel):
    accepted: bool = True
    operationId: str
