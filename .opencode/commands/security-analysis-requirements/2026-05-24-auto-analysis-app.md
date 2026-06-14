# 需求文档: 自动分析应用（auto-analysis）

## §1 背景与目标

### 背景

用户希望安全分析 agent 能够自动完成完整的分析循环：访问网站 → 获取任务 → 分析解题 → 提交验证 → 失败重试。目标是利用空闲 token 让 agent 越来越强。

上一次进化尝试通过"auto-analyst Agent"实现，但设计错误：将确定性逻辑（循环控制、网站操作）交给 LLM 编排，浪费 token 且不可靠。

**核心洞察**: LLM 只做需要智能的事（技术分析），确定性逻辑全用代码。

OpenCode 提供了 TypeScript SDK（`@opencode-ai/sdk`），支持：
- `createOpencodeServer()` — 启动 headless server
- `client.session.create()` + `client.session.prompt()` — 创建会话、发送消息
- `client.session.promptAsync()` — 异步发送
- `client.event.subscribe()` — SSE 事件流（实时状态推送）
- `Promise.all` 并发多个 session
- `directory` 参数传递项目空间（加载 .opencode/ 配置）

### 目标

在项目根目录下创建 `auto-analysis/` 独立应用，包含：

1. **TypeScript 后端**: 启动 OpenCode server，通过 SDK 调用 coordinator agent 做技术分析，管理网站会话、任务循环、并发调度
2. **React 前端**: 任务看板（查看状态/进度），并发控制，实时日志，手动操作
3. **网站适配器**: TypeScript 实现的通用网站操作（CTFd 优先）
4. **凭据管理**: 加密存储网站登录凭据

### 约束

- **独立应用**: 不修改现有 security-analysis 体系（agents/plugins/scripts 均不改）
- **通过 SDK 调用**: 后端通过 OpenCode SDK 调用 coordinator agent，复用所有现有分析能力
- **项目空间**: 自动解析当前项目目录（auto-analysis/ 的上级目录），传递给 OpenCode server
- **跨平台**: Windows / Linux / macOS

---

## §2 技术方案

### 2.1 架构总览

```
auto-analysis/
├── package.json                    # 独立 Node.js 项目
├── tsconfig.json
├── vite.config.ts                  # 前端构建配置
│
├── server/                         # 后端（Node.js + Express）
│   ├── index.ts                    # 入口：启动 Express + OpenCode server
│   ├── opencode.ts                 # OpenCode SDK 封装
│   ├── scheduler.ts                # 任务调度器（并发控制、重试）
│   ├── file-store.ts               # private_data 文件读写（加锁 + 原子写入）
│   ├── credentials.ts              # 凭据加密/解密
│   ├── routes/
│   │   ├── tasks.ts                # 任务 API（CRUD + 状态查询）
│   │   ├── events.ts               # SSE 事件流
│   │   └── config.ts               # 配置 API（并发数、网站设置）
│   └── adapters/
│       ├── base.ts                 # 网站适配器基类
│       └── ctfd.ts                 # CTFd 适配器
│
├── src/                            # 前端（React + Vite）
│   ├── App.tsx
│   ├── components/
│   │   ├── TaskBoard.tsx           # 任务看板
│   │   ├── TaskCard.tsx            # 单个任务卡片
│   │   ├── LiveLog.tsx             # 实时日志
│   │   └── ConcurrencyControl.tsx  # 并发控制滑块
│   └── hooks/
│       └── useSSE.ts               # SSE 事件 hook
│
├── shared/                         # 前后端共享类型
│   └── types.ts
│
└── private_data/                   # 运行时敏感数据（gitignore，写入需加锁）
    ├── credentials.json            # 加密凭据
    └── tasks.json                  # 任务状态持久化
```

### 2.2 后端核心流程

