"""路径解析 —— 拿到系统「真实」的桌面目录。

为什么不能直接用 Path.home() / "Desktop"：
    Windows 的桌面是可以被重定向到别处的 —— OneDrive 的「备份桌面」、
    域环境的文件夹重定向、组策略的 Known Folder Move，都会把真实桌面搬到
    C:\\Users\\<用户>\\OneDrive\\Desktop 之类的地方。
    而 Path.home() / "Desktop" 无论如何都返回 C:\\Users\\<用户>\\Desktop，
    那个目录用户根本看不到 —— 文件被下载进了「影子文件夹」，
    使用者会以为没下载成功。

三层解析，逐级兜底：
    1. SHGetKnownFolderPath(FOLDERID_DesktopDirectory)  系统标准做法，尊重重定向
    2. 注册表 HKCU\\...\\Explorer\\User Shell Folders\\Desktop（重定向后该值同样是真实路径）
    3. Path.home() / "Desktop"  最后的保底

注意用的是 FOLDERID_DesktopDirectory 而不是 FOLDERID_Desktop：
    后者是「桌面」这个虚拟命名空间的根，不对应磁盘上的真实文件夹，
    对它调用 SHGetKnownFolderPath 会返回 E_FILE_NOT_FOUND。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _windows_desktop_via_api() -> Path | None:
    """SHGetKnownFolderPath(FOLDERID_DesktopDirectory)。失败返回 None。"""
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        # FOLDERID_DesktopDirectory = {C2B67530-3871-49C6-B4C5-15F8A7A7A25A}
        folderid_desktop_directory = _GUID(
            0xC2B67530,
            0x3871,
            0x49C6,
            (ctypes.c_byte * 8)(0xB4, 0xC5, 0x15, 0xF8, 0xA7, 0xA7, 0xA2, 0x5A),
        )

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        func = shell32.SHGetKnownFolderPath
        func.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        func.restype = ctypes.c_long  # HRESULT，0 表示成功

        path_ptr = ctypes.c_wchar_p()
        guid_ptr = ctypes.cast(ctypes.byref(folderid_desktop_directory), ctypes.c_void_p)
        hresult = func(guid_ptr, 0, None, ctypes.byref(path_ptr))
        if hresult != 0 or not path_ptr.value:
            return None

        try:
            return Path(path_ptr.value)
        finally:
            try:
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            except Exception:
                pass
    except Exception:
        return None


def _windows_desktop_via_registry() -> Path | None:
    """读 HKCU\\...\\Explorer\\User Shell Folders\\Desktop。失败返回 None。

    这是「桌面」当前生效的位置。若用户启用了 OneDrive 备份桌面，
    这里会是 %USERPROFILE%\\OneDrive\\Desktop，展开后就是真实路径。
    """
    if sys.platform != "win32":
        return None

    try:
        import os
        import winreg

        subkey = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        if not value:
            return None
        expanded = os.path.expandvars(value)
        if not expanded:
            return None
        return Path(expanded)
    except Exception:
        return None


def desktop_dir() -> Path:
    """返回系统真实的桌面目录。

    优先走 Windows Known Folder API，其次读注册表，
    最后退回 Path.home() / "Desktop"。
    """
    for getter in (_windows_desktop_via_api, _windows_desktop_via_registry):
        path = getter()
        if path is not None:
            return path
    return Path.home() / "Desktop"


def default_output_dir() -> Path:
    """默认下载目录：桌面。"""
    return desktop_dir()
