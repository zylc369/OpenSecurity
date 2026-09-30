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
from services.config_manager import Surface  # noqa: E402

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


@test("ConfigManager: get_kv_list——场景生效值 KV（默认值唯一权威）")
def test_get_kv_list():
    cm = _fresh()
    # 未配置声明键 → 声明默认值
    eff = cm.get_kv_list(Surface.CONFIG)
    assert_eq(eff.get(cm.Keys.PERMISSION_ASK_TIMEOUT_SEC), "300", "未配置回退默认")
    assert_eq(eff.get(cm.Keys.REFLECT_NUDGE_ENABLED), "1", "开关键默认开启")
    assert_eq(eff.get(cm.Keys.RESUME_ANALYSIS_ENABLED), "1", "续传开关默认开启")
    # tunables 声明默认同样融合（值接口输出面含未配置调参的默认值）
    assert_eq(eff.get(cm.Keys.JULIANG_IP_TTL_SEC), "300.0", "tunables 默认融合")
    # 无默认且未配置 → 不出现
    assert_true(cm.Keys.IDA_PRO_HOME not in eff, "无默认未配置不出现")
    # 场景隔离: config 场景不含 remote/hidden 键
    assert_true(cm.Keys.REMOTE_CONSOLE_URL not in eff, "config 场景不含 remote 键")
    assert_true(cm.Keys.HEARTBEAT_TIMEOUT_SEC not in eff, "config 场景不含 hidden 键")
    # remote 场景 KV: 不含 config 键; 有默认的远程键融合、用户配置的远程键出现
    rem = cm.get_kv_list(Surface.REMOTE)
    assert_true(cm.Keys.DEEPSEEK_API_KEY not in rem, "remote 场景不含 config 键")
    assert_eq(rem.get(cm.Keys.REMOTE_HEARTBEAT_INTERVAL_SEC), "5.0",
              "remote tunables 默认融合（在其声明场景内）")
    cm.set({cm.Keys.REMOTE_CONSOLE_URL: "http://x"})
    assert_true(cm.Keys.REMOTE_CONSOLE_URL in cm.get_kv_list(Surface.REMOTE),
                "配置后远程键进入 remote 场景 KV")
    # 配置值优先于默认
    cm.set({cm.Keys.PERMISSION_ASK_TIMEOUT_SEC: "60"})
    assert_eq(cm.get_kv_list(Surface.CONFIG)[cm.Keys.PERMISSION_ASK_TIMEOUT_SEC], "60", "配置值优先")
    # 空串配置 → 回退默认（清空=回到默认的语义）
    cm.set({cm.Keys.PERMISSION_ASK_TIMEOUT_SEC: ""})
    assert_eq(cm.get_kv_list(Surface.CONFIG)[cm.Keys.PERMISSION_ASK_TIMEOUT_SEC], "300", "空串回退默认")
    # 未声明的手写键非空 → 保留
    cm.set({"SOME handwritten_KEY": "v"})
    assert_eq(cm.get_kv_list(Surface.CONFIG).get("SOME handwritten_KEY"), "v", "手写键保留")
    # 手写键空串 → 不出现
    cm.set({"EMPTY_HANDWRITTEN": ""})
    assert_true("EMPTY_HANDWRITTEN" not in cm.get_kv_list(Surface.CONFIG), "空手写键不出现")
    # 非法配置值在构建层校验回落（validator 失败→日志+声明默认; 无默认→空）
    cm.set({cm.Keys.DEEPSEEK_API_KEY: "short"})
    assert_true(cm.get_kv_list(Surface.CONFIG).get(cm.Keys.DEEPSEEK_API_KEY, "") == "",
                "非法 required 值回落空（无声明默认; 记日志）")
    # validator 结果缓存: 同 (key, value) 二次读取不再重跑校验（缓存命中）
    assert_true((cm.Keys.DEEPSEEK_API_KEY, "short") in cm._validation_cache,
                "非法结果进入校验缓存")
    cache_len = len(cm._validation_cache)
    cm.get_kv_list(Surface.CONFIG)
    cm.get_entries()  # 再读两遍
    assert_eq(len(cm._validation_cache), cache_len, "同 (key,value) 命中缓存不重跑")
    # get() 单键: 非法值回落默认后 → None（视同未配置）
    assert_true(cm.get(cm.Keys.DEEPSEEK_API_KEY) is None, "get() 非法回落→None")


