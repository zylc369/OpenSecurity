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

from typing import TYPE_CHECKING

from services.config_manager import ConfigManager, RemoteTransportMode
from services.logging_setup import LogManager
from services.remote_client import RemoteConsoleClient, RemoteHealthInfo

from services.model_assets import ModelLoadState  # pydantic 运行时解析需可见（model_assets 无反向依赖）

if TYPE_CHECKING:  # 仅类型检查用（零运行时依赖——依赖方向经 remote_client 间接）
    from services.model_assets import ModelAsset
    from services.remote_transport import TransportConfig

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


def _safe_state(m: "ModelAsset") -> "ModelLoadState":
    """状态采集防护（瞬时异常 → ERROR 态 + 日志——status 接口永不错杀）。"""
    from services.model_assets import ModelLoadState
    try:
        return m.local_state()
    except Exception as e:  # noqa: BLE001
        logger.warning("模型状态采集异常（%s）: %s", m.id, e)
        return ModelLoadState.ERROR


@dataclass(frozen=True)
class LocalModelState:
    """本地单模型状态（注册表驱动——与环境总览同源）。"""
    id: str
    display: str
    state: "ModelLoadState"  # 延迟注解（StrEnum——JSON 序列化字符串形态）


@dataclass
class RemoteLinkStatus:
    """状态机快照（前端远程 TAB 单一事实源）。"""

    enabled: bool                      # ENABLED 配置值（忠实显示，不随健康变）
    url: str
    token_configured: bool
    token_prefix: str                  # 前 6 位（脱敏）
    state: str                         # off / remote / degraded
    transport: RemoteTransportMode | None  # None = 未配置/非法（fail-closed，不开任何管道）
    fail_streak: int
    recover_streak: int
    last_ok_at: float | None           # wall clock 秒
    last_fail_reason: str | None
    remote_health: "RemoteHealthInfo | None"  # 远程节点健康快照（remote_client 同型直传）
    local_models: "list[LocalModelState]"  # 各模型本地加载态（注册表驱动）
    unload_countdown_sec: float | None # 恢复稳定期倒计时（未安排 → None）
    probe_attempts: int = 0           # 本轮离线期累计探测次数（成功后清零）
    probe_interval_sec: float = 5.0   # 探测周期（前端倒计时用）
    next_probe_in_sec: float = 0.0    # 距下次探测秒数（0=即将/进行中）
    local_code_fingerprint: str = ""  # 本机代码指纹（与 remote_health.code_fingerprint 对齐检测）
    path: str = ""                    # P2P 传输路径: direct/relay/""（可见性）
    direct_last_error: str = ""       # 最近一次直连尝试失败原因（空=无/非 P2P）




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
        self._unload_due_at: "float | None" = None
        self._last_remote_warmup_at: float = 0.0
        self._task: "asyncio.Task[None] | None" = None
        # 校验进行中标志: switch_transport 探测期间（不持锁），心跳/reload 的
        # _sync_client_locked 不得重建 client——存量配置视角（mode 未写）会误判
        # 需要重建并 close 掉校验用 client → 在途探测挂死在已关闭的 transport loop
        self._validating: bool = False
        # 建联进度（降级/建联期的"后端仍在工作"可视化）
        self._probe_attempts: int = 0
        self._next_probe_at: float = 0.0  # monotonic 时间戳

    def _read_config(self) -> tuple[str, bool, str]:
        """读远程三要素（ConfigManager 唯一读写方）。

        enabled 由 REMOTE_TRANSPORT_MODE 派生（mode 即开关: 有值=开，
        空/非法=关——fail-closed）; 不再有独立的 ENABLED 键。
        """
        url = (ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_URL) or "").strip()
        enabled = (ConfigManager.get_instance().p2p_settings().transport_mode is not None)
        token = (ConfigManager.get_instance().get(ConfigManager.Keys.REMOTE_CONSOLE_TOKEN) or "").strip()
        return url, enabled, token

    @staticmethod
    def _model_inference():
        """ModelInferenceService 延迟获取（循环依赖防护）。"""
        from services.model_loader import ModelInferenceService
        return ModelInferenceService.get_instance()

    # ── 路由层接口（model_loader / ocr_service 每请求调用）────

    def should_use_remote(self) -> bool:
        with self._lock:
            return self._state == self.STATE_REMOTE

    @property
    def is_remote_active(self) -> bool:
        """无锁只读判定（状态采集等"可能已持本服务锁"的路径专用）。

        防非重入锁自死锁: status() 持锁采集模型态, 模型态又可能问远程可用性
        ——此路径不得走 should_use_remote（重复获锁即自死锁）。
        state 为 str 单次读（原子）, 无锁一致。
        """
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
        """单次探测 + 状态机评估。返回本轮是否成功。

        启用门控按管道: http → url; p2p → 隧道配置齐备（免 URL）。
        """
        url, enabled, token = self._read_config()
        with self._lock:
            p2p = self._p2p_config_locked()
            self._sync_client_locked(url, token)
            if not (enabled and (url or p2p is not None)):
                if self._state != self.STATE_OFF:
                    logger.info("远程未启用（ENABLED=0 或两条管道均不可用）→ OFF")
                    self._state = self.STATE_OFF
                    self._cancel_unload_locked()
                return False  # 门控未过——不计数（避免 http+空URL 时 attempts 无限涨）
            self._probe_attempts += 1
            # 启用态: 探测 → 阈值判定（OFF 初始成功单次定态; DEGRADED 恢复需连续 N 次）
        ok, reason, info = await self._probe_raw()
        # 探测结束后设下一轮时刻（含探测耗时——倒计时真实; 若探测耗时超周期立即=0）
        self._next_probe_at = time.monotonic() + _tunables().heartbeat_interval_sec
        if ok:
            assert info is not None
            self._register_success(info)
        else:
            self._register_failure(reason)
        return ok

    async def _probe_raw(self) -> tuple[bool, str, RemoteHealthInfo | None]:
        """底层探测（to_thread 同步 httpx）。client 未就绪等任何失败统一面。"""
        try:
            client = self.get_client()
            info = await asyncio.to_thread(client.probe_health)
            return True, "", info
        except Exception as e:  # noqa: BLE001 —— 任何失败统一面（不 500）
            return False, f"{type(e).__name__}: {e}", None

    # ── 状态迁移（持锁核心）───────────────────────────────

    def _register_success(self, info: RemoteHealthInfo) -> None:
        with self._lock:
            self._fail_streak = 0
            self._probe_attempts = 0
            self._recover_streak += 1
            self._last_ok_at = time.time()
            self._last_health = info
            if self._state == self.STATE_OFF:
                # 初始启用: 单次成功即信任（无历史失败包袱）
                self._state = self.STATE_REMOTE
                logger.info("远程初始评估成功 → REMOTE（url=%s, 延迟 %.1fms）",
                            self._client_url, info.latency_ms)
                self._schedule_remote_tts_warmup_locked()
            elif (self._state == self.STATE_DEGRADED
                  and self._recover_streak >= _tunables().recover_threshold):
                self._state = self.STATE_REMOTE
                delay = _tunables().unload_delay_sec
                logger.info("远程恢复（连续 %d 次成功）→ REMOTE；%ds 稳定期后卸载本地模型",
                            self._recover_streak, delay)
                self._schedule_unload_locked()
                self._schedule_remote_tts_warmup_locked()

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
            logger.info("远程稳定 %ds，卸载本地模型（embedder/reranker/OCR/TTS——释放内存）", delay)
            try:
                                self._model_inference().release_all_local()
            except Exception:  # noqa: BLE001
                logger.exception("本地模型卸载异常")
            try:
                from services.ocr_service import OcrService
                OcrService.get_instance().release_sync()
            except Exception:  # noqa: BLE001
                logger.exception("OCR 卸载异常")
            try:
                from services.tts_service import TtsService
                TtsService.get_instance().release()
            except Exception:  # noqa: BLE001
                logger.exception("TTS 卸载异常")

        timer = threading.Timer(delay, _do_unload)
        timer.daemon = True
        timer.start()
        self._unload_timer = timer

    def _cancel_unload_locked(self) -> None:
        if self._unload_timer is not None:
            self._unload_timer.cancel()
            self._unload_timer = None
        self._unload_due_at = None

    def _schedule_remote_tts_warmup_locked(self) -> None:
        """进入 REMOTE 后预热节点 TTS（防首听吃节点全链冷启动）。

        节流窗（warmup_throttle_sec, 默认 300s）: 心跳抖动反复
        DEGRADED↔REMOTE 时不重复轰节点。文本用"好。"（与节点预载 warmup
        同串）——冷节点缓存 miss 真合成焐 worker; 热节点缓存命中 0ms,
        命中即 worker 活着, 预热目的已达成。
        """
        now = time.monotonic()
        if now - self._last_remote_warmup_at < _tunables().warmup_throttle_sec:
            return
        self._last_remote_warmup_at = now
        threading.Thread(target=self._warm_remote_tts,
                         name="remote-tts-warmup", daemon=True).start()

    def _warm_remote_tts(self) -> None:
        try:
            client = self.get_client()
            # 首选: 节点侧全池预热（POST /api/tts/warm——覆盖范围由节点池保证,
            # 池大小变化自动跟随; 与节点预载同一实现）。
            warmed = 0
            try:
                warmed = client.tts_warm()
            except Exception:  # noqa: BLE001 —— 旧节点 404/网络异常 → 回退
                warmed = 0
            if warmed <= 0:
                # 回退（旧节点）: 双发不同文本覆盖 2 worker（与池大小对齐）
                client.tts_synth("好。", "", 1.0, no_cache=True)
                client.tts_synth("很。", "", 1.0, no_cache=True)
                logger.info("节点 TTS 预热完成（兼容路径——节点未提供 warm 端点）")
            else:
                logger.info("节点 TTS 预热完成（全池 %d 个 worker——远程首听免冷启动）",
                            warmed)
        except Exception as e:  # noqa: BLE001 —— 预热失败不影响主流程
            logger.warning("节点 TTS 预热失败（首听可能吃冷启动）: %s", e)

    # ── 切换操作（routes/remote.py 调用）──────────────────

    async def switch_transport(self, mode: RemoteTransportMode) -> SwitchResult:
        """切换到指定管道（先校验后置位——mode 即开关: 置位=开，清空=关）。

        按管道分通道校验（p2p 只校验 P2P 四项; http 只校验链接/令牌），
        成功写 REMOTE_TRANSPORT_MODE 并评估。
        """
        url, _enabled, token = self._read_config()
        if mode is RemoteTransportMode.HTTP and not url:
            return SwitchResult(ok=False, error=(
                "HTTP 直连管道须填写远程控制台链接（REMOTE_CONSOLE_URL）"))
        if mode is RemoteTransportMode.P2P:
            p2p = ConfigManager.get_instance().p2p_settings()
            missing = [name for name, ok in (
                ("中继服务器地址（RELAY_HOST）", bool(p2p.relay_host)),
                ("中继预共享密钥（RELAY_PSK，base64 32B）", p2p.psk_valid),
                ("远程节点 ID（REMOTE_NODE_ID）", bool(p2p.node_id)),
            ) if not ok]
            if missing:
                return SwitchResult(ok=False, error=(
                    f"P2P 管道配置不全，缺: {'、'.join(missing)}"))
        # 校验阶段按「目标管道」构建 client（mode 即开关——点击时存量 mode
        # 为空，成功后才写入; 不传 override 会读到 None → 纯 P2P 场景 client 缺失）。
        # _validating 防心跳并发重建（探测不持锁期间，心跳以存量配置视角
        # close 校验用 client → 在途探测挂死在已关闭的 transport loop）。
        with self._lock:
            self._validating = True
            self._sync_client_locked(url, token, mode_override=mode)
        try:
            ok, reason, info = await self._probe_raw()
        finally:
            with self._lock:
                self._validating = False
        if not ok:
            return SwitchResult(ok=False, error=f"远程校验失败: {reason}")

        # 版本指纹对比（不一致警告不阻断; 注册表遍历——多态 snapshot 直比）
        from services.model_assets import ModelAssetRegistry
        warnings: list[str] = []
        assert info is not None
        for asset in ModelAssetRegistry.MODELS:
            remote_m = next(
                (x for x in info.models if x.repo_id == asset.repo_id), None)
            local_snap = asset.local_snapshot()
            if (remote_m is not None and local_snap and remote_m.snapshot
                    and local_snap != remote_m.snapshot):
                warnings.append(
                    f"模型 {asset.display} 版本不一致（本地 {local_snap[:8]}… / "
                    f"远程 {remote_m.snapshot[:8]}…）——向量空间可能漂移")

        ConfigManager.get_instance().set_one(
            ConfigManager.Keys.REMOTE_TRANSPORT_MODE, mode.value)
        self.reload_config()
        # 立即评估（校验刚成功 → 单次定态 REMOTE）
        with self._lock:
            self._state = self.STATE_REMOTE
            self._fail_streak = 0
            self._recover_streak = 1
            self._last_ok_at = time.time()
            self._last_health = info
            self._schedule_unload_locked()
            self._schedule_remote_tts_warmup_locked()
        logger.info("切换远程成功（url=%s, warnings=%d）", url, len(warnings))
        return SwitchResult(ok=True, warnings=warnings)

    def switch_off(self) -> SwitchResult:
        """关闭远程（清空 REMOTE_TRANSPORT_MODE——mode 即开关）→ OFF。本地模型保持加载（不卸载）。"""
        ConfigManager.get_instance().set_one(
            ConfigManager.Keys.REMOTE_TRANSPORT_MODE, "")
        with self._lock:
            self._state = self.STATE_OFF
            self._cancel_unload_locked()
        logger.info("切换本地（REMOTE_TRANSPORT_MODE 清空; 本地模型保持加载）")
        return SwitchResult(ok=True)

    def reload_config(self) -> None:
        """配置热重载: 重建 client + 清零计数（PUT /api/config?surface=remote 写管道键后由写边界钩子调用）。"""
        url, _enabled, token = self._read_config()
        with self._lock:
            p2p = self._p2p_config_locked()
            self._sync_client_locked(url, token)
            self._fail_streak = 0
            self._recover_streak = 0
            if not (url or p2p is not None):  # 两管道均不可用才 OFF（p2p 免 URL）
                self._state = self.STATE_OFF
                self._cancel_unload_locked()

    def _p2p_config_locked(
            self, mode_override: RemoteTransportMode | None = None,
    ) -> "TransportConfig | None":
        """P2P 传输配置（管道为 P2P 且四项齐备才注入）。

        mode_override: 校验阶段传「目标管道」（mode 即开关——点击时配置里的
        mode 必然为空，成功后才写入; 校验必须按目标管道构建探测 client，
        读存量配置会得到 None → 误报"客户端未初始化"）。None = 读存量配置
        （心跳/热重载路径）。校验场景只会传具体枚举（P2P/HTTP）——不存在
        "override 成 None"的需求。
        """
        from services.config_manager import ConfigManager
        from services.remote_transport import TransportConfig
        p2p = ConfigManager.get_instance().p2p_settings()
        mode = mode_override if mode_override is not None else p2p.transport_mode
        # 管道注入: 仅 mode 为 P2P（fail-closed——None/http 均不注入）;
        # 四项齐备（psk+host+node）才走隧道，缺任一即 None（HTTP 或不可用）
        if not (mode is RemoteTransportMode.P2P and p2p.psk_valid
                and p2p.relay_host and p2p.node_id):
            return None
        t = _tunables()
        return TransportConfig(
            relay_host=p2p.relay_host, relay_port=p2p.relay_port,
            psk=p2p.psk, node_id=p2p.node_id,
            punch_timeout_sec=t.punch_timeout_sec,
            api_timeout_sec=t.p2p_api_timeout_sec)

    def _sync_client_locked(self, url: str, token: str,
                            mode_override: RemoteTransportMode | None = None,
    ) -> None:
        """URL/token/P2P 配置变化时重建 client（持锁调用）。

        mode_override: 校验阶段传目标管道（详见 _p2p_config_locked）。
        校验进行中（_validating）挡**外部重建**（心跳/reload 以存量配置
        视角 close 校验用 client → 在途探测挂死）——但放行校验自身的
        override 构建（mode_override 路径）。
        """
        p2p = self._p2p_config_locked(mode_override)
        # 未变跳过（幂等短路）
        if (self._client is not None and url == self._client_url
                and token == self._client_token and p2p == self._client_p2p):
            return
        # 防拆: 校验中 + 外部调用（无 override）+ 已有 client → 跳过重建
        if (self._validating and self._client is not None
                and mode_override is None):
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
            probe_timeout=t.probe_timeout_sec, p2p=p2p) if (url or p2p) else None
        self._client_url = url
        self._client_token = token
        self._client_p2p = p2p
        if url or p2p:
            logger.info("远程 client 已（重）建: 管道=%s（url=%s）",
                        "p2p" if p2p else "http", url or "<无>")

    # ── 状态快照 ─────────────────────────────────────────

    def status(self) -> RemoteLinkStatus:
        from services.runtime_identity import code_fingerprint_str
        url, enabled, token = self._read_config()
        mode = ConfigManager.get_instance().p2p_settings().transport_mode
        local_fp = code_fingerprint_str()  # 文件系统 IO（glob+内容哈希）——锁外执行
        # 模型态采集在锁外: 单项采集可跨服务（如 TTS.ready → 远程可用性判定）
        # ——锁内调用会与非重入 status 锁自死锁（曾致 /api/models 全挂）
        from services.model_assets import ModelAssetRegistry, ModelLoadState
        local_models = [
            LocalModelState(id=m.id, display=m.display, state=_safe_state(m))
            for m in ModelAssetRegistry.MODELS
        ]
        with self._lock:
            countdown: float | None = None
            if self._unload_due_at is not None:
                countdown = max(0.0, self._unload_due_at - time.monotonic())
            client = self._client
            path = ""
            direct_err = ""
            if client is not None:  # 纯属性读（无回调/无阻塞——锁内安全）
                try:
                    path = client.transport_path()
                    direct_err = client.direct_last_error()
                except Exception:  # noqa: BLE001 —— 可见性字段不阻断状态快照
                    pass
            return RemoteLinkStatus(
                enabled=enabled,
                url=url,
                token_configured=bool(token),
                token_prefix=token[:6] if token else "",
                state=self._state,
                transport=mode,
                local_code_fingerprint=local_fp,
                path=path,
                direct_last_error=direct_err,
                fail_streak=self._fail_streak,
                recover_streak=self._recover_streak,
                last_ok_at=self._last_ok_at,
                last_fail_reason=self._last_fail_reason,
                remote_health=self._last_health,  # 同型直传（零搬运）
                local_models=local_models,
                unload_countdown_sec=countdown,
                probe_attempts=self._probe_attempts,
                probe_interval_sec=_tunables().heartbeat_interval_sec,
                next_probe_in_sec=max(
                    0.0, self._next_probe_at - time.monotonic())
                if self._next_probe_at else 0.0,
            )


