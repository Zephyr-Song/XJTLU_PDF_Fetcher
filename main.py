"""入口脚本。用法见 python main.py --help"""

import sys

from pdf_fetcher.cli import main

if __name__ == "__main__":
    if sys.platform == "win32":
        # 让 emoji / 中文在旧版 Windows 控制台不炸
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
