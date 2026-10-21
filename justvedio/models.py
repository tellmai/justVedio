from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import math

DEFAULT_URL = "https://ks.cqsdx.cn/exam/"
DEFAULT_VIDEO_URL = "https://www.bilibili.com/video/BV14zJY6WExr/"


@dataclass(frozen=True)
class Candidate:
    row: int
    district: str
    name: str = field(repr=False)
    id_number: str = field(repr=False)

    @property
    def masked_id(self):
        return self.id_number[:3] + "*" * (len(self.id_number) - 7) + self.id_number[-4:] if len(self.id_number) >= 8 else "*" * len(self.id_number)


@dataclass
class IdentityImport:
    candidates: list[Candidate]
    issues: list[str]
    sheet: str
    rejected: list[tuple[Candidate, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SiteConfig:
    url: str = DEFAULT_URL
    chrome_path: str = ""
    timeout_ms: int = 20000
    allow_local_test: bool = False

    def validate(self):
        p = urlparse(self.url)
        if p.username or p.password or p.query or p.fragment:
            raise ValueError("登录入口不能包含账号、查询参数或片段")
        local = self.allow_local_test and p.hostname in {"127.0.0.1", "localhost"}
        if not local and (p.scheme != "https" or p.hostname != "ks.cqsdx.cn" or p.port not in (None, 443)):
            raise ValueError("登录适配仅支持 https://ks.cqsdx.cn 考试系统")
        if local and p.scheme != "http":
            raise ValueError("本地测试地址须使用 HTTP")
        if p.path.rstrip("/") not in {"/exam", "/exam/index"}:
            raise ValueError("请使用区县选择入口 https://ks.cqsdx.cn/exam/")
        if self.chrome_path and not Path(self.chrome_path).is_file():
            raise ValueError("指定的浏览器程序不存在")


@dataclass(frozen=True)
class VideoOptions:
    concurrency: int = 10
    background: bool = True
    mode: str = "site"
    local_file: str = ""
    video_url: str = DEFAULT_VIDEO_URL
    entry_selector: str = ""
    frame_selector: str = ""
    video_selector: str = "video, bwp-video"
    play_selector: str = ""
    complete_selector: str = ""
    next_selector: str = ""
    max_videos: int = 100
    muted: bool = True
    login_timeout_seconds: float = 180
    video_timeout_seconds: float = 7200
    stall_timeout_seconds: float = 120

    def validate_execution(self):
        if isinstance(self.concurrency, bool) or not isinstance(self.concurrency, int) or not 1 <= self.concurrency <= 30:
            raise ValueError("并发数须为 1–30 的整数")
        if not isinstance(self.background, bool):
            raise ValueError('后台执行须为开启或关闭')

    def validate(self, config):
        config.validate()
        self.validate_execution()
        if self.mode not in {"site", "local"}:
            raise ValueError("请选择网站视频或本地视频测试")
        if self.mode == "local" and not Path(self.local_file).is_file():
            raise ValueError("请先选择本地视频文件")
        if not self.video_selector.strip():
            raise ValueError("视频元素选择器不能为空")
        if not 1 <= self.max_videos <= 1000:
            raise ValueError("最多连续观看视频数须为 1–1000")
        for value in (self.login_timeout_seconds, self.video_timeout_seconds, self.stall_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("超时时间必须是正数")
        if self.video_url:
            p = urlparse(self.video_url)
            local = config.allow_local_test and p.hostname in {"127.0.0.1", "localhost"}
            if p.username or p.password or not p.hostname or p.scheme not in ({"http", "https"} if local else {"https"}):
                raise ValueError("视频入口须为 HTTPS 网址，且不能包含账号密码")
