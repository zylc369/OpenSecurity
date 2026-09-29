"""model_lifecycle（ManagedModel/ModelWorker）单元测试。

覆盖（需求文档 §3.1 步骤 2 验证点）:
  1. 单飞加载: 并发 10 线程只 load 一次
  2. 排队卸载: 推理在途时 release 等推理完成后才 unload
  3. 空闲 reaper: 超时触发卸载 / 未启用时不触发
  4. 加载失败回 idle（下次调用重新加载）
  5. 状态快照字段（name/state/idle_sec/idle_timeout_sec/error）

运行方式:
  cd .opencode/control/backend
  python tests/test_model_lifecycle.py
"""
# pyright: reportMissingParameterType=false
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("OPENSECURITY_HOME", "/tmp/control_test_data")

from tests.test_control import test, assert_eq, assert_true, assert_false  # noqa: E402


def _make_model(**kwargs):
    """构造测试用 ManagedModel（计数器追踪 load/unload/infer）。"""
    from services.model_lifecycle import ManagedModel

    counter = {"load": 0, "unload": 0}

    def load_fn():
        counter["load"] += 1

    def unload_fn():
        counter["unload"] += 1

    m = ManagedModel(name=kwargs.pop("name", "test-model"),
                     load_fn=load_fn, unload_fn=unload_fn, **kwargs)
    return m, counter


@test("ManagedModel: 单飞加载——并发 10 线程只 load 一次")
def test_single_flight_load():
    m, counter = _make_model(name="sf")
    barrier = threading.Barrier(10)
    errors: list[str] = []

    def worker():
        try:
            barrier.wait()  # 同时起跑，最大化并发竞争
            m.ensure_loaded()
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert_eq(errors, [], "并发加载不应有异常")
    assert_eq(counter["load"], 1, "10 线程并发只应加载一次")
    assert_true(m.is_loaded(), "加载后 is_loaded=True")
    m.release()


@test("ManagedModel: 排队卸载——推理在途时 release 等推理完成后才 unload")
def test_queued_release():
    m, counter = _make_model(name="qr")
    order: list[str] = []
    infer_started = threading.Event()
    infer_gate = threading.Event()  # 闸门: 推理挂起直到测试放行

    def slow_infer():
        order.append("infer_start")
        infer_started.set()
        infer_gate.wait(timeout=10)  # 模拟长推理
        order.append("infer_end")
        return 42

    result: list = []
    t_infer = threading.Thread(
        target=lambda: result.append(m.run_inference(slow_infer)))
    t_infer.start()
    assert_true(infer_started.wait(timeout=5), "推理应已启动")

    t_release = threading.Thread(target=m.release)
    t_release.start()
    time.sleep(0.3)  # release 进入排队
    assert_eq(counter["unload"], 0, "推理在途时 unload 不得执行")
    assert_eq(order, ["infer_start"], "推理尚未结束")

    infer_gate.set()  # 放行推理
    t_infer.join(timeout=10)
    t_release.join(timeout=10)
    assert_eq(result[0], 42, "推理结果正确")
    assert_eq(order, ["infer_start", "infer_end"], "推理完整执行")
    assert_eq(counter["unload"], 1, "推理完成后 unload 执行一次")
    assert_false(m.is_loaded(), "卸载后 is_loaded=False")


@test("ManagedModel: 排队卸载后的再次推理自动重载")
def test_reload_after_release():
    m, counter = _make_model(name="rl")
    assert_eq(m.run_inference(lambda: "a"), "a")
    assert_eq(counter["load"], 1)
    m.release()
    assert_eq(counter["unload"], 1)
    assert_eq(m.run_inference(lambda: "b"), "b", "卸载后再推理自动重载")
    assert_eq(counter["load"], 2, "第二次加载发生")
    m.release()


@test("ManagedModel: 加载失败回 idle——下次调用重新加载")
def test_load_failure_recovers():
    from services.model_lifecycle import ManagedModel
    attempts = {"n": 0}

    def flaky_load():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("模拟首次加载失败")

    m = ManagedModel(name="flaky", load_fn=flaky_load, unload_fn=lambda: None)
    try:
        m.ensure_loaded()
        raise AssertionError("首次加载失败应抛 RuntimeError")
    except RuntimeError as e:
        assert_true("模拟首次加载失败" in str(e), f"异常信息应包含原因: {e}")
    assert_eq(m.state(), "idle", "失败后状态回 idle")
    assert_true(m.status().error is not None, "status.error 记录失败原因")

    m.ensure_loaded()  # 第二次成功
    assert_eq(m.state(), "ready")
    assert_true(m.status().error is None, "成功后 error 清除")
    m.release()


