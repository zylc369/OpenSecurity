# 消除 .opencode-control.users —— 心跳机制

日期: 2026-08-22
状态: ✅ 已完成（11 步全部执行 + 审计通过 + 生产切换完成）

## 实施结果记录

- 四套测试: 单测 54/54 · 集成 5/5 · TS 10/10 · e2e_real 5/5 · 前端 E2E 40/40（顺带修复）
- 查缺补漏（超出原清单，审计第 1 轮发现）:
  - test/control/conftest.py 是 IPC 化时漏改的坏测试（等已删除的端口文件）——改为 IPC 发现 + 心跳防自杀；并修复 macOS AF_UNIX ≤104 字节限制（pytest tmp_path 超长 → bind 必败），DATA_DIR 改 /tmp 短路径。前端 E2E 由"完全跑不起来"恢复为 40/40
  - detect_py_deps 删除 portalocker 死依赖条目（零消费方）
- 生产切换: 旧控制台(users 版) 26529 SIGTERM → users 文件删除 → 新控制台(心跳版) 89587 + heartbeat-keeper 过渡守护（8h TTL，bun pid 见 keeper 日志；用户重启 opencode 后新插件接管心跳，keeper 到期自退，生态自洽）
- 生产验证: 假 pid 60s 被 sweep 精确移除、keeper 持续跳控制台不死、MCP 检索/console-url/前端 API 全 200
- 已知无害残留: 旧 opencode(插件为内存中旧代码) 退出时会重建一个空的 .opencode-control.users 文件（新控制台不读，可手动删）
前置: `2026-08-20-ipc-no-port-files.md`（IPC 化消除了端口文件；本文消除最后一个跨语言共享状态文件）

## §1 背景与目标

**来源痛点**: IPC 化改造（2026-08-20）消除了 3 个状态文件，`users` 文件是最后一个残留。它需要双端（Python 控制台 + Bun 插件）维护严格一致的文件格式协议、原子写、PID 存活检测、start_time 复用防护——全是易错代码。期间真实发生的事故：过渡期运维手写 users 文件时写死旧 PID → 控制台每 60s 自杀循环。

**用户方案**: opencode 插件每 10 秒调用一次控制台告诉自己活着；控制台后台线程每 10 秒遍历内存表，超过 60 秒未收到某心跳 → 移除；表空 → 控制台自杀。

**预期收益**:
- 删除最后一个跨语言共享状态文件及整套协议代码（净减 ~250 行）
- 消灭一类 bug：文件格式解析、双端原子写竞态、PID 复用、残留清理
- 引用计数从"写时协议"变"运行时活性"——语义更直接

**用户已确认接受的代价**:
- 最后一个 opencode 退出后控制台多活 ≤60s（快速重启直接复用热控制台）
- 控制台事件循环阻塞 >60s 会误自杀（心跳路由 O(1)，概率极低，自愈闭环兜底）

## §2 技术方案

### 协议

```
插件端（每 10s）:  POST /api/heartbeat   body: {"pid": <opencode pid>}
控制台端:          内存表 {pid → last_seen(monotonic)}，Lock 保护
                  HeartbeatTask 每 10s sweep: 过期(>60s)移除; 表空且过宽限期(90s) → 自杀(EXIT_CODE_NORMAL)
```

**键 = 裸 pid**（不需要 start_time）: OS 保证同 pid 进程不同时存活。旧进程死 → 停跳 → 条目 60s 后被 sweep 移除；若新进程复用同 pid，其心跳刷新 last_seen，语义仍为"该 pid 活着"，无歧义。原 start_time 复用防护是为文件残留场景设计的——内存表无残留，问题不存在。

### 3 个关键设计点（用户已确认）

1. **首跳立即 + 启动宽限**: `startControl` 就绪后立即发首跳（不等周期）；控制台启动后 90s 内表空不自杀（spawn 者的 `waitForIpcReady` 窗口 8s + 首跳余量）。防"控制台刚起就判空自杀"循环。
2. **TS 侧 `setInterval` 必须 `.unref()`**: 不 unref 会挂住 opencode 事件循环 → opencode 僵尸 + 心跳永不停 → 控制台永不死。这是全方案最致命细节。心跳 Promise 链必须 `.catch()`（防 unhandled rejection 炸宿主）。
3. **HeartbeatSender 幂等**: `start()` 已在跳则直接返回（多 session/多次 hook 触发防重复 interval）。

