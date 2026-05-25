import socket
import subprocess
import time


class RTMPRelay:
    """Local ffmpeg RTMP relay that forwards one OBS stream to multiple destinations."""

    _KEY = "stream"

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._port: int | None = None

    @property
    def obs_server(self) -> str:
        return f"rtmp://localhost:{self._port}/live"

    @property
    def obs_key(self) -> str:
        return self._KEY

    def start(self, *destinations: str) -> None:
        self._check_ffmpeg()
        self._port = self._free_port()

        output_args: list[str] = []
        for dest in destinations:
            output_args += ["-c", "copy", "-f", "flv", dest]

        self._proc = subprocess.Popen(
            [
                "ffmpeg",
                "-listen",
                "1",
                "-f",
                "flv",
                "-i",
                f"rtmp://0.0.0.0:{self._port}/live/{self._KEY}",
                *output_args,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give ffmpeg time to bind the port before OBS connects.
        time.sleep(1.5)
        if self._proc.poll() is not None:
            raise RuntimeError("ffmpeg relay exited immediately — check ffmpeg logs.")

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        self._port = None

    @staticmethod
    def _check_ffmpeg() -> None:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ffmpeg is required for simultaneous streaming to both platforms.\n"
                "Install it with:  brew install ffmpeg"
            ) from exc

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]
