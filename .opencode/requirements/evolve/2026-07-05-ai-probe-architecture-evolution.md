# 需求：AI 探测架构演进

> 来源：本次会话深度调研（ai-dialogue 调用机制、Task/Hook 能力边界、靶子 agent 选择、临时文件放置）
> 状态：待实施

---

## §1 背景与目标

### 1.1 来源

本次会话从"能否用 Task 工具替代 ai-dialogue.py"出发，逐步查证了 opencode 架构对"动态指定模型""Hook 改模型""靶子 agent 选择""临时文件放置"的真实约束，得出 ai-dialogue 不可替代但定位需调整、配套需要批处理与自主编排的结论。

### 1.2 调研结论（架构事实，方案成立的依据）

| 结论 | 证据 |
|------|------|
| Task 工具不能调用时指定 model | task.ts:43-62 参数无 model；子任务 model = agent frontmatter 配置或父会话 fallback |
| Hook 不能改 model | plugin/src/index.ts 全部 hook 的 output 无 model 字段（chat.params 只改 temperature 等） |
| ai-dialogue 是动态指定 model 的唯一通路 | POST /session 带 model + 多轮 send，绕开 Task/Hook 限制 |
| `--agent ai-security-analysis` 给靶子注入攻击方法论 | ai-security-analysis.md:111-145 含越狱框架/payload 模板，扭曲靶子基线 |
| AGENTS.md 注入所有会话（含靶子 build） | instruction.ts findUp 加载，第10条"写任务目录"对无任务目录会话是矛盾指令 |
| system.transform 的 requireSecurityAgent 只注入 SECURITY_AGENTS | 通用规则到不了靶子；用"分层注入"解决（通用层在过滤前） |
| 临时目录白名单是 `os.tmpdir()/opencode`（global.ts:15），不是 `/tmp` | 写 /tmp 触发 external_directory ask；写 `os.tmpdir()/opencode` allow |

### 1.3 痛点

1. **靶子被注入攻击方法论**：`--agent ai-security-analysis` 让靶子收到越狱知识，扭曲防线评估的基线
2. **AGENTS.md 第10条三处重复且误伤**：与 execution-discipline.md 的"文件放置规则"重复；"写任务目录"对无任务目录的靶子（build）是矛盾指令
3. **逐轮 send 机械负担重**：ai-security-analysis.md:208-218 硬编码 create→send→...→delete，N 轮攻防 = N 轮 agent 对话，靶子回复逐轮塞满上下文
4. **agent 编排不够自主**：工作流硬编码，未发挥知识库的自主规划能力
5. **临时目录路径获取不一致**：AI 不知道白名单目录是 `os.tmpdir()/opencode`，往 /tmp 写卡权限

### 1.4 目标

1. 靶子降级 build：`--agent` 推荐值从 ai-security-analysis 改为 build（去掉靶子的攻击方法论注入）
2. 临时文件放置通用注入：system.transform 加通用层，所有会话（含靶子）收到白名单临时目录绝对路径
3. ai-dialogue 批处理子命令（A 方案）：广度扫描一次跑完，减少逐轮 send
4. agent 自主编排（B 方案）：ai-security-analysis 自主规划攻防，ai-dialogue 退为底层原语
5. AGENTS.md 第10条删除（通用注入 + execution-discipline.md 已覆盖）
6. 文档同步：所有 `--agent ai-security-analysis` 引用改为 build

---

## §2 技术方案

### 2.1 system.transform 分层注入

在 system.transform handler（security-analysis.ts:478）的 try 块内、requireSecurityAgent（line 481）**之前**插入通用注入层：

```ts
// 顶部新增 import（join 已从 "path" 引入，无需重复）
import { tmpdir } from "os";

// system.transform handler 内（line 480 后）、requireSecurityAgent（line 481）之前：
// ── 通用层：所有会话（含靶子 build、explore 等）──
output.system.push(
  `\n## 临时文件放置\n` +
  `如需写临时文件，写到 ${join(tmpdir(), "opencode")}/ 下。\n` +
  `> 该目录权限已放行，不会触发权限申请。`
);

