# 进度: 控制台路径收口（services/runtime_paths.py 唯一来源）

> 需求: `2026-09-28-console-path-single-source.md`（含 v2 实施修正）
> 来源: 用户评审（解析散落 + CACHE_DIR 正名）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | 新建 services/runtime_paths.py | ☑ | py_compile；沙箱三态（env 覆盖/兜底）；子路径对照 |
| S2 | config_manager 迁移 | ☑ | 仅剩 CONTROL_* env 读取；`resolve()` 保留 reset 语义；test_control 通过 |
| S3 | detect_tools + detect_py_deps 迁移 | ☑ | CACHE_DIR 全仓零；`detect_py_deps scan` CLI 真链路通过 |
| S4 | launchd/logging/knowledge_store 迁移 | ☑ | py_compile；`db/knowledge`、`logs` 自拼字面量清零 |
| S5 | control_url + clean_databases + test_e2e_real 迁移 | ☑ | 导入冒烟：sock/db 随 env 沙箱；自举可用 |
| S6 | 全量回归与终态扫描 | ☑ | 87+6 测试通过；控制台 execv 重启验证；终扫仅 runtime_paths.py 保留默认值 |

## as-built 记录

- **新模块**：`control/backend/services/runtime_paths.py`（48 行，纯 stdlib；双 API：`resolve()` 可重解析 + 进程级冻结常量+标准子路径）。
- **实施修正（v2）**：初版 frozen 常量打断了 `_reset_for_tests()`（修改引导 env 重建实例）的既有测试隔离语义 → 增加 `resolve()` 供 `config_manager._init_once` 调用；`AI_ENV_PATH` 常量移除（cm 走实例解析，避免冻结态与实例态双源）。
- **迁移**：9 个消费方（config_manager / detect_tools / detect_py_deps / launchd_setup / logging_setup / knowledge_store / control_url / clean_databases / test_e2e_real）；`ToolsEnv.CACHE_DIR`、`detect_py_deps.CACHE_DIR` 删除并正名（目录值来自 paths）。
- **验证证据**：
  - py_compile 全量通过；沙箱三态（`OPENSECURITY_HOME/OPENCODE_ROOT` env 覆盖、缺省兜底=仓库 `.opencode`）。
  - CLI 真链路：`detect_py_deps.py scan --json` 通过；`control_url._unix_socket_path()`/`clean_databases.KNOWLEDGE_DB` 随 env。
  - 测试：`test_control` 87 passed、`test_integration` 6 passed（各 1 个既有 `::test` 收集错误，与本变更无关）。
  - 控制台热重启：`code_stale:true` → `POST /api/system/restart` → boot_token `f308bdb8`→`ea949cfa`、`code_stale:false`、`/api/system` 正常。
  - 终态扫描：路径惯用式仅存于 `runtime_paths.py`；`bw-security-analysis` 字面量仅存于 `runtime_paths.py` 默认值与 config_manager 注释标签；`CACHE_DIR` 零。
- 遗留观察：socket 名/Windows 管道名仍按"跨进程约定复制"（非目录，未收口）；`routes/fs.py` 对请求路径的 `expanduser()` 属运行时输入处理（非配置边界，保留）。

## 评审修正（v2，命名与 OOP 写法）

- 文件更名：`services/paths.py` → `services/runtime_paths.py`（"paths" 太通用）。
- OOP 收口：常量与解析进静态类 `RuntimePaths`（类属性 + `resolve()` staticmethod；模块级仅两个私有求值函数）——对齐 `ToolsEnv`/`ConfigManager.Bootstrap` 既有风格。
- 消费方 9 处引用同步（`from services.runtime_paths import RuntimePaths`）；需求文档 §2.1 与实现逐字节同步（49 行）。

## 评审修正（v3，自举体系重构 + 两项历史缺陷修复）

- **自举移除**（新标准 = 启动方注入 PYTHONPATH）：`detect_py_deps`/`detect_tools`/`docker_build_toolbox`/`docker_push_toolbox`/`control_url`/`clean_databases` 及 mcp-servers 薄壳 ×4 的 sys.path 操作全部删除；注入点：install.sh/ps1（export PYTHONPATH=backend）、插件 env-check.ts、mcp-manager.ts（backend+mcp-servers）、test/deps conftest、test_control 用例。
- **clean_databases 迁移**：`tools/clean_databases.py` → `control/backend/clean_databases.py`（backend 根直跑天然可得导入路径）；`docs/项目介绍/知识与记忆体系.md` 同步。
- **历史缺陷修复（非本轮引入）**：
  1. `detect_tools` CLI 自"控制台重构 - 2"起静默丢失 → install.sh 第 2 步与知识库提示命令长期失效；已按历史原型恢复（scan/install/list-installable）+ 3 条 CLI 回归测试防再次丢失。
  2. `detect_py_deps install` 裸调用 `required_packages()`（NameError）→ `PyDepsDetector.required_packages()`；dry-run 实测输出 68 个包。
  3. test/deps 陈旧（旧模块级 API）13 红 → 按当前类 API + PYTHONPATH 约定重写，22 通过。
