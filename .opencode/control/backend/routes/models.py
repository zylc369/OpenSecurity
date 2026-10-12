"""/api/models 路由：模型资产查询 + 下载管理。

数据源：services/model_assets.py（与 /api/scan 的 models 字段同源）。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from services.model_assets import HardwareSummary, ModelAssetRegistry, ModelAssetStatus

router = APIRouter(prefix="/api/models", tags=["models"])


@dataclass
class ModelsPayload:
    models: "list[ModelAssetStatus]"
    hardware_summary: HardwareSummary
    hf_endpoint: str


@dataclass
class ModelDownloadAck:
    ok: bool
    model_id: str


@router.get("")
async def list_models() -> ModelsPayload:
    """全部模型资产状态（缓存/加载态/引用数）+ 整体硬件评估。"""
    return ModelsPayload(
        models=ModelAssetRegistry.get_instance().get_model_assets(),
        hardware_summary=ModelAssetRegistry.get_instance().hardware_summary(),
        hf_endpoint=ModelAssetRegistry.get_instance()._hf_endpoint(),
    )


@router.post("/{model_id}/download")
async def download_model(model_id: str) -> "ModelDownloadAck":
    """启动后台下载（幂等）。"""
    ok = ModelAssetRegistry.get_instance().start_download(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未知模型 id: {model_id}")
    return ModelDownloadAck(ok=True, model_id=model_id)


@dataclass
class IngestChunk:
    """模型文件分片（主控经 P2P wire 推送——局域网隔离/外网冷门仓库的部署通路）。"""
    name: str            # 目标文件名（资产目录内相对路径，禁路径穿越）
    offset: int          # 片偏移（字节）
    total: int           # 文件总字节（首片声明，落盘前校验）
    b64: str             # 分片内容（base64; 8MB 原始 → ~11MB 文本）
    done: bool = False   # 末片标记（触发 total 校验）


@router.post("/{model_id}/ingest")
async def ingest_chunk(model_id: str, chunk: IngestChunk) -> "dict[str, object]":
    """接收主控推送的模型文件分片（.part 临时写 → done 原子 rename）。

    仅接受已知资产 id（节点侧无该资产注册时 404）; name 规范化为纯文件名
    （防穿越）。通道安全: P2P Noise 加密（PSK）+ 网关本机转发。
    """
    reg = ModelAssetRegistry.get_instance()
    known = [m.id for m in reg.MODELS if m.id == model_id]
    if not known:
        raise HTTPException(status_code=404, detail=f"未知模型 id: {model_id}")
    import base64
    import re
    from pathlib import Path
    from services.tts_service import TTS_MODEL_DIR
    # 资产目录多态（当前仅 TTS 走推送; 后续资产按需扩展）
    target_dir = TTS_MODEL_DIR
    name = re.sub(r"[^A-Za-z0-9._-]", "_", chunk.name)
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / name
    if chunk.offset == 0:
        dst.with_suffix(dst.suffix + ".part").write_bytes(b"")
    part = dst.with_suffix(dst.suffix + ".part")
    data = base64.b64decode(chunk.b64)
    with open(part, "ab") as fh:
        fh.write(data)
    if chunk.done:
        size = part.stat().st_size
        if size != chunk.total:
            part.unlink(missing_ok=True)
            raise HTTPException(status_code=400,
                                detail=f"分片总长不符: {size} != {chunk.total}")
        part.replace(dst)
    return {"ok": True, "name": name, "received": part.stat().st_size
            if part.exists() else dst.stat().st_size}