@test("ManagedModel: 空闲 reaper——超时自动卸载")
def test_idle_reaper_triggers():
    m, counter = _make_model(name="reaper", idle_timeout_sec=0.3, reaper_interval_sec=0.1)
    m.run_inference(lambda: 1)
    assert_true(m.is_loaded(), "推理后已加载")
    # 等待 reaper（0.3s 超时 + 0.1s 周期 + 余量）
    deadline = time.time() + 3
    while time.time() < deadline and not counter["unload"]:
        time.sleep(0.05)
    assert_eq(counter["unload"], 1, "空闲超时后 reaper 应卸载")
    assert_false(m.is_loaded(), "reaper 卸载后 is_loaded=False")


@test("ManagedModel: 未启用 reaper——长时间空闲不卸载")
def test_no_reaper_when_disabled():
    m, counter = _make_model(name="noreaper")
    m.run_inference(lambda: 1)
    time.sleep(0.5)  # 无 idle_timeout → 永不自动卸载
    assert_true(m.is_loaded(), "未启用 reaper 时保持加载")
    assert_eq(counter["unload"], 0)
    m.release()


@test("ManagedModel: status 快照字段完整")
def test_status_fields():
    from services.model_lifecycle import ManagedModel
    m, _ = _make_model(name="st", idle_timeout_sec=600)
    st = m.status()
    assert_eq(st.name, "st")
    assert_eq(st.state, ManagedModel.STATE_IDLE)
    assert_true(st.idle_sec is None, "未加载时 idle_sec=None")
    assert_eq(st.idle_timeout_sec, 600)
    assert_true(st.error is None)
    m.run_inference(lambda: 1)
    st = m.status()
    assert_eq(st.state, ManagedModel.STATE_READY)
    assert_true(st.idle_sec is not None and st.idle_sec >= 0, "加载后 idle_sec 有效")
    m.release()


@test("ManagedModel: release 幂等——重复调用无害")
def test_release_idempotent():
    m, counter = _make_model(name="idem")
    m.run_inference(lambda: 1)
    m.release()
    m.release()  # 第二次: 状态 idle 直接返回
    assert_eq(counter["unload"], 1, "重复 release 只卸载一次")


@test("ManagedModel: 加载在途时 release——等加载完成后卸载（不中断加载）")
def test_release_during_starting():
    m, counter = _make_model(name="rs")
    load_started = threading.Event()
    load_gate = threading.Event()

    original_load = m._load_fn  # noqa: SLF001 —— 测试注入闸门

    def gated_load():
        original_load()
        load_started.set()
        load_gate.wait(timeout=10)

    m._load_fn = gated_load  # noqa: SLF001

    t_load = threading.Thread(target=m.ensure_loaded)
    t_load.start()
    assert_true(load_started.wait(timeout=5), "加载应已进入执行段")

    t_release = threading.Thread(target=m.release)
    t_release.start()
    time.sleep(0.2)
    assert_eq(counter["unload"], 0, "加载在途时不得卸载")

    load_gate.set()
    t_load.join(timeout=10)
    t_release.join(timeout=10)
    assert_eq(counter["unload"], 1, "加载完成后卸载执行")
    assert_false(m.is_loaded(), "最终回到未加载")


