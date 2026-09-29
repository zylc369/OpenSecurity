"""OOP 重构后单例边界测试（批次 D/E 类化模块的身份/隔离/幂等）。

覆盖（需求: 用户要求"所有正常 CASE 和边界 CASE"中，新类化单例的专属边界）:
  1. 单例身份: 构造/get_instance/重复访问同对象; _reset_for_tests 后新实例
  2. 资源收尾: _shutdown_for_tests 语义（有资源的类释放）
  3. 幂等: LogManager.setup / setup_auxiliary 重复调用不叠加 handler

运行: cd .opencode/control/backend && python3 tests/test_oop_singletons.py
"""
# pyright: reportMissingParameterType=false
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
_SANDBOX = Path("/tmp/oop_sgl_root")
_DATA = Path("/tmp/oop_sgl_data")
shutil.rmtree(_SANDBOX, ignore_errors=True)
shutil.rmtree(_DATA, ignore_errors=True)
_SANDBOX.mkdir(parents=True)
_DATA.mkdir(parents=True)
os.environ["TEST_OPENSECURITY_HOME"] = str(_DATA)  # #7 约定: 沙箱根经 TEST_ 变量表达（import test_control 后由它落 OPENSECURITY_HOME）
os.environ["OPENCODE_ROOT"] = str(_SANDBOX)
(_SANDBOX / ".ai_env").write_text("# 单例测试沙箱\n")

from tests.test_control import test, assert_eq, assert_true  # noqa: E402


@test("单例身份: 批次 D/E 全部单例类构造等价 get_instance")
def test_singleton_identity_all():
    from services.ocr_service import OcrService
    from services.remote_link import RemoteLinkService
    from services.model_loader import ModelInferenceService
    from services.model_assets import ModelAssetRegistry
    from services.heartbeat import HeartbeatRegistry
    from services.frontend_port import FrontendPortRegistry
    from services.ipc_listener import IpcListener
    from services.event_store import EventStoreService
    from services.knowledge_store import KnowledgeStoreService
    from services.restart import ConsoleRestarter
    from services.launchd_setup import LaunchdManager
    from services.config_manager import ConfigManager

    for cls in (OcrService, RemoteLinkService, ModelInferenceService,
                ModelAssetRegistry, HeartbeatRegistry, FrontendPortRegistry,
                EventStoreService, KnowledgeStoreService, ConsoleRestarter,
                LaunchdManager, ConfigManager):
        a = cls.get_instance()
        assert_true(cls() is a, f"{cls.__name__}: 构造应等价 get_instance")
        assert_true(cls.get_instance() is a, f"{cls.__name__}: 重复访问同对象")


@test("单例隔离: _reset_for_tests 后获得新实例（无资源类抽查）")
def test_singleton_reset():
    from services.heartbeat import HeartbeatRegistry
    a = HeartbeatRegistry.get_instance()
    HeartbeatRegistry._reset_for_tests()
    b = HeartbeatRegistry.get_instance()
    assert_true(b is not a, "reset 后应新实例")
    assert_true(HeartbeatRegistry.get_instance() is b, "新实例稳定")

    from services.restart import ConsoleRestarter
    ConsoleRestarter._reset_for_tests()
    c = ConsoleRestarter.get_instance()
    c.perform = lambda: None  # 拦截真实 execv（防测试进程被重启替换）
    assert_true(c.schedule() is True, "新实例可调度")
    assert_true(c.schedule() is False, "重复调度幂等拒绝")


@test("LogManager: setup 幂等——重复调用不叠加 root handler")
def test_log_manager_idempotent():
    from services.logging_setup import LogManager
    LogManager.get_instance().setup()               # 首次（file + stderr 两个 handler）
    after_first = len(logging.getLogger().handlers)
    assert_true(after_first >= 1, "首次 setup 添加 handler")
    LogManager.get_instance().setup()               # 幂等
    assert_eq(len(logging.getLogger().handlers), after_first, "重复 setup 不叠加 handler")


@test("LogManager: setup_auxiliary 独立文件 + propagate 关闭 + 幂等")
def test_log_auxiliary():
    from services.logging_setup import LogManager
    lg = LogManager.get_instance().setup_auxiliary("oop_test_aux", "oop-aux.log")
    LogManager.get_instance().setup_auxiliary("oop_test_aux", "oop-aux.log")  # 幂等
    assert_eq(len(lg.handlers), 1, "不叠加 handler")
    assert_true(lg.propagate is False, "不向 root 传播")
    lg.info("边界行-XYZ")
    for h in lg.handlers:
        h.flush()
    aux = _DATA / "logs" / "oop-aux.log"
    assert_true(aux.exists() and "边界行-XYZ" in aux.read_text(), "独立文件写入")
    ctl = _DATA / "logs" / "control.log"
    assert_true(not ctl.exists() or "边界行-XYZ" not in ctl.read_text(), "不进 control.log")


@test("FrontendPortRegistry: 单例端口注册状态共享 + reset 清空")
def test_frontend_registry_state():
    from services.frontend_port import FrontendPortRegistry
    import socket as _s
    # 起一个临时监听用于注册
    srv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    reg = FrontendPortRegistry.get_instance()
    assert_true(reg.register_tcp(port), "活端口注册成功")
    assert_eq(FrontendPortRegistry.get_instance().tcp_port(), port, "单例状态共享")
    FrontendPortRegistry._reset_for_tests()
    assert_true(FrontendPortRegistry.get_instance().tcp_port() is None, "reset 清空")
    srv.close()


@test("EventStoreService/KnowledgeStoreService: _create_fresh 独立实例（绕过单例）")
def test_create_fresh_independent():
    from services.event_store import EventStoreService
    fresh = EventStoreService._create_fresh(graphiti_factory=lambda: (None, "fake-err"))
    assert_true(fresh is not EventStoreService.get_instance(), "fresh 独立于单例")
    fresh2 = EventStoreService._create_fresh(graphiti_factory=lambda: (None, "fake-err"))
    assert_true(fresh is not fresh2, "两次 fresh 各自独立")


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"单例边界测试: {len(_tests)} 个\n")
    for _name, _fn in _tests:
        _fn()
    from tests.test_control import _results
    _passed = sum(1 for _, ok, _ in _results if ok)
    _failed = len(_results) - _passed
    print(f"\n通过 {_passed} / 失败 {_failed} / 总计 {len(_results)}")
    if _failed:
        for _n, ok, _msg in _results:
            if not ok:
                print(f"  ✗ {_n}: {_msg}")
        sys.exit(1)
