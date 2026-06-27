# 环境变量重命名：$SCRIPTS_DIR/$IDA_SCRIPTS_DIR → $AGENT_DIR/$SHARED_DIR

## §1 背景与目标

**来源**：用户使用 mobile-analysis agent 时发现变量命名 $SCRIPTS_DIR / $IDA_SCRIPTS_DIR 高度混淆：
- `$IDA_SCRIPTS_DIR` 不只是 IDA 脚本，还包含通用知识库（Frida 模板、密码学模式、加壳处理等）
- `$SCRIPTS_DIR` 听起来像通用脚本目录，实际是"当前 agent 专属目录"
- binary-analysis 下两个变量指向同一目录的特殊关系靠注释说明，容易忽略

**预期收益**：变量名自解释，减少 AI 因混淆而引用错误路径的概率，降低新 agent 接入的理解门槛。

**影响面**：34 个文件，~205 处替换。纯机械替换，无逻辑变更。

## §2 技术方案

### 2.1 变量映射

| 旧名 | 新名 | 含义 |
|------|------|------|
| `$SCRIPTS_DIR` | `$AGENT_DIR` | 当前 agent 的专属目录（工具 + 知识库 + 脚本） |
| `$IDA_SCRIPTS_DIR` | `$SHARED_DIR` | 所有 agent 共享的通用分析能力目录（始终指向 binary-analysis/） |
| `脚本目录 ($SCRIPTS_DIR)` | `Agent 目录 ($AGENT_DIR)` | Plugin 注入的环境信息描述文本 |
| `IDA 通用脚本目录 ($IDA_SCRIPTS_DIR)` | `共享目录 ($SHARED_DIR)` | Plugin 注入的环境信息描述文本 |

### 2.2 对各 agent 的语义变化

| Agent | 旧：$SCRIPTS_DIR | 新：$AGENT_DIR | 旧：$IDA_SCRIPTS_DIR | 新：$SHARED_DIR |
|-------|-----------------|---------------|---------------------|----------------|
| binary-analysis | .opencode/binary-analysis/ | .opencode/binary-analysis/ | .opencode/binary-analysis/（等于 $SCRIPTS_DIR） | .opencode/binary-analysis/（等于 $AGENT_DIR） |
| mobile-analysis | .opencode/mobile-analysis/ | .opencode/mobile-analysis/ | .opencode/binary-analysis/ | .opencode/binary-analysis/ |

### 2.3 Plugin 代码变更

文件：`.opencode/plugins/security-analysis.ts`

变更点：
1. `buildEnvSection()` 中的输出文本：`脚本目录 ($SCRIPTS_DIR)` → `Agent 目录 ($AGENT_DIR)`，`IDA 通用脚本目录 ($IDA_SCRIPTS_DIR)` → `共享目录 ($SHARED_DIR)`
2. `getCompactionReminder()` 中提及变量名的文本
3. 内部函数 `getScriptDir()` 和变量名 `scriptsDir` 不改（内部实现细节，不影响运行时变量名）

### 2.4 不改的范围

| 不改 | 原因 |
|------|------|
| Plugin 内部变量 `scriptsDir` / `getScriptDir()` | 内部实现，不影响注入到 prompt 的变量名 |
| Python 脚本中的 `FRIDA_SCRIPTS_DIR`（manage_frida.py） | 这是 Python 内部变量，不是 shell 环境变量，不受 Plugin 注入影响 |
| 历史需求文档（commands/security-analysis-requirements/ 下的旧文档） | 已归档，改动无实际收益且增加风险 |

### 2.5 binary-analysis prompt 特殊处理

binary-analysis prompt 中有特殊说明：`$IDA_SCRIPTS_DIR` 等于 `$SCRIPTS_DIR`（两个变量指向同一目录）。
重命名后改为：`$SHARED_DIR` 等于 `$AGENT_DIR`（两个变量指向同一目录）。

mobile-analysis prompt 中 `create_task_dir.py` 和 `detect_env.py` 使用 `$IDA_SCRIPTS_DIR` 调用 → 改为 `$SHARED_DIR`（因为这些脚本确实在共享目录中，且 mobile-analysis 依赖此目录）。

## §3 实现规范

### 3.1 实施步骤拆分

