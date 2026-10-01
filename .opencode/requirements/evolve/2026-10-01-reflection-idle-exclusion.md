# 2026-10-01 反思时钟空闲扣除（活跃时长口径）— 实施需求

> 状态：已实施（2026-10-01，步骤 1-4 完成；插件测试全绿 + pyright 0/0/0；活体验证待 opencode 重启，见 §4.2）。
> 来源：反思系统（2026-09-29）上线后的复盘——`isReflectionDue` 为纯墙钟判定，会话空闲时长全额计入间隔：空闲数小时后恢复活动的第一次检查立即命中，反思纸条/唤醒在"几乎没干活"时触发，且"距上次盘点 X 分钟"与"期间工具调用 N 次"数字自相矛盾。用户提供修复方案（空闲窗口 + 累计空闲 + 消费方扣除）并经两轮评审定稿；运行中系统睡眠不纳入处理（用户裁决，边界见 §2.5）。

## §1 背景与目标

### 1.1 现状（代码级三处咬合）

- `reflection.ts:isReflectionDue`：`Date.now() - session.lastReflectionAt >= 间隔`——纯墙钟，无空闲扣除。
- `lastReflectionAt` 唯一更新点是 `markReflectionFired`（发射纸条/唤醒时重置）；初值 = 会话创建时刻。
- 消费点两处：忙通道 `maybeAttachReflectNudge`（每条 bash）、空闲通道 `maybeResumeAnalysis`（每次 `session.idle`，反思分支优先于 resume）。

### 1.2 问题场景（均为可达路径）

用户中断（Esc）后离开数小时返回；任务完成后隔天复用同一会话；达 MAX_RESUMES / 超 8h 上限 / 关闭 resume 后长时间空闲；会话创建后久未使用。表现为：恢复后第一条 bash 立即附加纸条（例："距上次盘点 300+ 分钟；期间工具调用 2 次"），或首次 idle 直接发强制反思唤醒（替代 resume）。

### 1.3 目标

- 到期判定与全部展示数字改用"净活跃时长" = 墙钟跨度 − 会话空闲窗口累计。
- 空闲窗口 = `session.idle` 事件到下一次消息之间（该区间无执行）；"出生即空闲"覆盖创建→首次使用（该区间无 idle 事件）。
- 明确的"活跃"定义：会话运行期间的墙钟（含模型生成、工具执行、权限等待）计入；空闲窗口不计入。
- 不影响 resume 冷却、MAX_DURATION、`elapsedMinutes` 等其他墙钟机制（范围纪律，见 §2.5）。

### 1.4 预期收益

- 准确度：消除长空闲后的假触发（每命中一次省一次无依据的盘点/强制反思回合），触发前提与展示数字自洽。
- 该缺陷呈潜伏态（日志中暂无长空闲样本），首次"隔天续用/中断返场"即命中。

## §2 技术方案

### 2.1 新增字段（plugins/lib/session-manager.ts · SessionData）

| 字段 | 类型 / 初值 | 语义 |
|---|---|---|
| `idleAt` | `number \| null`，初值 = 构造时刻 | 当前空闲窗口起点；`null` = 无未结算窗口 |
| `totalIdleMs` | `number` = 0 | 会话累计已结算空闲（会话指标，不随反思清零） |
| `idleSinceReflectionMs` | `number` = 0 | 上次反思发射以来累计空闲（反思累加器，发射时清零） |

### 2.2 新增方法（SessionData，状态私有化 + 方法读写——规则 9）

```ts
/** 标记空闲窗口开启（幂等；已开窗口保留最早起点，不覆盖） */
markIdle(now = Date.now()): void
  if (idleAt === null) idleAt = now

/** 结算空闲窗口（幂等）：同时累加两个计数器后关闭窗口；返回结算时长（未开窗=0） */
settleIdle(now = Date.now()): number
  if (idleAt === null) return 0
  d = now - idleAt
  idleAt = null
  totalIdleMs += d
  idleSinceReflectionMs += d
  if (d >= IDLE_SETTLE_LOG_THRESHOLD_MS /* 60_000，模块级命名常量 */) debugLog(窗口结算日志)
  return d

/** 距上次反思的"净活跃时长"：墙钟跨度 − 已结算空闲（开放窗口不参与） */
activeMsSinceReflection(now = Date.now()): number
  return now - lastReflectionAt - idleSinceReflectionMs
```