@test("model_loader: ManagedModel 生命周期——卸载/重载/常驻壳/ready 语义")
def test_model_loader_lifecycle():
    import numpy as np
    from services.model_loader import ModelInferenceService

    class FakeST:
        def encode(self, texts, **kw):
            n = 1 if isinstance(texts, str) else len(texts)
            return np.zeros((n, 1024), dtype=np.float32)

    managed = ModelInferenceService.get_instance()._embedder_managed  # noqa: SLF001 —— 测试注入加载原语
    orig_load, orig_unload = managed._load_fn, managed._unload_fn  # noqa: SLF001

    def fake_load():
        ModelInferenceService.get_instance()._embedder = FakeST()  # noqa: SLF001  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)

    def fake_unload():
        ModelInferenceService.get_instance()._embedder = None  # noqa: SLF001

    managed._load_fn, managed._unload_fn = fake_load, fake_unload  # noqa: SLF001
    try:
        assert_false(ModelInferenceService.get_instance().is_models_ready(), "初始未就绪")
        shell_1 = ModelInferenceService.get_instance().get_embedder()
        assert_true(ModelInferenceService.get_instance().is_models_ready(), "加载后 ready")
        vecs = ModelInferenceService.get_instance().embed_batch_sync(["a", "b"])
        assert_eq((len(vecs), len(vecs[0])), (2, 1024), "fake 推理 1024 维")

        shell_2 = ModelInferenceService.get_instance().get_embedder()
        assert_true(shell_1 is shell_2, "壳常驻（两次 get 同一对象）")

        ModelInferenceService.get_instance().release_all_local()
        assert_false(ModelInferenceService.get_instance().is_models_ready(), "卸载后 ready=False")
        shell_3 = ModelInferenceService.get_instance().get_embedder()  # 重载
        assert_true(shell_1 is shell_3, "重载后壳不变（消费方长期持有安全）")
        assert_true(ModelInferenceService.get_instance().is_models_ready(), "重载后 ready")
        ModelInferenceService.get_instance().release_all_local()
    finally:
        managed._load_fn, managed._unload_fn = orig_load, orig_unload  # noqa: SLF001
        managed.release()


@test("model_loader: embed_sync 并发 8 线程压测（worker/锁双层串行无异常）")
def test_model_loader_concurrent_embed():
    import threading
    from services.model_loader import ModelInferenceService

    class FakeST:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self._lk = threading.Lock()

        def encode(self, texts, **kw):
            import numpy as np
            import time as _t
            with self._lk:
                self.active += 1
                self.peak = max(self.peak, self.active)
            _t.sleep(0.02)  # 拉宽并发窗口
            with self._lk:
                self.active -= 1
            n = 1 if isinstance(texts, str) else len(texts)
            return np.zeros((n, 1024), dtype=np.float32)

    managed = ModelInferenceService.get_instance()._embedder_managed  # noqa: SLF001
    orig_load, orig_unload = managed._load_fn, managed._unload_fn  # noqa: SLF001
    fake = FakeST()
    managed._load_fn = lambda: setattr(ModelInferenceService.get_instance(), "_embedder", fake)  # noqa: SLF001
    managed._unload_fn = lambda: setattr(ModelInferenceService.get_instance(), "_embedder", None)  # noqa: SLF001
    errors: list[str] = []
    try:
        def worker(i: int):
            try:
                vecs = ModelInferenceService.get_instance().embed_batch_sync([f"t{i}", f"x{i}"])
                assert len(vecs) == 2 and len(vecs[0]) == 1024
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert_eq(errors, [], f"8 线程并发不应有异常: {errors}")
        assert_eq(fake.peak, 1, f"推理并发峰值应恒为 1，实际 {fake.peak}")
        ModelInferenceService.get_instance().release_all_local()
    finally:
        managed._load_fn, managed._unload_fn = orig_load, orig_unload  # noqa: SLF001
        managed.release()


