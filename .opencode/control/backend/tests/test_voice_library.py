"""VoiceLibrary 单测（双源清单/默认音色/上传校验——临时 OPENSECURITY_HOME 隔离）。"""
# pyright: reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportAny=false, reportMissingTypeArgument=false
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.voice_library as vl  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """用户音色目录隔离到 tmp（内置 git 资产不受影响——只读）。"""
    monkeypatch.setenv("OPENSECURITY_HOME", str(tmp_path))
    vl.VoiceLibrary._reset_for_tests()
    yield tmp_path
    vl.VoiceLibrary._reset_for_tests()


def _tone_wav(seconds: float, sr: int = 44100) -> bytes:
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, tone, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def test_builtin_default_voice():
    lib = vl.VoiceLibrary.get_instance()
    v = lib.default_voice()
    assert v.id == "official_female" and v.source == "builtin"  # plus 定稿默认
    assert v.resolved_wav(lib).is_file()  # git 资产在位


def test_unknown_voice_none():
    assert vl.VoiceLibrary.get_instance().get("不存在") is None


def test_upload_roundtrip(_isolated_home):
    lib = vl.VoiceLibrary.get_instance()
    asset = lib.add_user_voice(_tone_wav(5.0), "测试男声", "male", "", "五秒测试音频")
    assert asset.source == "user" and lib.get(asset.id) is not None
    # 24kHz 转换落盘 + 清单持久化（重建实例可读——隔离目录内的清单）
    assert asset.resolved_wav(lib).is_file()
    lib2_manifest = _isolated_home / "voices" / "user_voices.json"
    data = json.loads(lib2_manifest.read_text())
    assert any(x["id"] == asset.id for x in data)


def test_upload_duration_reject(_isolated_home):
    lib = vl.VoiceLibrary.get_instance()
    with pytest.raises(vl.VoiceError, match="时长"):
        lib.add_user_voice(_tone_wav(1.0), "过短", "female", "", "一秒")


def test_upload_bad_gender(_isolated_home):
    with pytest.raises(vl.VoiceError, match="gender"):
        vl.VoiceLibrary.get_instance().add_user_voice(
            _tone_wav(5.0), "名", "alien", "", "稿")


def test_upload_duplicate_name(_isolated_home):
    lib = vl.VoiceLibrary.get_instance()
    lib.add_user_voice(_tone_wav(5.0), "重名", "female", "", "稿")
    with pytest.raises(vl.VoiceError, match="冲突"):
        lib.add_user_voice(_tone_wav(6.0), "重名", "female", "", "稿2")