// ── 专属层：仅 SECURITY_AGENTS（原有逻辑不变）──
const session = ctx.sessionManager.requireSecurityAgent(...)  // line 481 原有
if (!session) return;  // 非安全 agent 到此为止，但通用层已注入
```

- 路径用 Node `tmpdir()`（与 global.ts:15 白名单基准同源同算法，跨平台）；`join` 复用 line 2 已有的 `import { join, ... } from "path"`
- 通用层写一次，专属层不动 → 分层而非分叉，requireSecurityAgent 语义不变
- 靶子（build）走通用层，收到临时目录路径

### 2.2 靶子降级 build

| 文件 | 现状 | 改为 |
|------|------|------|
| ai-security-analysis.md:174 | "AI 安全分析必须传 `--agent ai-security-analysis`" | "靶子必须传 `--agent build`（裸模型基线，不注入攻击方法论）" |
| ai-security-analysis.md:180 | create 命令 `--agent ai-security-analysis` | `--agent build` |
| ai-security-analysis.md:186 | chat 命令 `--agent ai-security-analysis` | `--agent build` |

ai-dialogue.py 的 `--agent` **保持必传不动**（显式优于隐式）。

### 2.3 ai-dialogue 批处理子命令（A 方案）

新增 `scan` 子命令：传入策略文件，一次跑完多轮，返回聚合 JSON。

**策略文件格式**（JSON）：
```json
{
  "target_model": "deepseek-v4-pro",
  "provider": "opencode-go",
  "agent": "build",
  "stages": [
    {"name": "baseline", "prompts": ["正常问题1", "正常问题2"]]},
    {"name": "injection", "prompts": ["payload1", "payload2"]}
  ]
}
```

**命令**：
```bash
$PYTHON_CMD $SHARED_DIR/scripts/ai-dialogue.py scan --strategy <策略文件.json> --output $TASK_DIR/<结果>.json
```

**行为**：create 会话 → 按 stages 顺序 send 每个 prompt → 收集所有回复 → delete 会话 → 输出聚合 JSON（每条含 stage/prompt/reply）。

**输出格式**：
```json
{
  "session_id": "...",
  "target_model": "...",
  "results": [
    {"stage": "baseline", "prompt": "...", "reply": "..."},
    {"stage": "injection", "prompt": "...", "reply": "..."}
  ]
}
```

适用场景：基线探测、多向量初扫、渐进式 DAN 梯度等**可预先结构化**的广度扫描。深度突破（需动态判断）仍用 send 逐轮。

### 2.4 agent 自主编排（B 方案）

重构 ai-security-analysis.md 的"多轮攻防工作流"（line 208-218）：

- 现状：硬编码 create→send→send→...→summarize→delete 逐轮流程
- 改为：agent 基于知识库（llm-attack-methodology 6 阶段、bypass-framework-matrix 决策树）自主规划整段攻防
- ai-dialogue 退为底层原语：广度阶段调 scan（批处理），深度阶段调 send（逐轮）
- agent 自主决定何时切换、何时停止，不停下来问用户

具体 prompt 改动在实施时细化（依赖 A 的 scan 命令先就位）。

### 2.5 AGENTS.md 第10条删除

删除 AGENTS.md:81 "## 10. 禁止的目录"整节。理由：
- 通用临时文件放置已由 Plugin system.transform 通用层注入（所有会话，含靶子）
- 持久产物写 `$TASK_DIR` 已由 execution-discipline.md（agents-rules，只注入 SECURITY_AGENTS）规范
- 三处重复消除，且消除对靶子的矛盾指令

### 2.6 文档同步

| 文件 | 改动 |
|------|------|
| `$OPENCODE_ROOT/ai-security-analysis/knowledge-base/model-security-analysis-guide.md`（line 116） | `--agent ai-security-analysis` → `--agent build` |
| `$OPENCODE_ROOT/ai-security-analysis/knowledge-base/carrier-construction-guide.md`（line 73） | 同上 |
| `docs/项目介绍/ai-dialogue.md` | 同步推荐值 + 加 scan 子命令说明 |
| `$SHARED_DIR/scripts/registry.json`（line 99） | ai-dialogue 条目 example_call 改 build + 加 scan 条目 |
| `$SHARED_DIR/scripts/ai-dialogue.py`（line 13 注释） | 注释里 `--agent ai-security-analysis` 示例改 build |

---

## §3 实现规范

### 3.1 实施步骤拆分

**步骤 1. system.transform 通用注入层**
- 文件: `$OPENCODE_ROOT/plugins/security-analysis.ts`
- 改动: line 480 后插入通用注入（push 临时文件放置节 + 绝对路径）；顶部 import os（若缺）
- 预估行数: +10
- 验证点: `node --check security-analysis.ts` 通过；启动 opencode 后，build 会话（非安全 agent）的 system 里出现"临时文件放置"节（含本机 os.tmpdir()/opencode 绝对路径）
- 依赖: 无

**步骤 2. AGENTS.md 第10条删除**
- 文件: `AGENTS.md`（项目根）
- 改动: 删除 line 81 起的"## 10. 禁止的目录"整节
- 预估行数: -8
- 验证点: grep "禁止的目录" AGENTS.md 无结果；grep "任务目录" AGENTS.md 无结果（任务目录规则收口到 execution-discipline.md）
- 依赖: 步骤 1（通用注入已覆盖临时文件放置）

**步骤 3. 靶子降级 build（agent prompt + 文档）**
- 文件: `$OPENCODE_ROOT/agents/ai-security-analysis.md`（line 174/180/186）、`$AGENT_DIR/knowledge-base/carrier-construction-guide.md`（line 73）、`$AGENT_DIR/knowledge-base/model-security-analysis-guide.md`（line 116）、`docs/项目介绍/ai-dialogue.md`、`$SHARED_DIR/scripts/registry.json`（line 99）、`$SHARED_DIR/scripts/ai-dialogue.py`（line 13 注释）
- 改动: `--agent ai-security-analysis` → `--agent build`（推荐值，6 处）
- 预估行数: ~6 处替换
- 验证点: `grep -rn "agent ai-security-analysis" .opencode/` 无残留（需求文档历史引用除外）；ai-dialogue.py `--help` 显示 --agent 仍为必传
- 依赖: 无

**步骤 4. ai-dialogue scan 批处理子命令**
- 文件: `$SHARED_DIR/scripts/ai-dialogue.py`
- 改动: 新增 scan 子命令（解析策略文件 → create → 按 stages send → 聚合 → delete → 输出 JSON）；新增 `--strategy`/`--output` 参数
- 预估行数: +80（新增 scan_run 函数 + build_parser 子命令 + _dispatch 分支）
- 验证点: `python -c "compile(...)"` 通过；`ai-dialogue.py scan --help` 显示参数；用最小策略文件实测 create→send→delete→聚合 JSON 输出正确
- 依赖: 无

**步骤 5. agent 自主编排重构（B）**
- 文件: `$OPENCODE_ROOT/agents/ai-security-analysis.md`（line 208-218 工作流段）
- 改动: 重构多轮攻防工作流，引入 scan（广度）+ send（深度）的自主编排指引；强调基于知识库自主规划
- 预估行数: ~30（改写工作流段）
- 验证点: 人工读取确认工作流描述 scan/send 分工；无残留的硬编码 create→send→delete 逐步流程；展开后行数 < 450
- 依赖: 步骤 4（scan 命令就位）

**步骤 6. registry.json + 文档最终同步**
- 文件: `$SHARED_DIR/scripts/registry.json`、`docs/项目介绍/ai-dialogue.md`
- 改动: registry.json 加 scan 条目；ai-dialogue.md 加 scan 章节
- 预估行数: +20
- 验证点: registry.json JSON 合法；ai-dialogue.md 含 scan 命令说明且自包含
- 依赖: 步骤 4

### 3.2 编码规则

- ai-dialogue.py scan 子命令复用现有 session_create/send_message/session_delete 函数，不重复 HTTP 逻辑
- scan 用 try/finally 确保 session_delete（参照 chat 子命令 ai-dialogue.py:261-262 模式），避免中途失败遗留会话
- security-analysis.ts 通用注入用模板字符串拼接，不引入新依赖（tmpdir/join 均复用或标准库）
- 所有路径引用用 `$OPENCODE_ROOT`/`$SHARED_DIR`/`$AGENT_DIR` 变量，不硬编码绝对路径

---

## §4 验收标准

### 4.1 功能验收

- [ ] build 会话（非安全 agent）的 system prompt 包含"临时文件放置"节，路径为本机 `os.tmpdir()/opencode` 绝对值
- [ ] ai-security-analysis 会话仍收到完整环境信息（PYTHON_CMD/TASK_DIR 等），未被通用层影响
- [ ] ai-dialogue.py `--agent` 仍为必传；scan 子命令可用且输出聚合 JSON
- [ ] AGENTS.md 第10条已删除，grep 无残留
- [ ] ai-security-analysis.md 推荐 `--agent build`，无 `ai-security-analysis` 残留

### 4.2 回归验收

- [ ] SECURITY_AGENTS 的占位符展开（{{buwai-rule:}}）正常工作（通用层不影响专属层）
- [ ] ai-dialogue create/send/chat/list/messages/delete/summarize 子命令行为不变
- [ ] execution-discipline.md 的"文件放置规则"（$TASK_DIR）仍注入 SECURITY_AGENTS

### 4.3 架构验收

- [ ] system.transform 分层清晰：通用层（所有会话）在前，专属层（requireSecurityAgent）在后，临时文件放置只在通用层写一次
- [ ] 无循环依赖、无依赖方向违规
- [ ] 改动文件均在架构正确位置（Plugin→plugins/、脚本→$SHARED_DIR/scripts/、知识库→$AGENT_DIR/knowledge-base/）

---

## §5 与现有需求文档的关系

- **依赖** `2026-07-03-llm-dialogue-script-upgrade.md`（LLM 探测脚本升级）：本次是该需求创建 ai-dialogue.py 后的首次定位调整。该需求把 `--agent` 从写死 opencode 改为必传参数；本次把推荐值从 ai-security-analysis 改为 build，并新增 scan 子命令
- **关联** `2026-05-30-ai-security-analysis-agent.md`（AI 安全 Agent 创建）：该需求确立 ai-security-analysis 的知识库体系；本次不改变知识库，只调整靶子 agent 选择和工作流
- **关联** `2026-05-03-agent-prompt-snippets.md`（Agent Prompt 片段）：execution-discipline.md 的"文件放置规则"由该需求沉淀；本次确认其归属正确（SECURITY_AGENTS 专属），AGENTS.md 第10条删除后不重复
