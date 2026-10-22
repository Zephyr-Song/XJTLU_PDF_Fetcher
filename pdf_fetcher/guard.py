"""运行期保护：单实例锁 + 浏览器 profile 占用检测。

为什么需要这两件事（都是被真实问题逼出来的）：

1. **profile 只能被一个浏览器进程使用。**
   Chromium 系浏览器对同一个 --user-data-dir 是单例的：第二个进程启动后
   发现已有实例，会把命令行转交给它，然后**自己以 exitCode=0 退出**。
   Playwright 看到浏览器"启动即退出"，抛的是 TargetClosedError ——
   而旧代码把所有通道失败一律解释成「电脑上没装 Edge/Chrome」，
   于是用户明明装着两个浏览器却被告知没装。

   实测可用的探针：浏览器运行期间，profile 目录下的 `lockfile`
   会被独占锁定（open("r+b") 抛 PermissionError），关闭后该文件消失。
   这个判断不依赖 WMI/进程枚举，几十微秒就能出结果。

2. **GUI 被重复启动时必然撞上上面这条。**
   第二次双击 exe → 新 GUI 去抢同一个 profile → 启动即退出 → 报错。
   所以 GUI 启动时要拿一把跨进程的锁，拿不到就说明已经有一个实例在跑。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .paths import default_profile_dir

# Chromium 在 user-data-dir 下维护的锁文件
_CHROMIUM_LOCKFILE = "lockfile"


class ProfileBusyError(RuntimeError):
    """profile 被另一个浏览器进程占用，本次无法启动浏览器。"""


def profile_in_use(profile_dir: Path | str | None = None) -> bool:
    """判断该 profile 是否正被某个浏览器进程使用。

    依据：Chromium 运行期间独占锁住 `<profile>/lockfile`。
    · 文件不存在            → 没在用
    · 存在且能打开          → 残留的旧文件（上次异常退出），不算占用
    · 存在但打不开（被锁）   → 有浏览器正在用
    """
    profile = Path(profile_dir) if profile_dir else default_profile_dir()

    if sys.platform != "win32":
        # POSIX 下 Chromium 用 SingletonLock 符号链接（内容形如 hostname-12345）
        try:
            target = os.readlink(profile / "SingletonLock")
        except OSError:
            return False
        pid = target.rsplit("-", 1)[-1]
        if not pid.isdigit():
            return False
        try:
            os.kill(int(pid), 0)      # 只探测进程是否存在
        except ProcessLookupError:
            return False
        except PermissionError:
            return True               # 存在但不属于当前用户
        return True

    lock = profile / _CHROMIUM_LOCKFILE
    try:
        with open(lock, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        # PermissionError / WinError 32：被别的进程以独占共享模式打开
        return True


def busy_hint(profile_dir: Path | str | None = None) -> str:
    """profile 被占用时给用户看的说明（强调「关掉窗口」，别让人以为没装浏览器）。"""
    profile = Path(profile_dir) if profile_dir else default_profile_dir()
    return (
        "浏览器 profile 正被占用，无法启动新的浏览器窗口。\n\n"
        "最常见的原因：\n"
        "· 上一次收集打开的浏览器窗口还没关（可能在任务栏或别的窗口后面）\n"
        "· 同时开了两个「XJTLU 试卷下载器」窗口\n\n"
        "请关掉那个浏览器窗口（或另一个下载器窗口），再点「开始收集」。\n"
        "这不影响你的登录态，关掉重开不用重新登录。\n\n"
        f"profile 目录：{profile}"
    )


# ---------------------------------------------------------------- 单实例锁

class SingleInstance:
    """跨进程的「只允许一个实例」锁。

    Windows 用**命名互斥量（named mutex）**实现 —— 这是 Windows 上最可靠的
    单实例原语，不依赖文件共享语义，因此不会因为杀软、网络盘、或 PyInstaller
    单文件解压到不同临时目录而失效（旧版用 msvcrt.locking 锁文件，在真实
    双击/解压场景下会出现「两个实例都拿到锁」的竞态）。

    POSIX 仍用 fcntl 文件锁（行为稳定）。进程退出（含崩溃）由系统自动释放。
    """

    # Windows 互斥量名：Local\\ 限定在当前会话，避免机器级冲突
    _WIN_NAME = "Local\\XJTLU_PDF_Fetcher_SingleInstance"

    def __init__(self, path: Path | str) -> None:
        # path 仅 POSIX 下作为锁文件使用；Windows 用固定互斥量名
        self.path = Path(path)
        self._handle = None  # Windows 互斥量句柄
        self._fd: int | None = None  # POSIX 文件描述符

    def acquire(self) -> bool:
        """尝试加锁。成功返回 True；已被别的实例占用返回 False。"""
        if sys.platform == "win32":
            return self._acquire_win()
        return self._acquire_posix()

    def _acquire_win(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.GetLastError.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.CreateMutexW(None, True, self._WIN_NAME)
        if not handle:
            return False
        # ERROR_ALREADY_EXISTS = 183：已有一个实例持有同名互斥量
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def _acquire_posix(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if sys.platform == "win32":
            handle = self._handle
            self._handle = None
            if handle is not None:
                try:
                    import ctypes
                    from ctypes import wintypes

                    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
                    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                    kernel32.ReleaseMutex(handle)
                except OSError:
                    pass
                finally:
                    try:
                        ctypes.windll.kernel32.CloseHandle(handle)  # noqa: B018
                    except Exception:
                        pass
            return

        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def single_instance_path() -> Path:
    """单实例锁文件位置（仅 POSIX 使用；Windows 用命名互斥量）。"""
    return default_profile_dir().parent / "app.lock"


def kill_browser_using_profile(profile_dir: Path | str | None = None) -> int:
    """杀掉所有正在使用本程序 profile 的浏览器进程。

    本程序的 profile 目录是**专用的**（不会和用户的日常浏览器冲突），
    所以任何挂在这个 profile 上的浏览器进程都只能是本程序遗留的孤儿进程，
    安全可杀。返回「尝试结束的进程数」（best-effort）。

    典型场景：上次收集时浏览器窗口没正常关掉（或程序崩溃），这个进程会一直
    占着 profile 的 lockfile，导致下次一点「开始收集」就报「浏览器窗口还开着」
    却又找不到窗口在哪 —— 这里直接帮用户清理掉。
    """
    profile = Path(profile_dir) if profile_dir else default_profile_dir()
    if sys.platform != "win32":
        # POSIX：SingletonLock 是个指向 "hostname-pid" 的符号链接
        try:
            target = os.readlink(profile / "SingletonLock")
        except OSError:
            return 0
        pid = target.rsplit("-", 1)[-1]
        if not pid.isdigit():
            return 0
        try:
            os.kill(int(pid), 9)
            return 1
        except OSError:
            return 0

    # Windows：按命令行精确匹配本程序 profile 路径，避免误杀用户的正常浏览器
    marker = str(profile).replace("/", "\\")
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\""
        f" | Where-Object {{ $_.CommandLine -like '*{marker}*' }}"
        " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - 清理失败不阻塞主流程
        return 0
    # 给一点时间让进程退出、释放 lockfile
    time.sleep(1.0)
    return 1

