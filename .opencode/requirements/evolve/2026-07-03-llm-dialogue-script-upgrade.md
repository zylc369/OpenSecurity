# 需求：LLM 探测脚本升级

> 来源：docs/进化/进化-LLM探测脚本升级.md
> 状态：待实施

---

## §1 背景与目标

### 1.1 来源

用户提出：`.opencode/ai-security-analysis/scripts/` 下的 `deepseek_client.py` 和 `llm_sim.py` 已不合时宜——直连 LLM API 会导致 AI 功能缺失（无 agent 上下文、无工具链）。基于本次会话验证的 `tools/ai-security-analysis-dialogue` 创建新的通用脚本 `ai-dialogue.py`。

### 1.2 目标

1. 删除 `.opencode/ai-security-analysis/scripts/` 下全部代码
2. 基于 dialogue 工具创建 `ai-dialogue.py`，放到 `.opencode/binary-analysis/scripts/`
3. 新增 `--agent` 必传参数，支持指定目标模型运行的 agent 上下文
4. 更新所有引用（agent prompt 8 处 + 知识库 4 个文件）
5. 脚本文档放到 `docs/项目介绍/`，从项目 README 引用

### 1.3 根因

当前 dialogue 工具第 56 行写死 `"agent": "opencode"`（build agent），导致目标模型 session 用 build agent 上下文运行——无任务目录概念、无文件放置规则。`--agent` 参数解决这个根因。

---

## §2 技术方案

### 2.1 新脚本 ai-dialogue.py

基于 `tools/ai-security-analysis-dialogue/main.py`（262行），改动：

| 项 | 现状 | 新版 |
|---|---|---|
| 文件名 | `tools/ai-security-analysis-dialogue/main.py` | `$SHARED_DIR/scripts/ai-dialogue.py` |
| 描述 | "AI 安全分析对话工具" | "通用 AI 对话工具 — 通过 opencode serve 与目标模型对话" |
| agent | 写死 `"opencode"` | `--agent` 参数，create 和 chat 子命令必传 |
| provider 默认 | `opencode-go` | 保持不变 |
| 子命令 | create/send/chat/list/messages/delete/summarize | 不变 |
| HTTP/API 逻辑 | 不变 | 不变 |

opencode serve API 确认支持：`POST /api/session` payload 含 `agent: Agent.ID`（可选字段）。

### 2.2 删除旧代码

| 要删除的 | 路径 | 说明 |
|---------|------|------|
| deepseek_client.py | `.opencode/ai-security-analysis/scripts/` | 直连 API 客户端，不再使用 |
| llm_sim.py | 同上 | LLM 应用模拟器，依赖 deepseek_client，不再使用 |
| registry.json | 同上 | 脚本注册表，随目录删除 |
| \_\_pycache\_\_/ | 同上 | 缓存 |
| main.py | `tools/ai-security-analysis-dialogue/` | 被 ai-dialogue.py 替代 |
| README.md | 同上 | 内容迁移到 docs/项目介绍/ |

### 2.3 更新引用

**agent prompt**（`.opencode/agents/ai-security-analysis.md`）：

| 行号 | 现状 | 改为 |
|------|------|------|
| 133 | `用 $AGENT_DIR/scripts/llm_sim.py 本地模拟` | 删除此行（无替代方案，不再本地模拟） |
| 170 | llm_sim.py 工具行 | 删除 |
| 171 | deepseek_client.py 工具行 | 删除 |
| 172 | dialogue 工具行 | 路径改为 `$SHARED_DIR/scripts/ai-dialogue.py`，加 `--agent` |
| 176 标题 | "目标模型对话工具 (ai-security-analysis-dialogue)" | "目标模型对话工具 (ai-dialogue)" |
| 184-185 | llm_sim/deepseek_client 选择指引 | 删除这两行 |
| 192-210 | 7 处 dialogue 命令 | 路径改为 `$SHARED_DIR/scripts/ai-dialogue.py`，create 和 chat 加 `--agent ai-security-analysis` |
| 233-261 | "AI 分析辅助库"整节 | 删除（deepseek_client + llm_sim 使用方式） |