@test("ConfigManager: path 归一化 + validator 链（~/ 展开/通过/回落）")
def test_path_normalization():
    import tempfile
    cm = _fresh()
    from pathlib import Path as _P
    # 正向链: 真目录 + idat → ~/ 展开归一化 + validator 通过
    with tempfile.TemporaryDirectory() as td:
        ida_dir = _P(td) / "ida"
        ida_dir.mkdir()
        (ida_dir / "idat").touch()
        old_home = os.environ.get("HOME")
        try:
            os.environ["HOME"] = td
            cm.set({cm.Keys.IDA_PRO_HOME: "~/ida"})
            assert_eq(cm.get_kv_list(Surface.CONFIG).get(cm.Keys.IDA_PRO_HOME),
                      str(ida_dir), "~/ 展开归一化且 validator 通过")
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home
            else:
                os.environ.pop("HOME", None)
    # 负向链: 目录不存在 → validator 失败回落默认（kv 不含, 原因在日志）
    cm.set({cm.Keys.IDA_PRO_HOME: "~/not_exist_dir_xyz"})
    assert_true(cm.Keys.IDA_PRO_HOME not in cm.get_kv_list(Surface.CONFIG),
                "目录不存在→validator 失败回落空")
    # 未声明手写键不做归一化（无类型元数据）
    cm.set({"HANDWRITTEN_PATH_LIKE": "~/raw"})
    assert_eq(cm.get_kv_list(Surface.CONFIG).get("HANDWRITTEN_PATH_LIKE"),
              "~/raw", "手写键不归一化")


@test("ConfigManager: required_status——三态 + 场景过滤")
def test_required_status_states():
    cm = _fresh()
    # 未配置 → ok False
    st = {c.key: c for c in cm.required_status(Surface.CONFIG)}
    assert_true(cm.Keys.DEEPSEEK_API_KEY in st, "必要键在列")
    assert_true(not st[cm.Keys.DEEPSEEK_API_KEY].ok, "未配置 ok=False")
    # 配置合法 → ok True
    cm.set({cm.Keys.DEEPSEEK_API_KEY: "sk-abc123def456"})
    st = {c.key: c for c in cm.required_status(Surface.CONFIG)}
    assert_true(st[cm.Keys.DEEPSEEK_API_KEY].ok, "合法配置 ok=True")
    # 非法值（validator 失败回落空）→ ok False（等同缺失; 原因在日志）
    cm.set({cm.Keys.DEEPSEEK_API_KEY: "short"})
    st = {c.key: c for c in cm.required_status(Surface.CONFIG)}
    assert_true(not st[cm.Keys.DEEPSEEK_API_KEY].ok, "非法回落空 ok=False")
    # 场景过滤: 必要键全在 config 场景 → remote 场景为空
    assert_eq(len(cm.required_status(Surface.REMOTE)), 0, "remote 场景无必要键")


@test("ConfigManager: get_entries——序列场景参数（多场景并集）")
def test_get_entries_surface_sequence():
    cm = _fresh()
    both = cm.get_entries(surfaces=[Surface.CONFIG, Surface.REMOTE])
    keys = {e.key for e in both}
    assert_true(cm.Keys.DEEPSEEK_API_KEY in keys, "并集含 config 键")
    assert_true(cm.Keys.REMOTE_CONSOLE_URL in keys, "并集含 remote 键")
    assert_true(cm.Keys.HEARTBEAT_TIMEOUT_SEC not in keys, "并集不含 hidden 键")
    single = cm.get_entries(surfaces=Surface.REMOTE)
    assert_true(all(Surface.REMOTE in e.surfaces for e in single), "单值参数等价")


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
    assert_true(cm.Keys.PERMISSION_ASK_TIMEOUT_SEC in cfg.entries, "权限超时键已声明")
    assert_eq(cfg.entries[cm.Keys.PERMISSION_ASK_TIMEOUT_SEC].default_value, "300",
              "权限超时默认 300 秒")
    assert_eq(cfg.entries[cm.Keys.PERMISSION_ASK_TIMEOUT_SEC].category_code, "behavior",
              "权限超时归行为分类")
    assert_eq(cfg.entries[cm.Keys.PERMISSION_ASK_TIMEOUT_TYPES].default_value,
              "external_directory", "权限类型默认 external_directory")
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

    # hidden 场景: 心跳 3 项 + 节点侧 3 键（静态 _FIELDS 的 surfaces 数组归属）
    hidden = cm.get_entries(surfaces=Surface.HIDDEN)
    assert_eq(len([e for e in hidden
                   if e.key in {cm.Keys.HEARTBEAT_TIMEOUT_SEC,
                                       cm.Keys.HEARTBEAT_SWEEP_INTERVAL_SEC,
                                       cm.Keys.HEARTBEAT_GRACE_SEC}]), 3, "心跳调参 3 项")
    assert_eq(len([e for e in hidden
                   if e.key in {cm.Keys.CONTROL_API_KEY,
                                       cm.Keys.CONTROL_RESIDENT,
                                       cm.Keys.CONTROL_AUTOSTART}]), 3, "节点侧 3 键")
    hb = cm.field_of(cm.Keys.HEARTBEAT_GRACE_SEC)
    assert_true(hb is not None and Surface.HIDDEN in hb.surfaces,
                "心跳键 hidden 场景归属")

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
