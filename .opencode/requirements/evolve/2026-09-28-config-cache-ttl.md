# 需求: 配置缓存 TTL 化 + agent shell 业务键注入删除

> 状态: 已实施（见 §6 实施结果）
> 日期: 2026-09-28
> 前置: `2026-09-27-spawn-env-whitelist.md`（控制台 spawn 白名单化——本需求是
> env 治理的第二阶段: agent shell 通路）

## §1 背景与目标

**来源**: 白名单化复盘后的两个发现（用户裁决）:

1. **agent shell 业务键注入无消费方**（实证）: shell.env hook 将 .ai_env 全部键
   注入 agent bash（DEEPSEEK_API_KEY/JULIANG_API_KEY 实测在 env 中），但全仓
   grep 证实 agent 脚本/知识库/prompt/agents-rules/commands 对这些键**零引用**;
   后端消费方已全部走 ConfigManager 直读 .ai_env（白名单化的前置迁移）。
   注入面纯属风险（提示注入诱导 `env` 一发即外带业务密钥）而无收益。
2. **配置缓存 staleness 是真实缺陷**: 刷新仅 2 处（启动预热 + 冷却恢复前主动刷），
   无 TTL/变更推送——用户在配置页改 checkpoint 开关/IDA 路径后，agent 侧保持
   旧值直到 opencode 重启。冷却恢复路径的"先 refreshConfig 再校验"补丁
   （persistence.ts:358）证明滞后已在真实路径造成过问题。

**预期收益**:
- agent bash 的业务密钥注入面消除（提示注入外带面消除）
- 配置变更 30s 内全端生效（现状: 重启才生效）
- 控制台短暂不可用时配置读取不挂（TTL 内缓存兜底 + 刷新失败保留旧值）

## §2 技术方案

### §2.1 control-config.ts 缓存层改造

现状三个导出: `refreshConfig()` / `getAllConfig()` / `getCachedConfig()`。
问题: `getAllConfig`（null 才引导，否则返缓存）与 `getCachedConfig` 语义重复，
且"有时直读有时缓存"的暧昧行为没有存在价值（用户裁决）。

改造（3 → 2，语义正交）:

1. **`refreshConfig()` + `getAllConfig()` → 合并为 `fetchConfig()`**:
   - `fetchConfig(): Promise<Record<string, string>>`——**无缓存直读**语义:
     每次调用都请求控制台 `/api/config` 拿最新
   - 成功: 顺带更新 TTL 缓存（`cachedConfig` + `cachedAt`）并返回
   - 失败: throw（旧缓存保留——2026/9/14 事故教训注释在档）
   - 消费场景: 低频 + 要新鲜的异步路径（恢复校验、启动预热）——本地
     IPC 毫秒级，直读无压力
2. **`getCachedConfig()` 加 TTL + SWR（stale-while-revalidate）**:
   - 同步消费方（自动受益，无需改动）: shell.env 的 IDAT 注入
     （security-analysis.ts L1269）、chat.params 的 IDA 配置提示（L367）、
     认知检查点开关（checkpoint.ts L56——30s 感知上限，替代现状的
     "重启才生效"）
   - 新常量 `CONFIG_CACHE_TTL_MS = 30_000`
   - TTL 未过期 → 返回缓存（与现状同）
   - TTL 过期 → **立即返回旧值**（同步方永不阻塞）+ fire-and-forget 触发后台
     `fetchConfig()`（in-flight 标志防并发重复刷新）→ 下一轮调用即新值
   - 缓存为 null → 返回 `{}` + 后台引导一次（启动预热链路保证极少先触发）
   - 后台刷新失败 → 保留旧值 + debugLog（与既有事故教训一致）

### §2.2 shell.env 删全量注入

`security-analysis.ts` shell.env hook（约 L1282-1287）: 删除
`for (const [key, value] of Object.entries(allConfigs))` 全量注入循环。