```
用户在 React UI 点击"开始分析"
    ↓
POST /api/tasks/start { siteUrl: "https://..." }
    ↓
后端执行:
    1. 解密凭据 → 网站适配器登录
    2. listTasks() → 获取任务列表
    3. 为每个任务创建 Task 对象（id, status, retryCount）
    4. 调度器按并发数逐个/并行执行:
       a. getTaskInfo() → 获取任务详情
       b. 下载附件（如需要）→ downloadFile() → 自动解压到 ~/Downloads
       c. 生成分析 prompt
       d. OpenCode SDK: session.create() + session.prompt({ agent: "security-coordinator" })
       e. 等待完成 → 从响应提取答案
       f. submitAnswer() → 提交答案
       g. 检查结果 → 失败重试/标记完成
    5. 全部完成 → 输出汇总
    ↓
全程通过 SSE 推送进度给前端
```

### 2.3 OpenCode SDK 集成

```typescript
// server/opencode.ts
import { createOpencodeServer, createOpencodeClient } from "@opencode-ai/sdk"
import path from "path"
import fs from "fs"
import { fileURLToPath } from "url"

// ESM 兼容：Node 22+ 使用 import.meta.dirname，否则用 fileURLToPath（不用 URL.pathname，Windows 会多前导斜杠）
const __dirname = import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url))

// 运行时动态检测项目根目录：从当前文件位置向上查找包含 .opencode/ 的目录
function findProjectRoot(): string {
  let dir = path.resolve(__dirname)
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, ".opencode"))) return dir
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  // 回退：auto-analysis/ 的上级
  return path.resolve(__dirname, "..")
}

const PROJECT_ROOT = findProjectRoot()

let serverInstance: Awaited<ReturnType<typeof createOpencodeServer>> | null = null
let serverPromise: Promise<Awaited<ReturnType<typeof createOpencodeServer>>> | null = null

// 并发安全：多次调用返回同一个 promise，避免创建多个 server 实例
export async function getServer() {
  if (!serverInstance && !serverPromise) {
    serverPromise = createOpencodeServer().then((server) => {
      serverInstance = server
      return server
    })
  }
  return serverInstance ?? serverPromise!
}

export async function getClient() {
  const server = await getServer()
  return createOpencodeClient({ baseUrl: server.url, directory: PROJECT_ROOT })
}

// 从 SDK 响应中提取文本
// SessionPromptResponses = { 200: { info: AssistantMessage, parts: Array<Part> } }
// Part 包含 TextPart（type: "text", text: string）等多种变体
function extractText(data: { parts?: Array<{ type: string; text?: string }> } | undefined): string {
  if (!data?.parts) return ""
  return data.parts
    .filter((p) => p.type === "text" && p.text)
    .map((p) => p.text!)
    .join("\n")
}

// 调用 coordinator 分析
// 使用 session.prompt（同步阻塞）：等待 coordinator 完成全部工作后返回结果
// 并发由调度器通过 Promise.all 控制，不需要 promptAsync
export async function analyze(taskPrompt: string): Promise<string> {
  const client = await getClient()
  const session = await client.session.create()
  if (session.error) {
    throw new Error(`创建 session 失败: ${JSON.stringify(session.error)}`)
  }
  const result = await client.session.prompt({
    path: { id: session.data.id },
    body: {
      agent: "security-coordinator",
      parts: [{ type: "text", text: taskPrompt }],
    },
  })
  if (result.error) {
    throw new Error(`OpenCode 分析失败: ${JSON.stringify(result.error)}`)
  }
  return extractText(result.data)
}
```

**SDK 依赖方式**: 使用本地 link（`file:../vendor/opencode/packages/sdk/js`），确保版本与项目中的 OpenCode 源码一致。发布版可能版本不匹配导致 API 不兼容。

**prompt vs promptAsync 选择**: 使用 `session.prompt`（同步阻塞）。
- 优点：代码简单，直接 await 获取完整结果，不需要额外监听 SSE 收集响应
- 并发由调度器控制：调度器同时发起多个 `analyze()` 调用，用信号量限制并行数
- `promptAsync` 适合"发射后不管"场景，但我们需要结果才能决定是否重试

### 2.4 网站适配器（TypeScript）

