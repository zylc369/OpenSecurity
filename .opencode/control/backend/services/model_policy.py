"""模型生命周期策略表（唯一权威; 启动参数可覆盖空闲释放值）。

- release_sec: None=常驻(不释放); 正数=空闲该秒数后释放
- 场景差异（如远程节点 TTS 常驻）通过 server.py 启动参数注入:
    --model-idle-sec cosyvoice3-8bit=0   (0 = 常驻)
- 改默认: 直接改 DEFAULT_RELEASE_SEC（单一权威, 不引入配置文件层）
"""
from __future__ import annotations

# 空闲释放秒数默认值（改需求: 只改这里）; None=常驻
DEFAULT_RELEASE_SEC: dict[str, float | None] = {
    "bge-m3": None,
    "bge-reranker-v2-m3": None,
    "glm-ocr": 600.0,
    "cosyvoice3-8bit": 1800.0,
}

_KNOWN_IDS: frozenset[str] = frozenset(DEFAULT_RELEASE_SEC)
_OVERRIDES: dict[str, float | None] = {}


def known_ids() -> frozenset[str]:
    """全部受管模型 id（启动参数校验用）。"""
    return _KNOWN_IDS


def apply_idle_override(model_id: str, sec: float) -> None:
    """注入空闲释放覆盖值。sec=0 → 常驻(None); 负数/未知 id → ValueError。"""
    if model_id not in _KNOWN_IDS:
        raise ValueError(f"未知模型 id: {model_id}（已知: {sorted(_KNOWN_IDS)}）")
    if sec < 0:
        raise ValueError(f"空闲释放秒数不可为负: {model_id}={sec}")
    _OVERRIDES[model_id] = None if sec == 0 else float(sec)


def release_sec_of(model_id: str) -> float | None:
    """当前生效的空闲释放秒数（覆盖优先; None=常驻）。未知 id → KeyError。"""
    if model_id in _OVERRIDES:
        return _OVERRIDES[model_id]
    return DEFAULT_RELEASE_SEC[model_id]  # 未知 id 由 KeyError fail fast


def clear_override(model_id: str) -> None:
    """移除覆盖, 恢复默认值（测试/维护用）。"""
    _OVERRIDES.pop(model_id, None)


def reset_overrides_for_tests() -> None:
    """仅测试用: 清空覆盖状态。"""
    _OVERRIDES.clear()
