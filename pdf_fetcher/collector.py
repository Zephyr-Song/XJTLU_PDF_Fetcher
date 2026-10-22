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

import asyncio
from collections.abc import Callable

from playwright.async_api import BrowserContext, Error as PlaywrightError
from playwright.async_api import Page, Response, async_playwright

from .config import Config
from .detector import (
    Candidate,
    extract_filename,
    is_real_pdf,
    looks_like_pdf_response,
)
from .guard import (
    ProfileBusyError,
    busy_hint,
    kill_browser_using_profile,
    profile_in_use,
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

_LAUNCH_FAILED_HINT = (
    "浏览器启动失败 —— 浏览器是装着的，但没能正常拉起窗口。\n\n"
    "常见原因：\n"
    "· 浏览器窗口被安全软件 / 组策略拦截\n"
    "· 浏览器版本与内置驱动不匹配\n"
    "· 上次的浏览器进程没退干净，还占着 profile\n\n"
    "可以试试：\n"
    "· 关掉所有 Edge / Chrome 窗口后重试\n"
    "· 命令行加 --channel chrome 换另一个浏览器\n"
    "· 删掉 profile 目录让它重建（代价：要重新登录一次）"
)

# 判断异常是否表示「这个通道根本没有对应的可执行文件」
_MISSING_MARKERS = (
    "executable doesn't exist",
    "is not found",
    "no such file",
    "找不到",
)

# 上次非正常退出时，不要弹「恢复页面」气泡打断流程
_LAUNCH_ARGS = (
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
)


def _looks_missing(message: str) -> bool:
    low = message.lower()
    return any(marker in low for marker in _MISSING_MARKERS)


async def _launch_context(playwright, config: Config) -> tuple[BrowserContext, str]:
    """按优先级启动持久化上下文，返回 (context, 通道名)。

    持久化的意义：登录态存在磁盘 profile 里，只需第一次登录；
    收集阶段和下载阶段也因此共享同一份 cookie。

    启动前先确认 profile 没被占用 —— 否则 Chromium 的单例机制会让新进程
    直接把命令行转交给已有实例然后自己退出（exitCode=0），
    表现出来是 TargetClosedError，极容易被误判成「没装浏览器」。
    """
    profile = config.resolved_profile_dir
    if profile_in_use(profile):
        # 本程序的 profile 是专用的，残留的浏览器进程一定是上一次遗留的孤儿，
        # 直接帮用户杀掉（仍是同一个 profile，登录态在磁盘上不会丢），
        # 免得弹出「浏览器窗口还开着」却找不到窗口在哪 —— 这正是「打不开网页」的根因。
        killed = kill_browser_using_profile(profile)
        if killed:
            await asyncio.sleep(1.5)
        if profile_in_use(profile):
            # 杀不掉（比如被别的进程以独占方式锁死）才退回到人工提示
            raise ProfileBusyError(busy_hint(profile))

    errors: list[str] = []
    missing: list[str] = []

    for channel in config.browser_channels:
        label = channel or "chromium(内置)"
        try:
            kwargs: dict = {"headless": config.headless, "args": list(_LAUNCH_ARGS)}
            if channel:
                kwargs["channel"] = channel
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                **kwargs,
            )
            return context, label
        except Exception as exc:  # noqa: BLE001 - 逐个通道试探，失败是预期路径
            message = f"{type(exc).__name__}: {exc}"
            errors.append(f"  · {label}: {message}")
            if _looks_missing(message):
                missing.append(label)
            # 启动瞬间被单例机制顶掉：说明这期间 profile 被别人占了
            if type(exc).__name__ == "TargetClosedError" and profile_in_use(profile):
                raise ProfileBusyError(busy_hint(profile)) from exc
            continue

    detail = "\n\n各通道尝试结果：\n" + "\n".join(errors)
    # 只有「每个通道都报可执行文件不存在」才敢说是没装浏览器
    if missing and len(missing) == len(config.browser_channels):
        raise RuntimeError(_NO_BROWSER_HINT + detail)
    raise RuntimeError(_LAUNCH_FAILED_HINT + detail)


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
        # 供 GUI 从外部结束收集（不用逼用户去关浏览器窗口）
        self._context: BrowserContext | None = None
        self._stop = False

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
            if self._stop:          # GUI 点了「结束收集」
                return
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

    async def aclose(self) -> None:
        """从外部结束收集：置停止标志并关掉浏览器，让 run() 正常收敛。

        GUI 的「■ 结束收集」按钮走这条路径，用户不必去找到并关闭浏览器窗口。
        """
        self._stop = True
        ctx = self._context
        if ctx is None:
            return
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001 - 已经关了就算了
            pass

    async def run(self) -> list[Candidate]:
        async with async_playwright() as p:
            context, label = await _launch_context(p, self.config)
            self._context = context
            try:
                return await self._collect_loop(context, label)
            finally:
                # 无论正常结束、异常退出还是被取消，都必须关掉浏览器 ——
                # 否则 profile 一直被占着，下次启动必然 TargetClosedError。
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass
                self._context = None

    async def _collect_loop(
        self, context: BrowserContext, label: str
    ) -> list[Candidate]:
        self._log(f"\n浏览器已启动: {label}")
        self._log(f"登录态目录: {self.config.resolved_profile_dir}")

        if self._stop:      # 还没开始就被要求结束
            return list(self._seen.values())

        context.on("response", self._on_response)

        # 优先复用已有页面：上次非正常退出时 Chromium 会恢复多个标签，
        # 这里挑一个非 about:blank 的，避免在空白页里等着而看不到起始网址。
        existing = list(context.pages)
        pages = [pg for pg in existing if pg.url != "about:blank"]
        page = pages[0] if pages else (existing[0] if existing
                                       else await context.new_page())

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
            "然后逐个点开试卷。\n全部点完后，点「■ 结束收集」或直接关闭浏览器窗口。"
        )

        # 等待用户关闭浏览器（所有页面都关掉）
        await self._wait_for_browser_closed(context, page)

        # 关浏览器前扫一遍 DOM 链接
        await self._scan_dom_links(context)

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

                path = save_bytes(out_dir, filename, body)
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
