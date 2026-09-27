"""OCR 服务编排层（glm-ocr 生命周期，OcrService 类）。

架构：mcp-servers/ocr（FastMCP stdio 薄壳，不驻模型）
  └─ HTTP → routes/ocr.py → 本模块（编排）→ services/ocr_engines.py（引擎）
       ├─ macOS(Apple Silicon): MlxEngine 进程内加载（无子进程/无 pid 文件/无端口）
       └─ Windows/Linux: OllamaEngine HTTP（127.0.0.1:11434）

生命周期（收口到 services/model_lifecycle.ManagedModel）:
  • 状态机/单飞加载/排队卸载/空闲 reaper 全部由 ManagedModel 提供
    （本模块只做平台分支 + 两阶段 extract 编排 + 状态拼装）
  • extract(...):  未就绪自动懒加载（首图 ~1.6s）; 推理刷新活跃时间
  • 空闲超时卸载: READY 且空闲 >IDLE_RELEASE_SEC(600) → 卸载（还内存）
  • force_release(): 前端停止按钮（推理在途则排队等其完成）

并发安全（ManagedModel worker FIFO + 预处理并发）:
  • 使用并发（性能）: extract 的 preprocess（base64+PIL，纯 CPU）并行
    重叠; _infer_impl 段进 worker FIFO 排队（MLX Metal stream 是
    thread-local，GPU 串行是物理上限）
  • 三动作互斥: 使用/加载/卸载全在 worker FIFO——卸载排在在途推理后
    （等推理完成才动模型），加载与推理/卸载互斥，天然无竞争
  • 加载单飞: 并发 extract 懒加载等同一就绪事件; 成功不重复加载;
    失败回 idle，下次 extract 重新加载

推理超时语义: MLX generate 无中断 API，不做硬中断——max_tokens=4096 上界
（~400 tok/s 下 ≤20s）+ 推理耗时日志；客户端层（MCP/HTTP）超时自行断开。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import os
import platform
from dataclasses import dataclass

from services.model_lifecycle import ManagedModel
from services.ocr_engines import MlxEngine, OllamaEngine

logger = logging.getLogger(__name__)

IDLE_RELEASE_SEC = 600     # 纯空闲自动卸载窗口（用户确认 10 分钟）


@dataclass
class OcrStatus:
    """OCR 服务状态快照（GET /api/ocr/status 与模型页）。"""

    backend: str                  # mlx / ollama
    state: str                    # idle / starting / ready / stopping
    idle_release_sec: int
    last_activity_at: float | None
    error: str | None
    mlx_ready: bool               # 主环境可 import mlx_vlm（原 mlx_env_ready）
    model_cached: bool


class OcrService:
    """glm-ocr 生命周期编排（全局单例，get_instance() 获取）。

    引擎选择在构造时按平台定死; 生命周期经 ManagedModel（worker FIFO 串行）。
    """

    _instance: "OcrService | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "OcrService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "OcrService":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _init_once(self) -> None:
        self._mlx = MlxEngine()
        self._ollama = OllamaEngine()
        self._managed: ManagedModel | None = None  # 惰性（ollama 平台不需要）

    def _model(self) -> ManagedModel:
        """MLX 平台的受管模型（惰性构建; 名字固定 → worker 进程唯一）。"""
        if self._managed is None:
            self._managed = ManagedModel(
                name="glm-ocr",
                load_fn=self._load_mlx,
                unload_fn=self._mlx.unload,
                idle_timeout_sec=IDLE_RELEASE_SEC,
            )
        return self._managed

    def _load_mlx(self) -> None:
        """MLX 加载原语（ManagedModel worker 内执行）。"""
        self._mlx.load(MlxEngine.find_mlx_model() or "")

    # ─── 公开 API（routes/ocr.py 调用） ───────────────────

    async def extract(self, image_b64: str, prompt: str) -> str:
        """识图（远程路由 + 本地懒加载两阶段; 预处理段不持任何锁）。

        远程模式: 经远程节点推理（失败 fallback 本地——HOLD 语义）。
        本地: 未就绪自动加载（并发首图等同一就绪事件，单飞）;
        预处理并行重叠（to_thread），generate 在 ManagedModel worker
        FIFO 排队（MLX 物理串行）。

        Raises:
            RuntimeError: 加载失败 / 推理失败。
        """
        if self._backend() == "ollama":
            if not self._ollama.available():
                raise RuntimeError("Ollama 不可用或未拉取 glm-ocr（控制台模型页可下载）")
            text, _ = await self._ollama.infer(image_b64, prompt)
            return text
        # 远程路由（对 remote_link/remote_client 延迟 import——循环依赖防护）
        try:
            from services.remote_link import RemoteLinkService
            use_remote = RemoteLinkService.get_instance().should_use_remote()
        except Exception:  # noqa: BLE001 —— remote_link 未就绪 → 本地
            use_remote = False
        if use_remote:
            from services.remote_client import RemoteUnavailable
            try:
                client = RemoteLinkService.get_instance().get_client()
                return await asyncio.to_thread(client.ocr_extract, image_b64, prompt)
            except RemoteUnavailable as e:
                RemoteLinkService.get_instance().note_request_failure(f"ocr: {e}")
                logger.warning("远程 ocr 失败，fallback 本地: %s", e)
        # 阶段 1: 预处理（并发——纯 CPU，不进 worker 队列）
        prepared = await asyncio.to_thread(self._mlx.preprocess, image_b64, prompt)
        # 阶段 2: generate（ManagedModel: 确保加载 + worker FIFO 串行;
        # 卸载/加载与推理物理互斥）。patch 层次铁律: 经 _infer_impl
        # （worker 内执行层）——patch 公开投递层会绕过串行（历史假崩溃源）。
        text, _ = await asyncio.to_thread(
            self._model().run_inference, lambda: self._mlx._infer_impl(prepared))  # noqa: SLF001
        return text

    async def force_release(self) -> None:
        """强制卸载（前端模型页停止按钮）。推理在途则等其完成（FIFO 排队）。"""
        if self._backend() == "ollama":
            await self._ollama.unload()
        else:
            await asyncio.to_thread(self._model().release)

    def warm_up_sync(self) -> None:
        """预热（节点模式 / 远程降级预热用）: 只加载不推理。"""
        if self._backend() == "mlx":
            self._model().ensure_loaded()

    def release_sync(self) -> None:
        """同步卸载（remote_link 延迟卸载编排用，后台线程调用）。"""
        if self._backend() == "mlx" and self._managed is not None:
            self._managed.release()

    def status(self) -> OcrStatus:
        """状态快照（不持锁——字段原子性要求低，供轮询）。"""
        if self._backend() == "mlx":
            cached = MlxEngine.find_mlx_model() is not None
            m = self._managed.status() if self._managed is not None else None
            return OcrStatus(
                backend="mlx",
                state=m.state if m else ManagedModel.STATE_IDLE,
                idle_release_sec=IDLE_RELEASE_SEC,
                last_activity_at=None,  # 精确活动时刻不再单独追踪（idle_sec 提供口径）
                error=m.error if m else None,
                mlx_ready=MlxEngine.mlx_available(),
                model_cached=cached,
            )
        return OcrStatus(
            backend="ollama",
            state=ManagedModel.STATE_READY,
            idle_release_sec=IDLE_RELEASE_SEC,
            last_activity_at=None,
            error=None,
            mlx_ready=MlxEngine.mlx_available(),
            model_cached=self._ollama.available(),
        )

    def idle_sec(self) -> float | None:
        """当前已空闲秒数（模型页"空闲 X / 10 分钟"）。未加载 → None。"""
        if self._backend() != "mlx" or self._managed is None:
            return None
        return self._managed.idle_sec()

    def loaded_footprint_mb(self) -> float | None:
        """OCR 就绪时的控制台进程 footprint（进程页 in-process 内存口径）。"""
        if self._backend() == "mlx" and self._managed is not None and self._managed.is_loaded():
            return MlxEngine.footprint_mb()
        return None

    # ─── 工具 ─────────────────────────────────────────────

    @staticmethod
    def _backend() -> str:
        """平台分支：mlx / ollama。"""
        if platform.system() == "Darwin" and os.uname().machine == "arm64":
            return "mlx"
        return "ollama"


