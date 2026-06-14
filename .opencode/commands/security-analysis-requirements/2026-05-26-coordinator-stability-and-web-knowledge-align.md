# 进化需求：security-coordinator 执行稳定性修复 + web-analysis 知识库对齐

> 日期: 2026-05-26
> 来源: security-coordinator 执行 WebCTF 回头看任务后的复盘
> 痛点: coordinator 未使用 create_task_dir.py（连续两次）；新知识/脚本未被 web-analysis agent 引用

---

## §1 背景与目标

### 问题 1：新知识/脚本未被引用
security-coordinator（及 security-analysis-evolve）在 WebCTF 回头看任务中产出了新知识文档和脚本，但 web-analysis agent prompt 未引用它们，导致这些资源无法在后续分析中被使用。

### 问题 2：create_task_dir.py 未被调用
security-coordinator 在两次执行中都没有调用 `create_task_dir.py`，而是手动 mkdir 创建任务目录。目录名格式不符合脚本规范（如 `web-ctf-review-20260525-220529` vs `20260525_220529_xxxx`），导致 sessionID 映射缺失，压缩恢复后无法自动找回任务目录。

**根因分析**：
1. `security-coordinator.md` §0.1 使用 bash 语法（`$TASK_DIR=$(python3 "$SHARED_DIR/scripts/create_task_dir.py")`），但执行环境是 PowerShell
2. `$SHARED_DIR` 环境变量可能为空（Plugin 注入不一定可靠）
3. `python3` 在 Windows 上通常不存在（应为 `python`）
4. 缺少验证步骤：创建目录后没有检查格式是否正确

### 问题 3：子 agent 调用
经查证，coordinator **确实调用了子 agent**（session 映射文件存在），但子 agent 执行中断，coordinator 按降级策略自行完成分析。这符合 prompt 的"降级处理"规则，不需要修复。

### 目标
1. 修复新知识/脚本与 web-analysis agent 的引用对齐
2. 修复 coordinator 的任务目录创建流程，使其在 PowerShell 环境下也能可靠执行
3. 所有修复需同时适用于 bash 和 PowerShell 环境

---

## §2 技术方案

### 改动 1：web-analysis agent 引用对齐（已完成）

**改动文件**：`agents/web-analysis.md`
**改动内容**：
- 知识库索引新增 `bot-patterns.md`
- 工具清单新增 `markdown_fuzz.py`、`sandbox_escape.py`、`bot_analyze.py`
- 使用示例新增 3 个脚本的 import 示例

### 改动 2：bot-patterns.md 去重精简（已完成）

**改动文件**：`knowledge-base/bot-patterns.md`
**改动内容**：
- 删除与 `web-methodology.md` §1.5 重复的详细时间线和分析流程
- 删除与 `nextjs-analysis.md` §4.1 重复的 Chromium AE 特性
- 保留独有价值：Bot 代码通用结构、快速识别信号、决策树、安全决策分析
- 添加交叉引用到 web-methodology.md 和 attack-orchestration.md

### 改动 3：sandbox_escape.py flag 正则可配置化（已完成）

**改动文件**：`scripts/sandbox_escape.py`
**改动内容**：`generate_sandbox_test_payload` 新增 `flag_pattern` 参数，默认值 `SK-CERT\{[^}]+\}`

### 改动 4：security-coordinator.md 任务目录创建修复

**改动文件**：`agents/security-coordinator.md`
**改动内容**：

将 §0.1 的 bash 语法改为跨平台兼容的方式：

**修改前**：
```bash
$TASK_DIR=$(python3 "$SHARED_DIR/scripts/create_task_dir.py")
```

**修改后**：
```
执行命令创建父任务目录（根据操作系统选择命令）:

  PowerShell: python "$SHARED_DIR/scripts/create_task_dir.py"
  Bash:      python3 "$SHARED_DIR/scripts/create_task_dir.py"

如果 $SHARED_DIR 为空，使用硬编码路径:
  PowerShell: python "C:\Codes\open-security\.opencode\binary-analysis\scripts\create_task_dir.py"
  Bash:      python3 "$HOME/.config/opencode/binary-analysis/scripts/create_task_dir.py"

输出即为 $TASK_DIR 路径。记录到变量后继续。

验证: 输出路径必须匹配格式 YYYYMMDD_HHMMSS_xxxx（如 20260526_223243_ee92）。
     如果不匹配，说明脚本未被正确调用，必须重新执行上述命令。
```

