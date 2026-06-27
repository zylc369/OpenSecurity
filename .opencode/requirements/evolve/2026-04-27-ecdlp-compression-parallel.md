# 需求文档: ECDLP 并行求解 + 压缩上下文保留增强 + 并行计算规则

## §1 背景与目标

**来源**: TencentPediyKeygenMe2 (CRACKME3) 完整逆向分析复盘。用户确认的 5 个改进方案（3 个推荐做 + 2 个可选做）。

**痛点**:
1. ECDLP 求解浪费 ~3 轮 — 单线程 Floyd 跑 2.58B 步未找到解，改成 8 线程 DP 并行后 40 秒解决。现有 `ecdlp-solving.md` 只有单线程 Floyd 模板
2. 上下文压缩丢失分析状态 — 压缩后任务目录、环境信息、已完成分析全部丢失，需要人工恢复
3. 并行计算无指引 — `technology-selection.md` 仅 4 行描述并行，缺少线程数选择、DP 策略、MSVC 多线程模板

**目标**:
- 方案 A: 升级 `ecdlp-solving.md` — 添加并行 Pollard's rho + DP 模板、r=1 等特殊约束、完整工作流
- 方案 B: 增强 Plugin 压缩上下文保留 — Plugin compacting hook 动态注入环境信息；Agent prompt 添加变量丢失自愈规则
- 方案 C: 升级 `technology-selection.md` — 添加并行计算策略（线程数选择、DP 策略、MSVC 多线程模板）
- 方案 D (可选): Frida 版本适配知识库
- 方案 E: (已合入方案 C) MSVC 兼容性知识

**预期收益**:
- 速度: ECDLP 8 线程并行比单线程快 ~50x（40s vs ~33min 估算）
- 轮次: 压缩后状态丢失 → 0（自愈规则自动恢复）
- 准确度: 避免因压缩丢失导致的重复分析和方向迷失

## §2 技术方案

### 方案 A: 升级 ecdlp-solving.md

**改动文件**: `.opencode/binary-analysis/knowledge-base/ecdlp-solving.md`

**改动内容**:

1. **算法选择表** — 在现有表中新增"并行 Pollard's rho + DP"行（保留现有所有行，包括单线程 Pollard's rho 和 BSGS）：
   | 曲线位数 | 算法 | 预估耗时 | 内存 |
   | 33-64 bit | 并行 Pollard's rho + DP | 分钟级 (C, 8线程) | 极低+DP表 |

2. **新增 § "并行 Pollard's rho + Distinguished Points"**（ECDLP 特定实现细节，通用 DP 策略在 technology-selection.md）：
   - DP 策略：点 x 的低 d bit 全零时记录（如 d=16 → 1/65536 概率记录）
   - 线程数选择：min(CPU 核心数, 曲线位数/8)，不超过 16
   - 终止检测：共享原子标志或文件锁，任一线程找到解后通知其他线程退出
   - 碰撞检测：各线程的 DP 点写入共享哈希表，新 DP 与已有 DP 的 y 坐标比较

3. **替换现有 C 模板** — 仿射坐标并行 DP 版本（现有 Python 模板保留不改，仅替换 C 模板）：
   - 使用 `CreateThread`（Windows）/ `pthread`（Linux）
   - 仿射坐标（比 Jacobian 快 ~2x，因为省去 Z 坐标运算）
   - DP 判定：`(P.x & DP_MASK) == 0`
   - 线程安全：`CRITICAL_SECTION` 或 `pthread_mutex` 保护 DP 表
   - 跨平台：`#ifdef _WIN32` 条件编译区分 Windows (CreateThread/CRITICAL_SECTION) 和 Linux (pthread/pthread_mutex)
   - 结果输出到 stdout，Python 通过 subprocess 调用

4. **新增 § "特殊约束：非标准 ECDSA"**：
   - r=1 约束：某些实现要求 `Compare(r, Integer(1)) == 0`，不是标准 ECDSA 的 r∈[1,n-1]
   - 解法：ECDLP 求解 `k` 使得 `(k·G).x mod n = 1`（而非任意 r）
   - 验证：确认点 (1, y) 在曲线上且在子群中

5. **渐进策略更新** — 在现有渐进策略中追加并行化决策步骤（插在"转 C"和"验证"之间），不替换现有步骤：
   - 单线程 Python 原型验证正确性（~30min）
   - 性能估算 → 如果需要 >30min → 转 C 多线程
   - C 多线程 DP 版本（~60min）
   - 线程数 = CPU 核心数（从 `detect_env.py` 或 `os.cpu_count()` 获取）

