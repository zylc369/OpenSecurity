# Agent Prompt 片段系统 — 消除 Agent 间通用规则重复

## §1 背景与目标

**来源痛点**：binary-analysis.md（359行）和 mobile-analysis.md（267行）有约 62 行重复的通用规则（运行环境、变量初始化、阶段 0、分析执行框架、输出格式、任务存档等）。后续还会创建更多安全分析 agent，重复会加剧。

更新通用规则时需手动同步多个文件（遗漏风险高）；创建新 agent 时需手动复制通用规则（质量难保证）。

**预期收益**：
- 上下文：不增不减（通用规则从 agent.md 移到 Plugin 注入，总量不变）
- 轮次：不增不减
- 速度：不增不减
- 准确度：通用规则单一来源，消除"更新时遗漏"风险

## §2 技术方案

### 2.1 整体架构

```
Agent .md（带 {{buwai-rule:xxx}} 占位符）
  ↓ OpenCode 加载 → agent.prompt（占位符原文保留）
  ↓ 拼入 system[0]
  ↓ system.transform hook 触发
  ↓ Plugin 检测 agent .md 的 buwai-extension-id frontmatter
  ↓ 遍历 output.system 数组，正则匹配占位符
  ↓ 读取 agents-rules/xxx.md → 替换占位符
  ↓ LLM 收到展开后的完整 prompt
```

### 2.2 新增文件

**目录：`.opencode/agents-rules/`**

| 片段文件 | 内容 | 行数 |
|---------|------|:----:|
| `running-environment.md` | 运行环境 + 跨平台规则 | 4 |
| `variable-initialization.md` | 变量初始化表 + $BA_PYTHON 强制规则 | 10 |
| `task-initialization.md` | 阶段 0 三步初始化 + 失败/缓存规则 | 8 |
| `analysis-planning-rules.md` | 阶段 B 分析规划 5 条核心规则 | 5 |
| `execution-discipline.md` | 阶段 C 执行纪律表 | 10 |
| `loop-control.md` | 循环控制参数表（3 行通用） | 5 |
| `output-format.md` | 输出格式通用模板 | 10 |
| `task-archive.md` | 任务存档规则 | 3 |

合计：8 个文件，~55 行

### 2.3 占位符格式

```
{{buwai-rule:片段名}}
```

- 前缀 `buwai-rule:` 与 `$ABC` 变量格式完全不同，不会混淆
- 片段名 = `agents-rules/` 下的文件名（不含 `.md`）
- 正则：`/\{\{buwai-rule:([a-zA-Z0-9_-]+)\}\}/g`

### 2.4 Frontmatter 字段

Agent .md 新增自定义字段（OpenCode 不识别的自定义字段会被忽略，Plugin 自行读取 .md 文件解析）：

```yaml
buwai-extension-id: binary-analysis
```

- 存在 → Plugin 执行占位符替换
- 不存在 → Plugin 不处理
- 值：agent 名称（当前仅作文档用途，未来可用于分组加载）

### 2.5 Plugin 修改（security-analysis.ts）

在现有 `system.transform` hook 中新增占位符展开逻辑，在环境信息注入之前执行：

```typescript
// 伪代码
async system.transform(input, output) {
    // ... 现有的 session 检查 ...
    
    const agentName = session.agentName;
    if (!agentName) return;
    
    // 1. 读取 agent .md 文件，解析 frontmatter
    const agentFile = join(AGENTS_DIR, `${agentName}.md`);
    if (!hasBuwaiExtensionId(agentFile)) return;  // 无 frontmatter 字段则跳过
    
    // 2. 遍历 output.system 数组，替换占位符
    const regex = /\{\{buwai-rule:([a-zA-Z0-9_-]+)\}\}/g;
    for (let i = 0; i < output.system.length; i++) {
        if (!output.system[i].includes("{{buwai-rule:")) continue;
        output.system[i] = output.system[i].replace(regex, (_, name) => {
            const content = loadSnippet(name);  // 带缓存
            if (content === null) {
                debugLog(`Snippet not found: ${name}`);
                return _;  // 保留占位符原文
            }
            debugLog(`Expanded snippet: ${name} (${content.length} chars)`);
            return content;
        });
    }
    
    // 3. 然后执行现有的环境信息注入（每 10 次调用）
    // ... existing env injection logic ...
}
```

