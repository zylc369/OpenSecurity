"""受管模型生命周期抽象（ModelWorker + ManagedModel）。

三模型（embedder / reranker / OCR-MLX）统一收口:
  状态机 idle/starting/ready/stopping + 单飞加载 + FIFO 排队卸载 + 空闲 reaper(可选)。

设计语义（自 OCR 服务泛化，行为保真）:
  • ModelWorker: 常驻专职线程，FIFO 串行执行 load/infer/unload——
    卸载物理排在所有在途推理之后（"等推理完成才动模型"的队列语义，
    替代引用计数）。MLX 的 thread-local stream 约束天然满足
    （同一线程执行全部动作）。
  • 非阻塞加载提交: 持锁窗口内只做状态翻转 + 提交（不等待加载完成），
    加载在 worker FIFO 执行、完成回调置 READY——status() 轮询永不被
    长加载阻塞。
  • 单飞加载: 并发 ensure_loaded 只触发一次 load，其余等待同一事件;
    失败回 idle（下次重新加载）。
  • 防"假 READY"竞态: 加载完成回调只把 STARTING 翻成 READY——
    若此刻状态已被 release 改动（理论不可达，防御性兜底），不翻。
  • 空闲 reaper: idle_timeout_sec 非 None 时后台周期检查，超时自动卸载。

调用域约束: 本模块全部为同步阻塞原语（threading），调用方应在普通
线程（如 asyncio.to_thread 的池线程 / worker 线程）——禁止在事件循环
线程直接调用 run_inference / ensure_loaded / release（会阻塞循环）。
"""
from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")  # 泛型参数声明（typing 设施，Java 泛型对应物）

# ─── worker 进程级注册表（同名共享，静态类收口）──────────
# 约束来源: MLX Metal stream 绑定线程——同一模型的全部 load/infer/unload
# 必须永远在同一线程（进程唯一 worker）。同名 ManagedModel 实例（如测试
# 多实例 OcrService）共享 worker 后，多实例各自持有模型对象但串行执行，
# 行为与"每实例独占 worker"的旧约束等价且杜绝多线程崩。
# 不同模型名（embedder/reranker/ocr）各一个 worker——跨模型不互相阻塞。


class ModelWorkerRegistry:
    """按名获取进程唯一 ModelWorker（懒初始化）。"""

    _REGISTRY: "dict[str, ModelWorker]" = {}
    _LOCK = threading.Lock()

    @classmethod
    def get_worker(cls, name: str) -> "ModelWorker":
        with cls._LOCK:
            if name not in cls._REGISTRY:
                cls._REGISTRY[name] = ModelWorker(name)
            return cls._REGISTRY[name]

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._LOCK:
            cls._REGISTRY.clear()


@dataclass(frozen=True)
class ModelLifecycleStatus:
    """模型生命周期状态快照（模型页 / 远程 TAB 展示）。"""

    name: str
    state: str                    # idle / starting / ready / stopping
    idle_sec: float | None        # 已空闲秒数（未加载或未启用 reaper → None）
    idle_timeout_sec: float | None
    error: str | None             # 最近一次加载失败原因（成功后清除）


class ModelWorker:
    """专职常驻线程——FIFO 串行执行提交的函数（物理串行点）。

    queue.Queue + Future + daemon 线程（自 OCR 服务的 worker 泛化）。
    worker 常驻（unload 后线程保留，线程局部状态复用）。
    异常全部回传调用方（Future.set_exception），线程永不因任务失败退出。
    """

    def __init__(self, name: str) -> None:
        self._queue: "queue.Queue[tuple[Callable[[], object], concurrent.futures.Future]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._name = name

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name=f"model-worker-{self._name}")
                self._thread.start()

    def _run(self) -> None:
        while True:
            fn, fut = self._queue.get()
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 —— 异常全部回传调用方
                fut.set_exception(e)

    def call(self, fn: Callable[[], T]) -> T:
        """投递到 worker 线程执行并阻塞等结果。

        禁止在事件循环线程直接调用（会阻塞循环）。
        """
        self._ensure_started()
        fut: "concurrent.futures.Future[T]" = concurrent.futures.Future()
        self._queue.put((fn, fut))
        return fut.result()

    def post(self, fn: Callable[[], object]) -> "concurrent.futures.Future[object]":
        """投述到 worker 线程执行，立即返回 Future（不阻塞）。

        完成回调经 Future.add_done_callback 注册——回调在 worker 线程执行
        （set_result 之后），适合"加载完成置状态"的异步收尾。
        """
        self._ensure_started()
        fut: "concurrent.futures.Future[object]" = concurrent.futures.Future()
        self._queue.put((fn, fut))
        return fut


