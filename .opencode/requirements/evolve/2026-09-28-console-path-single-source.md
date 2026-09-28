# 2026-09-28 控制台路径收口：services/runtime_paths.py 唯一来源（含 CACHE_DIR 正名）

> 状态：已实施（2 轮检查 + 全量回归通过）| 入口：用户评审（① `OPENSECURITY_HOME/OPENCODE_ROOT/缓存目录` 解析散落多处；② `CACHE_DIR` 名不副实——它就是 OPENSECURITY_HOME 本体）
> 修订 v2（实施修正）：RuntimePaths 双 API（`resolve()` 可重解析 + 进程级冻结常量）；`AI_ENV_PATH` 常量移除（config_manager 走实例解析）；保留 `_reset_for_tests` 重解析语义
> 修订 v3（评审修正）：文件更名 `runtime_paths.py`（"paths" 太通用）；常量收口静态类 `RuntimePaths`（OOP 写法）；消费方与文档引用同步
> 修订 v4（评审修正二）：全部 sys.path 自举移除（启动方注入 PYTHONPATH；`clean_databases` 移至 backend 根）；恢复 `detect_tools` CLI（历史重构静默丢失）+ 修复 `detect_py_deps install` 裸调用；test/deps 陈旧测试重写（22 通过）
> 修订 v5（评审修正三）：`RuntimePaths.resolve()` 移除——类属性为唯一取数接口，新增 `refresh()`（唯一调用方 = ConfigManager 初始化）；config_manager 直读类属性（删实例路径字段）；`ToolsEnv._opencode_root` 删除；MCP 与控制台解耦（插件注入 `OPENSECURITY_CONTROL_IPC`，control_url 零 console import）
> 修订 v6（评审修正四）：`_resolve()` 模块级化（去类尾 staticmethod 包装；残留引用已消除）；类属性仅类型声明，`refresh()` 成为初始化与重算的唯一求值点（模块加载时首调）
> 关联：`2026-09-28-opensecurity-home-full-rename.md`（命名统一）；本文件解决"解析逻辑收口与正名"
> 实施进度与 as-built：`progress-2026-09-28-console-path-single-source.md`

## §1 背景与目标

**痛点**：
1. env 读取 + 归一化惯用式在 7 处重复：`config_manager`、`detect_tools`、`detect_py_deps`、`launchd_setup`、`control_url`、`clean_databases`、`test_e2e_real`；`db/knowledge/knowledge.db`、`logs/` 等子路径字面量也在多处拼接。
2. 命名误导：`ToolsEnv.CACHE_DIR`、`detect_py_deps.CACHE_DIR` 实为 OPENSECURITY_HOME 本体（不是"缓存目录"）。

**目标**：新增 `control/backend/services/runtime_paths.py` 作为 `OPENSECURITY_HOME` / `OPENCODE_ROOT` 及标准子路径的**唯一来源**；全部消费方改为引用；删除 `CACHE_DIR` 命名。

**明确不做**：改 socket 名/管道名（"按约定复制"的协议常量，非目录）；改 Python 侧 `os.path.expanduser` 官方归一化语义；改 plugin TS 侧（已在 `constants.ts` 单点）。

## §2 技术方案

### 2.1 新模块 `control/backend/services/runtime_paths.py`（全文稿）

