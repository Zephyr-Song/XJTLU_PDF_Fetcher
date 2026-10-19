"""配置 —— 所有可调参数集中在这里，改行为不用翻代码。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # ---- 站点 ----
    start_url: str = "https://etd.xjtlu.edu.cn/"

    # ---- 浏览器 ----
    # 按顺序尝试的浏览器通道。用系统浏览器可以复用你已登录的 profile，
    # 避免每次重新登录。全部失败则回落到 Playwright 内置 Chromium。
    browser_channels: tuple[str | None, ...] = ("msedge", "chrome", None)

    headless: bool = False
    page_timeout_ms: int = 60_000

    # ---- PDF 识别 ----
    # URL 中出现这些关键字的响应视为候选（ETD 的 PDF 走 browserfile）
    url_keywords: tuple[str, ...] = ("browserfile",)

    # ---- 输出 ----
    # None 表示桌面
    output_dir: Path | None = None
    # True 时按课程代码分子目录（从 URL 里猜出 CAN201 这类代码）
    group_by_course: bool = False

    # ---- 行为 ----
    # 收集阶段结束后是否自动开始下载
    auto_download: bool = True
    # 是否打印每个被跳过的响应（排查漏判时打开）
    verbose: bool = False

    @property
    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir).expanduser().resolve()
        return (Path.home() / "Desktop").resolve()


DEFAULT_CONFIG = Config()


def load_config(**overrides) -> Config:
    """从命令行参数构造配置，None 值的项用默认值。"""
    cfg = Config()
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
