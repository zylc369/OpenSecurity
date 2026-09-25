# 浏览器自动化 — 启动 / 登录 / 接管 / 确认

> 需要打开网页、登录平台、自动化 Chrome 行为、远程执行 JS、确认操作结果时使用。
> 浏览器启动的技术实现全库只保留本文档一处，其他文档只做策略性引用。

---

## 1. 浏览器启动（技术唯一权威处）

### 1.1 启动铁律

- **打开网页做交互操作（登录、填表、浏览、需要用户看到过程）→ 必须用 `$AGENT_DIR/scripts/browser_cdp.py` 启动独立 Chrome，再 `connect_over_cdp` 接管**。浏览器对用户始终可见：agent 操作过程可被观察监督，卡住时用户可直接看到卡在哪一步并介入
- **Playwright `launch(headless=True)` 只用于纯后台任务**（批量截图/渲染/探测——无交互、无观察需求）
- 禁止 Playwright `launch`/`launch_persistent_context` 启动有界面浏览器——launch 的浏览器是脚本子进程，脚本退出或 shell 会话中止即被连坐关闭，用户正看着的窗口会突然消失
- 禁止平台专属命令（macOS `open -na`、`nohup ... &` 等）临场启动——`nohup` 不脱离进程树，父会话中止仍会连坐

### 1.2 browser_cdp.py 用法

```bash
# 启动（成功后 stdout 末行输出 {"pid": N, "port": P, "profile": DIR, "reused": bool}）
python $AGENT_DIR/scripts/browser_cdp.py start [--url URL] [--port 9222] [--profile DIR] [--browser PATH]

# 仅探测 CDP 端口
python $AGENT_DIR/scripts/browser_cdp.py probe [--port 9222]
```

| 参数 | 说明 |
|------|------|
| `--url` | 启动后打开的 URL（如登录页） |
| `--port` | CDP 调试端口，默认 9222 |
| `--profile` | user-data-dir。默认每次独立时间戳目录（防实例冲突）；传固定目录可跨次复用登录态 |
| `--browser` | 显式指定 Chrome 可执行文件（覆盖探测链）；也可用 env `BROWSER_CDP_CHROME` |

退出码：`0` 成功/复用 ｜ `2` 找不到 Chrome（提示 `python -m playwright install chromium`）｜ `3` 进程启动即退（stderr 已落盘到 `<profile>/browser_stderr.log` 并回显）｜ `4` CDP 端口 15s 未就绪（常见原因：user-data-dir 与已运行 Chrome 实例冲突）

### 1.3 内部机制（无脚本环境时手动执行等效流程）

**三级 Chrome 探测链**（每级找不到才进入下级）：

| 级 | 来源 | 平台与路径 |
|----|------|-----------|
| 1 | `--browser` 参数 / env `BROWSER_CDP_CHROME` | 显式指定 |
| 2 | 系统安装 | macOS: `/Applications/Google Chrome.app`（含 Beta、Chromium）；Windows: `Program Files`/`Program Files (x86)`/`LocalAppData` 下 `chrome.exe`；Linux: `which google-chrome/chromium/chromium-browser` |
| 3 | Playwright 缓存目录 glob | macOS: `~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/...`；Linux: `~/.cache/ms-playwright/chromium-*/chrome-linux/chrome`；Windows: `%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win*\chrome.exe`（glob 模式用 `chromium-*` 避免误匹配 `chromium_headless_shell-*`；按版本号降序取最新） |

**脱离进程启动**（浏览器不随父 shell 会话中止而关闭）：

```python
import subprocess
# POSIX（macOS/Linux）: 脱离进程组
subprocess.Popen(cmd, start_new_session=True, stdout=err_f, stderr=err_f, close_fds=True)
# Windows: 脱离 Job Object
subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
```

固定参数：`--remote-debugging-port=<port> --user-data-dir=<profile> --no-first-run --no-default-browser-check`。

**四段成功判定**（顺序执行）：

