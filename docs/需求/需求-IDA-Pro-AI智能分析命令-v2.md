# 需求：IDA Pro AI 智能分析命令

## 1. 背景与目标

### 1.1 背景

当前项目已具备以下能力：

- **IDAPython 脚本集**（`disassembler/`）：反汇编导出、AI 辅助重命名、AI 辅助注释等，支持 IDA GUI 内运行和 `idat` 无头（headless）运行
- **AI 调用封装**（`ai/opencode.py`）：通过 `opencode run` 非交互模式调用 AI
- **Shell 工具库**（`shell/library/`）：IDA 路径检测、数据库锁检测、日志工具

但这些能力分散在各个独立脚本中，用户需要记忆不同脚本的用法、参数格式，无法用一个统一入口完成从"提出问题"到"获得分析结果"的完整链路。

### 1.2 目标

创建一个 **opencode 自定义命令**（`/ida-pro-analysis`），让用户在 AI 工具中以自然语言描述分析需求，命令自动：

1. **理解意图**：解析用户输入的二进制文件路径和分析需求
2. **制定计划**：将自然语言需求拆解为具体的 IDAPython 操作步骤
3. **执行分析**：调用 `idat` 无头模式执行 IDAPython 脚本，查询 IDA 数据库
4. **迭代优化**：验证结果正确性，如有问题则修复后重新执行（Reconcile Loop）
5. **持久化**：将分析结果更新到 IDA 数据库（注释、重命名）和中间状态文件
6. **反馈结果**：将分析结论清晰呈现给用户

### 1.3 典型使用场景

| 场景 | 用户输入示例 | 期望输出 |
|------|-------------|---------|
| 算法逆向 | `/ida-pro-analysis lesson1.exe.i64 分析 main_0 函数的 user_name 和 password 验证逻辑，找出通过验证的输入值` | 具体的用户名和密码值 |
| 入口分析 | `/ida-pro-analysis lesson1.exe.i64 找到所有入口函数` | main、init 等入口列表及其地址 |
| SO 入口分析 | `/ida-pro-analysis lesson1.so.i64 找到所有入口并分析其行为，更新注释到数据库` | JNI_OnLoad、init 等入口列表、行为摘要，IDA 中可查看注释 |
| DLL 导出分析 | `/ida-pro-analysis lesson1.dll.i64 列出所有导出函数及其功能` | 导出函数列表与功能描述 |
| 漏洞定位 | `/ida-pro-analysis target.i64 检查 sub_401000 中是否存在缓冲区溢出风险` | 风险点地址与原因分析 |
| 交叉引用追踪 | `/ida-pro-analysis app.i64 追踪哪些函数引用了字符串 "password"` | 引用链路和上下文分析 |

---

## 2. 技术方案

### 2.1 命令架构

采用**渐进式披露**思想，将命令拆分为多个文件：

```
.opencode/commands/
├── ida-pro-analysis.md          # 主命令：入口，接收 $ARGUMENTS
└── ida-pro-analysis/            # 子模块（被主命令引用）
    ├── planning.md              # 计划阶段：意图识别、步骤拆解
    ├── execution.md             # 执行阶段：调用 idat 运行脚本
    ├── reconciliation.md        # 审计阶段：结果验证与修复
    └── persistence.md           # 持久化阶段：更新数据库与中间状态
```

**主命令**（`ida-pro-analysis.md`）负责：

1. 解析 `$ARGUMENTS` 中的文件路径和分析需求
2. 依次加载子模块，按 Plan → Execute → Reconcile → Persist 循环执行
3. 将最终结果返回给用户

### 2.2 执行流程（Reconcile Loop）

```
┌─────────────┐
│  用户输入     │  /ida-pro-analysis <文件路径> <分析需求>
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Plan 计划   │  AI 分析需求 → 拆解为 IDAPython 操作步骤
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Execute 执行│  为每个步骤生成/选择脚本 → idat headless 执行
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Audit 审计  │  检查执行结果是否正确、是否遗漏
└──────┬──────┘
       │
       ├── 不通过 → 回到 Plan（调整步骤）或 Execute（修复参数）
       │
       ▼ 通过
┌─────────────┐
│  Persist 持久│  更新 IDA 数据库注释/重命名 + 写中间状态
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Report 报告 │  格式化输出分析结果给用户
└─────────────┘
```

