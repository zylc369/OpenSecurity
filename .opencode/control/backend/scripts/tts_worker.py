#!/usr/bin/env python3
"""TTS 常驻推理 worker（独立 venv .venv-tts 运行; 主进程经 stdin/stdout 行式 JSON 通信）。

协议（一行 JSON 一条消息）:
  请求: {"id": "...", "op": "synth", "text": "...", "wav": "参考音频路径",
         "out": "输出wav路径", "speed": 0.9,
         "instruct": "朗读指令(默认'请用正常语速说一句话'——instruct 模式)",
         "seed": 4, "mode": "", "ref_text": "逐字稿(mode=zero_shot 回退时用)"}
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
EDGE_HEAD_KEEP_SEC = 0.20   # 头尾静音整理: 段首保留(呼吸感/起音自然)
EDGE_TAIL_KEEP_SEC = 0.12   # 头尾静音整理: 段尾保留(收音完整)

_model: Any = None  # 常驻模型实例（首次请求懒加载）

# 默认朗读指令: instruct 模式下由指令控制语速——短文本不再慢(实测 209ms/字,
# 长文 182ms/字, 跨次方差 ±5%)。ref_text/mode=zero_shot 为可回退路径。
DEFAULT_INSTRUCT = "请用正常语速朗读接下来的内容。"  # instruct 模式默认指令(跨文本长度语速统一)
DEFAULT_MODE = "zero_shot"  # 默认合成模式: zero_shot=参考韵律续写(情感饱满); "instruct"=指令控制
DEFAULT_SEED = 4            # 默认采样种子(同 seed 同参数输出可复现; 前端可覆盖)


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
        # 预加载: Model 为懒构建包装, 首次 generate 才初始化内部子模块——实测该
        # "混合初始化"路径使首次输出语速慢 30-45%(服务链冷启动后首段必中招)。
        # 提前初始化(约 1.5s, 在启动期摊掉)后每次生成走稳定路径。
        try:
            _model._ensure_model_loaded()  # noqa: SLF001 —— mlx_audio 懒加载包装固定 API
            _model._ensure_tokenizers_loaded()  # noqa: SLF001
        except Exception as e:  # noqa: BLE001 —— 预加载失败不阻断（回退懒加载）
            print(f"[worker] 预加载跳过: {e}", file=sys.stderr, flush=True)
        print(f"[worker] 模型加载完成(+预加载) {time.monotonic()-t0:.1f}s", file=sys.stderr, flush=True)
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


def _trim_edges(wav_path: Path) -> None:
    """头尾静音整理: 裁掉超量的段首/段尾静音, 治理段级拼接的接缝停顿。

    生成音频自带头 0.4-0.9s / 尾 0.1-0.3s 静音, 段间接缝叠加 0.6-0.8s 明显
    停顿; 裁到短余量(头 EDGE_HEAD_KEEP_SEC / 尾 EDGE_TAIL_KEEP_SEC)后,
    接缝降至 ~0.3s 自然换气级。帧级 RMS 检测(峰值 2% 阈值), 原地原子替换。
    """
    import numpy as np
    import soundfile as sf
    data, sr = sf.read(str(wav_path), dtype="float32")
    frame = int(0.02 * sr)
    n = len(data) // frame
    if n < 3:
        return
    rms = np.sqrt(np.mean(data[: n * frame].reshape(n, frame) ** 2, axis=1))
    th = max(float(np.max(rms)) * 0.02, 1e-5)
    idx = np.where(rms > th)[0]
    if len(idx) == 0:
        return  # 全静音异常: 不裁(交由尾部静音检测链路处置)
    first = int(idx[0]) * frame
    last = min(len(data), (int(idx[-1]) + 1) * frame)
    head_cut = max(0, first - int(EDGE_HEAD_KEEP_SEC * sr))
    tail_cut = max(0, len(data) - last - int(EDGE_TAIL_KEEP_SEC * sr))
    if head_cut == 0 and tail_cut == 0:
        return
    trimmed = data[head_cut: len(data) - tail_cut if tail_cut else len(data)]
    tmp = wav_path.with_suffix(".trim.wav")
    sf.write(str(tmp), trimmed, sr, subtype="PCM_16")
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
    mode = str(req.get("mode") or "").strip() or DEFAULT_MODE
    seed_raw = req.get("seed")
    seed = int(seed_raw) if seed_raw is not None else DEFAULT_SEED
    if seed < 0:  # 0 是合法种子——仅负值回落默认
        seed = DEFAULT_SEED
    print(f"[worker] 生效参数: mode={mode!r} seed={seed} speed={speed:.2f}", file=sys.stderr, flush=True)

    for attempt in (1, 2):  # 静音重试（第二次为补机）
        t0 = time.monotonic()
        ref_audio = load_audio(str(req["wav"]), sample_rate=model.sample_rate)
        kw: dict[str, Any] = dict(text=text, ref_audio=ref_audio)
        ref_text = req.get("ref_text")
        if mode == "instruct":
            # instruct 模式: 指令控制语速/风格（LLM 不接收参考语音 token——
            # 无韵律传染; 参考音频仍提供音色 embedding 与声学条件）。
            ins = str(instruct).strip() if instruct else DEFAULT_INSTRUCT
            kw["instruct_text"] = f"You are a helpful assistant. {ins}"
        elif ref_text:
            # 默认 zero-shot: 参考韵律续写（情感饱满）。CosyVoice3 要求参考
            # 逐字稿带 system 前缀分隔参考区/生成区（缺失时泄漏+重复率上升）。
            SYS_PREFIX = "You are a helpful assistant.<|endofprompt|>"
            rt = str(ref_text)
            kw["ref_text"] = rt if rt.startswith(SYS_PREFIX) else SYS_PREFIX + rt
        else:
            # zero-shot 但音色无 ref_text → 回退 instruct（防御; 音色库正常均带逐字稿）
            ins = str(instruct).strip() if instruct else DEFAULT_INSTRUCT
            kw["instruct_text"] = f"You are a helpful assistant. {ins}"

        # 采样种子: 默认 4; 请求可传任意 >0 值覆盖（前端测试台调节用）。
        # 同 seed 输出等效可复现（±1 LSB 浮点抖）——故重试必须派生子种子
        # （seed+attempt-1），否则 attempt 2 产出与 attempt 1 实质相同,
        # 尾部静音/坏采样救不回来, 重试纯属浪费。
        mx.random.seed(seed + attempt - 1)
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
            print(f"[worker] 尾部静音检出 → 重试（{duration:.1f}s, 派生 seed={seed + 1}）",
                  file=sys.stderr, flush=True)
            continue
        break

    retried = attempt == 2
    if speed < 0.99:
        _atempo(out_path, speed)
    _trim_edges(out_path)  # 头尾静音整理(接缝停顿治理, 作用于最终输出)
    info = sf.info(str(out_path))
    duration = float(info.duration)
    return {"id": req.get("id", ""), "ok": True, "path": str(out_path),
            "duration": round(duration, 2), "rtf": round(rtf, 3), "retried": retried}


def main() -> int:
    # 诊断: HF 离线开关的真实来源(spawn 链)。stderr 进控制台日志。
    import os
    print(f"[worker][诊断] HF_HUB_OFFLINE 生效值={os.environ.get('HF_HUB_OFFLINE', '<unset>')} "
          f"父进程原值={os.environ.get('TTS_PARENT_HF_OFFLINE', '<unset>')}",
          file=sys.stderr, flush=True)
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
        _t_req = time.monotonic()
        print(f"[worker] 请求 {req.get('id', '?')}: {len(str(req.get('text', '')))}字 "
              f"mode={req.get('mode', '')!r} seed={req.get('seed', -1)}", file=sys.stderr, flush=True)
        try:
            resp = _synth(req, args.model_dir)
        except Exception as e:  # noqa: BLE001 —— worker 错误统一面（主进程决策重启）
            resp = {"id": req.get("id", ""), "ok": False, "error": f"{type(e).__name__}: {e}"}
            print(f"[worker] 请求异常: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _ms = (time.monotonic() - _t_req) * 1000
        print(f"[worker] 完成: 处理 {_ms:.0f}ms "
              f"{'ok' if resp.get('ok') else 'FAIL'} "
              f"音频={resp.get('duration', '?')}s rtf={resp.get('rtf', '?')} "
              f"{'静音重试' if resp.get('retried') else ''}", file=sys.stderr, flush=True)
        print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
