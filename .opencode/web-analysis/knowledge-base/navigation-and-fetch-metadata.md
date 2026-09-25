# 导航类型与请求元数据 — Sec-Fetch-* 判定、历史回退重发与 BFCache

> 分析依赖"请求是什么方式发起的"（浏览器发起 vs 脚本发起）、历史回退/前进是否会重新发请求、缓存是否拦截回退时用这条。触发词：Sec-Fetch-Site、Sec-Fetch-Dest、Sec-Fetch-User、none、history.back、go(-1)、BFCache、no-store、重定向继承。

---

## 1. 触发条件（什么时候用这条）

- 目标用 `Sec-Fetch-Site` / `Sec-Fetch-Dest` 等请求头做校验（如要求 `none` + `document`）；
- 需要判断某个导航动作会产生什么 `Sec-Fetch-*` 值；
- 需要判断历史回退/前进是否真的重新发请求、请求带什么头；
- 分析依赖 BFCache 是否命中（回退零请求 vs 真实重发）。

## 2. Sec-Fetch-* 体系

浏览器自动附加，页面脚本无法伪造或修改（受保护头）。常用四个：

| 头 | 取值 | 含义 |
|---|---|---|
| `Sec-Fetch-Site` | same-origin / same-site / cross-site / none | 发起方与目标的站点关系；`none` = 没有页面发起者（浏览器自身发起） |
| `Sec-Fetch-Dest` | document / iframe / script / fetch 等 | 请求的目标类型 |
| `Sec-Fetch-Mode` | navigate / no-cors / cors 等 | 请求模式 |
| `Sec-Fetch-User` | `?1` | 是否用户激活触发的导航 |

站点关系不含端口（同 host 不同端口 = same-site）。

## 3. none 的产生条件

`Sec-Fetch-Site: none` 只出现在"没有页面发起者"的导航：

- 地址栏输入、点击书签、外部程序打开；
- **历史回退/前进**产生的重新请求；
- 自动化浏览器侧导航（CDP `Page.navigate` / Puppeteer `goto()`）。

规则：

- **重定向继承**：跟随 3xx 的后续请求保持原导航的 `Sec-Fetch-Site`（goto 后跟 302 仍是 `none`）；
- **脚本发起的导航拿不到 `none`**：`location.href = ...`、`window.open()`、表单提交、`meta refresh`、`location.reload()` 都带站点关系值（same-origin / same-site / cross-site）；
- `none` 描述"发起方式"，与请求哪个网址无关：同一网址，刷新带 `same-origin`，回退带 `none`。

## 4. 各导航方式的判读表

| 导航方式 | Sec-Fetch-Site |
|---|---|
| Puppeteer `goto()`（浏览器侧） | none |
| goto 后跟 302 重定向 | none（继承） |
| `location.href = ...` | same-origin / cross-site |
| `window.open()`（含 noopener/noreferrer） | same-site / cross-site |
| 表单提交（GET/POST） | cross-site |
| HTTP `Refresh` / `<meta refresh>` | cross-site（同站跳转 same-site） |
| `location.reload()` | same-origin |
| sandbox iframe（透明源）内发起的导航 | cross-site |
| about:blank 弹窗再导航 | same-origin（继承 opener） |
| 历史回退（满足第 5 节条件时） | none |

复跑基线见 `$AGENT_DIR/scripts/probe-navigation/README.md`（探针脚本与判据）；跨版本引用先复跑。

## 5. 历史回退什么时候真正重新发请求

回退/前进不必然产生网络请求：

- **BFCache 命中**：整页从内存恢复，零请求（页面被冻结后原样复活）；
- **BFCache 未命中**：回退变成一次真实网络请求，带 `Sec-Fetch-Site: none` + `Sec-Fetch-Dest: document`（"浏览器发起"的顶层文档导航特征）。

影响命中的状态要素（设计实验时逐项覆盖）：

- 页面是否带 `Cache-Control: no-store`；
- 页面是否开过弹窗、是否有中间导航（如 about:blank）；
- 其他 BFCache 排除条件（未关闭的连接、未提交的表单等）。

## 6. no-store 与 BFCache 的版本条件

- 常规行为：带 `Cache-Control: no-store` 的页面不进 BFCache（也不进 HTTP 缓存），回退时重新请求；
- Chrome 放宽（自 116 起分阶段放量，134/135（2025-03/04）全量）：满足条件时可进 BFCache 并可恢复。条件：HTTPS 页面；无 cookie/授权状态变更（变更即 evict）；页面未使用 WebSocket/WebTransport/WebRTC；无返回 no-store 的 fetch/XHR。仅 Chrome；企业策略 `AllowBackForwardCacheForCacheControlNoStorePageEnabled` 可禁用；
- 条件不满足（含 HTTP 页面）仍按常规行为：回退重新发请求；
- 该行为直接影响"回退是否重发"的结论，使用前先在目标浏览器上复跑探针。

## 7. 检查方法

1. 起一个本地 HTTP 服务，把每个请求的方法、路径、`Sec-Fetch-*`、`Cookie` 头打印出来；
2. 用无头浏览器构造导航链：navigate 到页面，需要时构造历史（中间页 / about:blank），再 `history.back()` / `history.go(-1)`；
3. 判据：对照第 4 节判读表；回退是否有请求、带什么头，以服务端收到的记录为准（不靠前端推测）。

## 8. 边界与未测清单

- 仅覆盖 Chromium 行为；Firefox/Safari 对 `none` 的产生条件与 BFCache 策略不同；
- 版本升级后基线可能变化（第 4、6 节的值以复跑为准）；
- `Sec-Fetch-Site` 只描述发起方式、不携带身份：任何非浏览器客户端可直接伪造这些头，服务端不应将其作为认证依据；
- 未测清单：非 Chromium 内核、Service Worker 介入下的回退行为、跨源 opener 场景的遍历取值。
