import json
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "StreamManager"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class OBSSavedConfig:
    host: str = "localhost"
    port: int = 4455
    password: str = ""


@dataclass
class FacebookSavedConfig:
    app_id: str = ""
    app_secret: str = ""
    access_token: str = ""
    token_expires_at: str = ""  # ISO-8601
    last_page_id: str = ""
    last_page_name: str = ""
    stream_key_override: str = ""
    stream_key_enabled: bool = False


@dataclass
class YouTubeSavedConfig:
    client_id: str = ""
    client_secret: str = ""
    channel_name: str = ""


@dataclass
class StreamDefaults:
    last_title: str = ""
    last_description: str = ""
    youtube_enabled: bool = True
    facebook_enabled: bool = True
    fb_privacy: str = "Public"


@dataclass
class AppConfig:
    obs: OBSSavedConfig = field(default_factory=OBSSavedConfig)
    facebook: FacebookSavedConfig = field(default_factory=FacebookSavedConfig)
    youtube: YouTubeSavedConfig = field(default_factory=YouTubeSavedConfig)
    stream: StreamDefaults = field(default_factory=StreamDefaults)


class ConfigManager:
    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._config = self._load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def save(self) -> None:
        with open(CONFIG_FILE, "w") as f:
            json.dump(asdict(self._config), f, indent=2)

    def is_facebook_token_valid(self) -> bool:
        token = self._config.facebook.access_token
        expires_at = self._config.facebook.token_expires_at
        if not token or not expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(expires_at)
            return datetime.now(UTC) < expiry
        except ValueError:
            return False

    def days_until_facebook_expiry(self) -> int | None:
        expires_at = self._config.facebook.token_expires_at
        if not expires_at:
            return None
        try:
            expiry = datetime.fromisoformat(expires_at)
            delta = expiry - datetime.now(UTC)
            return max(0, delta.days)
        except ValueError:
            return None

    def is_youtube_configured(self) -> bool:
        cfg = self._config.youtube
        return bool(cfg.client_id and cfg.client_secret)

    def is_obs_configured(self) -> bool:
        return bool(self._config.obs.password)

    def _load(self) -> AppConfig:
        if not CONFIG_FILE.exists():
            return AppConfig()
        try:
            with open(CONFIG_FILE) as f:
                data: dict[str, object] = json.load(f)

            def _load_dc(cls: type, raw: object) -> object:
                if not isinstance(raw, dict):
                    return cls()
                known = {f.name for f in fields(cls)}
                return cls(**{k: v for k, v in raw.items() if k in known})

            return AppConfig(
                obs=_load_dc(OBSSavedConfig, data.get("obs", {})),  # type: ignore[arg-type]
                facebook=_load_dc(FacebookSavedConfig, data.get("facebook", {})),  # type: ignore[arg-type]
                youtube=_load_dc(YouTubeSavedConfig, data.get("youtube", {})),  # type: ignore[arg-type]
                stream=_load_dc(StreamDefaults, data.get("stream", {})),  # type: ignore[arg-type]
            )
        except Exception:
            return AppConfig()
