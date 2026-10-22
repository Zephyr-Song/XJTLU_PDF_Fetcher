"""核心逻辑单元测试 —— 不依赖浏览器，纯函数验证。

运行: python tests/test_core.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf_fetcher.config import Config  # noqa: E402
from pdf_fetcher.detector import (  # noqa: E402
    Candidate,
    extract_filename,
    is_real_pdf,
    is_static_asset,
    looks_like_pdf_response,
    sanitize_filename,
)
from pdf_fetcher.paths import desktop_dir  # noqa: E402
from pdf_fetcher.storage import human_size, resolve_save_path, save_bytes  # noqa: E402

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


# ---------------------------------------------------------------- PDF 识别

def test_detection() -> None:
    print("\n[1] PDF 识别（收集阶段的廉价判定）")

    # 正例
    check_true(
        "application/pdf 类型命中",
        looks_like_pdf_response("https://x/a", "application/pdf"),
    )
    check_true(
        "URL 以 .pdf 结尾命中",
        looks_like_pdf_response("https://x/download/paper.pdf"),
    )
    check_true(
        "带 query 的 .pdf 命中",
        looks_like_pdf_response("https://x/get?file=paper.pdf&sig=abc"),
    )
    check_true(
        "browserfile 关键字命中",
        looks_like_pdf_response("https://etd.xjtlu.edu.cn/browserfile/some/id"),
    )
    check_true(
        "octet-stream 收进来交给下载阶段校验",
        looks_like_pdf_response("https://x/file/123", "application/octet-stream"),
    )

    # 负例
    check_true("JS 文件跳过", not looks_like_pdf_response("https://x/app.js", "text/javascript"))
    check_true("CSS 跳过", not looks_like_pdf_response("https://x/a.css", "text/css"))
    check_true("PNG 跳过", not looks_like_pdf_response("https://x/a.png", "image/png"))
    check_true("JSON 跳过", not looks_like_pdf_response("https://x/data.json", "application/json"))
    check_true(
        "viewer.html 死排除（它是查看器页面不是 PDF）",
        not looks_like_pdf_response(
            "https://etd.xjtlu.edu.cn/viewer.html?id=1", "text/html"
        ),
    )
    check_true("普通 HTML 页面不命中", not looks_like_pdf_response("https://x/index.html", "text/html"))

    # 静态资源判定
    check_true("is_static_asset 识别 .woff2", is_static_asset("https://x/f.woff2"))
    check_true("is_static_asset 不误判 .pdf", not is_static_asset("https://x/a.pdf"))

    # magic bytes
    check_true("真实 PDF 文件头通过", is_real_pdf(b"%PDF-1.7\n..."))
    check_true("前导空白也能识别", is_real_pdf(b"  \n%PDF-1.4"))
    check_true("HTML 伪装成 PDF 被拒", not is_real_pdf(b"<!DOCTYPE html><html>"))
    check_true("空 body 被拒", not is_real_pdf(b""))
    check_true("ZIP 文件被拒", not is_real_pdf(b"PK\x03\x04"))


# ---------------------------------------------------------------- 去重键

def test_candidate_key() -> None:
    print("\n[2] 去重键（关键：同一文件不同签名不应重复下载）")

    a = Candidate(url="https://etd.xjtlu.edu.cn/browserfile/abc123?timestamp=111&signature=AAA")
    b = Candidate(url="https://etd.xjtlu.edu.cn/browserfile/abc123?timestamp=999&signature=ZZZ")
    c = Candidate(url="https://etd.xjtlu.edu.cn/browserfile/other456?timestamp=111")

    check_true("同 path 不同 query → 视为同一文件", a.key == b.key)
    check_true("不同 path → 视为不同文件", a.key != c.key)

    # 大小写与尾部斜杠
    d = Candidate(url="https://x/BrowserFile/ABC123/")
    e = Candidate(url="https://x/browserfile/abc123")
    check_true("大小写/尾斜杠归一化", d.key == e.key)


# ---------------------------------------------------------------- 文件名

def test_filename() -> None:
    print("\n[3] 文件名提取与清理")

    check(
        "从 Content-Disposition (filename=) 提取",
        extract_filename("https://x/a", 'attachment; filename="CAN201 2023.pdf"'),
        "CAN201 2023.pdf",
    )
    check(
        "从 RFC5987 filename* 提取并解码",
        extract_filename(
            "https://x/a",
            "attachment; filename*=UTF-8''%E8%AF%95%E5%8D%B7.pdf",
        ),
        "试卷.pdf",
    )
    check(
        "Content-Disposition 无 filename 时回落 URL path",
        extract_filename("https://x/dir/paper.pdf", "attachment"),
        "paper.pdf",
    )
    check(
        "URL path 提取",
        extract_filename("https://x/dir/CPT203_Final.pdf"),
        "CPT203_Final.pdf",
    )
    check(
        "URL 无扩展名时回落 fallback",
        extract_filename("https://x/browserfile/abc", "", fallback="paper"),
        "paper.pdf",
    )

    # 清理
    check(
        "非法字符替换为下划线",
        sanitize_filename('a/b\\c:d*e?f"g<h>i|j.pdf'),
        "a_b_c_d_e_f_g_h_i_j.pdf",
    )
    check("自动补 .pdf", sanitize_filename("final"), "final.pdf")
    check("路径穿越被处理", sanitize_filename("../../etc/passwd.pdf"), "_.._etc_passwd.pdf")
    check("空名兜底", sanitize_filename("   "), "paper.pdf")
    check("Windows 保留名加前缀", sanitize_filename("CON.pdf"), "_CON.pdf")
    check("超长名被截断", len(sanitize_filename("x" * 300 + ".pdf")) <= 180, True)
    check_true(
        "超长名仍保留 .pdf 后缀",
        sanitize_filename("x" * 300 + ".pdf").endswith(".pdf"),
    )


# ---------------------------------------------------------------- 落盘

def test_storage() -> None:
    print("\n[4] 落盘与重名处理")

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        p1 = save_bytes(d, "paper.pdf", b"%PDF-1.7 first")
        check("首次保存用原名", p1.name, "paper.pdf")

        p2 = save_bytes(d, "paper.pdf", b"%PDF-1.7 second")
        check("重名追加 (1)", p2.name, "paper(1).pdf")

        p3 = save_bytes(d, "paper.pdf", b"%PDF-1.7 third")
        check("再次重名追加 (2)", p3.name, "paper(2).pdf")

        check("内容未被覆盖", p1.read_bytes(), b"%PDF-1.7 first")
        check("三个文件都存在", len(list(d.glob("paper*.pdf"))), 3)

        # 子目录自动创建
        nested = d / "a" / "b"
        p4 = save_bytes(nested, "x.pdf", b"%PDF-1.4")
        check_true("多级目录自动创建", p4.exists())

    # resolve_save_path 不创建文件
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        path = resolve_save_path(d, "notexist.pdf")
        check("resolve_save_path 不写文件", path.exists(), False)

    # 人类可读大小
    check("512B", human_size(512), "512 B")
    check("1KB", human_size(1024), "1.0 KB")
    check("1.5MB", human_size(1024 * 1024 * 3 // 2), "1.5 MB")


# ---------------------------------------------------------------- 路径解析

def test_paths() -> None:
    print("\n[5] 路径解析（真实桌面 / 默认输出目录）")

    desk = desktop_dir()
    check_true("desktop_dir 返回 Path", isinstance(desk, Path))
    check_true("desktop_dir 是绝对路径", desk.is_absolute())
    check_true("desktop_dir 名为 Desktop", desk.name.lower() == "desktop")
    check_true("desktop_dir 存在", desk.exists())

    # 默认输出目录必须等于真实桌面
    check("默认输出目录 = 桌面", Config().resolved_output_dir, desk)

    # 显式指定时以指定为准
    tmp = Path(tempfile.gettempdir())
    check("显式输出目录优先", Config(output_dir=tmp).resolved_output_dir, tmp.resolve())

    # profile 目录：默认落在用户配置目录下，且收集/下载共用同一个
    prof = Config().resolved_profile_dir
    check_true("profile 目录是绝对路径", prof.is_absolute())
    check_true("profile 目录名为 browser-profile", prof.name == "browser-profile")
    check("profile 目录稳定（两次解析一致）", Config().resolved_profile_dir, prof)
    custom = tmp / "my-profile"
    check("可自定义 profile 目录", Config(profile_dir=custom).resolved_profile_dir, custom.resolve())


# ---------------------------------------------------------------- 占用检测

def _hold_exclusive(path: Path):
    """以「独占共享模式」打开文件，模拟 Chromium 锁住 lockfile 的行为。

    Windows 上 Chromium 用 FILE_SHARE_NONE 打开 lockfile，其他进程连 open
    都会失败（PermissionError）。普通 msvcrt.locking 模拟不出这个效果，
    因为它们只锁字节区间、仍允许打开。
    """
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            str(path), 0x80000000 | 0x40000000, 0, None, 4, 0, None
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError("模拟占用失败")
        return handle
    raise RuntimeError("仅 Windows 需要模拟")


def _release(handle) -> None:
    import ctypes

    ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))


def test_guard() -> None:
    print("\n[6] profile 占用检测 / 单实例锁")

    from pdf_fetcher.guard import SingleInstance, profile_in_use

    tmp = Path(tempfile.mkdtemp()) / "profile"
    tmp.mkdir(parents=True)

    check("空目录不算占用", profile_in_use(tmp), False)

    lockfile = tmp / "lockfile"
    lockfile.write_bytes(b"")
    check("残留的未加锁 lockfile 不算占用", profile_in_use(tmp), False)

    if sys.platform == "win32":
        handle = _hold_exclusive(lockfile)
        try:
            check("被浏览器独占锁住 = 占用中", profile_in_use(tmp), True)
        finally:
            _release(handle)
        check("浏览器退出后恢复可用", profile_in_use(tmp), False)
    else:
        print("  SKIP 独占共享模式模拟（仅 Windows）")

    # 单实例锁：同名锁文件只能被拿一次
    lock_path = tmp.parent / "app.lock"
    first = SingleInstance(lock_path)
    check("第一个实例拿到锁", first.acquire(), True)
    second = SingleInstance(lock_path)
    check("第二个实例拿不到锁", second.acquire(), False)
    first.release()
    check("释放后第二个实例可以拿到", second.acquire(), True)
    second.release()
    check("锁文件保留但可再次获取", SingleInstance(lock_path).acquire(), True)


def main() -> int:
    print("=" * 62)
    print("XJTLU PDF Fetcher · 核心逻辑测试")
    print("=" * 62)

    test_detection()
    test_candidate_key()
    test_filename()
    test_storage()
    test_paths()
    test_guard()

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败列表:")
        for name in FAILED:
            print(f"  · {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