**不变量**（实现时必须写进注释）：

1. 空闲窗口只能被 `settleIdle` 关闭；`markIdle` 不覆盖已开窗口（保留最早）。
2. `markReflectionFired` 只清 `idleSinceReflectionMs`，**不清 `idleAt`**——唤醒通道发射时窗口刚好打开，该窗口属于"本次反思之后"的新批次，由下次结算累加进新累加器。
3. `settleIdle` 幂等；触点单点收口在 `chat.message` 的 `finally`。

### 2.3 读写触点（全部落在现有 hook，无新钩子）

| 触点 | 位置 | 动作 | 覆盖 |
|---|---|---|---|
| `session.idle` 事件 | security-analysis.ts event hook 的 idle 分支顶部（`activelyTerminated` 判定之前） | `session?.markIdle()` | 一切"停止运行"转移（用户中断、resume 关闭/封顶、超时等） |
| `chat.message` 钩子 `finally` | security-analysis.ts（try/catch 之后的 `finally`） | `get(sessionID)?.settleIdle()` | 全部消息入口单点收口：覆盖 RECOVER-MODE / 无 agent 注入 / 错误回调等早退与异常路径；会话在本消息内首次创建（upsert 兜底/插件重启重建）时已存在，出生窗口（≈ 钩子处理时长）一并结算 |

### 2.4 判定与展示改造

- `isReflectionDue(session, configReader = getCachedConfig)`：`session.activeMsSinceReflection() >= getReflectIntervalMs(configReader)`。新增的 `configReader` 参数仅为测试注入，风格对齐同模块 `isReflectEnabled / getReflectIntervalMs`；现有两个调用点（reflection.ts 纸条、persistence.ts 唤醒）不传该参，行为不变。
- `markReflectionFired`：`sinceMin = activeMinutesSinceReflection(session, now)`——净活跃分钟、两位小数四舍五入（`Math.round(ms/600)/100`，下限 0.01；先算后清的顺序敏感约束保留）；随后 `lastReflectionAt = now; idleSinceReflectionMs = 0`（其余字段逻辑不变）。函数头注释更新为包含 `idleSinceReflectionMs` 的更新点说明。
- `persistence.ts` 到期日志：`净活跃 ${activeMinutesSinceReflection(session)}min`（与 sinceMin 共用同一导出函数，展示口径单一来源）。
- 保持墙钟（范围纪律）：`MAX_DURATION`（`lastUserMessageAt`，离席配额预算）、resume 冷却（毫秒级节流）、`elapsedMinutes`（唤醒文案"已运行"= 会话龄，运营数字）。

### 2.5 明确不做（已声明边界）

- **运行中系统睡眠（合盖）**：睡眠期进程冻结、无事件、无 idle 标记，该时长计入活跃 → 醒来后首个检查可能提前触发一次反思。检测方案（事件缺口推断 / 墙钟×单调钟漂移 / 内核睡眠记录 sysctl）经评估复杂度超预算，用户裁决放弃，作为已知边界接受。
- 时间源仍为 `Date.now()`；不引入新依赖；不新增配置项。

### 2.6 架构影响

- 改动文件：`plugins/lib/session-manager.ts`（字段/方法）、`plugins/lib/reflection.ts`（判定与状态更新）、`plugins/lib/persistence.ts`（日志口径）、`plugins/security-analysis.ts`（2 触点）、`control/backend/services/config_manager.py`（配置 hint 文案 1 行）；新增测试 `plugins/tests/test-reflection-clock.ts`。
- 无新模块、无依赖方向变化、无循环；无 agent prompt / skill 改动。

## §3 实现规范

### 3.1 实施步骤

