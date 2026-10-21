"""GUI 构建与消息泵测试。

注意：需要带 tkinter 的 Python。托管环境若缺少 tkinter，本测试会自动跳过
（GUI 代码本身不受影响，只是无法在这里验证）。

运行: python tests/test_gui.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def pump(app, times: int = 8, delay: float = 0.04) -> None:
    """推动 Tkinter 事件循环，让 after() 回调有机会执行。"""
    for _ in range(times):
        app.update()
        time.sleep(delay)


def main() -> int:
    print("=" * 62)
    print("XJTLU PDF Fetcher · GUI 测试")
    print("=" * 62)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("\n跳过：当前 Python 没有 tkinter。")
        print("（用带 tkinter 的 Python 运行，例如系统 Python 或 conda）")
        return 0

    from pdf_fetcher.detector import Candidate
    from pdf_fetcher.gui import CHECKED, UNCHECKED, App

    # messagebox 是模态对话框，会阻塞在等人点击上。测试里换成记录调用的假实现，
    # 既不弹窗，也能在最后断言「确实弹过完成提示」。
    from pdf_fetcher import gui as gui_mod

    dialogs: list[tuple[str, str]] = []

    def _fake_dialog(kind: str):
        def _fn(title: str = "", message: str = "", **_: object) -> None:
            dialogs.append((kind, f"{title} | {message}"))

        return _fn

    gui_mod.messagebox.showinfo = _fake_dialog("info")
    gui_mod.messagebox.showwarning = _fake_dialog("warning")
    gui_mod.messagebox.showerror = _fake_dialog("error")

    print("\n[1] 窗口构建")
    try:
        app = App()
    except Exception as exc:  # noqa: BLE001 - 无显示环境时会抛 TclError
        print(f"\n跳过：无法创建窗口（{type(exc).__name__}: {exc}）")
        print("（无图形环境，如 CI / SSH。GUI 代码未验证。）")
        return 0

    try:
        app.update()

        for attr in (
            "btn_collect", "btn_download", "btn_cancel",
            "tree", "progress", "log",
            "var_url", "var_out", "var_group", "var_status",
        ):
            check_true(f"控件存在: {attr}", hasattr(app, attr))

        check("初始下载按钮禁用", str(app.btn_download["state"]), "disabled")
        check("初始收集按钮可用", str(app.btn_collect["state"]), "normal")
        check("初始取消按钮禁用", str(app.btn_cancel["state"]), "disabled")

        print("\n[2] 候选注入与勾选")
        c1 = Candidate(url="https://x/browserfile/aaa?sig=1", hint="试卷A.pdf", source="network")
        c2 = Candidate(url="https://x/browserfile/bbb?sig=2", hint="试卷B.pdf", source="dom")

        # 模拟后台线程推送的消息
        app.msg.put(("candidate", c1))
        app.msg.put(("candidate", c2))
        app.msg.put(("collected", [c1, c2]))
        pump(app)

        rows = app.tree.get_children()
        check("列表行数", len(rows), 2)
        check("默认全部勾选", str(app.tree.item(c1.key)["values"][0]), CHECKED)
        check("下载按钮已启用", str(app.btn_download["state"]), "normal")
        check("状态栏显示数量", "2" in app.var_status.get(), True)

        app._toggle(c1.key)
        check("点击后取消勾选", str(app.tree.item(c1.key)["values"][0]), UNCHECKED)
        check("选中数量", len(app._selected()), 1)

        app._set_all(False)
        check("全不选", len(app._selected()), 0)

        app._set_all(True)
        check("全选", len(app._selected()), 2)

        print("\n[3] 收集阶段的按钮状态")
        app._phase = "collect"
        app._set_busy(True, "收集中…")
        check("收集按钮变为「结束收集」", str(app.btn_collect["text"]), "■ 结束收集")
        check("收集中收集按钮仍可点", str(app.btn_collect["state"]), "normal")
        check("收集中下载按钮仍禁用", str(app.btn_download["state"]), "disabled")
        check("收集中取消按钮可用", str(app.btn_cancel["state"]), "normal")

        # 没有后台 collector 时点「结束收集」不能崩
        app._on_collect()
        pump(app, times=2)
        check_true("无 collector 时结束收集不崩溃", True)

        app.msg.put(("collected", [c1, c2]))
        pump(app)
        check("收集完成后按钮回到「开始收集」", str(app.btn_collect["text"]), "① 开始收集")
        check("下载按钮带数量", str(app.btn_download["text"]), "② 下载选中 (2)")
        check("下载按钮已解锁", str(app.btn_download["state"]), "normal")

        app._set_all(False)
        check("全不选后下载按钮置灰", str(app.btn_download["state"]), "disabled")
        app._set_all(True)
        check("重新全选后恢复", str(app.btn_download["state"]), "normal")

        print("\n[4] 进度与日志")
        app.msg.put(("progress", (3, 10, "试卷A.pdf")))
        pump(app, times=5)
        check("进度条当前值", int(app.progress["value"]), 3)
        check("进度条最大值", int(app.progress["maximum"]), 10)

        app.msg.put(("log", "测试日志"))
        pump(app, times=5)
        check_true("日志写入", "测试日志" in app.log.get("1.0", "end"))

        print("\n[5] 完成态")
        app.msg.put(("downloaded", 2))
        pump(app, times=5)
        check("完成后按钮恢复", str(app.btn_collect["state"]), "normal")
        check_true(
            "弹过完成提示",
            any(kind == "info" and "2" in text for kind, text in dialogs),
        )

        print("\n[6] 消息泵容错")
        app.msg.put(("unknown_kind", None))   # 未知消息不应导致崩溃
        pump(app, times=3)
        check_true("未知消息被忽略", True)

    finally:
        app.worker.stop()
        app.destroy()

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