```typescript
// server/adapters/base.ts
interface SiteAdapter {
  // 登录：内部维护 cookie jar/session state（适配器内部状态，不通过返回值传递）
  // CTFd 实现: 先 GET 页面获取 CSRF nonce → POST /api/v1/auth/login（带 nonce）
  login(username: string, password: string): Promise<void>
  listTasks(): Promise<Task[]>
  getTaskInfo(taskId: string): Promise<TaskInfo>  // 返回包含 files: [{url}] 字段
  submitAnswer(taskId: string, answer: string): Promise<SubmitResult>
  // url: 站点相对路径（如 CTFd 的 "/files/xxx"），适配器内部拼接 baseUrl
  // outputPath: 本地保存路径（如 ~/Downloads/xxx）
  downloadFile(url: string, outputPath: string): Promise<DownloadResult>
}

// 下载结果
interface DownloadResult {
  success: boolean
  path: string            // 下载后的文件路径
  extractDir?: string     // 如果是压缩包且解压成功，解压后的目录路径
}

// 提交结果
interface SubmitResult {
  success: boolean
  message?: string        // 如 "correct"/"incorrect" 等服务端反馈
}

// server/adapters/ctfd.ts — CTFd REST API
class CTFdAdapter implements SiteAdapter {
  // 使用原生 fetch，不依赖 Python/Playwright
  // CTFd API: /api/v1/auth/login, /api/v1/challenges, /api/v1/challenges/attempt
  // 文件下载: GET /files/<path>（带 session cookie）
  // 自动解压: zip/tar.gz，散落一级目录时创建子目录
}
```

### 2.5 前端设计

| 组件 | 功能 |
|------|------|
| TaskBoard | 展示所有任务卡片（状态: pending/running/success/failed） |
| TaskCard | 单个任务：标题、类别、分值、状态、重试次数、实盘日志 |
| LiveLog | SSE 实时显示当前分析进度（agent 输出、工具调用） |
| ConcurrencyControl | 滑块调整并行分析数（1-5） |
| StartButton | 输入网站 URL → 开始分析（合入 App.tsx，非独立组件文件） |

### 2.6 凭据管理

TypeScript 实现的加密存储（全新实现，非 Python 方案移植）：
- 密钥派生: 机器指纹（hostname + username + platform + MAC）→ PBKDF2-HMAC-SHA256 → 32 字节密钥
- 加密: Node.js `crypto.createCipheriv('aes-256-gcm', key, iv)` — 比 Python 方案的 Fernet（AES-128-CBC）更强
- 存储: `private_data/credentials.json`
- 跨平台: 使用 Node.js 内置 `crypto` 模块，无需额外依赖

### 2.7 private_data 文件写入安全

调度器并发运行多个任务时，多个 async 函数可能同时写入 `private_data/` 下的文件（如 `tasks.json`、`credentials.json`）。必须确保文件写入的原子性，避免并发写入导致文件损坏。

**方案**: 使用 `proper-lockfile` 库对目标文件加锁（基于 flock/lockfile 机制），包装读写操作：
- 写入前获取文件锁 → 写入临时文件 → rename 原子替换 → 释放锁
- 读取前获取文件锁 → 读取 → 释放锁
- 封装为 `server/file-store.ts` 中的 `readJson()` / `writeJson()` 通用工具函数
- 所有对 `private_data/` 的文件读写必须通过这两个函数，禁止直接 `fs.readFile`/`fs.writeFile`

---

## §3 实现规范

### 3.0 改动范围表

| 目录/文件 | 操作 | 说明 |
|-----------|------|------|
| `auto-analysis/` (整个目录) | 新增 | 独立应用 |
| `auto-analysis/.gitignore` | 修改 | +2 行排除 /private_data、/dist |
| 现有 security-analysis 体系 | 不改动 | agents/plugins/scripts 全部不动 |

**不改动任何现有文件**（除了 auto-analysis/.gitignore）。

### 3.1 实施步骤拆分

