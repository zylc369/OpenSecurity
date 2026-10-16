"""model_policy 单测: 默认值/覆盖/0→常驻/校验。"""
from __future__ import annotations

import pytest

from services import model_policy


def setup_function() -> None:
    model_policy.reset_overrides_for_tests()


def test_defaults() -> None:
    assert model_policy.release_sec_of("cosyvoice3-8bit") == 1800.0
    assert model_policy.release_sec_of("glm-ocr") == 600.0
    assert model_policy.release_sec_of("bge-m3") is None
    assert model_policy.release_sec_of("bge-reranker-v2-m3") is None


def test_override_zero_is_permanent() -> None:
    model_policy.apply_idle_override("cosyvoice3-8bit", 0)
    assert model_policy.release_sec_of("cosyvoice3-8bit") is None


def test_override_value() -> None:
    model_policy.apply_idle_override("glm-ocr", 120)
    assert model_policy.release_sec_of("glm-ocr") == 120.0


def test_unknown_id_rejected() -> None:
    with pytest.raises(ValueError):
        model_policy.apply_idle_override("nope", 1)


def test_negative_rejected() -> None:
    with pytest.raises(ValueError):
        model_policy.apply_idle_override("glm-ocr", -5)


def test_clear_override() -> None:
    model_policy.apply_idle_override("glm-ocr", 0)
    model_policy.clear_override("glm-ocr")
    assert model_policy.release_sec_of("glm-ocr") == 600.0


def test_known_ids() -> None:
    assert model_policy.known_ids() == frozenset(
        {"bge-m3", "bge-reranker-v2-m3", "glm-ocr", "cosyvoice3-8bit"})