```python
"""路径唯一来源（静态类 RuntimePaths）：OPENSECURITY_HOME / OPENCODE_ROOT 及标准子路径。

- 读取边界归一化（expanduser + abspath；不做 realpath——保留符号链接语义）。
- 仅依赖标准库——可被各进程（控制台/薄壳/工具脚本）单独 import（导入路径由启动方注入 PYTHONPATH）。
- 其他模块不得再重复"读 env + 归一化"的写法；子路径字面量也收口在本类。
- 类属性 = 引导 env 的快照，消费方直接读取；`refresh()` 是唯一求值点（模块加载时首调；重算见其 docstring）。
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve() -> tuple[str, str]:
    """按当前环境解析 (OPENSECURITY_HOME, OPENCODE_ROOT)（不缓存）。"""
    home = os.environ.get("OPENSECURITY_HOME") or str(Path.home() / "bw-security-analysis")
    # .opencode 根兜底：由本文件位置逐级回溯 services → backend → control → .opencode（不解析符号链接）
    services_dir = Path(os.path.abspath(__file__)).parent
    root = os.environ.get("OPENCODE_ROOT") or str(services_dir.parents[2])
    # 归一化：expanduser + abspath（不做 realpath——保留符号链接语义）
    return (
        os.path.abspath(os.path.expanduser(home)),
        os.path.abspath(os.path.expanduser(root)),
    )


class RuntimePaths:
    """路径唯一来源（静态类）。

    - 类属性（OPENSECURITY_HOME / OPENCODE_ROOT / 各标准子路径）= 引导 env 快照，消费方直接读取；
    - `refresh()` 是**唯一求值点**（初始化与重算共用同一段代码）：模块加载时调用一次；
      此后唯一调用方是 ConfigManager 构造（_init_once）——测试在同一 pytest 进程内切换
      沙箱后重建实例时读到新值（生产 env 启动后不变，重算等价于快照）。
    """

    # —— 引导 env 快照（值由模块加载时的 refresh() 写入；消费方直接读取）——
    OPENSECURITY_HOME: str
    OPENCODE_ROOT: str
    LOGS_DIR: str
    KNOWLEDGE_DB: str
    VENV_DIR: str
    BIN_DIR: str
    TOOLS_DIR: str
    WORDLISTS_DIR: str

    @classmethod
    def refresh(cls) -> None:
        """按**当前** os.environ 求值并写入类属性快照（初始化与重算的**唯一求值点**）。

        何时会真正"变化"：
        - 生产：env 在进程启动前设定、之后不变——模块加载时求值一次，首次构造再算一次
          （结果等价）；
        - 测试：pytest 在**同一进程**内逐用例切换沙箱——先改进程版 `os.environ`，再重建
          ConfigManager **单例对象**（`_reset_for_tests()` 置空 `_instance` → `__new__` 走
          构造分支；不是进程、无 fork），本方法把类属性重新赋值为当前 env 的求值结果，
          让新实例读到新值，而不是模块加载时的旧快照。

        调用方: ① 模块加载（初始快照） ② ConfigManager 构造（_init_once）。
        运行中的其他模块不得调用。
        """
        cls.OPENSECURITY_HOME, cls.OPENCODE_ROOT = _resolve()
        cls.LOGS_DIR = os.path.join(cls.OPENSECURITY_HOME, "logs")
        cls.KNOWLEDGE_DB = os.path.join(cls.OPENSECURITY_HOME, "db", "knowledge", "knowledge.db")
        cls.VENV_DIR = os.path.join(cls.OPENSECURITY_HOME, ".venv")
        cls.BIN_DIR = os.path.join(cls.OPENSECURITY_HOME, "bin")
        cls.TOOLS_DIR = os.path.join(cls.OPENSECURITY_HOME, "tools")
        cls.WORDLISTS_DIR = os.path.join(cls.OPENSECURITY_HOME, "wordlists")


# 模块加载即快照（refresh() 是唯一求值点；ConfigManager 构造时按需重算）
RuntimePaths.refresh()
```

### 2.2 迁移清单

