import json
import os
import tempfile
from datetime import UTC, datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config.config_manager import CONFIG_DIR, ConfigManager
from ..models.stream import StreamConfig

SCOPES = ["https://www.googleapis.com/auth/youtube"]
YOUTUBE_RTMP_SERVER = "rtmp://a.rtmp.youtube.com/live2"
_TOKEN_FILE = CONFIG_DIR / "youtube_token.json"


class YouTubeService:
    def __init__(self, config_manager: ConfigManager) -> None:
        self._cfg = config_manager
        self._service = None  # type: ignore[var-annotated]
        self._broadcast_id: str | None = None

    def is_authenticated(self) -> bool:
        if not _TOKEN_FILE.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)  # type: ignore[assignment]
            return creds.valid or creds.refresh_token is not None  # type: ignore[union-attr]
        except Exception:
            return False

    def authenticate(self) -> None:
        creds: Credentials | None = None
        if _TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)  # type: ignore[assignment]

        if not creds or not creds.valid:  # type: ignore[union-attr]
            yt = self._cfg.config.youtube
            if not yt.client_id or not yt.client_secret:
                raise RuntimeError(
                    "YouTube client credentials are required. Add them in Settings."
                )
            # Build a temporary client_secrets.json from stored credentials
            secrets = {
                "installed": {
                    "client_id": yt.client_id,
                    "client_secret": yt.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                json.dump(secrets, tmp)
                tmp_path = tmp.name

            try:
                flow: InstalledAppFlow = InstalledAppFlow.from_client_secrets_file(
                    tmp_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            finally:
                os.unlink(tmp_path)

            _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())  # type: ignore[union-attr]

        self._service = build("youtube", "v3", credentials=creds)

    def create_stream(self, config: StreamConfig) -> tuple[str, str]:
        if self._service is None:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        scheduled_start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        broadcast = (
            self._service.liveBroadcasts()
            .insert(
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        "title": config.title,
                        "description": config.description,
                        "scheduledStartTime": scheduled_start,
                    },
                    "status": {"privacyStatus": "public"},
                    "contentDetails": {"enableAutoStart": True},
                },
            )
            .execute()
        )
        self._broadcast_id = broadcast["id"]

        stream = (
            self._service.liveStreams()
            .insert(
                part="snippet,cdn",
                body={
                    "snippet": {"title": config.title},
                    "cdn": {
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                    },
                },
            )
            .execute()
        )

        self._service.liveBroadcasts().bind(
            part="id,contentDetails",
            id=self._broadcast_id,
            streamId=stream["id"],
        ).execute()

        key: str = stream["cdn"]["ingestionInfo"]["streamName"]
        return YOUTUBE_RTMP_SERVER, key

    def get_broadcast_url(self) -> str | None:
        if self._broadcast_id:
            return f"https://www.youtube.com/watch?v={self._broadcast_id}"
        return None

    def get_channel_name(self) -> str | None:
        if self._service is None:
            return None
        try:
            response = (
                self._service.channels().list(part="snippet", mine=True).execute()
            )
            items = response.get("items", [])
            if items:
                return str(items[0]["snippet"]["title"])
        except Exception:
            pass
        return None

    def end_stream(self) -> None:
        if self._service and self._broadcast_id:
            self._service.liveBroadcasts().transition(
                broadcastStatus="complete",
                id=self._broadcast_id,
                part="id,status",
            ).execute()
            self._broadcast_id = None
