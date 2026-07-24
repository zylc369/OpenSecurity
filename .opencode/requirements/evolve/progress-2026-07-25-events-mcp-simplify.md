# Progress: Events MCP 工具简化（8→6）

## 步骤完成状态

| Step | 文件 | 状态 | 改动要点 |
|------|------|------|---------|
| 1 | server.py | ✅ | temporal_window + recent_context → time_search（时间参数可选） |
| 2 | server.py | ✅ | successful_tools + entity_by_label → entity_search（min_mentions 可选） |
| 3 | memorist.md | ✅ | 决策表 7→5 行；查询工程更新 |
| 4 | 知识与记忆体系.md | ✅ | 工具列表 8→6；数据流图更新 |
| 5 | 5 个测试文件 | ✅ | 工具名 + 参数适配 |

## 验证结果

- server.py 语法 ✅
- 6 个 @mcp.tool ✅
- 全项目 grep 无旧工具名残留 ✅
- 5 个测试文件语法 ✅
