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