**知识库**：

| 文件 | 行号 | 改动 |
|------|------|------|
| `model-security-analysis-guide.md` | 245 | CLI 路径改为 `$SHARED_DIR/scripts/ai-dialogue.py` + 加 `--agent` 说明 |
| `llm-attack-methodology.md` | 163-187 | §5"测试工具"整节：llm_sim 代码示例改为 ai-dialogue CLI 调用 |
| `carrier-construction-guide.md` | 70-76 | llm_sim import 代码块改为 ai-dialogue chat 调用 |
| `payload-effectiveness-evaluation.md` | 41-57 | ResponseParser 代码块改为从 ai-dialogue JSON 输出中解析 |

### 2.4 文档

创建 `docs/项目介绍/ai-dialogue.md`（基于 `tools/ai-security-analysis-dialogue/README.md`，更新脚本名、路径、--agent 参数），从项目 `README.md` 引用。

---

## §3 实现规范

### 3.0 改动范围表

| 操作 | 文件 | 预估行数 |
|------|------|---------|
| 新建 | `$SHARED_DIR/scripts/ai-dialogue.py` | ~270 行 |
| 新建 | `docs/项目介绍/ai-dialogue.md` | ~100 行 |
| 修改 | `$SHARED_DIR/scripts/registry.json` | +12 行 |
| 修改 | `.opencode/agents/ai-security-analysis.md` | -50 行 / +5 行 |
| 修改 | `model-security-analysis-guide.md` | ~5 行改 |
| 修改 | `llm-attack-methodology.md` | ~25 行改 |
| 修改 | `carrier-construction-guide.md` | ~10 行改 |
| 修改 | `payload-effectiveness-evaluation.md` | ~15 行改 |
| 修改 | `README.md` | +1 行 |
| 删除 | `.opencode/ai-security-analysis/scripts/` 整个目录 | - |
| 删除 | `tools/ai-security-analysis-dialogue/` 整个目录 | - |

### 3.1 实施步骤拆分

#### 步骤 1. 创建 ai-dialogue.py

- **文件**: `$SHARED_DIR/scripts/ai-dialogue.py`
- **预估行数**: ~270 行（含注释/空行），实际代码 ~150 行
- **改动**: 基于 `tools/ai-security-analysis-dialogue/main.py`，(1) 描述改为通用 (2) `session_create` 函数增加 agent 参数传入 (3) `build_parser` 的 create 和 chat 子命令加 `--agent` 必传参数 (4) `_dispatch` 传递 agent 参数
- **验证点**: `python -c "compile(open('<文件>').read(), '<文件>', 'exec')"` 通过 + `python ai-dialogue.py --help` 输出参数说明 + `python ai-dialogue.py create --help` 显示 `--agent` 为必传

#### 步骤 2. 注册到 registry.json

- **文件**: `$SHARED_DIR/scripts/registry.json`
- **预估行数**: +12 行
- **改动**: 追加 ai-dialogue 条目
- **验证点**: `python -c "import json; json.load(open('<文件>'))"` 通过

#### 步骤 3. 更新 agent prompt

- **文件**: `.opencode/agents/ai-security-analysis.md`
- **预估行数**: -50 行 / +5 行
- **改动**: (1) 删除 llm_sim/deepseek_client 工具行和选择指引 (2) 删除"AI 分析辅助库"整节 (3) 更新 dialogue 命令路径和加 --agent (4) 更新失败模式表中 llm_sim 引用
- **验证点**: 人工读取确认无残留的旧路径引用 + `--agent ai-security-analysis` 出现在 create/chat 命令中

#### 步骤 4. 更新 model-security-analysis-guide.md

