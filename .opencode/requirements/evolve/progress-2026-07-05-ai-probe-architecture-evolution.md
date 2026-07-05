# 进度：AI 探测架构演进

> 需求文档: 2026-07-05-ai-probe-architecture-evolution.md

## 步骤 1: system.transform 通用注入层 ✅
- 文件: `$OPENCODE_ROOT/plugins/security-analysis.ts`
- 改动: line 3 加 `import { tmpdir } from "os"`；line 482-490 插入通用注入层（requireSecurityAgent 之前 push 临时文件放置节）
- 验证: `bun build` 退出码 0；代码逻辑审查（通用注入在过滤前，所有会话含靶子 build 执行 push）
- 待集成验证: 重启 opencode 后确认 build 会话 system 含"临时文件放置"节

## 步骤 2: AGENTS.md 第10条删除 ✅
- 文件: `AGENTS.md`（项目根）
- 改动: 删除"## 10. 禁止的目录"整节（85→78 行）
- 验证: grep "禁止的目录"/"任务目录" 均无残留

## 步骤 3: 靶子降级 build ✅
- 文件: ai-security-analysis.md（3 处）、carrier-construction-guide.md、model-security-analysis-guide.md、registry.json、ai-dialogue.py 注释、ai-dialogue.py create/chat help（2 处）
- 改动: `--agent ai-security-analysis` → `--agent build`；help 示例改 build；语义改"靶子必须传"
- 验证: `grep "agent ai-security-analysis" .opencode/` 残留 0；ai-dialogue.py `--agent` 仍 required=True

## 步骤 4: ai-dialogue scan 批处理子命令 ✅
- 文件: `$SHARED_DIR/scripts/ai-dialogue.py`
- 改动: 新增 scan_run 函数 + scan 子命令（--strategy/--output）+ _dispatch 分支
- 验证: compile 通过；`scan --help` 显示参数；端到端实测（deepseek-v4-flash build 会话 create→send→delete→聚合 JSON 正确）

## 步骤 5: agent 自主编排重构 ✅
- 文件: `$OPENCODE_ROOT/agents/ai-security-analysis.md`（工作流段）
- 改动: "多轮攻防工作流"→"自主编排策略"，引入 scan（广度）+ send（深度）分工
- 验证: 工作流段重构为 scan/send 分工；展开后行数 432 < 450

## 步骤 6: registry.json + 文档同步 ✅
- 文件: registry.json（params 加 scan）、docs/项目介绍/ai-dialogue.md（表格调整+工作流重构+scan 章节）
- 验证: registry.json JSON 合法 + params 含 scan；ai-dialogue.md 含 scan 章节；无 `--agent ai-security-analysis` 残留
