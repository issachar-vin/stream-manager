import json
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests

from ..config.config_manager import ConfigManager
from ..models.stream import StreamConfig

GRAPH_API_BASE = "https://graph.facebook.com/v22.0"


@dataclass
class FacebookPage:
    id: str
    name: str
    access_token: str


PERSONAL_PROFILE = FacebookPage(id="me", name="Personal Profile", access_token="")


class FacebookService:
    def __init__(self, config_manager: ConfigManager) -> None:
        self._cfg = config_manager
        self._page: FacebookPage | None = None
        self._live_video_id: str | None = None
        self._stream_token: str | None = None
        self._permalink_url: str | None = None

    # ── Auth ──────────────────────────────────────────────────────────────

    def is_authenticated(self) -> bool:
        return self._cfg.is_facebook_token_valid()

    def open_token_page(self) -> None:
        """Opens Graph API Explorer in the browser pre-configured for this app."""
        fb = self._cfg.config.facebook
        params = {
            "client_id": fb.app_id,
            "scope": ",".join(
                [
                    "pages_show_list",
                    "pages_read_engagement",
                    "pages_manage_posts",
                    "publish_video",
                ]
            ),
        }
        url = f"https://developers.facebook.com/tools/explorer?{urlencode(params)}"
        webbrowser.open(url)

    def authenticate_with_token(self, short_lived_token: str) -> None:
        """
        Exchanges a short-lived token from Graph API Explorer for a
        long-lived token (~60 days) and persists it.
        """
        fb = self._cfg.config.facebook
        if not fb.app_id or not fb.app_secret:
            raise RuntimeError(
                "Facebook App ID and Secret are required. Set them in Settings."
            )

        long_lived, expires_in = self._exchange_for_long_lived(
            fb.app_id, fb.app_secret, short_lived_token.strip()
        )

        expiry = datetime.now(UTC) + timedelta(seconds=expires_in)
        self._cfg.config.facebook.access_token = long_lived
        self._cfg.config.facebook.token_expires_at = expiry.isoformat()
        self._cfg.save()

    def _exchange_for_long_lived(
        self, app_id: str, app_secret: str, short_lived: str
    ) -> tuple[str, int]:
        url = (
            f"{GRAPH_API_BASE}/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={app_id}"
            f"&client_secret={app_secret}"
            f"&fb_exchange_token={short_lived}"
        )
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            data: dict[str, object] = json.loads(resp.read())
        return str(data["access_token"]), int(data.get("expires_in", 5184000))  # type: ignore[call-overload]

    # ── Pages ─────────────────────────────────────────────────────────────

    def fetch_pages(self) -> list[FacebookPage]:
        token = self._cfg.config.facebook.access_token
        if not token:
            raise RuntimeError("Not authenticated.")

        response = requests.get(
            f"{GRAPH_API_BASE}/me/accounts",
            params={"access_token": token},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        pages = [
            FacebookPage(
                id=item["id"],
                name=item["name"],
                access_token=item["access_token"],
            )
            for item in data.get("data", [])
        ]

        last_id = self._cfg.config.facebook.last_page_id
        if last_id and not self._page:
            if last_id == "me":
                self._page = PERSONAL_PROFILE
            else:
                self._page = next((p for p in pages if p.id == last_id), None)

        return pages

    def select_page(self, page: FacebookPage) -> None:
        self._page = page
        self._cfg.config.facebook.last_page_id = page.id
        self._cfg.config.facebook.last_page_name = page.name
        self._cfg.save()

    # ── Streaming ─────────────────────────────────────────────────────────

    FB_RTMP_SERVER = "rtmps://live-api-s.facebook.com:443/rtmp/"

    def create_stream(self, config: StreamConfig) -> tuple[str, str]:
        fb = self._cfg.config.facebook
        if fb.stream_key_enabled and fb.stream_key_override:
            return self.FB_RTMP_SERVER, fb.stream_key_override

        if not self._page:
            raise RuntimeError(
                "No destination selected. Select a Page before going live."
            )

        if self._page.id == "me":
            token = self._cfg.config.facebook.access_token
            if not token:
                raise RuntimeError(
                    "No access token. Save your token in Settings first."
                )
        else:
            token = self._page.access_token

        self._stream_token = token

        last_exc: Exception | None = None
        for _attempt in range(2):
            try:
                response = requests.post(
                    f"{GRAPH_API_BASE}/{self._page.id}/live_videos",
                    params={
                        "access_token": token,
                        "fields": "id,stream_url,secure_stream_url,permalink_url",
                    },
                    data={
                        "title": config.title,
                        "description": config.description,
                        "status": "LIVE_NOW",
                        "privacy": f'{{"value":"{config.fb_privacy}"}}',
                    },
                    timeout=60,
                )
                if response.status_code == 500 and self._page.id == "me":
                    raise RuntimeError(
                        "Facebook rejected the live video request for your personal"
                        " profile. Personal profiles have restricted API access for"
                        " live streaming. Try selecting a Facebook Page instead."
                    )
                response.raise_for_status()
                break
            except requests.Timeout as exc:
                last_exc = exc
        else:
            raise RuntimeError(
                "Facebook API timed out after two attempts. Check your connection."
            ) from last_exc
        data = response.json()

        self._live_video_id = data["id"]
        raw_permalink = data.get("permalink_url", "")
        if raw_permalink.startswith("http"):
            self._permalink_url = raw_permalink
        elif raw_permalink.startswith("/"):
            self._permalink_url = f"https://www.facebook.com{raw_permalink}"
        else:
            self._permalink_url = None

        stream_url: str | None = data.get("secure_stream_url") or data.get("stream_url")
        if not stream_url:
            raise RuntimeError(
                "Facebook API did not return a stream URL. "
                "Check that your token has the publish_video permission."
            )

        # Always use the hardcoded RTMPS server and extract just the key.
        # The API URL is rtmps://live-api-s.facebook.com:443/rtmp/<key>?s_sw=1
        # Using rfind("/rtmp/") avoids any issue with rsplit on the query string.
        rtmp_idx = stream_url.rfind("/rtmp/")
        if rtmp_idx != -1:
            key = stream_url[rtmp_idx + 6 :]
        else:
            _, key = stream_url.rsplit("/", 1)
        return self.FB_RTMP_SERVER, key

    def get_stream_url(self) -> str | None:
        return self._permalink_url

    def end_stream(self) -> None:
        if self._live_video_id and self._stream_token:
            requests.post(
                f"{GRAPH_API_BASE}/{self._live_video_id}",
                params={
                    "access_token": self._stream_token,
                    "end_live_video": "true",
                },
                timeout=30,
            )
            self._live_video_id = None
            self._stream_token = None
            self._permalink_url = None