@test("model_loader 路由: OFF 态直通本地 / REMOTE 态走远程不加载本地 / 远程失败 fallback")
def test_remote_routing_and_fallback():
    import types
    import numpy as np
    from services.model_loader import ModelInferenceService
    from services.remote_client import RemoteUnavailable

    class FakeST:
        def encode(self, texts, **kw):
            if isinstance(texts, str):
                import numpy as np
                return np.zeros(1024, dtype=np.float32) + 7.0  # 单文本 1D
            import numpy as np
            return np.zeros((len(texts), 1024), dtype=np.float32) + 7.0

    managed = ModelInferenceService.get_instance()._embedder_managed  # noqa: SLF001 —— 测试注入加载原语
    orig_load, orig_unload = managed._load_fn, managed._unload_fn  # noqa: SLF001
    managed._load_fn = lambda: setattr(ModelInferenceService.get_instance(), "_embedder", FakeST())  # noqa: SLF001
    managed._unload_fn = lambda: setattr(ModelInferenceService.get_instance(), "_embedder", None)  # noqa: SLF001

    # fake remote_link stub 模块
    calls = {"remote": 0, "note": 0}
    stub = types.ModuleType("services.remote_link")
    stub_state = {"use_remote": False, "fail": False, "note": 0}

    class FakeRemoteClient:
        def embed(self, texts):
            calls["remote"] += 1
            n = 1 if isinstance(texts, str) else len(texts)
            return [[0.5] * 1024 for _ in range(n)]  # 标记远程结果

    class _FakeRL:
        @staticmethod
        def get_instance():
            return _FakeRL()
        def should_use_remote(self):
            return stub_state["use_remote"]
        def note_request_failure(self, reason):
            calls["note"] += 1
        def get_client(self):
            return _FailingClient() if stub_state["fail"] else FakeRemoteClient()
    setattr(stub, "RemoteLinkService", _FakeRL)  # 动态替换模块类（模块属性直赋值 pyright 不支持）

    def _install(use_remote: bool, fail: bool):
        stub_state["use_remote"] = use_remote
        stub_state["fail"] = fail
        # 双保险: sys.modules + services 包属性（from-import 优先取包属性）
        sys.modules["services.remote_link"] = stub
        import services
        services.remote_link = stub  # type: ignore[assignment]

    class _FailingClient:
        def embed(self, texts):
            calls["remote"] += 1
            raise RemoteUnavailable("模拟远程失效")

    real_mod = sys.modules.get("services.remote_link")
    try:
        # 场景 1: OFF 态（不注入 stub 时 _use_remote 异常回落 False——注入 False stub 更明确）
        _install(use_remote=False, fail=False)
        ModelInferenceService.get_instance().release_all_local()
        vec = ModelInferenceService.get_instance().embed_sync("hello")  # str 输入 → 1D
        assert_eq(len(vec), 1024, "OFF 态本地推理（1D）")
        assert_eq(vec[0], 7.0, "本地标记值")
        assert_eq(calls["remote"], 0, "OFF 态不触远程")
        assert_true(ModelInferenceService.get_instance().is_models_ready(), "OFF 态 ready=本地加载态")

        # 场景 2: REMOTE 态 → 远程推理、本地不加载
        ModelInferenceService.get_instance().release_all_local()
        _install(use_remote=True, fail=False)
        vec = ModelInferenceService.get_instance().embed_sync("hello")
        assert_eq(len(vec), 1024, "REMOTE 态返回 1D")
        assert_eq(vec[0], 0.5, "远程标记值")
        assert_eq(calls["remote"], 1, "REMOTE 态触远程一次")
        assert_false(managed.is_loaded(), "REMOTE 态本地不加载")
        assert_true(ModelInferenceService.get_instance().is_models_ready(), "REMOTE 态 ready=True（远程即服务）")

        vecs = ModelInferenceService.get_instance().embed_batch_sync(["a", "b"])
        assert_eq((len(vecs), len(vecs[0])), (2, 1024), "批量形状")

        # 场景 3: REMOTE 态 + 远程失效 → fallback 本地（HOLD 加载）+ note 被调
        _install(use_remote=True, fail=True)
        vec = ModelInferenceService.get_instance().embed_sync("hello")
        assert_eq(vec[0], 7.0, "fallback 后本地标记值")
        assert_eq(calls["note"], 1, "note_request_failure 被调用")
        assert_true(managed.is_loaded(), "fallback 触发本地加载（HOLD 语义）")
    finally:
        if real_mod is not None:
            sys.modules["services.remote_link"] = real_mod
            import services
            services.remote_link = real_mod  # type: ignore[assignment]
        else:
            sys.modules.pop("services.remote_link", None)
            import services
            if hasattr(services, "remote_link"):
                del services.remote_link  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
        managed._load_fn, managed._unload_fn = orig_load, orig_unload  # noqa: SLF001
        managed.release()


