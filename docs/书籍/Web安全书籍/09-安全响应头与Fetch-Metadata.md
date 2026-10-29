# 09 安全响应头与 Fetch Metadata

> **本章一句话**：服务器通过响应头把一整套防护指令交给浏览器执行；其中 **Fetch Metadata**（`Sec-Fetch-*` 系列）是一组"请求来源声明"，让服务器能区分"用户主动导航"与"页面脚本发起"。

## 9.1 全景表：一个响应里的安全头逐个读

本例响应里出现的头（大多来自 `helmet` 的默认配置，应用代码只写了一行注册）：

| 头 | 值 | 作用 | 在本例中的存在感 |
|----|----|------|----------------|
| `Cross-Origin-Opener-Policy` | `same-origin` | 跨源弹窗的遥控器折断（06 章） | 封死"用弹窗给审查页发消息" |
| `Cross-Origin-Resource-Policy` | `same-origin` | 别的网站加载本页**资源**（script/img/fetch）会被浏览器拦下 | 封死"把页面当脚本加载" |
| `X-Frame-Options` | `SAMEORIGIN` | 不许别的网站把本页嵌进 iframe | 封死"嵌进 iframe 读数据" |
| `Origin-Agent-Cluster` | `?1` | 请求浏览器对同一来源页面做更严格的进程隔离 | 基础防护，无直接攻击故事 |
| `Referrer-Policy` | `no-referrer` | 发请求时不带 `Referer` 头（防 URL 泄漏给第三方） | 基础防护 |
| `Strict-Transport-Security` | `max-age=...` | HSTS：强制该域走 HTTPS（只在 HTTPS 响应上有效） | 基础防护 |
| `X-Content-Type-Options` | `nosniff` | 禁止 MIME 嗅探：响应内容必须按声明的类型处理 | 防"当脚本加载"的辅助 |
| `X-DNS-Prefetch-Control` | `off` | 关闭 DNS 预取 | 隐私类默认值 |
| `X-Download-Options` | `noopen` | 旧 IE 时代防下载后直接打开 | 历史遗留 |
| `X-Permitted-Cross-Domain-Policies` | `none` | 禁止 Flash/PDF 时代的 crossdomain.xml 策略文件 | 历史遗留 |
| `X-XSS-Protection` | `0` | **显式关闭**老旧浏览器自带的 XSS Auditor（现代最佳实践：它弊大于利） | 注意："0"代表关闭，不是开启 |
| `Content-Security-Policy` | 各页面不同 | 资源与脚本白名单（08 章） | 预览页严格、渲染页没有 |
| `Vary` / `Cache-Control` / `ETag` | —— | 缓存控制（10 章） | —— |

**读头=读防线设计图**。实战练习：拿到一个目标的响应头，可以反推它做没做这些防护——

| 看到的头 | 推断 |
|---------|------|
| `X-Frame-Options` / `frame-ancestors` | 开发者考虑过"被嵌入"风险 |
| `COOP: same-origin` | "弹窗跨源通信"这条路被主动砍掉 |
| `CORP: same-origin` | 资源不许被别的网站引用 |
| `CSP` 且无 `unsafe-inline` | 内联脚本注入会被拦，需要 nonce/哈希类突破口 |
| 没有上述任何一个 | 这些攻击面全部开放 |

## 9.2 Fetch Metadata：请求的"来源声明"

浏览器在**每个请求**上自动附加一组 `Sec-Fetch-*` 请求头，声明"这个请求是怎么产生的"：

| 头 | 声明什么 | 常见值 |
|----|---------|--------|
| `Sec-Fetch-Site` | 请求发起方与目标"什么关系" | `same-origin` / `same-site` / `cross-site` / `none` |
| `Sec-Fetch-Dest` | 这个请求"要拿什么类型的东西" | `document` / `iframe` / `script` / `image` / `empty`（fetch/XHR） |
| `Sec-Fetch-Mode` | 请求模式 | `navigate` / `cors` / `no-cors` / `same-origin` |
| `Sec-Fetch-User` | 导航是否被浏览器视为"用户发起" | `?1`（地址栏、书签、历史回退等浏览器发起型导航——脚本调用的 `history.go()` 回放也算） |

四个关键性质：

