# 进度: 环境检测重构 + 任务目录创建搬 TS

需求文档: `2026-07-05-env-check-refactor.md`

## 步骤完成记录

### 步骤 1. PYTHON_PACKAGES 标记 agents + 全部 preinstall=True — ✅ 完成

### 步骤 2. _check_preinstall 扩展 — ✅ 完成
- 新增 _build_install_hint 辅助函数（从内联代码提取）
- _check_preinstall 扩展：find_spec + importlib.metadata.version 收集版本；_detect_compiler/_detect_ida_pro/_resolve_tool 全量检测；_save_cache 写 env_cache；支持 agent=="all"
- 关键设计：data 全量写 cache（所有包，供 Plugin 读完整环境信息）；errors 按 agent 过滤（只报当前 agent 缺的包）
- 验证: binary-analysis data 含 15 个包（全量）；errors 只报 triton+ida_pro（binary 相关）；web 包不在 errors 里（agents 过滤）；all 模式工作；env_cache 含 compiler/packages/ida_pro/tools

### 步骤 3. main() 默认/--force 改走 _check_preinstall + 删 --agent — ✅ 完成
- 删除 --agent 和 --skip-install 参数（无消费者）
- main 默认/--force 改走 _check_preinstall("all")（替代 run_detection）
- 验证: --force 输出完整 JSON（15 包）；--agent/--skip-install 报 unrecognized；默认模式缓存命中
- run_detection 保留但不被 main 调用

### 步骤 4. task-session.ts 新增 createTaskDir — ✅ 完成
- 新增 createTaskDir(sessionID): string（幂等检查 via getTaskDirRaw + 目录创建 + 映射注册 + persistence.json + clearTaskDirCache）
- 验证: node --check 通过

### 步骤 5. security-analysis.ts 改造 — ✅ 完成
- ensureTaskDir: spawn create_task_dir.py → 调 createTaskDir(sessionID)，签名去掉 pythonCmd
- runDetectEnv: --agent → --check-preinstall + Coordinator all + timeout 8000 + stderrTail 拼入错误消息
- checkEnvironment: ensureTaskDir 调用去 pythonCmd 参数
- 验证: node --check 通过 + 无 --agent 残留

### 步骤 6. 删除 create_task_dir.py + 更新引用 — ✅ 完成
- 删除 create_task_dir.py
- registry.json 删条目（JSON 有效）
- update_max_duration.py docstring 更新
- opencode-plugin-hooks-lifecycle.md 知识库引用更新为 createTaskDir
- task-session.ts L48 注释保留（描述正确：createTaskDir 替代 create_task_dir.py）

### 步骤 7. 端到端验证 — ✅ 完成
- V1: --check-preinstall + --output 模拟 Plugin runDetectEnv ✅（修复 bug: --check-preinstall 早退未处理 --output → env.json 不写入）
- V2: update_max_duration.py 兼容 createTaskDir 写的 .persistence.json ✅
- V3: --check-preinstall all（Coordinator 模式）✅
- 耗时 1.0s < 8s ✅
- env.json 15 包全量 data ✅
- 修复的 bug: --check-preinstall 早退分支加 --output 处理（写 env.json + _log）

## Phase 5 总结

全部 7 个步骤完成。核心改动:
1. detect_env.py: PYTHON_PACKAGES 标记 agents + 全部 preinstall=True；_check_preinstall 扩展（版本收集+编译器/IDA/工具检测+写 cache+支持 all）；main() 改走 _check_preinstall + 删 --agent/--skip-install；--check-preinstall 加 --output 处理
2. task-session.ts: 新增 createTaskDir（TS 实现，替代 create_task_dir.py）
3. security-analysis.ts: ensureTaskDir 改调 createTaskDir；runDetectEnv 改调 --check-preinstall + Coordinator all + timeout 8s + stderr 拼入错误
4. 删除 create_task_dir.py + 更新 registry.json/update_max_duration.py/opencode-plugin-hooks-lifecycle.md