- **验证**：py_compile ×13；bun build（mcp-manager/env-check）；负/正测试（无 PYTHONPATH→明确 ImportError；有→scan exit 0）；MCP 薄壳 JSON-RPC 握手通过（search_knowledge 在列，无 traceback）；`bash -n install.sh` OK；test_control 87 / test_integration 6 / test/deps 22；嵌套 opencode：checkPyDepsViaCli status=0 ×4 + MCP 注册成功 ×4；控制台热重启 boot_token `99eaaf0e→9e8cbcf7`、code_stale false。
- **未动（留档）**：binary-analysis/mobile-analysis 脚本族自带 `sys.path.insert`（另一子系统既有约定）；socket/管道协议常量"按约定复制"；`test_control.py:75`/`test_integration.py:48` 的 `def test(name)` 既有收集错误（建议后续改名）。

## 评审修正（v4，接口收敛 + MCP 解耦）

- **`RuntimePaths.resolve()` 移除**：类属性（快照）为唯一取数接口；新增 `refresh()`（与类体同式重算，唯一调用方 = `ConfigManager._init_once`——测试隔离"改 env 后重建实例"语义保留，无需双 API）。
- **config_manager**：属性直读 `RuntimePaths.OPENSECURITY_HOME/OPENCODE_ROOT`（删实例路径字段与 `resolve()` 调用）。
- **detect_tools**：`ToolsEnv._opencode_root()` 删除；4 处调用点直读 `RuntimePaths.OPENCODE_ROOT`。
- **MCP 与控制台解耦**：插件注入 `OPENSECURITY_CONTROL_IPC`（平台最终地址；常量源 = `constants.ts` 的 `CONTROL_UNIX_SOCKET`/`CONTROL_WIN_PIPE`）；`control_url.py` 删除 RuntimePaths import、删除本地 socket 名/管道名常量与 `_unix_socket_path()`，改读注入地址（缺失时 RuntimeError 明确报错）；mcp-manager 的 PYTHONPATH 收窄为 `mcp-servers`（薄壳同级导入），不再注入 backend / OPENSECURITY_HOME。
- **验证**：py_compile OK；`bun build` mcp-manager OK；`control_url` 控制台引用扫描 ZERO；负测试（缺 IPC env → `RuntimeError: OPENSECURITY_CONTROL_IPC 未注入…`）；正测试（仅 IPC env + PYTHONPATH=mcp-servers → resolve + knowledge 薄壳 JSON-RPC 握手通过）；test_control 87 / test_integration 6 / test/deps 22；嵌套 opencode：env-check status=0 ×4 + MCP 注册成功 ×4；控制台热重启 `9e8cbcf7→cf83479c`、code_stale false。

### Q&A 澄清（评审答复，同日）

- **`refresh()` 定位**：不是"运行期动态刷新"，而是"**构造时按当前 env 求值一次快照**"——生产 env 启动后不变（等价每进程一次）；pytest 单进程多沙箱切换是其唯一有效场景——重建的是 **ConfigManager 单例对象**（`_reset_for_tests()` 置空 `_instance` → `__new__` 走构造分支；**无 fork/子进程**），refresh 直接改写类属性。全仓 `ConfigManager._reset_for_tests` 调用点 15 处**全在测试**（零生产调用）→ 生产恰好一次 / 测试 N 次。调用方唯一（`config_manager._init_once`）。代码注释（runtime_paths.refresh / cm 构造处）已按此改写；§2.1 重同步复核 IDENTICAL；py_compile OK。
- **`_ipc_address()` 路径**：注入值即完整地址（`join(OPENSECURITY_HOME, "opensecurity-control.sock")` 拼接在插件侧完成），control_url 零拼接、零路径知识；实测注入值 = live socket 路径（`srwxr-xr-x`）、`resolve_control()` via=uds；Windows 注入完整管道名。

### 评审修正（v6，求值单一化）

- **`_resolve()` 模块级化**（评审改定）：类体与 `refresh()` 同源调用模块级私有函数；删除类尾 `staticmethod` 包装。中间态曾残留 `cls._resolve()` 旧引用（`refresh()` 内）——实测 `AttributeError: type object 'RuntimePaths' has no attribute '_resolve'`，本次统一时消除（无需恢复包装）。
- **初始化与重算单一求值点**：`refresh()` 成为唯一写入点（类属性仅类型声明，8 个值只写一次）；模块尾部 `RuntimePaths.refresh()` 完成加载时快照；类体内不再重复一份求值代码（此前 8 行 ×2 处）。
- 验证：py_compile；import 快照 + 沙箱切换链（reset + 重建）实测跟随；test_config_manager 5/5；test_control 87 / test_integration 6 / test/deps 22；§2.1 重同步 IDENTICAL。
- 实机验证：控制台热重启（execv，pid/start_time 不变属预期）boot_token `cf83479c→c37839f6`、code_stale true→false、/api/system 与 /api/config 200、/health 预热瞬态 503 → 稳定 200；日志实锤启动链（execv → IPC 监听 → bge-m3 ready → 心跳注册 pid=77514）。
