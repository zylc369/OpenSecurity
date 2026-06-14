# Bot 模式分类与识别

> Bot 快速分类参考。聚焦 **Bot 代码结构分析**和**模式快速识别**。
>
> **详细的分析流程**（攻击面枚举、外泄方式选择、CSP 绕过等）见 `$AGENT_DIR/knowledge-base/web-methodology.md` §1.5。
> **多步骤攻击编排**（popup 存活、轮询模板、控制器页面）见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3。
> **Bot 代码自动化分析**见 `$AGENT_DIR/scripts/bot_analyze.py`。

---

## 1. Bot 代码通用结构

几乎所有 Web CTF Bot 共享相同的基础结构（Express + Puppeteer）。Bot 代码的关键差异集中在两个点：
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

### 3.2 httpOnly 设置

CTF 中 flag Cookie 通常设为 `httpOnly: false`（刻意设计让 XSS 可读）。真实场景中鉴权 Cookie 应设 `httpOnly: true`。

### 3.3 Docker 中 Chromium 的 AE 特性

Docker 中系统包版 Chromium 通常不支持 Brotli 压缩，Accept-Encoding 不含 `br`。
这对缓存键匹配至关重要 — 详见 `$AGENT_DIR/knowledge-base/cache-poisoning.md` §7.1 和 `$AGENT_DIR/knowledge-base/nextjs-analysis.md` §4.1。

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
│   └── httpOnly: true? → XSS 不可读，需要 CSRF 或其他方式
│
└── CHALLENGE_URL 是什么?
    └── 记录下来 → 这是 Docker 内部域名，用于构造 Bot URL 和缓存键对齐
```

> 完整的攻击流程（信息收集 → 漏洞发现 → 利用构造 → 验证）见 `$AGENT_DIR/knowledge-base/web-methodology.md` §1.5。
> 攻击编排模板（控制器页面、postMessage、轮询）见 `$AGENT_DIR/knowledge-base/attack-orchestration.md`。
