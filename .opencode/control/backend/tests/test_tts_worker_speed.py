"""worker 变速拆分与 atempo 集成测试。

_atempo_factors: 纯数学拆分（ffmpeg atempo 单实例范围 0.5-2.0, 串联还原）。
_atempo: 真实 ffmpeg 跑正弦波, 断言输出时长 ≈ 原时长/speed（禁止 mock）。
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# worker 是 scripts/ 下脚本（非包）, 按路径加载; 模块级无副作用（模型惰性加载）
_WORKER = Path(__file__).resolve().parents[1] / "scripts" / "tts_worker.py"
_spec = importlib.util.spec_from_file_location("tts_worker", _WORKER)
tts_worker = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("tts_worker", tts_worker)
_spec.loader.exec_module(tts_worker)  # type: ignore[union-attr]


@pytest.mark.parametrize("speed, expected", [
    (0.5, [0.5]),          # 下边界单实例
    (2.0, [2.0]),          # 上边界单实例
    (1.5, [1.5]),          # 区间内直传
    (0.75, [0.75]),
    (3.0, [2.0, 1.5]),     # 上界（服务端 clamp 上限）→ 两级串联
    (2.5, [2.0, 1.25]),
    (4.0, [2.0, 2.0]),     # 防御超界输入
    (0.3, [0.5, 0.6]),     # 防御越下界（服务端不会给到）
])
def test_atempo_factors(speed: float, expected: "list[float]") -> None:
    got = tts_worker._atempo_factors(speed)
    want = [f"atempo={f:.6f}" for f in expected]
    assert got == want
    # 串联乘积还原 speed（拆分数学正确性）
    prod = 1.0
    for f in expected:
        prod *= f
    assert abs(prod - speed) < 1e-6


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 不可用")
def test_atempo_integration_speedup(tmp_path: Path) -> None:
    """加速档（原 bug: speed>1 静默 no-op）真实 ffmpeg 验证: 时长 ≈ 原/1.5。"""
    src = tmp_path / "in.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", str(src)],
        check=True, timeout=30)
    before = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=30).stdout.strip())
    tts_worker._atempo(src, 1.5)
    after = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=30).stdout.strip())
    assert before / after == pytest.approx(1.5, rel=0.05)  # ±5% 容差（帧对齐）


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 不可用")
def test_atempo_integration_chain_3x(tmp_path: Path) -> None:
    """3.0x 两级串联（2.0×1.5）真实 ffmpeg 验证: 时长 ≈ 原/3。"""
    src = tmp_path / "in.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", str(src)],
        check=True, timeout=30)
    before = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=30).stdout.strip())
    tts_worker._atempo(src, 3.0)
    after = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=30).stdout.strip())
    assert before / after == pytest.approx(3.0, rel=0.05)


# ───────────────────── _ffmpeg_bin 双路解析 ─────────────────────


def test_ffmpeg_bin_path_hit(monkeypatch) -> None:
    """① PATH 命中（brew/系统来源）优先返回 which 结果。"""
    monkeypatch.setattr(tts_worker.shutil, "which",
                        lambda _: "/opt/homebrew/bin/ffmpeg")
    assert tts_worker._ffmpeg_bin() == "/opt/homebrew/bin/ffmpeg"


def test_ffmpeg_bin_cmddir_fallback(monkeypatch, tmp_path: Path) -> None:
    """② PATH 未命中 → $OPENSECURITY_HOME/bin 回落（detect_tools 产物目录）。"""
    monkeypatch.setattr(tts_worker.shutil, "which", lambda _: None)
    monkeypatch.setenv("OPENSECURITY_HOME", str(tmp_path))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg").write_bytes(b"\x7fELF")  # 存在性判定（不执行）
    assert tts_worker._ffmpeg_bin() == str(bin_dir / "ffmpeg")


def test_ffmpeg_bin_missing_raises(monkeypatch, tmp_path: Path) -> None:
    """③ 两级皆缺 → RuntimeError 含安装指引（不静默返回假路径）。"""
    monkeypatch.setattr(tts_worker.shutil, "which", lambda _: None)
    monkeypatch.setenv("OPENSECURITY_HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="ffmpeg 不可用"):
        tts_worker._ffmpeg_bin()


def test_ffmpeg_bin_no_env_var(monkeypatch) -> None:
    """④ OPENSECURITY_HOME 未注入且 PATH 无 → RuntimeError（非 IndexError）。"""
    monkeypatch.setattr(tts_worker.shutil, "which", lambda _: None)
    monkeypatch.delenv("OPENSECURITY_HOME", raising=False)
    with pytest.raises(RuntimeError):
        tts_worker._ffmpeg_bin()
