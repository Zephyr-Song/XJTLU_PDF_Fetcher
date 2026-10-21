# XJTLU PDF Fetcher

[![GitHub Release](https://img.shields.io/github/v/release/Zephyr-Song/XJTLU_PDF_Fetcher?label=下载%20exe&color=blue)](https://github.com/Zephyr-Song/XJTLU_PDF_Fetcher/releases/latest)

批量下载 XJTLU ETD（Theses and Dissertations Database）里你**有权限访问**的历年试卷 PDF。

> **核心设计：先收集，后批量下载。**
> 你在浏览器里点开试卷页面时，脚本只把 URL 记下来（不下载）；全部点完后关掉浏览器，脚本一次性批量下载。
> 手动操作从「点一份存一份」变成「点一遍、然后走开」。

---

## ⏬ 不会用命令行？下载 exe 版（推荐）

不想装 Python、不想碰 git？直接下载打包好的单文件程序，**双击就能用**：

1. 打开本仓库的 **[Releases](https://github.com/Zephyr-Song/XJTLU_PDF_Fetcher/releases/latest)** 页面
2. 在 **Assets** 里下载 `XJTLU_PDF_Fetcher.exe`
3. 双击运行 → 用自己的账号登录 ETD → 点开试卷 → 关浏览器 → 自动下载

> exe 只是把本工具打包成免安装程序，**仍然只复用你自己的 ETD 登录态**，试卷留在你本机、不对外分发。下面的使用须知同样适用。

### 🔏 关于 Windows SmartScreen 拦截

第一次下载打开时，Windows 可能弹出 **“Windows 已保护你的电脑 / SmartScreen 阻止了无法识别的应用”**。这是因为 exe **没有代码签名**、发布者未知——属正常现象，不代表文件有毒。

两种处理办法：

1. **临时（用户侧）**：在拦截窗口点「**更多信息**」→「**仍要运行**」即可。本工具源码完全公开，可自行审查。
2. **彻底（发布侧，推荐）**：给 exe 做 Authenticode 代码签名。本项目 CI 已支持自动签名——在仓库 **Settings → Secrets and variables → Actions** 添加两个 Secret：
   - `CODESIGN_PFX`：证书（含私钥）的 **base64 编码 PFX**
   - `CODESIGN_PASSWORD`：PFX 密码

   之后每次发 Release，GitHub Actions 自动用该证书签名，SmartScreen 拦截即消失（**EV 证书即时生效**；OV/IV 证书会先显示你的发布者名称，随下载量积累声誉后不再警告）。

   - 预算有限可看：Certum 开源开发者证书（便宜）、Sectigo / SSL.com 的 OV 证书，或开源项目免费签名服务 **SignPath**。

---

## ⚠️ 使用须知（请先读完）

**本工具只做一件事：把你本来就能在线查看的 PDF 保存到本地，方便离线复习。**

### 允许 ✅
- 个人复习、期末备考
- 保存自己有访问权限的试卷
- 离线查看，避免反复加载

### 禁止 ❌
- **分发、上传、分享给他人**（包括群聊、网盘、社交平台）
- 任何商业用途
- 传播当前学年尚未公开的考试内容
- 绕过任何权限控制 —— 本工具不使用任何漏洞或越权手段，只复用你自己的登录态

**试卷版权归学校与出题教师所有。** 下载到本地是个人使用；一旦传播，问题就变成你的了。使用本工具即表示你理解并同意上述约定。

---

## 为什么需要它

ETD 只允许在线查看 PDF，不提供下载按钮。这导致：

- 没法离线看，每次复习都要联网重新加载
- 网络差的时候一个 PDF 要转很久
- 想按课程整理历年真题，只能一份份手动截图或另存

---

## 它和「边浏览边下载」的脚本有什么不同

| | 传统脚本 | 本工具 |
|---|---|---|
| 工作流 | 点一份 → 等存完 → 再点下一份 | 点一遍（只记录）→ 关浏览器 → 自动批量下载 |
| 手动次数 | 每份试卷 1 次操作 | 每份试卷 1 次点击，但无需等待 |
| 中途能否关浏览器 | 不能 | 可以 |
| 能不能先看看有哪些 | 不能，点了就存 | 可以，收集完再决定下不下 |

**关键差别**：传统的「监听响应即下载」会让每个 PDF 的完整内容都实时落到磁盘上，你要一直等到它传完才能点下一个。本工具收集阶段只读响应头（几个字节），几乎瞬间完成 —— 所以你可以快速翻完一门课的所有试卷，最后一次性下载。

---

## 安装

需要 Python 3.10+。

```bash
pip install -r requirements.txt
playwright install chromium
```

> `playwright install` 只需执行一次。如果你打算用系统 Edge/Chrome（推荐，能复用已登录态），内置 Chromium 只是兜底。

---

## 自行构建（可选）

想自己打包 exe：

```bash
pip install pyinstaller
pyinstaller build_exe.spec --noconfirm
```

产物在 `dist/XJTLU_PDF_Fetcher.exe`。

或者什么都不装，直接用 Releases 里那个 —— 它由本仓库的 GitHub Actions 从同一份公开源码自动构建。

---

## 用法

### 方式一：图形界面（推荐，不用记参数）

```bash
python main.py --gui
```

Windows 上也可以直接双击 **`run_gui.bat`**。嫌装环境麻烦的话，直接用上面 Releases 里的 `XJTLU_PDF_Fetcher.exe`，连 Python 都不用装。

界面长这样：

```
┌─ XJTLU 试卷下载器 ─────────────────────────────────────┐
│ 设置                                                    │
│  起始网址  https://etd.xjtlu.edu.cn/                    │
│  保存到    C:\Users\你\Desktop        [浏览…] [打开]    │
│  ☐ 按课程代码分子目录                                   │
├─────────────────────────────────────────────────────────┤
│ [① 开始收集] [② 下载选中] [取消]      [全选] [全不选]   │
├─────────────────────────────────────────────────────────┤
│ 收集到的试卷（点击行可切换勾选）                        │
│  选 │ 文件名                        │ 来源              │
│  ☑  │ CAN201_2023_Final.pdf         │ network           │
│  ☑  │ CPT203_2022_Final.pdf         │ network           │
│  ☐  │ MEC302_2021.pdf               │ dom               │
├─────────────────────────────────────────────────────────┤
│ ████████████░░░░░░░░░░  6/12  CPT203…                   │
├─────────────────────────────────────────────────────────┤
│ 日志                                                    │
│  [+] 收集 #1: CAN201_2023_Final.pdf                     │
│  [6/12] 已保存 CPT203_2022_Final.pdf  (2.1 MB)          │
└─────────────────────────────────────────────────────────┘
```

**操作四步：**

1. 确认「保存到」的目录
2. 点 **① 开始收集** → 弹出浏览器 → 登录 ETD、逐个点开试卷 → **关闭浏览器窗口**
3. 列表里会出现收集到的试卷，**点行可以取消/恢复勾选**，不需要的取消掉
4. 点 **② 下载选中** → 进度条走完就结束了

> 为什么不做成「网页上点按钮就能下载」？因为那等于把下载入口开放给所有人，性质从「个人离线备份」变成「分发试卷」—— 正是本文开头禁止的行为。**GUI 只跑在你自己的电脑上，不对外提供任何服务。**

### 方式二：命令行

```bash
python main.py
```

1. 会自动打开浏览器（优先用你的 Edge，其次是 Chrome，最后是内置 Chromium）
2. 在浏览器里**正常登录 ETD**，进入课程页面
3. **逐个点开**你要下载的试卷 —— 每收集到一个会打印 `[+] 收集 #N`
4. 全部点完后，**直接关闭浏览器窗口**
5. 脚本自动开始批量下载，存到桌面

### 常用参数

```bash
# 存到指定目录
python main.py -o D:/papers

# 按课程代码自动分子目录（CAN201/、CPT203/ ...）
python main.py -o D:/papers --group-by-course

# 只收集，把 URL 存成文件，之后再用（链接有签名，可能过期）
python main.py --collect-only -o urls.txt

# 从 URL 列表直接下载，不打开浏览器
python main.py --from-file urls.txt -o D:/papers

# 指定浏览器通道
python main.py --channel chrome

# 收集不到东西时，打开详细日志看哪些响应被跳过了
python main.py -v
```

### 参数表

| 参数 | 说明 |
|---|---|
| `-o, --output` | 输出目录（默认桌面） |
| `--group-by-course` | 按课程代码（如 `CAN201`）建子目录 |
| `--from-file FILE` | 从文本文件读 URL 列表下载，每行一个，`#` 开头为注释 |
| `--collect-only` | 只收集不下载；配合 `-o` 把 URL 写入文件 |
| `--no-auto-download` | 收集后打印 URL 但不下载 |
| `--channel` | `msedge` / `chrome` / `chromium`，默认按顺序自动尝试 |
| `--headless` | 无头模式（需要登录时不可用） |
| `--url` | 起始页面，默认 ETD 首页 |
| `--gui` | 打开图形界面（等价于双击 `run_gui.bat`） |
| `-v, --verbose` | 打印被跳过的响应数量 |

---

## 工作原理

### 两阶段设计

```
阶段 1 · 收集（Collector）
  浏览器启动 → 注册 response 监听器
  你手动浏览、点开试卷
      ↓ 每个响应
  looks_like_pdf_response(url, content_type)
      ↓ 命中就记进内存（不下载）
  {path 归一化后的 URL}
      ↓ 关浏览器后
  扫描所有页面的 <a href> / <iframe src> 补充遗漏
      ↓
  候选列表

阶段 2 · 下载（download_all）
  复用同一 context 的 cookie
      ↓ 逐个 request.get()
  is_real_pdf(body)  ← 校验 %PDF 文件头
      ↓ 通过才存
  存盘（重名自动加序号）
```

### 为什么要「收集」和「下载」分两步

原版（本仓库 v1）是「监听响应即保存」：每点开一份试卷，整个 PDF 立刻写盘。问题是你必须**等它传完**才能点下一份 —— 一份 20MB 的试卷在慢网络上要等十几秒。点 30 份就是十分钟的纯等待。

两阶段版本把「发现」和「传输」解耦：

- 收集阶段只读响应头（几百字节），点一份是毫秒级
- 你可以两三分钟翻完一门课所有试卷
- 关掉浏览器后，下载在无人值守状态下完成

### 为什么不做「输入课程代码自动发现」

ETD 前端是 SPA（首页只有 2KB 的空壳，内容全由前端异步渲染）。这意味着：

- 课程列表的 DOM 结构**随时可能随前端改版而变**
- 写死 CSS 选择器的方案一改版就彻底失效
- 也无法保证所有课程页面用同一套结构

所以本工具采用**网络层监听 + URL 特征匹配**：不管页面长什么样，只要浏览器真的去取了 PDF，就能被捕获。**服务端换皮肤、前端换框架，都不影响。**

**这是一个刻意的取舍**：放弃了「一键全自动」，换来了「不会因为改版而失效」。

### 三层浏览器兜底

```
msedge  →  chrome  →  playwright 内置 chromium
```

优先用系统浏览器，是因为你的登录态、客户端证书、企业代理配置都在系统浏览器里。**用内置 Chromium 往往要重新走一次完整登录流程。**

### 去重：为什么要归一化 URL

ETD 的 PDF 链接带 `timestamp` / `signature` 参数，**同一份试卷每次打开签名都不同**。如果直接用完整 URL 去重，同一个文件会被下载好几份。

`detector.Candidate.key` 只用 URL 的 path 部分作为去重键（`/browserfile/abc123`），忽略所有 query 参数。这样同一份试卷无论打开几次，只会下载一次。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| **需要手动点开每份试卷** | 脚本不主动遍历课程列表。原因见上：SPA 结构不稳定，宁可慢一点，也不要出一个改版就废掉的工具 |
| **URL 带签名，会过期** | 收集阶段拿到的链接含 `timestamp` / `signature`，过一段时间就失效。`--collect-only` 存下的列表建议尽快用掉 |
| **分片加载的 PDF 收不到** | 如果试卷用 canvas 逐页渲染或分片请求，不会有单个完整的 PDF 响应，本工具无法处理 |
| **只能下载你有权限的** | 完全复用你的登录态，没有任何越权手段 |

---

## 目录结构

```
XJTLU_PDF_Fetcher/
├── main.py                    # 入口
├── run_gui.bat / run_gui.sh   # 双击启动图形界面
├── run_win.bat                # 双击启动命令行模式
├── requirements.txt
├── pdf_fetcher/
│   ├── config.py              # 所有可调参数
│   ├── detector.py            # PDF 识别 / 文件名处理（纯函数）
│   ├── storage.py             # 落盘与重名处理
│   ├── collector.py           # 两阶段核心（收集 + 下载）
│   ├── gui.py                 # Tkinter 图形界面
│   └── cli.py                 # 命令行
└── tests/
    ├── test_core.py           # 49 项纯逻辑测试（无需浏览器）
    ├── test_integration.py    # 12 项端到端测试（本地 HTTP 服务）
    └── test_gui.py            # 26 项界面测试（需 tkinter）
```

设计上把**所有能纯函数化的逻辑都抽出来了**（`detector.py` / `storage.py`），所以大部分行为可以不起浏览器就验证。GUI 通过消息队列与后台线程通信 —— Tkinter 不是线程安全的，所有界面更新都必须在主线程做。

---

## 测试

```bash
python tests/test_core.py         # 49 项纯逻辑，秒级
python tests/test_integration.py  # 12 项端到端，本地起 HTTP 服务
python tests/test_gui.py          # 26 项界面测试，需要 tkinter
```

当前状态：**49 + 12 + 26 全部通过**。

> `test_gui.py` 在缺少 tkinter 的环境（部分精简版 Python）会自动跳过，并明确提示跳过原因，不会伪装成通过。

集成测试用本地 HTTP 服务模拟了四种真实响应形态：

- `browserfile` 签名 URL + RFC5987 中文文件名
- 标准 `Content-Disposition: filename=`
- **伪装成 `application/pdf` 的 HTML**（验证 magic bytes 拦截生效）
- 404

---

## 排查

**收集不到任何 PDF？**

```bash
python main.py -v
```

看被跳过的响应数量。如果跳过了很多但一个没收到，说明识别规则不匹配 —— 在 `pdf_fetcher/config.py` 的 `url_keywords` 里加上 URL 中的特征字符串。

**下载全部失败？**

链接可能已过期，重新跑一次收集。

**提示浏览器启动失败？**

```bash
playwright install chromium
```

**Windows 上中文文件名乱码？**

`main.py` 已处理 stdout 编码。如果仍有问题，用 `chcp 65001` 切到 UTF-8 代码页。

---

## 致谢

两阶段收集的思路受 [kevinlasnh/xjtlu-final-paper-pdf-downloader](https://github.com/kevinlasnh/xjtlu-final-paper-pdf-downloader) 启发（同校同学的项目）。本项目在实现上走了不同路线：用网络层特征匹配替代 DOM 解析，用两阶段解耦替代自动遍历。代码为独立实现。

---

## 代码签名政策（Code signing policy）

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- **构建来源**：所有 Windows 产物（`XJTLU_PDF_Fetcher.exe`）均由本仓库的 GitHub Actions 工作流 `.github/workflows/build-release.yml` 从公开源码自动构建，不接受手工上传的二进制。
- **签名者**：证书发布者为 SignPath Foundation（开源免费计划），私钥存放在其 HSM 中。
- **审批流程**：每个 Release 的签名请求由仓库维护者（@Zephyr-Song）在 SignPath 门户中人工审批一次。
- **账号安全**：SignPath 账号与本 GitHub 账号均启用双因素认证（2FA）。
- **隐私**：本工具不向任何服务器上报用户信息；它唯一的网络行为就是你本人访问 ETD 页面与下载你本人有权访问的试卷。

---

## 许可

MIT。使用本工具产生的一切后果由使用者承担，作者不对任何违反学校规定的行为负责。
