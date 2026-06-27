# Agent Prompt 片段系统 — 实施进度

## 步骤 1: 创建 agents-rules 目录 + 8 个片段文件 ✅
- 目录: `.opencode/agents-rules/`
- 8 个文件 (56 行): running-environment, variable-initialization, task-initialization, analysis-planning-rules, execution-discipline, loop-control, output-format, task-archive
- 验证: 文件名全小写连字符，内容与需求文档附录一致

## 步骤 2: Plugin 添加占位符展开逻辑 ✅
- 文件: `.opencode/plugins/security-analysis.ts` (649→720 行, +71 行)
- 新增: AGENTS_RULES_DIR, parseFrontmatter(), hasBuwaiExtensionId(), loadSnippet()
- 新增: system.transform hook 中占位符展开（每次调用，在 shouldInject 之前）
- 验证: node --check 通过，agentName 只声明一次

## 步骤 3: 修改 binary-analysis.md ✅
- 359→315 行 (净减 44 行)
- Frontmatter 新增 buwai-extension-id: binary-analysis
- 8 处替换为占位符
- Agent 专属内容保留: 常见失败模式表、数据库锁行、输出格式专属补充、安全规则、IDAPython 规范

## 步骤 4: 修改 mobile-analysis.md ✅
- 267→224 行 (净减 43 行)
- Frontmatter 新增 buwai-extension-id: mobile-analysis
- 8 处替换为占位符
- --agent mobile-analysis 参数以独立说明行保留 (L50)
- Agent 专属内容保留: 设备管理、frida Bridge 规则、移动端工具表、知识库索引

## 步骤 5: 端到端验证 ✅ (静态验证)
- Plugin 语法检查通过
- 8/8 占位符对应片段文件存在
- 展开后结构与原内容功能等价
