#!/usr/bin/env python3
"""TTS 常驻推理 worker（独立 venv .venv-tts 运行; 主进程经 stdin/stdout 行式 JSON 通信）。

协议（一行 JSON 一条消息）:
  请求: {"id": "...", "op": "synth", "text": "...", "wav": "参考音频路径",
         "ref_text": "逐字稿", "out": "输出wav路径", "speed": 0.9, "instruct": null}
  响应: {"id": "...", "ok": true, "path": "...", "duration": 62.4, "rtf": 0.31,
         "retried": false}
        {"id": "...", "ok": false, "error": "..."}

内存纪律: 模型常驻（单实例）; 每请求后 mx.clear_cache()（中间张量不累积）。
输出校验: 尾部静音（RMS<阈值）自动重试 1 次（半截合成事故预防）。
变速: speed<1 → ffmpeg atempo 后处理（变速不变调; speed=1 跳过）。

用法: .venv-tts/bin/python tts_worker.py [--model-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

# 尾部静音判定: 最后 10s 的峰值振幅 < 0.02（16bit 满摆幅归一后）视为合成中断
SILENCE_TAIL_SEC = 10.0
SILENCE_PEAK_THRESHOLD = 0.02

_model: Any = None  # 常驻模型实例（首次请求懒加载）
_ENGINE = "plus"  # plus（mlx 8bit）| torch（官方 fp32——cv3 同源）


def _load(model_dir: str) -> Any:
    global _model
    if _model is None:
        t0 = time.monotonic()
        if _ENGINE == "torch":
            # CosyVoice 官方栈（AutoModel + zero-shot; speed 为真 mel 插值变速）
            _BACKEND = Path(__file__).resolve().parent.parent
            sys.path.insert(0, str(_BACKEND / "third_party" / "CosyVoice"))
            sys.path.insert(0, str(_BACKEND / "third_party" / "CosyVoice" / "third_party" / "Matcha-TTS"))
            from cosyvoice.cli.cosyvoice import AutoModel
            _model = AutoModel(model_dir=model_dir)
        else:
            from mlx_audio.tts.utils import load_model
            _model = load_model(model_path=model_dir)
        print(f"[worker][{_ENGINE}] 模型加载完成 {time.monotonic()-t0:.1f}s",
              file=sys.stderr, flush=True)
    return _model


def _synth_torch(req: "dict[str, Any]", model: Any) -> "tuple[Path, float, float]":
    """torch 引擎合成（AutoModel.zero-shot; chunks 拼接; speed 原生 mel 插值）。"""
    import numpy as np
    import soundfile as sf
    import torch
    text = str(req["text"]).strip()
    out_path = Path(str(req["out"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    speed = float(req.get("speed") or 1.0)
    for attempt in (1, 2):
        t0 = time.monotonic()
        prompt_text = f"You are a helpful assistant.<|endofprompt|>{req.get('ref_text', '')}"
        chunks = list(model.inference_zero_shot(
            text, prompt_text, str(req["wav"]), stream=False, speed=speed))
        if not chunks:
            raise RuntimeError("torch 模型无音频产出")
        full = torch.cat([c["tts_speech"] for c in chunks], dim=-1)
        data = full.squeeze(0).numpy().astype(np.float32)
        sf.write(str(out_path), data, model.sample_rate, subtype="PCM_16")
        duration = float(len(data) / model.sample_rate)
        rtf = (time.monotonic() - t0) / max(duration, 0.01)
        if attempt == 1 and _tail_is_silent(out_path):
            print(f"[worker][torch] 尾部静音 → 重试", file=sys.stderr, flush=True)
            continue
        break
    return out_path, duration, rtf


def _tail_is_silent(wav_path: Path) -> bool:
    """尾部 SILENCE_TAIL_SEC 秒峰值低于阈值 → 判定半截合成（Eric 式事故）。"""
    import numpy as np
    import soundfile as sf
    info = sf.info(str(wav_path))
    n_tail = int(min(SILENCE_TAIL_SEC, info.duration) * info.samplerate)
    if n_tail == 0:
        return False
    data, _ = sf.read(str(wav_path), start=max(0, info.frames - n_tail),
                      frames=n_tail, dtype="float32")
    return bool(cast("np.ndarray", np.abs(data)).max() < SILENCE_PEAK_THRESHOLD)


def _atempo(wav_path: Path, speed: float) -> None:
    """变速不变调后处理（原文件替换——临时文件+rename 原子落盘）。"""
    tmp = wav_path.with_suffix(".atempo.wav")
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-filter:a", f"atempo={speed:.3f}", str(tmp)],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg atempo 失败: {r.stderr[:300]}")
    tmp.replace(wav_path)


def _synth(req: dict[str, Any], model_dir: str) -> dict[str, Any]:
    model = _load(model_dir)
    if _ENGINE == "torch":
        out_path, duration, rtf = _synth_torch(req, model)
        retried = False
        return {"id": req.get("id", ""), "ok": True, "path": str(out_path),
                "duration": round(duration, 2), "rtf": round(rtf, 3), "retried": retried}
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.generate import load_audio
    import mlx.core as mx
    text = str(req["text"]).strip()
    out_path = Path(str(req["out"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    speed = float(req.get("speed") or 1.0)
    instruct = req.get("instruct")

    for attempt in (1, 2):  # 静音重试（第二次为补机）
        t0 = time.monotonic()
        ref_audio = load_audio(str(req["wav"]), sample_rate=model.sample_rate)
        kw: dict[str, Any] = dict(text=text, ref_audio=ref_audio)
        ref_text = req.get("ref_text")
        if instruct:
            kw["instruct_text"] = f"You are a helpful assistant. {instruct}"
        elif ref_text:
            kw["ref_text"] = str(ref_text)
        chunks: list[Any] = []
        for result in model.generate(**kw):
            audio = getattr(result, "audio", None)
            if audio is not None and len(audio) > 0:
                chunks.append(np.array(audio))
        mx.clear_cache()  # 内存纪律: 中间张量即请即清
        if not chunks:
            raise RuntimeError("模型无音频产出（chunks 空）")
        full = np.concatenate(chunks)
        sf.write(str(out_path), full, model.sample_rate, subtype="PCM_16")
        duration = float(len(full) / model.sample_rate)
        rtf = (time.monotonic() - t0) / max(duration, 0.01)
        if attempt == 1 and _tail_is_silent(out_path):
            print(f"[worker] 尾部静音检出 → 重试（{duration:.1f}s）", file=sys.stderr, flush=True)
            continue
        break

    retried = attempt == 2
    if speed < 0.99:
        _atempo(out_path, speed)
        info = sf.info(str(out_path))
        duration = float(info.duration)
    return {"id": req.get("id", ""), "ok": True, "path": str(out_path),
            "duration": round(duration, 2), "rtf": round(rtf, 3), "retried": retried}


def main() -> int:
    # stdout 纪律: 行协议独占 stdout——依赖库（modelscope/cosyvoice）的
    # print 劫持到 stderr（防协议污染——"Downloading Model..." 之类）
    _protocol_stdout = sys.stdout
    sys.stdout = sys.stderr

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-dir", required=True, help="CosyVoice3 模型目录")
    ap.add_argument("--engine", default="plus", choices=["plus", "torch"],
                    help="推理引擎（plus=mlx 8bit 轻量; torch=官方 fp32 cv3 同源品质）")
    args = ap.parse_args()
    global _ENGINE
    _ENGINE = args.engine

    if shutil.which("ffmpeg") is None:
        print("[worker][warn] ffmpeg 不在 PATH——speed<1 的请求将失败", file=sys.stderr, flush=True)

    import select as _select
    while True:  # 常驻循环: 一行请求一行响应 + 孤儿自杀（父进程死亡守护）
        ready, _, _ = _select.select([sys.stdin], [], [], 5.0)
        if not ready:
            if os.getppid() == 1:  # 孤儿（父已死）→ 退出释放模型内存
                print("[worker] 父进程已死（ppid=1）→ 自杀退出", file=sys.stderr, flush=True)
                return 0
            continue
        line = sys.stdin.readline()
        if not line:  # EOF（管道关闭）
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _protocol_stdout.write(json.dumps(
                {"id": "", "ok": False, "error": f"协议解析失败: {e}"}) + "\n")
            _protocol_stdout.flush()
            continue
        try:
            resp = _synth(req, args.model_dir)
        except Exception as e:  # noqa: BLE001 —— worker 错误统一面（主进程决策重启）
            resp = {"id": req.get("id", ""), "ok": False, "error": f"{type(e).__name__}: {e}"}
        _protocol_stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        _protocol_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
