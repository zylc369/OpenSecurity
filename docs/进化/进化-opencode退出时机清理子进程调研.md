# 进化-opencode 退出时机清理子进程调研

> 调研日期: 2026-07-05
> 调研目标: 确认 opencode 结束前能否监听到消息/HOOK，以便在该时机 kill 掉 opencode 打开的进程（IDA、Frida、子 session 等）。
> 调研范围: `vendor/opencode`（核心源码）+ `vendor/oh-my-openagent`（社区参考插件）+ `.opencode/plugins/`（本仓 security-analysis 插件现状）。

## 一、结论先行

**能在 opencode 结束前监听到退出时机，但不能依赖 `dispose` hook，必须注册 Node.js 信号处理器。**

| 方案 | 可靠性 | 说明 |
|------|--------|------|
| `dispose` hook | ❌ 不可靠 | 主进程 `finally { process.exit() }` 直接退出，不给 finalizer 执行机会 |
| `event` hook | ❌ 不行 | event 体系没有 `process.exit`/`shutdown`/`beforeExit` 类事件 |
| `process.on("SIGINT"/"SIGTERM")` | ✅ 可靠 | 用户 Ctrl+C 或 kill 命令时触发，可做异步 cleanup |
| `process.on("beforeExit")` | ⚠️ 部分 | 进程无任务时触发，但 `process.exit()` 不触发它 |
| `process.on("exit")` | ✅ 最后兜底 | 退出前最后机会，**只能同步操作**（不能 await） |

**推荐组合**: SIGINT/SIGTERM（主 cleanup + 超时强制退出）+ exit（同步兜底 kill）+ dispose hook（双保险，scope 正常关闭时生效）。

## 二、OpenCode Plugin 官方退出清理机制：`dispose` hook

### 2.1 Hooks 接口官方定义

`vendor/opencode/packages/plugin/src/index.ts:222-223` 的 `Hooks` 接口里官方定义了 `dispose` hook：

```ts
export interface Hooks {
  dispose?: () => Promise<void>
  event?: (input: { event: Event }) => Promise<void>
  config?: (input: Config) => Promise<void>
  // ...其他 hooks
}
```

### 2.2 dispose hook 的注册与触发

`vendor/opencode/packages/opencode/src/plugin/index.ts:261-274` 通过 `Effect.addFinalizer` 注册 dispose hook 的调用：

```ts
yield* Effect.addFinalizer(() =>
  Effect.forEach(
    hooks,
    (hook) =>
      Effect.tryPromise({
        try: () => Promise.resolve(hook.dispose?.()),
        catch: errorMessage,
      }).pipe(
        Effect.tapError((error) => Effect.logError("plugin dispose hook failed", { error })),
        Effect.ignore,
      ),
    { discard: true },
      ),
)
```

dispose hook **理论上**在 InstanceState scope 关闭时被调用。问题在于：scope 何时被关闭？

## 三、dispose hook 的触发时机——分场景

| 场景 | 是否触发 dispose | 证据 |
|------|----------------|------|
| `effectCmd` 命令（`opencode agent` 等） | ✅ 触发 | `vendor/opencode/packages/opencode/src/cli/effect-cmd.ts:90-94` 显式 `finally { store.dispose(ctx) }` |
| `opencode run`（TUI）正常退出 | ⚠️ 不确定 | `stream.transport.ts:1460` 有 `close()`，但 `runtime.lifecycle.ts` 的 close 链没看到显式 `store.dispose` |
| `opencode serve`（server 模式） | ❌ 不触发 | daemon 通过 SIGTERM 杀死（`daemon.ts:95`），server.ts 只有 HTTP socket graceful shutdown |
| 主进程 `process.exit()` | ❌ **不触发** | `index.ts:136-141` `finally { process.exit() }` 直接退出，不等 finalizer |

### 3.1 关键证据：主进程直接 process.exit()

`vendor/opencode/packages/opencode/src/index.ts:136-141`：

```ts
} finally {
  // Some subprocesses don't react properly to SIGTERM and similar signals.
  // Most notably, some docker-container-based MCP servers don't handle such signals unless
  // run using `docker run --init`.
  // Explicitly exit to avoid any hanging subprocesses.
  process.exit()
}
```

opencode 主进程在 `finally` 块里**直接 `process.exit()`**，注释明确说"Explicitly exit to avoid any hanging subprocesses"——**主动选择不等待子进程清理**。`process.exit()` 立即终止进程，async finalizer 没机会执行。

### 3.2 opencode 主入口没有 graceful shutdown

opencode 主入口**没有** SIGINT/SIGTERM handler 做 graceful shutdown。只有：

