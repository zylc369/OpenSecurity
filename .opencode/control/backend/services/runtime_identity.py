"""运行时身份与代码指纹（services 层公共收口——原 routes/health 私有实现下沉）。

消费方: routes/health（/api/health 载荷）、routes/remote（节点 health 载荷）、
remote_link（status 本地对照值）。分层: services 不反向依赖 routes（全仓唯一
违例的修正）。
"""
from __future__ import annotations

import glob
import hashlib
import os


def _code_fingerprint() -> tuple[int, str]:
    """backend 代码指纹: (py 文件数, 内容哈希 8hex)。

    内容哈希而非 mtime——同 commit 在两台机器上 checkout 时刻不同，
    mtime 必不同（"与本地一致"永远达不到的误报根因）; 内容哈希
    与写入时间无关，同版本必同指纹。路径排序保证哈希稳定。
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    files = sorted(glob.glob(os.path.join(backend_dir, "**", "*.py"), recursive=True))
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode("utf-8"))
        h.update(b"\0")
        with open(f, "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return (len(files), h.hexdigest()[:8])


def code_fingerprint_str() -> str:
    """代码指纹（规范格式——本地/远程版本对齐检测的唯一形态）。"""
    n, digest = _code_fingerprint()
    return f"py{n:03d}-{digest}"
