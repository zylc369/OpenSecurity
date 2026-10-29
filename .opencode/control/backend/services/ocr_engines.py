"""OCR 引擎层：MLX（进程内）与 Ollama（HTTP）两种实现。

编排（状态机/单飞/空闲卸载）在 services/model_lifecycle.py 的 ManagedModel；
本模块只做"单次推理原语"（纯实现），不持锁不投递队列——并发安全与
执行线程约束由 ManagedModel 的 worker FIFO 保证（load/infer/unload
全部在同一线程执行，MLX thread-local stream 约束天然满足）。

实测依据（2026-08-22, 主 venv, GLM-OCR-4bit, M-series）:
  load ~0.3s（safetensors mmap + NVMe）; generate 396 tok/s;
  unload = del + mx.clear_cache() 归还 1.2GB 权重（92%），推理足迹稳态 ~380MB 无泄漏。
"""
from __future__ import annotations
from typing import Protocol, TypedDict, cast

import gc
import importlib.util
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# 模块级 logger（原 MlxEngine/OllamaEngine 两处类体绑定合并——类命名空间
# 不在方法名字查找链; 日志名统一 .ocr_engines）
logger = logging.getLogger(__name__)

import httpx

class _OllamaTagEntry(TypedDict, total=False):
    """ollama /api/tags 条目（解析边界模型）。"""
    name: str


class _OllamaTags(TypedDict, total=False):
    models: "list[_OllamaTagEntry]"


class _OllamaGenerate(TypedDict, total=False):
    """ollama /api/generate 响应（解析边界模型）。"""
    response: str




@dataclass
class GenerationStats:
    """单次推理的耗时画像（日志与排查用）。"""

    elapsed_sec: float
    output_chars: int


@dataclass
class PreparedOcrInput:
    """预处理产物（extract 并发阶段输出，推理段输入）。

    并发侧只做纯 CPU（base64 解码 + PIL 解析）——apply_chat_template
    可能 touch processor/model 的 MLX 状态，与 generate 一样必须在
    worker 线程执行（thread-local stream 约束），故模板在 _infer_impl 内做。
    """

    text_prompt: str   # 原始指令（模板前的用户 prompt）
    image: object      # PIL.Image（RGB）


class _MlxModelLike(Protocol):
    """mlx_vlm Apple-only：Linux CI 无此包——最小表面 Protocol 收口。"""

    @property
    def config(self) -> object: ...


class _MlxGenResult(Protocol):
    text: str


class _MlxGenerateFn(Protocol):
    def __call__(self, model: "_MlxModelLike", processor: object,
                 prompt: str, image: object, *,
                 max_tokens: int, verbose: bool) -> "_MlxGenResult": ...