| 消费方 | 现状 | 改为 |
|--------|------|------|
| `config_manager.py` | 自读 env×2 + 归一化；Bootstrap 持 env 名/默认值 | `_init_once` 调 `RuntimePaths.refresh()`（生产等价一次快照；测试重建链重读）；路径属性直读 `RuntimePaths.*`（无实例路径字段）；删 Bootstrap 三个路径常量 |
| `detect_tools.py` | `ToolsEnv.CACHE_DIR` 自读 env，派生 3 目录；`_opencode_root()` 自推导；venv 候选 2 处拼 `.venv` | `CMD_DIR=RuntimePaths.BIN_DIR`、`TOOLS_HOME_DIR=RuntimePaths.TOOLS_DIR`、`WORDLISTS_DIR=RuntimePaths.WORDLISTS_DIR`；`_opencode_root()` 删除（4 处调用点直读 `RuntimePaths.OPENCODE_ROOT`）；候选 2 处→`RuntimePaths.VENV_DIR`（CACHE_DIR 删除） |
| `detect_py_deps.py` | `CACHE_DIR`/`VENV_DIR` 自读 env | `VENV_DIR = RuntimePaths.VENV_DIR`（CACHE_DIR 删除）；导入路径由启动方注入 PYTHONPATH=backend；docstring 约束更新 |
| `launchd_setup.py` | env 或 cm 双读 ×2；日志目录拼接 | `str(cm.opencode_root)` / `str(cm.opensecurity_home)`（cm 由 paths 提供）；日志目录→`RuntimePaths.LOGS_DIR` |
| `control_url.py` | `_unix_socket_path` 自读 env | 读启动方注入的 `OPENSECURITY_CONTROL_IPC`（完整平台地址；零控制台代码依赖；PYTHONPATH 仅 mcp-servers） |
| `clean_databases.py` | 自读 env + 拼 db 路径 | 移至 `control/backend/` 根（直跑天然可得导入路径）+ `KNOWLEDGE_DB = Path(RuntimePaths.KNOWLEDGE_DB)` |
| `knowledge_store.py` | 拼 `db/knowledge/knowledge.db` | `Path(RuntimePaths.KNOWLEDGE_DB)` |
| `logging_setup.py` | 拼 `logs/` ×2 | `Path(RuntimePaths.LOGS_DIR) / ...` ×2 |
| `test_e2e_real.py` | 自读 env | `Path(RuntimePaths.OPENSECURITY_HOME)` |

### 2.3 显式语义变化

- `ConfigManager.opencode_root` 不再有"空串"分支：env 未设时由 paths 按 `.opencode` 位置回溯派生（此前为空串 → `.ai_env` 走 CWD 相对）。影响：直跑控制台将读取真实 `.ai_env`（更符合预期）；`frontend_port` 的 `if not opencode_root` 防御分支成为恒定可用兜底（保留，不删）。
- 跨目录运行/导入的进程由**启动方注入 PYTHONPATH**（install.sh/ps1 → backend；插件 env-check → backend；mcp-manager → mcp-servers；测试夹具同）；脚本内不写 sys.path 自举；人工直跑 CLI 用 `cd backend && python -m services.<x>`；`clean_databases` 移至 backend 根（直跑 `python <脚本>` 即为包根上下文）。
- 归一化语义不变（官方 `expanduser + abspath`，无 realpath）。
- **保留测试隔离设计**：修改引导 env + 重建实例 → `ConfigManager._init_once` 内 `RuntimePaths.refresh()` 重算类属性快照（既有 OPENCODE_ROOT 交换用例语义不变）。
- **MCP 与控制台解耦**：插件 mcp-manager 注入 `OPENSECURITY_CONTROL_IPC`（平台最终地址；Unix socket 路径 / Windows 管道名）；`control_url` 不再 import 控制台代码，MCP 的 PYTHONPATH 仅 `mcp-servers`（薄壳同级导入）。

### 2.4 架构影响图

```
control/backend/services/runtime_paths.py（新，纯 stdlib；类属性快照 + refresh）
   ├─ config_manager（init 时 refresh；属性直读 RuntimePaths.*）
   ├─ detect_tools（ToolsEnv 目录 + venv 候选；_opencode_root 已删）
   ├─ detect_py_deps（VENV_DIR）
   ├─ launchd_setup / logging_setup / knowledge_store（日志、记忆库、plist 路径）
   ├─ mcp-servers/control_url.py（插件注入 IPC 地址；零控制台依赖）
   └─ control/backend/clean_databases.py（backend 根直跑）
零 prompt 影响；TS 侧改动限于插件注入点（env-check / mcp-manager）。
```

### 2.5 Phase 4.5 预算校验

本批零 prompt/命令行数变化（5 agent 展开 428/449/407/416/320 不变；命令与 KB 不涉及）。

## §3 实现规范

### 3.1 实施步骤