**步骤 1. 项目初始化（package.json + tsconfig + vite）**
  - 文件: `auto-analysis/package.json`, `tsconfig.json`, `vite.config.ts`
  - 预估行数: ~80 行
  - 验证点: `npm install` 成功
  - 依赖: 无
  - SDK 依赖: 使用本地 link `"@opencode-ai/sdk": "file:../vendor/opencode/packages/sdk/js"`，确保版本一致
  - 其他依赖: `proper-lockfile`（private_data 文件加锁）、`express`、`cors`、`concurrently`、`tsx`、`vite`、`@vitejs/plugin-react`、`react`、`react-dom`
  - **运行时**: server 使用 `tsx` 运行（不预编译），因为 SDK exports 指向 `.ts` 源文件（没有预编译 dist）
  - **模块系统**: `"type": "module"`（ESM），因为 SDK 是 ESM package
  - 运行脚本: package.json 配置 `dev`（concurrently 启动前后端）、`build`（vite build 前端）、`start`（tsx server/index.ts）
  - vite.config.ts 必须配置 proxy: 将 `/api/*` 代理到后端 Express（localhost:3001）
  - 前置条件: 系统已安装 `opencode` CLI（用于 `createOpencodeServer()` 启动子进程）

**步骤 2. 共享类型定义**
  - 文件: `auto-analysis/shared/types.ts`
  - 预估行数: ~50 行
  - 验证点: 后端文件能正确 import 类型，TypeScript 编译通过
  - 依赖: 无

**步骤 3. 后端: OpenCode SDK 封装**
  - 文件: `auto-analysis/server/opencode.ts`
  - 预估行数: ~80 行
  - 验证点: 能启动 opencode server 并创建 session
  - 依赖: 步骤 1

**步骤 4a. 后端: 网站适配器基类**
  - 文件: `auto-analysis/server/adapters/base.ts`
  - 预估行数: ~60 行
  - 验证点: TypeScript 编译通过；SiteAdapter 接口包含完整方法签名
  - 依赖: 步骤 2

**步骤 4b. 后端: CTFd 适配器实现**
  - 文件: `auto-analysis/server/adapters/ctfd.ts`
  - 预估行数: ~190 行
  - 验证点: TypeScript 编译通过；CTFd adapter 包含 login/listTasks/getTaskInfo/submitAnswer/downloadFile 实现
  - 包含: CTFd REST API 调用 + 文件下载 + 智能解压（zip/tar.gz，散落一级目录时创建子目录）
  - 依赖: 步骤 4a

**步骤 5. 后端: 文件存储（加锁读写）+ 凭据管理**
  - 文件: `auto-analysis/server/file-store.ts`, `auto-analysis/server/credentials.ts`
  - 预估行数: ~150 行
  - 验证点: file-store 的 readJson/writeJson 加锁闭环；凭据加密/解密闭环
  - 包含: proper-lockfile 文件锁、临时文件 + rename 原子写入、凭据 AES-256-GCM 加解密
  - 依赖: 步骤 1（proper-lockfile 依赖）

**步骤 6. 后端: 任务调度器**
  - 文件: `auto-analysis/server/scheduler.ts`
  - 预估行数: ~150 行
  - 验证点: TypeScript 编译通过；并发控制逻辑正确
  - 依赖: 步骤 3, 4b, 5

**步骤 7a. 后端: Express 入口 + SSE 路由**
  - 文件: `auto-analysis/server/index.ts`, `auto-analysis/server/routes/events.ts`
  - 预估行数: ~100 行
  - 验证点: `npx tsx server/index.ts` 启动后，SSE 端点 `/api/events` 可连接
  - 依赖: 步骤 6

**步骤 7b. 后端: 任务路由 + 配置路由**
  - 文件: `auto-analysis/server/routes/tasks.ts`, `auto-analysis/server/routes/config.ts`
  - 预估行数: ~120 行
  - 验证点: `curl http://localhost:3001/api/tasks` 返回 200；`curl http://localhost:3001/api/config` 返回 200
  - 依赖: 步骤 7a

**步骤 8a. 前端: 基础设施（SSE hook + App 骨架）**
  - 文件: `auto-analysis/src/hooks/useSSE.ts`, `auto-analysis/src/App.tsx`
  - 预估行数: ~80 行
  - 验证点: `npm run dev` 前端页面加载，SSE 连接建立
  - 依赖: 步骤 7a（需要后端 SSE 端点）

