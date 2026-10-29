# 05 iframe 与 sandbox

> **本章一句话**：iframe 让一个页面"嵌"另一个页面；加了 `sandbox` 属性后，被嵌页面被**降级关押**——最狠的一招是**没收身份证**（opaque origin，无国籍源），让里面的脚本"能跑，但谁也碰不了、也碰不了谁"。

## 5.1 iframe 是什么：页面里的"小窗口"

```html
<iframe src="/sandbox"></iframe>
```

`<iframe>` 标签在页面里嵌一个小窗口，窗口里装**另一个**网页（可以同站、也可以别的网站）。同一个网页的三种打开方式（后文反复用到）：

| 打开方式 | 是什么 | 谁管它 |
|---------|--------|--------|
| **直接打开**（顶层） | 它就是标签页的主体 | 浏览上下文组（06 章） |
| **iframe 嵌入** | 被别的页面嵌在身体里 | 同源策略 / sandbox 属性 |
| **弹窗** | JavaScript `window.open()` 弹出的新窗口 | 浏览上下文组 / COOP（06 章） |

## 5.2 防止被嵌入：X-Frame-Options 与 frame-ancestors

默认情况下**任何网站都能把你的页面嵌进自己的 iframe**（这就是点击劫持等攻击的基础）。防它的两个头（历史先后关系）：

| 头 | 写法 | 效果 |
|----|------|------|
| `X-Frame-Options`（老） | `SAMEORIGIN` | 只允许同源页面嵌自己，别的网站嵌会被浏览器拒绝加载 |
| CSP `frame-ancestors`（新） | `frame-ancestors 'self'` | 同上，且能写多个来源，功能更细 |

本例的页面两个都配了（分别来自 helmet 默认和 /sandbox 的自定义 CSP）。审计时看到这组头，说明"用 iframe 嵌入读数据"这条路被明确封死。

## 5.3 sandbox 属性与它的令牌

```html
<iframe sandbox="allow-scripts" src="/sandbox"></iframe>
```

`sandbox` 属性的语义是 **"白名单关押"**：**属性里没列出的能力，全部剥夺**。上面这行的含义：小窗口里只保留"运行 JavaScript"一项权利，其余全禁。全部令牌速查（不写=对应能力被禁）：

| 令牌 | 解禁什么 |
|------|---------|
| `allow-scripts` | 运行 JavaScript |
| `allow-same-origin` | 保留真实身份证（见 5.5） |
| `allow-forms` | 填表单并提交 |
| `allow-popups` | `window.open` 开弹窗 |
| `allow-popups-to-escape-sandbox` | 弹出的新窗口脱离沙箱 |
| `allow-top-navigation` | 让整个标签页跳转 |
| `allow-top-navigation-by-user-activation` | 同上，但要求用户真实点过页面 |
| `allow-top-navigation-to-custom-protocols` | 允许整页跳转到自定义协议（`tel:`、`mailto:` 等；Chrome 103+） |
| `allow-modals` | 弹 `alert`/`confirm`/`prompt` 提示框 |
| `allow-downloads` | 触发文件下载 |
| `allow-pointer-lock` / `allow-orientation-lock` / `allow-presentation` | 鼠标锁定 / 锁屏幕方向 / 投屏 |
| `allow-storage-access-by-user-activation` | 用户操作后请求读取第一方存储（Storage Access API） |

在本例中，沙箱只给了 `allow-scripts` 一项——这个"吝啬"是整道防线的关键，下面逐条看后果。

## 5.4 opaque origin：没收身份证

**正常情况**：每个页面有一个源（4.1 的"身份证"）。**被 sandbox 关押且没给 `allow-same-origin` 的 iframe** 里，页面运行 `window.origin` 得到：

```javascript
window.origin   // "null"
```

这就是 **opaque origin（不透明源，俗称"无国籍"）**：即使它加载的明明是目标网站自己的页面，浏览器也把它当作"来历不明的无国籍户"——**它和任何网站都不同源**（包括装载它的父页面）。类比：被关进玻璃房，外面的人看得见它、它也看得见外面，但玻璃房没有地址，它跟谁都不"同区"。

无国籍带来的三个具体后果（每条都在后续攻防中被用到）：

**后果一：读不了"没给它开门"的服务器。** 它发的 `fetch()` 请求照发、服务器照回（第一层不管），但读响应走第二层规则：

- 目标服务器没配 CORS → 浏览器不许它读；
- 服务器配的是白名单回显 → 它带的 `Origin` 是字面量 `null`，而白名单里登记的都是真实域名，**没人登记 null**，所以读不成；
- 只有 `Access-Control-Allow-Origin: *` 的公开 API 它照样能读。

**后果二：它和外面互相读不了（双向的，父页面也不例外）。** 外面任何页面（最直接的是装它的**父页面**）都访问不了它的内容和变量；反过来它也读不到外面。本例的防线核心就靠这条：保存随机暗号（nonce）的页面是父页面，沙箱里的攻击脚本**隔玻璃读不走它**——这就是防线设计者敢把暗号放在页面变量里的底气。