### 2.3 核心设计原则

1. **无头模式为主**：所有 IDA 操作通过 `idat -A -S` 执行，不依赖 IDA GUI
2. **脚本驱动**：将分析操作封装为独立的 IDAPython 脚本（`disassembler/` 目录），命令通过 shell 调用 `idat` 执行这些脚本
3. **AI 编排**：命令提示词引导 AI 充当"编排器"，根据需求选择/组合/生成脚本
4. **结果可验证**：每步执行后都有明确的成功/失败判断和日志

---

## 3. 命令实现规范

### 3.1 命令文件格式

命令使用 Markdown 格式（`.opencode/commands/ida-pro-analysis.md`），符合 opencode 自定义命令规范：

```markdown
---
description: IDA Pro AI 智能分析 — 输入二进制文件路径和分析需求，自动完成逆向分析
---

（命令提示词内容）
```

用户通过 `$ARGUMENTS` 传入参数，格式约定：

```
/ida-pro-analysis <文件路径> <分析需求描述>
```

- `$1`：IDA 数据库文件路径（`.i64` / `.idb` / 二进制文件）
- `$2...`：分析需求（自然语言描述）

### 3.2 命令提示词设计要点

命令提示词需要引导 AI 执行以下步骤（不是直接告诉 AI 要做什么，而是提供足够的上下文让 AI 能自主决策）：

#### 3.2.1 角色与能力边界

- 明确 AI 作为"逆向分析编排器"的角色
- 说明可用的工具集：`idat` 无头执行、IDAPython 脚本、IDA 数据库操作
- 明确 AI 不能直接操作 IDA GUI，必须通过脚本间接操作

#### 3.2.2 可用的 IDAPython 脚本清单

命令提示词中应列出当前项目已有的脚本及其功能、参数格式，让 AI 能根据需求选择合适的脚本：

| 脚本 | 功能 | 调用方式 |
|------|------|---------|
| `disassembler/dump_func_disasm.py` | 导出函数反汇编 | `IDA_FUNC_ADDR=xxx IDA_OUTPUT=xxx idat -A -S dump_func_disasm.py` |
| `disassembler/ai_analyze.py` | AI 辅助重命名/注释 | `IDA_ACTIONS=rename,comment IDA_PATTERN=xxx python ai_analyze.py --input xxx` |

对于现有脚本无法覆盖的需求，AI 应能生成临时的 IDAPython 脚本来完成操作。

#### 3.2.3 常见分析操作的脚本模板

提供以下操作的 IDAPython 脚本模板，供 AI 按需调整使用：

1. **入口点枚举**：查询 main、init、JNI_OnLoad、导出函数等
2. **函数反编译/反汇编**：获取指定函数的反编译 C 代码或反汇编
3. **交叉引用查询**：查找某个地址/函数/字符串的调用者/被调用者
4. **字符串搜索**：在二进制中搜索特定字符串及其引用位置
5. **符号重命名**：将自动命名（sub_xxx）改为有意义的名称
6. **注释写入**：为函数或代码行添加注释
7. **类型信息查询**：查看结构体、枚举等类型定义
8. **导入/导出表分析**：列出导入函数和导出函数

每个模板都应是无头模式的完整脚本（含环境变量解析、`auto_wait`、`qexit`），遵循 `rules/headless-automation-guide.md` 规范。

#### 3.2.4 输出格式规范

AI 的最终输出应包含：

1. **分析摘要**：一句话说明分析结论
2. **详细结果**：按函数/地址组织的分析细节
3. **操作记录**：对 IDA 数据库做了哪些修改（重命名、注释等）
4. **置信度说明**：哪些结论是确定的，哪些是推测的

### 3.3 日志规范

命令执行过程的日志分为三层：

| 层级 | 位置 | 内容 |
|------|------|------|
| idat 日志 | `-L` 指定的路径 | IDAPython 脚本的执行日志（`[*]`/`[+]`/`[!]` 前缀） |
| 命令日志 | `analysis_intermediate/<task_id>/command.log` | AI 编排决策、脚本选择、参数构造等 |
| 中间状态 | `analysis_intermediate/<task_id>/state.json` | 任务状态、已完成步骤、中间结果 |