class MlxEngine:
    """进程内 MLX 推理引擎（macOS Apple Silicon 分支）。

    纯实现层: load/unload/_infer_impl 直接执行（不投递队列）——调用方
    （ManagedModel 的 worker FIFO）保证它们在专职线程串行执行。
    编排层必须经 asyncio.to_thread 调用（不在事件循环线程直接调）。
    MLX 环境支撑设施（可用性探测/模型定位/footprint）为类静态方法。

    线程安全分层:
      • preprocess: 纯 CPU + 只读 processor/model.config（PIL 解码 + chat
        template），可多线程并发——多请求的预处理重叠执行
      • load / _infer_impl / unload: 由 ManagedModel 的 worker 单线程执行
        （thread-local stream 约束 + FIFO 串行），与调用线程无关
    """

    MAX_TOKENS = 4096
    DEFAULT_PROMPT = "Extract all text from this image. Output text only."

    def __init__(self) -> None:
        self._model: "_MlxModelLike | None" = None
        self._processor: "object | None" = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @staticmethod
    def mlx_available() -> bool:
        """主 venv 是否可 import mlx_vlm（不执行模块代码，find_spec 探测）。"""
        return importlib.util.find_spec("mlx_vlm") is not None

    @staticmethod
    def find_mlx_model() -> str | None:
        """HF 缓存定位 GLM-OCR-4bit snapshot 目录。"""
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        for d in hub.glob("models--mlx-community--GLM-OCR-4bit/snapshots/*"):
            if (d / "model.safetensors").exists() or (d / "model.safetensors.index.json").exists():
                return str(d)
        return None

    @staticmethod
    def footprint_mb() -> float | None:
        """当前进程 Physical footprint（MB，与活动监视器同口径，含 Metal 映射）。

        非 macOS 或 vmmap 失败返回 None（调用方按缺失处理，不得用于断言）。
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

    def load(self, model_path: str) -> None:
        """加载模型（~0.3s）。失败抛 RuntimeError（用户可读原因）。幂等。"""
        if self.loaded:
            return
        if not self.mlx_available():
            raise RuntimeError("主环境缺 mlx-vlm（依赖页可安装）")
        if not Path(model_path).is_dir():
            raise RuntimeError(f"模型快照缺失: {model_path}（控制台模型页可下载）")
        before = self.footprint_mb()
        t0 = time.monotonic()
        try:
            from mlx_vlm import load as _load  # pyright: ignore[reportPrivateImportUsage, reportUnknownMemberType, reportUnknownVariableType]  mlx_vlm 无类型标注
            loaded_model, loaded_processor = _load(model_path)  # pyright: ignore[reportUnknownVariableType] —— Linux CI 无 mlx_vlm（本地有真类型）
            self._model = cast("_MlxModelLike", loaded_model)  # mlx.nn.Module 的 config 为运行期挂载——最小 Protocol 收口
            self._processor = loaded_processor
        except Exception as e:
            self._model = self._processor = None
            raise RuntimeError(f"MLX 模型加载失败: {e}") from e
        after = self.footprint_mb()
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
        return PreparedOcrInput(text_prompt=prompt or self.DEFAULT_PROMPT, image=image)

    def _infer_impl(self, prepared: PreparedOcrInput) -> "tuple[str, GenerationStats]":
        """串行推理段（ManagedModel worker 内执行）。返回耗时画像。

        防御: 未加载 → RuntimeError（worker 内检查，覆盖竞争窗口）；
        generate 异常 → RuntimeError。
        """
        model = self._model
        processor = self._processor
        if model is None or processor is None:
            raise RuntimeError("MLX 引擎未加载（推理窗口内被卸载，请重试）")
        t0 = time.monotonic()
        try:
            from mlx_vlm.prompt_utils import apply_chat_template  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] —— mlx_vlm 无类型标注
            from mlx_vlm import generate as _generate  # pyright: ignore[reportPrivateImportUsage, reportUnknownVariableType]  mlx_vlm 未声明 __all__/Linux CI 无此包
            text_prompt = cast("str", apply_chat_template(  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType, reportUnknownMemberType] —— mlx_vlm 无类型标注（库级）
                processor, model.config,
                prepared.text_prompt, num_images=1,
            ))
            generate_fn = cast("_MlxGenerateFn", _generate)  # mlx_vlm 无类型标注——最小 Protocol 收口
            result = generate_fn(
                model, processor, text_prompt, prepared.image,
                max_tokens=self.MAX_TOKENS, verbose=False,
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

    def unload(self) -> None:
        """卸载: del 权重 + mx.clear_cache() 归还 OS（~35ms）。幂等。"""
        if not self.loaded:
            return
        before = self.footprint_mb()
        self._model = self._processor = None
        try:
            import mlx.core as mx
            mx.clear_cache()  # pyright: ignore[reportUnknownMemberType] —— mlx Apple-only（Linux CI 无此包）
        except Exception as e:  # clear_cache 失败不影响语义（仅缓存残留）
            logger.warning("MLX clear_cache 异常（忽略，仅缓存残留）: %s", e)
        gc.collect()
        after = self.footprint_mb()
        logger.info("MLX unload: footprint %s→%s MB", before, after)


class OllamaEngine:
    """Ollama HTTP 引擎（win/linux/intel-mac 分支，进程外服务）。"""

    OLLAMA_BASE = "http://127.0.0.1:11434"
    OLLAMA_MODEL = "glm-ocr"

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=180.0)

    @property
    def loaded(self) -> bool:
        """Ollama 无常驻句柄——以模型在服务端为准（available 即用）。"""
        return True

    def available(self) -> bool:
        """服务端是否已有 glm-ocr 模型。"""
        try:
            r = httpx.get(f"{self.OLLAMA_BASE}/api/tags", timeout=3.0)
            tags = cast("_OllamaTags", r.json())
            names = [m.get("name", "") for m in tags.get("models", [])]
            return any(n.split(":")[0] == self.OLLAMA_MODEL for n in names)
        except (httpx.HTTPError, ValueError):
            return False

    async def infer(self, image_b64: str, prompt: str) -> tuple[str, GenerationStats]:
        t0 = time.monotonic()
        payload: "dict[str, object]" = {
            "model": self.OLLAMA_MODEL,
            "prompt": prompt or MlxEngine.DEFAULT_PROMPT,
            "images": [image_b64],
            "stream": False,
            "keep_alive": "30s",
            "options": {"temperature": 0},
        }
        r = await self._http.post(f"{self.OLLAMA_BASE}/api/generate", json=payload)
        r.raise_for_status()
        text = cast("_OllamaGenerate", r.json()).get("response", "")
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
                f"{self.OLLAMA_BASE}/api/generate",
                json={"model": self.OLLAMA_MODEL, "keep_alive": 0, "prompt": ""},
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            logger.warning("Ollama unload 请求失败（忽略）: %s", e)
