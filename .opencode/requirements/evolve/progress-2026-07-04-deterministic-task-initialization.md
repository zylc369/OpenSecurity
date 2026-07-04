# 进度: 任务初始化确定化

需求文档: `2026-07-04-deterministic-task-initialization.md`

## 步骤完成记录

### 步骤 1. create_task_dir.py 幂等化 — ✅ 完成
- 改动: `create()` 开头加 sessionID 映射检查，已存在则返回已有目录
- 验证: 语法 OK + 幂等性测试（同 SESSION_ID 跑两次输出相同）+ 映射文件正确
- 要点: 映射文件损坏（非法 JSON/路径失效）时降级新建，不阻塞

### 步骤 2. detect_env.py 合并 + stdout 纯净化 — ✅ 完成
- 改动:
  - 新增 `_log(msg)` 函数（打 stderr），所有进度日志收口
  - `run_detection` + `main` 的进度 print 全改为 `_log`（~20 处）
  - `--output` 模式的 `print(f"[+] 结果已写入...")` 改为 `_log`
  - stdout 只保留 `print(output_json)`（无 --output 时）
  - 新增 `--agent <AGENT>` 参数，默认模式在全量检测后合并 `_check_preinstall(agent)` 的 errors
- 验证:
  - 语法 OK
  - stdout 纯净（首字符 `{`，0 行进度日志）— `json.load(stdin)` 成功
  - --agent 合并 preinstall（errors 含 triton 安装失败 + IDA Pro 未检测到）
  - --check-preinstall 向后兼容 OK

### 步骤 3. update_max_duration.py 新建 — ✅ 完成
- 改动: 从 $TASK_DIR/.persistence.json 读取，更新 max_duration_hours；范围 (0,24] 超范围钳位 6；保留 resume_count/last_resume_at；TASK_DIR 缺失或文件不存在时报错退出
- 验证: 语法 OK + 正常更新(6→2.0) + 钳位(30→6) + 缺失 TASK_DIR exit(1) + 保留其他字段

### 步骤 4. security-analysis.ts: checkEnvironment 重构 — ✅ 完成
- 改动:
  - 新增 `ensureTaskDir(pythonCmd, sessionID)`: spawn create_task_dir.py + 传 SESSION_ID + 验证映射注册
  - 新增 `runDetectEnv(agent, pythonCmd, sessionID)`: spawn detect_env.py --agent + 解析 JSON + 格式化 errors（全量字符串 + preinstall 对象混合）
  - 重构 `checkEnvironment`: ensurePythonCmd → ensureTaskDir（仅根 session，判断 parentSessionID）→ runDetectEnv
  - 删除 `checkPreinstall` 函数（~50 行）
  - 更新 tool.execute.before 注释引用
- 验证: node --check 通过 + rg 无 checkPreinstall 代码引用（仅注释提及）
- chat.message 调用点签名不变（agent, sessionID → EnvironmentCheckResult），无需改动

### 步骤 5. 删除初始化文档 — ✅ 完成
- 删除 agents-rules/task-initialization.md + binary-analysis/knowledge-base/task-initialization.md
- 验证: 两文件不存在；无活跃代码引用残留（requirements/evolve 历史文档的引用属归档，不改）

### 步骤 6. agent prompt 清理 — ✅ 完成
- 5 个单 agent (binary/mobile/web/crypto/ai-security): 删除"## 阶段 0：任务初始化（强制）"整段，在"分析执行框架"blockquote 下补充任务初始化说明（$TASK_DIR 由 Plugin 自动完成 + update_max_duration 用法）
- Coordinator: "阶段 0" 改为精简的"任务初始化"段落（删 0.1 创建命令 + 0.2 变量表）；更新"执行纪律"表格的"阶段 0 强制"行为"任务目录"规则
- 验证: rg "buwai-rule:task-initialization|create_task_dir\.py|阶段 0：任务初始化" .opencode/agents/ 零匹配；binary-analysis 结构抽查干净

### 步骤 7. 端到端验证 — ✅ 完成
- 组合验证（模拟 Plugin checkEnvironment 调用链）:
  - Step A ensureTaskDir: task_dir 创建 + mapping 注册 ✅
  - Step B 幂等性: 同 SESSION_ID 重复跑返回相同目录 ✅
  - Step C runDetectEnv --output: stdout JSON 可解析 + env.json 写入磁盘 ✅
  - Step D update_max_duration: 6→3.0 更新成功 ✅
  - Step E 故障路径: errors 含 IDA Pro install_hint 指导信息 ✅
- 修复的 bug: detect_env.py --output 模式下 stdout 未输出 JSON（原改造把 print 放进 else 分支），修复为 stdout 始终输出 + --output 额外写文件
- 运行时验证（启动 opencode）需用户在本地环境做

## Phase 5 总结

全部 7 个步骤完成。核心改动:
1. create_task_dir.py 幂等化（防双重触发产生孤儿目录）
2. detect_env.py 合并 preinstall + stdout 纯净化（新增 --agent 参数）
3. update_max_duration.py 新增（方案 C: AI 识别用户意图后更新）
4. security-analysis.ts checkEnvironment 重构（ensureTaskDir 仅根 session + runDetectEnv 合并）
5-6. 删除 2 个初始化文档 + 清理 6 个 agent prompt