6. **常见陷阱新增**：
   - n > p 异常（违反 Hasse's bound，但 CryptoPP 仍接受）
   - 仿射坐标 vs Jacobian 坐标选择（仿射更快但需要模逆，Jacobian 不需要模逆但多了 Z 坐标）
   - DP mask 太小 → 表太大；太大 → 碰撞慢。推荐 d = 曲线位数/2 - 4

### 方案 B: 增强压缩上下文保留

**改动文件**:
1. `.opencode/plugins/security-analysis.ts` — 修改 compacting hook 逻辑（动态注入环境信息）
2. `.opencode/agents/binary-analysis.md` — 添加变量丢失自愈规则

**改动 1: Plugin compacting hook 动态注入环境信息摘要**

在 `experimental.session.compacting` hook 中，从 `ENV_CACHE_FILE` 读取实际环境信息，动态拼接成摘要文本注入到 `output.context`（而非在静态 COMPACTION_CONTEXT_PROMPT 常量中添加模板）：

```js
// 在 compacting hook 中动态注入（伪代码）
const envData = readJsonSafe(ENV_CACHE_FILE);
let envSummary = "## 环境信息（压缩时自动注入）\n";
if (envData?.data) {
  envSummary += `- BA_PYTHON: ${envData.data.venv_python || '未知'}\n`;
  // ... 其他字段（参照 system.transform 中的逻辑独立构建，不修改 system.transform）
}
output.context.push(envSummary);
output.context.push(COMPACTION_CONTEXT_PROMPT);
```

这样环境信息的值是 Plugin 从 env_cache.json 实时读取的，不依赖 LLM 总结器从对话历史中提取。

**改动 2: Agent prompt 添加变量丢失自愈规则**

在 `## 后续交互处理` 中添加：

```
### 变量丢失自愈（压缩恢复后执行）

如果上下文压缩后变量丢失（$TASK_DIR、$SCRIPTS_DIR 等），按以下步骤恢复：
1. $SCRIPTS_DIR: 从 Plugin 注入的环境信息恢复，或从 config.json 读取
2. $TASK_DIR: 从 ~/bw-security-analysis/workspace/ 中查找包含匹配目标二进制路径的 summary.json 的目录
3. 如果有多个匹配 → 按修改时间排序取最新的
4. 如果找不到匹配的任务目录 → 提示用户确认，或创建新任务目录
```

**设计决策**: 任务目录路径不在 COMPACTION_CONTEXT_PROMPT 中硬编码（因为它是动态创建的，Plugin 无法在压缩时知道当前值）。改为依赖 LLM 总结器保留 + 自愈规则双重保障。

### 方案 C: 升级 technology-selection.md 并行计算策略

**改动文件**: `.opencode/binary-analysis/knowledge-base/technology-selection.md`

**改动内容**: 扩充现有 `## 并行计算策略` 章节（当前仅 4 行），替换为完整内容：

1. **线程数选择**：
   | 场景 | 线程数 | 原因 |
   | ECDLP (64-bit) | min(cpu_count, 16) | 8 线程比单线程快 ~50x |
   | 暴力搜索 | cpu_count | 线性加速 |
   | 内存密集型 | min(cpu_count, 4) | 内存带宽瓶颈 |

2. **MSVC 多线程模板**（仅 Windows 部分，Linux 替代方案 pthread 见 ecdlp-solving.md 的 C 模板）：
    ```c
    #include <windows.h>
    // CRITICAL_SECTION 保护 DP 表
    // CreateThread 创建工作线程
    // InterlockedExchange 设置终止标志
    ```

3. **Distinguished Points 策略（通用描述，不含 ECDLP 特定实现，详细实现见 ecdlp-solving.md）**：
   - 什么场景用 DP：多线程随机游走类算法（线程间不共享路径，只通过 DP 表碰撞）
   - DP mask 选择原则：d 值决定 DP 概率，影响表大小和碰撞速度，需根据可用内存权衡
   - DP 表实现模式：哈希表 + 线程安全写入 + 碰撞检测（通用模式，不限 ECDLP）

4. **Python 调用并行 C 程序模式**（扩充现有"渐进策略"章节，不替换）：
   - 编译多线程 C → subprocess 调用 → 读 stdout
   - 线程数通过命令行参数传递
   - 超时通过 subprocess timeout 控制

### 方案 D (可选): Frida 版本适配知识库

**改动文件**: `.opencode/binary-analysis/knowledge-base/frida-hook-templates.md`

**前提**: 文件必须已存在。如不存在则跳过此方案。

