"""远程链接状态机（模型远程化一期核心编排）。

状态: OFF（未启用/未配置） | REMOTE（启用且健康） | DEGRADED（启用但失效）

心跳（asyncio task，server lifespan 启动）:
  周期与阈值经 ConfigManager.get_instance().remote_tunables() 每轮重读（.ai_env 配置，
  改后即时生效; 键清单/默认值见 ConfigManager.remote_tunables()）:
    • 连续失败达 fail_threshold（含请求级失败反馈）:
        REMOTE → DEGRADED + 后台预热本地三模型（降级）
    • 连续成功达 recover_threshold:
        DEGRADED → REMOTE + 安排 unload_delay_sec 稳定期后卸载本地模型
        （稳定期内再降级 → 取消卸载）

请求级 fallback 反馈: 路由层远程调用失败时调 note_request_failure——
与心跳失败同源计数（更快感知降级）。

日志: 独立文件 OPENSECURITY_HOME/logs/remote-link.log（setup_auxiliary_logger，
propagate=False——不进 control.log，两类日志物理分离）。

循环依赖防护: 对 model_loader / ocr_service 的预热/卸载调用全部函数内
延迟 import（它们也延迟 import 本模块）。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field

from services.config_manager import ConfigManager
from services.logging_setup import LogManager
from services.ocr_engines import MlxEngine
from services.remote_client import RemoteConsoleClient, RemoteHealthInfo

logger = LogManager.get_instance().setup_auxiliary("remote_link", "remote-link.log")



def _tunables() -> "ConfigManager.RemoteTunables":
    """远程链接可调参数（ConfigManager 委托）。

    独立成模块级函数的原因: 单测注入点（monkeypatch 本函数替换小阈值，
    与 _read_config 同模式）——不设 env 覆盖通道（配置唯一收口 .ai_env）。
    """
    from services.config_manager import ConfigManager
    return ConfigManager.get_instance().remote_tunables()


@dataclass
class SwitchResult:
    """切换操作结果（routes/remote.py 透传前端）。"""

    ok: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class RemoteLinkStatus:
    """状态机快照（前端远程 TAB 单一事实源）。"""

    enabled: bool                      # ENABLED 配置值（忠实显示，不随健康变）
    url: str
    token_configured: bool
    token_prefix: str                  # 前 6 位（脱敏）
    state: str                         # off / remote / degraded
    fail_streak: int
    recover_streak: int
    last_ok_at: float | None           # wall clock 秒
    last_fail_reason: str | None
    remote_health: "dict[str, object] | None"  # service/version/models/latency_ms
    local_models: "dict[str, str]"  # 三模型本地加载态
    unload_countdown_sec: float | None # 恢复稳定期倒计时（未安排 → None）




class RemoteLinkService:
    """远程链接状态机（全局单例，get_instance() 获取）。线程安全。"""

    STATE_OFF = "off"
    STATE_REMOTE = "remote"
    STATE_DEGRADED = "degraded"
    _instance: "RemoteLinkService | None" = None
    _instance_lock: "threading.Lock" = __import__("threading").Lock()  # pyright: ignore[reportAny] —— __import__ 动态模块成员，类型不可知

    def __new__(cls) -> "RemoteLinkService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "RemoteLinkService":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._shutdown_for_tests()
            cls._instance = None

    def _shutdown_for_tests(self) -> None:
        """测试重置收尾: 关闭共享 httpx client。"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("远程 client close 异常: %s", e)

    def _init_once(self) -> None:
        self._lock = threading.Lock()
        self._state: str = self.STATE_OFF
        self._client: "RemoteConsoleClient | None" = None
        self._client_url: str = ""
        self._client_token: str = ""
        self._fail_streak = 0
        self._recover_streak = 0
        self._last_ok_at: float | None = None
        self._last_fail_reason: str | None = None
        self._last_health: "RemoteHealthInfo | None" = None
        self._unload_timer: "threading.Timer | None" = None
        self._unload_due_at: float | None = None
        self._task: "asyncio.Task[None] | None" = None

    def _read_config(self) -> tuple[str, bool, str]:
        """读远程三 KEY（ConfigManager 唯一读写方）。"""
        from services.config_manager import ConfigManager
        url = (ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_URL) or "").strip()
        enabled = (ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_ENABLED) or "").strip().lower() in ("1", "true")
        token = (ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_TOKEN) or "").strip()
        return url, enabled, token

    def _local_fingerprints(self) -> dict[str, str]:
        """本地模型指纹（repo_id → snapshot hash; HF 缓存目录名，不加载模型）。"""
        from pathlib import Path
        
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        result: dict[str, str] = {}
        for repo in (ConfigManager.Protocol.EMBED_MODEL, ConfigManager.Protocol.RERANKER_MODEL):
            repo_dir = repo.replace("/", "--")
            snaps = list(hub.glob(f"models--{repo_dir}/snapshots/*"))
            result[repo] = snaps[0].name if snaps else ""
        try:
        
            from pathlib import PurePath
            p = MlxEngine.find_mlx_model()
            result["glm-ocr"] = PurePath(p).parent.name if p else ""
        except Exception:  # noqa: BLE001 —— OCR 指纹缺失不阻断
            result["glm-ocr"] = ""
        return result

    @staticmethod
    def _model_inference():
        """ModelInferenceService 延迟获取（循环依赖防护）。"""
        from services.model_loader import ModelInferenceService
        return ModelInferenceService.get_instance()

    # ── 路由层接口（model_loader / ocr_service 每请求调用）────

    def should_use_remote(self) -> bool:
        with self._lock:
            return self._state == self.STATE_REMOTE

    def get_client(self) -> RemoteConsoleClient:
        with self._lock:
            if self._client is None:
                raise RuntimeError("远程客户端未初始化（未启用远程模式）")
            return self._client

    def note_request_failure(self, reason: str) -> None:
        """请求级失败反馈（加速降级判定; 任意线程可调）。"""
        logger.warning("请求级远程失败: %s", reason)
        self._register_failure(reason)

    # ── 生命周期 ─────────────────────────────────────────

    def start(self) -> None:
        """启动心跳 task（server lifespan / 测试 asyncio.run 内调用）。幂等。"""
        if self._task is not None and not self._task.done():
            return
        self.reload_config()
        self._task = asyncio.get_running_loop().create_task(self._heartbeat_loop())
        t = _tunables()
        logger.info("remote_link 心跳启动（interval=%.0fs fail>=%d recover>=%d unload_after=%.0fs）",
                    t.heartbeat_interval_sec, t.fail_threshold,
                    t.recover_threshold, t.unload_delay_sec)

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_tunables().heartbeat_interval_sec)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 —— 读配置瞬时异常不杀心跳任务
                logger.exception("心跳读 tunables 异常（本轮跳过继续）")
                continue
            try:
                await self._probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 —— 心跳异常不退出
                logger.exception("心跳周期异常（忽略继续）")

    async def _probe_once(self) -> bool:
        """单次探测 + 状态机评估。返回本轮是否成功。"""
        url, enabled, token = self._read_config()
        with self._lock:
            self._sync_client_locked(url, token)
            if not (enabled and url):
                if self._state != self.STATE_OFF:
                    logger.info("远程未启用（ENABLED=0 或 URL 空）→ OFF")
                    self._state = self.STATE_OFF
                    self._cancel_unload_locked()
                return False
            # 启用态: 探测 → 阈值判定（OFF 初始成功单次定态; DEGRADED 恢复需连续 N 次）
        ok, reason, info = await self._probe_raw()
        if ok:
            assert info is not None
            self._register_success(info)
        else:
            self._register_failure(reason)
        return ok

    async def _probe_raw(self) -> tuple[bool, str, RemoteHealthInfo | None]:
        """底层探测（to_thread 同步 httpx）。"""
        client = self.get_client()
        try:
            info = await asyncio.to_thread(client.probe_health)
            return True, "", info
        except Exception as e:  # noqa: BLE001 —— 任何失败统一面
            return False, f"{type(e).__name__}: {e}", None

    # ── 状态迁移（持锁核心）───────────────────────────────

    def _register_success(self, info: RemoteHealthInfo) -> None:
        with self._lock:
            self._fail_streak = 0
            self._recover_streak += 1
            self._last_ok_at = time.time()
            self._last_health = info
            if self._state == self.STATE_OFF:
                # 初始启用: 单次成功即信任（无历史失败包袱）
                self._state = self.STATE_REMOTE
                logger.info("远程初始评估成功 → REMOTE（url=%s, 延迟 %.1fms）",
                            self._client_url, info.latency_ms)
            elif (self._state == self.STATE_DEGRADED
                  and self._recover_streak >= _tunables().recover_threshold):
                self._state = self.STATE_REMOTE
                delay = _tunables().unload_delay_sec
                logger.info("远程恢复（连续 %d 次成功）→ REMOTE；%ds 稳定期后卸载本地模型",
                            self._recover_streak, delay)
                self._schedule_unload_locked()

    def _register_failure(self, reason: str) -> None:
        with self._lock:
            self._recover_streak = 0
            self._fail_streak += 1
            self._last_fail_reason = reason
            if (self._state in (self.STATE_REMOTE, self.STATE_OFF)
                    and self._fail_streak >= _tunables().fail_threshold):
                # REMOTE: 降级; OFF: 初始评估失败——均预热本地备好服务
                self._state = self.STATE_DEGRADED
                self._cancel_unload_locked()
                logger.warning("远程失效（连续 %d 次失败: %s）→ DEGRADED，预热本地模型",
                               self._fail_streak, reason)
                threading.Thread(target=self._warm_local, name="remote-warmup",
                                 daemon=True).start()

    # ── 预热 / 延迟卸载（后台线程; 延迟 import 防循环）─────

    def _warm_local(self) -> None:
        self._model_inference().preload_all_models_background()

    def _schedule_unload_locked(self) -> None:
        """安排稳定期后卸载（持锁调用）。"""
        self._cancel_unload_locked()
        delay = _tunables().unload_delay_sec
        self._unload_due_at = time.monotonic() + delay

        def _do_unload() -> None:
            with self._lock:
                if self._state != self.STATE_REMOTE:
                    logger.info("稳定期内状态变化（%s），取消卸载", self._state)
                    self._unload_due_at = None
                    return
                self._unload_due_at = None
            logger.info("远程稳定 %ds，卸载本地三模型（释放内存）", delay)
            try:
                                self._model_inference().release_all_local()
            except Exception:  # noqa: BLE001
                logger.exception("本地模型卸载异常")
            try:
                from services.ocr_service import OcrService
                OcrService.get_instance().release_sync()
            except Exception:  # noqa: BLE001
                logger.exception("OCR 卸载异常")

        timer = threading.Timer(delay, _do_unload)
        timer.daemon = True
        timer.start()
        self._unload_timer = timer

    def _cancel_unload_locked(self) -> None:
        if self._unload_timer is not None:
            self._unload_timer.cancel()
            self._unload_timer = None
        self._unload_due_at = None

    # ── 切换操作（routes/remote.py 调用）──────────────────

    async def switch_to_remote(self) -> SwitchResult:
        """校验远程（连通+token+版本指纹）→ 成功写 ENABLED=1 并评估。"""
        url, enabled, token = self._read_config()
        if not url:
            return SwitchResult(ok=False, error="未配置远程控制台链接（REMOTE_CONSOLE_URL）")
        with self._lock:
            self._sync_client_locked(url, token)
        ok, reason, info = await self._probe_raw()
        if not ok:
            return SwitchResult(ok=False, error=f"远程校验失败: {reason}")

        # 版本指纹对比（不一致警告不阻断）
        warnings: list[str] = []
        assert info is not None
        local = self._local_fingerprints()
        for m in info.models:
            if m.repo_id in local and local[m.repo_id] and m.snapshot \
                    and local[m.repo_id] != m.snapshot:
                warnings.append(f"模型 {m.repo_id} 版本不一致（本地 {local[m.repo_id][:8]}… / "
                                f"远程 {m.snapshot[:8]}…）——向量空间可能漂移")

        from services.config_manager import ConfigManager
        ConfigManager.get_instance().set_one(ConfigManager.Keys.REMOTE_CONSOLE_ENABLED, "1")
        self.reload_config()
        # 立即评估（校验刚成功 → 单次定态 REMOTE）
        with self._lock:
            self._state = self.STATE_REMOTE
            self._fail_streak = 0
            self._recover_streak = 1
            self._last_ok_at = time.time()
            self._last_health = info
            self._schedule_unload_locked()
        logger.info("切换远程成功（url=%s, warnings=%d）", url, len(warnings))
        return SwitchResult(ok=True, warnings=warnings)

    def switch_to_local(self) -> SwitchResult:
        """写 ENABLED=0 → OFF。本地模型保持加载（不卸载）。"""
        from services.config_manager import ConfigManager
        ConfigManager.get_instance().set_one(ConfigManager.Keys.REMOTE_CONSOLE_ENABLED, "0")
        with self._lock:
            self._state = self.STATE_OFF
            self._cancel_unload_locked()
        logger.info("切换本地（ENABLED=0; 本地模型保持加载）")
        return SwitchResult(ok=True)

    def reload_config(self) -> None:
        """配置热重载: 重建 client + 清零计数（PUT /api/config?surface=remote 写 URL/TOKEN 后由写边界钩子调用）。"""
        url, _enabled, token = self._read_config()
        with self._lock:
            self._sync_client_locked(url, token)
            self._fail_streak = 0
            self._recover_streak = 0
            if not url:
                self._state = self.STATE_OFF
                self._cancel_unload_locked()

    def _sync_client_locked(self, url: str, token: str) -> None:
        """URL/token 变化时重建 client（持锁调用）。"""
        if self._client is not None and url == self._client_url and token == self._client_token:
            return
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("远程 client close 异常（重建前）: %s", e)
        t = _tunables()
        self._client = RemoteConsoleClient(
            url, token=token,
            infer_timeout=t.infer_timeout_sec,
            probe_timeout=t.probe_timeout_sec) if url else None
        self._client_url = url
        self._client_token = token
        if url:
            logger.info("远程 client 已（重）建: %s", url)

    # ── 状态快照 ─────────────────────────────────────────

    def status(self) -> RemoteLinkStatus:
        url, enabled, token = self._read_config()
        with self._lock:
            local_models: "dict[str, str]" = {}
            try:
                local_models["embedder"] = self._model_inference().embedder_status().state
                local_models["reranker"] = self._model_inference().reranker_status().state
            except Exception:  # noqa: BLE001
                pass
            try:
                from services.ocr_service import OcrService
                local_models["ocr"] = OcrService.get_instance().status().state
            except Exception as e:  # noqa: BLE001
                logger.warning("OCR 状态采集异常: %s", e)
            countdown: float | None = None
            if self._unload_due_at is not None:
                countdown = max(0.0, self._unload_due_at - time.monotonic())
            return RemoteLinkStatus(
                enabled=enabled,
                url=url,
                token_configured=bool(token),
                token_prefix=token[:6] if token else "",
                state=self._state,
                fail_streak=self._fail_streak,
                recover_streak=self._recover_streak,
                last_ok_at=self._last_ok_at,
                last_fail_reason=self._last_fail_reason,
                remote_health={
                    "service": self._last_health.service,
                    "version": self._last_health.version,
                    "latency_ms": self._last_health.latency_ms,
                    "models": [{"repo_id": m.repo_id, "snapshot": m.snapshot,
                                "loaded": m.loaded} for m in self._last_health.models],
                } if self._last_health else None,
                local_models=local_models,
                unload_countdown_sec=countdown,
            )


