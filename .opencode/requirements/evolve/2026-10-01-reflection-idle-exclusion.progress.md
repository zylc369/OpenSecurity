# 2026-10-01 反思时钟空闲扣除 — 执行进度

## Phase 0/1 复盘与讨论（完成）

- 发现：`isReflectionDue` 纯墙钟判定；`lastReflectionAt` 仅在发射时更新 → 长时间空闲后恢复活动的第一次检查立即命中（假触发 + "距上次盘点 X 分钟"与工具计数矛盾）。
- 用户方案：SessionData 记录空闲窗口起点 + 累计空闲；消费方扣除空闲得"真实需要关注的时间长度"。
- 评审修正：P1 周期内累加器（防跨周期重复扣除，原"会话总空闲"直接减会负向偏置数小时）；P2 状态机三规则（出生即空闲 / markIdle set-once / 触点覆盖全部消息入口）；P4 范围纪律（仅反思链路切净活跃；MAX_DURATION、resume 冷却、elapsedMinutes 保持墙钟）。
- 用户裁决：睡眠（合盖）检测放弃——缺口推断/双钟漂移/内核 sysctl 三方案复杂度超预算；运行中睡眠计入活跃，作为已声明边界。
- 证据：代码走查 reflection.ts:92-114/174、persistence.ts:312-314、session-manager.ts:84；真实日志长空闲样本暂无（潜伏缺陷）；配置 hint 文案无测试断言（grep 零命中）；探针实验（bun/node 双运行时）已启动后按裁决全部清理。

## Phase 2 需求文档（完成）

- 产出：`requirements/evolve/2026-10-01-reflection-idle-exclusion.md`（158 行）
- 含：§1 背景/§2 技术方案（字段、方法、不变量、触点、改造、边界）/§3.1 四步（各 ≤200 行）/§4 验收（T1-T8）/§5 文档关系。

## Phase 3 需求审计（完成：2 轮审+修 → 纯审计零问题）

- R1（3 处修正）：chat.message 触点精确到 "try 内、RECOVER-MODE 前"；步骤 1 补 `lastReflectionAt` 注释同步与测试文件步骤拆分说明；步骤 3 grep 断言具体化。
- R2（3 处修正）：沙箱路径具体化为 `/tmp/reflection_clock_test`；测试清单补"沙箱守卫同既有测试"；§4.2 补可选活体验证项。
- 纯审计轮：零问题 → 通过。

## Phase 4 执行计划确认（完成）

- 步骤顺序：1 → 2 → 3（步骤 4 独立并行）；遗漏检查：无新增步骤。
- 架构影响图（5 文件 + 1 新测试）：
```
session.idle ──markIdle────────────▶ SessionData.idleAt
chat.message(finally) ─settleIdle──▶ {totalIdleMs, idleSinceReflectionMs, idleAt=null}
isReflectionDue ◀── activeMsSinceReflection()（净活跃口径 = 墙钟 − 已结算空闲）
markReflectionFired ──先算后清（activeMinutesSinceReflection，两位小数）──▶ idleSinceReflectionMs=0（不动 idleAt）
persistence 日志 ◀── activeMinutesSinceReflection()
config_manager.py hint（步骤 4，独立文案）
```

## Phase 5 执行（完成）

### 步骤 1 完成：SessionData 空闲时钟（字段 + 方法 + 日志常量）

- 改动：`session-manager.ts` 新增 `IDLE_SETTLE_LOG_THRESHOLD_MS` 常量、`idleAt/totalIdleMs/idleSinceReflectionMs` 三字段、`markIdle/settleIdle/activeMsSinceReflection` 三方法（含不变量注释）；`lastReflectionAt` 注释补判定口径交叉引用。
- 新增测试：`tests/test-reflection-clock.ts`（T1-T4）。
- 验证证据：`bun build` 编译冒烟 ✓；新测试 T1-T4 通过 4/4 ✓；既有 `test-reflection-config.ts` 回归通过 2/2 ✓。

### 步骤 2 完成：判定与发射改造 + 日志口径