所有日志使用中文，包含足够的上下文信息便于排查。

---

## 4. 依赖的 IDAPython 工具脚本

### 4.1 已有脚本（可直接复用）

| 脚本 | 说明 | 复用方式 |
|------|------|---------|
| `disassembler/dump_func_disasm.py` | 函数反汇编导出 | 直接 `idat -A -S` 调用 |
| `disassembler/ai_analyze.py` | AI 重命名/注释统合入口 | 终端 `python` 调用（内部自动调用 `idat`） |
| `disassembler/ai_utils.py` | AI 分析工具函数库 | 被 IDAPython 脚本 import |
| `disassembler/ai_rename.py` | AI 重命名功能 | 被 `ai_analyze.py` 调用 |
| `disassembler/ai_comment.py` | AI 注释功能 | 被 `ai_analyze.py` 调用 |
| `shell/library/detect_ida_path.sh` | IDA 路径检测 | shell 脚本 source |
| `shell/library/detect_db_lock.sh` | 数据库锁检测 | shell 脚本 source |
| `shell/library/log.sh` | 日志工具 | shell 脚本 source |
| `ai/opencode.py` | opencode 非交互调用 | Python import |

### 4.2 需要新建的脚本

以下脚本为命令提供基础的"查询"能力，AI 在编排时可以按需调用：

#### 4.2.1 通用查询脚本 `disassembler/query_database.py`

**用途**：接受查询类型和参数，返回 IDA 数据库的结构化信息（JSON 格式），作为命令的"万能查询接口"。

**支持的查询类型**（通过环境变量 `IDA_QUERY` 指定）：

| 查询类型 | 说明 | 参数 |
|---------|------|------|
| `entry_points` | 枚举所有入口点（main、init、JNI_OnLoad、导出函数等） | 无 |
| `functions` | 按模式匹配函数列表 | `IDA_PATTERN` |
| `decompile` | 反编译指定函数 | `IDA_FUNC_ADDR` |
| `disassemble` | 反汇编指定函数 | `IDA_FUNC_ADDR` |
| `xrefs_to` | 查询指定地址的交叉引用（谁调用了它） | `IDA_FUNC_ADDR` 或 `IDA_ADDR` |
| `xrefs_from` | 查询指定函数调用了哪些函数 | `IDA_FUNC_ADDR` |
| `strings` | 搜索字符串及其引用位置 | `IDA_PATTERN`（搜索模式） |
| `imports` | 列出所有导入函数 | 无 |
| `exports` | 列出所有导出函数 | 无 |
| `segments` | 列出所有段信息 | 无 |
| `structs` | 列出所有结构体定义 | 可选 `IDA_PATTERN` |
| `func_info` | 查询单个函数的详细信息（签名、调用者、被调用者、字符串引用等） | `IDA_FUNC_ADDR` |
| `rename` | 重命名符号 | `IDA_OLD_NAME` + `IDA_NEW_NAME` |
| `set_comment` | 设置函数/地址注释 | `IDA_FUNC_ADDR` + `IDA_COMMENT` + 可选 `IDA_ADDR`（行内注释） |

**输出格式**：

```json
{
  "success": true,
  "query": "entry_points",
  "data": { ... },
  "error": null
}
```

**设计要点**：

- 每个查询类型对应一个内部处理函数
- 输出为 JSON 写入环境变量 `IDA_OUTPUT` 指定的文件
- 遵循 `rules/headless-automation-guide.md` 的三模式实现规范
- 包含详细的中文执行日志

#### 4.2.2 通用更新脚本 `disassembler/update_database.py`

**用途**：接受更新操作类型和参数，将分析结果写回 IDA 数据库。

**支持的操作类型**（通过环境变量 `IDA_OPERATION` 指定）：

