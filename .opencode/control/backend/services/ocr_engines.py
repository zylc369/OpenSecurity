"""OCR 引擎层：MLX（进程内）与 Ollama（HTTP）两种实现。

编排（锁/状态机/引用计数）在 services/ocr_service.py 的 OcrService；
本模块只做"单次推理原语"，不持有锁——并发安全由编排层的单锁保证。

实测依据（2026-08-22, 主 venv, GLM-OCR-4bit, M-series）:
  load ~0.3s（safetensors mmap + NVMe）; generate 396 tok/s;
  unload = del + mx.clear_cache() 归还 1.2GB 权重（92%），推理足迹稳态 ~380MB 无泄漏。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import importlib.util
import logging
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_MODEL = "glm-ocr"
DEFAULT_PROMPT = "Extract all text from this image. Output text only."
MAX_TOKENS = 4096


@dataclass
class GenerationStats:
    """单次推理的耗时画像（日志与排查用）。"""

    elapsed_sec: float
    output_chars: int


def mlx_available() -> bool:
    """主 venv 是否可 import mlx_vlm（不执行模块代码，find_spec 探测）。"""
    return importlib.util.find_spec("mlx_vlm") is not None


def find_mlx_model() -> str | None:
    """HF 缓存定位 GLM-OCR-4bit snapshot 目录。"""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    for d in hub.glob("models--mlx-community--GLM-OCR-4bit/snapshots/*"):
        if (d / "model.safetensors").exists() or (d / "model.safetensors.index.json").exists():
            return str(d)
    return None


@dataclass
class PreparedOcrInput:
    """预处理产物（extract 并发阶段输出，infer_serialized 输入）。

    并发侧只做纯 CPU（base64 解码 + PIL 解析）——apply_chat_template
    可能 touch processor/model 的 MLX 状态，与 generate 一样必须在
    worker 线程执行（thread-local stream 约束），故模板在 _infer_impl 内做。
    """

    text_prompt: str   # 原始指令（模板前的用户 prompt）
    image: object      # PIL.Image（RGB）


def footprint_mb() -> float | None:
    """当前进程 Physical footprint（MB，与活动监视器同口径，含 Metal 映射）。

    非 macOS 或 vmmap 失败返回 None（调用方按缺失处理，不得用于断言）。
    与 process_registry._footprint_mb 同源实现（第 3 处出现时收口到公共模块）。
    """
    import os as _os
    import sys as _sys
    if _sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["/usr/bin/vmmap", "--summary", str(_os.getpid())],
            capture_output=True, text=True, timeout=30,
        ).stdout
        m = re.search(r"Physical footprint:\s+([\d.]+)([GMK])", out)
        if not m:
            return None
        v, u = float(m.group(1)), m.group(2)
        return round(v * 1024 if u == "G" else v if u == "M" else v / 1024, 1)
    except (OSError, subprocess.TimeoutExpired):
        return None


class _MlxWorker:
    """MLX 专职执行线程——load/generate/unload 全部经它串行执行。

    为什么必须单线程（两层实测证据）:
      1. MLX Metal stream 是 thread-local——模型在 A 线程 load、B 线程
         generate → RuntimeError: There is no Stream(gpu, N) in current thread
         （跨线程尚且如此，多线程并发更必崩且非确定性）
      2. 因此"哪个线程执行 MLX"不能交给 asyncio.to_thread 的池调度——
         池线程复用是概率行为，旧实现串行场景偶然同线程才没崩（潜伏炸弹）。

    worker 常驻（daemon）: unload 后线程保留，stream 初始化复用，下轮加载更稳。
    队列 FIFO = 物理串行点（generate 之间、generate 与 load/unload 之间天然互斥）。
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[object, concurrent.futures.Future]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="mlx-worker",
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            fn, fut = self._queue.get()
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 —— 异常全部回传调用方
                fut.set_exception(e)

    def call(self, fn):
        """投递到 worker 线程执行并阻塞等结果。

        调用方应在普通线程（如 asyncio.to_thread 的池线程）——不得在
        事件循环线程直接调（会阻塞循环）。
        """
        self._ensure_started()
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._queue.put((fn, fut))
        return fut.result()


