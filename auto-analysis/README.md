# Auto Analysis

自动完成 CTF 安全分析循环：访问网站 → 获取题目 → AI 分析解题 → 提交验证 → 失败重试。

通过 OpenCode SDK 调用 `security-coordinator` agent 执行技术分析，确定性逻辑（循环控制、网站操作、并发调度）全部由代码驱动。

## 前置条件

- Node.js >= 22（`import.meta.dirname` 支持）
- 项目根目录存在 `.opencode/` 配置（SDK `findProjectRoot()` 向上查找此目录）
- 系统已安装 `opencode` CLI（`createOpencodeServer()` 需要启动子进程）

## 安装

```bash
cd auto-analysis
npm install
```

`postinstall` 会自动执行 `setup-sdk.mjs`，为 SDK 创建 `node_modules` junction（解决 SDK 内部 `cross-spawn` 依赖解析）。

## 开发

```bash
npm run dev
```

启动两个进程（concurrently）：
- **server**（蓝色）: `tsx watch server/index.ts` — 后端，端口 3001，文件变更自动重启
- **client**（绿色）: `vite` — 前端开发服务器，端口 5173，热更新

Vite 自动将 `/api/*` 请求代理到 `http://localhost:3001`。

打开 http://localhost:5173 即可使用。

## 调试

**后端日志**：

开发模式默认使用 `pino-pretty` 彩色输出，带时间戳：

```
2026-05-24 15:30:01.234 INFO  Auto Analysis 后端已启动
2026-05-24 15:30:01.235 INFO  SSE 端点: http://localhost:3001/api/events
```

控制日志级别：

```bash
LOG_LEVEL=debug npm run dev    # 显示所有调试日志
LOG_LEVEL=warn npm run dev     # 只显示警告和错误
```

**类型检查**：

SDK 未预编译（exports 指向 `.ts` 源码），`tsc` 会报告 SDK 内部错误。使用专用脚本过滤：

```bash
node typecheck.mjs
```

只报告项目自有代码的类型错误，忽略 `vendor/opencode` 路径下的错误。

**前端**：

浏览器开发者工具即可。SSE 事件流可在 Network 标签的 EventStream 中查看。

## 打包

```bash
npm run build
```

Vite 将前端构建到 `dist/`。后端不预编译（`tsx` 运行时编译），直接部署 `server/` + `shared/` 源码。

## 启动（生产）

```bash
NODE_ENV=production npm start
```

- 后端 Express 直接托管 `dist/` 下的前端静态文件
- 日志输出 JSON 格式（不加载 pino-pretty）
- 默认端口 3001，可通过 `PORT` 环境变量修改

打开 http://localhost:3001 即可使用。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `3001` | 后端监听端口 |
| `NODE_ENV` | — | 设为 `production` 启用 JSON 日志、关闭 pino-pretty |
| `LOG_LEVEL` | `info` | 日志级别：`trace` / `debug` / `info` / `warn` / `error` / `fatal` |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 获取所有任务 |
| POST | `/api/tasks/start` | 开始分析（body: `{ siteUrl }`） |
| POST | `/api/tasks/abort` | 取消当前调度 |
| GET | `/api/config` | 获取调度器配置 |
| PATCH | `/api/config` | 更新配置（body: `{ maxConcurrency?, maxRetries? }`） |
| PUT | `/api/config/credentials` | 保存凭据（body: `{ siteUrl, username, password }`） |
| GET | `/api/config/credentials?siteUrl=...` | 检查凭据是否存在 |
| GET | `/api/events` | SSE 事件流（task:status / task:log / scheduler:complete） |

## 使用流程

1. **配置凭据**: 前端界面输入 CTFd 网站地址 → 系统提示配置用户名密码 → PUT `/api/config/credentials`
2. **开始分析**: 点击"开始分析" → 后端登录 CTFd → 获取题目列表 → 并发调度分析
3. **实时监控**: SSE 推送任务状态到看板，实时日志显示分析进度
4. **调整并发**: 拖动滑块调整并行分析数（1-5）

## 目录结构

```
auto-analysis/
├── server/                  # 后端（Express + tsx 运行）
│   ├── index.ts             # 入口：Express + 优雅退出
│   ├── opencode.ts          # OpenCode SDK 封装（单例 server、analyze）
│   ├── scheduler.ts         # 任务调度器（并发控制、重试）
│   ├── logger.ts            # pino 日志配置
│   ├── file-store.ts        # private_data 文件读写（加锁 + 原子写入）
│   ├── credentials.ts       # 凭据加密/解密（AES-256-GCM）
│   ├── routes/
│   │   ├── tasks.ts         # 任务 API
│   │   ├── events.ts        # SSE 事件流
│   │   └── config.ts        # 配置 API
│   └── adapters/
│       ├── base.ts          # SiteAdapter 接口
│       └── ctfd.ts          # CTFd REST API 实现
├── src/                     # 前端（React + Vite）
│   ├── App.tsx              # 主组件
│   ├── main.tsx             # React 入口
│   ├── components/
│   │   ├── TaskBoard.tsx    # 任务看板
│   │   ├── TaskCard.tsx     # 任务卡片
│   │   ├── LiveLog.tsx      # 实时日志
│   │   └── ConcurrencyControl.tsx  # 并发控制
│   └── hooks/
│       └── useSSE.ts        # SSE 事件 hook
├── shared/
│   └── types.ts             # 前后端共享类型
├── private_data/            # 运行时数据（gitignore）
│   ├── credentials.json     # 加密凭据
│   ├── tasks.json           # 任务状态
│   └── files/               # 下载的附件
├── setup-sdk.mjs            # postinstall: SDK junction 创建
├── typecheck.mjs            # 类型检查（过滤 SDK 错误）
├── package.json
├── tsconfig.json
└── vite.config.ts
```
