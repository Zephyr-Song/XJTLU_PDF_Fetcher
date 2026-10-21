"""命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .collector import Collector, download_all
from .config import Config
from .detector import Candidate, extract_filename
from .storage import save_bytes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xjtlu-pdf-fetcher",
        description="从 XJTLU ETD 批量下载你有权限访问的试卷 PDF（收集后再批量下载）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 默认：打开浏览器手动浏览 → 收集 → 关闭浏览器后自动批量下载
  python main.py

  # 指定输出目录
  python main.py -o D:/papers

  # 从链接列表直接下载（不打开浏览器，适合已经整理好 URL 的情况）
  python main.py --from-file urls.txt

  # 只收集不下载，把结果写成 urls.txt 供以后使用
  python main.py --collect-only -o urls.txt
""",
    )
    p.add_argument("-o", "--output", type=str, default=None,
                   help="输出目录（默认桌面）")
    p.add_argument("--from-file", type=str, default=None, metavar="URLSFILE",
                   help="从文本文件读取 URL 列表直接下载，每行一个")
    p.add_argument("--collect-only", action="store_true",
                   help="只收集不下载；配合 -o 把 URL 列表写入文件")
    p.add_argument("--no-auto-download", action="store_true",
                   help="收集后不自动下载")
    p.add_argument("--channel", type=str, default=None,
                   choices=["msedge", "chrome", "chromium"],
                   help="指定浏览器通道（默认自动尝试 Edge → Chrome → 内置）")
    p.add_argument("--profile-dir", type=str, default=None, metavar="DIR",
                   help="浏览器 profile 目录（存放 ETD 登录态，默认在用户配置目录下）")
    p.add_argument("--headless", action="store_true",
                   help="无头模式（注意：需要登录时无法手动输入账号密码）")
    p.add_argument("--url", type=str, default=None,
                   help="起始页面（默认 ETD 首页）")
    p.add_argument("-v", "--verbose", action="store_true", help="打印跳过的响应")
    p.add_argument("--gui", action="store_true", help="打开图形界面（点按钮操作）")
    return p


def config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config()
    if args.output and not args.collect_only:
        cfg.output_dir = Path(args.output)
    if args.no_auto_download:
        cfg.auto_download = False
    if args.headless:
        cfg.headless = True
    if args.url:
        cfg.start_url = args.url
    if args.verbose:
        cfg.verbose = True
    if args.channel:
        cfg.browser_channels = (
            (None,) if args.channel == "chromium" else (args.channel, None)
        )
    if args.profile_dir:
        cfg.profile_dir = Path(args.profile_dir)
    return cfg


def read_urls_from_file(path: Path) -> list[Candidate]:
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {path}")
    out: list[Candidate] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(Candidate(url=line, hint=extract_filename(line), source="file"))
    return out


def write_urls_to_file(items: list[Candidate], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 由 XJTLU PDF Fetcher 生成",
        "# 注意：ETD 的 PDF 链接带签名，可能一段时间后失效，需要重新收集",
        "",
        *(c.url for c in items),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已将 {len(items)} 个 URL 写入 {path}")


async def run_async(args: argparse.Namespace) -> int:
    cfg = config_from_args(args)

    # 模式 A：从文件直接下载
    if args.from_file:
        candidates = read_urls_from_file(Path(args.from_file))
        print(f"从文件读取到 {len(candidates)} 个 URL")
        await download_all(candidates, cfg)
        return 0

    # 模式 B：浏览器收集
    candidates = await Collector(cfg).run()

    if not candidates:
        print("\n没有收集到 PDF。可能原因：")
        print("  · 没有真正打开过试卷页面（只是浏览了列表）")
        print("  · 试卷是 canvas 渲染或分片加载，不走 PDF 响应")
        print("  · 需要先用 -v 查看被跳过的响应，确认识别规则")
        return 1

    # 只收集：把 URL 写文件
    if args.collect_only:
        target = Path(args.output) if args.output else Path("urls.txt")
        write_urls_to_file(candidates, target)
        return 0

    if not cfg.auto_download:
        print("\n已跳过下载（--no-auto-download）。URL 列表：")
        for c in candidates:
            print(f"  {c.url}")
        return 0

    await download_all(candidates, cfg)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import main as gui_main

        return gui_main()

    try:
        return asyncio.run(run_async(args))
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n错误: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
