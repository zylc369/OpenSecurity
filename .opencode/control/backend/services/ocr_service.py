"""OCR 服务编排层（glm-ocr 生命周期，OcrService 类）。

架构：mcp-servers/ocr（FastMCP stdio 薄壳，不驻模型）
  └─ HTTP → routes/ocr.py → 本模块（编排）→ services/ocr_engines.py（引擎）
       ├─ macOS(Apple Silicon): MlxEngine 进程内加载（无子进程/无 pid 文件/无端口）
       └─ Windows/Linux: OllamaEngine HTTP（127.0.0.1:11434）

并发安全（lifecycle 锁 + MLX 专职 worker 线程）:
  _lifecycle_lock（asyncio）: 状态变更独占——懒加载路径 / force_release /
                              reaper 卸载路径
  _MlxWorker（引擎内，FIFO 单线程）: load/generate/unload 的物理串行点。

  • 使用并发（性能）: extract 不持 lifecycle——多请求并发进入，预处理
    （base64+PIL，线程安全）并行重叠；generate 段进 worker FIFO 排队
    （MLX Metal stream 是 thread-local，多线程并发推理实测必崩——GPU 串行
    是物理上限，并发收益 = 预处理重叠 + 推理不阻塞懒加载/status）
  • 三动作互斥: 使用/加载/卸载都汇聚到 worker FIFO——卸载排在在途推理后
    （等推理完成才动模型），加载与推理/卸载互斥，天然无竞争
  • 加载单飞: 并发 extract 懒加载等同一 ready 事件；成功不重复加载；
    失败回 idle，下次 extract 重新加载
  • 竞争窗口（设计内，引擎层防御兜底）: extract 过 ready 检查后模型被
    reaper 卸载且无新 load → generate 提交时引擎 loaded 检查（worker 内
    执行）报"未就绪"，客户端重试即可（仅在空闲超时窗口触发，极低）

生命周期（纯空闲超时，无引用计数）:
  extract(...)       → 未就绪则懒加载（首图 ~1.6s）; 推理刷新活跃时间
  reaper 协程每 5s:  READY 且空闲 >IDLE_RELEASE_SEC(600) → 卸载（还内存）
  force_release()    → 前端停止按钮（推理在途则等其完成）

  推理超时语义: MLX generate 无中断 API，不做硬中断——max_tokens=4096 上界
  （~400 tok/s 下 ≤20s）+ 推理耗时日志；客户端层（MCP/HTTP）超时自行断开。
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from dataclasses import dataclass

from services.ocr_engines import (
    MlxEngine,
    OllamaEngine,
    find_mlx_model,
    footprint_mb,
    mlx_available,
)

logger = logging.getLogger(__name__)

IDLE_RELEASE_SEC = 600     # 纯空闲自动卸载窗口（用户确认 10 分钟）
REAPER_INTERVAL_SEC = 5    # 后台清理协程周期

STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_READY = "ready"
STATE_STOPPING = "stopping"


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
    """glm-ocr 生命周期编排（模块级单例 ocr_service）。

    引擎选择在构造时按平台定死；状态变更与推理全部经 _lock 串行化。
    """

    def __init__(self) -> None:
        self._lifecycle_lock = asyncio.Lock()   # 状态变更独占（GPU 串行由引擎 worker FIFO 保证）
        self._state: str = STATE_IDLE
        self._mlx = MlxEngine()
        self._ollama = OllamaEngine()
        self._ready_event: asyncio.Event | None = None
        self._last_activity_at: float = 0.0
        self._error: str = ""
        self._reaper_task: asyncio.Task | None = None

    # ─── 公开 API（routes/ocr.py 调用） ───────────────────

    async def extract(self, image_b64: str, prompt: str) -> str:
        """识图（懒加载 + 并发使用——推理段不持 lifecycle 锁）。

        未就绪时自动加载（并发首图等同一就绪事件，单飞）。
        多请求并发: 预处理并行重叠（to_thread），generate 在引擎 worker
        FIFO 排队（MLX 物理串行）。进入与完成都刷新活跃时间。

        Raises:
            RuntimeError: 加载失败 / 竞争窗口内模型被卸载 / 推理失败。
        """
        self._last_activity_at = time.time()
        if self._backend() == "ollama":
            if not self._ollama.available():
                raise RuntimeError("Ollama 不可用或未拉取 glm-ocr（控制台模型页可下载）")
            text, _ = await self._ollama.infer(image_b64, prompt)
            self._last_activity_at = time.time()
            return text
        await self._ensure_ready()
        # 阶段 1: 预处理（并发——不持任何锁）
        prepared = await asyncio.to_thread(self._mlx.preprocess, image_b64, prompt)
        # 阶段 2: generate（经 to_thread 提交 worker FIFO——与 load/unload 互斥）
        text, _ = await asyncio.to_thread(self._mlx.infer_serialized, prepared)
        self._last_activity_at = time.time()
        return text

    async def force_release(self) -> None:
        """强制卸载（前端模型页停止按钮）。推理在途则等其完成（锁互斥）。"""
        async with self._lifecycle_lock:
            if self._backend() == "ollama":
                await self._ollama.unload()
            else:
                await self._stop_locked()

    def status(self) -> OcrStatus:
        """状态快照（不持锁——字段原子性要求低，供轮询）。"""
        if self._backend() == "mlx":
            cached = find_mlx_model() is not None
        else:
            cached = self._ollama.available()
        return OcrStatus(
            backend=self._backend(),
            state=self._state,
            idle_release_sec=IDLE_RELEASE_SEC,
            last_activity_at=self._last_activity_at or None,
            error=self._error or None,
            mlx_ready=mlx_available(),
            model_cached=cached,
        )

    def idle_sec(self) -> float | None:
        """当前已空闲秒数（模型页"空闲 X / 10 分钟"）。未加载 → None。"""
        if self._state != STATE_READY or self._last_activity_at <= 0:
            return None
        return max(0.0, time.time() - self._last_activity_at)

    def loaded_footprint_mb(self) -> float | None:
        """OCR 就绪时的控制台进程 footprint（进程页 in-process 内存口径）。"""
        if self._backend() == "mlx" and self._state == STATE_READY:
            return footprint_mb()
        return None

    # ─── 内部: 状态变更（必须持锁） ────────────────────────

    async def _ensure_ready(self) -> None:
        """懒加载入口（extract 调用）。未就绪则加载，并发单飞。

        Raises:
            RuntimeError: 加载失败（环境缺失/模型未缓存/底层异常）/ 状态机异常。
        """
        self._ensure_reaper()
        async with self._lifecycle_lock:
            if self._state == STATE_READY:
                return
            if self._state == STATE_STOPPING:
                # 不可达防御: STOPPING 只在 _stop_locked 持锁期间存在，
                # 锁被本方法拿到时状态必已离开 STOPPING。若真到达说明状态机损坏。
                raise RuntimeError(f"OCR 状态机异常: stopping 态不可达（state={self._state}）")
            if self._state == STATE_IDLE:
                await self._start_mlx_locked()    # 持锁加载（内部 to_thread）
                event = self._ready_event
            else:                                  # starting: 搭车等同一事件
                event = self._ready_event
                logger.info("OCR 懒加载: 已有加载在途，并发等待")
        if event is not None:
            await event.wait()
            async with self._lifecycle_lock:
                if self._error:
                    self._cleanup_failed_start_locked()
                    raise RuntimeError(self._error)
                if self._state == STATE_STARTING:
                    # 仅在加载成果未被中途卸载时置 READY。
                    # 防竞态: force_release 可能在"加载完成 → 本处置 READY"窗口
                    # 抢到锁完成卸载（state 已回 IDLE）——此时不得把 IDLE 翻成
                    # READY（引擎已空，假 READY 会让懒加载快路径失效）。
                    # 等待者直接返回；引擎空由 extract 的 loaded 防御兜住，
                    # 下次 extract 走 IDLE 分支重新加载，自愈。
                    self._state = STATE_READY

    async def _start_mlx_locked(self) -> None:
        """idle → starting → (to_thread → worker 加载)。持 lifecycle 锁调用。"""
        self._state = STATE_STARTING
        self._error = ""
        self._ready_event = asyncio.Event()
        model = find_mlx_model()
        try:
            await asyncio.to_thread(self._mlx.load, model or "")
            self._ready_event.set()
        except RuntimeError as e:
            self._error = str(e)
            logger.error("OCR 加载失败: %s", self._error)
            self._ready_event.set()               # 唤醒搭车者（醒来见 error）
            self._cleanup_failed_start_locked()   # 发起者自清（幂等；cleanup 后 None 事件已 set 无碍）
            raise

    async def _stop_locked(self) -> None:
        """ready → stopping → unload → idle。持 lifecycle 锁调用。

        unload 经 to_thread 提交 worker FIFO——物理排在所有在途 generate
        之后（三动作互斥的执行点）。
        """
        if not self._mlx.loaded and self._state == STATE_IDLE:
            return
        self._state = STATE_STOPPING
        before = footprint_mb()
        await asyncio.to_thread(self._mlx.unload)
        self._last_activity_at = 0.0
        self._error = ""
        self._state = STATE_IDLE
        logger.info("OCR 卸载完成: footprint %s→%s MB", before, footprint_mb())

    def _cleanup_failed_start_locked(self) -> None:
        """加载失败收尾（持锁）: 状态回 idle，清残留。"""
        self._state = STATE_IDLE
        self._ready_event = None

    # ─── 后台清理 ─────────────────────────────────────────

    def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.get_running_loop().create_task(self._reaper_loop())

    async def _reaper_loop(self) -> None:
        """周期清理：空闲超时卸载。异常绝不退出。"""
        while True:
            await asyncio.sleep(REAPER_INTERVAL_SEC)
            try:
                async with self._lifecycle_lock:
                    if (self._state == STATE_READY
                            and self._last_activity_at > 0
                            and time.time() - self._last_activity_at > IDLE_RELEASE_SEC):
                        logger.info("OCR reaper: 空闲>%ds，卸载", IDLE_RELEASE_SEC)
                        await self._stop_locked()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("OCR reaper 异常（忽略继续）")

    # ─── 工具 ─────────────────────────────────────────────

    @staticmethod
    def _backend() -> str:
        """平台分支：mlx / ollama。"""
        if platform.system() == "Darwin" and os.uname().machine == "arm64":
            return "mlx"
        return "ollama"


# 模块级单例 + 兼容委托（routes/ocr.py、model_assets 消费）
ocr_service = OcrService()

extract = ocr_service.extract
force_release = ocr_service.force_release


def status() -> OcrStatus:
    return ocr_service.status()
