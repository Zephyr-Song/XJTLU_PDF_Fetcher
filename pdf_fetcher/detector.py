"""PDF 探测与分类 —— 纯函数，无 IO，可单元测试。

设计原则：
  收集阶段用「廉价启发式」（只看 URL 和 header），避免逐个大文件读 body；
  下载阶段用「严格校验」（读 magic bytes），保证存下来的确实是 PDF。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------- 常量

# 明确的非 PDF 静态资源后缀，直接排除（避免无谓的响应处理）
NON_DOCUMENT_EXTENSIONS: tuple[str, ...] = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".json", ".xml",
)

# PDF 的 magic bytes
PDF_MAGIC = b"%PDF"

# .pdf 出现在 URL 中且后面是结束符或分隔符（兼容 ?file=a.pdf&sig=xxx）
_PDF_IN_URL_RE = re.compile(r"\.pdf(?:$|[?#&;])")

# Content-Disposition 里提取文件名的正则# 覆盖三种写法：
#   filename="a.pdf"
#   filename=a.pdf
#   filename*=UTF-8''%E8%AF%95%E5%8D%B7.pdf   (RFC 5987)
_CONTENT_DISPOSITION_RE = re.compile(
    r"""filename\*?\s*=\s*(?:UTF-8'')?"?([^";\n]+)"?""",
    re.IGNORECASE,
)

# 文件名中的非法字符（Windows / 跨平台通用）
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')

# Windows 保留设备名
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


# ---------------------------------------------------------------- 数据模型

@dataclass(frozen=True)
class Candidate:
    """一个待下载的候选对象。"""

    url: str
    hint: str = ""          # 文件名提示（可能来自 Content-Disposition 或 URL）
    source: str = ""        # 发现来源，便于排查：network / dom / manual / file
    content_type: str = ""

    @property
    def key(self) -> str:
        """去重键：去掉 query 里的签名参数，避免同一文件不同签名被算作两个。

        重要：ETD 的 PDF 链接带 timestamp/signature，同一份试卷每次打开
        签名都不同。如果直接用完整 URL 去重，同一个文件会被下载多份。
        """
        parsed = urlparse(self.url)
        path = parsed.path.rstrip("/").lower()
        # 用 path 的最后一段作为主体标识；没有 path 的退化用完整 url
        return path or self.url.lower()


# ---------------------------------------------------------------- 判定逻辑

def is_static_asset(url: str) -> bool:
    """判断是否为明确的静态资源（应跳过）。"""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in NON_DOCUMENT_EXTENSIONS)


def looks_like_pdf_response(
    url: str,
    content_type: str = "",
    extra_url_keywords: tuple[str, ...] = ("browserfile",),
) -> bool:
    """收集阶段的廉价判定：不看 body，只靠 URL 和 content-type。

    为降低漏判，采用宽进策略 —— 收集阶段多收一些，下载阶段再用
    magic bytes 精确校验，误收的会被丢弃。
    """
    if is_static_asset(url):
        return False

    ct = (content_type or "").lower()
    lower_url = url.lower()

    # 死排除：PDF 查看器页面本身是 HTML，不是 PDF
    if "viewer.html" in lower_url:
        return False

    # 明确命中
    if "application/pdf" in ct:
        return True
    # .pdf 出现在 path 末尾，或出现在 query 里（如 ?file=paper.pdf&sig=xxx）
    if _PDF_IN_URL_RE.search(lower_url):
        return True
    if any(kw in lower_url for kw in extra_url_keywords):
        return True

    # octet-stream 可疑，但可能是 zip 之类，收进来交给下载阶段校验
    if "octet-stream" in ct:
        return True

    return False


def is_real_pdf(body: bytes) -> bool:
    """下载阶段的严格校验：检查文件头。"""
    return bool(body) and body.lstrip()[:4] == PDF_MAGIC


def extract_filename(
    url: str,
    content_disposition: str = "",
    fallback: str = "paper",
) -> str:
    """按优先级提取文件名：Content-Disposition > URL path > fallback。"""
    # 1) Content-Disposition（服务器给的最准）
    if content_disposition:
        m = _CONTENT_DISPOSITION_RE.search(content_disposition)
        if m:
            name = unquote(m.group(1).strip())
            if name:
                return sanitize_filename(name)

    # 2) URL path 的最后一段
    path = urlparse(url).path
    last = unquote(path.rstrip("/").rsplit("/", 1)[-1]) if path else ""
    if last and "." in last:
        return sanitize_filename(last)

    # 3) 兜底
    return sanitize_filename(f"{fallback}.pdf")


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """清理文件名：非法字符、保留名、长度、扩展名。"""
    name = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip().strip(".")

    # 注意：分隔符已在上面被替换成下划线，因此不存在路径穿越风险。
    # 这里不再做 ".." → "_" 的整体替换，否则会破坏 a..b.pdf 这类合法名。

    if not name:
        return "paper.pdf"

    # 保留设备名冲突（Windows 上 CON.pdf 会写入失败）
    stem = name.rsplit(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        name = f"_{name}"

    # 保证扩展名
    if not name.lower().endswith(".pdf"):
        name += ".pdf"

    # 截断保护（Windows 全路径 260 字符限制）
    if len(name) > max_length:
        stem = name[:-4][: max_length - 4]
        name = f"{stem}.pdf"

    return name


def guess_course_code(url: str) -> str:
    """尝试从 URL 里猜课程代码（用于按课归档），猜不到返回空串。

    常见形式：CAN201 / CPT203 / MEC302 / COMP101
    """
    # 课程代码通常由 2-5 个字母 + 3-4 位数字组成。
    # 用自定义边界而不是 \b，因为 \b 不认下划线（CPT203_2023 会匹配失败）。
    pattern = re.compile(r"(?<![A-Z0-9])([A-Z]{2,5}\d{3,4})(?![0-9])")
    m = pattern.search(unquote(url).upper())
    return m.group(1) if m else ""