1. 启动前探测 `GET http://127.0.0.1:<port>/json/version`——已可达则**复用现有实例**，不再启动（同端口重复启动是常见错误）
2. 启动后 1.5s `proc.poll()`——进程立即退出则读 `<profile>/browser_stderr.log` 报错
3. 轮询 `/json/version`（最长 15s）——返回 200 且 JSON 含 `Browser` 字段即就绪
4. 超时且进程仍活——user-data-dir 与已有 Chrome 实例冲突（新进程把 URL 转发给旧实例后不开调试端口），换独立 `--profile` 或 kill 冲突进程

### 1.4 执行模式对比

| 模式 | 启动/连接 | 定位 |
|------|-----------|------|
| A: Playwright 直接启动 | `launch(headless=True)` | 纯后台任务——批量截图/渲染/探测，脚本内闭环，退出自动清理 |
| B: 独立进程 + CDP 接管 | `browser_cdp.py start` + `connect_over_cdp` | 网页交互操作——用户可见可监督可介入，登录态跨脚本存活 |

**选型: 网页交互（登录/表单/需要观察）一律 B（§1.1 铁律）; 纯后台批量任务用 A。**

- 模式 A 的 `channel="chrome"` 按平台自动定位系统 Chrome; 选系统 Chrome 而非自带 Chromium 的原因: 后者缺 Widevine/专有编解码器等组件，指纹易被环境评分识别
- 模式 B 的登录态复用: `--profile 固定目录` 跨次保留 cookie/localStorage
- CDP API 与接管代码模板见 §5; 登录完成判定见 §2

---

## 2. 登录决策树

登录需求出现 → 默认走有界面独立浏览器（§1.1 铁律），全程对用户可见：

```
├─ Default: browser_cdp.py 启动 → connect_over_cdp 接管 → 自动定位表单填表提交
│    UI 输入框接受任何用户可输入的值（规避 API 层格式校验/凭证猜测坑），真实浏览器环境下人机验证多数不触发；用户全程可见，随时可介入
├─ 升级 1: 人机验证出现且 10s 未自动通过 → 同一浏览器内点击验证组件（操作细节见 §3）
├─ 升级 2: 交互挑战卡死 / 缺少只有用户知道的凭证
│    → 请用户在同一浏览器完成登录/验证，完成后 agent 接管继续（登录态已就位）
└─ 定位: API 逆向服务于登录后的程序化操作（表单提交/批量查询），不作为完成登录的手段；禁止为"完成登录"逆向前端超过 5 轮
```

登录完成判定: 轮询 `page.url`——回到目标域且脱离认证路径（`/auth`、`/login` 等）即成功，60s 超时按决策树升级。

---

## 3. 人机验证: 两类机制勿混淆

| 类型 | 机制 | 应对 |
|------|------|------|
| Cloudflare 环境评分（被动） | 无可见组件，jsd 脚本采集行为/环境 | 真实浏览器（§2 Default 的 browser_cdp.py 启动; 若纯后台任务则 A 模式加 `channel="chrome"`）+ 正常操作节奏，多数不触发; 触发 → 升级 1 |
| 服务端 CAPTCHA 路由（主动） | 后端在特定端点强制校验验证 token | **不可自动绕过**（siteverify 真实验证）; 换不受保护的路径（如用已有账号登录而非注册），或升级 2 |

- **先查再选路径**: 查平台 CAPTCHA 配置端点（常见 `GET <api>/captcha` 或 `/site/config`，`routes` 字段列出受保护端点）——先知道哪些端点受保护再选路径，而不是撞上再绕
- **升级 1 操作**: 检测 = 遍历 `page.frames` 找 `challenges.cloudflare.com`; 交互组件点击 = `frame.query_selector("input[type=checkbox]").click(timeout=3000)`; 10s 未通过 → 升级 2
- **无头行为结论**: `--headless=new` 下 UA 含 `HeadlessChrome` 但**不构成** Cloudflare 拦截依据。`navigator.webdriver`: 手动启动 + CDP 接管时为 `false`，`launch()` 启动时为 `true`（注入自动化标志; Cloudflare 不单看此值）。被拦时排查 IP 信誉/操作节奏或换 headed，而非归咎 UA

