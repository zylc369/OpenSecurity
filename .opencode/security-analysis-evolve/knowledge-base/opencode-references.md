# OpenCode 开发参考

> Plugin/Agent 开发所需的文档索引与源码查阅流程。
> 触发: 涉及 Plugin Hook、Agent 文件格式、插件调试、需查 vendor 源码时。不依赖主 prompt 上下文即可理解。

---

## 知识库文档（优先查找）

| 文档路径 | 触发条件 |
|----------|---------|
| `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md` | 沉淀知识到任何知识库文件之前 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-api.md` | 查看 Hook 签名、input/output 类型 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-hooks-lifecycle.md` | 理解 Hook 执行时序、awaited vs fire-and-forget、常见陷阱 |
| `$SHARED_DIR/knowledge-base/opencode-plugin-development-guide.md` | 从零创建插件、最小模板、状态管理模式 |
| `$SHARED_DIR/knowledge-base/opencode-agent-format.md` | 创建/修改 Agent 文件格式、frontmatter 字段（mode/hidden/tools/description 路由写法） |
| `$SHARED_DIR/knowledge-base/opencode-plugin-debugging.md` | 排查 Plugin 问题、测试验证方法 |
| `$SHARED_DIR/knowledge-base/idapython-conventions.md` | 生成 IDAPython 脚本时的编码规范 |

## 源码参考（知识库不足时）

| 源码 | 用途 |
|------|------|
| `vendor/opencode/packages/opencode/src/` | OpenCode 核心源码: session 管理、plugin 调度、LLM 交互、agent 加载（agent/agent.ts 的 frontmatter schema、tool/task.ts 的派发解析、session/prompt.ts 的列表注入过滤） |
| `vendor/oh-my-openagent/src/` | 社区参考插件: 完整 Plugin 实现示例（context collector、message transform、event 处理） |

查阅流程:
1. 先搜索上表知识库文档
2. 知识库无答案 → 在 `vendor/` 中搜索相关关键词（hook 名、函数名、类型签名）
3. 找到答案后，将新知识补充到对应知识库文档（下次不用再查源码）

## opencode 平台行为实证记录

### Windows 命名管道 IPC 实现要点（pywin32 / Python 端）

**同步句柄 I/O 在句柄级序列化**——`FO_SYNCHRONOUS_IO` 文件对象上，pending 的
`ReadFile` 会阻塞同句柄的 `WriteFile`（跨线程同样; NT 内核语义，MSDN
"Synchronous and Overlapped Pipe I/O" 明示多线程读/写"does not help"）。
**"一读线程 + 一写线程"双泵在同步管道上必然死锁**（正确性对端到端数据流
为条件）。三种正解:
- **单线程轮询桥**（工程最简）: `PeekNamedPipe` 非阻塞探测管道可读性
  （单线程独占该句柄时"always returns immediately"——MSDN）+ `select`
  探测 socket 可读性，同一线程交替转发——无并发 I/O 即无序列化问题;
  代价: 1ms 级轮询粒度。`PeekNamedPipe(handle, size=1)` 返回
  `(data, totalAvail, bytesLeft)`，**size 传 1 而非 0**（C 层 `malloc(0)`
  可能返回 NULL 误报 NoMemory）
- OVERLAPPED 异步 I/O（每操作独立 OVERLAPPED + event; 工程面大）
- 双单工管道（协议需改，客户端要连两次）

**pywin32 相关坑（代码级）**:
- `FILE_FLAG_FIRST_PIPE_INSTANCE` 在 **win32pipe** 模块（win32file 无此常量）
- `pywintypes.error` **不继承 OSError**（`class error(Exception)`）——捕获
  win32 API 错误必须显式含它
- `ConnectNamedPipe` 的 `ERROR_PIPE_CONNECTED`(535) 是**返回值**不是异常
  （win32pipe.i @comm: "this value is returned"）——返回值 0/535 均"连接就绪"
- pywin32 无类型 stub——basedpyright 把句柄误推 `int`、`ReadFile` 返回
  误推 `str`，相关行需 `# pyright: ignore[reportArgumentType]`
- 客户端侧（Bun/node:net）用 libuv 异步 I/O——**无序列化问题**；仅
  Python/pywin32 端需要轮询桥或 OVERLAPPED

### MCP 子进程 env 是合并语义（无白名单选项）

opencode spawn MCP server 时（`packages/opencode/src/mcp/index.ts`）:

```ts
env: {
  ...process.env,                    // 全量继承 opencode 主进程
  ...(cmd === "opencode" ? { BUN_BE_BUN: "1" } : {}),
  ...mcp.environment,                // 配置的 environment 铺在上面
}
```

- **语义**: `mcp.add` 的 `environment` 字段是**合并**（叠加覆盖同名键），
  不是替换——无法通过该字段剔除继承键（业务键/conda 杂键必然进入 MCP 子进程）。
