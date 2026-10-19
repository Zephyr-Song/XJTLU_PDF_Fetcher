"""落盘逻辑 —— 纯逻辑（除最终写文件外），可测试。"""

from __future__ import annotations

import os
from pathlib import Path

from .detector import sanitize_filename


def resolve_save_path(directory: Path, filename: str) -> Path:
    """解决重名：若已存在则追加 (1) (2) ... 直到空位。

    不做「覆盖」是刻意的 —— 批量下载时用户不希望悄悄丢文件。
    """
    directory = Path(directory)
    filename = sanitize_filename(filename)
    path = directory / filename
    if not path.exists():
        return path

    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = directory / f"{stem}({counter}){ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def save_bytes(directory: Path, filename: str, body: bytes) -> Path:
    """写入文件，返回真实路径。目录不存在时自动创建。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = resolve_save_path(directory, filename)
    with open(path, "wb") as f:
        f.write(body)
    return path


def human_size(n: int) -> str:
    """字节数转人类可读。"""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"