- 改动：`reflection.ts`（`isReflectionDue` 净活跃 + `configReader` 注入；`markReflectionFired` 先算后清 + `idleSinceReflectionMs` 归零、不清 `idleAt`）、`persistence.ts`（到期日志净活跃口径）。
- 验证证据：编译冒烟 ✓；T1-T8 全通过 8/8 ✓；grep 确认净活跃口径消费点（`activeMsSinceReflection`：判定/展示 helper；`activeMinutesSinceReflection`：sinceMin/日志）。

### 步骤 3 完成：触点接线 + 全量回归

- 改动：`security-analysis.ts` 两触点（chat.message 结算、session.idle 开窗）；评审修订轮将结算单点收敛至 chat.message `finally`（原"钩子顶部 + upsert"两处取消，见文末"评审修订轮"）。
- 验证证据：grep 断言 + 上下文读取确认三点位置正确 ✓；插件全量测试——reflection-clock 8/8、reflection-config 2/2、permission-timeout 17/17、control 11/11 ✓；`security-analysis.ts` 编译冒烟 ✓。

### 步骤 4 完成：配置 hint 文案对齐

- 改动：`config_manager.py` 1 行（hint → 净活跃口径）。
- 验证证据：py_compile ✓；pyright 全量 0 errors / 0 warnings / 0 notes ✓；后端测试与基线一致（无新增失败）；旧配置需求文档未逐字引用 hint 文案，无文档漂移 ✓。

### 基线对照（既有失败，与本需求无关——已实证）

- `test_config_manager.py` 7/9、`test_control.py` 92/93、`test_remote_routes.py` 4/5 中的失败在 **HEAD 版本原样复现**；根因（2026-10-01 修复时确认）：行为/契约变更未同步消费方测试断言——① 权限超时默认值 300→60 ② IDA_PRO_HOME required 放宽 ③ /api/config 迁移 POST 契约漏同步 test_remote_routes。**均已于 2026-10-01 修复并全量回归**（9/9、93/93、5/5 + e2e_remote 全过）。
- 处置：本需求范围外；修复记录见测试盲区模式 P（契约/行为变更消费方清算）。

## Phase 6 实现审计（完成：2 轮审+修 → 纯审计零问题）

- R1（走查+修正）：5 文件 diff 全量逐条对照需求文档（一致，无逻辑问题）；8 文件不可见字节扫描零命中；`lastReflectionAt` 残留消费点核查（仅字段本体 + `activeMsSinceReflection` + `markReflectionFired`，无遗留墙钟消费）；新符号全仓引用核查（仅 4 个预期文件）；架构地图粒度核查（plugins 目录级、不含测试清单，无需更新）。
- R2（修正）：`settleIdle` 未开窗路径补"安静返回、不记日志"注释（高频路径日志策略显式化）。
- 纯审计轮：零问题 → 通过。
- R2 后复验：编译 ✓ + 字节扫描 ✓ + 四套插件测试重跑全绿 ✓。

## 待办

- opencode 重启后：插件加载冒烟（plugin_debug.log 无编译错误）+ 可选活体验证（REFLECT_NUDGE_INTERVAL_MIN 调小，观察"空闲窗口结算"日志与净活跃触发数字）。

## 评审修订轮（用户 3 点，2026-10-01）

1. `activeMsSinceReflection` 去掉开放窗口扣减项（公式 = 墙钟 − 已结算空闲）；T3 断言同步（开放窗口不参与）。
2. `sinceMin` 改两位小数四舍五入——新增导出 `activeMinutesSinceReflection`（`Math.round(ms/600)/100`，下限 0.01），`markReflectionFired` 与 persistence 日志共用；T6 样本改 20.25 并补四舍五入/下限用例。
3. `settleIdle` 触点收敛到 `chat.message` 的 `finally` 单点（删除钩子顶部与 upsert 两处调用）。

验证：T1-T8 全过（8/8）+ 既有插件测试全绿（2/2、17/17、11/11）+ 四文件编译冒烟 ✓。

