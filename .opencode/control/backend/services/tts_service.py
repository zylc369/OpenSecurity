"""TTS 服务（CosyVoice3-8bit @ mlx-audio-plus 引擎，常驻 worker 子进程推理）。

架构:
  本地: TtsWorkerClient → 主 venv python scripts/tts_worker.py（stdin/stdout
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
import queue
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TYPE_CHECKING, Any, Callable, cast

from services import model_policy

if TYPE_CHECKING:  # 质检结果类型(运行时懒 import, 静态检查用)
    from scripts.tts_qc import QcResult as QcResultT

if TYPE_CHECKING:
    from services.voice_library import VoiceAsset as VoiceAssetT

logger = logging.getLogger(__name__)


def _ascii_alnum_ratio(text: str) -> float:
    """ASCII 字母/数字字符占比（高风险文本检测——ASR 对字母数字串转写天然
    随机, 质检必然误报; 音频本身无缺陷）。"""
    if not text:
        return 0.0
    n = sum(1 for c in text if c.isascii() and c.isalnum())
    return n / len(text)

_HOME = Path(os.environ.get("OPENSECURITY_HOME", str(Path.home() / "bw-security-analysis")))
# CosyVoice3 torch 模型目录（自定义目录非 HF cache——局域网 rsync 部署 + 目录口径检测）
TTS_MODEL_DIR = _HOME / "models" / "cosyvoice3-8bit"
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = _BACKEND_ROOT / "scripts" / "tts_worker.py"
# 主 venv 直跑（依赖已并入: torch 2.14/transformers 5.17/numpy 2.5 + TTS 依赖集）
import sys as _sys
WORKER_VENV_PY = Path(_sys.executable)

DEFAULT_SPEED = 1.0
CACHE_LIMIT = 2048
CACHE_BYTES_LIMIT = 256 * 1024 * 1024  # 256MiB 字节预算（大 WAV 防撑爆内存）
MAX_TEXT_LEN = 2000
WORKER_TIMEOUT_SEC = 300.0  # 单请求上限（368 字实测 ~30s; 长文+冷启动余量）
# 空闲自动释放阈值统一由 services/model_policy.py 策略表提供
# （cosyvoice3-8bit 默认 1800s; 节点场景经启动参数 --model-idle-sec ...=0 设常驻）


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
    source: str = "local"  # 生成来源（"remote"/"local"——缓存命中为生成时来源）


@dataclass
class WorkerResponse:
    """worker 行协议响应（解析边界——dict 值域在 request 内消化定型）。"""
    ok: bool
    error: str = ""
    path: str = ""
    duration: float = 0.0


class TtsWorkerClient:
    """worker 子进程生命周期 + 行协议收发（线程安全——TtsService 全局锁内使用）。

    空闲自动释放: 每分钟检查 last_active，超策略表阈值无请求 → kill
    （内存全归还; 下次请求冷启动 ~10s——听书间歇场景的内存/延迟平衡点;
    release_sec=None（常驻策略）时看门狗不启用）。
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None  # type: ignore[type-arg]
        self._lock = threading.Lock()
        self._last_active = 0.0
        self._idle_watchdog: threading.Timer | None = None
        self._idle_check_interval_sec: float = 60.0  # 空闲检查周期秒（单测注入小值）

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure(self) -> "subprocess.Popen[str]":
        if self.alive and self._proc is not None:
            return self._proc
        if not self._venv_healthy():
            raise TtsUnavailable(
                "TTS 引擎依赖缺失——安装职责在启动链(节点: ./start-remote-node.sh; "
                "主控: 控制台「Python 依赖」页或 install.sh), 运行时不自愈安装")
        _need = ("config.json", "model.safetensors")
        if not all((TTS_MODEL_DIR / f).is_file() for f in _need):
            raise TtsUnavailable(
                f"模型未就绪: 在控制台「环境总览→模型」下载，"
                f"或放置模型目录到 {TTS_MODEL_DIR}")
        if self._proc is not None:
            self._kill()
        logger.info("[tts] 启动 worker（模型加载 ~10s）")
        # worker 需从 HF 拉 8bit 模型目录之外的运行时小组件(campplus.onnx
        # speaker encoder / BlankEN 配置, 共 ~4MB)。server.py L26 的全局
        # 离线加速设计(setdefault HF_HUB_OFFLINE=1)会被 worker 继承 →
        # 组件 cache 未命中即崩。此处剥离 =1(与历史"下载子进程剥离
        # HF_HUB_OFFLINE"同一模式): worker 允许在线拉组件 + 镜像加速,
        # 首次拉取后命中本地 cache。
        import os as _os
        _ep = _os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
        # 诊断: 记录覆盖前 server 进程的原始值(worker 继承的真实来源)
        _parent_hf = _os.environ.get("HF_HUB_OFFLINE", "<unset>")
        logger.warning("[tts][诊断] server 环境 HF_HUB_OFFLINE=%s (worker 继承源, 已覆盖为 0)",
                       _parent_hf)
        env = {**_os.environ, "HF_HUB_OFFLINE": "0", "HF_ENDPOINT": _ep,
               "TTS_PARENT_HF_OFFLINE": _parent_hf,
               # tqdm 进度条转义序列会以二进制污染 stderr 日志——静音
               "HF_HUB_DISABLE_PROGRESS_BARS": "1", "TQDM_DISABLE": "1"}
        self._proc = subprocess.Popen(  # noqa: S603 —— 固定脚本路径
            [str(WORKER_VENV_PY), str(WORKER_SCRIPT), "--model-dir", str(TTS_MODEL_DIR)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None,  # 继承主控 stderr（控制台日志文件）——worker 加载/崩溃可诊断
            text=True, bufsize=1, env=env,
        )
        return self._proc

    @staticmethod
    def _venv_healthy() -> bool:
        """plus 引擎健康检查（mlx_audio import + plus/funasr/pypinyin 元数据探测——
        mlx-audio-plus 是补丁包无独立模块, 只能按 distribution 探测（
        必须触发幂等补装，否则 worker 永远缺包。"""
        if not WORKER_VENV_PY.is_file():
            return False
        import subprocess as _sp
        r = _sp.run([str(WORKER_VENV_PY), "-c",
                     "import mlx_audio; import importlib.metadata as _m; _m.version('mlx-audio-plus'); _m.version('funasr'); _m.version('pypinyin')"],
                    capture_output=True, timeout=120)  # noqa: S603 —— 主 venv 解释器
        return r.returncode == 0

    def request(self, payload: "dict[str, Any]") -> WorkerResponse:
        """一发一收（单 client 内一问一答由池取用语义保证——同一时刻至多
        一个调用方; 串行天然成立）。超时杀进程。"""
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
        """单例看门狗（1min 周期; daemon 线程不阻退出）。空闲释放阈值读
        策略表（None=常驻 → 不启用看门狗）。"""
        if self._idle_watchdog is not None:
            return
        release_sec = model_policy.release_sec_of("cosyvoice3-8bit")
        if release_sec is None:
            return  # 常驻策略: 不做空闲释放

        def _check() -> None:
            # 无锁读（60s 粒度检查; 竞态窗口≈检查点与请求更新 last_active 的
            # 微秒级交叠——即便误杀，请求侧 broken-pipe 自愈重启，无数据损失）
            self._idle_watchdog = None
            if (self._proc is not None and self._last_active > 0
                    and time.monotonic() - self._last_active > release_sec):
                logger.info("[tts] 空闲 %.0fs → 释放 worker（内存归还; 下次请求冷启动 ~10s）",
                            release_sec)
                self._kill()
                return
            # 未达阈值且 worker 存活 → 重排下一次检查（周期链式续期——
            # one-shot 不重排会导致阈值永达不到）
            if self._proc is not None:
                self._ensure_idle_watchdog()

        timer = threading.Timer(self._idle_check_interval_sec, _check)
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


LOCAL_WORKER_POOL_SIZE = 2  # 本地并行 worker 数（内存/GPU 平衡点: 每实例 ~1.3G 模型）


class TtsWorkerPool:
    """并行 worker 池: N 个独立 worker 进程 + 空闲取用（阻塞排队=背压）。

    接口与单 TtsWorkerClient 相同（request/alive/shutdown）——调用方与测试
    mock 零感知（`svc._worker.request` patch 点不变）。每 client 的空闲释放
    看门狗独立生效（闲者自清，下次请求冷启动自愈）。
    """

    def __init__(self, size: int = LOCAL_WORKER_POOL_SIZE) -> None:
        self._clients = [TtsWorkerClient() for _ in range(size)]
        self._free: "queue.Queue[TtsWorkerClient]" = queue.Queue()
        for c in self._clients:
            self._free.put(c)

    def request(self, payload: "dict[str, Any]") -> WorkerResponse:
        """取空闲 worker 一发一收（无空闲则阻塞排队——天然背压）。"""
        client = self._free.get()
        try:
            return client.request(payload)
        finally:
            self._free.put(client)

    @property
    def alive(self) -> bool:
        return any(c.alive for c in self._clients)

    @property
    def size(self) -> int:
        """池容量（预热覆盖范围/诊断用）。"""
        return len(self._clients)

    def warm_all(self, make_payload: "Callable[[int], dict[str, Any]]") -> int:
        """对池内每个 worker 各烧一次（取空闲+FIFO——启动无并发下逐一命中）。

        "预热覆盖范围"的唯一实现点: 池大小变化时本方法自动覆盖新容量
        （调用方无需知道 worker 数）。make_payload(i) 生成第 i 个 worker 的
        请求体。返回成功数（ok=false 不计）; 失败不抛（懒加载兜底）。
        """
        ok = 0
        n = len(self._clients)
        for i in range(n):
            client = self._free.get()
            try:
                resp = client.request(make_payload(i))
                if not resp.ok:  # worker 合成失败（ok=false 响应）不计成功
                    raise RuntimeError(f"worker 预热失败: {resp.error or '未知'}")
                ok += 1
            except Exception as e:  # noqa: BLE001 —— 单 worker 失败不阻塞其余
                logger.warning("[tts] worker 预热失败（第 %d/%d 个）: %r", i + 1, n, e)
            finally:
                self._free.put(client)
        return ok

    def shutdown(self) -> None:
        for c in self._clients:
            c.shutdown()


class TtsService:
    """TTS 合成（缓存/远程路由/worker 本地推理三件套，全局单例）。"""

    _instance: "TtsService | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._cache: "OrderedDict[tuple[str, float, str, int, str, str], tuple[bytes, str]]" = OrderedDict()
        # 并发结构（按资源分域）: 缓存细锁 / 本地信号量（容量=worker 池大小）/
        # 远程独立。本地域并发度由并行 worker 数决定（GPU 双实例实测平衡点）;
        # 远程等待（网络 IO）不占本地域（transport 并发安全, 节点侧自排队）。
        self._cache_lock = threading.Lock()          # 只包缓存读写（微秒级）
        # 本地推理域（含 fallback——统一入口）: 并发度=池大小（双 worker 并行）
        self._local_sem = threading.Semaphore(LOCAL_WORKER_POOL_SIZE)
        self._worker = TtsWorkerPool()

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

    @property
    def ready(self) -> bool:
        """TTS 就绪（本地 worker 存活 或 远程链路可用）——生命周期/UI 判定统一入口。

        合成请求远程优先: 远程在线时本地 worker 本就不启动, 但功能可用。
        """
        if self.engine_loaded:
            return True
        try:
            from services.remote_link import RemoteLinkService
            # 无锁只读: 本属性会被 status() 等"已持远程锁"的采集路径调用,
            # 走加锁接口会自死锁（非重入锁）
            return RemoteLinkService.get_instance().is_remote_active
        except Exception:  # noqa: BLE001 —— remote_link 未就绪 → 按本地判定
            return False

    # ── 合成 ─────────────────────────────────────────

    def warm_local_workers(self) -> int:
        """预热全部本地 worker 与质检链路（预热唯一入口）。

        调用方: 节点预载（--model-preload → model_ops.load）/降级接管（model_loader 预热线程）。
        覆盖范围: ① worker 池全量（warm_all——池大小变化自动跟随）
        ② 质检链路（收尾全链短合成触发 TtsQC/funasr 初始化——池预热只覆盖
        worker 进程, ASR ~1GB 懒加载在此提前烧掉）。全程持本地域许可（与
        合成/卸载互斥——不会被 release 半路杀; release 取满许可会等本预热完）。
        返回成功 worker 数; 失败不抛（懒加载兜底）。
        """
        import tempfile

        from services.voice_library import VoiceLibrary
        try:
            lib = VoiceLibrary.get_instance()
            va = lib.default_voice()
            wav_path = str(va.resolved_wav(lib))
            ref_text = va.ref_text
        except Exception as e:  # noqa: BLE001 —— 音色库不可用时放弃预热
            logger.warning("[tts] 预热跳过（音色库不可用）: %s", e)
            return 0

        outs: "list[str]" = []

        def _mk(i: int) -> "dict[str, Any]":
            out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
            outs.append(out)
            return {"id": f"warm-{i}-{time.monotonic_ns()}", "op": "synth",
                    "text": "好。", "wav": wav_path, "ref_text": ref_text,
                    "out": out, "speed": DEFAULT_SPEED, "instruct": "",
                    "seed": -1, "mode": ""}

        n = 0
        try:
            with self._local_sem:  # 与合成/卸载互斥（release 取满许可等本预热完）
                n = self._worker.warm_all(_mk)
                # 质检链路预热: 全链短合成一次（触发 TtsQC/funasr 初始化）
                try:
                    self._synth_qc_local("好。", va, DEFAULT_SPEED)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[tts] 质检链路预热失败（首听可能吃 ASR 冷加载）: %s", e)
        finally:
            for p in outs:
                Path(p).unlink(missing_ok=True)

        logger.info("[tts] 本地预热完成: worker %d/%d + 质检链路",
                    n, self._worker.size)
        return n

    def warmup(self) -> None:
        """预热: 全池本地 worker 各一次最短合成（模型加载 + 首跑编译）。

        调用方: 节点预载（--model-preload → model_ops.load）/降级接管
        （model_loader 预热线程）。覆盖范围由 warm_local_workers→池 warm_all
        保证（池大小变化自动跟随）。失败不抛（懒加载兜底——首请求自愈）。
        """
        try:
            self.warm_local_workers()
        except Exception as e:  # noqa: BLE001 —— 预热失败不致命
            logger.warning("[tts] 预热失败（懒加载兜底）: %s", e)

    def synthesize(self, text: str, voice: str = "",
                   speed: float = DEFAULT_SPEED,
                   instruct: str = "", seed: int = -1,
                   mode: str = "") -> TtsResult:
        """文本 → WAV 字节（LRU 命中标记 cached）。空文本 ValueError。

        voice: 音色库 id（空=默认音色）; speed: 1.0 原速, <1 服务端 atempo 减速。
        instruct: 朗读指令（空=引擎默认"请用正常语速朗读接下来的内容。"——测试台参数）。
        seed: 采样种子（≤0=默认 4; 同 seed 同参数输出等效可复现）。
        """
        from services.voice_library import VoiceLibrary, VoiceError
        t_enter = time.monotonic()
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
        key = (voice_id, speed, instruct, seed, mode, text)
        logger.info("[tts] 请求进入: %d字 voice=%s instruct=%r seed=%d mode=%r",
                    len(text), voice_id, instruct, seed, mode)
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                logger.info("[tts] 缓存命中, 直接返回（%.0fms）",
                            (time.monotonic() - t_enter) * 1000)
                return TtsResult(wav=hit[0], cached=True, gen_ms=0.0,
                                 voice=voice_id, speed=speed, source=hit[1])
        # 远程域（独立于本地域）: 远程等待为网络 IO, 不占本地队列
        # （四模型统一远程化——should_use_remote → 远程推理, 失败 fallback 本地;
        #  缓存命中不出本机）
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
                wav = client.tts_synth(text, voice_id, speed,
                                       instruct=instruct, seed=seed, mode=mode)
                # 质检回验在节点侧完整执行（节点本地链路自带质检 + 不合格派生
                # 种子重试——生产自检闭环）; 主控不再重复质检: 同代码同模型
                # 复核无增量——移除冗余层（此前代价: 首段冷加载 ~4s + 每段 ~1s）。
                # 本分支日志耗时为纯远程链路耗时。
                logger.info("[tts] 远程合成完成: %.0fms, 请求总耗时 %.0fms",
                            (time.monotonic() - t0) * 1000,
                            (time.monotonic() - t_enter) * 1000)
                return TtsResult(wav=wav, cached=False,
                                 gen_ms=(time.monotonic() - t0) * 1000,
                                 voice=voice_id, speed=speed,
                                 source="remote")
            except RemoteUnavailable as e:
                try:
                    RemoteLinkService.get_instance().note_request_failure(f"tts: {e}")
                except Exception:  # noqa: BLE001
                    pass
                logger.warning("远程 tts 失败，fallback 本地: %s", e)
        # 本地域（容量=池大小——本地路径与 fallback 统一入口）:
        # 单 client 内一问一答由池取用语义保证; 超出并发度的请求排队（背压）
        t_wait = time.monotonic()
        with self._local_sem:
            logger.info("[tts] 本地队列等待 %.0fms（进入后累计 %.0fms）",
                        (time.monotonic() - t_wait) * 1000,
                        (time.monotonic() - t_enter) * 1000)
            wav, gen_ms = self._synth_qc_local(text, voice_asset, speed,
                                               instruct=instruct, seed=seed,
                                               mode=mode)
            logger.info("[tts] 本地合成完成: 生成 %.0fms, 请求总耗时 %.0fms",
                        gen_ms, (time.monotonic() - t_enter) * 1000)
            # 缓存写入保持在域内: release() 的"取号→清缓存"原子性依赖
            # "域内无在途写"——写放域外会被卸载清空后回写（卸载残留旧条目）。
            with self._cache_lock:
                self._cache[key] = (wav, "local")
                self._cache.move_to_end(key)
                while (len(self._cache) > CACHE_LIMIT
                       or sum(len(v[0]) for v in self._cache.values()) > CACHE_BYTES_LIMIT):
                    self._cache.popitem(last=False)
        return TtsResult(wav=wav, cached=False, gen_ms=gen_ms,
                         voice=voice_id, speed=speed, source="local")

    def _qc_check(self, wav: bytes, text: str,
                  voice_asset: "VoiceAssetT") -> "QcResultT | None":
        """ASR 回验（懒加载——首次调用才初始化 Paraformer ~1GB）。

        返回 QcResult;质检系统不可用（funasr 缺失等）返回 None=放行
        （质量门是增强不是依赖——缺 ASR 不阻断合成）。
        高字母数字占比文本（如站点广告串）跳过质检: 参考含字母数字时 ASR
        转写为汉字/拼音变体, PER 必然超限——属质检不适用而非音频缺陷。
        """
        ratio = _ascii_alnum_ratio(text)
        if ratio > 0.25:
            logger.info("[tts] 高风险文本（字母数字占比 %.0f%%）, 跳过质检放行: %.20s…",
                        ratio * 100, text)
            return None
        import tempfile
        try:
            from scripts.tts_qc import TtsQC, QcConfig
        except Exception as e:  # noqa: BLE001 —— funasr/pypinyin 缺失
            logger.warning("[tts] 质检模块不可用，放行: %s", e)
            return None
        try:
            qc = TtsQC.instance()
            cfg = QcConfig()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav)
                p = tmp.name
            try:
                return qc.check(p, text, ref_text=voice_asset.ref_text, cfg=cfg)
            finally:
                Path(p).unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 —— 质检崩溃不阻断合成
            logger.warning("[tts] 质检执行异常，放行: %s", e)
            return None

    def _synth_qc_local(self, text: str, voice_asset: "VoiceAssetT",
                        speed: float, instruct: str = "",
                        seed: int = -1, mode: str = "") -> "tuple[bytes, float]":
        """本地合成 + 质量门 N 版重试（max_attempts 上限，全不合格兜底
        取 PER 最小者交付——不空手，日志可追）。QC 模块缺失时退化为单版直出。"""
        try:
            from scripts.tts_qc import QcConfig
            cfg = QcConfig()
        except Exception as e:  # noqa: BLE001 —— funasr/pypinyin 缺失
            logger.warning("[tts] 质检模块不可用，跳过质量门: %s", e)
            return self._synth_local(text, voice_asset, speed,
                                     instruct=instruct, seed=seed, mode=mode)
        best: "tuple[bytes, float, QcResultT] | None" = None  # (wav, ms, qc)
        prev_bad: "frozenset[str] | None" = None
        for attempt in range(1, cfg.max_attempts + 1):
            # 每版派生子种子: 同 seed 输出实质可复现（±浮点抖）, 不派生则
            # 重试产同版、质检永远无新样本可检（-1 也会因 +1 变非负而派生）
            wav, gen_ms = self._synth_local(text, voice_asset, speed,
                                            instruct=instruct,
                                            seed=seed + attempt - 1, mode=mode)
            logger.info("[tts] 第 %d 版生成 %.0fms, 开始质检", attempt, gen_ms)
            q = self._qc_check(wav, text, voice_asset)
            if q is None or q.ok:
                logger.info("[tts] 交付: 第 %d 版（%s）",
                            attempt, "首版通过" if attempt == 1 else "重试后通过")
                return wav, gen_ms
            logger.warning("[tts] 质检不合格(第 %d/%d 版): %s %s",
                           attempt, cfg.max_attempts, q.detail,
                           f"句定位={q.bad_sentences[:3]}" if q.bad_sentences else "")
            # 噪声主导提前交付: 连续两版失败句集合一致 → 差异源于 ASR 对
            # 特定句(方言/生僻)的系统性转写漂移而非随机 TTS 错(真错在 RAS
            # 补丁后随机分布, 句定位版间不同)——再重试只是浪费时间
            # 失败句集合比较用稳定键（去浮动 per——含 per 则每版必不相等,
            # 提前交付永不命中）; 旧字段兜底兼容
            cur_bad = frozenset(q.bad_keys if q.bad_keys
                                else tuple(s.split("…")[0] for s in q.bad_sentences[:3]))
            if attempt >= 2 and prev_bad is not None and cur_bad == prev_bad:
                logger.warning("[tts] 连续两版失败句一致——ASR 噪声主导, 提前交付(省 %d 版重试)",
                               cfg.max_attempts - attempt)
                logger.warning("[tts] 交付: 第 %d 版（噪声提前交付）", attempt)
                return wav, gen_ms
            prev_bad = cur_bad
            if best is None or q.per < best[2].per:
                best = (wav, gen_ms, q)
        logger.warning("[tts] %d 版均未过质检，兜底交付 PER 最小版", cfg.max_attempts)
        assert best is not None
        return best[0], best[1]

    def _synth_local(self, text: str, voice_asset: "VoiceAssetT", speed: float,
                     instruct: str = "", seed: int = -1,
                     mode: str = "") -> "tuple[bytes, float]":
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
                "instruct": instruct,
                "seed": seed,
                "mode": mode,
            })
            if not resp.ok:
                raise TtsUnavailable(f"worker 合成失败: {resp.error or '未知'}")
            wav = Path(resp.path or out_path).read_bytes()
            return wav, (time.monotonic() - t0) * 1000
        finally:
            Path(out_path).unlink(missing_ok=True)

    def cache_size(self) -> int:
        with self._cache_lock:
            return len(self._cache)

    def release(self) -> None:
        """释放 worker 与缓存（模型目录变更后重载用）。

        先取满本地域全部许可（等在途本地合成全部完成后才关 worker——卸载
        排队语义; 池化后须取满容量, 取 1 只能挡住并发中的一路）; 缓存清理
        走缓存锁（取满后域内无在途写——清后无回写残留）。
        """
        for _ in range(LOCAL_WORKER_POOL_SIZE):
            self._local_sem.acquire()
        try:
            self._worker.shutdown()
            with self._cache_lock:
                self._cache.clear()
        finally:
            for _ in range(LOCAL_WORKER_POOL_SIZE):
                self._local_sem.release()


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
