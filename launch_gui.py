"""双击即可用的图形界面入口（给 PyInstaller 打包成 exe 用）。

只做一件事：启动 Tkinter 图形界面。不需要命令行参数，
也不需要控制台窗口。打包时 PyInstaller 以本文件为入口，
普通用户双击 exe 就能直接进入 GUI。
"""

import sys

from pdf_fetcher.gui import main

if __name__ == "__main__":
    if sys.platform == "win32":
        # 让 emoji / 中文在旧版 Windows 控制台不炸（虽然窗口版没有控制台，保险起见）
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