```
步骤 1. 重命名 Plugin 中的环境变量注入文本
  - 文件: .opencode/plugins/security-analysis.ts
  - 预估行数: ~6 行修改
  - 验证点: node --check 验证语法通过；grep 确认文件中不再出现旧变量名文本（"$SCRIPTS_DIR" / "$IDA_SCRIPTS_DIR"），只有内部变量 scriptsDir 保留
  - 依赖: 无

步骤 2. 重命名 binary-analysis agent prompt 中的变量
  - 文件: .opencode/agents/binary-analysis.md
  - 预估行数: ~16 行修改
  - 验证点: grep 确认文件中不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
  - 依赖: 无

步骤 3. 重命名 mobile-analysis agent prompt 中的变量
  - 文件: .opencode/agents/mobile-analysis.md
  - 预估行数: ~16 行修改
  - 验证点: grep 确认文件中不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
  - 依赖: 无

步骤 4. 重命名 security-analysis-evolve agent prompt 中的变量
  - 文件: .opencode/agents/security-analysis-evolve.md
  - 预估行数: ~1 行修改
  - 验证点: grep 确认文件中不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
  - 依赖: 无

步骤 5. 重命名 binary-analysis 知识库中的变量（7 个文件）
  - 文件:
    - .opencode/binary-analysis/knowledge-base/templates.md
    - .opencode/binary-analysis/knowledge-base/verification-patterns.md
    - .opencode/binary-analysis/knowledge-base/dynamic-analysis-frida.md
    - .opencode/binary-analysis/knowledge-base/process-patch-reference.md
    - .opencode/binary-analysis/knowledge-base/dynamic-analysis.md
    - .opencode/binary-analysis/knowledge-base/gui-automation.md
    - .opencode/binary-analysis/knowledge-base/packer-handling.md
    - .opencode/binary-analysis/knowledge-base/opencode-plugin-debugging.md
  - 预估行数: ~50 行修改
  - 验证点: grep 确认这 8 个文件中不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
  - 依赖: 无

步骤 6. 重命名 mobile-analysis 知识库和脚本中的变量（5 个 md + 1 个 json）
  - 文件:
    - .opencode/mobile-analysis/knowledge-base/mobile-methodology.md
    - .opencode/mobile-analysis/knowledge-base/frida-hook-principles.md
    - .opencode/mobile-analysis/knowledge-base/frida-17x-api.md
    - .opencode/mobile-analysis/knowledge-base/android-unpacking.md
    - .opencode/mobile-analysis/knowledge-base/mobile-frida.md
    - .opencode/mobile-analysis/knowledge-base/frida-17x-bridge.md
    - .opencode/mobile-analysis/scripts/registry.json
    - .opencode/mobile-analysis/README.md
  - 预估行数: ~19 行修改
  - 验证点: grep 确认这些文件中不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
  - 依赖: 无

步骤 7. 重命名 binary-analysis 脚本 registry.json 中的变量
  - 文件: .opencode/binary-analysis/scripts/registry.json
  - 预估行数: ~8 行修改
  - 验证点: python -c "import json; json.load(open('<文件>'))" 验证 JSON 合法；grep 确认不再出现旧变量名
  - 依赖: 无

步骤 8. 重命名 commands 中活跃文档的变量
  - 文件:
    - .opencode/commands/gui-interact-pc.md
    - .opencode/commands/security-analysis-evolve.md
    - .opencode/commands/security-analysis-requirements/mobile-analysis-evolve-v1.md（未归档的活跃演进文档）
  - 预估行数: ~6 行修改
  - 验证点: grep 确认这三个文件中不再出现旧变量名
  - 依赖: 无

步骤 9. 全局验证
  - 文件: 无新文件
  - 预估行数: 0
  - 验证点:
    1. grep 全 .opencode/ 目录（排除 commands/security-analysis-requirements/ 下的旧需求文档和 mobile-analysis/scripts/manage_frida.py 内部 Python 变量）确认不再出现 $SCRIPTS_DIR 或 $IDA_SCRIPTS_DIR
    2. 逐个检查 exclude 列表中的合理残留：
       - commands/security-analysis-requirements/ 下的历史文档（不改，预期残留）
       - mobile-analysis/scripts/manage_frida.py 中的 FRIDA_SCRIPTS_DIR（Python 内部变量，不改）
    3. node --check 验证 Plugin 语法
    4. 所有修改过的 JSON 文件语法验证
  - 依赖: 步骤 1-8
```

### 3.2 编码规则

1. **纯文本替换**：$SCRIPTS_DIR → $AGENT_DIR，$IDA_SCRIPTS_DIR → $SHARED_DIR。不改变任何逻辑、缩进、换行。
2. **中文描述同步修改**：
   - "脚本目录" → "Agent 目录"
   - "IDA 通用脚本目录" → "共享目录"
   - "共享 IDA 脚本目录" → "共享目录"
3. **不修改历史需求文档**（commands/security-analysis-requirements/ 下 2026-05-01 之前的文档）
4. **不修改 Python 内部变量**（manage_frida.py 中的 FRIDA_SCRIPTS_DIR）

## §4 验收标准

### 功能验收
- [ ] Plugin 注入的环境信息中出现 `Agent 目录 ($AGENT_DIR)` 和 `共享目录 ($SHARED_DIR)`
- [ ] 所有 agent prompt 中的变量引用已更新
- [ ] 所有知识库文档中的路径引用已更新
- [ ] registry.json 中的 usage 模板已更新

### 回归验收
- [ ] Plugin `node --check` 通过
- [ ] 所有修改过的 JSON 文件 `json.load()` 通过
- [ ] 全局 grep 确认无遗漏（排除已知例外）

### 架构验收
- [ ] 变量名含义清晰，新读者无需额外解释即可理解
- [ ] 未引入新依赖或新文件
- [ ] 内部实现（Plugin 代码逻辑、Python 脚本逻辑）未受影响

## §5 与现有需求文档的关系

- 本需求是独立的命名改进，不依赖也不阻塞其他需求
- 与 `2026-04-29-mobile-analysis-agent.md` 相关：该文档引入了 $IDA_SCRIPTS_DIR 的跨 agent 共享机制，本需求只改命名不改机制