**步骤 8b. 前端: 任务看板组件**
  - 文件: `auto-analysis/src/components/TaskBoard.tsx`, `auto-analysis/src/components/TaskCard.tsx`
  - 预估行数: ~150 行
  - 验证点: 看板显示任务列表，任务状态实时更新
  - 依赖: 步骤 8a

**步骤 8c. 前端: 辅助组件（LiveLog + ConcurrencyControl）**
  - 文件: `auto-analysis/src/components/LiveLog.tsx`, `auto-analysis/src/components/ConcurrencyControl.tsx`
  - 预估行数: ~120 行
  - 验证点: 实时日志显示；并发控制滑块可调整
  - 依赖: 步骤 8a

**步骤 9. .gitignore 更新**
  - 文件: `auto-analysis/.gitignore`
  - 预估行数: ~2 行（追加 `/private_data`、`/dist`）
  - 验证点: `auto-analysis/private_data/` 和 `auto-analysis/dist/` 被 git 排除
  - 依赖: 无

**步骤 10. 端到端验证**
  - 预估行数: 0 行
  - 验证点:
    - 后端启动成功
    - 前端页面加载
    - SSE 事件流连通
    - OpenCode SDK 能创建 session 并调用 coordinator
    - 现有 agents/plugins/scripts 无改动
  - 依赖: 步骤 1-8c, 9

---

## §4 验收标准

### 功能验收

- [ ] 后端能启动 OpenCode server 并通过 SDK 创建 session
- [ ] 后端能通过 SDK 调用 security-coordinator agent
- [ ] CTFd adapter 能登录并获取题目列表
- [ ] CTFd adapter 能提交 flag
- [ ] CTFd adapter 能下载附件并自动解压
- [ ] 凭据加密/解密闭环
- [ ] private_data 文件并发读写安全（加锁 + 原子写入）
- [ ] 任务调度器支持并发控制
- [ ] SSE 实时推送任务进度
- [ ] 前端任务看板显示所有任务状态
- [ ] 前端并发控制滑块可调整

### 回归验收

- [ ] .opencode/ 下所有 agent prompt 无改动
- [ ] .opencode/plugins/security-analysis.ts 无改动
- [ ] .opencode/binary-analysis/ 下所有脚本无改动
- [ ] .opencode/agents-rules/ 下所有片段无改动

### 架构验收

- [ ] auto-analysis/ 是独立 Node.js 项目（有自己的 package.json）
- [ ] 通过 SDK directory 参数传递项目空间
- [ ] 不修改现有 security-analysis 体系的任何文件
- [ ] 前后端分离（Express API + React SPA）

---

## §5 与现有需求文档的关系

- 独立于所有已有需求文档
- 不依赖任何未完成的进化任务
- 复用现有 security-coordinator + delegate_analysis 体系（通过 SDK 调用）
- 替代 2026-05-24-auto-analyst.md（已回退）

---

## §6 关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 架构方式 | 独立前后端应用 | 需要前端 UI 监控和并发控制 |
| 后端语言 | TypeScript (tsx 运行) | 与 OpenCode SDK 同生态；SDK exports 指向 .ts 源文件，需 tsx 运行 |
| 前端框架 | React | 用户指定 |
| 分析调度 | SDK 直接调用 coordinator | 不需要 auto-analyst agent，代码驱动更可靠 |
| 项目空间 | 自动解析 + SDK directory 参数 | server.ts 注释确认此机制 |
| 网站操作 | TypeScript fetch | CTFd 有 HTTP API，不需要 Python/Playwright |
| 并发支持 | Promise.all + 调度器 | SDK 示例已展示此模式 |
| SDK 依赖 | 本地 file: link | 版本与项目 OpenCode 源码一致，避免发布版不兼容 |
| prompt 选择 | session.prompt（同步阻塞） | 直接 await 获取完整结果，并发由调度器控制 |
| 模块系统 | ESM | SDK 是 ESM package，需要 type: module |
| 运行时数据目录 | private_data/ | 存放凭据和任务状态，含敏感信息需 gitignore |
| 文件写入安全 | proper-lockfile + 原子替换 | 并发任务可能同时写 private_data，需加锁防损坏 |