---

## 4. 硬信号: 出现即停止技术绕过、升级求助

- sitekey 非 Cloudflare 官方测试密钥族——`1x00000000000000000000AA` 总通过 / `2x00000000000000000000AB` 总阻止 / `3x00000000000000000000FF` 总失败，**其余均为生产密钥**（siteverify 真实验证，伪造 token 路线死路）
- 响应含 `CAPTCHA failed validation`（token 已被服务端拒绝，同上死路）
- 凭证猜测连败 3 次（API 层或 UI 层）——继续猜无收益，直接请用户提供

---

## 5. CDP 核心 API

CDP 是 Chrome 原生的远程调试协议。Playwright 通过 CDP 控制浏览器。

### 常用命令

| 命令 | 用途 | 参数 |
|------|------|------|
| `Debugger.enable` | 启用调试器（**必须**，否则 debug condition 不执行） | 无 |
| `Debugger.disable` | 关闭调试器 | 无 |
| `Runtime.evaluate` | 在页面上下文中执行 JS | `expression`、`includeCommandLineAPI`、`awaitPromise` |
| `Page.navigate` | 导航到 URL | `url` |
| `Page.reload` | 刷新页面 | 无 |

### 关键参数

```python
# Runtime.evaluate 必须设置 includeCommandLineAPI 才能使用 debug() 等控制台 API
cdp.send("Runtime.evaluate", {
    "expression": "debug(myFunction, 'condition'); false",
    "includeCommandLineAPI": True,  # ← 必须！否则 debug() 未定义
})

# 等待 Promise 完成
cdp.send("Runtime.evaluate", {
    "expression": "new Promise(r => setTimeout(r, 1000))",
    "awaitPromise": True,
})
```

### 必须做的事 vs 不要做的事

| 操作 | 原因 |
|------|------|
| ✅ **必须** `Debugger.enable` | 不发送这个命令，`debug(func, "代码")` 中的第二个参数（字符串里的代码）完全不会被执行 |
| ✅ **必须** `includeCommandLineAPI: True` | 在 `Runtime.evaluate` 中使用 `debug()`、`undebug()` 等 Console API 时必须设置，否则报 `debug is not defined` |
| ❌ **不要** `Runtime.enable` | 会触发大量控制台事件涌入，影响性能。你不需要它 |

### 自动 resume 断点

```python
def on_paused(params):
    """调试器暂停时自动恢复"""
    cdp.send("Debugger.resume", {})

cdp.on("Debugger.paused", on_paused)
```

### Playwright 连接 CDP 实例

```python
from playwright.sync_api import sync_playwright

# 浏览器已由 browser_cdp.py 启动（模式 B），或按 §1.3 的脱离进程方式手动启动
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    cdp = page.context.new_cdp_session(page)
    cdp.send("Debugger.enable", {})
    result = cdp.send("Runtime.evaluate", {
        "expression": "1 + 1",
        "includeCommandLineAPI": True,
    })
    # 结束时直接退出 with 块断开连接——禁止 browser.close()（见 §7.6）
```

---

## 6. debug() API 和 debug condition

### API 语法

```javascript
debug(targetFunction, "conditionExpression");   // 设置条件断点
undebug(targetFunction);                        // 移除断点
```

### debug() 能用的前提

`debug()` 不是标准 JavaScript API，而是 Chrome DevTools Console 专属的函数：

| 条件 | 说明 |
|------|------|
| Console 环境 | `<script>` 标签中调用 `debug()` 会报 `ReferenceError`。只有 DevTools Console 里才有这个函数 |
| CDP 中需要 `Debugger.enable` | 不发送这个命令，`debug(func, "代码")` 中的第二个参数里的代码完全不会被执行 |
| CDP 中需要 `includeCommandLineAPI: True` | `Runtime.evaluate` 默认不包含 Console 专属 API，加这个参数才能用 `debug()` |