**S1. 新建 services/runtime_paths.py**
- 文件：`control/backend/services/runtime_paths.py`（新） | 预估：+38 行 | 依赖：无
- 验证点：① `py_compile` 通过；② 沙箱实测：`OPENSECURITY_HOME=~/oh` 展开、`OPENCODE_ROOT` env 优先、env 缺省时 root 回溯为仓库 `.opencode`；③ 子路径与既有拼接值逐一相等（脚本对照）

**S2. config_manager 迁移**
- 文件：`config_manager.py` | 预估：净 -6 行 | 依赖：S1
- 验证点：① 内部不再出现 `os.environ.get` 路径读取（仅剩 CONTROL_* 两项）；② `cm.opensecurity_home/opencode_root/ai_env_path` 行为实测（含 env 沙箱）；③ `grep 'OPENSECURITY_HOME_ENV\|OPENCODE_ROOT_ENV\|DEFAULT_OPENSECURITY_HOME'` 全仓零残留；④ `test_control` 全量通过（含 `_reset_for_tests` 重解析用例）

**S3. detect_tools + detect_py_deps 迁移**
- 文件：两文件 | 预估：净 -8 行 | 依赖：S1
- 验证点：① `CACHE_DIR` 全仓零残留；② `ToolsEnv.CMD_DIR/TOOLS_HOME_DIR/WORDLISTS_DIR` == paths 对应值（沙箱实测）；③ `detect_py_deps.py scan` CLI 直跑通过（真链路）；④ py_compile

**S4. launchd/logging_store/knowledge_store 迁移**
- 文件：3 文件 | 预估：净 -6 行 | 依赖：S1
- 验证点：① `py_compile`；② 三文件不再出现自拼 `logs`/`db/knowledge` 字面量（grep）；③ `cm.ai_env_path`、`logging_setup._control_handler` 冒烟（test_control 覆盖）

**S5. control_url + clean_databases + test_e2e_real 迁移**
- 文件：3 文件 | 预估：净 -6 行 | 依赖：S1
- 验证点：① 三文件 import 冒烟（PYTHONPATH=backend[:mcp-servers] 注入）；② `control_url._unix_socket_path()` == RuntimePaths.OPENSECURITY_HOME/sock 名；③ `clean_databases.KNOWLEDGE_DB` == RuntimePaths.KNOWLEDGE_DB

**S6. 全量回归与终态扫描**
- 文件：无（检查） | 依赖：S1-S5
- 验证点：① `test_control.py` 全量（87+）通过；② `test_integration.py` 通过；③ 控制台 `/health` 触发 code_stale 自重启后恢复 `ok`（新代码上线）；④ 全仓扫描：路径惯用式仅存在于 `runtime_paths.py`（其余零）；⑤ progress/as-built 完整

### 3.2 编码规则

- 引用一律 `from services.runtime_paths import RuntimePaths`；跨目录进程由启动方注入 PYTHONPATH（脚本内无 sys.path 自举）；人工直跑 `cd backend && python -m services.<x>`；IPC 地址只读注入的 `OPENSECURITY_CONTROL_IPC`，不得自行拼接
- 不重复子路径字面量；不新增第三方依赖；不改归一化语义

## §4 验收标准

**功能验收**：runtime_paths.py 为唯一解析点；9 个消费方全部迁移；`CACHE_DIR` 命名清零；CLI 链路可用（PYTHONPATH 注入约定）。
**回归验收**：测试套件通过；控制台自重启后正常；归一化/沙箱语义与迁移前一致（除 §2.3 声明项）；零 TS 改动。
**架构验收**：新模块落位 `control/backend/services/`（既有归属）；跨目录导入一律"启动方注入 PYTHONPATH"；MCP 薄壳不依赖控制台代码（IPC 地址经环境变量注入）。

## §5 与现有需求文档的关系

- **承接** `2026-09-28-opensecurity-home-full-rename.md` §2.5-2 的归一化策略（本文件将其收口到单一模块）。
- **并行**：无交集。
- **范围外观察**：`vite.config.ts` 的 IPC 地址仍按常量自算（开发侧启动方复制，非依赖链）；binary-analysis/mobile-analysis 脚本族的 `sys.path.insert` 属另一子系统约定；`test_control.py:75`/`test_integration.py:48` 的 `def test(name)` 既有收集错误建议后续改名。
