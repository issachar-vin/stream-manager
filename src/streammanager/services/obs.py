import subprocess
import time

import obsws_python as obs

from ..config.config_manager import OBSSavedConfig as OBSConfig

YOUTUBE_RTMP_SERVER = "rtmp://a.rtmp.youtube.com/live2"
FACEBOOK_OUTPUT_NAME = "Facebook Live"


class OBSService:
    def __init__(self, config: OBSConfig) -> None:
        self._config = config
        self._client: obs.ReqClient | None = None

    def connect(self, launch_if_closed: bool = True) -> None:
        if self._client:
            return
        if launch_if_closed and not self._is_obs_running():
            self._launch_obs()
        self._client = obs.ReqClient(
            host=self._config.host,
            port=self._config.port,
            password=self._config.password,
            timeout=5,
        )

    def disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None

    def configure_primary_output(self, server: str, key: str) -> None:
        client = self._require_client()
        try:
            if client.get_stream_status().output_active:
                client.stop_stream()
                time.sleep(1)
        except Exception:
            pass
        client.set_stream_service_settings(
            "rtmp_custom", {"server": server, "key": key}
        )
        # Verify the settings were applied — OBS silently ignores unknown service types.
        try:
            result = client.get_stream_service_settings()
            applied = getattr(result, "stream_service_settings", {}) or {}
            if applied.get("server") != server:
                got = repr(applied.get("server"))
                raise RuntimeError(
                    f"OBS did not apply stream settings (got server={got})"
                )
        except AttributeError:
            pass  # obsws_python version without get_stream_service_settings

    def configure_secondary_output(self, name: str, server: str, key: str) -> None:
        self._require_client().set_output_settings(name, {"server": server, "key": key})

    def start_streaming(self) -> None:
        self._require_client().start_stream()

    def stop_streaming(self) -> None:
        self._require_client().stop_stream()

    def start_output(self, name: str) -> None:
        self._require_client().start_output(name)

    def stop_output(self, name: str) -> None:
        self._require_client().stop_output(name)

    def get_output_list(self) -> list[str]:
        try:
            result = self._require_client().get_output_list()
            outputs: list[dict] = getattr(result, "outputs", []) or []
            return [o["outputName"] for o in outputs if o.get("outputName")]
        except Exception:
            return []

    def check_status(self) -> tuple[bool, bool]:
        """Returns (connected, streaming) via a short-lived connection. Thread-safe."""
        if not self._is_obs_running():
            return False, False
        try:
            tmp = obs.ReqClient(
                host=self._config.host,
                port=self._config.port,
                password=self._config.password,
                timeout=3,
            )
            streaming = bool(tmp.get_stream_status().output_active)
            tmp.disconnect()
            return True, streaming
        except Exception:
            return False, False

    def _require_client(self) -> obs.ReqClient:
        if self._client is None:
            raise RuntimeError("Not connected to OBS. Call connect() first.")
        return self._client

    def _is_obs_running(self) -> bool:
        result = subprocess.run(
            ["pgrep", "-x", "OBS"],
            capture_output=True,
        )
        return result.returncode == 0

    def _launch_obs(self) -> None:
        subprocess.Popen(["open", "-a", "OBS"])
        # Wait for the WebSocket server to become available
        for _ in range(30):
            time.sleep(1)
            if self._is_obs_running():
                time.sleep(3)  # give the WebSocket server a moment to bind
                break
