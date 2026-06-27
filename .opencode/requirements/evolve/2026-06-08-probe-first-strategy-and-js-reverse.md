# 进化需求：试探优先策略 + JS 逆向混淆知识库

> 来源: JS Safe 6.0 CTF 解题复盘（writeup 第八章）
> 日期: 2026-06-08
> 状态: 待实施

---

## §1 背景与目标

### 背景

JS Safe 6.0 解题过程中，AI 花了一周、300+ 个脚本版本才解出来，而人类改了 3 处 HTML、几分钟就解出来了。根因分析发现核心差距在于**分析策略**而非工具能力：

1. AI 先完整分析所有机制再动手，人类先试探再聚焦分析
2. AI 试图在替代环境（Python）推演目标环境（Chrome）的行为，人类直接在目标环境试探
3. AI 视野发散试图理解所有机制，人类只关注眼前遇到的问题

### 目标

1. **新增试探优先策略**（方案 A）：创建共享 agents-rules 片段，注入到所有 4 个分析 agent
2. **强化规划聚焦约束**（方案 B）：修改现有 analysis-planning-rules，增加"不发散"约束
3. **新增 JS 混淆模式识别知识库**（方案 C）：web-analysis 知识库，覆盖不可见 Unicode、tagged template、原型链劫持等模式
4. **新增浏览器调试知识库**（方案 D）：web-analysis 知识库，覆盖 CDP/Playwright/DevTools API
5. **补充 CSP 脚本哈希防篡改**：在已有 csp-bypass.md 中补充 sha256 脚本哈希校验绕过

### 预期收益

| 维度 | 预期改进 |
|------|---------|
| 上下文 | 减少初始信息收集阶段的发散阅读，预计减少 30-50% 无效上下文占用 |
| 轮次 | 先试探再聚焦，预计减少 40-60% 规划轮次 |
| 速度 | 直接在目标环境试探，避免在错误环境推演 |
| 准确度 | 基于实际反馈决策而非推理，减少推理错误 |

---

## §2 技术方案

### 改动文件清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `agents-rules/probe-first-strategy.md` | **新增** | 试探优先策略共享片段（~45 行） |
| 2 | `agents-rules/analysis-planning-rules.md` | **修改** | 增加聚焦约束（+10 行） |
| 3 | `agents/binary-analysis.md` | **修改** | 插入 `{{buwai-rule:probe-first-strategy}}`（+2 行） |
| 4 | `agents/web-analysis.md` | **修改** | 插入 `{{buwai-rule:probe-first-strategy}}`（+2 行） |
| 5 | `agents/mobile-analysis.md` | **修改** | 插入 `{{buwai-rule:probe-first-strategy}}`（+2 行） |
| 6 | `agents/ai-security-analysis.md` | **修改** | 插入 `{{buwai-rule:probe-first-strategy}}`（+2 行） |
| 7 | `web-analysis/knowledge-base/js-obfuscation-patterns.md` | **新增** | JS 混淆模式识别知识库（~100 行） |
| 8 | `web-analysis/knowledge-base/browser-debugging.md` | **新增** | 浏览器调试技巧知识库（~80 行） |
| 9 | `web-analysis/knowledge-base/csp-bypass.md` | **修改** | 补充 CSP 脚本哈希防篡改（+30 行） |
| 10 | `agents/web-analysis.md` | **修改** | 知识库索引表增加 2 行 |

### 架构影响

- **共享片段注入**：probe-first-strategy.md 放入 agents-rules/ 目录，通过 `{{buwai-rule:probe-first-strategy}}` 注入到所有 agent。这与现有的 running-environment、execution-discipline 等片段使用相同的注入机制
- **知识库按需加载**：js-obfuscation-patterns.md 和 browser-debugging.md 放入 web-analysis/knowledge-base/，通过 web-analysis.md 的索引表按需加载，不影响其他 agent 的上下文
- **无循环依赖**：web-analysis 的知识库不引用其他 agent 的内容；共享片段 agents-rules/ 不引用任何 agent 专属内容

