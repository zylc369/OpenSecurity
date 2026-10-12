"""ModelAssetRegistry.filter_by_tags 圈选语义测试（tags 通用化设计）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.model_assets import ModelAssetRegistry, ModelTag  # noqa: E402


def test_default_is_security_group():
    """空 tags = 安全组（向后兼容——不含 TTS 资产）。"""
    ids = [m.id for m in ModelAssetRegistry.filter_by_tags([])]
    assert "bge-m3" in ids and "glm-ocr" in ids
    tts_ids = {m.id for m in ModelAssetRegistry.filter_by_tags(["tts"])}
    assert not (set(ids) & tts_ids)


def test_tts_only():
    ids = [m.id for m in ModelAssetRegistry.filter_by_tags(["tts"])]
    assert ids == ["cosyvoice3-8bit"]


def test_combined():
    ids = {m.id for m in ModelAssetRegistry.filter_by_tags(["security", "tts"])}
    assert {"bge-m3", "bge-reranker-v2-m3", "glm-ocr", "cosyvoice3-8bit"} <= ids


def test_unknown_tag_rejected():
    """未知标签显式报错（防静默漏装——安装范围错误是部署事故）。"""
    with pytest.raises(ValueError, match="未知模型标签"):
        ModelAssetRegistry.filter_by_tags(["security", "hacker"])


def test_tags_declared_on_assets():
    """圈选通用化: 资产自带 tags 字段（新增场景零 ensure_models 改动）。"""
    for m in ModelAssetRegistry.MODELS:
        assert isinstance(m.tags, tuple) and m.tags
        assert all(isinstance(t, ModelTag) for t in m.tags)
