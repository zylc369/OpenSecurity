"""TTS 服务（CosyVoice3-8bit @ mlx-audio-plus 引擎，常驻 worker 子进程推理）。

架构:
  本地: TtsWorkerClient → .venv-tts python scripts/tts_worker.py（stdin/stdout
        行式 JSON 协议; 模型常驻 worker 内; 每请求 mx.clear_cache; 尾部静音
        自动重试; speed<1 ffmpeg atempo 后处理）。
  远程: should_use_remote → P2P → 节点同构 TtsService（失败 fallback 本地）。
  音色: VoiceLibrary 双源（内置 git 资产 + 用户运行时）; voice 参数=音色 id。

worker 生命周期: 首次合成懒启动; 单请求超时杀进程（下次自动重拉）; 空闲常驻
（听书场景）; release() 显式回收（模型目录变更/测试）。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from services.voice_library import VoiceAsset as VoiceAssetT

logger = logging.getLogger(__name__)

# CosyVoice3-8bit 模型目录（自定义目录非 HF cache——局域网 rsync 部署 + 目录口径检测）
TTS_MODEL_DIR = Path(os.environ.get("OPENSECURITY_HOME",
                                    str(Path.home() / "bw-security-analysis"))) / "models" / "cosyvoice3-8bit"
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = _BACKEND_ROOT / "scripts" / "tts_worker.py"
WORKER_VENV_PY = _BACKEND_ROOT / ".venv-tts" / "bin" / "python"

DEFAULT_SPEED = 1.0
CACHE_LIMIT = 2048
CACHE_BYTES_LIMIT = 256 * 1024 * 1024  # 256MiB 字节预算（大 WAV 防撑爆内存）
MAX_TEXT_LEN = 2000
WORKER_TIMEOUT_SEC = 300.0  # 单请求上限（368 字实测 ~30s; 长文+冷启动余量）
# 空闲自动释放（对齐 OCR 的 idle 模式; TTS 模型加载重（冷 ~10s）→ 阈值比 OCR(600s) 长）
WORKER_IDLE_SEC = float(os.environ.get("TTS_WORKER_IDLE_SEC", "1800"))


class TtsUnavailable(RuntimeError):
    """TTS 不可用（模型缺失/依赖未装/合成失败统一面）。"""


@dataclass
class TtsResult:
    """合成结果（WAV 字节 + 路由元数据）。"""
    wav: bytes
    cached: bool
    gen_ms: float
    voice: str
    speed: float


@dataclass
class WorkerResponse:
    """worker 行协议响应（解析边界——dict 值域在 request 内消化定型）。"""
    ok: bool
    error: str = ""
    path: str = ""
    duration: float = 0.0


class TtsWorkerClient:
    """worker 子进程生命周期 + 行协议收发（线程安全——TtsService 全局锁内使用）。

    空闲自动释放: 每分钟检查 last_active，超 WORKER_IDLE_SEC 无请求 → kill
    （内存全归还; 下次请求冷启动 ~10s——听书间歇场景的内存/延迟平衡点）。
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None  # type: ignore[type-arg]
        self._lock = threading.Lock()
        self._last_active = 0.0
        self._idle_watchdog: threading.Timer | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure(self) -> "subprocess.Popen[str]":
        if self.alive and self._proc is not None:
            return self._proc
        if not self._venv_healthy():
            self._bootstrap_venv()
        if not (TTS_MODEL_DIR / "model.safetensors").is_file():
            raise TtsUnavailable(
                f"模型未就绪: 在控制台「环境总览→模型」下载 CosyVoice3，"
                f"或 rsync 模型目录到 {TTS_MODEL_DIR}")
        if self._proc is not None:
            self._kill()
        logger.info("[tts] 启动 worker（模型加载 ~10s）")
        self._proc = subprocess.Popen(  # noqa: S603 —— 固定脚本路径
            [str(WORKER_VENV_PY), str(WORKER_SCRIPT), "--model-dir", str(TTS_MODEL_DIR)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None,  # 继承主控 stderr（控制台日志文件）——worker 加载/崩溃可诊断
            text=True, bufsize=1,
        )
        return self._proc

    @staticmethod
    def _venv_healthy() -> bool:
        """.venv-tts 健康检查（非仅存在——半成品 venv（有解释器缺包）
        必须触发幂等补装，否则 worker 永远缺包。"""
        if not WORKER_VENV_PY.is_file():
            return False
        import subprocess as _sp
        r = _sp.run([str(WORKER_VENV_PY), "-c",
                     "from mlx_audio.tts.models.cosyvoice3 import cosyvoice3; import numpy"],
                    capture_output=True, timeout=60)  # noqa: S603 —— 固定 venv 解释器
        return r.returncode == 0

    @staticmethod
    def _bootstrap_venv() -> None:
        """.venv-tts 缺失时自愈安装（节点远程部署无手动通道——模型在位而
        依赖缺失的唯一解; uv+镜像 ~2-4min; 失败抛 TtsUnavailable）。"""
        installer = _BACKEND_ROOT / "scripts" / "install_tts_deps.sh"
        if not installer.is_file():
            raise TtsUnavailable(f"TTS 环境未就绪且缺安装脚本: {installer}")
        logger.info("[tts] .venv-tts 缺失 → 自愈安装（uv+镜像，2-4 分钟）")
        import subprocess as _sp
        r = _sp.run(["/bin/zsh", str(installer)], capture_output=True, text=True,
                    timeout=900)  # noqa: S603,S607 —— 固定项目脚本
        if r.returncode != 0 or not WORKER_VENV_PY.is_file():
            raise TtsUnavailable(
                f"TTS 环境自愈安装失败: {r.stdout[-400:]} {r.stderr[-400:]}")

    def request(self, payload: "dict[str, Any]") -> WorkerResponse:
        """一发一收（调用方持 TtsService 锁——串行天然成立）。超时杀进程。"""
        proc = self._ensure()
        self._last_active = time.monotonic()
        self._ensure_idle_watchdog()
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._kill()
            raise TtsUnavailable(f"worker 管道断开: {e}") from e
        timer = threading.Timer(WORKER_TIMEOUT_SEC, self._kill)
        timer.start()
        try:
            line = proc.stdout.readline()  # pyright: ignore[reportAny] —— text mode readline
        finally:
            timer.cancel()
        if not line:
            self._kill()
            raise TtsUnavailable(
                f"worker 无响应（超时 {WORKER_TIMEOUT_SEC:.0f}s 或崩溃——已回收，下次请求重启）")  # pyright: ignore[reportAny] —— line Any 透传
        try:
            parsed: object = json.loads(line)  # pyright: ignore[reportAny] —— json 解析边界
            raw = cast("dict[str, object]", parsed)
        except json.JSONDecodeError as e:
            self._kill()
            raise TtsUnavailable(f"worker 协议响应损坏: {line[:200]}") from e
        ok = raw.get("ok")
        err = raw.get("error", "")
        path = raw.get("path", "")
        dur = raw.get("duration", 0.0)
        return WorkerResponse(
            ok=bool(ok) if isinstance(ok, bool) else False,
            error=err if isinstance(err, str) else str(err),
            path=path if isinstance(path, str) else "",
            duration=float(dur) if isinstance(dur, (int, float)) else 0.0,
        )

    def _ensure_idle_watchdog(self) -> None:
        """单例看门狗（1min 周期; daemon 线程不阻退出）。"""
        if self._idle_watchdog is not None:
            return

        def _check() -> None:
            # 无锁读（60s 粒度检查; 竞态窗口≈检查点与请求更新 last_active 的
            # 微秒级交叠——即便误杀，请求侧 broken-pipe 自愈重启，无数据损失）
            self._idle_watchdog = None
            if (self._proc is not None and self._last_active > 0
                    and time.monotonic() - self._last_active > WORKER_IDLE_SEC):
                logger.info("[tts] 空闲 %.0fs → 释放 worker（内存归还; 下次请求冷启动 ~10s）",
                            WORKER_IDLE_SEC)
                self._kill()

        timer = threading.Timer(60.0, _check)
        timer.daemon = True
        timer.start()
        self._idle_watchdog = timer

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait(timeout=10)
            self._proc = None

    def shutdown(self) -> None:
        with self._lock:
            if self._idle_watchdog is not None:
                self._idle_watchdog.cancel()
                self._idle_watchdog = None
            self._kill()


class TtsService:
    """TTS 合成（缓存/远程路由/worker 本地推理三件套，全局单例）。"""

    _instance: "TtsService | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._cache: "OrderedDict[tuple[str, float, str], bytes]" = OrderedDict()
        self._lock = threading.Lock()
        self._worker = TtsWorkerClient()

    @classmethod
    def get_instance(cls) -> "TtsService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._worker.shutdown()
            cls._instance = None

    @property
    def engine_loaded(self) -> bool:
        """worker 存活即已加载（模型常驻 worker 内——懒启动语义）。"""
        return self._worker.alive

    # ── 合成 ─────────────────────────────────────────

    def synthesize(self, text: str, voice: str = "",
                   speed: float = DEFAULT_SPEED) -> TtsResult:
        """文本 → WAV 字节（LRU 命中标记 cached）。空文本 ValueError。

        voice: 音色库 id（空=默认音色）; speed: 1.0 原速, <1 服务端 atempo 减速。
        """
        from services.voice_library import VoiceLibrary, VoiceError
        text = text.strip()
        if not text:
            raise ValueError("文本为空")
        if len(text) > MAX_TEXT_LEN:
            raise ValueError(f"文本过长（{len(text)} > {MAX_TEXT_LEN}）")
        try:
            voice_asset = (VoiceLibrary.get_instance().get(voice)
                           if voice else VoiceLibrary.get_instance().default_voice())
        except VoiceError as e:
            raise TtsUnavailable(str(e)) from e
        if voice_asset is None:
            available = [v.id for v in VoiceLibrary.get_instance().list_voices()]
            raise ValueError(f"未知音色: {voice}（可选: {available}）")
        speed = min(max(speed, 0.5), 3.0)
        voice_id = voice_asset.id
        key = (voice_id, speed, text)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return TtsResult(wav=hit, cached=True, gen_ms=0.0,
                                 voice=voice_id, speed=speed)
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
                wav = client.tts_synth(text, voice_id, speed)
                return TtsResult(wav=wav, cached=False,
                                 gen_ms=(time.monotonic() - t0) * 1000,
                                 voice=voice_id, speed=speed)
            except RemoteUnavailable as e:
                try:
                    RemoteLinkService.get_instance().note_request_failure(f"tts: {e}")
                except Exception:  # noqa: BLE001
                    pass
                logger.warning("远程 tts 失败，fallback 本地: %s", e)
        wav, gen_ms = self._synth_local(text, voice_asset, speed)
        with self._lock:
            self._cache[key] = wav
            self._cache.move_to_end(key)
            while (len(self._cache) > CACHE_LIMIT
                   or sum(len(v) for v in self._cache.values()) > CACHE_BYTES_LIMIT):
                self._cache.popitem(last=False)
        return TtsResult(wav=wav, cached=False, gen_ms=gen_ms,
                         voice=voice_id, speed=speed)

    def _synth_local(self, text: str, voice_asset: "VoiceAssetT", speed: float) -> "tuple[bytes, float]":
        """本地 worker 合成（临时 wav → 字节; 音色文件随请求传递路径）。"""
        import tempfile
        t0 = time.monotonic()
        from services.voice_library import VoiceLibrary
        lib = VoiceLibrary.get_instance()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = tmp.name
        try:
            resp = self._worker.request({
                "id": f"tts-{time.monotonic_ns()}",
                "op": "synth",
                "text": text,
                "wav": str(voice_asset.resolved_wav(lib)),
                "ref_text": voice_asset.ref_text,
                "out": out_path,
                "speed": speed,
            })
            if not resp.ok:
                raise TtsUnavailable(f"worker 合成失败: {resp.error or '未知'}")
            wav = Path(resp.path or out_path).read_bytes()
            return wav, (time.monotonic() - t0) * 1000
        finally:
            Path(out_path).unlink(missing_ok=True)

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def release(self) -> None:
        """释放 worker 与缓存（模型目录变更后重载用）。"""
        with self._lock:
            self._worker.shutdown()
            self._cache.clear()


def _smoke_main(argv: "list[str]") -> int:
    """python -m services.tts_service --smoke "文本" [voice_id]。"""
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--smoke" not in argv:
        print("用法: python -m services.tts_service --smoke <文本> [voice_id]")
        return 2
    args = [a for a in argv[1:] if a != "--smoke"]
    text = args[0] if args else "你好，这是远程语音合成测试。"
    voice = args[1] if len(args) > 1 else ""
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
    sys.exit(_smoke_main(sys.argv))
