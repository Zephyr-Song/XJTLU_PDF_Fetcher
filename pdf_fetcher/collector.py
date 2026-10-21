"""核心：两阶段「先收集、后批量下载」。

为什么要两阶段（这是相比原版最大的改进）：
  原版是「边浏览边存」—— 你必须开着浏览器、一个个点开试卷、等它存完，
  点 30 份试卷就是 30 次手动操作，中途不能关。

  两阶段是：浏览时只把 URL 记进内存（不下载），你随便点、随便翻，
  关掉浏览器后一次性批量下载全部。手动操作从「点一次下载一次」
  降到「点一次看一次」，批量是自动的。

为什么要用持久化上下文（launch_persistent_context）：
  1. 登录态留在磁盘 profile 里 —— 第一次登录 ETD 之后，之后每次都不用再登。
  2. 收集阶段和下载阶段共用同一个 profile，下载时带着同一份 cookie，
     不会因为新建空 context 而丢掉登录态、被 ETD 拒掉。
  3. 调用的是你自己机器上的 Edge/Chrome 程序（继承企业策略与证书信任），
     只是用了一个独立 profile 目录，不会和你日常浏览的 profile 打架。

为什么不用「输入课程代码自动发现」：
  ETD 前端是 SPA（首页只是 2KB 的空壳），课程列表由前端异步渲染，
  DOM 结构随时可能变。写死选择器的方案一旦改版就完全失效。
  网络拦截 + URL 特征匹配不依赖 DOM，服务端换皮肤也不影响。
"""

from __future__ import annotations

from collections.abc import Callable

from playwright.async_api import BrowserContext, Error as PlaywrightError
from playwright.async_api import Page, Response, async_playwright

from .config import Config
from .detector import (
    Candidate,
    extract_filename,
    guess_course_code,
    guess_course_code_from_url,
    is_real_pdf,
    looks_like_pdf_response,
)
from .storage import human_size, save_bytes

try:  # 新版 Playwright 单独导出了这个异常类型
    from playwright.async_api import TargetClosedError
except ImportError:  # pragma: no cover - 老版本没有单独导出
    TargetClosedError = None  # type: ignore[assignment,misc]


def _is_target_closed(exc: BaseException) -> bool:
    """判断异常是否表示「目标 / 浏览器已被关闭」。

    不依赖 Playwright 是否单独导出 TargetClosedError（各版本不一致），
    按异常类名 + 报错文本双重判定。
    """
    if type(exc).__name__ == "TargetClosedError":
        return True
    return "closed" in str(exc).lower()

# 回调签名：on_log 接收一行日志，on_candidate 接收新收集到的候选
LogFn = Callable[[str], None]
CandidateFn = Callable[["Candidate"], None]
ProgressFn = Callable[[int, int, str], None]


# ---------------------------------------------------------------- 浏览器启动

_NO_BROWSER_HINT = (
    "电脑上既没有 Microsoft Edge 也没有 Google Chrome。\n"
    "本工具需要调用系统浏览器来复用你的 ETD 登录态，\n"
    "请安装 Edge 或 Chrome 任意一个后重试。"
)


async def _launch_context(playwright, config: Config) -> tuple[BrowserContext, str]:
    """按优先级启动持久化上下文，返回 (context, 通道名)。

    持久化的意义：登录态存在磁盘 profile 里，只需第一次登录；
    收集阶段和下载阶段也因此共享同一份 cookie。
    """
    errors: list[str] = []
    for channel in config.browser_channels:
        label = channel or "chromium(内置)"
        try:
            kwargs: dict = {"headless": config.headless}
            if channel:
                kwargs["channel"] = channel
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.resolved_profile_dir),
                **kwargs,
            )
            return context, label
        except Exception as exc:  # noqa: BLE001 - 逐个通道试探，失败是预期路径
            errors.append(f"  · {label}: {type(exc).__name__}: {exc}")
            continue

    raise RuntimeError(_NO_BROWSER_HINT + "\n\n各通道尝试结果：\n" + "\n".join(errors))