保留（不动）:
- IDAT/IDA_PRO_HOME 显式注入（L1268-1276，独立通路，`getCachedConfigValue`
  → TTL 化后的 `getCachedConfig`，行为兼容）
- SESSION_ID / OPENCODE_ROOT / AGENT_DIR / SHARED_DIR 等目录与工具链注入
  （来自 plugin 计算常量，非 .ai_env）

### §2.3 消费方迁移

| 调用点 | 现状 | 改为 | 理由 |
|---|---|---|---|
| `security-analysis.ts:986` 启动预热 | `await refreshConfig()` | `await fetchConfig()` | 同语义（强制刷+填缓存） |
| `persistence.ts:226` 恢复校验读配置 | `await getAllConfig()` | `await fetchConfig()` | 低频要新鲜——直读 |
| `persistence.ts:358` 冷却恢复刷新 | `refreshConfig().then(...)` | `fetchConfig().then(...)` | 同语义 |
| `persistence.ts:14` import | refreshConfig, getAllConfig | fetchConfig | — |
| `tests/test-control.ts` | 三函数混用 | fetchConfig + getCachedConfig | 测试同步 |
| `lib/venv.ts:73` 注释 | 提及 getAllConfig | 提及 fetchConfig | 注释同步 |

### §2.4 架构影响

改动面: plugin 内部 4 个文件 + 测试。零 agent 侧改动（已实证无消费方）。
属高风险改动类（Plugin），按 playbook 要求端到端验证（§4）。

## §3 实现规范

### 改动范围表

| 文件 | 改动 |
|---|---|
| `plugins/lib/control-config.ts` | 合并 refreshConfig+getAllConfig → fetchConfig; getCachedConfig 加 TTL+SWR |
| `plugins/security-analysis.ts` | 启动预热改 fetchConfig; shell.env 删全量注入循环 |
| `plugins/lib/persistence.ts` | 三处调用迁移 fetchConfig |
| `plugins/tests/test-control.ts` | 迁移 + 新增 TTL/SWR 与注入删除断言 |

### 编码规则

- TS 遵循插件现有风格（debugLog 关键路径打日志——SWR 的后台刷新触发/
  失败必须打日志）
- 不引入新依赖

### §3.1 实施步骤拆分

1. **control-config.ts: 合并 fetchConfig（直读+喂缓存）**
   - 文件: `plugins/lib/control-config.ts`
   - 预估行数: ~30
   - 验证点: bun 跑 test-control 既有用例前先同步步骤 4 的迁移? 否——
     本步先实现 fetchConfig 并**暂时保留** refreshConfig/getAllConfig 作为
     薄委托（`export const refreshConfig = fetchConfig` 形态），既有消费方
     零破坏; `bun -e "import(...)"` 冒烟
   - 依赖: 无

2. **control-config.ts: getCachedConfig 加 TTL + SWR**
   - 文件: `plugins/lib/control-config.ts`
   - 预估行数: ~40（含日志）
   - 验证点: 手动 review SWR 分支（过期返旧值/后台刷/失败保留/in-flight）;
     bun import 冒烟
   - 依赖: 步骤 1（复用 cachedAt）

3. **消费方迁移 + 删旧导出**
   - 文件: security-analysis.ts / persistence.ts / venv.ts（注释）/
     test-control.ts
   - 预估行数: ~15
   - 验证点: `grep -rn "refreshConfig\|getAllConfig" .opencode/plugins/`
     零残留（注释中的历史记载除外）; bun 测试过
   - 依赖: 步骤 1

4. **shell.env 删全量注入循环**
   - 文件: `plugins/security-analysis.ts`
   - 预估行数: -10（删代码）+ 3（注释说明为何不注入）
   - 验证点: 新起 bash 工具调用 `env | grep -cE "DEEPSEEK|JULIANG"` 为 0;
     `$IDAT` 仍正确注入（IDAT env 存在）
   - 依赖: 无（与步骤 1-3 独立，但同批回归）