| 操作类型 | 说明 | 参数 |
|---------|------|------|
| `rename` | 重命名函数/变量/全局数据 | `IDA_OLD_NAME` + `IDA_NEW_NAME` |
| `set_func_comment` | 设置函数注释 | `IDA_FUNC_ADDR` + `IDA_COMMENT` |
| `set_line_comment` | 设置行内注释 | `IDA_ADDR` + `IDA_COMMENT` |
| `batch` | 批量执行多个操作 | `IDA_BATCH_FILE`（JSON 文件路径） |

**batch 操作的 JSON 格式**：

```json
{
  "operations": [
    {"type": "rename", "old_name": "sub_401000", "new_name": "validate_password"},
    {"type": "set_func_comment", "func_addr": "0x401000", "comment": "验证用户密码"},
    {"type": "set_line_comment", "addr": "0x401050", "comment": "比较密码长度"}
  ]
}
```

### 4.3 脚本代码规范

所有新建脚本必须遵循：

- **AGENTS.md** 中的编码规范（导入规则、文件头、日志规范等）
- **`rules/headless-automation-guide.md`** 的三模式实现指南
- 良好的抽象设计，通用逻辑提取到 `disassembler/` 下的公共模块
- `.venv` 虚拟环境中的 IDA SDK 类型存根用于 IDE 提示

---

## 5. 中间状态管理方案

### 5.1 方案设计

采用**任务级隔离、按需加载**的方案：

```
analysis_intermediate/
├── <task_id>/
│   ├── state.json          # 任务状态
│   ├── plan.md             # 分析计划（AI 生成）
│   ├── steps/
│   │   ├── 001_query_entry_points.json    # 步骤执行结果
│   │   ├── 002_decompile_main.json
│   │   └── 003_update_comments.json
│   └── command.log         # 命令编排日志
└── latest -> <task_id>/    # 软链接，指向最近一次任务
```

### 5.2 state.json 结构

```json
{
  "task_id": "20260417_143052_abc123",
  "binary_path": "/path/to/binary.i64",
  "user_request": "分析 main_0 函数的验证逻辑",
  "status": "in_progress",
  "created_at": "2026-04-17T14:30:52",
  "updated_at": "2026-04-17T14:35:10",
  "current_phase": "execute",
  "total_steps": 5,
  "completed_steps": 3,
  "analysis_summary": "发现 main_0 函数包含用户名和密码验证逻辑...",
  "ida_modifications": [
    {"type": "rename", "old": "sub_401000", "new": "validate_user"},
    {"type": "func_comment", "addr": "0x401000", "comment": "验证用户名和密码"}
  ]
}
```

### 5.3 读取策略

| 情况 | 处理方式 |
|------|---------|
| 新任务（无历史状态） | 创建新任务目录，从零开始 |
| 同一二进制 + 相似需求 | 提示用户是否加载历史状态，加载后从断点继续 |
| 同一二进制 + 不同需求 | 创建新任务，但可引用历史任务的 IDA 数据库修改记录作为上下文 |
| 历史任务已完成 | 只读模式查看结果，不自动继续 |

### 5.4 设计原则

1. **任务隔离**：每次 `/ida-pro-analysis` 调用创建独立的任务目录，互不干扰
2. **轻量级**：`state.json` 只记录关键状态，不保存大量中间数据（大量数据通过 IDA 数据库本身保存）
3. **可恢复**：任务因任何原因中断后，可通过 state.json 中的进度信息恢复
4. **可追溯**：每个步骤的输入/输出都记录在 `steps/` 目录中

---

## 6. 命令文档拆分方案

### 6.1 主命令文件 `ida-pro-analysis.md`

**职责**：接收用户输入，编排整体流程，返回最终结果。

**内容包括**：

1. 命令描述（frontmatter）
2. 角色定义与能力说明
3. 参数解析规则（`$1` = 文件路径，`$2...` = 分析需求）
4. 整体流程编排（引用子模块）
5. 输出格式要求
6. 约束与安全规则

### 6.2 子模块文件

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `planning.md` | 计划阶段 | 意图识别框架、常见需求→脚本映射表、计划输出格式 |
| `execution.md` | 执行阶段 | idat 调用模板、参数构造规则、输出解析方法、错误处理 |
| `reconciliation.md` | 审计阶段 | 结果验证清单、常见错误模式、修复策略 |
| `persistence.md` | 持久化阶段 | 数据库更新操作、中间状态读写、幂等性保证 |

