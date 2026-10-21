"""端到端集成测试：本地起 HTTP 服务，验证真实下载链路。

验证点：
  · 真实 HTTP 请求能拿到 body
  · %PDF magic bytes 校验能拦住伪装文件
  · Content-Disposition 里的中文文件名正确解码
  · 重名自动加序号、不覆盖
  · 一律平铺存放，不建子目录

运行: python tests/test_integration.py
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf_fetcher.collector import download_all  # noqa: E402
from pdf_fetcher.config import Config  # noqa: E402
from pdf_fetcher.detector import Candidate  # noqa: E402

# 一个最小但合法的 PDF（文件头 + 最小结构）
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

FAKE_PDF = b"<!DOCTYPE html><html><body>Not a PDF</body></html>"


class Handler(http.server.BaseHTTPRequestHandler):
    """提供几种不同的响应形态，覆盖真实场景。"""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定
        path = self.path

        if path.startswith("/browserfile/"):
            # 模拟 ETD：签名 URL，返回 PDF，带 RFC5987 中文文件名
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''%E8%AF%95%E5%8D%B7.pdf",
            )
            self.send_header("Content-Length", str(len(MINIMAL_PDF)))
            self.end_headers()
            self.wfile.write(MINIMAL_PDF)
            return

        if path.startswith("/named/"):
            # 带 ASCII 文件名的 PDF
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="CAN201_2023.pdf"')
            self.send_header("Content-Length", str(len(MINIMAL_PDF)))
            self.end_headers()
            self.wfile.write(MINIMAL_PDF)
            return

        if path.startswith("/fake/"):
            # 伪装成 PDF 的 HTML —— 应被 magic bytes 校验拦住
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(FAKE_PDF)))
            self.end_headers()
            self.wfile.write(FAKE_PDF)
            return

        if path.startswith("/404/"):
            self.send_error(404)
            return

        self.send_error(404)

    def log_message(self, *args) -> None:
        """静音访问日志。"""
        return


class Server:
    def __init__(self) -> None:
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "Server":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"


PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, actual, expected) -> None:
    if actual == expected:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}\n        期望: {expected!r}\n        实际: {actual!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


async def run_tests(server: Server) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "downloads"

        candidates = [
            # 两个 browserfile → 中文名，应都成为 试卷.pdf / 试卷(1).pdf
            Candidate(url=f"{server.base}/browserfile/aaa?signature=1"),
            Candidate(url=f"{server.base}/browserfile/bbb?signature=2"),
            # 带 ASCII 文件名
            Candidate(url=f"{server.base}/named/x"),
            # 伪装 PDF → 应被跳过
            Candidate(url=f"{server.base}/fake/y"),
            # 404 → 应被跳过
            Candidate(url=f"{server.base}/404/z"),
        ]

        cfg = Config(output_dir=out, headless=True)
        ok = await download_all(candidates, cfg)

        print("\n[验证结果]")
        check("成功下载数（5 个候选中 3 个有效）", ok, 3)

        files = sorted(p.name for p in out.glob("*.pdf"))
        print(f"  （实际文件: {files}）")

        check("文件总数", len(files), 3)
        check_true("中文名首份存在", "试卷.pdf" in files)
        check_true("中文名重名自动序号", "试卷(1).pdf" in files)
        check_true("ASCII 文件名正确", "CAN201_2023.pdf" in files)
        check_true("伪装 PDF 未被保存", not any("y" == p.stem for p in out.glob("*.pdf")))
        check_true(
            "所有落盘文件确为真 PDF",
            all(p.read_bytes()[:4] == b"%PDF" for p in out.glob("*.pdf")),
        )

    # 一律平铺存放：文件名里带课程代码也不能建子目录
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "flat"
        candidates = [
            Candidate(url=f"{server.base}/named/CAN201_paper"),
        ]
        cfg = Config(output_dir=out, headless=True)
        await download_all(candidates, cfg)
        subdirs = [p.name for p in out.iterdir() if p.is_dir()]
        files = [p.name for p in out.iterdir() if p.is_file()]
        print("\n[平铺存放]")
        check("不生成子目录", subdirs, [])
        check_true("文件直接落在输出目录", any("CAN201" in f for f in files))

    # 从文件读取的流程（urls.txt 为空时不应崩）
    print("\n[边界情况]")
    from pdf_fetcher.cli import read_urls_from_file

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "urls.txt"
        f.write_text("# 注释行\n\n\n", encoding="utf-8")
        check("空列表（仅注释）返回空", read_urls_from_file(f), [])

        f2 = Path(tmp) / "u2.txt"
        f2.write_text("# c\nhttp://a/1.pdf\n\nhttp://b/2.pdf\n", encoding="utf-8")
        items = read_urls_from_file(f2)
        check("跳过注释与空行", len(items), 2)
        check("URL 正确", items[0].url, "http://a/1.pdf")

        try:
            read_urls_from_file(Path(tmp) / "notexist.txt")
            check_true("不存在的文件应抛异常", False)
        except FileNotFoundError:
            check_true("不存在的文件应抛异常", True)


def main() -> int:
    print("=" * 62)
    print("XJTLU PDF Fetcher · 端到端集成测试（本地 HTTP 服务）")
    print("=" * 62)

    with Server() as server:
        print(f"\n测试服务器: {server.base}")
        asyncio.run(run_tests(server))

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print(f"  · {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
