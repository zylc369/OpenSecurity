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
import threading
from dataclasses import dataclass

import psutil

# ─── 模型清单（唯一维护点）────────────────────────────────
# min_free_gb: 加载该模型所需的最小可用内存（GB，粗粒度门槛）
# disk_gb:     权重磁盘占用的参考值（GB，进度估算用）


@dataclass(frozen=True)
class ModelAsset:
    id: str
    repo_id: str
    type: str            # embedder / reranker
    display: str
    purpose: str
    min_free_gb: float
    disk_gb: float


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
]

# ─── 下载状态管理（进程内全局，线程安全）─────────────────────

@dataclass
class DownloadState:
    status: str = "idle"        # idle / downloading / done / error
    progress: float = 0.0       # 0~1（按磁盘占用近似）
    error: str = ""

_states: dict[str, DownloadState] = {m.id: DownloadState() for m in MODELS}
_lock = threading.Lock()


def _hf_endpoint() -> str:
    """HF 端点：环境变量 > .ai_env > 官方默认。"""
    from services import config_store
    val = os.environ.get("HF_ENDPOINT") or config_store.read("HF_ENDPOINT") or ""
    return val.strip() or "https://huggingface.co"


def _is_cached(repo_id: str) -> tuple[bool, str | None, float]:
    """查询缓存状态。返回 (cached, cache_path, size_gb)。"""
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_id == repo_id:
                return True, str(repo.repo_path), round(repo.size_on_disk / 1024**3, 2)
    except Exception:
        pass
    return False, None, 0.0


def _hardware_assessment(model: ModelAsset) -> dict:
    """硬件适配评估。ok=False 时 reasons 说明缺什么。"""
    reasons: list[str] = []
    avail = round(psutil.virtual_memory().available / 1024**3, 1)
    if avail < model.min_free_gb:
        reasons.append(f"可用内存 {avail}GB 低于加载所需 {model.min_free_gb}GB（关闭占内存的应用后重试）")
    notes = []
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        notes.append("Apple Silicon · Metal 加速可用")
    return {"ok": not reasons, "reasons": reasons, "notes": notes, "available_gb": avail}


def get_model_assets() -> list[dict]:
    """全部模型资产状态（/api/models 与 /api/scan.models 的数据源）。"""
    from services import model_loader
    ready = model_loader.is_models_ready()

    result = []
    for m in MODELS:
        cached, cache_path, size_gb = _is_cached(m.repo_id)
        with _lock:
            st = _states[m.id]
            download = {"status": st.status, "progress": st.progress, "error": st.error}
        result.append({
            "id": m.id,
            "repo_id": m.repo_id,
            "type": m.type,
            "display": m.display,
            "purpose": m.purpose,
            "min_free_gb": m.min_free_gb,
            "disk_gb": m.disk_gb,
            "cached": cached,
            "cache_path": cache_path,
            "size_gb": size_gb,
            "loaded": ready,          # embedder/reranker 同源就绪标志（B 方案）
            "hardware": _hardware_assessment(m),
            "download": download,
        })
    return result


def start_download(model_id: str) -> bool:
    """启动后台下载（幂等：已在下载中直接返回 True）。

    已缓存 → 立即标记 done（不真下载）。理由：缓存由 sentence-transformers
    创建时只拉推理必需文件（部分快照），再跑 snapshot_download 会补齐
    onnx 等冗余大文件（~1.5GB），对使用者是纯浪费。

    Returns:
        False = model_id 不存在。
    """
    model = next((m for m in MODELS if m.id == model_id), None)
    if model is None:
        return False

    cached, _, _ = _is_cached(model.repo_id)
    if cached:
        with _lock:
            _states[model.id].status = "done"
            _states[model.id].progress = 1.0
            _states[model.id].error = ""
        return True

    with _lock:
        if _states[model.id].status == "downloading":
            return True  # 幂等
        _states[model.id].status = "downloading"
        _states[model.id].progress = 0.0
        _states[model.id].error = ""

    threading.Thread(
        target=_download_worker, args=(model,), daemon=True, name=f"model-dl-{model.id}"
    ).start()
    threading.Thread(
        target=_progress_poller, args=(model,), daemon=True, name=f"model-dl-progress-{model.id}"
    ).start()
    return True


def _download_worker(model: ModelAsset) -> None:
    """子进程下载。

    为什么是子进程而不是线程内直调：控制台启动时设了 HF_HUB_OFFLINE=1 /
    TRANSFORMERS_OFFLINE=1（model 加载不联网，server.py），而下载恰恰需要联网。
    huggingface_hub 的 offline 标志在 import 时固化，线程内改环境变量不可靠——
    子进程环境干净可控（去掉 offline 标志 + 注入 HF_ENDPOINT）。
    进度不受影响：_progress_poller 按磁盘占用轮询，与进程形态无关。
    """
    import subprocess
    import sys

    endpoint = _hf_endpoint()
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
            with _lock:
                _states[model.id].status = "done"
                _states[model.id].progress = 1.0
        else:
            _record_error(model, RuntimeError(r.stderr.strip()[-400:] or f"退出码 {r.returncode}"), endpoint)
    except subprocess.TimeoutExpired:
        _record_error(model, RuntimeError("下载超时（2 小时）"), endpoint)
    except Exception as e:
        _record_error(model, e, endpoint)


def _record_error(model: ModelAsset, e: Exception, endpoint: str) -> None:
    hint = ""
    if "hf-mirror" not in endpoint:
        hint = f"（当前端点 {endpoint}。国内网络可在 .ai_env 配置 HF_ENDPOINT=https://hf-mirror.com 后重试）"
    with _lock:
        _states[model.id].status = "error"
        _states[model.id].error = f"{type(e).__name__}: {e}{hint}"


def _progress_poller(model: ModelAsset) -> None:
    """轮询磁盘占用近似进度（snapshot_download 无内置回调）。"""
    import time
    while True:
        with _lock:
            if _states[model.id].status != "downloading":
                return
        _, _, size_gb = _is_cached(model.repo_id)
        with _lock:
            _states[model.id].progress = min(round(size_gb / model.disk_gb, 2), 0.99)
        time.sleep(2)
