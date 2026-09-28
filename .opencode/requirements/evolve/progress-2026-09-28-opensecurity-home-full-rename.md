# 进度: 全面统一 DATA_DIR → OPENSECURITY_HOME

> 需求: `2026-09-28-opensecurity-home-full-rename.md`
> 来源: 用户指令（撤除兼容别名，全面统一）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | 脚本替换（36 文件 179 处） | ☑ | 零残留 |
| S2 | 手工清理 6 处 | ☑ | 伪影扫描零 |
| S3 | 语法与沙箱 | ☑ | bun build ×5；py_compile ×31；新名生效/旧名忽略 |
| S4 | 测试套件 | ☑ | test_control 87 passed；test_integration 6 passed |
| S5 | 新进程端到端 | ☑ | 注入/环境段/控制台/4×MCP 全绿 |
| S6 | 终态复扫 | ☑ | 代码/测试/文档零残留；记录仅史实 |

## as-built 记录

- 替换方式：Python 脚本三形态正则替换（`DATA_DIR`→`OPENSECURITY_HOME`；`(?<![A-Za-z0-9])data_dir(?![A-Za-z0-9_])`→`opensecurity_home`；同理 camel），36 文件 179 处一次到位。
- 手工修复：constants 读链重写；config_manager 兼容常量和读取链删除、docstring×2；security-analysis 注释。
- 验证证据：`bun build`（security-analysis/control-manager/mcp-manager/test-control/constants）；`py_compile` 31 文件；沙箱实测（`OPENSECURITY_HOME=/tmp/oh2` 生效、`DATA_DIR=/tmp/dd` 被忽略回默认）；`test_control.py` 87 passed、`test_integration.py` 6 passed；新进程诊断会话（bash 注入 + 环境信息段逐字 + 控制台复用 + 4×MCP 注册）；全仓复扫零残留。
- 既有问题（非本变更）：`test_control.py:75` / `test_integration.py:48` 的 `def test(name)` 助手函数被 pytest 收集为用例（各 1 collection error）。

## 评审修正（v2）

- ① 6 处重复读取清理（兼容链残留）：clean_databases / control_url / vite.config / test_e2e_real / detect_py_deps / detect_tools → 单次读取。
- ② 外部路径归一化落地（读取边界 `expanduser + abspath`，无 realpath）：OPENSECURITY_HOME（8 站点）、OPENCODE_ROOT（4 站点）、OPENSECURITY_VENV_DIR（1 站点）、IDA_PRO_HOME（ConfigManager.get_all 统一 + validator）。
- 验证：重复读取扫描零；TS 四态实测（`~/oh` 展开 / `rel/oh` 解析 / venv 覆盖 / 默认）；Python 实测（detect_tools/detect_py_deps/control_url/clean_databases + config_manager：home 展开、root 归一、`IDA_PRO_HOME=~/fake_ida` 读归一）；`py_compile` OK；`bun build` OK；`test_control` 87 passed；新进程诊断（注入 + 旧名空）通过。

## 问答补充（v3，无行为变更）

- 确认 **Node/Bun 无官方 tilde 展开 API**（nodejs/node#684 wontfix；官方件仅 `os.homedir()` + `path.resolve()`，本机实测 node v24.13.0 / bun 1.3.14 均无 `path.expandUser`）；实现与 npm 事实标准 `untildify` 语义对齐（只展开前导 `~`/`~/`/`~\`，不 `~user`）。
- 边界用例实测：`~`→家目录；`~/x`→家目录/x；`~user/x`→不展开（按相对路径解析）；`mid~dle/x`→原样。TS 注释已补充该依据；不引入 `untildify` 依赖（1 行逻辑，不值得增依赖）。

## 插件侧去自研展开（v4，用户评审）

- 决策：官方无 tilde API → **不保留自研路径函数**；插件侧（`constants.ts`、`vite.config.ts`）移除 `normalizeExternalPath` 与内联 `~` 替换，env 原样透传（覆盖值须为绝对路径；shell 导出时由 shell 展开）；默认值仍为代码构造的绝对路径。
- 实测（透传四态）：`~/x`→`~/x`、`rel/x`→`rel/x`、`/abs/x`→`/abs/x`、缺省→`/Users/aserlili/bw-security-analysis`（含 VENV）。
- 构建：`constants.ts` / `security-analysis.ts` / `vite.config.ts` 全绿；自研函数与 `resolve()` 调用在插件侧清零。
- 保留：Python 侧官方 `os.path.expanduser + abspath` 不变（标准库 API，非自研）。
