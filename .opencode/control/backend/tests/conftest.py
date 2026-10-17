
# pyright: reportUnknownParameterType=false, reportMissingTypeArgument=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
# test_control.py 是自包含直跑脚本（自带极简测试框架），非 pytest 用例——
# 其 def test(name) 注册器会被 pytest 误收集（fixture 'name' not found），
# 且 @test 装饰的 wrapper 也非 pytest 形态。整体排除收集;消费方
# （test_api_guard 等）`from tests.test_control import test, ...` 不受影响。
collect_ignore = [
    "test_control.py",       # 自包含直跑脚本（自带注册器, 显式路径可跑）
    "test_integration.py",   # 同形态: pytest 目录收集会误收报错
    "test_e2e_real.py",      # 同形态
]


# ── ConfigManager 沙箱测试的环境还原（防跨文件污染）─────────────
# test_config_manager 的 _fresh() 会 setenv 沙箱路径——用例结束不还原时，
# 后续文件（proxy 系）的 ConfigManager 单例读到沙箱空配置（凭证全丢）。
# 此 fixture 用例级还原: 该文件每个用例后恢复真实 env + 重置单例。
import os as _os
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _restore_cm_sandbox(request: "_pytest.FixtureRequest"):
    if "test_config_manager" not in str(getattr(request, "fspath", "")):
        yield
        return
    _keys = ("OPENSECURITY_HOME", "OPENSECURITY_AI_ENV", "OPENCODE_ROOT")
    _saved = {k: _os.environ.get(k) for k in _keys}
    yield
    for k, v in _saved.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v
    from services.config_manager import ConfigManager
    ConfigManager._reset_for_tests()


# ── 快慢分离: 慢文件标记（pytest -m "not slow" 只跑快集）──────────
# 慢 = 真起服务/真等时间窗（分钟级）; 快 = 纯逻辑（秒级）。
# 日常: pytest -m "not slow"  全量: pytest（CI/提交前）
_SLOW_FILES = {"test_e2e_remote.py", "test_remote_e2e.py", "test_control.py"}


def _pytest_configure(config: "_pytest.Config") -> None:
    config.addinivalue_line(
        "markers", "slow: 真集成/起服务测试（-m 'not slow' 跳过）")


def _pytest_collection_modifyitems(config: "_pytest.Config", items: "list") -> None:
    from pathlib import Path as _Path
    for item in items:
        if _Path(str(getattr(item, "fspath", ""))).name in _SLOW_FILES:
            item.add_marker(_pytest.mark.slow)