**加载函数**：

```typescript
interface CacheEntry { content: string | null; mtime: number; }
const snippetCache = new Map<string, CacheEntry>();

function loadSnippet(name: string): string | null {
    const filePath = join(AGENTS_RULES_DIR, `${name}.md`);
    try {
        const stat = statSync(filePath);
        const cached = snippetCache.get(name);
        if (cached && cached.mtime === stat.mtimeMs) return cached.content;
        const content = readFileSync(filePath, "utf-8").trim();
        snippetCache.set(name, { content, mtime: stat.mtimeMs });
        return content;
    } catch {
        debugLog(`Failed to load snippet: ${filePath}`);
        snippetCache.set(name, { content: null, mtime: 0 });
        return null;
    }
}
```

**Frontmatter 检查缓存**：`hasBuwaiExtensionId()` 按 agentName 缓存 `{ result: boolean, mtime: number }`。每次调用只做 `stat()` 取 mtime，mtime 未变则用缓存，变了则重新读取文件。改完 agent .md 后下次 LLM 调用即生效，无需重启 OpenCode。

**Snippet 缓存策略**：同上，缓存 `{ content: string, mtime: number }`。每次调用 `stat()` 检测文件变更，mtime 变了才重新读取内容。改完 snippet 文件后下次 LLM 调用即生效。

**⚠ 关键实现约束**：占位符展开逻辑必须放在 `shouldInject`（每 10 次环境注入）的 `return` 之前。当前 system.transform 在非注入轮次会 `return` 跳过，如果展开逻辑放在 return 之后，9/10 的 LLM 调用不会展开占位符。正确顺序：session 检查 → 占位符展开（每次）→ shouldInject 检查 → 环境信息注入（每 10 次）。

### 2.6 Agent .md 文件修改

两个 agent 文件做相同的操作：
1. Frontmatter 新增 `buwai-extension-id`
2. 通用段落的内容替换为 `{{buwai-rule:xxx}}`
3. 段落标题和结构保持不变
4. Agent 专属补充内容保留在占位符之前或之后

### 2.7 通用规则的统一处理

两个 agent 的一些通用规则有微小差异，统一方式：

| 差异点 | BA 版本 | MA 版本 | 统一方式 |
|-------|--------|--------|---------|
| $SHARED_DIR 描述 | "等于 $AGENT_DIR" | "环境信息'共享目录'" | 用 MA 的通用版（实际值由 Plugin 环境信息注入） |
| detect_env --agent | 无 | `--agent mobile-analysis` | 通用版不带 --agent；MA 在 agent 专属内容中补充此参数 |
| 阶段 B 规则 2 | "根据 scene.scene_tags" | "根据需求关键词" | "根据分析结果和需求选择分析路径" |
| 阶段 B 规则 5 | 有"方案优先" | 无 | 保留在 snippet（MA 多一条规则无副作用） |
| 阶段 C 纪律表 | 每条有详细描述 | 缩略版 | 用 BA 完整版 |
| 循环控制 | 有"数据库锁"行 | 无 | snippet 只含 3 行通用；BA 的"数据库锁"保留在 agent 专属 |
| 输出格式 | 有"操作记录"段 | 有"工具执行记录"段 | snippet 只含通用模板；agent 专属字段保留 |

## §3 实现规范

### 改动范围表

| 文件 | 操作 | 改动量 |
|------|------|-------|
| `.opencode/agents-rules/*.md` | 新增 ×8 | ~55 行 |
| `.opencode/plugins/security-analysis.ts` | 修改 | ~60 行新增 |
| `.opencode/agents/binary-analysis.md` | 修改 | ~55 行替换为占位符 |
| `.opencode/agents/mobile-analysis.md` | 修改 | ~55 行替换为占位符 |

### §3.1 实施步骤拆分

**步骤 1. 创建 agents-rules 目录和 8 个片段文件**
- 文件: `.opencode/agents-rules/` 目录 + 8 个 `.md` 文件
- 预估行数: ~55 行（新建）
- 验证点:
  1. 每个文件内容与下文"片段内容规格"一致
  2. 文件名全小写、连字符分隔
- 依赖: 无

