# 2026-09-28 全面统一：DATA_DIR → OPENSECURITY_HOME（撤除兼容别名）

> 状态：已实施（2 轮检查 + 终态扫描通过）| 入口：用户指令（"DATA_DIR 统一改成 OPENSECURITY_HOME"）
> 来源：`2026-09-28-opensecurity-home-var-rename.md` 的兼容设计修订（该文 §2.2/§2.4 被本文件取代；v2 注记已加）
> 实施进度与 as-built：`progress-2026-09-28-opensecurity-home-full-rename.md`

## §1 背景与目标

用户决策：不保留兼容别名，`DATA_DIR` 三形态全量更名为 `OPENSECURITY_HOME` 对应形态，覆盖插件、控制台、MCP、工具脚本、repo 级测试与进程间通道；读侧不再接受旧名（破坏性变更，用户明确要求）。

## §2 技术方案

### 2.1 三形态映射

| 旧名 | 新名 |
|------|------|
| `DATA_DIR`（含 `TEST_DATA_DIR`/`DEFAULT_DATA_DIR`/`DATA_DIR_ENV`） | `OPENSECURITY_HOME`（`TEST_OPENSECURITY_HOME`/`DEFAULT_OPENSECURITY_HOME`/`OPENSECURITY_HOME_ENV`） |
| `data_dir`（含 `self._data_dir`、`cm.data_dir`、docker 占位符） | `opensecurity_home` |
| `dataDir` | `opensecurityHome` |

### 2.2 关键改动点

- `plugins/lib/constants.ts`：导出改 `OPENSECURITY_HOME`；读取收敛为单名 `process.env.OPENSECURITY_HOME || 默认`；派生常量（`WORKSPACE_DIR`/`TOOLS_CMD_DIR`/`TOOLS_HOME_DIR`/`LOGS_DIR`/`CONTROL_UNIX_SOCKET` 等）随之。
- `config_manager.py`：`OPENSECURITY_HOME_ENV = "OPENSECURITY_HOME"` + `DEFAULT_OPENSECURITY_HOME`；兼容常量与兼容读取行删除。
- 进程间通道：`control-manager.buildSpawnEnv`、`mcp-manager` 注入键与 `launchd_setup` plist 键（`<key>OPENSECURITY_HOME</key>`）统一；daemon/MCP 子进程按新键读取。
- 测试：全部沙箱开关改新名（`TEST_OPENSECURITY_HOME`、`os.environ["OPENSECURITY_HOME"]`）。
- 保留独立键不动：`OPENSECURITY_VENV_DIR`（venv 与数据目录解耦的既有设计）。

### 2.3 实施方式

- 脚本化三形态替换（lookaround 词边界，防 `metadata_dir` 类误伤）：36 文件 179 处。
- 手工清理 6 处：`constants.ts` 读链块重写（去兼容与重复行）；`config_manager.py` 4 处（docstring×2、兼容常量行删除、读取链收敛）；`security-analysis.ts` 注释。

### 2.4 影响面

无 prompt 行数变化；环境信息段与 16 处文档引用不变（已用新名）；5 agent 展开 428/449/407/416/320 不变。

## §3 实施与验证（as-built）

| 步骤 | 内容 | 结果 |
|------|------|------|
| S1 | 脚本替换 36 文件 / 179 处 | 零残留（脚本内验证） |
| S2 | 手工清理 6 处 | 伪影扫描零（`兼容 OPENSECURITY_HOME` 等） |
| S3 | 语法与套件 | `bun build` ×5 OK；`py_compile` ×31 OK；沙箱：新名生效、旧名不再被读取 |
| S4 | 测试套件 | `test_control` 87 passed；`test_integration` 6 passed（两者各 1 个既有 `::test` 助手函数收集错误，与本变更无关） |
| S5 | 新进程端到端 | bash `HOME_VAR=[...]` 注入、`OLD=[]` 空、环境信息段逐字；控制台复用 + knowledge/events/ocr/proxy 4×MCP 注册成功 |
| S6 | 终态复扫 | 代码/测试三形态零残留；运行时/人类文档零残留；记录侧仅历史文档（21 文件）保留原名史实 |

## §4 验收标准

- **功能**：新名在插件注入、进程间通道、控制台服务、测试沙箱全链生效；旧名不再被任何读取点接受。
- **回归**：`DATA_DIR|data_dir|dataDir` 在代码与测试中零残留；全部相关测试通过；构建/编译零错误。
- **架构**：改动全部落在既有归属目录（plugins/control/mcp-servers/tools/test）；无新增归属争议。

## §5 与现有文档的关系

- **承接并取代** `2026-09-28-opensecurity-home-var-rename.md` 的兼容设计；`2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md` 追加 v3 注记。
- **不受影响**：命令文档（`2026-09-27-cookie-jar-kb-and-attribution-command.md`）引用的 `$OPENSECURITY_HOME` 与命令落盘一致（草稿==实现）。
- **记录策略**：历史文档中的 `DATA_DIR` 作为史实保留（含各修订链）；如需连历史一并改写由用户另行决策。
- **范围外观察**：repo 级 `test/knowledge`、`test/mcp_events` 等脚本的 `Path.home()/bw-security-analysis` 默认值不含 `DATA_DIR` 名，未在本次范围；`test_control.py:75` 与 `test_integration.py:48` 的 `def test(name)` 助手命名瑕疵建议后续单独修。
