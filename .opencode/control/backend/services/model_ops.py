"""模型加载/卸载原语分发（server 预载 与 /api/models load|unload 共用）。

语义: load 阻塞至"真实可用"（预热推理/预热合成——保证不是"提交了加载"而已）;
失败抛异常, 由调用方处置（server 后台线程序化日志; 路由层转 500）。
未知 id → KeyError（调用方先行校验 known_ids）。
"""
from __future__ import annotations


def load(model_id: str) -> None:
    """按 id 加载至可用（阻塞）; 未知 id → KeyError。"""
    from services.model_loader import ModelInferenceService
    if model_id == "bge-m3":
        ModelInferenceService.get_instance().embed_sync("预热")
    elif model_id == "bge-reranker-v2-m3":
        ModelInferenceService.get_instance().rerank_sync("预热", ["warmup"])
    elif model_id == "glm-ocr":
        from services.ocr_service import OcrService
        OcrService.get_instance().warm_up_sync()
    elif model_id == "cosyvoice3-8bit":
        from services.tts_service import TtsService
        svc = TtsService.get_instance()
        svc.warmup()
        if not svc.ready:
            raise RuntimeError("TTS 引擎未就绪（依赖/模型缺失? 见日志）")
    else:
        raise KeyError(model_id)


def unload(model_id: str) -> None:
    """按 id 释放内存（下次使用自动重载）; 未知 id → KeyError。"""
    from services.model_loader import ModelInferenceService
    if model_id == "bge-m3":
        ModelInferenceService.get_instance().release_embedder()
    elif model_id == "bge-reranker-v2-m3":
        ModelInferenceService.get_instance().release_reranker()
    elif model_id == "glm-ocr":
        from services.ocr_service import OcrService
        OcrService.get_instance().release_sync()
    elif model_id == "cosyvoice3-8bit":
        from services.tts_service import TtsService
        TtsService.get_instance().release()
    else:
        raise KeyError(model_id)
