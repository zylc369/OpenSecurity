# BinaryAnalysis Plugin 与架构改进

## §1 背景与目标

**来源**: Phase 0 复盘 — 结合 oh-my-openagent 源码审计 BinaryAnalysis 实现

**痛点**:
1. Plugin 的 `system.transform` output 类型猜测错误（`{ system: string[] }` 而非 string），环境信息注入可能完全无效
2. Plugin 缺少 `event` hook，无法在压缩后恢复分析状态（capture/restore）
3. Agent prompt 中 IDAPython 编码规范（~34 行）常驻，违反渐进式披露
4. `context-persistence.md` 内容过时，仍讨论"可行性待确认"的方案
5. `initial_analysis.py` 与 `query.py` 存在大量代码重复

**预期收益**:
- 改进 1: 环境信息注入从"可能不工作"变为"确定工作"
- 改进 2: 长对话压缩后分析结论不丢失，减少 2-5 轮重复解释
- 改进 3: Agent prompt 移除 34 行编码规范，替换为 3 行触发指引，净减少 ~31 行
- 改进 4: 文档一致性
- 改进 5: 消除 ~200 行代码重复，降低维护成本

## §2 技术方案

### 改进 1: 修复 Plugin — `system.transform` output 类型修正

**问题**: 当前代码猜测 output 为 string/array/object，实际类型为 `{ system: string[] }`。

**方案**: 
- 修正 `system.transform` hook，正确使用 `output.system.push(content)` 
- 类型签名: `(input: { sessionID?: string; model: { id: string; providerID: string; [key: string]: unknown } }, output: { system: string[] }) => Promise<void>`
- 参考: `oh-my-openagent/src/plugin/system-transform.ts`

**改动文件**: `.opencode/plugins/security-analysis.ts`

### 改进 2: Plugin 增加 `event` hook + compaction prompt

**问题**: 压缩后分析状态丢失（当前二进制路径、已发现的关键函数、中间结论）。

**方案**:
- 在 `compacting` hook 中注入结构化的 BinaryAnalysis 上下文提示（告诉压缩模型保留哪些信息）
- 增加 `event` hook，监听 `session.created`/`session.deleted` 管理 session 状态
- 增加 `session.compacted` 事件处理（日志记录，未来可扩展恢复逻辑）

**注**: 当前 `compacting` hook 的 `output.context.push()` 调用已是类型正确的（output 类型为 `{ context: string[] }`）。本改进仅更新注入内容。

**改动文件**: `.opencode/plugins/security-analysis.ts`

**compaction prompt 内容**（参考 oh-my-openagent 的 COMPACTION_CONTEXT_PROMPT 但简化）:
```
当总结此会话时，你必须保留以下信息：

## BinaryAnalysis 分析状态（必须保留）
- 目标二进制文件路径
- 已识别的关键函数及其地址
- 已发现的分析结论（如 bug、特殊条件、算法特征）
- 当前分析阶段和待完成步骤
- 验证结果和置信度评估
```

### 改进 3: Agent prompt 瘦身 — IDAPython 编码规范提取到知识库

**问题**: Agent prompt 尾部 34 行 IDAPython 编码规范只在生成脚本时需要。

**方案**:
- 将 `agents/binary-analysis.md` 第 327-360 行的 IDAPython 编码规范提取
- 移入 `knowledge-base/idapython-conventions.md`（新建）
- Agent prompt 中保留 3 行触发指引：`需要生成 IDAPython 脚本时，读取 $SCRIPTS_DIR/knowledge-base/idapython-conventions.md`
- 同时在"知识库索引"表中增加条目

**改动文件**: 
- `.opencode/agents/binary-analysis.md`（删除编码规范，增加知识库引用）
- `.opencode/binary-analysis/knowledge-base/idapython-conventions.md`（新建）

### 改进 4: 更新 `context-persistence.md`

**问题**: 文档仍讨论"方案 A/B 可行性待确认"，实际已实现。

**方案**: 重写为当前 Plugin 架构的设计文档，描述：
- Plugin 的定位（上下文持久化，不是"压缩 hook"）
- 使用的 hooks 及其作用
- 知识库按需加载机制

**改动文件**: `.opencode/binary-analysis/context-persistence.md`

### 改进 5: 重构 — 提取共享分析逻辑到 `_analysis.py`

**问题**: `scripts/initial_analysis.py` 重新实现了 `query.py` 中的段收集、入口点、导入表、字符串搜索、壳检测（约 200 行重复代码）。

