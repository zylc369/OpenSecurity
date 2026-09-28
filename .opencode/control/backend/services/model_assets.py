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
from dataclasses import dataclass

import psutil

from services.config_manager import ConfigManager

# 模块级 logger（原类体绑定导致方法内裸名 NameError——类命名空间不在方法名字查找链）
logger = logging.getLogger(__name__ + ".ModelAssetRegistry")

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


@dataclass(frozen=True)
class ModelAsset:
    id: str
    repo_id: str
    type: str            # embedder / reranker / ocr
    display: str
    purpose: str
    min_free_gb: float
    disk_gb: float
    # ocr 平台差异：mac(apple silicon)=MLX/HF；win/linux=Ollama。
    # 空 = 全平台 HF 下载（embedder/reranker）
    ollama_model: str = ""



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
        ModelAsset(
            id="bge-m3",
            repo_id="BAAI/bge-m3",
            type="embedder",
            display="BGE-M3",
            purpose="向量化（知识库 / 事件图谱 embedding）",
            min_free_gb=4.0,
            disk_gb=4.3,
        ),
        ModelAsset(
            id="bge-reranker-v2-m3",
            repo_id="BAAI/bge-reranker-v2-m3",
            type="reranker",
            display="BGE Reranker v2 m3",
            purpose="重排序（事件检索 rerank）",
            min_free_gb=4.0,
            disk_gb=2.2,
        ),
        ModelAsset(
            id="glm-ocr",
            repo_id="mlx-community/GLM-OCR-4bit",
            type="ocr",
            display="GLM-OCR (0.9B)",
            purpose="本地图像文字识别（ocr MCP 后端；mac=MLX / 其他=Ollama）",
            min_free_gb=4.0,
            disk_gb=1.2,
            ollama_model="glm-ocr",
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
        self._change_callbacks: list = []


    def add_change_callback(self, fn) -> None:
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
        """查询 HF 缓存状态。"""
        try:
            from huggingface_hub import scan_cache_dir
            info = scan_cache_dir()
            for repo in info.repos:
                if repo.repo_id == repo_id:
                    return ModelCacheState(True, str(repo.repo_path),
                                           round(repo.size_on_disk / 1024**3, 2))
        except Exception as e:
            logger.warning("缓存状态读取异常: %s", e)
        return ModelCacheState(False, None, 0.0)


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
            names = [m.get("name", "") for m in r.json().get("models", [])]
            hit = next((m for m in names if m.split(":")[0] == model.ollama_model), None)
            if hit:
                return ModelCacheState(True, f"ollama:{hit}", 2.2)
            return ModelCacheState(False, None, 0.0)
        except (httpx.HTTPError, ValueError):
            return ModelCacheState(False, None, 0.0)


    def _ocr_loaded_state(self) -> bool:
        """OCR 模型当前是否在内存（懒加载 + 空闲卸载，state==ready 即驻留）。"""
        try:
            from services.ocr_service import OcrService
            return OcrService.get_instance().status().state == "ready"
        except Exception:
            return False


    def hardware_summary(self) -> HardwareSummary:
        """整体硬件评估: 全部已缓存模型同时驻留的总内存需求 vs 当前可用。"""
        avail = round(psutil.virtual_memory().available / 1024**3, 1)
        cached = [m for m in self.MODELS if (
            self._ocr_cache_state(m).cached if m.type == "ocr" else self._is_cached(m.repo_id).cached)]
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
        from services.model_loader import ModelInferenceService
        from services.ocr_service import OcrService

        result: list[ModelAssetStatus] = []
        for m in self.MODELS:
            if m.type == "ocr":
                cache = self._ocr_cache_state(m)
                loaded = self._ocr_loaded_state()
                idle_sec = OcrService.get_instance().idle_sec()
                idle_timeout: int | None = OcrService.get_instance().status().idle_release_sec
            elif m.type == "reranker":
                cache = self._is_cached(m.repo_id)
                loaded = ModelInferenceService.get_instance().is_reranker_loaded()  # 懒加载真实态
                idle_sec, idle_timeout = None, None
            else:
                cache = self._is_cached(m.repo_id)
                # 本地真实加载态（远程托管时本地未加载是事实; 远程路由口径由远程 TAB 呈现）
                loaded = ModelInferenceService.get_instance().embedder_status().state == "ready"
                idle_sec, idle_timeout = None, None
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

        cached, _, _ = self._is_cached(model.repo_id)
        if cached:
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

        if model.type == "ocr":
            threading.Thread(
                target=self._ocr_download_worker, args=(model,), daemon=True, name=f"model-dl-{model.id}"
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
            _, _, size_gb = self._is_cached(model.repo_id)
            with self._lock:
                self._states[model.id].progress = min(round(size_gb / model.disk_gb, 2), 0.99)
            time.sleep(2)
