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
import sys
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

    用操作系统文件锁实现，进程退出（包括崩溃）时由系统自动释放，
    不会留下需要手工清理的死锁文件。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """尝试加锁。成功返回 True；已被别的实例占用返回 False。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False

        self._fd = fd
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.truncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        return True

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
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
    """单实例锁文件位置：和 profile 同级，避开需要管理员权限的目录。"""
    return default_profile_dir().parent / "app.lock"