### 改动 5：csp-bypass.md 补充 CSP 位置判断（已完成）

**改动文件**：`knowledge-base/csp-bypass.md`
**改动内容**：在 max_input_vars 章节补充如何判断 CSP 在代码层 vs 服务器层

---

## §3 实施规范

### §3.1 实施步骤拆分

步骤 1. 修改 security-coordinator.md §0.1 任务目录创建指令
  - 文件: `agents/security-coordinator.md`
  - 预估行数: ~20 行（修改 §0.1 区域）
  - 验证点: 修改后的指令同时包含 PowerShell 和 Bash 命令；包含 $SHARED_DIR 为空时的 fallback 路径；包含验证步骤
  - 依赖: 无

步骤 2. 同步修改所有引用 create_task_dir.py 的 agent prompt
  - 文件: `agents/web-analysis.md`（已有 `{{buwai-rule:task-initialization}}` 占位符，检查片段内容）
  - 文件: `agents/binary-analysis.md`（检查是否有同样问题）
  - 文件: `agents/mobile-analysis.md`（检查是否有同样问题）
  - 预估行数: ~0-10 行（取决于片段是否已处理）
  - 验证点: 其他 agent 是否通过 `{{buwai-rule:task-initialization}}` 片段引用了创建逻辑。如果是，只需修改片段文件
  - 依赖: 步骤 1

步骤 3. 验证所有改动的一致性
  - 文件: 无新文件
  - 预估行数: 0
  - 验证点:
    - web-analysis.md 引用了所有新知识库和脚本
    - bot-patterns.md 的交叉引用路径正确
    - security-coordinator.md 的任务目录创建指令跨平台兼容
    - 所有 Python 脚本语法正确
  - 依赖: 步骤 1、2

---

## §4 验收标准

### 功能验收
- [ ] web-analysis.md 的知识库索引包含 `bot-patterns.md`
- [ ] web-analysis.md 的工具清单包含 `markdown_fuzz.py`、`sandbox_escape.py`、`bot_analyze.py`
- [ ] bot-patterns.md 不包含与 web-methodology.md §1.5 大段重复的内容
- [ ] bot-patterns.md 包含指向 web-methodology.md 和 attack-orchestration.md 的交叉引用
- [ ] sandbox_escape.py 的 `generate_sandbox_test_payload` 支持 `flag_pattern` 参数
- [ ] security-coordinator.md §0.1 同时包含 PowerShell 和 Bash 命令
- [ ] security-coordinator.md §0.1 包含 $SHARED_DIR 为空时的 fallback 路径
- [ ] security-coordinator.md §0.1 包含目录名格式验证步骤

### 回归验收
- [ ] 现有脚本（cache_poison.py、param_bomb.py、web_helpers.py）功能不受影响
- [ ] 现有知识库文档结构不变（只做了精简和补充，没有删除核心内容）
- [ ] web-analysis agent 原有的知识库引用（7 个文档）仍然有效

### 架构验收
- [ ] 新文件放在正确的位置（web-analysis/knowledge-base/ 和 web-analysis/scripts/）
- [ ] registry.json 包含所有 6 个脚本
- [ ] 跨文件引用使用 `$AGENT_DIR`/`$SHARED_DIR` 变量（不硬编码绝对路径）

---

## §5 与现有需求文档的关系

- `2026-05-22-security-coordinator.md` — 创建 coordinator agent（本次修改 coordinator prompt）
- `2026-05-05-web-analysis-agent.md` — 创建 web-analysis agent（本次新增引用）
- `2026-05-25-delegate-analysis-async.md` — delegate_analysis 异步轮询（子 agent 调用的技术基础）
