"""API 审计中间件——所有请求入口/出口完整留痕（纯 ASGI 层，零消耗）。

实现: 拦截 receive/send channel——请求 body 经 receive 累积（转发原始消息，
下游零感知）; 响应 body 经 send 累积（原样透传，客户端零影响）。不经
BaseHTTPMiddleware（其 _StreamingResponse 包装下 body_iterator 排干不可靠）。

每请求两行:
  [入口] → GET /path?query 入参: {完整 JSON / <类型, 长度>}
  [出口] ← GET /path → 200 45ms 响应: {完整 JSON / <形态>}
内容分级: 文本类（json/表单/text）打内容; 二进制/超大（>8MB）打形态。
"""
from __future__ import annotations

import logging
import time
from typing import Any, MutableMapping, cast

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("api.audit")

_HARD_CAP = 64 * 1024        # 单条日志内容上限（超长标注总长）
_STREAM_CAP = 8 * 1024 * 1024  # body 收集上限（超出只记形态——透传不受影响）
_TEXT_CT = ("", "application/json", "application/x-www-form-urlencoded",
            "text/plain", "text/html")


def _clip(txt: str) -> str:
    if len(txt) <= _HARD_CAP:
        return txt
    return f"{txt[:_HARD_CAP]}…（截断，共 {len(txt)} 字符）"


# 兜底敏感键前缀（ConfigField type=password 声明之外的渠道——如 MCP 层键）
_SENSITIVE_KEY_FALLBACK = ("API_KEY", "TOKEN", "PSK", "SECRET", "PASSWORD")


def _sensitive_keywords() -> "tuple[str, ...]":
    """敏感键集合（单一事实源: ConfigField type=password 声明派生 + 兜底）。"""
    try:
        from services.config_manager import ConfigFieldType, ConfigManager
        declared = [
            f.key for f in ConfigManager.get_instance()._FIELDS  # noqa: SLF001
            if f.type is ConfigFieldType.PASSWORD]
    except Exception:  # noqa: BLE001 —— 配置模块未就绪（测试沙箱等）—— 兜底可用
        declared = []
    return tuple(declared) + _SENSITIVE_KEY_FALLBACK


def _mask_secrets(txt: str) -> str:
    """敏感值脱敏: JSON 形态键值 + query 串参数（键名含关键词即脱敏值）。

    空值保持空（"未配置"语义不污染）; 大小写不敏感。
    """
    import re
    for kw in _sensitive_keywords():
        # JSON: "KEY":"value"（value 非空才脱——空串保持"未配置"语义）
        txt = re.sub(
            rf'("[^"]*{kw}[^"]*"\s*:\s*)"([^"]+)"',
            lambda m: f'{m.group(1)}"***"', txt, flags=re.IGNORECASE)
        # query 串: token=xxx / key=xxx（& 或行尾边界）
        txt = re.sub(
            rf'([?&][^=&]*{kw}[^=&]*=)([^&\s]+)',
            lambda m: f'{m.group(1)}***', txt, flags=re.IGNORECASE)
    return txt


def _scope_str(scope: Scope, key: str, default: str = "") -> str:
    """scope 值定型取值（isinstance 窄化——Any 不外泄）。"""
    v = cast("object", scope.get(key, default))
    return v if isinstance(v, str) else default


def _scope_bytes(scope: Scope, key: str) -> bytes:
    v = cast("object", scope.get(key))
    return v if isinstance(v, bytes) else b""


def _header(scope: Scope, name: str) -> str:
    pairs = cast("list[tuple[bytes, bytes]]", scope.get("headers") or [])
    for k, v in pairs:
        if k.decode(errors="replace").lower() == name:
            return v.decode(errors="replace")
    return ""


class AuditMiddleware:
    """纯 ASGI 中间件（app.add_middleware 直接兼容）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = _scope_str(scope, "method", "?")
        path = _scope_str(scope, "path", "?")
        qs = _scope_bytes(scope, "query_string").decode(errors="replace")
        ctype = _header(scope, "content-type").split(";")[0].strip()
        is_read = method in ("GET", "HEAD", "OPTIONS")
        log_body = (not is_read) and ctype in _TEXT_CT

        # ── 请求 body 累积（透传原始 receive 消息——下游零感知）──
        req_parts: list[bytes] = []
        req_total = 0

        async def recv() -> MutableMapping[str, Any]:
            nonlocal req_total
            msg = await receive()
            mtype = cast("object", msg.get("type"))
            mbody = cast("object", msg.get("body", b""))
            if mtype == "http.request" and isinstance(mbody, bytes):
                req_total += len(mbody)  # 长度无条件记（含二进制——入口形态行用）
                if log_body and req_total <= _STREAM_CAP:
                    req_parts.append(mbody)  # 内容仅文本类收集
            return msg

        # ── 响应累积（send 原样透传）──
        t0 = time.monotonic()
        status: list[int] = []
        resp_parts: list[bytes] = []
        resp_total = 0

        async def send_wrap(message: MutableMapping[str, Any]) -> None:
            nonlocal resp_total
            if message.get("type") == "http.response.start":
                mst = cast("object", message.get("status", 0))
                status.append(mst if isinstance(mst, int) else 0)
                # 响应开始时请求 body 必已读完——入口行在此打（内容完整）
                # 三路平铺: 只读无 body / 文本类完整 / 二进制形态
                if is_read:
                    logger.info("[入口] → %s %s%s（无 body）", method,
                                path, f"?{qs}" if qs else "")
                elif log_body:
                    raw = b"".join(req_parts)
                    logger.info("[入口] → %s %s%s%s", method, path,
                                f"?{qs}" if qs else "",
                                f" 入参: {_clip(_mask_secrets(raw.decode(errors='replace')))}"
                                if raw else "（空 body）")
                else:  # 二进制/上传类: 类型+长度（内容不落日志; 长度=自统计）
                    logger.info("[入口] → %s %s%s 入参: <%s, %d 字节>",
                                method, path, f"?{qs}" if qs else "",
                                ctype or "未知类型", req_total)
            elif message.get("type") == "http.response.body":
                mdata = cast("object", message.get("body", b""))
                if isinstance(mdata, bytes):
                    resp_total += len(mdata)
                    if resp_total <= _STREAM_CAP:
                        resp_parts.append(mdata)
            await send(message)

        try:
            await self.app(scope, recv, send_wrap)
        except Exception:
            dt = (time.monotonic() - t0) * 1000
            logger.error("[出口] ← %s %s 异常 %.0fms", method, path, dt,
                         exc_info=True)
            raise
        dt = (time.monotonic() - t0) * 1000
        if resp_total > _STREAM_CAP:
            body_txt = f"<响应 {resp_total} 字节（超上限，内容略）>"
        else:
            raw = b"".join(resp_parts)
            # 先脱敏后截断——secret 横跨截断边界时不泄漏前缀
            body_txt = _clip(_mask_secrets(raw.decode(errors="replace"))) if raw else "<空 body>"
        st = status[0] if status else 0
        level = logging.ERROR if st >= 500 else (
            logging.WARNING if st >= 400 else logging.INFO)
        logger.log(level, "[出口] ← %s %s → %d %.0fms 响应: %s%s", method,
                   path, st, dt, body_txt,
                   f" [慢>{2000}ms]" if dt > 2000 else "")


__all__ = ["AuditMiddleware"]