### 6.3 渐进式披露的实现

主命令通过 `@` 文件引用机制加载子模块：

```markdown
## 执行流程

### 1. 计划阶段
@.opencode/commands/ida-pro-analysis/planning.md

### 2. 执行阶段
@.opencode/commands/ida-pro-analysis/execution.md

### 3. 审计阶段
@.opencode/commands/ida-pro-analysis/reconciliation.md

### 4. 持久化阶段
@.opencode/commands/ida-pro-analysis/persistence.md
```

---

## 7. 安全与约束

### 7.1 文件安全

- 只操作用户指定的 IDA 数据库文件，不修改其他文件
- 不删除 IDA 数据库文件
- 写文件前检查目录存在性（`mkdir -p`）
- 不在日志或输出中暴露敏感路径信息（如有必要则脱敏）

### 7.2 操作安全

- 数据库修改操作（重命名、注释）需先列出预览，确认后再执行
- 批量修改提供 `--dry-run` 模式
- 不执行可能损坏数据库的操作（如强制保存已锁定的数据库）

### 7.3 AI 行为约束

- AI 不得自行决定修改二进制文件
- AI 不得跳过审计阶段直接报告结果
- 当 AI 置信度不足时，应明确告知用户而非编造结论
- 分析结果应区分"事实"（来自 IDA 数据库的精确信息）和"推测"（AI 基于上下文的推理）

---

## 8. 实现优先级与分阶段交付

### Phase 1：最小可用版本

**目标**：能处理最常见的分析需求

1. 创建主命令文件 `ida-pro-analysis.md`
2. 实现 `disassembler/query_database.py` 中的核心查询类型：`entry_points`、`functions`、`decompile`、`disassemble`、`func_info`、`xrefs_to`、`xrefs_from`、`strings`
3. 实现 `disassembler/update_database.py` 中的 `rename` 和 `set_func_comment` 操作
4. 创建 `planning.md` 和 `execution.md` 子模块
5. 基础的中间状态管理（创建任务目录 + state.json）

### Phase 2：完善循环

**目标**：实现完整的 Reconcile Loop

1. 创建 `reconciliation.md` 子模块
2. 创建 `persistence.md` 子模块
3. 补充 `query_database.py` 的其余查询类型
4. 补充 `update_database.py` 的 `set_line_comment` 和 `batch` 操作
5. 完善中间状态管理（历史任务恢复、引用）

### Phase 3：增强体验

**目标**：提升易用性和可靠性

1. 添加更多脚本模板（常见操作的开箱即用模板）
2. 优化命令提示词，减少 AI 的无效输出
3. 添加执行超时保护和异常恢复机制
4. 添加分析结果的可视化格式（表格、调用图等）

---

## 9. 验收标准

1. **功能验收**：
   - 能正确处理 1.3 中列出的所有典型使用场景
   - AI 能根据文件类型（exe/dll/so）智能识别入口类型
   - 分析结果准确，注释和重命名能正确写入 IDA 数据库

2. **质量验收**：
   - 命令执行有完整日志，日志使用中文，包含上下文信息
   - 代码遵循 AGENTS.md 编码规范
   - 新建 IDAPython 脚本通过 shell 测试框架验证
   - 新建 Python 工具函数有 pytest 测试

3. **架构验收**：
   - 命令文件按渐进式披露拆分，单文件不超过合理长度
   - IDAPython 脚本有良好的抽象和复用，不出现重复逻辑
   - 中间状态管理可靠，任务隔离且可恢复

---

## 10. 参考资料

| 资料 | 位置/链接 |
|------|----------|
| opencode 自定义命令文档 | https://opencode.ai/docs/zh-cn/commands/ |
| IDAPython 示例索引 | `vendor/ida-sdk/src/plugins/idapython/examples/index.md` |
| IDAPython 示例源码 | `vendor/ida-sdk/src/plugins/idapython/examples/` |
| IDAPython 参考文档 | https://python.docs.hex-rays.com/ |
| 无头自动化指南 | `rules/headless-automation-guide.md` |
| 脚本分类参考 | `rules/script-classification.md` |
| 项目编码规范 | `AGENTS.md` |
