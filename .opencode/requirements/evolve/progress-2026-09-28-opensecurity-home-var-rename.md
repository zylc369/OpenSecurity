# 进度: 变量规范名升级 $OPENSECURITY_HOME（兼容别名 DATA_DIR）

> 需求: `2026-09-28-opensecurity-home-var-rename.md`
> 来源: 用户评审（命名/描述）→ 用户选定 OPENSECURITY_HOME

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | 插件读链与注入 | ☑ | 三态实测（both→新名 / old→旧名 / 无→默认）；bun build 零错误；注入键 5 处就位 |
| S2 | 读侧兼容（R1-R7） | ☑ | py_compile ×5；沙箱三态 ×2；test_control 87 passed（同既有 collection error） |
| S3 | 运行时文档改名（9 文件 16 处） | ☑ | 运行时文档 `$DATA_DIR` 零残留；`$OPENSECURITY_HOME` 命中 16；旧标签零 |
| S4 | 记录同步（命令文档 v4 + 注记） | ☑ | 命令草稿==文件 True（55 行）；v4/v2 注记与 add-new-agent 更新就位 |
| S5 | 端到端验证（新进程） | ☑ | 诊断：HOME_VAR 注入 + OLD_VAR 空 + 环境信息段逐字；命令回归完整报告（81KB） |
| S6 | 全仓复扫与收尾 | ☑ | `$DATA_DIR` 仅剩历史记录；代码类=兼容链/内部通道/测试夹具（按设计） |

## as-built 记录

- Phase 3 审计：2 轮修复（计数 13→16、验证点措辞、compat 常量设计）+ 纯审计（S3 计数陈旧 → 修复后复评）通过。
- 插件：`constants.ts` 读链（新名||旧名||默认）；env section 行替换（"OpenSecurity 主目录" + 归属/内容/用法三要素）；shell.env 注入 `OPENSECURITY_HOME`；启动/汇总日志与注释同步。
- 读侧兼容 7 文件：config_manager（规范名常量 + 别名常量 + 链式读取 + docstring）、detect_tools、detect_py_deps、control_url、clean_databases、vite.config、test_e2e_real。
- 文档：9 文件 16 处改名（含 crash-triage 重启命令 `OPENSECURITY_HOME="$OPENSECURITY_HOME"`）；旧记录 v4/v2 注记；add-new-agent 兼容名注记。
- 委派验证：`test_control.py` 87 passed（该套件通过旧名沙箱，验证兼容链）；`bun build` ×1；`py_compile` ×6。
- 残余分类（终态）：records 6 文件（历史/说明）；代码 compat 链 7 文件 + 内部通道 3（control-manager/mcp-manager/launchd）+ 测试夹具 + constants 注释——均按设计。
- 遗留观察：环境信息段引用 `$OPENSECURITY_HOME` 的会话提示为英文变量名 + 中文说明，符合既有风格；后续如需内网文档同步英文化另行处理。
- **后续（同日）**：兼容别名已按用户决策撤除、全量统一——见 `2026-09-28-opensecurity-home-full-rename.md`；本文件中"读侧兼容链/内部通道不动"等表述已被其取代。