_WORKER_SINGLETON: _MlxWorker | None = None
_WORKER_SINGLETON_LOCK = threading.Lock()


def _global_mlx_worker() -> _MlxWorker:
    """进程级唯一 MLX worker（懒初始化）。

    为什么必须进程单例（实测三层证据，2026-08-22）:
      1. Metal stream 绑定线程——模型在 A 线程 load、B 线程 generate →
         RuntimeError: There is no Stream(gpu, N)
      2. 多个 MLX 线程并存时 stream 初始化非确定性竞争——部分线程能初始化
         部分直接崩（双线程 1/2 成功、三线程 2/3 成功、第二/三个 worker
         线程 0/3 成功，均为同错）
      3. 因此"哪个线程碰 MLX"必须收敛为进程内唯一常驻线程——所有引擎
         实例（含测试多实例）共享同一 worker，load/unload/generate 永远
         同线程，stream 一次初始化终身复用（unload→load 循环实测同线程稳定）
    """
    global _WORKER_SINGLETON
    with _WORKER_SINGLETON_LOCK:
        if _WORKER_SINGLETON is None:
            _WORKER_SINGLETON = _MlxWorker()
        return _WORKER_SINGLETON


class MlxEngine:
    """进程内 MLX 推理引擎（macOS Apple Silicon 分支）。

    生命周期: load() → preprocess()×N(并发) / infer_serialized()×N(worker 串行) → unload()。
    load/infer_serialized/unload 为同步阻塞（投递 _MlxWorker 执行），
    编排层必须经 asyncio.to_thread 调用（不在事件循环线程直接调）。

    线程安全分层:
      • preprocess: 纯 CPU + 只读 processor/model.config（PIL 解码 + chat
        template），可多线程并发——多请求的预处理重叠执行
      • load / infer_serialized / unload: 经 _MlxWorker 单线程执行
        （thread-local stream 约束 + FIFO 串行），与调用线程无关
    """

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._worker = _global_mlx_worker()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, model_path: str) -> None:
        """加载模型（投递 worker 执行，~0.3s）。失败抛 RuntimeError（用户可读原因）。"""
        if self.loaded:
            return
        self._worker.call(lambda: self._load_impl(model_path))

    def _load_impl(self, model_path: str) -> None:
        """实际加载（仅在 worker 线程执行）。"""
        if self.loaded:
            return
        if not mlx_available():
            raise RuntimeError("主环境缺 mlx-vlm（依赖页可安装）")
        if not Path(model_path).is_dir():
            raise RuntimeError(f"模型快照缺失: {model_path}（控制台模型页可下载）")
        before = footprint_mb()
        t0 = time.monotonic()
        try:
            from mlx_vlm import load as _load
            self._model, self._processor = _load(model_path)
        except Exception as e:
            self._model = self._processor = None
            raise RuntimeError(f"MLX 模型加载失败: {e}") from e
        after = footprint_mb()
        logger.info("MLX load: %.2fs, footprint %s→%s MB, model=%s",
                    time.monotonic() - t0, before, after, Path(model_path).name)

    def preprocess(self, image_b64: str, prompt: str) -> PreparedOcrInput:
        """预处理（可并发）: base64 解码 + PIL 解析 + chat template。

        防御: b64 损坏/图异常 → RuntimeError。
        """
        import base64
        import io
        try:
            raw = base64.b64decode(image_b64, validate=True)
        except Exception as e:
            raise RuntimeError(f"图片 base64 解码失败: {e}") from e
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as im:
                image = im.convert("RGB")
        except Exception as e:
            raise RuntimeError(f"图片解析失败: {e}") from e
        return PreparedOcrInput(text_prompt=prompt or DEFAULT_PROMPT, image=image)

    def infer_serialized(self, prepared: PreparedOcrInput) -> GenerationStats:
        """串行推理段（投递 worker FIFO 执行）。返回耗时画像。

        防御: 未加载 → RuntimeError（worker 内检查，覆盖竞争窗口）；
        generate 异常 → RuntimeError。
        """
        return self._worker.call(lambda: self._infer_impl(prepared))

    def _infer_impl(self, prepared: PreparedOcrInput):
        """实际推理（仅在 worker 线程执行: 模板 + generate）。"""
        if not self.loaded:
            raise RuntimeError("MLX 引擎未加载（需先 acquire）")
        t0 = time.monotonic()
        try:
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm import generate as _generate
            text_prompt = apply_chat_template(
                self._processor, self._model.config,
                prepared.text_prompt, num_images=1,
            )
            result = _generate(
                self._model, self._processor, text_prompt, prepared.image,
                max_tokens=MAX_TOKENS, verbose=False,
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"MLX 推理失败: {e}") from e
        stats = GenerationStats(
            elapsed_sec=round(time.monotonic() - t0, 2),
            output_chars=len(result.text),
        )
        logger.info("MLX infer: %ss, %d chars", stats.elapsed_sec, stats.output_chars)
        return result.text, stats

    def infer(self, image_b64: str, prompt: str) -> tuple[str, GenerationStats]:
        """单步便捷入口（预处理+推理）。测试/独立调用用；服务路径走两阶段。"""
        prepared = self.preprocess(image_b64, prompt)
        return self.infer_serialized(prepared)  # type: ignore[return-value]

    def unload(self) -> None:
        """卸载（投递 worker FIFO——排在在途推理之后，~35ms）。幂等。"""
        self._worker.call(self._unload_impl)

    def _unload_impl(self) -> None:
        """实际卸载（仅在 worker 线程执行）: del 权重 + mx.clear_cache() 归还 OS。"""
        if not self.loaded:
            return
        before = footprint_mb()
        self._model = self._processor = None
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception as e:  # clear_cache 失败不影响语义（仅缓存残留）
            logger.warning("MLX clear_cache 异常（忽略，仅缓存残留）: %s", e)
        gc.collect()
        after = footprint_mb()
        logger.info("MLX unload: footprint %s→%s MB", before, after)