1. **由浏览器自动填写**，属于"禁止修改的请求头"（forbidden header）——页面 JavaScript **碰不到它**：写不了也改不了（在 `fetch` 里硬塞会被忽略）。这是它能当安全依据的根本原因：服务器读到的必然是浏览器的话，不是攻击者代码的话。
2. **它声明"关系"，不声明"地址"**：`none` 只说"这个请求没有页面来源"，不说"我是谁"。所以它不会破坏"无国籍页面"的匿名性（05 章）——只泄露"我和你近不近"，不泄露"我具体是谁"。
3. **检查动作 100% 在服务器端**：浏览器只负责如实上报；读头、比对、决定放行还是 403，全是服务器代码。
4. **服务端检查示例**（本例渲染分支的守门函数）：

```javascript
function policy(req) {
  return Object.entries({
    "sec-fetch-site": "none",       // 要求：请求没有页面来源（用户直接操作级）
    "sec-fetch-dest": "document",   // 要求：拿的是整页文档（不是脚本/图片/fetch）
  }).every(([header, expected]) => req.get(header) === expected);
}
```

## 9.3 Sec-Fetch-Site 的取值与"none 的唯一路径"

| 值 | 什么时候出现 |
|---|-------------|
| `same-origin` | 发请求的页面与目标同源（脚本跳转、同源 fetch/img） |
| `same-site` | 同一注册域的不同子域之间 |
| `cross-site` | 从别的网站发起（跨站 fetch、别的网站嵌你的资源、无国籍页面的请求） |
| `none` | **用户直接操作**且请求真的发出去：地址栏回车、点书签、外部应用打开、**历史导航且缓存未命中** |

对攻击者最重要的推论：

- 页面脚本发起的跳转（`location.href=...`）永远标 `same-origin` 或 `cross-site`，**标不出 `none`**；
- `Sec-Fetch-*` 又是 JS 改不了的；
- 于是**用代码产生 `none` 的唯一方式**是调用 `history.go()` / `history.back()`——语义上等同于"用户按了后退键"。再叠加一个前提：**目标页必须不在 BFCache 里**（缓存命中时不发请求，头无从产生）——完整公式见 11 章。

## 9.4 服务端检查的真实边界（威胁模型）

| 边界 | 说明 |
|------|------|
| **能挡住"页面脚本"** | JS 无法伪造这组头，所以能有效区分"真人导航"与"脚本跳转" |
| **挡不住非浏览器客户端** | 用 `curl` 直接发包可以任意伪造这组头（本例的复现实验就手工伪造过 `Sec-Fetch-Site: none` 并成功通过检查）——它的威胁模型是"浏览器内的页面代码"，不是"任意 HTTP 客户端" |
| **区分不了"真人回退"与"脚本驱动的回退"** | `history.go()` 产生的请求同样标 `none`。所以它只能证明"这是一次用户操作级导航"，不能证明"用户真的想访问" |
| **只作纵深防御** | 它应该与"一次性令牌、服务端状态检查"配合使用（12 章防御部分） |

## 9.5 其他头的细节补充

- **HSTS**（`Strict-Transport-Security`）：只对 HTTPS 响应生效；一旦被浏览器记下，之后对该域的所有 HTTP 访问会被浏览器强制升级为 HTTPS。部署在纯 HTTP 环境时它是一个空头。
- **`nosniff`**：响应声明的 `Content-Type` 即为最终解释方式。比如服务器把用户上传的文件声明为 `text/html`，浏览器就会当网页渲染——`nosniff` 不能防这个，防它的是"上传内容不直接以危险类型回显"。
- **`X-XSS-Protection: 0`**：看到它不要误读为"没防护"。它是显式关掉一个已废弃的浏览器内置过滤器（该过滤器曾引入旁路问题），现代替代品是 CSP。

## 9.6 易混点

| 混淆 | 正解 |
|------|------|
| `COOP` / `CORP` / `CORS` | 开窗隔离 / 资源加载限制 / 跨源读取授权——名字像，用途各不同 |
| `X-Frame-Options` vs CSP `frame-ancestors` | 新老两代防嵌入手段，作用相同；`frame-ancestors` 支持多来源列表 |
| "Sec-Fetch 头是浏览器用来拦请求的" | 它是**给服务器看的报告**；拦不拦由服务器代码决定 |
| "`X-XSS-Protection: 1` 比 `0` 好" | 现代实践相反：该过滤器已废弃，显式 `0`（关闭）才是推荐配置 |

---

**下一章**：[10 HTTP 缓存与 ETag](10-HTTP缓存与ETag.md)——浏览器为什么"不发请求也能给你看页面"，以及如何让"第二次访问"必然到达服务器。
