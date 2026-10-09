from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit, quote, unquote


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


# Profile defaults are deliberately limited to the accepted generic output.
RTMP_PROFILES = {"generic": dict(width=720, height=1280, fps=25,
    video_bitrate="3000k", audio_bitrate="128k", audio_sample_rate=48000,
    preset="veryfast")}


@dataclass(frozen=True)
class RTMPSettings:
    enabled: bool = False
    url: str | None = field(default=None, repr=False)
    stream_key: str | None = field(default=None, repr=False)
    publish_url: str | None = field(default=None, repr=False)
    platform: str = "generic"
    gop: int | None = None
    width: int = 720
    height: int = 1280
    fps: int = 25
    video_bitrate: str = "3000k"
    audio_bitrate: str = "128k"
    audio_sample_rate: int = 48000
    preset: str = "veryfast"
    video_buffer_ms: int = 400
    audio_buffer_ms: int = 400
    reconnect_initial_ms: int = 1000
    reconnect_max_ms: int = 30000
    recovery_window_ms: int = 120000
    stop_timeout_ms: int = 5000
    ffmpeg_binary: str = "ffmpeg"

    @classmethod
    def from_env(cls) -> "RTMPSettings":
        platform = os.getenv("RTMP_PLATFORM", "generic")
        if platform not in RTMP_PROFILES:
            raise ValueError("Unsupported RTMP_PLATFORM")
        profile = RTMP_PROFILES[platform]
        settings = cls(
            enabled=_bool("RTMP_ENABLED", False),
            platform=platform,
            publish_url=os.getenv("RTMP_PUBLISH_URL") or None,
            gop=_positive_int("RTMP_GOP", 50) if os.getenv("RTMP_GOP") else None,
            url=os.getenv("RTMP_URL") or None,
            stream_key=os.getenv("RTMP_STREAM_KEY") or None,
            width=_positive_int("RTMP_WIDTH", profile["width"]),
            height=_positive_int("RTMP_HEIGHT", profile["height"]),
            fps=_positive_int("RTMP_FPS", profile["fps"]),
            video_bitrate=os.getenv("RTMP_VIDEO_BITRATE", profile["video_bitrate"]),
            audio_bitrate=os.getenv("RTMP_AUDIO_BITRATE", profile["audio_bitrate"]),
            audio_sample_rate=_positive_int("RTMP_AUDIO_SAMPLE_RATE", profile["audio_sample_rate"]),
            preset=os.getenv("RTMP_PRESET", profile["preset"]),
            video_buffer_ms=_positive_int("RTMP_VIDEO_BUFFER_MS", 400),
            audio_buffer_ms=_positive_int("RTMP_AUDIO_BUFFER_MS", 400),
            reconnect_initial_ms=_positive_int("RTMP_RECONNECT_INITIAL_MS", 1000),
            reconnect_max_ms=_positive_int("RTMP_RECONNECT_MAX_MS", 30000),
            recovery_window_ms=_positive_int("RTMP_RECOVERY_WINDOW_MS", 120000),
            stop_timeout_ms=_positive_int("RTMP_STOP_TIMEOUT_MS", 5000),
            ffmpeg_binary=os.getenv("FFMPEG_BINARY", "ffmpeg"),
        )
        return settings

    def __post_init__(self) -> None:
        if self.platform not in RTMP_PROFILES:
            raise ValueError("Unsupported RTMP_PLATFORM")
        for value in (self.width, self.height, self.fps, self.audio_sample_rate,
                      self.video_buffer_ms, self.audio_buffer_ms, self.reconnect_initial_ms,
                      self.reconnect_max_ms, self.recovery_window_ms, self.stop_timeout_ms):
            if value <= 0:
                raise ValueError("RTMP numeric settings must be positive")
        if self.width % 2 or self.height % 2:
            raise ValueError("RTMP_WIDTH and RTMP_HEIGHT must be even for yuv420p")
        if self.gop is not None and self.gop <= 0:
            raise ValueError("RTMP_GOP must be positive")
        if self.audio_sample_rate not in {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000}:
            raise ValueError("Invalid AAC sample rate")
        if self.preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}:
            raise ValueError("Invalid libx264 preset")
        if not all(re.fullmatch(r"[1-9][0-9]*[kKmM]?", v) for v in (self.video_bitrate, self.audio_bitrate)):
            raise ValueError("Invalid RTMP bitrate")
        if self.reconnect_initial_ms > self.reconnect_max_ms:
            raise ValueError("RTMP reconnect initial exceeds maximum")
        if self.publish_url and (self.url or self.stream_key):
            raise ValueError("Use RTMP_PUBLISH_URL or RTMP_URL plus RTMP_STREAM_KEY exclusively")
        if self.enabled or self.publish_url or self.url:
            parsed = self.parsed_target
            if not self.publish_url and urlsplit(self.url).query:
                raise ValueError("Use RTMP_PUBLISH_URL for query-authenticated targets")
            if self.publish_url and (not parsed.path.strip("/") or parsed.path.endswith("/")):
                raise ValueError("Full publish URL must include a publish path")

    @property
    def target(self) -> str:
        if self.publish_url:
            return self.publish_url
        if not self.url or not self.stream_key or not self.stream_key.strip("/"):
            raise ValueError("RTMP_URL and RTMP_STREAM_KEY are required")
        return f"{self.url.rstrip('/')}/{self.stream_key.lstrip('/')}"

    @property
    def parsed_target(self):
        try:
            target = self.target
            parsed = urlsplit(target)
            if (parsed.scheme not in {"rtmp", "rtmps"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in target)):
                raise ValueError
            if parsed.port == 0:
                raise ValueError
            # Parse the port without echoing an invalid credential-bearing URL.
            return parsed
        except (ValueError, TypeError):
            raise ValueError("Invalid RTMP publish target") from None

    @property
    def gop_frames(self) -> int:
        return self.gop if self.gop is not None else self.fps * 2

    @property
    def redacted_target(self) -> str:
        if not (self.url or self.publish_url):
            return "RTMP target not configured"
        parsed = self.parsed_target
        return f"{parsed.scheme}://{parsed.netloc}/***"

    def redact(self, text: str) -> str:
        # FFmpeg can echo only the key or query rather than the complete URL.
        secrets = [self.target, self.stream_key or ""]
        parsed = self.parsed_target
        secrets.extend([parsed.path, parsed.query])
        secrets.extend(parsed.path.split("/"))
        secrets.extend(part.split("=", 1)[-1] for part in parsed.query.split("&"))
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret:
                for form in {secret, unquote(secret), quote(secret, safe="")}:
                    if form:
                        text = text.replace(form, "***")
        return re.sub(r"rtmps?://[^\s\\\"'<>]+", "rtmp://***", text)


@dataclass(frozen=True)
class Settings:
    mock_llm: bool = True
    mock_tts: bool = True
    mock_avatar: bool = True
    mock_media: bool = True
    redis_url: str | None = None
    tool_base_url: str | None = None
    tool_token: str | None = None
    max_sessions: int = 8
    max_queue: int = 100
    webrtc_enabled: bool = True
    rtmp: RTMPSettings = field(default_factory=RTMPSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mock_llm=_bool("MOCK_LLM", True),
            mock_tts=_bool("MOCK_TTS", True),
            mock_avatar=_bool("MOCK_AVATAR", True),
            mock_media=_bool("MOCK_MEDIA", True),
            redis_url=os.getenv("REDIS_URL") or None,
            tool_base_url=os.getenv("TOOL_BASE_URL") or None,
            tool_token=os.getenv("TOOL_TOKEN") or None,
            max_sessions=int(os.getenv("MAX_SESSIONS", "8")),
            max_queue=int(os.getenv("MAX_SPEECH_QUEUE", "100")),
            webrtc_enabled=_bool("WEBRTC_ENABLED", True),
            rtmp=RTMPSettings.from_env(),
        )
