"""配置 —— 所有可调参数集中在这里，改行为不用翻代码。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import default_output_dir, default_profile_dir


@dataclass
class Config:
    # ---- 站点 ----
    start_url: str = "https://etd.xjtlu.edu.cn/"

    # ---- 浏览器 ----
    # 按顺序尝试的浏览器通道。用的是系统浏览器程序（继承企业策略与证书信任），
    # 但跑在独立的 profile 目录里（见 profile_dir），不会和你日常浏览的 profile 冲突。
    # 全部失败则回落到 Playwright 内置 Chromium。
    browser_channels: tuple[str | None, ...] = ("msedge", "chrome", None)

    headless: bool = False
    page_timeout_ms: int = 60_000

    # ---- PDF 识别 ----
    # URL 中出现这些关键字的响应视为候选（ETD 的 PDF 走 browserfile）
    url_keywords: tuple[str, ...] = ("browserfile",)

    # ---- 输出 ----
    # None 表示桌面。所有文件平铺存放（不做子目录分组）
    output_dir: Path | None = None

    # ---- 浏览器 profile ----
    # 存放 ETD 登录态的独立用户数据目录。None 表示用系统默认位置。
    # 第一次登录 ETD 后状态留在这里，之后不用重复登录；
    # 收集阶段与下载阶段也共用它，保证下载时带着同一份 cookie。
    profile_dir: Path | None = None

    # ---- 行为 ----
    # 收集阶段结束后是否自动开始下载
    auto_download: bool = True
    # 是否打印每个被跳过的响应（排查漏判时打开）
    verbose: bool = False

    @property
    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir).expanduser().resolve()
        # 用 Known Folder API 拿真实桌面，避免 OneDrive / 组策略重定向时
        # 下载进用户看不见的影子目录
        return default_output_dir()

    @property
    def resolved_profile_dir(self) -> Path:
        """浏览器 profile 目录（保存 ETD 登录态）。"""
        if self.profile_dir:
            return Path(self.profile_dir).expanduser().resolve()
        return default_profile_dir()


DEFAULT_CONFIG = Config()


def load_config(**overrides) -> Config:
    """从命令行参数构造配置，None 值的项用默认值。"""
    cfg = Config()
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