class OllamaEngine:
    """Ollama HTTP 引擎（win/linux/intel-mac 分支，进程外服务）。"""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=180.0)

    @property
    def loaded(self) -> bool:
        """Ollama 无常驻句柄——以模型在服务端为准（available 即用）。"""
        return True

    def available(self) -> bool:
        """服务端是否已有 glm-ocr 模型。"""
        try:
            r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3.0)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return any(n.split(":")[0] == OLLAMA_MODEL for n in names)
        except (httpx.HTTPError, ValueError):
            return False

    async def infer(self, image_b64: str, prompt: str) -> tuple[str, GenerationStats]:
        t0 = time.monotonic()
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt or DEFAULT_PROMPT,
            "images": [image_b64],
            "stream": False,
            "keep_alive": "30s",
            "options": {"temperature": 0},
        }
        r = await self._http.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        r.raise_for_status()
        text = r.json().get("response", "")
        stats = GenerationStats(
            elapsed_sec=round(time.monotonic() - t0, 2),
            output_chars=len(text),
        )
        logger.info("Ollama infer: %ss, %d chars", stats.elapsed_sec, stats.output_chars)
        return text, stats

    async def unload(self) -> None:
        """Ollama 显式卸载（keep_alive=0；不动 Ollama 进程）。"""
        try:
            await self._http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": OLLAMA_MODEL, "keep_alive": 0, "prompt": ""},
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            logger.warning("Ollama unload 请求失败（忽略）: %s", e)
