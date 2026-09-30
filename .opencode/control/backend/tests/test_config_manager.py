"""ConfigManager 单元测试（单例/读写/tunables/元数据/沙箱隔离）。

运行: cd .opencode/control/backend && python3 tests/test_config_manager.py
"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

if TYPE_CHECKING:
    from services.config_manager import ConfigManager

from tests.test_control import test, assert_eq, assert_true  # noqa: E402

_SANDBOX = Path("/tmp/cm_unit_root")
_DATA = Path("/tmp/cm_unit_data")


def _fresh() -> ConfigManager:
    """隔离沙箱 + 重置单例，返回新实例。"""
    from services.config_manager import ConfigManager
    ConfigManager._reset_for_tests()
    shutil.rmtree(_SANDBOX, ignore_errors=True)
    shutil.rmtree(_DATA, ignore_errors=True)
    _SANDBOX.mkdir(parents=True)
    _DATA.mkdir(parents=True)
    os.environ["OPENSECURITY_HOME"] = str(_DATA)
    os.environ["OPENSECURITY_AI_ENV"] = str(_DATA / ".ai_env")  # 同步重定向（import test_control 设的指向它的沙箱）
    os.environ["OPENCODE_ROOT"] = str(_SANDBOX)
    return ConfigManager.get_instance()


@test("ConfigManager: 单例身份——构造/get_instance/重复访问同对象")
def test_singleton_identity():
    from services.config_manager import ConfigManager
    _fresh()
    a = ConfigManager.get_instance()
    assert_true(ConfigManager() is a, "构造与 get_instance 同对象")
    assert_true(ConfigManager.get_instance() is a, "重复访问同对象")
    ConfigManager._reset_for_tests()
    b = ConfigManager.get_instance()
    assert_true(b is not a, "重置后新实例")


@test("ConfigManager: .ai_env 读写——set/get/delete/注释保留/模板")
def test_env_rw():
    cm = _fresh()
    assert_true(cm.ensure_template(), "首次创建模板")
    assert_false = not cm.ensure_template()
    assert_true(assert_false, "二次调用幂等不重写")
    cm.set({cm.Keys.DEEPSEEK_API_KEY: "sk-abc123def",
            cm.Keys.CONTROL_RESIDENT: "1"})
    assert_eq(cm.get(cm.Keys.CONTROL_RESIDENT), "1")
    raw = cm.ai_env_path.read_text()
    assert_true("# IDA Pro 安装目录" in raw, "注释保留")
    cm.delete(cm.Keys.CONTROL_RESIDENT)
    assert_true(cm.get(cm.Keys.CONTROL_RESIDENT) is None, "删除生效")


@test("ConfigManager: tunables——.ai_env 优先/非法回退默认/三组齐全")
def test_tunables():
    cm = _fresh()
    rt = cm.remote_tunables()
    assert_eq((rt.fail_threshold, rt.recover_threshold), (2, 3), "默认值")
    ht = cm.heartbeat_tunables()
    assert_eq(ht.timeout_sec, 60.0)
    pt = cm.proxy_tunables()
    assert_eq(pt.rotate_conn_threshold, 35)
    cm.set({cm.Keys.REMOTE_UNLOAD_DELAY_SEC: "12.5",
            cm.Keys.REMOTE_FAIL_THRESHOLD: "x!",
            cm.Keys.HEARTBEAT_TIMEOUT_SEC: "9"})
    rt2 = cm.remote_tunables()
    assert_eq(rt2.unload_delay_sec, 12.5, ".ai_env 优先")
    assert_eq(rt2.fail_threshold, 2, "非法回退默认")
    assert_eq(cm.heartbeat_tunables().timeout_sec, 9.0, "心跳参数生效")


@test("ConfigManager: 元数据——surface 过滤/分类/readonly/兜底")
def test_meta():
    from services.config_manager import Surface, ConfigCategory
    cm = _fresh()

    # config 面: 五分类有序，不含远程/系统面条目
    cfg = cm.config_meta(Surface.CONFIG)
    assert_eq([c.code for c in cfg.categories],
              ["tools", "models", "proxy", "behavior", "developer"], "config 面分类序")
    assert_true(cm.Keys.DEEPSEEK_API_KEY in cfg.entries, "常规键进 config 面")
    assert_true(cm.Keys.REFLECT_NUDGE_ENABLED in cfg.entries, "反思开关已声明")
    assert_eq(cfg.entries[cm.Keys.REFLECT_NUDGE_INTERVAL_MIN].default_value, "30",
              "反思间隔默认 30")
    assert_eq(cfg.entries[cm.Keys.REFLECT_NUDGE_ENABLED].category_desc, "行为",
              "分类描述服务端权威")
    for k in (cm.Keys.REMOTE_CONSOLE_URL, cm.Keys.CONTROL_API_KEY,
              cm.Keys.HEARTBEAT_TIMEOUT_SEC):
        assert_true(k not in cfg.entries, f"{k} 不进 config 面")
    # 代理池 5 调参进 config 面 proxy 分类且可写
    proxy_keys = [cm.Keys.JULIANG_IP_TTL_SEC, cm.Keys.JULIANG_TTL_MARGIN_SEC,
                  cm.Keys.PROXY_ROTATE_CONN_THRESHOLD, cm.Keys.DOMAIN_COOLDOWN_SEC,
                  cm.Keys.ROTATE_HISTORY_LIMIT]
    for k in proxy_keys:
        assert_eq(cfg.entries[k].category_code, "proxy", f"{k} 归代理分类")
        assert_eq(cfg.entries[k].readonly, False, f"{k} 可写")

    # remote 面: 连接三键 + 远程 6 调参; ENABLED/调参 readonly
    rem = cm.config_meta(Surface.REMOTE)
    assert_eq([c.code for c in rem.categories], ["remote", "remote_tuning"],
              "remote 面分类序")
    assert_eq(len(rem.entries), 9, "remote 面 9 条目")
    assert_eq(rem.entries[cm.Keys.REMOTE_CONSOLE_ENABLED].readonly, True,
              "ENABLED 只读")
    assert_eq(rem.entries[cm.Keys.REMOTE_HEARTBEAT_INTERVAL_SEC].readonly, True,
              "远程调参只读")
    assert_eq(rem.entries[cm.Keys.REMOTE_CONSOLE_URL].readonly, False, "URL 可写")
    assert_true(cm.Keys.CONTROL_API_KEY not in rem.entries, "节点侧键不进 remote 面")

    # hidden 面: 心跳 3 项 + 节点侧 3 键声明存在（surface=hidden 占位）
    assert_eq(len(cm.heartbeat_tunable_configs()), 3, "心跳调参 3 项")
    assert_eq(len(cm.node_side_configs()), 3, "节点侧 3 键")
    hb = cm.field_of(cm.Keys.HEARTBEAT_GRACE_SEC)
    assert_true(hb is not None and hb.surface == Surface.HIDDEN,
                "心跳键 hidden 占位")

    # 分类枚举: 顺序 + desc 全覆盖
    ordered = ConfigCategory.ordered()
    assert_eq(len(ordered), 9, "9 分类")
    assert_eq(ordered[0].value, "tools", "首分类 tools")
    for c in ordered:
        assert_true(c.desc, f"{c.value} 有描述")

    # 未知键兜底: 仅 config 面 OTHER 分类; remote 面不兜底
    cm.set({"SOME_UNKNOWN_KEY": "v"})
    cfg2 = cm.config_meta(Surface.CONFIG)
    assert_true("SOME_UNKNOWN_KEY" in cfg2.entries, "未知键 config 面兜底")
    assert_eq(cfg2.entries["SOME_UNKNOWN_KEY"].category_code, "other", "未知键归其他")
    assert_true("other" in [c.code for c in cfg2.categories], "其他分类出现")
    assert_true("SOME_UNKNOWN_KEY" not in cm.config_meta(Surface.REMOTE).entries,
                "未知键不进 remote 面")


@test("ConfigManager: 引导属性——dev_mode 优先级/is_windows/ipc_addr")
def test_bootstrap_props():
    from services.config_manager import ConfigManager
    cm = _fresh()
    assert_eq(cm.opensecurity_home, str(_DATA))
    assert_eq(cm.opencode_root, str(_SANDBOX))
    assert_true(isinstance(cm.is_windows, bool))
    assert_true(cm.ipc_addr().endswith(cm.Protocol.IPC_UNIX_SOCKET_NAME) or cm.is_windows)
    # env 兜底语义: .ai_env 未定义该键时 env 注入生效（CI/无文件环境通道;
    # 沙箱无 .ai_env → 本断言走兜底路径。文件定义时文件权威的完整语义
    # 见 test_control 的 test_dev_mode_default 四场景）
    os.environ[cm.Bootstrap.FRONTEND_DEV_ENV] = "1"
    ConfigManager._reset_for_tests()
    cm2 = ConfigManager.get_instance()
    assert_true(cm2.is_dev_mode, "env 兜底生效")
    del os.environ[cm.Bootstrap.FRONTEND_DEV_ENV]


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"config_manager 测试: {len(_tests)} 个\n")
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