### 数据格式

无新增 JSON 格式或接口变更。

---

## §3 实现规范

### 改动范围表

| 类型 | 文件数 | 新增行数 | 修改行数 |
|------|--------|---------|---------|
| 新增 agents-rules 片段 | 1 | ~45 | 0 |
| 新增 web 知识库 | 2 | ~180 | 0 |
| 修改 agents-rules 片段 | 1 | ~10 | 0 |
| 修改 agent prompt | 5 | ~10 | 0 |
| 修改 web 知识库 | 1 | ~30 | 0 |
| **合计** | **10** | **~275** | **0** |

### 编码规则

1. agents-rules 片段必须自包含（不依赖主 prompt 上下文）
2. 知识库文件必须通过 knowledge-writing-guide.md 的质量检查清单
3. 所有路径引用使用 `$AGENT_DIR` / `$SHARED_DIR` 变量
4. agent prompt 插入位置：在 `{{buwai-rule:execution-discipline}}` 之前、`{{buwai-rule:analysis-planning-rules}}` 之后

### §3.1 实施步骤拆分

#### 步骤 1. 创建 agents-rules/probe-first-strategy.md

- **文件**: `.opencode/agents-rules/probe-first-strategy.md`
- **预估行数**: ~45 行
- **内容要点**:
  - 试探→反馈→聚焦→解决 四步循环
  - 视野聚焦：只看眼前的问题
  - 在正确环境里试探
  - 根据反馈做决策
  - 反模式警告
- **验证点**: 文件存在且内容自包含（读一遍确认不依赖主 prompt 上下文即可理解）

#### 步骤 2. 修改 agents-rules/analysis-planning-rules.md — 增加聚焦约束

- **文件**: `.opencode/agents-rules/analysis-planning-rules.md`
- **预估行数**: 新增 ~10 行
- **内容要点**:
  - 增加规则 6: 聚焦约束 — 只规划解决当前问题的方案，不规划"理解所有机制"
  - 增加规则 7: 反模式 — ❌ "先完整分析所有机制再动手" → ✅ "先解决眼前问题"
- **验证点**: 文件内容完整，与现有 5 条规则风格一致

#### 步骤 3. 修改 binary-analysis.md — 注入试探优先策略

- **文件**: `.opencode/agents/binary-analysis.md`
- **预估行数**: 新增 2 行（标题 + 引用标签）
- **改动**: 在 `### 阶段 B：分析规划（强制）` 的 `{{buwai-rule:analysis-planning-rules}}` 之后、`### 阶段 C：执行与监控` 之前插入新小节
- **验证点**: `{{buwai-rule:probe-first-strategy}}` 标签存在且位置正确

#### 步骤 4. 修改 web-analysis.md — 注入试探优先策略 + 更新知识库索引

- **文件**: `.opencode/agents/web-analysis.md`
- **预估行数**: 新增 ~6 行
- **改动**:
  - 在 `### 阶段 B` 的 `{{buwai-rule:analysis-planning-rules}}` 之后插入试探优先策略引用（2 行）
  - 在知识库索引表（`### Web 安全知识库` 段）增加 `js-obfuscation-patterns.md` 和 `browser-debugging.md` 两个条目（4 行）
- **验证点**: 引用标签和索引条目都存在且格式与现有条目一致

#### 步骤 5. 修改 mobile-analysis.md — 注入试探优先策略

- **文件**: `.opencode/agents/mobile-analysis.md`
- **预估行数**: 新增 2 行
- **改动**: 在 `### 阶段 B` 的 `{{buwai-rule:analysis-planning-rules}}` 之后插入
- **验证点**: 标签存在且位置正确

#### 步骤 6. 修改 ai-security-analysis.md — 注入试探优先策略

- **文件**: `.opencode/agents/ai-security-analysis.md`
- **预估行数**: 新增 2 行
- **改动**: 在 `### 阶段 B` 的 `{{buwai-rule:analysis-planning-rules}}` 之后插入
- **验证点**: 标签存在且位置正确

