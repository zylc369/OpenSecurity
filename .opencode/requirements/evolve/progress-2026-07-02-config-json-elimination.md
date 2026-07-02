# 实施进度: 消除 config.json（2026-07-02）

需求文档: `2026-07-02-config-json-elimination.md`

## 步骤进度

| 步骤 | 描述 | 状态 | 验证结果 |
|------|------|------|--------|
| 1 | detect_env: Dependency dataclass + .ai_env 基础设施 | ✅ | compile OK + .ai_env 模板生成 + gitignore |
| 2 | detect_env: REQUIRED_PACKAGES → PYTHON_PACKAGES | ✅ | compile + 零残留 + _check_preinstall crypto OK |
| 3 | detect_env: EXTERNAL_TOOLS + _resolve_tool + 删 config 读取 | ✅ | compile + ida_pro 双向 + mobile 工具检测 |
| 4 | detect_env: _check_preinstall 扩展 tool 类 | ✅ | compile + 各 agent check-preinstall（含 required=False 修复）|
| 5 | detect_env: env_cache 结构扩展 | ✅ | 随步骤 3 返回值自动带上，env_cache 含 idat_path/description/resolved_path |
| 6 | constants.ts: process.env.OPENCODE_ROOT | ✅ | node --check + bun build |
| 7 | security-analysis.ts: EnvData 扩展 | ✅ | node --check |
| 8 | security-analysis.ts: buildEnvSection 改读 env_cache + 删 getToolsForAgent | ✅ | node --check + getToolsForAgent 零残留 |
| 9 | 清全部 config 引用 + 删 ConfigData/ToolConfig/CONFIG_FILE | ✅ | node --check + CONFIG_FILE/ConfigData/ToolConfig 零残留 |
| 10 | 文档清理 11+ 文件 | ✅ | config.json 代码+文档零残留 |
| 11 | 端到端验证 | ✅（detect_env 全链路）| env_cache 全量 tools + ida_pro.idat_path + 各 agent check-preinstall success |

## 执行中发现并修复的问题

1. **required=False 的 preinstall 不应阻塞**（步骤 4）：GoReSym/otool/ldid/sage 缺失不应阻塞 agent。修复：_check_preinstall 跳过 required=False 的缺失。
2. **env_cache tools 按 agent 过滤导致不全**（步骤 11）：_detect_tools(agent) 收到 AGENT_NAME 导致过滤，env_cache 全局共享应全量。修复：_detect_tools() 去掉 agent 过滤，全量检测。
3. **_detect_tools 残留行**（步骤 11）：Edit 后 errors.append 残留导致 IndentationError。已删。
4. **注释/文档遗漏**：execution-discipline.md L22、security-analysis.ts L700 注释。已清。

## 待用户重启 opencode 验证（运行时）

步骤 11 第 4 点（Plugin 实际加载后 system.transform/shell.env 注入）需重启 opencode 确认：
- system.transform 注入环境信息段含 IDA Pro/tools
- shell.env 注入 $IDAT（从 env_cache 的 ida_pro.idat_path）
- process.env.OPENCODE_ROOT 传播到 detect_env 子进程