步骤 1. SessionData 空闲时钟（字段 + 方法 + 日志常量）
- 文件：`plugins/lib/session-manager.ts`（约 +55 行，含 `lastReflectionAt` 字段注释补判定口径交叉引用）、`plugins/tests/test-reflection-clock.ts`（新建，T1-T4 约 90 行；T5-T8 由步骤 2 追加）
- 验证点：T1-T4 用例通过（`OPENSECURITY_HOME=/tmp/reflection_clock_test bun .opencode/plugins/tests/test-reflection-clock.ts`）；既有 `test-reflection-config.ts` 不被破坏
- 依赖：无

步骤 2. 判定与发射改造 + 日志口径
- 文件：`plugins/lib/reflection.ts`（约 +15 行）、`plugins/lib/persistence.ts`（约 ±3 行）
- 验证点：T5-T8 用例通过；grep 确认净活跃口径消费点齐备——`activeMsSinceReflection`（判定 / 展示 helper）与 `activeMinutesSinceReflection`（markReflectionFired / persistence 日志）
- 依赖：步骤 1

步骤 3. 触点接线 + 全量回归
- 文件：`plugins/security-analysis.ts`（`chat.message` 的 `finally` 结算 + idle 分支开窗，约 +8 行）
- 验证点：grep 断言触点存在且位置正确——`security-analysis.ts` 中 `settleIdle` 1 处（chat.message `finally`）、`markIdle` 1 处（idle 分支、`activelyTerminated` 判定前）；`session-manager.ts` 中无 `settleIdle` 调用（仅方法定义）；新测试 + 既有插件测试全部通过；插件语法/类型检查通过（`bun build --target=bun` 或仓库既有方式）
- 依赖：步骤 2

步骤 4. 配置 hint 文案对齐（净活跃口径）
- 文件：`control/backend/services/config_manager.py`（1 行：hint 改为"净活跃时长（扣除会话空闲）超过该间隔即注入提醒; 默认 30 分钟，改后 30s 内生效"）
- 验证点：控制台测试（test_control / test_config_manager）继续通过；meta 接口返回新 hint
- 依赖：无（可与步骤 1-3 并行）

### 3.2 编码规则

1. §2.2 三条不变量必须写入代码注释；触点顺序原因（早退路径覆盖）写入调用点注释。
2. 规则 10 日志：`markIdle` 开窗记一条；`settleIdle` 窗口 ≥60s 记结算日志（含会话累计空闲）；`markReflectionFired` 既有日志保留。
3. 规则 9：状态与方法收在 SessionData；判定保持薄壳；日志阈值用模块级命名常量，不散魔术数。

## §4 验收标准

### 4.1 功能验收

- F1 空闲不累计：`lastReflectionAt` 后开启并结算空闲窗口 W，再经历 W 的工作时间 → 未到期；继续工作至净活跃 = 间隔 → 到期。
- F2 跨周期不重复扣除：发射后的第二周期按"新增空闲之后"的净活跃判定，不受历史空闲影响（旧公式会负向偏置数小时——回归用例必测）。
- F3 出生即空闲：会话创建 → 首次使用之间的时长被计为空闲（首条消息结算扣除）。
- F4 展示口径：纸条/唤醒"距上次盘点 X 分钟"与两处日志的 X = 净活跃分钟；唤醒通道发射后开放窗口不清（由下一批结算）。
- F5 触点覆盖：三条触点真实存在（grep + 走查）；幂等可重复调用。

测试清单（`plugins/tests/test-reflection-clock.ts`；沙箱 OPENSECURITY_HOME 守卫与运行方式同既有测试文件）：
- T1 出生即空闲与首次结算（created→首次使用 ≈ 5min 场景；立即结算 ≈0 场景）
- T2 `markIdle` 幂等/保留最早；`settleIdle` 双计数器累计 + 关闭 + 二次调用返回 0
- T3 `activeMsSinceReflection` 三态（无空闲 / 已结算扣除 / 开放窗口不参与）
- T4 开窗/结算日志冒烟（沙箱下方法不抛异常）
- T5 `isReflectionDue` 边界（configReader 注入：净活跃 29.9min 否 / 30.1min 是）
- T6 `markReflectionFired`：先算后清（sinceMin≈20.25min 样本；两位小数四舍五入与 0.01 下限用例）、`idleSinceReflectionMs` 归零、`idleAt` 保持、计数递增、工具差正确
- T7 跨周期回归（F2 样本：旧公式会误判、新公式正确）
- T8 全链路序列模拟（markIdle → settle → 工作 → 发射 → 再循环）

