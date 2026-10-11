"""模型资产单一数据源。

收口原则：/api/models 与 /api/scan 的 models 字段都从本模块取数据，
模型清单/缓存状态/下载管理只在此处实现一次。

模型下载：huggingface_hub.snapshot_download 匿名拉取（BAAI 系列均为公开模型），
自动落到 ~/.cache/huggingface/hub/，sentence-transformers 加载时自动读取。
国内直连不稳时可在 .ai_env 配 HF_ENDPOINT=https://hf-mirror.com（镜像）。
"""
from __future__ import annotations

import os
import platform
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict, cast

import psutil

from services.config_manager import ConfigManager

# 模块级 logger（原类体绑定导致方法内裸名 NameError——类命名空间不在方法名字查找链）
logger = logging.getLogger(__name__ + ".ModelAssetRegistry")

class _OllamaTagEntry(TypedDict, total=False):
    """ollama /api/tags 条目（解析边界模型）。"""
    name: str


class _OllamaTagsResponse(TypedDict, total=False):
    models: "list[_OllamaTagEntry]"


@dataclass(frozen=True)
class ModelCacheState:
    """模型缓存查询结果。"""
    cached: bool
    path: str | None             # 缓存路径或状态说明（如依赖缺失提示）
    size_gb: float


@dataclass(frozen=True)
class HardwareSummary:
    """模型板块整体硬件评估（全部已缓存模型同时驻留的总需求 vs 可用内存）。

    逐模型评估已废弃（三个模型 min_free_gb 恰同值导致三行重复显示）；
    总需求 = sum(已缓存模型的 min_free_gb)——未下载的模型不计入。
    """
    ok: bool
    reason: str                       # ok=False 时的说明（单条）
    notes: tuple[str, ...]
    available_gb: float
    total_required_gb: float


@dataclass(frozen=True)
class DownloadView:
    """下载状态视图（前端展示）。"""
    status: str                  # idle / downloading / done / error
    progress: float              # 0~1
    error: str


@dataclass(frozen=True)
class ModelAssetStatus:
    """模型资产状态（/api/models 与 deps 快照的数据单元）。"""
    id: str
    repo_id: str
    type: str                    # embedder / reranker / ocr
    display: str
    purpose: str
    min_free_gb: float
    disk_gb: float
    cached: bool
    cache_path: str | None
    size_gb: float
    loaded: bool
    idle_sec: float | None            # OCR 专用: 已空闲秒数（其他模型 None）
    idle_timeout_sec: int | None      # OCR 专用: 空闲自动卸载阈值（其他模型 None）
    download: DownloadView


# ─── 模型清单（唯一维护点）────────────────────────────────
# min_free_gb: 加载该模型所需的最小可用内存（GB，粗粒度门槛）
# disk_gb:     权重磁盘占用的参考值（GB，进度估算用）


class ModelAssetKind(StrEnum):
    """模型类型（闭值域——新增类型=新枚举成员+新子类）。"""
    EMBEDDER = "embedder"
    RERANKER = "reranker"
    OCR = "ocr"
    TTS = "tts"


class ModelLoadState(StrEnum):
    """模型本地加载态（跨前后端契约值域——前端 literal union 对齐）。"""
    READY = "ready"
    STARTING = "starting"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelAsset:
    """模型资产基类——多态扩展点: local_state/local_snapshot 由各类型子类
    实现（新增模型=注册表一条声明零逻辑改动; 新增类型=新子类）。
    服务依赖一律方法内延迟 import（循环依赖防护——与 model_loader 链隔离）。
    """
    id: str
    repo_id: str
    type: ModelAssetKind
    display: str
    purpose: str
    min_free_gb: float
    disk_gb: float
    required_files: tuple[str, ...] = ()  # 缓存完整性: 快照目录至少存在其一
    ollama_model: str = ""  # ocr 平台差异（win/linux=Ollama; 空=全平台 HF）

    def local_state(self) -> ModelLoadState:
        """本地加载态（枚举值域; 基类默认 UNKNOWN）。"""
        return ModelLoadState.UNKNOWN

    def loaded(self) -> bool:
        """已加载便捷判定（环境总览/远程页共用口径）。"""
        return self.local_state() == "ready"

    def cache_state(self) -> "ModelCacheState":
        """缓存检测（HF 快照完整性; OcrAsset 覆写平台差异）。"""
        return ModelAssetRegistry.get_instance()._is_cached(self.repo_id)  # noqa: SLF001

    def idle_info(self) -> "tuple[float | None, int | None]":
        """（已空闲秒, 自动卸载阈值）——OCR 专用，其余 (None, None)。"""
        return (None, None)

    def download_worker(self, registry: "ModelAssetRegistry") -> "Callable[[ModelAsset], None] | None":
        """下载执行体（平台/类型差异多态; None=无专属 worker，走默认）。"""
        return registry._download_worker  # noqa: SLF001

    def hub_size_gb(self, registry: "ModelAssetRegistry") -> float:
        """进度口径的磁盘占用（HF hub 默认; TTS 等目录型资产 override）。"""
        return registry._cache_size_gb(self.repo_id)  # noqa: SLF001

    def local_snapshot(self) -> str:
        """本地版本指纹（模型自知其指纹来源: HF snapshot / 目录指纹）。"""
        return ""

    def _hub_snapshot(self) -> str:
        """HF hub snapshot 目录名（embedder/reranker/ocr 共用）。"""
        from pathlib import Path
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        snaps = list(hub.glob(f"models--{self.repo_id.replace('/', '--')}/snapshots/*"))
        return snaps[0].name if snaps else ""


