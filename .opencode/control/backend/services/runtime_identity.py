"""运行时身份与代码指纹（services 层公共收口——原 routes/health 私有实现下沉）。

消费方: routes/health（/api/health 载荷）、routes/remote（节点 health 载荷）、
remote_link（status 本地对照值）。分层: services 不反向依赖 routes（全仓唯一
违例的修正）。
"""
from __future__ import annotations

import glob
import os


def _code_fingerprint() -> tuple[int, float]:
    """backend 代码指纹: (py 文件数, max mtime)。变更任一 .py → 指纹变。"""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    files = glob.glob(os.path.join(backend_dir, "**", "*.py"), recursive=True)
    return (len(files), max((os.path.getmtime(f) for f in files), default=0.0))


def code_fingerprint_str() -> str:
    """代码指纹（规范格式——本地/远程版本对齐检测的唯一形态）。"""
    n, m = _code_fingerprint()
    return f"py{n:03d}-m{int(m)}"