**约束**: `query.py` 末尾有 `run_headless(_main)` 模块级调用，直接 import 会触发 IDA 进程退出。因此不能让 `initial_analysis.py` 导入 `query.py`。

**方案**: 新建 `_analysis.py` 共享模块，将重复逻辑收敛到一处。

具体做法：
1. 新建 `.opencode/binary-analysis/_analysis.py`
2. 将 `initial_analysis.py` 中的收集函数（`_collect_segments`, `_collect_entry_points`, `_collect_imports`, `_collect_strings`, `_detect_packer`）移入 `_analysis.py`
3. 修改 `query.py` 中对应的 `_query_xxx()` 函数，改为调用 `_analysis.py` 的函数
4. 修改 `initial_analysis.py`，从 `_analysis.py` 导入

**依赖方向**: `_analysis.py` → `_utils.py` → `_base.py`，`query.py` → `_analysis.py`，`scripts/initial_analysis.py` → `_analysis.py`

**行为差异处理**:
- 入口点分类：统一使用 `initial_analysis.py` 的 case-insensitive 版本（更准确）
- 段异常检测：统一使用 `query.py` 的 exact-or-prefix 版本（更精确）
- 壳检测信号权重：统一使用 `query.py` 的版本（含 import_count 判断更完善）

**改动文件**:
- `.opencode/binary-analysis/_analysis.py`（新建，从 initial_analysis.py 提取共享逻辑）
- `.opencode/binary-analysis/query.py`（替换内联逻辑为 `_analysis.py` 调用）
- `.opencode/binary-analysis/scripts/initial_analysis.py`（替换内联逻辑为 `_analysis.py` 调用）

## §3 实现规范

### 改动范围表

| 改进 | 文件 | 改动类型 | 影响范围 |
|------|------|---------|---------|
| 1 | `plugins/security-analysis.ts` | 修改 | Plugin 行为 |
| 2 | `plugins/security-analysis.ts` | 修改 | Plugin 行为 |
| 3 | `agents/binary-analysis.md` | 修改 | Agent prompt |
| 3 | `knowledge-base/idapython-conventions.md` | 新建 | 知识库 |
| 4 | `binary-analysis/context-persistence.md` | 重写 | 文档 |
| 5 | `binary-analysis/_analysis.py` | 新建 | 共享分析逻辑 |
| 5 | `binary-analysis/query.py` | 修改（高风险） | 所有查询类型 |
| 5 | `binary-analysis/scripts/initial_analysis.py` | 修改 | 初始分析 |

### 高风险改动

| 改动 | 风险 | 验证要求 |
|------|------|---------|
| query.py 改为调用 `_analysis.py` | 影响所有查询类型 | 每个查询类型语法检查 |

### 代码迁移规范

- query.py 的 `_query_xxx()` 函数改为调用 `_analysis.py` 的共享函数，保持 `_QUERY_HANDLERS` 映射不变
- `initial_analysis.py` 从 `_analysis.py` 导入共享函数，不走 idat，直接 Python import
- `_analysis.py` 不含 `run_headless()` 调用，只导出纯业务函数
- 知识库文件必须自包含（不依赖 Agent prompt 上下文）

## §4 验收标准

### 功能验收

- [ ] `system.transform` output 使用正确的 `output.system.push()` API
- [ ] `compacting` hook 注入 BinaryAnalysis 专用 compaction prompt
- [ ] `event` hook 注册并处理 `session.created`/`session.deleted`/`session.compacted`
- [ ] Agent prompt 净减少 ~31 行
- [ ] 知识库 `idapython-conventions.md` 内容完整且自包含
- [ ] Agent prompt 中有触发加载知识库的指引
- [ ] `context-persistence.md` 反映当前实现
- [ ] `scripts/initial_analysis.py` 不再重复实现 query.py 的逻辑
- [ ] query.py 所有查询类型对外接口不变

### 回归验收

- [ ] query.py 语法检查通过
- [ ] update.py 语法检查通过
- [ ] scripts/initial_analysis.py 语法检查通过
- [ ] _analysis.py 语法检查通过
- [ ] _utils.py 语法检查通过
- [ ] _base.py 语法检查通过
- [ ] Plugin 语法检查通过（`node --check`）

### 架构验收

- [ ] 依赖方向: `_analysis.py` → `_utils.py` → `_base.py`（单向），`query.py` → `_analysis.py`，`scripts/initial_analysis.py` → `_analysis.py`
- [ ] 知识库文件路径使用相对路径
- [ ] Agent prompt < 450 行

## §5 与现有需求文档的关系

无前置需求文档。本次改进基于 Phase 0 审计发现。