@dataclass(frozen=True)
class EmbedderAsset(ModelAsset):
    def local_state(self) -> str:
        from services.model_loader import ModelInferenceService
        return ModelLoadState(
            ModelInferenceService.get_instance().embedder_status().state)

    def local_snapshot(self) -> str:
        return self._hub_snapshot()


@dataclass(frozen=True)
class RerankerAsset(ModelAsset):
    def local_state(self) -> str:
        from services.model_loader import ModelInferenceService
        return ModelLoadState(
            ModelInferenceService.get_instance().reranker_status().state)

    def local_snapshot(self) -> str:
        return self._hub_snapshot()


@dataclass(frozen=True)
class OcrAsset(ModelAsset):
    def local_state(self) -> str:
        from services.ocr_service import OcrService
        return ModelLoadState(OcrService.get_instance().status().state)

    def cache_state(self) -> "ModelCacheState":
        return ModelAssetRegistry.get_instance()._ocr_cache_state(self)  # noqa: SLF001

    def idle_info(self) -> "tuple[float | None, int | None]":
        from services.ocr_service import OcrService
        st = OcrService.get_instance().status()
        return (OcrService.get_instance().idle_sec(), st.idle_release_sec)

    def download_worker(self, registry: "ModelAssetRegistry") -> "Callable[[ModelAsset], None] | None":
        # OCR 下载链路平台差异大（Ollama/win 分支），专属 worker
        return registry._ocr_download_worker  # noqa: SLF001

    def local_snapshot(self) -> str:
        try:
            from pathlib import PurePath
            from services.ocr_engines import MlxEngine
            p = MlxEngine.find_mlx_model()
            return PurePath(p).parent.name if p else ""
        except Exception:  # noqa: BLE001 —— OCR 指纹缺失不阻断
            return ""


