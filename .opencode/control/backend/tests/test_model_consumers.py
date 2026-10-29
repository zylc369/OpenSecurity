"""模型消费方闭环守卫（known_ids 的每一项必须有真实消费方）。

防线对应的真实故障形态:
  • idle 接线缺失: `--model-idle-sec <id>=X` 校验放行但无人消费
    （设置成功、行为不生效——参数成摆设）
  • load/unload 分发缺失: 新增 id 未接入 model_ops 时按钮静默无效

新增模型 id 时必须同步改动: model_policy 表 / 消费服务接线 / 本测试。
"""
from __future__ import annotations

import pytest

from services import model_loader, model_ops, model_policy, ocr_service, tts_service
from services.model_loader import ModelInferenceService
from services.ocr_service import OcrService
from services.tts_service import TtsService

PROBE_SEC = 77.0


class _FakeModelSvc:
    """伪造 ModelInferenceService（记录调用序列）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_sync(self, _text: str) -> None:
        self.calls.append("embed_sync")

    def rerank_sync(self, _query: str, _passages: "list[str]") -> None:
        self.calls.append("rerank_sync")

    def release_embedder(self) -> None:
        self.calls.append("release_embedder")

    def release_reranker(self) -> None:
        self.calls.append("release_reranker")


class _FakeOcrSvc:
    """伪造 OcrService（记录调用序列）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def warm_up_sync(self) -> None:
        self.calls.append("warm_up_sync")

    def release_sync(self) -> None:
        self.calls.append("release_sync")


class _FakeTtsSvc:
    """伪造 TtsService（ready 恒真——mock 场景下 load 的远程就绪判定不阻断）。"""

    ready = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def warmup(self) -> None:
        self.calls.append("warmup")

    def release(self) -> None:
        self.calls.append("release")


@pytest.fixture(autouse=True)
def _clean_policy():
    model_policy.reset_overrides_for_tests()
    yield
    model_policy.reset_overrides_for_tests()


def test_known_ids_shape() -> None:
    assert model_policy.known_ids() == frozenset(
        {"bge-m3", "bge-reranker-v2-m3", "glm-ocr", "cosyvoice3-8bit"})


def test_idle_wiring_bge_m3() -> None:
    """override 后重建服务: embedder 接线必须取到策略值（而非硬编码/缺省 None）。"""
    model_policy.apply_idle_override("bge-m3", PROBE_SEC)
    ModelInferenceService._reset_for_tests()
    try:
        inst = ModelInferenceService.get_instance()
        assert inst._embedder_managed._idle_timeout_sec == PROBE_SEC, (
            "bge-m3 idle 策略未接入 ManagedModel——--model-idle-sec 将无声失效")
    finally:
        ModelInferenceService._reset_for_tests()


def test_idle_wiring_reranker() -> None:
    model_policy.apply_idle_override("bge-reranker-v2-m3", PROBE_SEC)
    ModelInferenceService._reset_for_tests()
    try:
        inst = ModelInferenceService.get_instance()
        assert inst._reranker_managed._idle_timeout_sec == PROBE_SEC, (
            "bge-reranker-v2-m3 idle 策略未接入 ManagedModel")
    finally:
        ModelInferenceService._reset_for_tests()


def test_idle_wiring_ocr() -> None:
    model_policy.apply_idle_override("glm-ocr", PROBE_SEC)
    OcrService._reset_for_tests()
    try:
        inst = OcrService.get_instance()
        inst._model()  # 触发惰性 ManagedModel 构造（构造时读取策略）
        assert inst._managed is not None
        assert inst._managed._idle_timeout_sec == PROBE_SEC, (
            "glm-ocr idle 策略未接入 ManagedModel")
    finally:
        OcrService._reset_for_tests()


def test_load_dispatch_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """四个 id 的 load 分发到对应服务的对应方法（防新增 id 漏分支/走错分支）。"""
    e, o, t2 = _FakeModelSvc(), _FakeOcrSvc(), _FakeTtsSvc()
    monkeypatch.setattr(model_loader.ModelInferenceService, "get_instance",
                        classmethod(lambda cls: e))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)
    monkeypatch.setattr(ocr_service.OcrService, "get_instance",
                        classmethod(lambda cls: o))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)
    monkeypatch.setattr(tts_service.TtsService, "get_instance",
                        classmethod(lambda cls: t2))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)

    model_ops.load("bge-m3")
    assert e.calls == ["embed_sync"]
    e.calls.clear()
    model_ops.load("bge-reranker-v2-m3")
    assert e.calls == ["rerank_sync"]
    model_ops.load("glm-ocr")
    assert o.calls == ["warm_up_sync"]
    model_ops.load("cosyvoice3-8bit")
    assert t2.calls == ["warmup"]


def test_unload_dispatch_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """四个 id 的 unload 分发到对应释放方法。"""
    e, o, t2 = _FakeModelSvc(), _FakeOcrSvc(), _FakeTtsSvc()
    monkeypatch.setattr(model_loader.ModelInferenceService, "get_instance",
                        classmethod(lambda cls: e))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)
    monkeypatch.setattr(ocr_service.OcrService, "get_instance",
                        classmethod(lambda cls: o))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)
    monkeypatch.setattr(tts_service.TtsService, "get_instance",
                        classmethod(lambda cls: t2))  # pyright: ignore[reportUnknownArgumentType]  (测试 fake 注入)

    model_ops.unload("bge-m3")
    assert e.calls == ["release_embedder"]
    e.calls.clear()
    model_ops.unload("bge-reranker-v2-m3")
    assert e.calls == ["release_reranker"]
    model_ops.unload("glm-ocr")
    assert o.calls == ["release_sync"]
    model_ops.unload("cosyvoice3-8bit")
    assert t2.calls == ["release"]


def test_unknown_id_rejected() -> None:
    with pytest.raises(KeyError):
        model_ops.load("nope")
    with pytest.raises(KeyError):
        model_ops.unload("nope")


def test_tts_ready_avoids_locked_remote_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """ready 的远程判定必须走无锁属性。

    真实故障形态: status() 持远程锁采集模型态 → TTS.ready → 加锁判定接口
    重复获同一把非重入锁 → 自死锁（/api/models 轮询全挂, TTS worker 不活时必现）。
    """
    from services import remote_link as rl
    locked_called: list[int] = []

    def _spy_locked(self: rl.RemoteLinkService) -> bool:
        locked_called.append(1)
        return False

    monkeypatch.setattr(rl.RemoteLinkService, "should_use_remote", _spy_locked)
    monkeypatch.setattr(rl.RemoteLinkService, "is_remote_active",
                        property(lambda self: True))  # pyright: ignore[reportArgumentType,reportAny]  (测试属性注入)
    svc = TtsService()  # worker 不活（未启动）
    assert svc.ready is True  # 经无锁属性判定远程可用
    assert locked_called == [], "ready 走了加锁判定（status 锁内自死锁回归）"