**后果三：它的孩子也是无国籍，而且每个"null"互不相等。** 里面再嵌 iframe，子 iframe 继承关押状态；两个沙箱页面的 `null` 身份彼此也不相等，连沙箱父子之间都互相不可读。

## 5.5 allow-same-origin 与高危组合

`allow-same-origin` 不是"跨源互访令牌"，而是"**不没收真实身份**"：

- iframe 内容**本来就和父页面同源**：加它 → 保留身份 → 父子可完整互访 DOM ✅
- iframe 内容是**跨源页面**：加它只是保留它自己（仍是别人的）身份，与父页面照样互访不了 ❌

**本例故意不给它的原因**：沙箱页与父页面都从目标域加载、本来同源。一旦给了 `allow-same-origin`，攻击脚本就保有目标域身份证 → 与父页面同源 → 直接 `parent.document` 读走暗号、替父页面发请求，"防线立刻被攻破"。所以单令牌 `allow-scripts` 就是刻意把它关成无国籍。

> **高危组合警告**（CSP 规范明文）：`allow-scripts` + `allow-same-origin` 同时给、且 iframe 内容与父页面同源时，脚本既能执行又保有同源身份，可以**摘掉自己 iframe 的 sandbox 属性再重载**，沙箱形同虚设。这对组合不该出现在同源场景。

## 5.6 CSP 响应头版 sandbox：跟着文档走的关押

服务器还可以在**响应头**里写：

```text
Content-Security-Policy: sandbox allow-scripts
```

效果和 iframe 的 `sandbox` 属性一模一样，但**作用范围更广**：iframe 属性只管"被装进 iframe 的页面"；响应头跟着文档本身走，**不管这个页面用什么方式打开**（iframe 里、弹窗里、直接打开）都生效。

这条区别是一整类攻击的生死线。本例用它封死了一条捷径：一个页面的脚本地址可以被弹窗/窗口直接打开——如果关押只写在 iframe 属性上，攻击者绕开 iframe 直接打开它，脚本就恢复真实身份；把 `sandbox` 写进响应头后，**这条页面无论怎么打开都是无国籍**。

## 5.7 Trusted Types：禁止"把字符串当代码"

另一个与沙箱配合的机制是 **Trusted Types**（CSP 的一部分），常见配置：

```text
require-trusted-types-for 'script'; trusted-types 'none'
```

它禁止把**普通字符串**直接当网页/代码塞进页面——`srcdoc`、`innerHTML`、`document.write` 这类"把一段字符串变成 DOM"的写法会被浏览器直接拒绝（除非字符串经过专门的"可信类型"包装，而 `'none'` 表示连包装规则都不许建）。

安全含义：沙箱里的脚本想在内部**再造一个子窗口**时，第一道锁是 CSP 不许加载任何地址（`default-src 'none'`），第二道锁就是 Trusted Types——连"不用地址、直接把 HTML 写进去"这条路也堵死。组合起来是完整的"不许造器官"。

## 5.8 小结：无国籍脚本的能力清单

给一个"运行在 sandbox + 无国籍 + 严格 CSP"环境里的脚本列能力表（本例攻击脚本 S2 的真实处境）：

| 能力 | 状态 | 原因 |
|------|------|------|
| 运行 JavaScript | ✅ | `allow-scripts` |
| 发/收 `postMessage` | ✅ | 消息通信不要求同源（07 章） |
| 读同源数据、读父页面 | ❌ | 无国籍（后果二） |
| 开新窗口 | ❌ | 没给 `allow-popups` |
| 提交表单 | ❌ | 没给 `allow-forms` |
| 让主标签页跳转 | ❌ | 没给 `allow-top-navigation` |
| 弹原生提示框 | ❌ | 没给 `allow-modals` |
| 加载新资源（子 iframe、图片等） | ❌ | CSP `default-src 'none'` |

一句话：它是一个"**能计算、能发信，但看不见、动不了**"的信使——这正是后面攻击要利用的发信能力（`postMessage`）的来源。

## 5.9 易混点

| 混淆 | 正解 |
|------|------|
| iframe 的 `sandbox` 属性 vs CSP 的 `sandbox` 指令 vs CSP `nonce` | 三个不同机制：关押规则 / 跟着文档的关押 / 脚本运行许可证。名字都沾"CSP"，实际作用完全不同 |
| "无国籍 = 没能力" | 脚本照跑、消息照发；被没收的是身份（读和操作），不是执行 |
| "iframe 同源父子本来就不能互操作" | 恰恰相反：不设 sandbox 时同源父子可以**完整互读互改**；是 sandbox 把同源关系打散的 |
| "CSP 的 nonce 和 sandbox 是一回事" | nonce 是"脚本运行许可证"（08 章），sandbox 是"关押规则"；本例沙箱页两个都用了 |

---

**下一章**：[06 弹窗与 COOP](06-弹窗与COOP.md)——窗口之间的关系、以及浏览器如何"折断"跨源弹窗之间的通道。