**改动内容**: 在文档顶部添加版本兼容性说明：
- `Module.findBaseAddress()` → 使用 `Process.findModuleByName(name).base`
- `Memory.readU32(ptr)` → 使用 `ptr.readU32()`
- `Memory.patchCode()` 可能 hang → 改用 `Memory.protect()` + `ptr.writeU8()`

### 方案 E: (已合入方案 C)

MSVC 兼容性知识不再独立实现，合入方案 C 的 technology-selection.md 升级中（包含 CreateThread/CRITICAL_SECTION 模板和 `__umul128` 说明）。

## §3 实现规范

### 改动范围表

| 方案 | 文件 | 改动类型 | 预估行数 |
|------|------|---------|---------|
| A | knowledge-base/ecdlp-solving.md | 修改 | ~160 行新增/替换 |
| B | plugins/security-analysis.ts | 修改 | ~15 行新增（compacting hook 中动态拼接环境信息 + 保持原有 COMPACTION_CONTEXT_PROMPT）|
| B | agents/binary-analysis.md | 修改 | ~10 行新增，-75 行提取（净 -65 行）|
| B | knowledge-base/gui-automation.md | 扩充（如已存在）或新建 | ~45 行（从 Agent prompt 提取的 GUI 命令详情）|
| B | knowledge-base/process-patch-reference.md | 无需修改 | Agent prompt 中的 Patch 命令示例已被此文件包含，只需从 Agent prompt 删除即可 |
| C | knowledge-base/technology-selection.md | 修改 | ~50 行新增/替换 |
| D | knowledge-base/frida-hook-templates.md | 修改 | ~15 行新增 |
| E | (已合入方案 C) | — | — |

### 编码规则

- 知识库 .md 文件必须自包含（不依赖主 prompt 上下文）
- 代码模板中的注释使用中文
- C 模板使用 MSVC 兼容语法（不使用 `__int128`，用 `__umul128`），同时用 `#ifdef _WIN32` 支持跨平台
- 不修改任何 Python 逻辑代码。JS 仅修改 compacting hook 的环境信息注入逻辑（从 env_cache.json 读取并 push），不修改 system.transform 和 event hook

### §3.1 实施步骤拆分

```
步骤 1. 升级 ecdlp-solving.md — 算法选择表 + 并行 Pollard's rho + DP 章节
  - 文件: knowledge-base/ecdlp-solving.md
  - 预估行数: ~60 行（替换算法选择表 + 新增并行章节）
  - 验证点: 阅读新增内容确认（a）不引用主 prompt 中未定义的术语（b）MSVC 兼容（c）引用路径格式正确
  - 依赖: 无

步骤 2. 升级 ecdlp-solving.md — C 并行模板（基础框架 + 模运算 + 点运算）
  - 文件: knowledge-base/ecdlp-solving.md
  - 预估行数: ~80 行（替换现有 C 模板：仿射坐标点运算 + MSVC __umul128 模运算）
  - 验证点: 确认（a）无 `__int128`，用 `__umul128`（b）代码结构完整（有 struct 定义、模运算函数、点运算函数声明）（c）不含 main 函数（在步骤 3 添加）
  - 依赖: 步骤 1

步骤 3. 升级 ecdlp-solving.md — C 并行模板（多线程 + DP 碰撞 + main）
  - 文件: knowledge-base/ecdlp-solving.md
  - 预估行数: ~80 行（在步骤 2 基础上追加：CreateThread + CRITICAL_SECTION + DP 表 + worker 函数 + main）
  - 验证点: 确认（a）代码完整可编译（有 main 入口）（b）使用 `#ifdef _WIN32` 跨平台（c）DP 判定和碰撞逻辑正确
  - 依赖: 步骤 2

步骤 4. 升级 ecdlp-solving.md — 特殊约束 + 渐进策略 + 陷阱更新
  - 文件: knowledge-base/ecdlp-solving.md
  - 预估行数: ~40 行
  - 验证点: 确认（a）r=1 约束说明完整（b）渐进策略包含并行化决策（c）新陷阱覆盖复盘中的 n>p 异常和 DP mask 选择
  - 依赖: 步骤 3

步骤 5. 增强 Plugin compacting hook — 动态注入环境信息
  - 文件: plugins/security-analysis.ts
  - 预估行数: ~15 行（在 compacting hook 中从 env_cache.json 读取实际环境信息，动态拼接后与 COMPACTION_CONTEXT_PROMPT 一起注入）
  - 验证点: `node --check security-analysis.ts` 语法通过 + 确认 compacting hook 读取 env_cache.json 并拼接环境信息文本
  - 依赖: 无