- TUI run 模式的 SIGINT handler（`runtime.lifecycle.ts:281-301`），只用来"Ctrl-c clears a live prompt draft"——清空 prompt draft，不是 graceful shutdown
- server 模式的 HTTP graceful shutdown（`server.ts:214`，`gracefulShutdownTimeout: "1 second"`）——只关 HTTP socket，不调 plugin dispose

## 四、OpenCode event hook 没有退出事件

从 `Hooks` 接口和 event 体系看，OpenCode 的 event 类型有：

- `session.created` / `session.deleted` / `session.idle` / `session.compacted` / `session.error` / `session.status`
- `message.updated` / `message.removed` / `message.part.delta` / `message.part.updated`

**没有** `process.exit` / `shutdown` / `beforeExit` 类的事件。**不能通过 event hook 监听退出。**

## 五、oh-my-openagent 的经验：dispose 不够，必须加信号处理器

oh-my-openagent 用了**双保险**策略，印证了 dispose hook 不可靠。

### 5.1 dispose hook 路径

`vendor/oh-my-openagent/packages/omo-opencode/src/plugin-dispose.ts` 的 `createPluginDispose` 在 dispose 时调用：

- `backgroundManager.shutdown()` —— 关闭后台任务管理器
- `skillMcpManager.disconnectAll()` —— 断开所有 MCP 客户端
- `disposeHooks()` —— 清理 hooks

### 5.2 信号处理器路径（关键参考实现）

`vendor/oh-my-openagent/packages/omo-opencode/src/features/background-agent/process-cleanup.ts` 是最完整的参考实现：

- 注册 `SIGINT`、`SIGTERM`、`SIGBREAK`(win32)、`beforeExit`、`exit` 全套信号处理器
- 信号触发时 `cleanupAll()` 对所有注册的 manager 调 `shutdown()`
- `SIGINT`/`SIGTERM`/`SIGBREAK` 触发后 `scheduleForcedExit`：**6 秒超时 + 等 cleanup 完成后 `process.exit()`**
- `beforeExit`/`exit` 只调 cleanup 不强制退出

关键代码片段（`process-cleanup.ts:44-58`）：

```ts
function scheduleForcedExit(
  cleanupResult: void | Promise<void>,
  exitCode: number,
  exitAfterCleanup = false,
): void {
  if (!_scheduleForcedExitEnabled) return
  process.exitCode = exitCode
  const exitTimeout = setTimeout(() => process.exit(), 6000)
  void Promise.resolve(cleanupResult).finally(() => {
    clearTimeout(exitTimeout)
    if (exitAfterCleanup) {
      process.exit(exitCode)
    }
  })
}
```

注释明确说（`process-cleanup.ts:18-21`）：

> Signal handlers (SIGINT/SIGTERM/SIGBREAK/beforeExit/exit) remain registered because they are the real shutdown path and run `cleanupAll()` before the host actually terminates.

### 5.3 mcp-client-core 也独立注册信号处理器

`vendor/oh-my-openagent/packages/mcp-client-core/src/skill-mcp-manager/cleanup.ts:20-50` 也独立注册了 `SIGINT`、`SIGTERM`、`SIGBREAK` 信号处理器，注释明确说：

> Note: Node's 'exit' event is synchronous-only, so we rely on signal handlers for async cleanup.
> Signal handlers invoke the async cleanup function and ignore errors so they don't block or throw.
> Don't call process.exit() here - let the background-agent manager handle the final process exit.

## 六、security-analysis 插件现状：已经在用信号处理器

`.opencode/plugins/lib/timeline.ts:24-29` **已经用了 `process.on("exit")`**：

```ts
// 进程退出时同步 flush 所有未写入的 buffer（覆盖 Ctrl+C / process.exit 场景）
process.on("exit", () => {
  for (const [sessionID, buffer] of timelineBuffers) {
    if (buffer.length > 0) flushTimeline(sessionID);
  }
});
```

注释明确说"覆盖 Ctrl+C / process.exit 场景"——说明本仓已经知道 dispose hook 不可靠，已经在用信号处理器兜底。但目前只用于 flush timeline 日志，没有用于 kill 子进程。

## 七、opencode 自己的 MCP 子进程 kill 逻辑（参考）

`vendor/opencode/packages/opencode/src/mcp/index.ts:530-555` 用 finalizer kill MCP 子进程：

