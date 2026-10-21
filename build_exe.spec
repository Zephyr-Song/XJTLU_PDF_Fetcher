# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把图形界面打包成单文件 Windows exe。

用法（在仓库根目录）：
    pip install pyinstaller
    pyinstaller build_exe.spec --noconfirm

产物： dist/XJTLU_PDF_Fetcher.exe  （双击即用，无需安装 Python / Playwright / git）
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Playwright 通过子进程启动一个 node driver，PyInstaller 默认收集不全，
# 用 collect_all 把它连带 driver / 依赖一起打进 exe，避免运行时 MissingModule。
for pkg in ("playwright", "playwright.async_api", "playwright.sync_api", "playwright._impl"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["launch_gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "pdf_fetcher",
        "pdf_fetcher.gui",
        "pdf_fetcher.cli",
        "pdf_fetcher.collector",
        "pdf_fetcher.detector",
        "pdf_fetcher.storage",
        "pdf_fetcher.config",
        "asyncio",
        "greenlet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="XJTLU_PDF_Fetcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    windowed=True,
)