步骤 6. Agent prompt 添加变量丢失自愈规则
  - 文件: agents/binary-analysis.md
  - 预估行数: ~10 行（在后续交互处理章节中添加自愈规则）
  - 验证点: 人工阅读确认规则可执行 + 不与其他规则冲突
  - 依赖: 无

步骤 6.5. Agent prompt 瘦身（Phase 4.5）
  - 文件: agents/binary-analysis.md + knowledge-base/gui-automation.md
  - 预估行数: -75 行（从 Agent prompt 提取（a）GUI 自动化工具：保留现有引用行（行 355），删除其后的标题和详细命令代码块 ~45 行 → gui-automation.md（b）进程 Patch 工具：保留现有引用行（行 407），删除其后的命令代码块 ~17 行（process-patch-reference.md 已包含相同内容））
  - 验证点: `wc -l agents/binary-analysis.md` 确认 < 450 行（预期 ~432 行）+ gui-automation.md 自包含 + 引用路径正确 + process-patch-reference.md 未被修改
  - 依赖: 步骤 6（先加后减，确保净行数达标）

步骤 7. 升级 technology-selection.md 并行计算策略
  - 文件: knowledge-base/technology-selection.md
  - 预估行数: ~50 行（替换现有 4 行并行章节为完整内容）
  - 验证点: 人工阅读确认自包含性 + 与 ecdlp-solving.md 无重复（边界：ecdlp 讲 ECDLP 特定 DP 实现细节，此处讲通用并行策略和 MSVC 多线程 API）
  - 依赖: 步骤 4（确保不与 ecdlp-solving.md 内容重复）

步骤 8. (可选) Frida 版本适配知识库
  - 文件: knowledge-base/frida-hook-templates.md
  - 预估行数: ~15 行
  - 验证点: 文件存在性检查 + 人工阅读确认 API 替代方案准确
  - 依赖: 无（但需要 frida-hook-templates.md 已存在，不存在则跳过）
```

## §4 验收标准

### 功能验收

| 编号 | 验收项 | 验证方式 |
|------|--------|---------|
| F1 | ecdlp-solving.md 包含并行 Pollard's rho + DP 完整描述 | 人工阅读 |
| F2 | ecdlp-solving.md 的 C 模板使用 MSVC 兼容语法 | 检查无 `__int128`，使用 `__umul128` |
| F3 | ecdlp-solving.md 包含 r=1 特殊约束说明 | 人工阅读 |
| F4 | Plugin compacting hook 动态注入环境信息摘要 | 读取 mjs 确认 compacting hook 从 env_cache.json 读取并拼接环境信息 |
| F5 | Agent prompt 包含变量丢失自愈规则 | 读取 md 文件确认 |
| F6 | technology-selection.md 并行计算策略包含线程数选择和 DP 策略 | 人工阅读 |
| F7 | 所有知识库文件自包含 | 逐个阅读确认不依赖主 prompt 上下文 |
| F8 | (可选) frida-hook-templates.md 包含版本兼容性说明 | 读取文件确认（如文件不存在则跳过） |

### 回归验收

| 编号 | 验收项 | 验证方式 |
|------|--------|---------|
| R1 | security-analysis.ts 加载不报错 | `node --check` |
| R2 | Agent prompt < 450 行（含 Phase 4.5 瘦身提取） | `wc -l` |
| R3 | 现有 COMPACT_RULES 规则完整保留 | diff 检查 |
| R4 | 现有 Plugin system.transform 功能不变 | 检查代码未修改 |

### 架构验收

| 编号 | 验收项 |
|------|--------|
| A1 | ecdlp-solving.md 与 technology-selection.md 无内容重复（ECDLP 并行细节在 ecdlp-solving.md，通用并行策略在 technology-selection.md）|
| A2 | Agent prompt 仅添加自愈规则（~10 行），不膨胀详细流程 |

## §5 与现有需求文档的关系

- **2026-04-26-crackme3-retro-improvements.md**: 本需求的直接前身。上一个需求解决了 process_patch.py 工具化和 PowerShell 修复，本需求解决剩余的知识库升级和压缩保留增强
- **2026-04-22-plugin-and-architecture-improvements.md**: Plugin 架构已建立，本需求在此基础上增强 COMPACTION_CONTEXT_PROMPT，不改变架构
- **2026-04-22-knowledge-and-ops-improvements.md**: 知识库升级的延续，本需求专注 ecdlp-solving.md 和 technology-selection.md 的实战经验沉淀