### 4.2 回归验收

- 既有插件测试（`test-reflection-config.ts` 等）通过；控制台测试通过（步骤 4）。
- 插件加载冒烟（opencode 重启后 plugin_debug.log 无编译错误）——交付后由用户重启验证。
- 可选活体验证（重启后）：将 `REFLECT_NUDGE_INTERVAL_MIN` 调小（如 1），人为制造空闲窗口，观察任务级 plugin.log 中"空闲窗口结算"日志与反思触发数字为净活跃口径、空闲不触发假到期。
- resume 机制零行为变化（未触及）；`REFLECT_NUDGE_INTERVAL_MIN` 消费链不变。

### 4.3 架构验收

- 落位合规；无依赖方向变化/循环；规则 9 满足（状态在类内）；无 agent prompt 改动（Phase 4.5 不适用）。

## §5 与现有需求文档的关系

- `2026-09-29-reflection-system.md`：本需求修正其 §2.3 到期公式（`now − lastReflectionAt ≥ 间隔` → 净活跃口径）。两通道、守卫、文案、自停机制全部不变。
- `2026-09-30-config-surface-categories.md`：`REFLECT_NUDGE_INTERVAL_MIN` 配置项消费链不变；其面向用户的语义由墙钟变为净活跃，hint 文案对齐随本需求执行（步骤 4）。
- 睡眠检测：曾评估三方案（缺口推断 / 双钟漂移 / 内核睡眠记录），用户裁决不做，边界见 §2.5。

## §6 执行记录（2026-10-01）

- 步骤 1-4 全部完成，改动与 §2/§3.1 一致：
  - `session-manager.ts`：`IDLE_SETTLE_LOG_THRESHOLD_MS` 常量 + 三字段 + 三方法（不变量注释）；
  - `reflection.ts`：`isReflectionDue`（净活跃 + `configReader` 注入）、`markReflectionFired`（先算后清 + `idleSinceReflectionMs` 归零、不清 `idleAt`）；
  - `persistence.ts`：到期日志净活跃口径；
  - `security-analysis.ts`：chat.message 顶部结算 + session.idle 分支开窗（`activelyTerminated` 之前）；
  - `config_manager.py`：hint 对齐净活跃口径。
- 验证证据：新测试 8/8；既有插件测试全绿（reflection-config 2/2、permission-timeout 17/17、control 11/11）；`bun build` 编译冒烟通过；pyright 全量 0 errors / 0 warnings / 0 notes；8 个产出文件不可见字节零命中。
- 后端测试基线对照：`test_config_manager.py` 7/9、`test_control.py` 92/93 中失败的 3 例在 HEAD 版本原样复现，属"行为变更未同步测试断言"（权限超时默认值 300→60、IDA_PRO_HOME required 放宽、/api/config 迁移 POST 漏同步 test_remote_routes）——已于 2026-10-01 全部修复，与本次改动无关。
- 待办：opencode 重启后做插件加载冒烟与（可选）活体验证。
- 用户评审修订（3 点）：
  ① `activeMsSinceReflection` 去掉"开放窗口"扣减项（窗口在消息入口整体结算；评估点处开放窗口不存在或刚开启 ≈0）——公式简化为 `墙钟 − 已结算空闲`；
  ② `sinceMin` 改两位小数四舍五入（新导出 `activeMinutesSinceReflection`：`Math.round(ms/600)/100`，下限 0.01），`markReflectionFired` 与 persistence 日志共用同一函数；
  ③ `settleIdle` 触点收敛为 `chat.message` 的 `finally` 单点（替代原"钩子顶部 + upsert 内"两处；覆盖全部早退/异常路径，消息内首次创建场景由 finally 处已存在的会话结算）。
  回归：T1-T8 全过 8/8 + 既有插件测试全绿（2/2、17/17、11/11）+ 编译冒烟 ✓。