### 第二个参数里代码的执行规则

| 规则 | 说明 |
|------|------|
| 返回 truthy → 暂停 | Chrome 在目标函数入口暂停执行 |
| 返回 falsy → 不暂停 | 函数正常执行，但第二个参数里的代码**已经执行过了** |
| 副作用一定会执行 | 赋值、自增等操作无论返回值如何都会执行。出题人常利用这个特性在 `debug()` 的字符串参数中隐藏关键逻辑，绕过它就会破坏这些逻辑 |

### 嵌套 debug 调用会被抑制

如果函数 A 的 `debug()` 第二个参数里的代码执行过程中，又触发了另一个被 `debug()` 插桩的函数 B，Chrome 可能会跳过 B 的 `debug()` 执行。这是 Chrome 的行为，不是 bug。当自动化结果和手动操作不一致时，检查是否存在这种嵌套调用。

---

## 7. 常见陷阱

### 7.1 修改 HTML 后 CSP 哈希不匹配

当 HTML 文件使用 `script-src 'sha256-xxx'` CSP 时，修改脚本内容会导致哈希不匹配，浏览器拒绝执行脚本。

**解决**：去掉 CSP 的 content 属性或更新哈希值。详见 `$AGENT_DIR/knowledge-base/csp-bypass.md`。

### 7.2 Headless 模式下行为差异

headless 模式下定时器调度、CPU 节流等行为可能与有头模式不同。如果自动化脚本的结果和手动操作不一致，换有界面浏览器复现（§1.1 铁律启动，用户也可同步观察）。

### 7.3 Console API 不等于普通 JS

`debug()`、`undebug()`、`monitor()`、`copy()` 等 Console API 只在 DevTools Console 环境中可用，`<script>` 标签里调用会报 `ReferenceError`。通过 CDP 的 `Runtime.evaluate` 使用这些函数时需要加 `includeCommandLineAPI: True`。

### 7.4 Page reload 后状态丢失

`page.reload()` 会清除所有 `debug()` 设置和 JavaScript 状态。需要在 reload 后重新设置 debug condition。

### 7.5 接管期间用户关闭页面

模式 B 接管后，用户可能随手关闭标签页——后续 Playwright 操作抛 `TargetClosedError`。**catch 后 `context.new_page()` 重开页面继续**，不要中断整个流程；也不要因此误判浏览器死亡（浏览器主进程还在，`/json/version` 仍可达）。

### 7.6 connect_over_cdp 后禁止 close

`browser.close()` 会关闭**用户的浏览器**（模式 B 的浏览器承载着用户的手动登录态）。正确做法：**退出 `with` 块即自动断开连接**，浏览器保持运行。只有确认无人接管、由自己启动的浏览器才允许清理（`kill <pid>`）。

---

## 8. 操作后确认方法论

提交类操作（flag 提交、表单发送、状态变更）的结果确认，按操作时序执行，持久信号优先于瞬态信号：

```
0. 提交前（预备）:
   - 挂 page.on("response") 监听（零成本，提交响应体是第一权威信号）
   - 保存页面 DOM 文本快照（供提交后 diff）
1. 提交后第一步——前后对比读页面反馈（不预设反馈形态与用词）:
   - 重新获取页面 DOM 文本（必要时先刷新，部分平台的完成标志刷新后才渲染）→ 与快照 diff → 对差异区域做语义判断。倒计时/计数器等自然变化是噪音，语义上排除即可
   - 反馈用什么词、什么语言不重要，读得懂语义即可
2. 页面无反馈（无差异或差异无语义）→ 读监听到的提交响应体
3. 仍无法确认 → API 直调重放确认（注意归因边界与代价）:
   - CDP 提取 cookie 直调提交端点，按响应语义判断——常见形态: 幂等再次成功、already-solved/duplicate 类响应、错误 flag 响应
   - 归因边界: 队制平台 "already solved" 只能证明账号/队伍已解出，不能证明上一次提交本身成功（解出可能来自队友）
   - 代价: 若上次实际失败，重放会再记一次提交（错误计数/限流），有提交次数限制的平台慎用此步
```

