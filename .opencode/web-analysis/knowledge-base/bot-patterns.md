# Bot 模式分类与识别

> Bot 快速分类参考。聚焦 **Bot 代码结构分析**和**模式快速识别**。
>
> **详细的分析流程**（攻击面枚举、外泄方式选择、CSP 绕过等）见 `$AGENT_DIR/knowledge-base/web-methodology.md` §1.5。
> **多步骤攻击编排**（popup 存活、轮询模板、控制器页面）见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3。
> **Bot 代码自动化分析**见 `$AGENT_DIR/scripts/bot_analyze.py`。

---

## 1. Bot 代码通用结构

几乎所有 admin bot 共享相同的基础结构（Express + Puppeteer）。Bot 代码的关键差异集中在两个点：
1. **Flag 存储方式**（Cookie vs localStorage vs DOM）
2. **页面数量**（单页 vs 双页）

### 1.1 快速提取关键信息

从 Bot server.js 中按优先级提取：

| 信息 | 搜索关键词 | 用途 |
|------|-----------|------|
| Flag 来源 | `FLAG` / `process.env.FLAG` | 确定 flag 格式 |
| 内部 URL | `CHALLENGE_URL` | 确定 Docker 内部域名 |
| Flag 存储位置 | `setCookie` / `localStorage` / `page.evaluate` | 确定攻击目标 |
| 页面数量 | `browser.newPage()` 调用次数 | 确定是单页还是双页模式 |
| 超时时间 | `timeout` 参数 | 确定攻击时间窗口 |
| 浏览器类型 | `PUPPETEER_EXECUTABLE_PATH` | Docker 中通常是 `chromium`（非 Chrome） |

> 自动化提取工具：`python $AGENT_DIR/scripts/bot_analyze.py <server.js 路径>`

---

## 2. Bot 模式快速分类

### 2.1 识别信号

| 模式 | `newPage()` 次数 | Flag 设置时机 | Flag 位置 |
|------|-----------------|--------------|----------|
| **单页** | 1 次 | `goto(userUrl)` 之前 | Cookie |
| **双页** | 2 次 | `firstPage.close()` 之后（secondPage 中） | localStorage |

### 2.2 攻击策略对照

| 模式 | 核心策略 | 关键约束 |
|------|---------|---------|
| 单页 + Cookie | XSS → `document.cookie` 直接读取 | Cookie httpOnly=false |
| 单页 + localStorage | XSS → `localStorage.getItem()` 直接读取 | 需要知道 key 名 |
| 双页 + localStorage | popup 存活 + 轮询等待 flag 写入 | popup 必须与 flag 同源；sandboxed iframe 需先逃逸 |

> 各模式的详细时间线、利用条件、攻击编排模板见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3。

---

## 3. Bot 代码中的安全决策分析

### 3.1 URL 验证

所有 Bot 都验证 URL 协议（只允许 http/https），但**不限制目标地址**。

**影响**：
- 不能使用 `javascript:` 或 `data:` 协议作为 Bot URL
- 可以使用 `http://internal-service:port` 访问内网服务
- 可以使用 `https://external-server.com/page` 访问外部服务器

### 3.1a Bot 网络位置攻击面盘点（admin bot 题必做）

Bot 与应用同容器/同网络命名空间时，**bot 的网络视角 = 容器内视角**——公网入口的防护（反代加的头、WAF、端口过滤）对 bot 全部无效。逐项盘点:

| 检查项 | 看哪里 | 攻击含义 |
|---|---|---|
| 上游进程直听端口 | `entrypoint.sh`/`docker-compose.yml`——`php -S 127.0.0.1:900x`、gunicorn/uvicorn 多 worker、`node server.js` 等 | 反代（Caddy/nginx）在公网端口追加的 CSP/头/限流**不存在**于直连响应——构造 `http://127.0.0.1:<上游端口>/<反射点>` 让 bot 访问 |
| sidecar 服务 | compose 里的第二、三个 service（redis/memcached/内部 API） | SSRF 型面: bot 可达 `internal-host:port`，应用凭据可能就在环境变量里 |
| host 回环别名 | `localhost` vs `127.0.0.1` vs `host.docker.internal` | cookie/host 隔离差异（localhost 与 127.0.0.1 是不同 origin，cookie 域可能只挂一边） |
| 绑定差异 | `0.0.0.0` vs `127.0.0.1` 监听 | 0.0.0.0 时其他容器也能访问该端口 |

**方法**: 公网端口响应头 vs 直连上游端口响应头逐项 diff（CSP/X-Frame-Options/CORS 差异即突破口）; 目标附件里有 entrypoint.sh 的优先读它——端口清单就是攻击面清单。

### 3.2 httpOnly 设置

演练环境的 flag cookie 常设为 `httpOnly: false`（刻意设计让 XSS 可读）；生产环境鉴权 cookie 应设为 `httpOnly: true`。

### 3.3 Docker 中 Chromium 的 AE 特性

Docker 中系统包版 Chromium 通常不支持 Brotli 压缩，Accept-Encoding 不含 `br`。
这对缓存键匹配至关重要 — 详见 `$AGENT_DIR/knowledge-base/cache-poisoning.md` §7.1 和 `$AGENT_DIR/knowledge-base/nextjs-analysis.md` §4.1。

### 3.4 攻击者可控 Cookie 写入面（cookie 播种 / jar 溢出）