@dataclass(frozen=True)
class TtsAsset(ModelAsset):
    def local_state(self) -> str:
        # engine_loaded = 引擎懒加载真实态（首次合成才载）; 文件就绪是 cached 维度
        from services.tts_service import TtsService
        return (ModelLoadState.READY if TtsService.get_instance().engine_loaded
                else ModelLoadState.IDLE)

    def cache_state(self) -> "ModelCacheState":
        """TTS 缓存判定: 手动目录双文件（onnx+voices）齐备才算 cached。

        不走 HF _is_cached——下载源是 GitHub Release（HF 仓库无 voices.bin，
        引擎所需单文件打包格式与 HF 的分音色文件不兼容）。"""
        from services.tts_service import MODEL_FILE, VOICES_FILE, TTS_ASSET_DIR
        m, v = TTS_ASSET_DIR / MODEL_FILE, TTS_ASSET_DIR / VOICES_FILE
        if m.is_file() and v.is_file():
            size = round((m.stat().st_size + v.stat().st_size) / 1024**3, 2)
            return ModelCacheState(True, str(TTS_ASSET_DIR), size)
        return ModelCacheState(False, None, 0.0)

    def hub_size_gb(self, registry: "ModelAssetRegistry") -> float:  # noqa: ARG002 —— 签名多态一致
        """进度口径: 目录磁盘占用（下载落同目录，poller 可见增长）。"""
        from services.tts_service import TTS_ASSET_DIR
        if not TTS_ASSET_DIR.is_dir():
            return 0.0
        total = sum(f.stat().st_size for f in TTS_ASSET_DIR.rglob("*") if f.is_file())
        return round(total / 1024**3, 2)

    def download_worker(self, registry: "ModelAssetRegistry") -> "Callable[[ModelAsset], None] | None":  # noqa: ARG002 —— 签名多态一致
        """专属下载: kokoro-onnx GitHub Release（v1.0——zf_*/zm_* 中文音色名与代码一致）两文件流式下载。

        线程内直下即可（urllib 不受 HF_HUB_OFFLINE 影响）; 临时名+rename
        原子落盘，中断不残留半文件误判。"""
        def worker(model: ModelAsset) -> None:  # noqa: ARG001 —— 签名一致
            import urllib.request
            from services.tts_service import MODEL_FILE, VOICES_FILE, TTS_ASSET_DIR
            base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
            # v1.1-zh 音色为数字名（zf_001...），与代码/前端的 zf_xiaobei 体系不符——用 v1.0
            TTS_ASSET_DIR.mkdir(parents=True, exist_ok=True)
            for name in (MODEL_FILE, VOICES_FILE):
                tmp = TTS_ASSET_DIR / (name + ".part")
                dst = TTS_ASSET_DIR / name
                try:
                    logger.info("[models] TTS 下载 %s ...", name)
                    # 显式超时流式下载（urlretrieve 无超时——网络异常/代理拦截时无限 hang）
                    req = urllib.request.Request(f"{base}/{name}", method="GET")
                    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 —— 固定 Release URL
                        with open(tmp, "wb") as fh:
                            while True:
                                chunk = resp.read(1 << 20)
                                if not chunk:
                                    break
                                fh.write(chunk)
                    tmp.rename(dst)
                    logger.info("[models] TTS 完成 %s", name)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise
        return worker

    def local_snapshot(self) -> str:
        """TTS 模型不在 HF hub——目录 size+mtime 短指纹（变更可检测）。"""
        from pathlib import Path
        d = Path.home() / ".cache" / "opensecurity" / "tts"
        if not d.is_dir():
            return ""
        st = max((f.stat() for f in d.rglob("*") if f.is_file()),
                 key=lambda s: s.st_mtime, default=None)
        return f"tts-{int(st.st_size)}-{int(st.st_mtime)}" if st else ""
    # ocr 平台差异：mac(apple silicon)=MLX/HF；win/linux=Ollama。
    # 空 = 全平台 HF 下载（embedder/reranker）
    ollama_model: str = ""
    # 缓存完整性: 快照目录中**至少存在其中一个**文件才算完整（权重文件候选集）。
    # 防"部分下载=已缓存"假完成（snapshot_download 启动即建 repo 目录，
    # scan_cache_dir 只看目录存在会误判; 大权重文件才是下载主体）
    required_files: tuple[str, ...] = ()



# ─── 下载状态管理（进程内全局，线程安全）─────────────────────

@dataclass
class DownloadState:
    status: str = "idle"        # idle / downloading / done / error
    progress: float = 0.0       # 0~1（按磁盘占用近似）
    error: str = ""



