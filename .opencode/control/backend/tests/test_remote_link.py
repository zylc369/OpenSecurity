"""remote_link 状态机单元测试（fake client + 小阈值 env，不发真网络/不写真实 .ai_env）。

覆盖（需求文档 §3.1 步骤 10 验证点）:
  1. 连续失败 → 降级 + 预热触发
  2. 连续成功 → 恢复 + 延迟卸载安排 + 稳定期后执行卸载
  3. 恢复稳定期内再降级 → 取消卸载
  4. switch_to_remote: 校验失败不置位 / 成功置位 ENABLED
  5. switch_to_local: OFF + 本地模型不卸载
  6. reload_config: 重建 client
  7. 独立日志文件（remote-link.log）且不进 control.log

运行方式:
  cd .opencode/control/backend
  python tests/test_remote_link.py
"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ["TEST_OPENSECURITY_HOME"] = "/tmp/control_test_rl"  # #7 约定: 沙箱根经 TEST_ 变量表达（import test_control 后由它落 OPENSECURITY_HOME）
Path("/tmp/control_test_rl", "logs").mkdir(parents=True, exist_ok=True)
# 参数沙箱: 小阈值写 .ai_env（可调参数唯一通道是 config_store——无 env 第二套）
RL_TEST_ROOT = Path("/tmp/control_test_rl_root")
RL_TEST_ROOT.mkdir(parents=True, exist_ok=True)
(RL_TEST_ROOT / ".ai_env").write_text("\n".join([
    "# remote_link 测试小值（加速阈值/计时验证）",
    "REMOTE_HEARTBEAT_INTERVAL_SEC=0.05",
    "REMOTE_FAIL_THRESHOLD=2",
    "REMOTE_RECOVER_THRESHOLD=3",
    "REMOTE_UNLOAD_DELAY_SEC=0.5",
    "REMOTE_INFER_TIMEOUT_SEC=2",
    "REMOTE_PROBE_TIMEOUT_SEC=1",
]) + "\n")
os.environ["OPENCODE_ROOT"] = str(RL_TEST_ROOT)

from tests.test_control import test, assert_eq, assert_true  # noqa: E402

from services import remote_link as rl_module  # noqa: E402
from services.remote_client import RemoteHealthInfo, ModelFingerprint  # noqa: E402


def _mk_service(url="http://fake.remote:1", enabled=True, token="tok123"):
    """构造隔离的 RemoteLinkService（fake 配置 + 可控探测）。"""
    svc = rl_module.RemoteLinkService()
    rl_module.RemoteLinkService.get_instance()._read_config = lambda: (url, enabled, token)  # noqa: F811 —— 测试注入
    svc.reload_config()
    return svc


def _ok_info(latency=12.5):
    return RemoteHealthInfo(
        service="opencode-control", version="t",
        models=[ModelFingerprint("BAAI/bge-m3", "snap-abc", True)], latency_ms=latency)


def _set_probe(svc, results):
    """注入探测结果序列（元素: RemoteHealthInfo 或 Exception 字符串）。"""
    seq = list(results)

    async def fake_probe():
        if not seq:
            return (True, "", _ok_info())
        r = seq.pop(0)
        if isinstance(r, str):
            return (False, r, None)
        return (True, "", r)

    svc._probe_raw = fake_probe  # noqa: SLF001 —— 测试注入


async def _pump(svc, n: int):
    for _ in range(n):
        await svc._probe_once()  # noqa: SLF001


@test("remote_link: 初始评估——单次成功定态 REMOTE")
def test_initial_ok():
    async def run():
        svc = _mk_service()
        _set_probe(svc, [_ok_info()])
        await _pump(svc, 1)
        assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_REMOTE, "单次成功 → REMOTE")
        assert_true(svc.should_use_remote(), "路由开启")
    asyncio.run(run())


@test("remote_link: 连续 2 次失败 → DEGRADED + 预热触发")
def test_degrade_on_failures():
    async def run():
        # 预热验证: 只替换 _model_inference 返回桩（真 _warm_local 保持原样——
        # 曾因整体替换 _warm_local 掩盖了 staticmethod 引用 self 的必炸 bug）。
        # patch/还原必须 staticmethod 包装对称: 类属性读取会脱壳成普通函数，
        # 裸还原会破坏 staticmethod 语义（实例调用绑定 self → TypeError）
        warm_calls = []
        stub = type("StubMI", (), {"preload_all_models_background": staticmethod(
            lambda: warm_calls.append(1))})()
        orig_mi = rl_module.RemoteLinkService.__dict__["_model_inference"]
        rl_module.RemoteLinkService._model_inference = staticmethod(lambda: stub)  # noqa: SLF001  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
        svc = _mk_service()
        _set_probe(svc, [_ok_info()])
        await _pump(svc, 1)
        assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_REMOTE)

        _set_probe(svc, ["fail-1", "fail-2"])
        await _pump(svc, 2)
        st = svc.status()
        assert_eq(st.state, rl_module.RemoteLinkService.STATE_DEGRADED, "2 连败 → DEGRADED")
        assert_true("fail-2" in (st.last_fail_reason or ""), "记录失败原因")
        assert_false_fn = st.fail_streak
        assert_eq(assert_false_fn, 2, "fail_streak=2")
        rl_module.RemoteLinkService._model_inference = orig_mi  # noqa: SLF001
        assert_true(len(warm_calls) == 1, f"预热触发一次，实际 {len(warm_calls)}")
        assert_true(not svc.should_use_remote(), "路由关闭（本地兜底）")
    asyncio.run(run())


@test("remote_link: DEGRADED 后连续 3 次成功 → 恢复 + 稳定期后卸载")
def test_recover_and_unload():
    async def run():
        released = []
        from services.model_loader import ModelInferenceService
        from services.ocr_service import OcrService
        _svc = ModelInferenceService.get_instance()
        _osvc = OcrService.get_instance()
        orig_ml, orig_ocr = _svc.release_all_local, _osvc.release_sync
        _svc.release_all_local = lambda: released.append("ml")  # type: ignore[method-assign]
        _osvc.release_sync = lambda: released.append("ocr")  # type: ignore[method-assign]
        try:
            svc = _mk_service()
            _set_probe(svc, ["f1", "f2"])
            await _pump(svc, 2)
            assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_DEGRADED)

            _set_probe(svc, [_ok_info(), _ok_info(), _ok_info()])
            await _pump(svc, 3)
            st = svc.status()
            assert_eq(st.state, rl_module.RemoteLinkService.STATE_REMOTE, "3 连胜 → 恢复")
            assert_true(st.unload_countdown_sec is not None and st.unload_countdown_sec > 0,
                        "稳定期倒计时已安排")

            await asyncio.sleep(0.7)  # 等稳定期（0.5s）到期执行卸载
            assert_eq(released, ["ml", "ocr"], "稳定期后卸载三模型")
            assert_true(svc.status().unload_countdown_sec is None, "卸载后无倒计时")
        finally:
            _svc.release_all_local = orig_ml
            _osvc.release_sync = orig_ocr
    asyncio.run(run())


@test("remote_link: 恢复稳定期内再降级 → 取消卸载")
def test_cancel_unload_on_redegrade():
    async def run():
        released = []
        from services.model_loader import ModelInferenceService
        from services.ocr_service import OcrService
        _svc = ModelInferenceService.get_instance()
        _osvc = OcrService.get_instance()
        orig_ml, orig_ocr = _svc.release_all_local, _osvc.release_sync
        _svc.release_all_local = lambda: released.append("ml")  # type: ignore[method-assign]
        _osvc.release_sync = lambda: released.append("ocr")  # type: ignore[method-assign]
        try:
            svc = _mk_service()
            _set_probe(svc, ["f1", "f2"])
            await _pump(svc, 2)

            _set_probe(svc, [_ok_info(), _ok_info(), _ok_info()])
            await _pump(svc, 3)
            assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_REMOTE)

            # 稳定期内（0.5s 未到）再降级
            _set_probe(svc, ["x1", "x2"])
            await _pump(svc, 2)
            assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_DEGRADED, "稳定期内降级")

            await asyncio.sleep(0.8)  # 越过原稳定期时刻
            assert_eq(released, [], "卸载被取消（未执行）")
        finally:
            _svc.release_all_local = orig_ml
            _osvc.release_sync = orig_ocr
    asyncio.run(run())


@test("remote_link: 请求级失败反馈达阈值同样触发降级")
def test_note_request_failure():
    svc = _mk_service()
    # 先置 REMOTE（绕过探测直接改状态——单元测试白盒）
    svc._state = rl_module.RemoteLinkService.STATE_REMOTE  # noqa: SLF001
    svc.note_request_failure("请求级失败-1")
    assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_REMOTE, "1 次未达阈值")
    svc.note_request_failure("请求级失败-2")
    assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_DEGRADED, "2 次请求级失败 → 降级")


@test("remote_link: switch_to_remote 校验失败不置位 / 成功置位")
def test_switch_to_remote():
    import services.config_manager as cs
    written = {}
    _cmi = cs.ConfigManager.get_instance()
    orig_write = _cmi.set_one
    _cmi.set_one = lambda k, v: written.update({k: v}) or {}  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        async def run():
            svc = _mk_service()
            # 校验失败
            _set_probe(svc, ["boom"])
            r = await svc.switch_to_remote()
            assert_true(not r.ok, "校验失败 ok=False")
            assert_true("boom" in r.error, f"error 含原因: {r.error}")
            assert_eq(written, {}, "校验失败不写 ENABLED")

            # 校验成功（版本指纹一致——fake snapshot 与本地对比可能不一致 → 只警告）
            _set_probe(svc, [])
            r = await svc.switch_to_remote()
            assert_true(r.ok, f"校验成功 ok=True: {r.error}")
            assert_eq(written.get("REMOTE_CONSOLE_ENABLED"), "1", "成功写 ENABLED=1")
            assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_REMOTE, "切换后 REMOTE")
        asyncio.run(run())
    finally:
        _cmi.set_one = orig_write


@test("remote_link: switch_to_local → OFF 且不触发卸载")
def test_switch_to_local():
    import services.config_manager as cs
    written = {}
    _cmi = cs.ConfigManager.get_instance()
    orig_write = _cmi.set_one
    _cmi.set_one = lambda k, v: written.update({k: v}) or {}  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
    try:
        svc = _mk_service()
        svc._state = rl_module.RemoteLinkService.STATE_REMOTE  # noqa: SLF001
        svc._schedule_unload_locked()  # noqa: SLF001 —— 安排一个卸载
        r = svc.switch_to_local()
        assert_true(r.ok)
        assert_eq(written.get("REMOTE_CONSOLE_ENABLED"), "0", "写 ENABLED=0")
        assert_eq(svc.status().state, rl_module.RemoteLinkService.STATE_OFF, "状态 OFF")
        assert_true(svc.status().unload_countdown_sec is None, "卸载被取消")
    finally:
        _cmi.set_one = orig_write


@test("remote_link: reload_config 重建 client + 计数清零")
def test_reload_config():
    svc = _mk_service(url="http://first:1")
    old_client = svc._client  # noqa: SLF001
    svc._fail_streak = 5  # noqa: SLF001
    rl_module.RemoteLinkService.get_instance()._read_config = lambda: ("http://second:2", True, "newtok")  # noqa: F811
    svc.reload_config()
    assert_true(svc._client is not old_client, "client 已重建")  # noqa: SLF001
    assert_eq(svc._client_url, "http://second:2", "URL 更新")  # noqa: SLF001
    assert_eq(svc._fail_streak, 0, "计数清零")  # noqa: SLF001


@test("remote_link: 独立日志文件且不进 control.log")
def test_independent_log():
    svc = _mk_service()
    svc.note_request_failure("独立日志验证行")
    time.sleep(0.2)  # 日志 flush
    rl_log = Path("/tmp/control_test_rl/logs/remote-link.log")
    assert_true(rl_log.exists(), "remote-link.log 存在")
    assert_true("独立日志验证行" in rl_log.read_text(), "内容写入独立文件")
    ctl = Path("/tmp/control_test_rl/logs/control.log")
    assert_true(not ctl.exists() or "独立日志验证行" not in ctl.read_text(),
                "control.log 不含 remote_link 行")


if __name__ == "__main__":
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"remote_link 测试: {len(_tests)} 个\n")
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
