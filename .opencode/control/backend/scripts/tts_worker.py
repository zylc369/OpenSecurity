#!/usr/bin/env python3
"""TTS 常驻推理 worker（独立 venv .venv-cosy-tts; 主进程经 stdin/stdout 行式 JSON 通信）。

协议（一行 JSON 一条消息）:
  请求: {"id": "...", "op": "synth", "text": "...", "wav": "参考音频路径",
         "ref_text": "逐字稿", "out": "输出wav路径", "speed": 0.9, "instruct": null}
  响应: {"id": "...", "ok": true, "path": "...", "duration": 62.4, "rtf": 0.31,
         "retried": false}
        {"id": "...", "ok": false, "error": "..."}

内存纪律: 模型常驻（单实例）; 每请求后 mx.clear_cache()（中间张量不累积）。
输出校验: 尾部静音（RMS<阈值）自动重试 1 次（半截合成事故预防）。
变速: speed 透传 torch 栈（mel 插值——韵律保持的生成时变速）。

用法: .venv-cosy-tts/bin/python tts_worker.py [--model-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

# 尾部静音判定: 最后 10s 的峰值振幅 < 0.02（16bit 满摆幅归一后）视为合成中断
SILENCE_TAIL_SEC = 10.0
SILENCE_PEAK_THRESHOLD = 0.02

_model: Any = None  # 常驻模型实例（首次请求懒加载）


def _load(model_dir: str) -> Any:
    """CosyVoice3 @ vendor/tts-funaudio（MPS: llm fp16 / flow fp32 / hift cpu）。

    依赖跑在主 venv（torch 2.14 + transformers 5.17 + numpy 2.5——实测 RTF 0.77）。
    hift CPU 包装: f0 pitch predictor 用 float64（MPS 不支持）——drmse 踩坑结论。
    """
    global _model
    if _model is None:
        import os as _os
        t0 = time.monotonic()
        _VENDOR = Path(__file__).resolve().parents[4] / "vendor" / "tts-funaudio"
        _os.chdir(str(_VENDOR))  # 模型 yaml 内路径相对 vendor 仓库根
        sys.path.insert(0, str(_VENDOR))
        sys.path.insert(0, str(_VENDOR / "third_party" / "Matcha-TTS"))
        import torch
        from cosyvoice.cli.cosyvoice import CosyVoice3
        cv = CosyVoice3(model_dir=model_dir)
        m = cv.model
        if torch.backends.mps.is_available():
            m.device = torch.device("mps")
            m.llm.to("mps", torch.float16)   # 带宽减半——最大速度杠杆（整数 token 边界无损）
            m.flow.to("mps", torch.float32)  # fp32（cached conditioning 撞 half 必炸）
            m.hift.to("cpu")
            _orig_hift = m.hift.inference
            def _hift_cpu(speech_feat, **kw):
                return _orig_hift(speech_feat.to("cpu"), **kw)
            m.hift.inference = _hift_cpu     # f0 float64 → CPU
            print("[worker] 设备: llm/flow→mps(fp16/fp32), hift→cpu", file=sys.stderr, flush=True)
        _model = cv
        print(f"[worker] 模型加载完成 {time.monotonic()-t0:.1f}s",
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


def _synth(req: dict[str, Any], model_dir: str) -> dict[str, Any]:
    model = _load(model_dir)
    out_path, duration, rtf = _synth_torch(req, model)
    return {"id": req.get("id", ""), "ok": True, "path": str(out_path),
            "duration": round(duration, 2), "rtf": round(rtf, 3), "retried": False}


def main() -> int:
    # stdout 纪律: 行协议独占 stdout——依赖库（modelscope/cosyvoice）的
    # print 劫持到 stderr（防协议污染——"Downloading Model..." 之类）
    _protocol_stdout = sys.stdout
    sys.stdout = sys.stderr

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-dir", required=True, help="CosyVoice3 模型目录")
    args = ap.parse_args()

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
