# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""质检流程行为测试（提前交付稳定键 / 高风险文本跳过质检）。

防线对应的真实故障形态:
  • 提前交付失效: 失败句集合含浮动 per（'…(per=59%)' vs '…(per=54%)'）
    → 版间永不相等 → 跑满 4 版（质检必败文本白等 ~11s）
  • 高风险文本: 字母数字串 ASR 转写天然随机 → 质检必然误报 → 全链白等
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from services.tts_service import TtsService, _ascii_alnum_ratio


@dataclass
class _FakeQc:
    """伪装 QcResult（只需提前交付判定用到的字段）。"""

    ok: bool = False
    per: float = 0.5
    bad_keys: "tuple[str, ...]" = ()
    bad_sentences: "list[str]" = field(default_factory=list)
    detail: str = "fake"


def test_ascii_alnum_ratio() -> None:
    assert _ascii_alnum_ratio("找书加微信：ail636066") > 0.5  # 广告串
    assert _ascii_alnum_ratio("崔桂英笑着摸了摸孩子的头。") == 0.0
    assert _ascii_alnum_ratio("") == 0.0
    assert _ascii_alnum_ratio("1998年，他出生了") >= 0.25  # 数字占比高


def test_high_alnum_text_skips_qc(monkeypatch: pytest.MonkeyPatch) -> None:
    """高字母数字占比 → 质检跳过（None 放行, 不产生重试）。"""
    svc = TtsService()
    assert svc._qc_check(b"wav-bytes", "找书加微信：ail636066", object()) is None  # noqa: SLF001  # pyright: ignore[reportArgumentType]  (测试直调)


def test_early_deliver_on_stable_bad_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """连续两版失败键一致 → 提前交付（调用 2 版即停）。"""
    svc = TtsService()
    calls: list[int] = []

    def _fake_synth(*_a, **_k):
        calls.append(1)
        return b"wav", 1.0

    monkeypatch.setattr(svc, "_synth_local", _fake_synth)  # noqa: SLF001
    monkeypatch.setattr(svc, "_qc_check",  # noqa: SLF001
                        lambda *_a, **_k: _FakeQc(ok=False, bad_keys=("同一句",)))
    wav, _ms = svc._synth_qc_local("文本", object(), 1.0)  # noqa: SLF001  # pyright: ignore[reportArgumentType]  (测试直调)
    assert wav == b"wav"
    assert len(calls) == 2, f"稳定键一致应 2 版停, 实际 {len(calls)} 版"


def test_no_early_deliver_when_keys_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败键每版不同（真随机错）→ 跑满 max_attempts 兜底交付。"""
    svc = TtsService()
    calls: list[int] = []

    def _fake_synth(*_a, **_k):
        calls.append(1)
        return b"wav", 1.0

    def _fake_qc(*_a, **_k):
        return _FakeQc(ok=False, bad_keys=(f"句{len(calls)}",))

    monkeypatch.setattr(svc, "_synth_local", _fake_synth)  # noqa: SLF001
    monkeypatch.setattr(svc, "_qc_check", _fake_qc)  # noqa: SLF001
    wav, _ms = svc._synth_qc_local("文本", object(), 1.0)  # noqa: SLF001  # pyright: ignore[reportArgumentType]  (测试直调)
    assert wav == b"wav"
    assert len(calls) == 4, f"失败键变化应跑满 4 版, 实际 {len(calls)} 版"