**步骤 2. Plugin 添加占位符展开逻辑**
- 文件: `.opencode/plugins/security-analysis.ts`
- 预估行数: ~60 行（新增）
- 改动内容:
  1. 新增 `AGENTS_RULES_DIR` 常量
  2. 新增 `parseFrontmatter()` 函数（简单 YAML 解析，支持扁平 key-value）
  3. 新增 `loadSnippet()` 函数（带内存缓存）
  4. 在 `system.transform` hook 中，环境信息注入之前，调用占位符展开逻辑
  5. 日志记录每次展开的片段名和字节数
- 验证点:
  1. `node --check security-analysis.ts` 语法检查通过
  2. 日志中可见占位符展开记录（需配合步骤 3 或 4 的 agent .md 修改后验证）
- 依赖: 步骤 1

**步骤 3. 修改 binary-analysis.md**
- 文件: `.opencode/agents/binary-analysis.md`
- 预估行数: ~55 行删除 + ~8 行占位符新增 = 净减 ~47 行
- 改动内容:
  1. Frontmatter 新增 `buwai-extension-id: binary-analysis`
  2. 8 个通用段落内容替换为对应占位符
  3. 保留 agent 专属补充内容不变（常见失败模式、数据库锁行、IDAPython 规范等）
- 验证点:
  1. Frontmatter 包含 `buwai-extension-id`
  2. 所有 `{{buwai-rule:xxx}}` 占位符对应的片段文件存在
  3. Agent 专属内容未被删除（常见失败模式表、结果验证、超时监控、技术选型、工具清单、知识库索引、IDAPython 规范）
  4. 输出格式中 agent 专属内容保留：「操作记录（如有数据库更新）」段、详细统计行（`idat 调用: X 次 | 手写脚本: X 个 | 重试: X 次 | 耗时: Xm Xs`）、「确定: （来自 IDA 数据库）」置信度来源
  5. 总行数 < 450
- 依赖: 步骤 1

**步骤 4. 修改 mobile-analysis.md**
- 文件: `.opencode/agents/mobile-analysis.md`
- 预估行数: ~55 行删除 + ~8 行占位符新增 = 净减 ~47 行
- 改动内容:
  1. Frontmatter 新增 `buwai-extension-id: mobile-analysis`
  2. 8 个通用段落内容替换为对应占位符
  3. 保留 agent 专属补充内容不变（移动端工具、设备管理、frida Bridge 规则等）
  4. 阶段 0 中的 `--agent mobile-analysis` 参数：从通用占位符移出，在占位符后添加独立说明行 `> **mobile-analysis agent**：环境检测命令需添加 \`--agent mobile-analysis\` 参数。`
- 验证点:
  1. Frontmatter 包含 `buwai-extension-id`
  2. 所有占位符对应的片段文件存在
  3. Agent 专属内容未被删除（移动端工具表、IDA 脚本引用、设备管理、知识库索引、frida Bridge 规则）
  4. `--agent mobile-analysis` 参数以独立说明行形式保留在占位符之后
  5. 总行数 < 450
- 依赖: 步骤 1

**步骤 5. 端到端验证**
- 验证点:
  1. binary-analysis agent 启动后，Plugin 日志显示所有占位符被展开（无 `{{buwai-rule:xxx}}` 残留）
  2. mobile-analysis agent 启动后，同上
  3. mobile-analysis.md 中 `--agent mobile-analysis` 参数未丢失
  4. 展开后的 prompt 内容与改动前的内容功能等价
- 依赖: 步骤 2、3、4

## §4 验收标准

### 功能验收
- [ ] 8 个片段文件存在于 `.opencode/agents-rules/` 目录
- [ ] 两个 agent .md 文件的 frontmatter 包含 `buwai-extension-id`
- [ ] Plugin 日志显示占位符展开成功（片段名 + 字节数）
- [ ] LLM 收到的 system prompt 中无 `{{buwai-rule:xxx}}` 残留
- [ ] 不存在的片段名 → 日志警告 + 占位符原文保留

### 回归验收
- [ ] Plugin 的环境信息注入不受影响（每 10 次调用注入一次）
- [ ] Plugin 的 compacting hook 不受影响
- [ ] Plugin 的 tool.execute.before hook 不受影响
- [ ] 无 `buwai-extension-id` 的 agent 不受影响（无占位符替换）

