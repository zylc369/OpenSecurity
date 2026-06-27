# 进化需求：Plugin 注入 $PYTHON_CMD 消除跨平台 python 命令歧义

> 日期: 2026-05-26
> 来源: 用户直接提方案
> 痛点: agent prompt 中每处 python 调用都要写 bash/PowerShell 双列表格，维护成本高且遗漏就失败

---

## §1 背景与目标

### 问题

agent prompt 和知识库中的 Python 命令调用存在跨平台问题：
- Linux/macOS 用 `python3`，Windows 用 `python`
- 当前方案：每处调用都写 bash/PowerShell 双列表格（task-initialization.md、security-coordinator.md）
- 问题：新增脚本时容易遗漏平台判断；双列表格浪费上下文

### 方案

Plugin 在启动时检测系统可用的 Python 命令（`python3` 或 `python`），注入为 `$PYTHON_CMD` 环境变量。所有 agent prompt 和知识库文件统一使用 `$PYTHON_CMD`。

### 目标

1. 从机制上消除 `python3`/`python` 的平台歧义
2. 简化 task-initialization.md 和 security-coordinator.md 中的跨平台表格
3. 修复 Plugin 内部硬编码的 `python3`（buildSubSessionSystem 行 419）

---

## §2 技术方案

### 改动 1：Plugin 添加 Python 命令检测

**文件**：`plugins/security-analysis.ts`

- 新增 `detectPythonCmd()` 函数：尝试 `python3 --version`，失败则尝试 `python --version`，都失败则 fallback 到 `python`
- 模块级缓存，Plugin 生命周期内只检测一次
- Plugin 启动时调用一次，确保早期失败可观测

检测逻辑：
```
python3 --version 成功 → "python3"
python --version 成功  → "python"
都失败                 → "python"（fallback）
```

### 改动 2：buildEnvSection 注入 $PYTHON_CMD

**文件**：`plugins/security-analysis.ts`，`buildEnvSection` 函数

在环境信息中新增一行：
```
- 系统 Python ($PYTHON_CMD): python
```

位置：在 `IDA Pro` 行之后、编译器行之前。

### 改动 3：修复 Plugin 内部硬编码的 python3

**文件**：`plugins/security-analysis.ts`

| 位置 | 当前 | 改为 |
|------|------|------|
| `buildSubSessionSystem` 行 419 | `python3 "$SHARED_DIR/scripts/detect_env.py"` | `${pythonCmd} "$SHARED_DIR/scripts/detect_env.py"` |
| `system.transform` 行 1327 | `python "$SHARED_DIR/scripts/detect_env.py"` | `${pythonCmd} "$SHARED_DIR/scripts/detect_env.py"` |
| `tool.execute.before` 行 1375 | `python "$SHARED_DIR/scripts/detect_env.py"` | `${pythonCmd} "$SHARED_DIR/scripts/detect_env.py"` |

### 改动 4：简化 task-initialization.md

**文件**：`binary-analysis/knowledge-base/task-initialization.md`

将三个 Step 中的 bash/PowerShell 双列表格替换为单行 `$PYTHON_CMD` 命令。同时移除跨平台注意事项和 fallback 路径说明（`$PYTHON_CMD` 已由 Plugin 保证可用）。

### 改动 5：简化 security-coordinator.md §0.1

**文件**：`agents/security-coordinator.md`

将 §0.1 的双列表格替换为 `$PYTHON_CMD` 单行命令。移除 fallback 路径说明。

### 改动 6：更新 running-environment.md

**文件**：`agents-rules/running-environment.md`

记录 `$PYTHON_CMD` 变量的含义和用法。

---

## §3 实施规范

### §3.1 实施步骤拆分

步骤 1. Plugin 添加 detectPythonCmd() + buildEnvSection 注入
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~30 行（新增函数 + import + buildEnvSection 改动 + 启动时调用）
  - 验证点: Plugin 加载后日志中可见 `detectPythonCmd: detected python3/python`；agent 收到的系统提示中包含 `系统 Python ($PYTHON_CMD): python`
  - 依赖: 无

步骤 2. 修复 Plugin 内部硬编码的 python3/python
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~10 行（3 处替换）
  - 验证点: `node --check security-analysis.ts` 语法通过
  - 依赖: 步骤 1

步骤 3. 简化 task-initialization.md
  - 文件: `binary-analysis/knowledge-base/task-initialization.md`
  - 预估行数: ~20 行（替换 3 个双列表格为单行命令，移除注意事项）
  - 验证点: 文件中不再出现 "Bash"/"PowerShell" 平台判断表格
  - 依赖: 步骤 1

步骤 4. 简化 security-coordinator.md §0.1
  - 文件: `agents/security-coordinator.md`
  - 预估行数: ~15 行（替换 §0.1 双列表格，移除 fallback 说明）
  - 验证点: 文件中不再出现 "Bash"/"PowerShell" 平台判断表格
  - 依赖: 步骤 1

步骤 5. 更新 running-environment.md
  - 文件: `agents-rules/running-environment.md`
  - 预估行数: ~5 行
  - 验证点: 文件包含 `$PYTHON_CMD` 说明
  - 依赖: 步骤 1

---

## §4 验收标准

### 功能验收
- [ ] Plugin 启动日志中可见 `detectPythonCmd: detected python3/python`
- [ ] agent 系统提示中包含 `系统 Python ($PYTHON_CMD): <命令>`
- [ ] `buildSubSessionSystem` 使用检测到的命令（非硬编码 `python3`）
- [ ] 错误消息使用检测到的命令
- [ ] task-initialization.md 三个 Step 均使用 `$PYTHON_CMD`
- [ ] security-coordinator.md §0.1 使用 `$PYTHON_CMD`
- [ ] running-environment.md 记录 `$PYTHON_CMD`

### 回归验收
- [ ] `create_task_dir.py` 实际调用成功（端到端）
- [ ] `detect_env.py` 实际调用成功（端到端）
- [ ] 其他 agent prompt 不受影响（binary-analysis、mobile-analysis 通过 `{{buwai-rule:task-initialization}}` 读取更新后的知识库）

### 架构验收
- [ ] `$PYTHON_CMD` 和 `$BA_PYTHON` 并存不冲突（系统 Python vs venv Python）
- [ ] 检测结果仅在 Plugin 进程内缓存，不写入文件（检测成本可忽略）

---

## §5 与现有需求文档的关系

- `2026-05-26-coordinator-stability-and-web-knowledge-align.md` — 上一轮修复（双列表格方案），本次用 Plugin 注入方案替代
