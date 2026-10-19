"""核心：两阶段「先收集、后批量下载」。

为什么要两阶段（这是相比原版最大的改进）：
  原版是「边浏览边存」—— 你必须开着浏览器、一个个点开试卷、等它存完，
  点 30 份试卷就是 30 次手动操作，中途不能关。

  两阶段是：浏览时只把 URL 记进内存（不下载），你随便点、随便翻，
  关掉浏览器后一次性批量下载全部。手动操作从「点一次下载一次」
  降到「点一次看一次」，批量是自动的。

为什么不用「输入课程代码自动发现」：
  ETD 前端是 SPA（首页只是 2KB 的空壳），课程列表由前端异步渲染，
  DOM 结构随时可能变。写死选择器的方案一旦改版就完全失效。
  网络拦截 + URL 特征匹配不依赖 DOM，服务端换皮肤也不影响。
"""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Response, async_playwright

from .config import Config
from .detector import Candidate, extract_filename, is_real_pdf, looks_like_pdf_response
from .storage import human_size, save_bytes

# ---------------------------------------------------------------- 浏览器启动


async def _launch_with_fallback(playwright, config: Config) -> tuple[Browser, str]:
    """按优先级尝试各浏览器通道，返回 (browser, 使用的通道名)。

    用系统浏览器（Edge/Chrome）的好处是能复用已有的登录态与证书信任链；
    内置 Chromium 作为最后兜底，保证脚本在任何机器上都能跑。
    """
    errors: list[str] = []
    for channel in config.browser_channels:
        label = channel or "chromium(内置)"
        try:
            kwargs = {"headless": config.headless}
            if channel:
                kwargs["channel"] = channel
            browser = await playwright.chromium.launch(**kwargs)
            return browser, label
        except Exception as exc:  # noqa: BLE001 - 逐个通道试探，失败是预期路径
            errors.append(f"  · {label}: {type(exc).__name__}")
            continue

    raise RuntimeError("所有浏览器通道都启动失败：\n" + "\n".join(errors))


# ---------------------------------------------------------------- 收集阶段


class Collector:
    """在浏览器里浏览时，把遇到的 PDF 候选 URL 收集起来（不下载）。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._seen: dict[str, Candidate] = {}
        self._skipped = 0

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
                print(
                    f"  [+] 收集 #{len(self._seen)}: {candidate.hint}"
                    f"  ({len(url)} 字符 URL)"
                )
        except Exception:  # noqa: BLE001 - 单个响应出错不能中断整个收集
            return

    async def _scan_dom_links(self, context: BrowserContext) -> None:
        """辅助：扫描所有已打开页面的 <a href> 和 iframe src，补充候选。

        有些列表页会直接把 PDF 链接渲染成超链接，网络拦截可能收不到
        （页面未真正请求），这一步把这类链接补进来。
        """
        for page in context.pages:
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
                    print(f"  [+] 收集 #{len(self._seen)}: {candidate.hint}  (DOM)")

    async def run(self) -> list[Candidate]:
        async with async_playwright() as p:
            browser, label = await _launch_with_fallback(p, self.config)
            print(f"\n浏览器已启动: {label}")

            context = await browser.new_context()
            context.on("response", self._on_response)

            page = await context.new_page()

            print(f"\n正在打开: {self.config.start_url}")
            try:
                await page.goto(
                    self.config.start_url,
                    wait_until="domcontentloaded",
                    timeout=self.config.page_timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001 - 超时也允许继续手动操作
                print(f"页面加载提示: {type(exc).__name__}（可继续手动操作）")

            print(
                "\n"
                + "=" * 62
                + "\n  收集模式已开启 —— 现在请手动操作浏览器：\n"
                "    1. 登录 ETD（如需）\n"
                "    2. 进入课程页面，逐个点开你想下载的试卷\n"
                "    3. 随便翻、随便点，脚本只记录不下载，很快\n"
                "    4. 全部点完后，直接关闭浏览器窗口\n"
                + "=" * 62
                + "\n"
            )

            # 等待用户关闭浏览器（所有页面都关掉）
            while context.pages:
                await page.wait_for_timeout(500)

            # 关浏览器前扫一遍 DOM 链接
            await self._scan_dom_links(context)

            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

            print(f"\n收集结束：共 {len(self._seen)} 个候选")
            if self.config.verbose:
                print(f"（另有 {self._skipped} 个非 PDF 响应被跳过）")

            return list(self._seen.values())


# ---------------------------------------------------------------- 下载阶段


async def download_all(candidates: list[Candidate], config: Config) -> int:
    """复用同一 context 的 cookie 批量下载。返回成功数量。"""
    if not candidates:
        print("没有候选可下载。")
        return 0

    out_dir = config.resolved_output_dir
    print(f"\n开始批量下载 {len(candidates)} 个文件 → {out_dir}\n")

    ok = 0
    async with async_playwright() as p:
        browser, _ = await _launch_with_fallback(p, config)
        context = await browser.new_context()

        for index, cand in enumerate(candidates, start=1):
            prefix = f"[{index}/{len(candidates)}]"
            try:
                resp = await context.request.get(cand.url, timeout=config.page_timeout_ms)
                if not resp.ok:
                    print(f"{prefix} 跳过（HTTP {resp.status}）: {cand.hint}")
                    continue

                body = await resp.body()
                if not is_real_pdf(body):
                    # 收集阶段是宽进策略，这里严格校验后丢弃误收的
                    print(f"{prefix} 跳过（非 PDF 文件头）: {cand.hint}")
                    continue

                filename = extract_filename(
                    cand.url,
                    resp.headers.get("content-disposition", ""),
                    fallback=cand.hint or "paper",
                )

                target_dir = out_dir
                if config.group_by_course:
                    from .detector import guess_course_code

                    code = guess_course_code(cand.url)
                    if code:
                        target_dir = out_dir / code

                path = save_bytes(target_dir, filename, body)
                print(f"{prefix} 已保存 {path.name}  ({human_size(len(body))})")
                ok += 1

            except Exception as exc:  # noqa: BLE001 - 单个失败不影响整批
                print(f"{prefix} 失败（{type(exc).__name__}）: {cand.hint}")

        await browser.close()

    print(f"\n完成：成功 {ok} / {len(candidates)}")
    return ok