### 架构验收
- [ ] 片段文件放在 `.opencode/agents-rules/`（不在 knowledge-base/ 中，语义不同）
- [ ] 片段内容使用 `$AGENT_DIR`/`$SHARED_DIR` 变量（与 agent prompt 一致）
- [ ] 依赖方向：agent .md → 占位符 → Plugin 读取 agents-rules/ → 注入（无循环依赖）

## §5 与现有需求文档的关系

独立需求，不依赖其他未完成的需求文档。

---

## 附录：片段内容规格

### running-environment.md

```markdown
> 动态环境信息由 Plugin 注入到上下文中。环境检测见"阶段 0"。

**跨平台**：bash 模板用 `python3`/`idat`/`VAR=xxx cmd`；PowerShell 模板用 `python`/`idat.exe`/`$env:VAR="xxx"; cmd`。
```

### variable-initialization.md

```markdown
环境信息由 Plugin 在每轮注入（见系统提示中的"环境信息"段）。在首次需要执行脚本的 bash 命令中，从环境信息提取路径赋值：

| 变量 | 来源 | 说明 |
|------|------|------|
| `$AGENT_DIR` | 环境信息"Agent 目录 ($AGENT_DIR)" | 本 Agent 的工具目录 |
| `$SHARED_DIR` | 环境信息"共享目录 ($SHARED_DIR)" | 共享分析能力目录 |
| `$IDAT` | 环境信息"IDA Pro"路径 + `/idat` | 需检查文件存在性 |
| `$BA_PYTHON` | 阶段 0 env.json 的 `venv_python` | 带第三方包的 venv Python |

**强制**：带第三方包的 Python 脚本必须用 `$BA_PYTHON`，禁止用系统 Python（仅 `detect_env.py` 例外）。
```

### task-initialization.md

```markdown
在阶段 A 之前必须按顺序执行以下 3 步。详细流程见 `$SHARED_DIR/knowledge-base/task-initialization.md`。

1. **创建任务目录**：`TASK_DIR=$(python3 "$SHARED_DIR/scripts/create_task_dir.py")`
2. **环境检测**：`python3 "$SHARED_DIR/scripts/detect_env.py" --output "$TASK_DIR/env.json"`
3. **初始化 $BA_PYTHON**：从 `~/bw-security-analysis/env_cache.json` 提取 `venv_python`

环境检测失败 → **停下来告知用户，禁止继续**。环境检测结果缓存 24h（`~/bw-security-analysis/env_cache.json`），无需每次重新检测。
```

### analysis-planning-rules.md

```markdown
核心规则：
1. **先规划再执行** — 禁止无方案直接开始分析
2. **场景驱动** — 根据分析结果和需求选择分析路径
3. **知识库按需加载** — 只读取场景对应的文档，不全部加载
4. **必须输出方案** — 向用户输出完整方案（分析路径、计划步骤、预计耗时），禁止跳过
5. **方案优先** — 未输出方案前禁止执行任何分析调用
```

### execution-discipline.md

```markdown
按规划执行，遵守以下**执行纪律**：

| 纪律 | 规则 |
|------|------|
| **失败快速切换** | 同一方向连续失败 **2 次** → 强制切换方向，禁止第三次尝试 |
| **超时保护** | 单步骤耗时超过预期 2x → 暂停评估，考虑换方向 |
| **方向选择** | 遵循知识库中的优先级顺序，低耗高收益方向优先 |
| **进度输出** | 用户不应看到超过 30 秒的无输出间隔 |
| **禁止重复** | 失败后必须记录失败原因和已尝试的方向，避免重复 |
```

### loop-control.md

```markdown
| 参数 | 值 |
|------|-----|
| 最大尝试次数 | 2（同一方向连续 2 次失败即切换方向） |
| 单次 idat 超时 | 300 秒 |
| 累计耗时上限 | 120 分钟 |
```

### output-format.md

文件内容（注意：包含一个 markdown 代码块，外层的 ``` 是文件内容的一部分）：

    ```
    ## 分析摘要
    （一句话说明分析结论）

    ## 详细结果
    （按分析维度组织的分析细节）

    ## 置信度说明
    - 确定: （来自工具输出）
    - 推测: （AI 推理，标注置信度）

    ## 执行统计
    - 总耗时: Xm Xs
    - 任务目录: ~/bw-security-analysis/workspace/<task_id>/
    ```

### task-archive.md

```markdown
命令结束时在任务目录写入 `summary.json`（包含 binary_path、user_request、status、metrics）。
```
