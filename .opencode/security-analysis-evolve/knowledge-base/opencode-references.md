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
