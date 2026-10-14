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


def _patch_ras() -> None:
    """对齐官方 RAS 语义（mlx-audio 移植缺陷修复）:

    plus 原版: 重复检测触发后全词表随机重采且不屏蔽原 token——
      (a) 可能重采同一个（回退无效） (b) 全词表随机质量差（吃字/错字来源）。
    官方语义: 触发后先把重复 token 的 logits 置 -inf（屏蔽）再受限重采。
    """
    import mlx.core as mx
    from mlx_audio.tts.models.cosyvoice3.llm import llm as cv3_llm

    def ras_sampling_fixed(logits, decoded_tokens, sampling,
                           top_p=0.8, top_k=25, win_size=10, tau_r=0.1):
        top_ids = cv3_llm.nucleus_sampling(logits, top_p=top_p, top_k=top_k)
        if len(decoded_tokens) > 0:
            rep_num = sum(1 for t in decoded_tokens[-win_size:] if t == top_ids)
            if rep_num >= win_size * tau_r:
                logits[top_ids] = -float("inf")  # 屏蔽重复 token（plus 缺失）
                # 受限重采（top-k 而非全词表）
                top_ids = cv3_llm.nucleus_sampling(logits, top_p=top_p, top_k=top_k)
                if top_ids == int(logits.shape[0]):  # 防御（不可能分支）
                    pass
        return top_ids

    cv3_llm.ras_sampling = ras_sampling_fixed
    # from-import 名字拷贝——build 处（cosyvoice3 模块）引用也要覆盖
    import mlx_audio.tts.models.cosyvoice3.cosyvoice3 as cv3_outer
    cv3_outer.ras_sampling = ras_sampling_fixed
    print("[worker] RAS patch 就绪（llm + cosyvoice3 双命名空间）", file=sys.stderr, flush=True)


def _load(model_dir: str) -> Any:
    global _model
    if _model is None:
        from mlx_audio.tts.utils import load_model
        t0 = time.monotonic()
        _model = load_model(model_path=model_dir)
        print(f"[worker] 模型加载完成 {time.monotonic()-t0:.1f}s", file=sys.stderr, flush=True)
    return _model


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
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.generate import load_audio
    import mlx.core as mx

    model = _load(model_dir)
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
            # CosyVoice3 zero-shot 要求: 参考逐字稿必须带 system 前缀分隔参考区/生成区。
            # 缺失时模型把参考文本念出来(泄漏)且重复率上升——上游修复 commit 64685e8 同源。
            SYS_PREFIX = "You are a helpful assistant.<|endofprompt|>"
            rt = str(ref_text)
            kw["ref_text"] = rt if rt.startswith(SYS_PREFIX) else SYS_PREFIX + rt
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-dir", required=True, help="CosyVoice3 模型目录")
    args = ap.parse_args()

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
            print(json.dumps({"id": "", "ok": False, "error": f"协议解析失败: {e}"}), flush=True)
            continue
        try:
            resp = _synth(req, args.model_dir)
        except Exception as e:  # noqa: BLE001 —— worker 错误统一面（主进程决策重启）
            resp = {"id": req.get("id", ""), "ok": False, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