# ---------------------------------------------------------------- 收集阶段


class Collector:
    """在浏览器里浏览时，把遇到的 PDF 候选 URL 收集起来（不下载）。"""

    def __init__(
        self,
        config: Config,
        on_log: LogFn | None = None,
        on_candidate: CandidateFn | None = None,
    ) -> None:
        self.config = config
        self._seen: dict[str, Candidate] = {}
        self._skipped = 0
        self._on_log = on_log
        self._on_candidate = on_candidate

    def _log(self, msg: str) -> None:
        """统一出口：有回调走回调（GUI），没有就打印（CLI）。"""
        if self._on_log:
            self._on_log(msg)
        else:
            print(msg)

    def _on_response(self, response: Response) -> None:
        """网络响应回调 —— 必须是同步函数，不能 await（Playwright 会丢失事件）。"""
        try:
            url = response.url
            if not looks_like_pdf_response(
                url,
                response.headers.get("content-type", ""),
                self.config.url_keywords,
            ):
                self._skipped += 1
                return

            candidate = Candidate(
                url=url,
                hint=extract_filename(
                    url, response.headers.get("content-disposition", "")
                ),
                source="network",
                content_type=response.headers.get("content-type", ""),
            )

            if candidate.key not in self._seen:
                self._seen[candidate.key] = candidate
                self._log(f"  [+] 收集 #{len(self._seen)}: {candidate.hint}")
                if self._on_candidate:
                    self._on_candidate(candidate)
        except Exception:  # noqa: BLE001 - 单个响应出错不能中断整个收集
            return

    async def _scan_dom_links(self, context: BrowserContext) -> None:
        """辅助：扫描所有已打开页面的 <a href> 和 iframe src，补充候选。

        有些列表页会直接把 PDF 链接渲染成超链接，网络拦截可能收不到
        （页面未真正请求），这一步把这类链接补进来。
        """
        try:
            pages = list(context.pages)
        except Exception:  # noqa: BLE001 - context 可能已关闭
            return
        for page in pages:
            try:
                hrefs = await page.eval_on_selector_all(
                    "a[href], iframe[src]",
                    "els => els.map(e => e.href || e.src).filter(Boolean)",
                )
            except Exception:  # noqa: BLE001 - 页面可能已关闭或跨域
                continue

            for url in hrefs:
                if not looks_like_pdf_response(url, "", self.config.url_keywords):
                    continue
                candidate = Candidate(url=url, hint=extract_filename(url), source="dom")
                if candidate.key not in self._seen:
                    self._seen[candidate.key] = candidate
                    self._log(f"  [+] 收集 #{len(self._seen)}: {candidate.hint}  (DOM)")
                    if self._on_candidate:
                        self._on_candidate(candidate)

    async def _wait_for_browser_closed(self, context: BrowserContext, page: Page) -> None:
        """等用户关闭浏览器窗口 —— 这是「收集结束」的信号。

        关窗口的瞬间，Playwright 还没来得及把 page 标记为关闭，
        正在等待的 wait_for_timeout 会抛 TargetClosedError。
        那是预期内的结束信号，必须吞掉；否则整个收集阶段会被判为失败
        （表现为「收集失败：TargetClosedError」）。
        """
        while True:
            try:
                if not context.pages:
                    return
            except Exception:  # noqa: BLE001 - context 已关闭
                return
            try:
                await page.wait_for_timeout(500)
            except PlaywrightError as exc:
                if _is_target_closed(exc):
                    return
                raise

    async def run(self) -> list[Candidate]:
        async with async_playwright() as p:
            context, label = await _launch_context(p, self.config)
            self._log(f"\n浏览器已启动: {label}")
            self._log(f"登录态目录: {self.config.resolved_profile_dir}")

            context.on("response", self._on_response)

            pages = list(context.pages)
            page = pages[0] if pages else await context.new_page()

            self._log(f"\n正在打开: {self.config.start_url}")
            try:
                await page.goto(
                    self.config.start_url,
                    wait_until="domcontentloaded",
                    timeout=self.config.page_timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001 - 超时也允许继续手动操作
                self._log(f"页面加载提示: {type(exc).__name__}（可继续手动操作）")

            self._log(
                "收集模式已开启：请在浏览器窗口里登录 ETD（首次需登录，之后自动复用），"
                "然后逐个点开试卷。\n全部点完后，直接关闭浏览器窗口即可开始批量下载。"
            )

            # 等待用户关闭浏览器（所有页面都关掉）
            await self._wait_for_browser_closed(context, page)

            # 关浏览器前扫一遍 DOM 链接
            await self._scan_dom_links(context)

            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass

            self._log(f"\n收集结束：共 {len(self._seen)} 个候选")
            if self.config.verbose:
                self._log(f"（另有 {self._skipped} 个非 PDF 响应被跳过）")

            return list(self._seen.values())


# ---------------------------------------------------------------- 下载阶段


async def download_all(
    candidates: list[Candidate],
    config: Config,
    on_log: LogFn | None = None,
    on_progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """复用同一 profile 的登录态批量下载。返回成功数量。

    on_log(msg)                   —— 每行日志
    on_progress(done, total, msg) —— 进度（GUI 用进度条）
    should_stop()                 —— 返回 True 时在下一个文件前中断
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)
        else:
            print(msg)

    if not candidates:
        log("没有候选可下载。")
        return 0

    out_dir = config.resolved_output_dir
    log(f"开始批量下载 {len(candidates)} 个文件 → {out_dir}")

    ok = 0
    total = len(candidates)

    async with async_playwright() as p:
        context, label = await _launch_context(p, config)
        log(f"浏览器已启动: {label}（复用已保存的登录态）")

        for index, cand in enumerate(candidates, start=1):
            if should_stop and should_stop():
                log("已取消下载。")
                break

            prefix = f"[{index}/{total}]"
            if on_progress:
                on_progress(index - 1, total, cand.hint)

            try:
                resp = await context.request.get(
                    cand.url, timeout=config.page_timeout_ms
                )
                if not resp.ok:
                    log(f"{prefix} 跳过（HTTP {resp.status}）: {cand.hint}")
                    continue

                body = await resp.body()
                if not is_real_pdf(body):
                    # 收集阶段是宽进策略，这里严格校验后丢弃误收的
                    log(f"{prefix} 跳过（非 PDF 文件头）: {cand.hint}")
                    continue

                filename = extract_filename(
                    cand.url,
                    resp.headers.get("content-disposition", ""),
                    fallback=cand.hint or "paper",
                )

                target_dir = out_dir
                if config.group_by_course:
                    # 优先从文件名取课程代码；取不到再看 URL 的查询参数
                    # （不能看路径 —— /browserfile/abc123 这种哈希会被误判）
                    code = guess_course_code(filename) or guess_course_code_from_url(
                        cand.url
                    )
                    if code:
                        target_dir = out_dir / code
                    else:
                        log(f"{prefix} 认不出课程代码，平铺存放: {filename}")

                path = save_bytes(target_dir, filename, body)
                log(f"{prefix} 已保存 {path.name}  ({human_size(len(body))})")
                ok += 1

            except PlaywrightError as exc:
                if _is_target_closed(exc):
                    log(f"{prefix} 浏览器已关闭，下载中断。")
                    break
                log(f"{prefix} 失败（{type(exc).__name__}）: {cand.hint}")
            except Exception as exc:  # noqa: BLE001 - 单个失败不影响整批
                log(f"{prefix} 失败（{type(exc).__name__}）: {cand.hint}")

        if on_progress:
            on_progress(total, total, "")
        try:
            await context.close()
        except Exception:  # noqa: BLE001
            pass

    log(f"完成：成功 {ok} / {total}")
    return ok
