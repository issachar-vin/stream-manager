import contextlib
from datetime import datetime

from .config.config_manager import ConfigManager
from .models.stream import StreamConfig, StreamStatus
from .services.facebook import FacebookPage, FacebookService
from .services.obs import OBSService
from .services.rtmp_relay import RTMPRelay
from .services.youtube import YouTubeService


class StreamManagerApp:
    def __init__(self, config_manager: ConfigManager) -> None:
        self._cfg = config_manager
        self._obs = OBSService(config_manager.config.obs)
        self._youtube = YouTubeService(config_manager)
        self._facebook = FacebookService(config_manager)
        self._relay: RTMPRelay | None = None

    @property
    def facebook(self) -> FacebookService:
        return self._facebook

    @property
    def youtube(self) -> YouTubeService:
        return self._youtube

    @property
    def config(self) -> ConfigManager:
        return self._cfg

    def open_facebook_token_page(self) -> None:
        self._facebook.open_token_page()

    def login_facebook_with_token(self, token: str) -> None:
        self._facebook.authenticate_with_token(token)

    def fetch_facebook_pages(self) -> list[FacebookPage]:
        return self._facebook.fetch_pages()

    def select_facebook_page(self, page: FacebookPage) -> None:
        self._facebook.select_page(page)

    def login_youtube(self) -> None:
        self._youtube.authenticate()

    def get_youtube_channel_name(self) -> str | None:
        return self._youtube.get_channel_name()

    def get_youtube_broadcast_url(self) -> str | None:
        return self._youtube.get_broadcast_url()

    def get_facebook_stream_url(self) -> str | None:
        return self._facebook.get_stream_url()

    def check_obs_status(self) -> tuple[bool, bool]:
        """Returns (connected, streaming). Safe to call from any thread."""
        return self._obs.check_status()

    def go_live(
        self, config: StreamConfig, *, youtube: bool = True, facebook: bool = True
    ) -> StreamStatus:
        self._obs = OBSService(self._cfg.config.obs)
        self._obs.connect()

        status = StreamStatus()
        now = datetime.now().strftime("%I:%M %p")

        # ── Both platforms — use ffmpeg relay ─────────────────────────────
        if youtube and facebook:
            status.youtube.attempted = True
            status.facebook.attempted = True
            try:
                yt_server, yt_key = self._youtube.create_stream(config)
                fb_server, fb_key = self._facebook.create_stream(config)
                yt_dest = yt_server.rstrip("/") + "/" + yt_key
                fb_dest = fb_server.rstrip("/") + "/" + fb_key
                relay = RTMPRelay()
                relay.start(yt_dest, fb_dest)
                self._relay = relay
                self._obs.configure_primary_output(
                    server=relay.obs_server, key=relay.obs_key
                )
                self._obs.start_streaming()
                status.youtube.live = True
                status.youtube.started_at = now
                status.youtube.title = config.title
                status.youtube.url = self._youtube.get_broadcast_url()
                status.facebook.live = True
                status.facebook.started_at = now
                status.facebook.title = config.title
                status.facebook.page_name = self._cfg.config.facebook.last_page_name
                status.facebook.url = self._facebook.get_stream_url()
            except Exception as exc:
                if self._relay:
                    self._relay.stop()
                    self._relay = None
                err = str(exc)
                status.youtube.error = err
                status.facebook.error = err

        # ── YouTube only ──────────────────────────────────────────────────
        elif youtube:
            status.youtube.attempted = True
            try:
                yt_server, yt_key = self._youtube.create_stream(config)
                self._obs.configure_primary_output(server=yt_server, key=yt_key)
                self._obs.start_streaming()
                status.youtube.live = True
                status.youtube.started_at = now
                status.youtube.title = config.title
                status.youtube.url = self._youtube.get_broadcast_url()
            except Exception as exc:
                status.youtube.error = str(exc)

        # ── Facebook only ─────────────────────────────────────────────────
        elif facebook:
            status.facebook.attempted = True
            try:
                fb_server, fb_key = self._facebook.create_stream(config)
                self._obs.configure_primary_output(server=fb_server, key=fb_key)
                self._obs.start_streaming()
                status.facebook.live = True
                status.facebook.started_at = now
                status.facebook.title = config.title
                status.facebook.page_name = self._cfg.config.facebook.last_page_name
                status.facebook.url = self._facebook.get_stream_url()
            except Exception as exc:
                status.facebook.error = str(exc)

        if not status.any_live:
            self._obs.disconnect()

        return status

    def end_stream(self) -> None:
        # Connect without launching in case the stream was started outside this app.
        with contextlib.suppress(Exception):
            self._obs.connect(launch_if_closed=False)
        with contextlib.suppress(Exception):
            self._obs.stop_streaming()
        if self._relay:
            with contextlib.suppress(Exception):
                self._relay.stop()
            self._relay = None
        with contextlib.suppress(Exception):
            self._youtube.end_stream()
        with contextlib.suppress(Exception):
            self._facebook.end_stream()
        self._obs.disconnect()