5. **测试补强**
   - 文件: `tests/test-control.ts`
   - 预估行数: ~40
   - 验证点: 新增用例过——a) fetchConfig 直读返回控制台真值并喂缓存
     （后续 getCachedConfig 拿到）; b) TTL 内同步调用不发请求;
     c) TTL 过期后同步调用返回旧值且后台刷新被触发（mock 时间或短 TTL 注入）;
     d) 刷新失败旧值保留
   - 依赖: 步骤 1-3

6. **端到端回归**
   - 文件: 无新改动
   - 验证点: test-control 全量过; test_integration 6/6; 手动链路:
     bash env 业务键 0 + IDAT 在; 配置页改值后 ≤30s agent 侧生效（模拟）
   - 依赖: 步骤 1-5

## §4 验收标准

**功能验收**:
- agent bash（工具调用）env 中无 DEEPSEEK_API_KEY/JULIANG_API_KEY 等业务键
- $IDAT/$IDA_PRO_HOME 注入照常
- TTL 过期后 30s 级新鲜度（SWR 下轮生效）; fetchConfig 直读总是最新
- refreshConfig/getAllConfig 名字消失; API 面收敛为
  fetchConfig（直读）+ getCachedConfig（TTL 缓存）两个正交语义

**回归验收**:
- test-control 全绿; test_integration 6/6; e2e 不受影响（不触配置注入链）
- 控制台/前端/MCP/vite 全部照常（本轮不触 spawn 链路）

**架构验收**:
- 缓存刷新语义统一为 TTL + SWR 单一实现（无按调用点特判）
- 零 agent 侧文件改动

## §5 与现有需求文档的关系

- `2026-09-27-spawn-env-whitelist.md`: 同属 env 治理系列——白名单管
  "plugin → 控制台进程" spawn 通路; 本需求管 "plugin → agent bash"
  shell.env 通路 + 配置读取新鲜度。两者互补，无重叠改动。
- `pending-items.md` #2（agent shell 业务键注入收紧）: 本需求落地后勾选。

## §6 实施结果

**完成于 2026-09-28**（步骤 1-6 全部落地）:

1. **control-config.ts**: API 面 3→2——`fetchConfig()`（无缓存直读+喂缓存，
   失败 throw 旧值保留）+ `getCachedConfig()`（30s TTL + SWR: 过期返旧值 +
   fire-and-forget 后台刷新，in-flight 防并发，失败保留旧值）。
   另导出 `forceExpireCacheForTest()`（测试钩子，触发真实 SWR 分支非 mock 值）。
   注意: §3.1 步骤 1 原计划"暂留薄委托"，实际与步骤 2 一次成型同文件重写、
   立即接步骤 3 迁移——中间态未跑测试，无风险残留。
2. **消费方迁移**: security-analysis.ts（import + 启动预热）、persistence.ts
   （import + 恢复校验直读 + 冷却恢复刷新）、venv.ts 注释、test-control.ts。
   `grep refreshConfig|getAllConfig plugins/` 零残留 ✓。
3. **shell.env 删全量注入**: 业务键退出 agent bash; IDAT/IDA_PRO_HOME 显式
   通路保留。**运行时生效需重启 opencode**（plugin 代码 opencode 启动时加载）。
4. **测试**: test-control 11/11（新增 SWR 过期分支用例: 强制过期断言
   完整旧值立即返回 + 后台刷新落地后缓存完整）; test_integration 6/6。
   测试自举沙箱控制台（/tmp/control_test_ts*），fetchConfig 真连沙箱非碰生产。
5. **审计轮发现并修复**: SWR 后台刷新触发路径补 debugLog（原只有失败路径
   有日志，排查时看不到 SWR 是否工作）。

**待重启后验证**（用户下次重启 opencode 时自动闭环）:
- bash 工具 `env | grep -cE "DEEPSEEK|JULIANG"` = 0（业务键归零）
- `$IDAT` 注入照常
- 配置页改值后 ≤30s agent 侧生效
