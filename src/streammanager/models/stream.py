from dataclasses import dataclass, field


@dataclass
class StreamConfig:
    title: str
    description: str
    fb_privacy: str = "EVERYONE"
    tags: list[str] = field(default_factory=list)


@dataclass
class PlatformStatus:
    attempted: bool = False
    live: bool = False
    error: str | None = None
    started_at: str | None = None
    title: str | None = None
    page_name: str | None = None
    url: str | None = None


@dataclass
class StreamStatus:
    youtube: PlatformStatus = field(default_factory=PlatformStatus)
    facebook: PlatformStatus = field(default_factory=PlatformStatus)

    @property
    def any_live(self) -> bool:
        return self.youtube.live or self.facebook.live

    @property
    def summary(self) -> str:
        count = sum([self.youtube.live, self.facebook.live])
        total = sum([self.youtube.attempted, self.facebook.attempted])
        if count == total:
            return f"Live on {count}/{total} platforms"
        if count > 0:
            return f"Partially live — {count}/{total} platforms"
        return "All platforms failed"