### 改动文件

| 文件 | 动作 |
|---|---|
| `control/backend/services/heartbeat.py` | **新增** HeartbeatRegistry（dataclass 条目 + Lock + record/sweep/active_count）+ HeartbeatTask（周期 sweep + 宽限 + 自杀回调） |
| `control/backend/routes/heartbeat.py` | **新增** `POST /api/heartbeat` |
| `control/backend/config.py` | 新增 4 常量（env 可覆盖，供测试注入小值）；删 USERS_FILE、USERS_CLEANUP_INTERVAL_SEC |
| `control/backend/server.py` | UsersCleanupTask → HeartbeatTask；include heartbeat router |
| `control/backend/services/ref_counter.py` | **删除整文件** |
| `control/backend/services/process_lock.py` | 删 is_process_alive（atomic_write 保留，config_store 在用） |
| `control/backend/services/detect_py_deps.py` | pywin32 描述改为 Windows 命名管道用途 |
| `plugins/lib/heartbeat.ts` | **新增** HeartbeatSender 类（首跳立即 + 10s interval unref + catch 全吞 + 幂等 start/stop） |
| `plugins/lib/control-manager.ts` | 删 users 调用（cleanupDeadUsers/addSelfToUsers/removeSelfFromUsers）、删整个 exit handler（registerExitHandler）；接 HeartbeatSender.start()；spawn env 注释更新 |
| `plugins/lib/ref-counter.ts` | **删除整文件** |
| `plugins/lib/process-utils.ts` | **删除整文件**（唯一实质消费方是 ref-counter；心跳裸 pid 后 start_time 检测无消费方） |
| `plugins/lib/constants.ts` | 删 CONTROL_USERS_FILE；新增 HEARTBEAT_INTERVAL_MS = 10_000（注释注明与 Python 端 HEARTBEAT_TIMEOUT_SEC 协议配对） |
| `plugins/security-analysis.ts` | 注释更新（"加自己 PID 到 users 文件" → "启动心跳"） |
| `control/backend/tests/test_control.py` | users 组改写为 heartbeat 组 |
| `control/backend/tests/test_integration.py` | users 流程改写为心跳流程（env 注入小超时真实验证自杀/存活） |
| `plugins/tests/test-control.ts` | users/process-utils 组改写为 heartbeat 组 |

### 数据结构（规则 9 强类型）

```python
@dataclass
class HeartbeatEntry:
    pid: int
    last_seen: float  # time.monotonic()

class HeartbeatRegistry:
    _entries: dict[int, HeartbeatEntry]
    _lock: threading.Lock
    def record(self, pid: int) -> None
    def sweep(self, now: float, timeout_sec: float) -> int  # 返回移除数
    def active_count(self) -> int

class HeartbeatTask:  # 同 UsersCleanupTask 模式
    def __init__(self, shutdown_callback: Callable[[], None]) -> None
    def start(self) -> None / def stop(self) -> None
```

```typescript
class HeartbeatSender {  // 模块级单例
  private timer: Timer | null
  start(): Promise<void>   // 幂等; 首跳立即
  stop(): void             // clearInterval
}
```

## §3 实现规范

- 遵守现有依赖方向；heartbeat.py 只依赖 config + 标准库 + logging
- 所有关键路径打日志（规则 10）: 首跳成功/失败、sweep 移除、宽限期内空表、自杀触发、心跳收到新 pid
- 心跳路由挂载后 `/health` 语义不变
- 删除功能时连带删除全部引用，grep 验证零残留（规则 8.6——不留墓碑注释、不写"原 users 机制"说明）

### §3.1 实施步骤