**禁止把 toast 作为确认手段**——toast 数秒即逝，轮询时机不可控，是最不可靠的信号源; 不同平台反馈机制不同（toast/行内文字/状态图标/无反馈），提交后先观察页面实际反馈机制，不要预设 toast 选择器。

### API 直调修正链（登录态接口 401/400 逐层修正）

```
401 UNAUTHORIZED → 补请求头: Cookie(session) + Origin + Referer + 框架标识头（如 tRPC 系加 x-trpc-source: http）
400 参数错误     → 读错误体中的参数 schema 提示改参数——tRPC/zod 系 400 错误体直接列出缺失字段名与 path（如 [{"path":["slug"],"message":"Required"}]），把错误体当 API 文档读，不要盲猜参数名
200/4xx 语义     → 响应体中的状态字段/错误消息即权威结论
```

### 提交探测的代价分级

| 探测手段 | 代价 | 适用 |
|---------|------|------|
| 空参数/格式错误参数 | 无提交记录（多数平台进不到提交逻辑） | 探测端点存在性与参数 schema 的首选 |
| 错误 flag | 记一次错误提交（部分平台限次/扣分） | 仅当真实 flag 只有一次机会、必须先验证端点/参数时 |
| 真实 flag | 正式提交 | 确认完毕后 |

## 9. 目标侧 CDP/WebDriver 端口暴露攻击面

> 本文件其余章节是"我方"自动化; 本节是被测服务内部的 automation 端口——同一套协议从攻击侧看是权限边界突破口。

**形态**: 渲染/截图/html-to-image 类服务在容器内跑多个 Chromium 实例——低权限渲染实例执行用户提交的 HTML/JS，另有 loopback 上的高权限实例供内部操控（ChromeDriver `--port=38560+N` 或 CDP `--remote-debugging-port`），启动参数常见 `--allowed-origins='*'` 甚至 `--disable-web-security` + 允许 `file://`。

**利用链**: 用户 JS 在低权限实例内 `fetch('http://127.0.0.1:PORT/status')` 扫 loopback 端口段（端口=基地址+种子 mod 8 一类窄窗口，如 38560-38567; ChromeDriver `/status` 回 `ready:true`）→ 直接 `POST /session` 在**高权限实例**开新会话（WebDriver over HTTP 无鉴权，通配 origin 放行跨源）→ `POST /session/{id}/url` 导航 `file:///` 读宿主文件 → `/session/{id}/source` 拿页面源码——权限以"被控实例"为准，随机文件名/Unix 权限对 WebDriver 视角全部透明。单页有渲染时限时用**多页面拆分**: 每页 JS 只同步执行一条 WebDriver 命令，N 页接力完成整个会话操作。

**像素 codeword 信道**（输出是图像、无文本回传时）: 把要回传的比特/字符编码为**灰度亮度条**（每字符一根条，亮度档间隔 ≥10/255，取条中心像素采样，相邻条靠中心采样+足够条宽区分边界），渲染进结果图; JPEG 有损压缩下单色条内中心像素漂移 ≤2 档，nearest-codeword 解码零误差。比 OCR 可靠（无字形歧义）、比逐像素二值化抗压缩。收发两侧约定: 条宽 ≥8px、以已知终止符/已知明文字符收尾作对齐校验。

**审计清单**: 服务容器内 `127.0.0.1` 端口段是否有 ready 状态的 automation 端点; 启动参数含 `allowed-origins`/`remote-debugging`/`disable-web-security`; 渲染实例与内部实例是否共享 network namespace; 用户 JS 可达 loopback 即视为同暴露。
