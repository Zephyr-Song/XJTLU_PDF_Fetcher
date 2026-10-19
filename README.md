# XJTLU PDF Fetcher

批量下载 XJTLU ETD（Theses and Dissertations Database）里你**有权限访问**的历年试卷 PDF。

> **核心设计：先收集，后批量下载。**
> 你在浏览器里点开试卷页面时，脚本只把 URL 记下来（不下载）；全部点完后关掉浏览器，脚本一次性批量下载。
> 手动操作从「点一份存一份」变成「点一遍、然后走开」。

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

## 用法

### 基本流程（推荐）

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
├── requirements.txt
├── pdf_fetcher/
│   ├── config.py              # 所有可调参数
│   ├── detector.py            # PDF 识别 / 文件名处理（纯函数）
│   ├── storage.py             # 落盘与重名处理
│   ├── collector.py           # 两阶段核心
│   └── cli.py                 # 命令行
└── tests/
    ├── test_core.py           # 49 项纯逻辑测试（无需浏览器）
    └── test_integration.py    # 12 项端到端测试（本地 HTTP 服务）
```

设计上把**所有能纯函数化的逻辑都抽出来了**（`detector.py` / `storage.py`），所以大部分行为可以不起浏览器就验证。

---

## 测试

```bash
python tests/test_core.py         # 纯逻辑，秒级
python tests/test_integration.py  # 端到端，本地起 HTTP 服务
```

当前状态：**49 + 12 全部通过**。

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

## 许可

MIT。使用本工具产生的一切后果由使用者承担，作者不对任何违反学校规定的行为负责。
