"""API 鉴权中间件（局域网暴露面收口）。

策略（默认安全）:
  • 本机来源（127.0.0.1 / ::1 / testclient）→ 放行全部功能
  • 非本机来源（局域网）:
      - 路径在推理白名单（/embed /rerank /api/ocr/extract /api/remote/health
        /api/remote/node-config /api/remote/autostart）→ 校验
        Authorization: Bearer == CONTROL_API_KEY（constant-time）→ 匹配放行
      - 其余路径一律 403（fs/docker/process/config/scan 等管理面绝不暴露局域网）
  • CONTROL_API_KEY 未配置 → 非本机一律 403（此时绑定也仍是 127.0.0.1，
    双保险——未配置即无局域网服务）

设计约束: token 比较用 secrets.compare_digest（防时序侧信道）; 日志不落
token 明文（仅前 6 位）。
"""
from __future__ import annotations

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.config_manager import ConfigManager

logger = logging.getLogger(__name__)

# 局域网可访问的推理类路径（精确匹配; 尾斜杠容忍）
class ApiGuardMiddleware(BaseHTTPMiddleware):
    """按来源与路径执行鉴权（挂在 CORS 之后注册 → 先于 CORS 执行）。"""

    LAN_ALLOWED_PATHS = frozenset({
        "/embed",
        "/rerank",
        "/api/ocr/extract",
        "/api/remote/health",
        "/api/remote/node-config",
        "/api/remote/autostart",
    })

    LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "testclient", "localhost"})

    @classmethod
    def _is_local(cls, host: str | None) -> bool:
        """请求来源是否本机（testclient 为 httpx.TestClient 的固定 scope 值，
        生产 TCP 对端不可能出现该字符串——纳入本机名单仅服务于测试）。"""
        return (host or "").lower() in cls.LOCAL_HOSTS

    @classmethod
    def _path_allowed(cls, path: str) -> bool:
        """路径是否在局域网白名单（精确 + 尾斜杠容忍）。"""
        normalized = path.rstrip("/") or "/"
        return normalized in cls.LAN_ALLOWED_PATHS

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        host = request.client.host if request.client else None
        if self._is_local(host):
            return await call_next(request)

        cm = ConfigManager.get_instance()
        api_key = (cm.get(cm.Keys.CONTROL_API_KEY) or "").strip()
        if not api_key:
            logger.warning("鉴权拒绝（未配置 CONTROL_API_KEY）: host=%s path=%s", host, request.url.path)
            return JSONResponse(
                {"detail": "Forbidden: 本控制台未开放局域网访问（CONTROL_API_KEY 未配置）"},
                status_code=403)

        if not self._path_allowed(request.url.path):
            logger.warning("鉴权拒绝（路径不在局域网白名单）: host=%s path=%s", host, request.url.path)
            return JSONResponse(
                {"detail": "Forbidden: 该接口仅限本机访问"},
                status_code=403)

        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {api_key}"
        if not secrets.compare_digest(auth, expected):
            logger.warning("鉴权拒绝（令牌错误）: host=%s path=%s auth_prefix=%s",
                           host, request.url.path, auth[:12])
            return JSONResponse(
                {"detail": "Unauthorized: 令牌无效"},
                status_code=401)

        return await call_next(request)