- **字段名必须是 `environment`**: 历史上误写 `env` 被静默丢弃。
- **如需收紧 MCP env**: command 前置 `/usr/bin/env -i KEY=VAL ... <原command>`
  （exec 层清空一切父 env，只留显式键; win32 无 env 命令不适用; 已验证握手
  正常——本仓库当前未启用，MCP 保持合并语义直跑）。
- **验证方式**: MCP 子进程 `ps eww <pid>` 看 environ 键集合（快照=execve
  传入值，不反映运行时 os.environ 修改）。

### 权限询问的自动处理路径（事件 + reply 端点）

**权限拦截/自动回复的正确路径是「事件 + reply 端点」，`permission.ask` plugin hook 不可用**：

- `permission.ask` hook 未接线——类型定义存在，运行时无触发点（1.18.32 与 dev 最新版均无）。
- 插件 `event` hook 可收到 `permission.asked` / `permission.replied`（v2 为 `permission.v2.asked` / `permission.v2.replied`），事件含请求 ID / 会话 ID / 权限类型等完整字段。
- `POST /permission/{requestID}/reply` body `{reply:"reject", message}` 完成拒绝；`message` 生成 `CorrectedError.feedback`，随被拒工具的错误结果送达模型，模型继续执行、不中断会话。
- API 用法（事件字段对照 / 端点差异 / 底层调用要点）详见 `$SHARED_DIR/knowledge-base/opencode-plugin-api.md`。
- 验证方式：起 `opencode serve` + 临时项目插件监听事件并调用 reply；检查插件日志（asked → 超时 reply 时序）与 session 消息（`GET /session/{id}/message`，工具错误含 feedback 文本）。

**v1/v2 双轨对照**（升级迁移用）：

| 项 | v1（1.18.x 现行） | v2（dev 已实现，未接管主流程） |
|---|---|---|
| 事件 | `permission.asked` / `permission.replied` | `permission.v2.asked` / `permission.v2.replied` |
| 字段 | permission / patterns / always | action / resources / save |
| 回复 | `/permission/{requestID}/reply` body `{reply, message?}`；旧 `/session/{sid}/permissions/{pid}` body `{response}` | `/api/session/{sid}/permission/{rid}/reply` body `{reply, message?}` |
| SDK | `postSessionIdPermissionsPermissionId`（无 message）；注入 client 无 `permission` 命名空间 | `client.permission.reply({requestID, reply, message})`（v2 SDK 面） |
| 插件形态 | named export 函数返回 hooks 对象；`.opencode/plugins/*.ts` 自动发现 | `export default {id, effect/setup}`；v2 loader 只认此形态（v1 形态文件不会被 v2 runtime 加载） |

**bash 工具的外部目录检查边界**：`external_directory` 权限只对命令行中静态可解析的路径触发（命令解析器扫描）；脚本文件内部的路径访问不被扫描——`python script.py` 命令行不含外部路径即不触发，脚本内 `open("/outside/file")` 正常执行。引导模型"通过脚本访问"时，须提示把脚本写到可写位置（项目内 / 已放行目录）再运行。

**CLI `opencode run` 权限行为**：非交互模式对权限询问自动回复——`--auto` 回复 "once"（自动允许）；未加 `--auto` 打印警告并回复 "reject"（不会挂起等待）。

### agent frontmatter 未知字段透传与严格网关冲突

**opencode 把 agent 文件 frontmatter 的非标准字段收进 `agent.options` 并透传进 LLM 请求参数**：

- 收集点 `core/src/v1/config/agent.ts` 的 normalize: 非 KNOWN_KEYS（name/model/variant/prompt/description/temperature/top_p/mode/hidden/color/steps/maxSteps/options/permission/disable/tools）的字段全部塞 options
- 合并点 `session/llm/request.ts`: `options = merge(base, model.options, agent.options, variant)` → 进最终请求参数

**触发情境**: 请求报 `Extra inputs are not permitted, field: '<自定义字段名>'`——网关侧 Pydantic extra=forbid 类严格校验所致；宽容网关忽略额外字段不报错（同一 agent 在不同 provider 表现不同即此原因，且同一网关的校验行为可能随其服务端变更而变化）。

**处理**: 插件 `chat.params` hook 里 `delete output.options["<自定义字段>"]`——请求构建的最后关口（plugin.trigger 在参数汇总后、发送前调用，修改 `output.options` 直接生效，清理后请求参数中不再含该字段）。

**体系约定**: agent frontmatter 仅用 `buwai-extension-id` 一个自定义字段（占位符展开标记，见 lib/snippet.ts）; 插件 chat.params 已统一清理。**新增 frontmatter 自定义字段时必须同步登记 chat.params 清理列表**，否则严格网关下复现同类报错。

**诊断手法**:
- 测试插件在 chat.params 打印 `Object.keys(output.options)` 直接看透传字段集
- 本地重现: `opencode serve` + prompt 请求体带 `"agent": "<name>"`（注意: agent 必须放 prompt body，仅在 session 创建时传不生效——实际请求会回落到 build agent）