**何时查本节**（满足其一即读）：
- bot 端脚本/预览页出现 `document.cookie = <拼接用户输入>` 的数据流（用户输入被当 cookie 写进浏览器）；
- 提交类功能（配方/配置/表单字段）的值最终成为 bot 浏览器 cookie；
- 服务端 Set-Cookie 出现 `Priority=High/Low`（Chromium 专有属性，涉及 jar 行为）；
- 单次输入可写入 cookie 数量接近或超过浏览器上限（Chromium 180/host）；
- 同一站对同类对象下发的一组 cookie 属性不对称（如 `session` 带 `Priority=High` 而 `role` 不带）——设计意图指纹。

**替换 HttpOnly 的两条路线**：

| 路线 | 前提 | 做法 |
|------|------|------|
| 1 路径 shadowing | 能向 cookie 字符串注入属性（`; path=/x` 未被清洗） | 同名不同 path 的新 cookie 与旧 cookie 并存；请求命中更长 path 时优先发送，服务端取首/末个取决于解析库（Express `cookie` 包取首个）——以目标行为的实际观察为准 |
| 2 jar 溢出驱逐 | 属性注入被清洗（`;`/空格/`=` 被剥离） | 先撑爆 jar 挤掉旧 cookie，再补写同名目标 cookie（见下） |

**Jar 溢出驱逐机制（Chromium）**：
- 每 host 配额 180 条；超过时触发**批量驱逐**——一次清掉最久未用的一批（低水位约 150，之后继续累积，形成 150↔180 锯齿；低水位与批量随版本而异）；
- 驱逐按 Priority 分层（Low → Medium → High），同级按访问时间最久先驱逐；`document.cookie` 写入默认 Medium；
- HttpOnly 不影响驱逐；同名同域同路径的 HttpOnly 不能被 JS 覆盖（非 HTTP API 写入被整体忽略）——所以必须"先驱逐、后补写"；
- 验证方法：Playwright 打开页面执行 `document.cookie = 'role=chief; path=/'` 后读 `context.cookies()`——旧 HttpOnly 值仍在、且未产生新 cookie。

**构造模板（路线 2，目标 cookie 名 `T` 值 `V`）**：

```
写入序列（bot 端逐条执行）：
1..N:  填充 cookie（唯一名 f0..fN-1）
最后 1 条: {T: V}
```

- 填充数使 `现存数 + 写入数 > 上限`（触发驱逐）且目标写入后不被挤出——**目标 cookie 必须放序列末尾**（批量驱逐淘汰最旧项，中间位置会被后续写入或下一轮批量驱逐清掉）；填充数 ≥ 上限 − 现存数 + 1；工程上总写入数常取上限的 1.1~1.7 倍留余量；
- 落地方式随场景：配方/字段数组逐项一条，或循环生成批量字段。

**验证与判断**：
- 成功：目标接口按新角色响应（更高权限内容/flag）；
- 对照组：只写填充（不含目标 cookie）→ 原角色响应——证明差分来自目标 cookie；
- 未生效排查：① 总量未达上限（未触发驱逐）；② 目标写入太早被 LRU 挤出（应放末尾）；③ 服务端角色判定不在 cookie（改查服务端会话）；④ bot 非 Chromium——Firefox 上限 150/域、无 Priority 属性、驱逐策略不同，路线 2 主要针对 Chromium 系（Docker chromium / Puppeteer / Playwright 默认）。

**黑盒复现（无源码时）**：
- 站点若提供"bot 视角预览页"（如 `/review/:id`、`/preview/:id` 形态的路由渲染并执行 bot 端脚本）→ 用自己的会话打开该页，以本地无头浏览器观察 cookie 写入结果与后续请求，避免对线上盲目试发；
- 预览页脚本顺序即 bot 实际执行顺序（播种 → 业务请求），可作为事实基线。

> HttpOnly 的其他旁路（服务端回显、CSRF via XSS）见 `$AGENT_DIR/knowledge-base/xss-advanced.md`「HttpOnly 不是终点」节。

---

## 4. 从 Bot 行为推导攻击链

### 4.1 决策树

```
分析 Bot server.js
│
├── 只有一个 newPage()?
│   ├── 是 → 单页模式
│   │   ├── Cookie 在 goto 前设置? → XSS 读 document.cookie
│   │   └── localStorage 在 goto 前设置? → XSS 读 localStorage
│   └── 否（两个 newPage()）→ 双页模式
│       └── firstPage.goto(userUrl) 是第一个操作?
│           └── 是 → XSS 需要存活到 secondPage 保存 flag
│               ├── XSS 可以开 popup? → popup 存活 + 轮询
│               └── XSS 在 sandbox 中? → 需要先逃逸 sandbox
│
├── 有 setCookie 调用?
│   ├── httpOnly: false? → XSS 可读 document.cookie
│   └── httpOnly: true? → XSS 不可读：CSRF / 服务端回显；可向 bot 浏览器写 cookie 时走 §3.4（shadowing / jar 溢出驱逐）
│
└── CHALLENGE_URL 是什么?
    └── 记录下来 → 这是 Docker 内部域名，用于构造 Bot URL 和缓存键对齐
```

> 完整的攻击流程（信息收集 → 漏洞发现 → 利用构造 → 验证）见 `$AGENT_DIR/knowledge-base/web-methodology.md` §1.5。
> 攻击编排模板（控制器页面、postMessage、轮询）见 `$AGENT_DIR/knowledge-base/attack-orchestration.md`。