- **文件**: `model-security-analysis-guide.md`
- **预估行数**: ~5 行改
- **改动**: §6.1 CLI 速查路径 + 加 --agent 说明
- **验证点**: 路径引用 `$SHARED_DIR/scripts/ai-dialogue.py`

#### 步骤 5. 更新 llm-attack-methodology.md

- **文件**: `llm-attack-methodology.md`
- **预估行数**: ~25 行改
- **改动**: §5"测试工具"整节，llm_sim Python 代码示例改为 ai-dialogue CLI 调用示例
- **验证点**: 无 llm_sim 引用 + ai-dialogue 调用包含 --agent 参数

#### 步骤 6. 更新 carrier-construction-guide.md

- **文件**: `carrier-construction-guide.md`
- **预估行数**: ~10 行改
- **改动**: 第 70-76 行 llm_sim import 代码块改为 ai-dialogue chat 调用
- **验证点**: 无 llm_sim 引用

#### 步骤 7. 更新 payload-effectiveness-evaluation.md

- **文件**: `payload-effectiveness-evaluation.md`
- **预估行数**: ~15 行改
- **改动**: 第 41-57 行 ResponseParser 代码块改为从 ai-dialogue JSON 输出中用 Python 解析
- **验证点**: 无 llm_sim/ResponseParser 引用

#### 步骤 8. 创建文档 + 更新 README

- **文件**: `docs/项目介绍/ai-dialogue.md`（新建）+ `README.md`（+1 行引用）
- **预估行数**: ~100 行新建 + 1 行改
- **改动**: 基于 README.md 迁移内容，更新脚本名、路径、--agent 参数
- **验证点**: 人工读取确认文档自包含 + README 有引用链接

#### 步骤 9. 删除旧代码

- **文件**: `.opencode/ai-security-analysis/scripts/` 整个目录 + `tools/ai-security-analysis-dialogue/` 整个目录
- **预估行数**: 0（纯删除）
- **改动**: `rm -rf` 两个目录
- **验证点**: 两个目录不存在 + `grep -r "ai-security-analysis-dialogue\|deepseek_client\|llm_sim" .opencode/` 无残留引用（需求文档中的历史引用除外）

---

## §4 验收标准

### 功能验收
- [ ] ai-dialogue.py `--help` 显示所有子命令
- [ ] ai-dialogue.py create `--help` 显示 `--agent` 为必传参数
- [ ] ai-dialogue.py 语法检查通过
- [ ] registry.json 包含 ai-dialogue 条目且 JSON 合法
- [ ] agent prompt 无残留旧路径引用
- [ ] 4 个知识库文件无残留 llm_sim/deepseek_client 引用
- [ ] docs/项目介绍/ai-dialogue.md 存在且自包含
- [ ] README.md 有文档引用链接

### 回归验收
- [ ] ai-dialogue.py 的 HTTP/API 逻辑与原 dialogue 工具一致（只改了 agent 来源）
- [ ] 子命令名称和参数与原工具一致（create/send/chat/list/messages/delete/summarize）
- [ ] JSON 输出格式不变

### 架构验收
- [ ] ai-dialogue.py 在 `$SHARED_DIR/scripts/`（通用目录）
- [ ] `.opencode/ai-security-analysis/scripts/` 目录已删除
- [ ] `tools/ai-security-analysis-dialogue/` 目录已删除
- [ ] 无文件引用已删除的路径

---

## §5 与现有需求文档的关系

- 与 `2026-05-30-ai-security-analysis-agent.md`（AI安全Agent创建）：本次替换该需求沉淀的 deepseek_client.py 和 llm_sim.py
- 与 `2026-05-30-opencode-runner-integration.md`（opencode runner 集成）：本次替换该需求引入的 dialogue 工具
- 与 `2026-07-02-model-security-knowledge-fixes.md`（模型安全知识修正）：本次更新该需求刚写入的 CLI 速查路径