@test("model_loader 路由: rerank 同构（远程/失败回退）")
def test_remote_routing_rerank():
    import types
    import numpy as np
    from services.model_loader import ModelInferenceService
    from services.remote_client import RemoteUnavailable

    class FakeCE:
        def predict(self, pairs, **kw):
            return np.zeros(len(pairs), dtype=np.float32) + 9.0

    managed = ModelInferenceService.get_instance()._reranker_managed  # noqa: SLF001
    orig_load, orig_unload = managed._load_fn, managed._unload_fn  # noqa: SLF001
    managed._load_fn = lambda: setattr(ModelInferenceService.get_instance(), "_reranker", FakeCE())  # noqa: SLF001
    managed._unload_fn = lambda: setattr(ModelInferenceService.get_instance(), "_reranker", None)  # noqa: SLF001

    calls = {"note": 0}
    stub = types.ModuleType("services.remote_link")
    rl_state = {"fail": False}

    class OkClient:
        def rerank(self, query, texts):
            return [0.25] * len(texts)

    class FailClient:
        def rerank(self, query, texts):
            raise RemoteUnavailable("rerank 远程失效")

    class _FakeRL:
        @staticmethod
        def get_instance():
            return _FakeRL()
        def should_use_remote(self):
            return True
        def note_request_failure(self, reason):
            calls["note"] += 1
        def get_client(self):
            return FailClient() if rl_state["fail"] else OkClient()
    setattr(stub, "RemoteLinkService", _FakeRL)  # 动态替换模块类（模块属性直赋值 pyright 不支持）

    real_mod = sys.modules.get("services.remote_link")
    try:
        sys.modules["services.remote_link"] = stub
        import services
        services.remote_link = stub  # type: ignore[assignment]
        scores = ModelInferenceService.get_instance().rerank_sync("q", ["p1", "p2"])
        assert_eq(list(scores), [0.25, 0.25], "远程 rerank 分数")
        assert_false(managed.is_loaded(), "远程态 reranker 本地不加载")

        rl_state["fail"] = True
        scores = ModelInferenceService.get_instance().rerank_sync("q", ["p1", "p2"])
        assert_eq([float(s) for s in scores], [9.0, 9.0], "fallback 本地 rerank")
        assert_eq(calls["note"], 1, "note 被调用")
        assert_true(managed.is_loaded(), "fallback 触发本地加载")
    finally:
        if real_mod is not None:
            sys.modules["services.remote_link"] = real_mod
            import services
            services.remote_link = real_mod  # type: ignore[assignment]
        else:
            sys.modules.pop("services.remote_link", None)
            import services
            if hasattr(services, "remote_link"):
                del services.remote_link  # pyright: ignore[reportAttributeAccessIssue]  (测试动态 patch/fake 注入)
        managed._load_fn, managed._unload_fn = orig_load, orig_unload  # noqa: SLF001
        managed.release()


@test("ManagedModel: 加载挂死兜底——load_fn 永不完成时等待者超时转可见异常")
def test_load_hang_timeout():
    import threading
    from services.model_lifecycle import ManagedModel
    gate = threading.Event()

    def hang_load():
        gate.wait(timeout=30)  # 模拟底层运行时挂死（如 MLX Metal eval 死锁）

    m = ManagedModel(name="hang", load_fn=hang_load, unload_fn=lambda: None)
    orig_timeout = ManagedModel.LOAD_WAIT_TIMEOUT_SEC
    ManagedModel.LOAD_WAIT_TIMEOUT_SEC = 1.0  # 测试注入小超时
    try:
        try:
            m.ensure_loaded()
            raise AssertionError("挂死加载应抛超时 RuntimeError")
        except RuntimeError as e:
            assert_true("超时" in str(e) and "挂死" in str(e), f"异常应含超时与挂死语义: {e}")
        # 恢复底层（释放挂起的 load 线程），状态可自愈
        gate.set()
    finally:
        ManagedModel.LOAD_WAIT_TIMEOUT_SEC = orig_timeout
        import time as _t
        _t.sleep(0.2)
        m.release()


if __name__ == "__main__":
    # 与 test_control.py 同款收集逻辑（本文件注册的测试）
    _tests = [(n, f) for n, f in globals().items()
              if callable(f) and getattr(f, "_is_test", False)]
    print(f"model_lifecycle 测试: {len(_tests)} 个\n")
    for _name, _fn in _tests:
        _fn()
    from tests.test_control import _results
    _passed = sum(1 for _, ok, _ in _results if ok)
    _failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"\n通过 {_passed} / 失败 {_failed} / 总计 {len(_results)}")
    if _failed:
        for _n, ok, _msg in _results:
            if not ok:
                print(f"  ✗ {_n}: {_msg}")
        sys.exit(1)