#### 步骤 7. 创建 web-analysis/knowledge-base/js-obfuscation-patterns.md

- **文件**: `.opencode/web-analysis/knowledge-base/js-obfuscation-patterns.md`
- **预估行数**: ~100 行
- **内容要点**:
  - §1 不可见 Unicode 字符混淆（U+FFA0 变量名 + U+2000-U+200A 空格）
  - §2 tagged template 隐式函数调用
  - §3 Function.call tagged template 创建空函数
  - §4 原型链 Proxy/getter 劫持
  - §5 debug condition 副作用执行
  - §6 快速检测清单
- **验证点**: 文件自包含 + 每条知识有"场景→检查→利用"三要素 + 通过 knowledge-writing-guide.md 质量检查

#### 步骤 8. 创建 web-analysis/knowledge-base/browser-debugging.md

- **文件**: `.opencode/web-analysis/knowledge-base/browser-debugging.md`
- **预估行数**: ~80 行
- **内容要点**:
  - §1 Chrome DevTools Protocol (CDP) 核心 API
  - §2 Playwright + CDP 自动化模式
  - §3 debug() API 和 debug condition
  - §4 常见陷阱
- **验证点**: 文件自包含 + 代码示例可执行 + 通过质量检查

#### 步骤 9. 修改 web-analysis/knowledge-base/csp-bypass.md — 补充脚本哈希防篡改

- **文件**: `.opencode/web-analysis/knowledge-base/csp-bypass.md`
- **预估行数**: 新增 ~30 行
- **改动**: 在 §2.3 末尾（"hash 对应的脚本是否可控"那行之后）新增 §2.3.5 小节：CSP 脚本哈希防篡改与绕过
- **内容要点**:
  - `script-src 'sha256-xxx'` 的原理：哈希值 = 脚本内容 SHA256
  - 修改脚本内容（哪怕一个字符）→ 哈希变化 → 浏览器拒绝执行
  - 绕过方法 1: 去掉 CSP 的 content 属性（`<meta>` 标签场景）
  - 绕过方法 2: 修改 CSP 头（HTTP 响应头场景，需中间人/服务端控制）
  - 绕过方法 3: 利用 CSP 配置缺陷（如同时有 'unsafe-eval'）
- **验证点**: 补充内容与现有 §2.3 风格一致，通过质量检查

---

## §4 验收标准

### 功能验收

- [ ] `agents-rules/probe-first-strategy.md` 存在且内容自包含
- [ ] `analysis-planning-rules.md` 包含聚焦约束（规则 6、7）
- [ ] 4 个 agent prompt 都包含 `{{buwai-rule:probe-first-strategy}}` 且位置正确
- [ ] `js-obfuscation-patterns.md` 存在且覆盖 6 类混淆模式
- [ ] `browser-debugging.md` 存在且覆盖 CDP/Playwright/debug API
- [ ] `csp-bypass.md` 包含脚本哈希防篡改内容
- [ ] `web-analysis.md` 知识库索引表包含 2 个新增条目

### 回归验收

- [ ] 所有 agent prompt 的 `{{buwai-rule:xxx}}` 标签格式正确
- [ ] 所有知识库文件通过 knowledge-writing-guide.md 质量检查
- [ ] 无循环依赖、无散落文件

### 架构验收

- [ ] agents-rules/ 不引用任何 agent 专属内容
- [ ] web-analysis/knowledge-base/ 不引用其他 agent 的内容
- [ ] 所有路径引用使用变量（`$AGENT_DIR` / `$SHARED_DIR`）

---

## §5 与现有需求文档的关系

- 独立需求，不依赖未完成的现有需求文档
- 与 `2026-05-03-agent-prompt-snippets.md`（agents-rules 机制建立）是一脉相承的关系：本次在该机制上新增 1 个片段
- 与 `2026-05-05-web-analysis-agent.md`（web-analysis agent 建立）是补充关系：本次新增知识库内容