```ts
yield* Effect.addFinalizer(() =>
  Effect.gen(function* () {
    const clients = Object.values(s.clients)
    s.clients = {}
    yield* Effect.forEach(
      clients,
      (client) =>
        Effect.gen(function* () {
          const pid = client.transport instanceof StdioClientTransport ? client.transport.pid : null
          if (typeof pid === "number") {
            const pids = yield* descendants(pid)
            for (const dpid of pids) {
              try {
                process.kill(dpid, "SIGTERM")
              } catch {}
            }
          }
          yield* Effect.tryPromise(() => client.close()).pipe(Effect.ignore)
        }),
      { concurrency: "unbounded" },
    )
  }),
)
```

opencode 自己用 finalizer kill MCP 子进程（`process.kill(dpid, "SIGTERM")` + `descendants(pid)` 获取子孙进程），但**同样依赖 scope 被正确关闭**。如果 `process.exit()` 直接调用，这个 finalizer 也不会执行。

## 八、推荐方案

### 8.1 信号处理器组合

参考 oh-my-openagent `process-cleanup.ts` + 现有 `timeline.ts`，推荐组合：

| 信号 | 特性 | 用途 |
|------|------|------|
| `SIGINT` | Ctrl+C，可异步 | 主要 cleanup 路径，kill 子进程 + 等待 + `process.exit()` |
| `SIGTERM` | kill 命令，可异步 | 同 SIGINT |
| `beforeExit` | 进程无任务时，可异步 | 兜底 cleanup（但 `process.exit()` 不触发它） |
| `exit` | 退出前最后机会，**只能同步** | 最终兜底，`process.kill(pid, "SIGKILL")` |
| `dispose` hook | scope 正常关闭时 | 双保险（plugin reload / effectCmd 时生效） |

### 8.2 kill 子进程的要点

1. **记录子进程 PID**（spawn 时保存到注册表）
2. **`process.kill(pid, "SIGTERM")`** 优雅终止
3. **detached 进程必须显式 kill**（`spawn(..., { detached: true, stdio: "ignore" }).unref()` 的进程不会随父进程退出）—— opencode 的 MCP 子进程就是这种
4. **`process.on("exit")` 里只能同步操作**——不能 await，只能 `process.kill(pid, "SIGKILL")` 兜底
5. **用 `descendants(pid)` 获取子孙进程**——子进程可能又 spawn 了孙进程（如 idat 启动的 Python 子进程）

### 8.3 注册表模式（参考 oh-my-openagent）

```ts
interface CleanupTarget {
  shutdown(): void | Promise<void>
}

const cleanupManagers = new Set<CleanupTarget>()

export function registerManagerForCleanup(manager: CleanupTarget): void {
  cleanupManagers.add(manager)
  // 首次注册时安装信号处理器（幂等）
}

export function unregisterManagerForCleanup(manager: CleanupTarget): void {
  cleanupManagers.delete(manager)
  // 最后一个 manager 注销时卸载信号处理器
}
```

每个 manager 自己实现 `shutdown()`，在信号处理器里统一调 `cleanupAll()`。

## 九、可复用的现成代码位置

| 位置 | 用途 |
|------|------|
| `.opencode/plugins/lib/timeline.ts:24-29` | `process.on("exit")` 同步兜底的现成模式 |
| `vendor/oh-my-openagent/packages/omo-opencode/src/features/background-agent/process-cleanup.ts` | 完整参考实现：`registerManagerForCleanup` + `scheduleForcedExit` + 6 秒超时模式 |
| `vendor/oh-my-openagent/packages/mcp-client-core/src/skill-mcp-manager/cleanup.ts:20-50` | 信号处理器注册/注销模式（独立注册 SIGINT/SIGTERM/SIGBREAK） |
| `vendor/oh-my-openagent/packages/omo-opencode/src/plugin-dispose.ts` | dispose hook 路径的参考实现（双保险的一面） |
| `vendor/opencode/packages/opencode/src/mcp/index.ts:530-555` | `descendants(pid)` + `process.kill(dpid, "SIGTERM")` 的子孙进程 kill 模式 |

## 十、下一步

如果要在 security-analysis 插件里实现"退出时 kill opencode 打开的进程"（如 idat、frida、子 session），可以基于本调研进入进化流程的 Phase 1：讨论方案。需要关注：

1. **哪些进程需要 kill**：idat（IDA 批处理）、frida（动态分析）、子 session（opencode 子 agent）、其他 spawn 的进程
2. **PID 注册表放在哪**：可能是 `lib/process-registry.ts`，类似 `timeline.ts` 的模式
3. **kill 策略**：SIGTERM 优先 → 超时后 SIGKILL；detached 进程必须显式 kill
4. **与现有 `timeline.ts` 的 `process.on("exit")` 的关系**：是否合并到一个统一的 cleanup 模块
5. **dispose hook 是否也接入**：双保险，scope 正常关闭时也清理