class ModelAssetRegistry:
    """模型资产注册表（缓存/下载/状态快照，全局单例）。"""

    _instance: "ModelAssetRegistry | None" = None
    _instance_lock = threading.Lock()

    MODELS: list[ModelAsset] = [
        EmbedderAsset(
            id="bge-m3",
            repo_id="BAAI/bge-m3",
            type=ModelAssetKind.EMBEDDER,
            required_files=("pytorch_model.bin", "model.safetensors"),
            display="BGE-M3",
            purpose="向量化（知识库 / 事件图谱 embedding）",
            min_free_gb=4.0,
            disk_gb=4.3,
        ),
        RerankerAsset(
            id="bge-reranker-v2-m3",
            repo_id="BAAI/bge-reranker-v2-m3",
            type=ModelAssetKind.RERANKER,
            required_files=("pytorch_model.bin", "model.safetensors"),
            display="BGE Reranker v2 m3",
            purpose="重排序（事件检索 rerank）",
            min_free_gb=4.0,
            disk_gb=2.2,
        ),
        OcrAsset(
            id="glm-ocr",
            repo_id="mlx-community/GLM-OCR-4bit",
            type=ModelAssetKind.OCR,
            required_files=("model.safetensors", "pytorch_model.bin"),
            display="GLM-OCR (0.9B)",
            purpose="本地图像文字识别（ocr MCP 后端；mac=MLX / 其他=Ollama）",
            min_free_gb=4.0,
            disk_gb=1.2,
            ollama_model="glm-ocr",
        ),
        TtsAsset(
            id="kokoro-tts",
            repo_id="github:thewh1teagle/kokoro-onnx@model-files-v1.1",  # 下载源标识（实际由专属 worker 下载）
            type=ModelAssetKind.TTS,
            required_files=(),
            display="Kokoro TTS (82M)",
            purpose="远程朗读语音合成（remote-p2p TTS; legado 经 P2P 调用）",
            min_free_gb=1.0,
            disk_gb=0.19,  # v1.0 fp16 onnx 164MB + voices-v1.0 28MB
        ),
    ]


    def __new__(cls) -> "ModelAssetRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ModelAssetRegistry":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _init_once(self) -> None:
        self._states: dict[str, DownloadState] = {m.id: DownloadState() for m in self.MODELS}
        self._lock = threading.Lock()
        # 下载完成/失败时的变更回调（deps 快照失效等消费方注册；service 不 import routes）
        self._change_callbacks: "list[Callable[[str], None]]" = []


    def add_change_callback(self, fn: "Callable[[str], None]") -> None:
        """注册变更回调（下载完成时调用，参数 model_id）。幂等注册。"""
        if fn not in self._change_callbacks:
            self._change_callbacks.append(fn)


    def _notify_change(self, model_id: str) -> None:
        for fn in list(self._change_callbacks):
            try:
                fn(model_id)
            except Exception as e:
                logger.warning("模型回调异常（不干扰下载）: %s", e)


    def _hf_endpoint(self) -> str:
        """HF 端点：.ai_env > 官方默认（env 通道已删）。"""
        val = ConfigManager.get_instance().get("HF_ENDPOINT") or ""
        return val.strip() or "https://huggingface.co"


    def _is_cached(self, repo_id: str) -> ModelCacheState:
        """查询 HF 缓存状态（含完整性: required_files 至少一个存在才算缓存完整）。

        部分（中断/进行中）快照视为未缓存——snapshot_download 对已下文件
        秒过/断点续传，触发重下成本低; 误判"已缓存"会让加载时缺权重文件。
        """
        try:
            from huggingface_hub import scan_cache_dir
            info = scan_cache_dir()
            for repo in info.repos:
                if repo.repo_id == repo_id:
                    size_gb = round(repo.size_on_disk / 1024**3, 2)
                    required = self._required_files_for(repo_id)
                    if not required:
                        return ModelCacheState(True, str(repo.repo_path), size_gb)
                    if self._snapshot_has_any_file(str(repo.repo_path), required):
                        return ModelCacheState(True, str(repo.repo_path), size_gb)
                    logger.info("[models] %s 缓存不完整（缺 %s）——视为未缓存", repo_id, required)
                    return ModelCacheState(False, None, 0.0)
        except Exception as e:
            if "Cache directory not found" in str(e):
                pass  # 首次环境正常态（从没下载过）——静默
            else:
                logger.warning("缓存状态读取异常: %s", e)
        return ModelCacheState(False, None, 0.0)

    def _cache_size_gb(self, repo_id: str) -> float:
        """该 repo 在 HF 缓存的磁盘占用（含 blobs/*.incomplete 进行中文件）。

        仅供进度估算——不能用 _is_cached（其返回值是"完整性判定"语义，
        不完整时 size 归零，会抹掉进度信息）。
        """
        try:
            from huggingface_hub import scan_cache_dir
            for repo in scan_cache_dir().repos:
                if repo.repo_id == repo_id:
                    return round(repo.size_on_disk / 1024**3, 2)
        except Exception:
            pass
        return 0.0

    def _required_files_for(self, repo_id: str) -> tuple[str, ...]:
        """该 repo 的缓存完整性候选文件集（required_files 任一存在即完整）。"""
        for m in self.MODELS:
            if m.repo_id == repo_id:
                return m.required_files
        return ()

    @staticmethod
    def _snapshot_has_any_file(repo_path: str, required: tuple[str, ...]) -> bool:
        """快照目录（repo_path/snapshots/<rev>/）中是否存在任一必需文件。"""
        import glob as _glob
        snaps = _glob.glob(os.path.join(repo_path, "snapshots", "*"))
        for snap in snaps:
            for name in required:
                if os.path.exists(os.path.join(snap, name)):
                    return True
        return False


    def _ocr_cache_state(self, model: ModelAsset) -> ModelCacheState:
        """OCR 模型缓存状态（平台分支）。

        mac(apple silicon): 主环境可 import mlx_vlm + HF 缓存快照 → cached
        其他平台:          Ollama /api/tags 有 glm-ocr → cached
        """
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            from services.ocr_engines import MlxEngine
            hf = self._is_cached(model.repo_id)
            if hf.cached and MlxEngine.mlx_available():
                return hf
            if hf.cached and not MlxEngine.mlx_available():
                return ModelCacheState(False, "模型已缓存但主环境缺 mlx-vlm（依赖页可安装）", hf.size_gb)
            return ModelCacheState(False, None, 0.0)
        # win/linux/intel-mac → Ollama
        try:
            import httpx
        except ImportError:
            return ModelCacheState(False, "缺少 httpx（依赖页可安装）", 0.0)
        try:
            r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
            tags = cast("_OllamaTagsResponse", r.json())
            names = [m.get("name", "") for m in tags.get("models", [])]
            hit = next((m for m in names if m.split(":")[0] == model.ollama_model), None)
            if hit:
                return ModelCacheState(True, f"ollama:{hit}", 2.2)
            return ModelCacheState(False, None, 0.0)
        except (httpx.HTTPError, ValueError):
            return ModelCacheState(False, None, 0.0)


    def hardware_summary(self) -> HardwareSummary:
        """整体硬件评估: 全部已缓存模型同时驻留的总内存需求 vs 当前可用。"""
        avail = round(cast(int, psutil.virtual_memory().available) / 1024**3, 1)
        cached = [m for m in self.MODELS if m.cache_state().cached]
        total = round(sum(m.min_free_gb for m in cached), 1)
        ok = avail >= total
        reason = "" if ok else (
            f"可用内存 {avail}GB 低于全部模型加载需求 {total}GB（关闭占内存的应用后重试）")
        notes: list[str] = []
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            notes.append("Apple Silicon · Metal 加速可用")
        return HardwareSummary(ok=ok, reason=reason, notes=tuple(notes),
                               available_gb=avail, total_required_gb=total)


    def get_model_assets(self) -> list[ModelAssetStatus]:
        """全部模型资产状态（/api/models 与 deps 快照的数据源）。"""
        result: list[ModelAssetStatus] = []
        for m in self.MODELS:
            # 多态委托（新增模型/类型零分发逻辑——各类型子类自知其状态源）
            cache = m.cache_state()
            loaded = m.loaded()
            idle_sec, idle_timeout = m.idle_info()
            with self._lock:
                st = self._states[m.id]
                download = DownloadView(status=st.status, progress=st.progress, error=st.error)
            result.append(ModelAssetStatus(
                id=m.id, repo_id=m.repo_id, type=m.type, display=m.display,
                purpose=m.purpose, min_free_gb=m.min_free_gb, disk_gb=m.disk_gb,
                cached=cache.cached, cache_path=cache.path, size_gb=cache.size_gb,
                loaded=loaded, idle_sec=idle_sec, idle_timeout_sec=idle_timeout,
                download=download,
            ))
        return result


    def start_download(self, model_id: str) -> bool:
        """启动后台下载（幂等：已在下载中直接返回 True）。

        已缓存 → 立即标记 done（不真下载）。理由：缓存由 sentence-transformers
        创建时只拉推理必需文件（部分快照），再跑 snapshot_download 会补齐
        onnx 等冗余大文件（~1.5GB），对使用者是纯浪费。

        Returns:
            False = model_id 不存在。
        """
        model = next((m for m in self.MODELS if m.id == model_id), None)
        if model is None:
            return False

        cache_state = self._is_cached(model.repo_id)
        if cache_state.cached:
            with self._lock:
                self._states[model.id].status = "done"
                self._states[model.id].progress = 1.0
                self._states[model.id].error = ""
            return True

        with self._lock:
            if self._states[model.id].status == "downloading":
                return True  # 幂等
            self._states[model.id].status = "downloading"
            self._states[model.id].progress = 0.0
            self._states[model.id].error = ""

        worker = model.download_worker(self)
        if worker is not None:
            threading.Thread(
                target=worker, args=(model,), daemon=True, name=f"model-dl-{model.id}"
            ).start()
            return True

        threading.Thread(
            target=self._download_worker, args=(model,), daemon=True, name=f"model-dl-{model.id}"
        ).start()
        threading.Thread(
            target=self._progress_poller, args=(model,), daemon=True, name=f"model-dl-progress-{model.id}"
        ).start()
        return True


    def _ocr_download_worker(self, model: ModelAsset) -> None:
        """OCR 模型下载（平台分支）。

        mac(apple silicon): HF snapshot_download 拉模型权重
          （运行环境 mlx-vlm 由依赖检测统一准备，控制台进程内加载）
        其他平台: ollama pull glm-ocr（Ollama 未安装/未运行则报错提示）
        """
        import subprocess
        import sys

        def _fail(msg: str):
            with self._lock:
                self._states[model.id].status = "error"
                self._states[model.id].error = msg

        def _done():
            with self._lock:
                self._states[model.id].status = "done"
                self._states[model.id].progress = 1.0
            self._notify_change(model.id)

        try:
            if platform.system() == "Darwin" and platform.machine() == "arm64":
                # 模型权重（复用 _download_worker 的子进程下载机制：offline 标志剥离）。
                # 运行环境（mlx-vlm）由依赖检测统一准备，不再私建 venv
                endpoint = self._hf_endpoint()
                env = {
                    k: v for k, v in os.environ.items()
                    if k not in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
                }
                env["HF_ENDPOINT"] = endpoint
                script = (
                    "from huggingface_hub import snapshot_download; "
                    f"snapshot_download(repo_id={model.repo_id!r}, endpoint={endpoint!r})"
                )
                r = subprocess.run(
                    [sys.executable, "-c", script],
                    env=env, capture_output=True, text=True, timeout=7200,
                )
                if r.returncode == 0:
                    _done()
                else:
                    _fail(r.stderr.strip()[-400:] or f"退出码 {r.returncode}")
            else:
                r = subprocess.run(
                    ["ollama", "pull", model.ollama_model],
                    capture_output=True, text=True, timeout=7200,
                )
                if r.returncode == 0:
                    _done()
                else:
                    _fail(
                        (r.stderr.strip()[-300:] or f"退出码 {r.returncode}")
                        + "（需先安装并运行 Ollama：https://ollama.com）"
                    )
        except subprocess.TimeoutExpired:
            _fail("下载超时")
        except OSError as e:
            _fail(f"执行异常: {e}")


    def _download_worker(self, model: ModelAsset) -> None:
        """子进程下载。

        为什么是子进程而不是线程内直调：控制台启动时设了 HF_HUB_OFFLINE=1 /
        TRANSFORMERS_OFFLINE=1（model 加载不联网，server.py），而下载恰恰需要联网。
        huggingface_hub 的 offline 标志在 import 时固化，线程内改环境变量不可靠——
        子进程环境干净可控（去掉 offline 标志 + 注入 HF_ENDPOINT）。
        进度不受影响：_progress_poller 按磁盘占用轮询，与进程形态无关。
        """
        import subprocess
        import sys

        endpoint = self._hf_endpoint()
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
        }
        env["HF_ENDPOINT"] = endpoint
        script = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download(repo_id={model.repo_id!r}, endpoint={endpoint!r})"
        )
        try:
            r = subprocess.run(
                [sys.executable, "-c", script],
                env=env, capture_output=True, text=True, timeout=7200,  # 4GB 级下载给 2h
            )
            if r.returncode == 0:
                with self._lock:
                    self._states[model.id].status = "done"
                    self._states[model.id].progress = 1.0
            else:
                self._record_error(model, RuntimeError(r.stderr.strip()[-400:] or f"退出码 {r.returncode}"), endpoint)
        except subprocess.TimeoutExpired:
            self._record_error(model, RuntimeError("下载超时（2 小时）"), endpoint)
        except Exception as e:
            self._record_error(model, e, endpoint)


    def _record_error(self, model: ModelAsset, e: Exception, endpoint: str) -> None:
        hint = ""
        if "hf-mirror" not in endpoint:
            hint = f"（当前端点 {endpoint}。国内网络可在 .ai_env 配置 HF_ENDPOINT=https://hf-mirror.com 后重试）"
        with self._lock:
            self._states[model.id].status = "error"
            self._states[model.id].error = f"{type(e).__name__}: {e}{hint}"


    def _progress_poller(self, model: ModelAsset) -> None:
        """轮询磁盘占用近似进度（snapshot_download 无内置回调）。"""
        import time
        while True:
            with self._lock:
                if self._states[model.id].status != "downloading":
                    return
            size_gb = model.hub_size_gb(self)
            with self._lock:
                self._states[model.id].progress = min(round(size_gb / model.disk_gb, 2), 0.99)
            time.sleep(2)
