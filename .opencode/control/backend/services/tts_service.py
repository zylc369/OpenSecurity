"""远端 TTS 服务（kokoro-onnx; 需求 D5/D8——初版 WAV 24kHz，Opus 列为后续优化）。

模型资产（控制台「环境总览→模型」下载，产物落此目录; 也可手动放置）:
  ~/.cache/opensecurity/tts/kokoro-v1.0.fp16.onnx     （kokoro-onnx GitHub Release v1.0）
  ~/.cache/opensecurity/tts/voices-v1.0.bin

失败语义: 模型缺失/依赖未装 → TtsUnavailable（路由层映射 503——
调用方不需要区分错误种类）。LRU 键 = (voice, speed, text)。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TTS_ASSET_DIR = Path.home() / ".cache" / "opensecurity" / "tts"
MODEL_FILE = "kokoro-v1.0.fp16.onnx"      # kokoro-onnx GitHub Release v1.0（含 zf_*/zm_* 中文音色）
VOICES_FILE = "voices-v1.0.bin"
DEFAULT_VOICE = "zf_xiaobei"
DEFAULT_SPEED = 1.0
SAMPLE_RATE = 24000
CACHE_LIMIT = 2048
CACHE_BYTES_LIMIT = 256 * 1024 * 1024  # 256MiB 字节预算（review#7——条目数上限之外防大 WAV 撑爆内存）
MAX_TEXT_LEN = 2000


class TtsUnavailable(RuntimeError):
    """TTS 不可用（模型缺失/依赖未装/合成失败统一面）。"""


@dataclass(frozen=True)
class TtsResult:
    """合成结果（WAV 全文件字节）。"""

    wav: bytes
    cached: bool
    gen_ms: float
    voice: str
    speed: float


class TtsService:
    """kokoro-onnx 懒加载 + LRU 缓存（线程安全; 全局单例 get_instance）。"""

    _instance: "TtsService | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engine: "object | None" = None  # kokoro_onnx.Kokoro
        self._engine_failed = False            # 依赖缺失只报一次（避免每请求重复 import 报错）
        self._cache: "OrderedDict[tuple[str, float, str], bytes]" = OrderedDict()

    @classmethod
    def get_instance(cls) -> "TtsService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = TtsService()
        return cls._instance

    # ── 引擎 ─────────────────────────────────────────

    @property
    def engine_loaded(self) -> bool:
        """引擎是否已加载（懒加载真实态; 不触发加载——模型资产状态页用）。"""
        return self._engine is not None

    def _model_paths(self) -> "tuple[Path, Path]":
        """模型文件定位: TTS_ASSET_DIR（GitHub Release 下载产物/手动放置同一目录）。

        历史: 曾优先 HF hub snapshot——但 kokoro_onnx 引擎所需的 voices.bin
        在 HF onnx-community 仓库并不存在（音色是 voices/*.bin 每音色一文件，
        与引擎的单文件打包格式不兼容）——该分支从未可能成功，已删。
        """
        return TTS_ASSET_DIR / MODEL_FILE, TTS_ASSET_DIR / VOICES_FILE

    def engine_ready(self) -> bool:
        """模型文件与依赖是否就绪（不触发加载）。"""
        model, voices = self._model_paths()
        return model.is_file() and voices.is_file()

    def _get_engine(self) -> "object":
        if self._engine is not None:
            return self._engine
        if self._engine_failed:
            raise TtsUnavailable("TTS 引擎不可用（先前初始化失败——见日志）")
        model, voices = self._model_paths()
        if not (model.is_file() and voices.is_file()):
            raise TtsUnavailable(
                f"模型未就绪: 在控制台「环境总览→模型」下载 Kokoro TTS，"
                f"或手动放置 {TTS_ASSET_DIR}（{model.name}/{voices.name}）")
        try:
            from kokoro_onnx import Kokoro  # type: ignore[no-any-reexport] —— 无存根库
        except ImportError as e:
            self._engine_failed = True
            logger.warning("kokoro-onnx 未安装: %s", e)
            raise TtsUnavailable("kokoro-onnx 未安装（pip install kokoro-onnx）") from e
        try:
            t0 = time.monotonic()
            from typing import Callable as _Callable, cast as _cast
            engine_ctor = _cast("_Callable[[str, str], object]", Kokoro)
            self._engine = engine_ctor(str(model), str(voices))
            logger.info("TTS 引擎已加载（%.1fs）", time.monotonic() - t0)
            return self._engine
        except Exception as e:  # noqa: BLE001 —— 引擎初始化失败统一面
            self._engine_failed = True
            logger.exception("TTS 引擎初始化失败")
            raise TtsUnavailable(f"引擎初始化失败: {e}") from e

    # ── 合成 ─────────────────────────────────────────

    def synthesize(self, text: str, voice: str = DEFAULT_VOICE,
                   speed: float = DEFAULT_SPEED) -> TtsResult:
        """文本 → WAV 字节（LRU 命中标记 cached）。空文本 ValueError。"""
        text = text.strip()
        if not text:
            raise ValueError("文本为空")
        if len(text) > MAX_TEXT_LEN:
            raise ValueError(f"文本过长（{len(text)} > {MAX_TEXT_LEN}）")
        speed = min(max(speed, 0.5), 3.0)
        key = (voice, speed, text)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return TtsResult(wav=hit, cached=True, gen_ms=0.0,
                                 voice=voice, speed=speed)
        # 远程路由（四模型统一远程化——与 embed/rerank/ocr 同语义:
        # should_use_remote → 远程推理，失败 fallback 本地; 缓存命中不出本机）
        try:
            from services.remote_link import RemoteLinkService
            use_remote = RemoteLinkService.get_instance().should_use_remote()
        except Exception:  # noqa: BLE001 —— remote_link 未就绪 → 本地
            use_remote = False
        if use_remote:
            from services.remote_client import RemoteUnavailable
            t0 = time.monotonic()
            try:
                client = RemoteLinkService.get_instance().get_client()
                wav = client.tts_synth(text, voice, speed)
                return TtsResult(wav=wav, cached=False,
                                 gen_ms=(time.monotonic() - t0) * 1000,
                                 voice=voice, speed=speed)
            except RemoteUnavailable as e:
                try:
                    RemoteLinkService.get_instance().note_request_failure(f"tts: {e}")
                except Exception:  # noqa: BLE001
                    pass
                logger.warning("远程 tts 失败，fallback 本地: %s", e)
        engine = self._get_engine()
        t0 = time.monotonic()
        try:
            from typing import Sequence as _Seq, cast as _cast2
            raw = getattr(engine, "create")(  # pyright: ignore[reportAny] —— 无存根引擎
                text, voice=voice, speed=speed,
                # espeak-ng 中文语音名为 "cmn"（cmn-cn/zh 均不存在——实测枚举）
                lang="cmn" if voice.startswith("z") else "en-us")
            samples = _cast2("_Seq[float]",
                             raw[0] if isinstance(raw, tuple) else raw)
        except Exception as e:  # noqa: BLE001 —— 合成失败统一面
            raise TtsUnavailable(f"合成失败: {e}") from e
        wav = WavEncoder.encode(samples, SAMPLE_RATE)
        gen_ms = (time.monotonic() - t0) * 1000
        with self._lock:
            self._cache[key] = wav
            self._cache.move_to_end(key)
            while (len(self._cache) > CACHE_LIMIT
                   or sum(len(v) for v in self._cache.values()) > CACHE_BYTES_LIMIT):
                self._cache.popitem(last=False)
        return TtsResult(wav=wav, cached=False, gen_ms=gen_ms,
                         voice=voice, speed=speed)

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def release(self) -> None:
        """释放引擎与缓存（模型目录变更后重载用）。"""
        with self._lock:
            self._engine = None
            self._engine_failed = False
            self._cache.clear()


class WavEncoder:
    """float32 一维采样 → WAV 文件字节（无第三方依赖; PCM16 单声道封装器）。"""

    @staticmethod
    def encode(samples: "object", sample_rate: int) -> bytes:
        import io
        import struct
        import wave
        from typing import Sequence, cast
        floats = list(cast("Sequence[float]", samples))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # int16
            w.setframerate(sample_rate)
            clipped = [max(-1.0, min(1.0, f)) for f in floats]
            w.writeframes(struct.pack(f"<{len(clipped)}h",
                                      *[int(f * 32767) for f in clipped]))
        return buf.getvalue()


def _smoke_main(argv: "list[str]") -> int:
    """python -m services.tts_service --smoke "文本" [voice]。"""
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--smoke" not in argv:
        print("用法: python -m services.tts_service --smoke <文本> [voice]")
        return 2
    args = [a for a in argv[1:] if a != "--smoke"]
    text = args[0] if args else "你好，这是远程语音合成测试。"
    voice = args[1] if len(args) > 1 else DEFAULT_VOICE
    try:
        result = TtsService.get_instance().synthesize(text, voice=voice)
    except (TtsUnavailable, ValueError) as e:
        print(f"smoke 失败: {e}")
        return 1
    out = Path("/var/tmp/tts_smoke.wav")
    out.write_bytes(result.wav)
    print(f"smoke 成功: {out}（{len(result.wav)}B, {result.gen_ms:.0f}ms, "
          f"voice={result.voice}）——二次调用验证缓存:")
    t0 = time.monotonic()
    TtsService.get_instance().synthesize(text, voice=voice)
    print(f"缓存命中耗时 {(time.monotonic() - t0) * 1000:.2f}ms")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_smoke_main(sys.argv))
