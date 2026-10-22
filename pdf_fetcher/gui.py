"""图形界面 —— 点按钮就能用，不需要记命令行参数。

设计要点：
  · Tkinter 自带，不引入任何额外依赖
  · asyncio 跑在后台线程，GUI 主线程通过队列取消息（Tkinter 不是线程安全的）
  · 收集和下载分离：先"开始收集"，看列表勾选，再"下载选中"

运行: python main.py --gui    或    python run_gui.bat
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .collector import Collector, download_all  # noqa: F401
from .config import Config
from .detector import Candidate
from .guard import ProfileBusyError, SingleInstance, single_instance_path
from .paths import desktop_dir

CHECKED = "☑"
UNCHECKED = "☐"


class AsyncWorker:
    """在后台线程里跑一个 asyncio 事件循环，供 GUI 提交协程。"""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()

        def _run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._ready.set()
            self.loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def submit(self, coro) -> None:
        if self.loop is None:
            raise RuntimeError("事件循环未启动")
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("XJTLU 试卷下载器")
        self.geometry("880x640")
        self.minsize(720, 520)

        self.worker = AsyncWorker()
        self.worker.start()

        # GUI 线程与工作线程之间的消息通道
        self.msg: queue.Queue[tuple[str, object]] = queue.Queue()

        # 状态
        self.candidates: list[Candidate] = []
        self.checked: dict[str, bool] = {}     # key -> 是否勾选
        self.busy = False
        self._cancel = False
        self._phase: str | None = None         # "collect" / "download" / None
        self._collector: Collector | None = None

        self._build_ui()
        self._poll()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ 界面

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # ---------- 顶部：参数 ----------
        top = ttk.LabelFrame(self, text="设置")
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(top, text="起始网址").grid(row=0, column=0, sticky="w", **pad)
        self.var_url = tk.StringVar(value=Config().start_url)
        ttk.Entry(top, textvariable=self.var_url).grid(
            row=0, column=1, columnspan=3, sticky="ew", **pad
        )

        ttk.Label(top, text="保存到").grid(row=1, column=0, sticky="w", **pad)
        self.var_out = tk.StringVar(value=str(desktop_dir()))
        ttk.Entry(top, textvariable=self.var_out).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(top, text="浏览…", width=8, command=self._choose_dir).grid(
            row=1, column=2, **pad
        )
        ttk.Button(top, text="打开", width=6, command=self._open_dir).grid(
            row=1, column=3, **pad
        )

        top.columnconfigure(1, weight=1)

        # ---------- 操作按钮 ----------
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=2)

        self.btn_collect = ttk.Button(
            bar, text="① 开始收集", width=14, command=self._on_collect
        )
        self.btn_collect.pack(side="left", padx=(0, 6))

        self.btn_download = ttk.Button(
            bar, text="② 下载选中", width=14, command=self._on_download, state="disabled"
        )
        self.btn_download.pack(side="left", padx=6)

        self.btn_cancel = ttk.Button(
            bar, text="取消", width=8, command=self._on_cancel, state="disabled"
        )
        self.btn_cancel.pack(side="left", padx=6)

        # side="right" 是「先 pack 的靠最右」，所以先放全不选、再放全选
        ttk.Button(bar, text="全不选", width=8, command=lambda: self._set_all(False)).pack(
            side="right", padx=(2, 0)
        )
        ttk.Button(bar, text="全选", width=6, command=lambda: self._set_all(True)).pack(
            side="right", padx=2
        )

        # ---------- 中部：候选列表 ----------
        mid = ttk.LabelFrame(self, text="收集到的试卷（点击行可切换勾选）")
        mid.pack(fill="both", expand=True, padx=10, pady=6)

        columns = ("check", "name", "source")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", height=10)
        self.tree.heading("check", text="选")
        self.tree.heading("name", text="文件名")
        self.tree.heading("source", text="来源")
        self.tree.column("check", width=40, anchor="center", stretch=False)
        self.tree.column("name", width=560, anchor="w")
        self.tree.column("source", width=90, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb.pack(side="right", fill="y", padx=(0, 6), pady=6)

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        # ---------- 进度 ----------
        prog = ttk.Frame(self)
        prog.pack(fill="x", padx=10, pady=(0, 4))

        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)

        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(prog, textvariable=self.var_status, width=24, anchor="e").pack(
            side="right", padx=(8, 0)
        )

        # ---------- 底部：日志 ----------
        logf = ttk.LabelFrame(self, text="日志")
        logf.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.log = tk.Text(logf, height=8, wrap="word", state="disabled")
        lvsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lvsb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lvsb.pack(side="right", fill="y", padx=(0, 6), pady=6)

    # ------------------------------------------------------------ 小工具

    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_out.get() or ".")
        if chosen:
            self.var_out.set(chosen)

    def _open_dir(self) -> None:
        path = Path(self.var_out.get())
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import os

                os.startfile(str(path))  # noqa: S606 - 用户主动点击的本地目录
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("打不开", f"无法打开目录：{exc}")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _collect_btn_text(self) -> str:
        """收集进行中时，这个按钮的作用是「结束收集」而不是「开始收集」。"""
        if self.busy and self._phase == "collect":
            return "■ 结束收集"
        return "① 开始收集"

    def _update_download_btn(self) -> None:
        """按钮上直接带数量，让「收集中」也能看到进度在涨。

        解锁条件：不在忙 + 至少勾了一个。全不选时置灰（点下去会白跑一次）。
        """
        picked = len(self._selected())
        self.btn_download.configure(
            text=(f"② 下载选中 ({picked})" if self.candidates else "② 下载选中"),
            state="disabled" if (self.busy or picked == 0) else "normal",
        )

    def _set_busy(self, busy: bool, phase: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        # 收集阶段这个按钮要保持可点（它就是「结束收集」）
        self.btn_collect.configure(
            state=("normal" if (busy and self._phase == "collect") else state),
            text=self._collect_btn_text(),
        )
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        self._update_download_btn()
        if phase:
            self.var_status.set(phase)

    # ------------------------------------------------------------ 列表勾选

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for cand in self.candidates:
            mark = CHECKED if self.checked.get(cand.key) else UNCHECKED
            self.tree.insert(
                "", "end", iid=cand.key, values=(mark, cand.hint, cand.source)
            )
        self._update_download_btn()

    def _toggle(self, key: str) -> None:
        self.checked[key] = not self.checked.get(key, True)
        mark = CHECKED if self.checked[key] else UNCHECKED
        self.tree.set(key, "check", mark)
        self._update_download_btn()

    def _on_tree_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        # 只有点在「选」列（#1）或行本身时才切换
        if row and col in ("#1", "#2"):
            self._toggle(row)

    def _on_tree_space(self, _event: tk.Event) -> None:
        for row in self.tree.selection():
            self._toggle(row)

    def _set_all(self, value: bool) -> None:
        for cand in self.candidates:
            self.checked[cand.key] = value
        self._refresh_tree()

    def _selected(self) -> list[Candidate]:
        return [c for c in self.candidates if self.checked.get(c.key)]

    # ------------------------------------------------------------ 配置

    def _make_config(self) -> Config:
        cfg = Config()
        cfg.start_url = self.var_url.get().strip() or cfg.start_url
        out = self.var_out.get().strip()
        cfg.output_dir = Path(out) if out else None
        return cfg

    # ------------------------------------------------------------ 收集

    def _on_collect(self) -> None:
        if self.busy:
            # 收集进行中再点一次 = 结束收集（不用去关浏览器窗口）
            self._finish_collect()
            return

        self.candidates = []
        self.checked = {}
        self._refresh_tree()
        self.progress["value"] = 0
        self._phase = "collect"
        self._set_busy(True, "收集中…")
        self._append_log("—— 开始收集 ——")
        self._append_log("① 在弹出的浏览器窗口里登录 ETD（首次需登录，之后自动复用）")
        self._append_log("② 逐个点开要看的试卷（按钮上的数字会实时增加）")
        self._append_log("③ 点完点上面的「■ 结束收集」，或直接关掉浏览器窗口")
        self._append_log("④ 然后「② 下载选中」解锁，勾选后开始批量下载")

        self.worker.submit(self._collect_task(self._make_config()))

    def _finish_collect(self) -> None:
        """结束收集：关掉后台浏览器，让协程正常收尾并吐出候选列表。"""
        collector = self._collector
        loop = self.worker.loop
        if collector is None or loop is None:
            return
        self._append_log("正在结束收集…")
        self.var_status.set("正在结束…")
        self.btn_collect.configure(state="disabled")

        def _schedule() -> None:
            asyncio.ensure_future(collector.aclose())

        try:
            loop.call_soon_threadsafe(_schedule)
        except RuntimeError:  # noqa: BLE001 - 事件循环已停
            pass

    async def _collect_task(self, cfg: Config) -> None:
        try:
            collector = Collector(
                cfg,
                on_log=lambda m: self.msg.put(("log", m)),
                on_candidate=lambda c: self.msg.put(("candidate", c)),
            )
            self._collector = collector
            result = await collector.run()
            self.msg.put(("collected", result))
        except ProfileBusyError as exc:
            self.msg.put(("profile_busy", str(exc)))
        except Exception as exc:  # noqa: BLE001 - 错误要回显到界面
            self.msg.put(("error", f"收集失败：{type(exc).__name__}: {exc}"))

    # ------------------------------------------------------------ 下载

    def _on_download(self) -> None:
        if self.busy:
            return
        picked = self._selected()
        if not picked:
            messagebox.showinfo("没有选中", "请先勾选要下载的试卷。")
            return

        self._cancel = False
        self.progress["value"] = 0
        self._phase = "download"
        self._set_busy(True, "下载中…")
        self._append_log(f"—— 开始下载 {len(picked)} 个文件 ——")

        self.worker.submit(self._download_task(picked, self._make_config()))

    async def _download_task(self, picked: list[Candidate], cfg: Config) -> None:
        try:
            ok = await download_all(
                picked,
                cfg,
                on_log=lambda m: self.msg.put(("log", m)),
                on_progress=lambda d, t, hint: self.msg.put(("progress", (d, t, hint))),
                should_stop=lambda: self._cancel,
            )
            self.msg.put(("downloaded", ok))
        except ProfileBusyError as exc:
            self.msg.put(("profile_busy", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self.msg.put(("error", f"下载失败：{type(exc).__name__}: {exc}"))

    def _on_cancel(self) -> None:
        if self._phase == "collect":
            # 收集阶段没有「下一个文件」这个概念，取消 = 结束收集
            self._finish_collect()
            return
        self._cancel = True
        self.var_status.set("正在取消…")
        self._append_log("已请求取消，当前文件下载完后停止。")

    # ------------------------------------------------------------ 消息泵

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.msg.get_nowait()

                if kind == "log":
                    self._append_log(str(payload))

                elif kind == "candidate":
                    cand = payload
                    assert isinstance(cand, Candidate)
                    self.candidates.append(cand)
                    self.checked[cand.key] = True
                    self.tree.insert(
                        "", "end", iid=cand.key,
                        values=(CHECKED, cand.hint, cand.source),
                    )
                    self._update_download_btn()
                    self.var_status.set(f"收集中 · 已收集 {len(self.candidates)} 个")

                elif kind == "collected":
                    items = payload
                    assert isinstance(items, list)
                    self._phase = None
                    self._collector = None
                    self.candidates = items
                    for c in items:
                        self.checked.setdefault(c.key, True)
                    self._refresh_tree()
                    self._set_busy(False, f"收集完成：{len(items)} 个")
                    self._append_log(f"—— 收集完成，共 {len(items)} 个 ——")
                    if items:
                        self._append_log("已解锁：勾选后点「② 下载选中」开始批量下载。")
                    if not items:
                        messagebox.showwarning(
                            "没有收集到",
                            "没有捕获到 PDF。\n\n"
                            "常见原因：\n"
                            "· 只浏览了列表页，没有真正点开试卷\n"
                            "· 试卷是 canvas 渲染或分片加载\n"
                            "· 识别规则不匹配（可先用命令行 -v 排查）",
                        )

                elif kind == "progress":
                    done, total, hint = payload
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                    if hint:
                        self.var_status.set(f"{done}/{total} {str(hint)[:16]}")

                elif kind == "downloaded":
                    ok = payload
                    self._phase = None
                    self._set_busy(False, "完成")
                    self._append_log(f"—— 下载完成：成功 {ok} 个 ——")
                    messagebox.showinfo("完成", f"成功下载 {ok} 个文件。")

                elif kind == "profile_busy":
                    self._phase = None
                    self._collector = None
                    self._set_busy(False, "浏览器被占用")
                    self._append_log(str(payload))
                    messagebox.showwarning("浏览器窗口还开着", str(payload))

                elif kind == "error":
                    self._phase = None
                    self._collector = None
                    self._set_busy(False, "出错")
                    self._append_log(str(payload))
                    messagebox.showerror("出错", str(payload))

        except queue.Empty:
            pass

        self.after(100, self._poll)

    # ------------------------------------------------------------ 关闭

    def _shutdown_browser(self) -> None:
        """退出前把后台浏览器关掉。

        不关的话 profile 会一直被那个浏览器进程占着，
        下次启动必然报 TargetClosedError —— 这也是「打不开网页」的根因之一。
        """
        collector = self._collector
        loop = self.worker.loop
        if collector is None or loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(collector.aclose(), loop)
            future.result(timeout=5)
        except Exception:  # noqa: BLE001 - 退出流程里尽力而为
            pass

    def _on_close(self) -> None:
        if self.busy and not messagebox.askokcancel("确认", "任务进行中，确定退出？"):
            return
        self._shutdown_browser()
        try:
            self.worker.stop()
        finally:
            self.destroy()


def _warn_already_running() -> None:
    """已经有一个实例在跑时的提示。

    两个实例会抢同一个浏览器 profile：后启动的那个浏览器会被单例机制
    直接顶掉（exitCode=0），表现成「收集失败」。
    """
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "已经在运行",
            "「XJTLU 试卷下载器」已经有一个窗口在运行了。\n\n"
            "请到任务栏切换到那个窗口。\n\n"
            "不要同时开两个 —— 两个窗口会抢同一个浏览器 profile，谁都用不了。",
        )
        root.destroy()
    except Exception:  # noqa: BLE001 - 没有图形环境时退回命令行提示
        print("「XJTLU 试卷下载器」已经有一个实例在运行。", file=sys.stderr)


def main() -> int:
    # 单实例保护：必须在创建窗口之前拿到锁
    lock = SingleInstance(single_instance_path())
    if not lock.acquire():
        _warn_already_running()
        return 0

    try:
        try:
            app = App()
        except tk.TclError as exc:
            print(f"无法启动图形界面：{exc}", file=sys.stderr)
            print("可以用命令行模式：python main.py --help", file=sys.stderr)
            return 1
        app.mainloop()
        return 0
    finally:
        lock.release()
