"""双击即可用的图形界面入口（给 PyInstaller 打包成 exe 用）。

默认行为：启动 Tkinter 图形界面。不需要命令行参数，也不需要控制台窗口。
打包时 PyInstaller 以本文件为入口，普通用户双击 exe 就能直接进入 GUI。

也支持一个自检模式（给 CI 和排障用）：
    XJTLU_PDF_Fetcher.exe --selftest --selftest-out result.txt
不打开任何窗口，把关键路径跑一遍，用退出码表达成败。
"""

import sys

if __name__ == "__main__":
    if sys.platform == "win32":
        # 让 emoji / 中文在旧版 Windows 控制台不炸（虽然窗口版没有控制台，保险起见）
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if "--selftest" in sys.argv:
        from pdf_fetcher.selftest import main as selftest_main

        sys.exit(selftest_main())
    else:
        from pdf_fetcher.gui import main as gui_main

        sys.exit(gui_main())