class ManagedModel:
    """受管模型生命周期（线程安全）。

    状态常量与日志器为类静态字段（Java 静态成员风格）。

    load_fn / unload_fn 由使用方提供（均在 worker 线程执行）:
      load_fn: 加载模型（状态机保证仅 STARTING 态进入，幂等）
      unload_fn: 卸载模型（应自身幂等; 重复调用无害）
    """

    STATE_IDLE = "idle"
    STATE_STARTING = "starting"
    STATE_READY = "ready"
    STATE_STOPPING = "stopping"
    logger = logging.getLogger(__name__ + ".ManagedModel")

    # 加载等待上限（秒）: 真实模型加载（含 MLX/MPS 冷缓存）远小于此值;
    # 超时 = 底层运行时挂死（如 MLX Metal eval 死锁）——转可见异常优于永久挂起。
    LOAD_WAIT_TIMEOUT_SEC = 120.0

    def __init__(
        self,
        name: str,
        load_fn: Callable[[], None],
        unload_fn: Callable[[], None],
        idle_timeout_sec: float | None = None,
        reaper_interval_sec: float = 5.0,
    ) -> None:
        self._name = name
        self._load_fn = load_fn
        self._unload_fn = unload_fn
        self._idle_timeout_sec = idle_timeout_sec
        self._reaper_interval_sec = reaper_interval_sec

        self._worker = ModelWorkerRegistry.get_worker(name)
        self._lock = threading.Lock()          # 状态变更独占（持锁窗口内禁止阻塞等待）
        self._state: str = self.STATE_IDLE
        self._error: str = ""
        self._ready_event: threading.Event | None = None
        self._last_activity_at: float = 0.0    # 最近活动（monotonic; reaper 用）
        self._reaper_thread: threading.Thread | None = None

    # ── 查询 ─────────────────────────────────────────────

    def is_loaded(self) -> bool:
        with self._lock:
            return self._state == self.STATE_READY

    def state(self) -> str:
        with self._lock:
            return self._state

    def idle_sec(self) -> float | None:
        """已空闲秒数; 未加载或未启用 reaper → None（模型页数据源）。"""
        with self._lock:
            if self._idle_timeout_sec is None or self._state != self.STATE_READY:
                return None
            if self._last_activity_at <= 0:
                return None
            return max(0.0, time.monotonic() - self._last_activity_at)

    def status(self) -> ModelLifecycleStatus:
        with self._lock:
            idle: float | None = None
            if (self._idle_timeout_sec is not None and self._state == self.STATE_READY
                    and self._last_activity_at > 0):
                idle = max(0.0, time.monotonic() - self._last_activity_at)
            return ModelLifecycleStatus(
                name=self._name,
                state=self._state,
                idle_sec=idle,
                idle_timeout_sec=self._idle_timeout_sec,
                error=self._error or None,
            )

    # ── 加载（单飞; 持锁窗口不阻塞）─────────────────────

    def ensure_loaded(self) -> None:
        """确保模型已加载（并发单飞）。失败抛 RuntimeError。

        竞态防御: 等待者醒来只做判定，不翻状态（置 READY 统一在加载
        完成回调）——杜绝"等待者把已卸载的 IDLE 翻成假 READY"。
        STOPPING 态（卸载在锁外窗口执行）短暂自旋等待收尾后重载——
        worker FIFO 保证新 load 排在 unload 之后，顺序天然正确。
        """
        self._ensure_reaper()
        while True:
            event: threading.Event | None = None
            with self._lock:
                if self._state == self.STATE_READY:
                    return
                if self._state == self.STATE_STOPPING:
                    pass  # 卸载在途——出锁等待（窗口=剩余在途推理+unload，毫秒~秒级）
                elif self._state == self.STATE_IDLE:
                    event = self._start_locked()
                else:  # starting: 搭车等同一事件
                    event = self._ready_event
                    self.logger.info("[%s] 懒加载: 已有加载在途，并发等待", self._name)
            if event is not None:
                if not event.wait(timeout=self.LOAD_WAIT_TIMEOUT_SEC):
                    self.logger.error("[%s] 加载等待超时（%.0fs）——底层运行时疑似挂死"
                                      "（如 MLX Metal eval 死锁），转异常", self._name,
                                      self.LOAD_WAIT_TIMEOUT_SEC)
                    raise RuntimeError(
                        f"[{self._name}] 模型加载等待超时（{self.LOAD_WAIT_TIMEOUT_SEC:.0f}s）"
                        "——底层运行时挂死（Metal/MPS 疑似死锁）")
                with self._lock:
                    if self._error and self._state == self.STATE_IDLE:
                        raise RuntimeError(f"[{self._name}] 加载失败: {self._error}")
                    # READY（成功）或防御性兜底（异常时序）——返回，下次调用自愈
                return
            time.sleep(0.05)

    def _start_locked(self) -> threading.Event:
        """idle → starting → 非阻塞提交加载。持锁调用（窗口内只翻转+提交）。

        加载经 worker FIFO 执行（与推理/卸载物理互斥）; 完成收尾在
        _on_load_done 回调（worker 线程）。
        """
        self._state = self.STATE_STARTING
        self._error = ""
        self._ready_event = threading.Event()
        event = self._ready_event
        fut = self._worker.post(self._load_fn)
        fut.add_done_callback(self._on_load_done)
        return event

    def _on_load_done(self, fut: "concurrent.futures.Future[object]") -> None:
        """加载完成收尾（worker 线程执行）。

        成功: STARTING → READY + 记录活动时间 + 唤醒等待者。
        失败: STARTING → IDLE + 记录 error + 唤醒等待者（醒来抛错）。
        状态非 STARTING 时不动（防御: release 已介入的理论窗口）。
        """
        exc = fut.exception()
        with self._lock:
            if self._state != self.STATE_STARTING:
                self.logger.warning("[%s] 加载完成回调发现状态非 starting（%s），跳过收尾",
                               self._name, self._state)
                if self._ready_event is not None:
                    self._ready_event.set()
                return
            if exc is None:
                self._state = self.STATE_READY
                self._last_activity_at = time.monotonic()
            else:
                self._error = f"{type(exc).__name__}: {exc}"
                self._state = self.STATE_IDLE
                self.logger.error("[%s] 加载失败: %s", self._name, self._error)
            if self._ready_event is not None:
                self._ready_event.set()

    # ── 推理 / 卸载 ─────────────────────────────────────

    def run_inference(self, fn: Callable[[], T]) -> T:
        """执行一次推理: 确保加载 → worker FIFO 执行。

        加载/卸载与推理全经同一 FIFO——在途推理完成前 unload 不会执行。
        """
        self.ensure_loaded()
        try:
            return self._worker.call(fn)
        finally:
            with self._lock:
                self._last_activity_at = time.monotonic()

    def release(self) -> None:
        """事件触发卸载（排队在在途推理之后）。幂等。

        STARTING 态（加载在途）: 等待加载完成（不中断——模型加载不可
        安全中断），随后卸载。
        """
        with self._lock:
            if self._state == self.STATE_IDLE:
                return
            event = self._ready_event if self._state == self.STATE_STARTING else None
        if event is not None:
            # 加载收尾回调置位（成功 READY / 失败 IDLE）; 超时兜底同 ensure_loaded
            if not event.wait(timeout=self.LOAD_WAIT_TIMEOUT_SEC):
                self.logger.error("[%s] release 等待加载收尾超时（%.0fs）", self._name,
                                  self.LOAD_WAIT_TIMEOUT_SEC)
                raise RuntimeError(
                    f"[{self._name}] release 等待加载收尾超时"
                    f"（{self.LOAD_WAIT_TIMEOUT_SEC:.0f}s）——底层运行时挂死")
        with self._lock:
            if self._state != self.STATE_READY:
                return  # 加载失败已回 IDLE / 已被并发 release 处理
            self._release_locked()

    def _release_locked(self) -> None:
        """ready → stopping → unload → idle。持锁调用。

        unload 经 worker FIFO——物理排在所有在途推理之后。
        持锁窗口 = unload 执行期（MLX 实测 ~35ms，可接受; embedder
        del + gc 数百 ms 量级，仍远小于加载）。
        """
        self._state = self.STATE_STOPPING
        t0 = time.monotonic()
        try:
            self._worker.call(self._unload_fn)
        finally:
            self._last_activity_at = 0.0
            self._error = ""
            self._state = self.STATE_IDLE
            self._ready_event = None
        self.logger.info("[%s] 卸载完成（%.0fms）", self._name, (time.monotonic() - t0) * 1000)

    # ── 空闲 reaper ─────────────────────────────────────

    def _ensure_reaper(self) -> None:
        """启动 reaper 线程（仅 idle_timeout 启用时; 卸载后自动退出，按需重启）。"""
        if self._idle_timeout_sec is None:
            return
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            return
        self._reaper_thread = threading.Thread(
            target=self._reaper_loop, daemon=True, name=f"model-reaper-{self._name}")
        self._reaper_thread.start()

    def _reaper_loop(self) -> None:
        """周期检查: READY 且空闲超阈值 → 卸载。异常绝不退出。

        卸载后本循环退出（无对象可看护），下次 ensure_loaded 重启。
        """
        while True:
            time.sleep(self._reaper_interval_sec)
            try:
                with self._lock:
                    if (self._state == self.STATE_READY
                            and self._last_activity_at > 0
                            and self._idle_timeout_sec is not None
                            and time.monotonic() - self._last_activity_at > self._idle_timeout_sec):
                        self.logger.info("[%s] reaper: 空闲>%.0fs，卸载",
                                    self._name, self._idle_timeout_sec)
                        self._release_locked()
                        return
            except Exception:  # noqa: BLE001
                self.logger.exception("[%s] reaper 异常（忽略继续）", self._name)