```
1. Python 心跳核心
   - 文件: config.py（+4 常量）、services/heartbeat.py（新增）
   - 预估行数: ~110
   - 验证点: compile 过 + python -c 手动 record/sweep/宽限行为符合预期
   - 依赖: 无

2. server.py 接入 + 路由
   - 文件: server.py（UsersCleanupTask→HeartbeatTask + include_router）、routes/heartbeat.py（新增）
   - 预估行数: ~45
   - 验证点: compile 过 + 临时 DATA_DIR 起真控制台: POST 心跳 200 + 表有条目 + 无 users 引用
   - 依赖: 1

3. Python 侧删除
   - 文件: services/ref_counter.py（删）、process_lock.py（删 is_process_alive）、detect_py_deps.py（描述）、routes/ocr.py（注释里的 ref_counter 协议表述）、config.py（EXIT_CODE_NORMAL 注释）
   - 预估行数: -170
   - 验证点: rg 'ref_counter|USERS_FILE|is_process_alive|users' backend/ 零业务残留（测试文件除外）+ compile 全过
   - 依赖: 2

4. TS HeartbeatSender
   - 文件: plugins/lib/heartbeat.ts（新增）、constants.ts（+HEARTBEAT_INTERVAL_MS）
   - 预估行数: ~70
   - 验证点: bun build 过 + 单文件行为冒烟（fake fetch 计数）
   - 依赖: 无

5. TS 侧接入 + 删除
   - 文件: control-manager.ts（删 users 调用+exit handler、接 sender）、security-analysis.ts（注释）、constants.ts（删 CONTROL_USERS_FILE）
   - 预估行数: 净 -60
   - 验证点: bun build 过 + rg 'Users|users' plugins/lib plugins/security-analysis.ts 零业务残留
   - 依赖: 4

6. TS 侧删文件
   - 文件: plugins/lib/ref-counter.ts（删）、plugins/lib/process-utils.ts（删）
   - 预估行数: -258
   - 验证点: rg 零引用 + bun build 过
   - 依赖: 5

7. test_control.py 改写
   - 文件: tests/test_control.py
   - 预估行数: 净 ±80（users 组 → heartbeat 组: record/sweep 过期/宽限/幂等键/HeartbeatTask 触发）
   - 验证点: 单测全绿（59 - users组 + heartbeat组）
   - 依赖: 3

8. test_integration.py 改写
   - 文件: tests/test_integration.py
   - 预估行数: ±60（心跳存活流程 + 停跳自杀流程，env 注小超时）
   - 验证点: 集成全绿
   - 依赖: 2

9. test-control.ts 改写
   - 文件: plugins/tests/test-control.ts
   - 预估行数: ±70（users/process-utils 组 → heartbeat 组）
   - 验证点: TS 全绿
   - 依赖: 5, 6

10. 全量回归
    - 验证点: 四套齐绿（单测/集成/TS/e2e_real）
    - 依赖: 7, 8, 9

11. 生产切换
    - 动作: SIGTERM 旧控制台 → rm users 文件 → spawn 新控制台（detached，生产 DATA_DIR）
    - 验证点: uds+TCP health 200 + 真实心跳入表（生产 opencode pid）+ 90s 后不自杀 + plugin.log 见首跳日志
    - 依赖: 10
```

## §4 验收标准

**功能验收**:
- [x] users 文件从盘上消失，全仓无引用（rg 验证）
- [x] 心跳入表: POST /api/heartbeat → active_count=1
- [x] 停跳 60s（测试注入小值）→ 控制台自杀（exit code 同 EXIT_CODE_NORMAL 语义）
- [x] 宽限期内表空不自杀
- [x] opencode 快速重启（<60s）复用热控制台，新首跳续命
- [x] TS interval unref（opencode 可正常退出）

**回归验收**:
- [x] 四套测试全绿（单测/集成/TS/e2e_real 5 真链路）
- [x] 生产控制台切换后: MCP 检索可用、前端 /api 代理 200、vite 上报正常

**架构验收**:
- [x] 依赖方向不变（heartbeat.py 不依赖上层）
- [x] 无墓碑注释/死代码残留（rg 零命中）
- [x] 规则 9: dataclass + 类封装 + 单例，无裸 dict 传递

## §5 与现有需求文档的关系

- `2026-08-20-ipc-no-port-files.md`: IPC 化的续篇。IPC 消除端口文件，本文消除 users 文件——完成后 DATA_DIR 内零控制台状态文件（仅 IPC socket 本身，由内核生命周期管理）
- 该文档 §6/§7 的演进记录中"users 机制保留"的表述以本文为准
