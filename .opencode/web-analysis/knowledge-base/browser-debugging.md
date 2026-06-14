# 浏览器调试与自动化 — CDP / Playwright / DevTools API

> 需要自动化 Chrome 行为、远程执行 JS、控制调试器时使用。

---

## 1. Chrome DevTools Protocol (CDP) 核心 API

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
    "awaitPromise": True,  # 等待 Promise resolve 后返回
})
```

### 必须做的事 vs 不要做的事

| 操作 | 原因 |
|------|------|
| ✅ **必须** `Debugger.enable` | 不发送这个命令，`debug(func, "代码")` 中的第二个参数（字符串里的代码）完全不会被执行 |
| ✅ **必须** `includeCommandLineAPI: True` | 在 `Runtime.evaluate` 中使用 `debug()`、`undebug()` 等 Console API 时必须设置，否则报 `debug is not defined` |
| ❌ **不要** `Runtime.enable` | 会触发大量控制台事件涌入，影响性能。你不需要它 |

---

## 2. Playwright + CDP 自动化模式

### 连接已有 Chrome 实例

```python
from playwright.sync_api import sync_playwright

# 1. 启动 Chrome（带远程调试端口）
import subprocess
chrome_proc = subprocess.Popen([
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "--remote-debugging-port=9222",
    "--no-first-run",
])

# 2. Playwright 连接
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    cdp = page.context.new_cdp_session(page)

    # 3. 使用 CDP
    cdp.send("Debugger.enable", {})
    result = cdp.send("Runtime.evaluate", {
        "expression": "1 + 1",
        "includeCommandLineAPI": True,
    })
    print(result)  # {'result': {'type': 'number', 'value': 2}}
```

### 自动 resume 断点

```python
def on_paused(params):
    """调试器暂停时自动恢复"""
    cdp.send("Debugger.resume", {})

cdp.on("Debugger.paused", on_paused)
```

### 使用 Playwright 内置 Chromium

```python
# 如果不需要系统 Chrome，可用 Playwright 自带的 Chromium
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    cdp = context.new_cdp_session(page)
```

---

## 3. debug() API 和 debug condition

### API 语法

```javascript
// 设置条件断点
debug(targetFunction, "conditionExpression");

// 移除条件断点
undebug(targetFunction);
```

### debug() 能用的前提

`debug()` 不是标准 JavaScript API，而是 Chrome DevTools Console 专属的函数。要让 `debug()` 可用，需要满足以下所有条件：

| 条件 | 说明 |
|------|------|
| Console 环境 | `<script>` 标签中调用 `debug()` 会报 `ReferenceError`。只有 DevTools Console 里才有这个函数 |
| CDP 中需要 `Debugger.enable` | 不发送这个命令，`debug(func, "代码")` 中的第二个参数里的代码完全不会被执行 |
| CDP 中需要 `includeCommandLineAPI: True` | `Runtime.evaluate` 默认不包含 Console 专属 API，加这个参数才能用 `debug()` |

### 第二个参数里代码的执行规则

| 规则 | 说明 |
|------|------|
| 返回 truthy → 暂停 | Chrome 在目标函数入口暂停执行 |
| 返回 falsy → 不暂停 | 函数正常执行，但 `debug()` 第二个参数里的代码**已经执行过了** |
| 副作用一定会执行 | 第二个参数里的赋值、自增等操作无论返回值如何都会执行。出题人常利用这个特性在 `debug()` 的字符串参数中隐藏关键逻辑，绕过它就会破坏这些逻辑 |

### 嵌套 debug 调用会被抑制

如果函数 A 的 `debug()` 第二个参数里的代码执行过程中，又触发了另一个被 `debug()` 插桩的函数 B，Chrome 可能会跳过 B 的 `debug()` 执行。这是 Chrome 的行为，不是 bug。当自动化结果和手动操作不一致时，检查是否存在这种嵌套调用。

---

## 4. 常见陷阱

### 4.1 修改 HTML 后 CSP 哈希不匹配

当 HTML 文件使用 `script-src 'sha256-xxx'` CSP 时，修改脚本内容会导致哈希不匹配，浏览器拒绝执行脚本。

**解决**：去掉 CSP 的 content 属性或更新哈希值。详见 `$AGENT_DIR/knowledge-base/csp-bypass.md`。

### 4.2 Headless 模式下行为差异

headless 模式下定时器调度、CPU 节流等行为可能与有头模式不同。如果自动化脚本的结果和手动操作不一致，优先用 `headless=False` 排查。

### 4.3 Console API 不等于普通 JS

`debug()`、`undebug()`、`monitor()`、`copy()` 等 Console API 只在 DevTools Console 环境中可用，`<script>` 标签里调用会报 `ReferenceError`。通过 CDP 的 `Runtime.evaluate` 使用这些函数时需要加 `includeCommandLineAPI: True`。

### 4.4 Page reload 后状态丢失

`page.reload()` 会清除所有 `debug()` 设置和 JavaScript 状态。需要在 reload 后重新设置 debug condition。
