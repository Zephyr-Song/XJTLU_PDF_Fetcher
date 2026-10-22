"""自检 —— 不开窗口，把关键路径跑一遍，用退出码表达成败。

为什么需要它：
  exe 是以 windowed 模式（console=False）打包的，没有 stdout，
  而且「模块没被打进包」这类问题单元测试根本发现不了
  （表现是运行时才炸：Could not load PyInstaller's embedded PKG archive）。

  所以：
    · CI 用 `dist\\XJTLU_PDF_Fetcher.exe --selftest --selftest-out r.txt`
      对**真正的打包产物**做冒烟测试
    · 用户想确认自己这台机器环境行不行，也可以直接跑这个命令

用法：
  python launch_gui.py --selftest --selftest-out result.txt
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

MODULES = (
    "pdf_fetcher.config",
    "pdf_fetcher.detector",
    "pdf_fetcher.storage",
    "pdf_fetcher.paths",
    "pdf_fetcher.guard",
    "pdf_fetcher.collector",
    "pdf_fetcher.cli",
    "pdf_fetcher.gui",
    "pdf_fetcher.selftest",
)

# Windows 上常见的浏览器可执行文件位置
_BROWSER_CANDIDATES = {
    "msedge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ),
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ),
}


def _check_modules() -> str:
    for name in MODULES:
        importlib.import_module(name)
    return f"{len(MODULES)} 个模块全部可导入"


def _check_desktop() -> str:
    from .paths import desktop_dir

    desk = desktop_dir()
    if not desk.exists():
        raise RuntimeError(f"桌面目录不存在：{desk}")
    return str(desk)


def _check_profile() -> str:
    from .config import Config

    profile = Config().resolved_profile_dir
    profile.mkdir(parents=True, exist_ok=True)
    probe = profile / ".selftest-write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return str(profile)


def _check_browsers() -> str:
    found: list[str] = []
    for name, paths in _BROWSER_CANDIDATES.items():
        if any(Path(p).exists() for p in paths):
            found.append(name)
    if not found:
        raise RuntimeError("既没找到 Edge 也没找到 Chrome")
    return "可用浏览器：" + "、".join(found)


def _check_profile_free() -> str:
    from .guard import profile_in_use

    if profile_in_use():
        raise RuntimeError(
            "profile 正被占用（可能上一次打开的浏览器窗口还没关）"
        )
    return "profile 未被占用"


def _check_playwright() -> str:
    import playwright.sync_api as sync_api

    driver = Path(sync_api.__file__).resolve().parent.parent / "driver"
    if not driver.exists():
        raise RuntimeError(f"找不到 playwright driver 目录：{driver}")
    return str(driver)


CHECKS = (
    ("模块导入", _check_modules),
    ("真实桌面目录", _check_desktop),
    ("profile 目录可写", _check_profile),
    ("浏览器可执行文件", _check_browsers),
    ("playwright driver", _check_playwright),
    ("profile 未被占用", _check_profile_free),
)


def run_checks() -> tuple[bool, list[str]]:
    """跑一遍自检，返回 (是否全部通过, 逐行结果)。"""
    lines: list[str] = []
    all_ok = True
    for name, fn in CHECKS:
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - 自检要把失败原因报出来
            all_ok = False
            lines.append(f"FAIL  {name} — {type(exc).__name__}: {exc}")
        else:
            lines.append(f"OK    {name} — {detail}")
    return all_ok, lines


def main(argv: list[str] | None = None) -> int:
    """命令行入口。返回 0 = 全部通过，1 = 有失败。"""
    args = list(sys.argv[1:] if argv is None else argv)

    out_path: Path | None = None
    if "--selftest-out" in args:
        index = args.index("--selftest-out")
        if index + 1 < len(args):
            out_path = Path(args[index + 1])

    ok, lines = run_checks()

    text = "\n".join(lines)

    def _safe_print(value: str) -> None:
        # windowed 模式下 sys.stdout 是 None，直接 print 会抛异常
        try:
            if sys.stdout is not None:
                print(value)
        except Exception:  # noqa: BLE001
            pass

    _safe_print(text)
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                ("SELFTEST OK\n" if ok else "SELFTEST FAILED\n") + text + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"（写结果文件失败：{exc}）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
