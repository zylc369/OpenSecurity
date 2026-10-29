"""/api/logs 路由：日志查询（grep + limit 语义）。

用途：主控/agent 查询控制台与远程节点日志（节点侧同代码部署；主控经
`/api/remote/node-logs/query` 转发到节点的本端点）。

- 请求只收"日志文件名 + 查询条件 + 是否正则 + 条数"——等价 `grep -E 条件 文件 | tail -n N`；
- 文件名限定 `RuntimePaths.LOGS_DIR` 内（`services.log_query` 单点校验，防穿越）；
- 文件 IO 一律 `asyncio.to_thread`（同 `_forward_get` 的线程域约束：大文件反向读
  可能扫几十 MB，禁在事件循环内同步执行）。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.log_query import LogQueryResult, query_log
from services.runtime_paths import RuntimePaths

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogQueryRequest(BaseModel):
    """日志查询请求（file 为日志文件名——非路径；pattern 空串 = 全部行）。"""

    file: str = Field(min_length=1, max_length=128)
    pattern: str = Field(default="", max_length=1000)
    is_regex: bool = True
    limit: int = Field(default=200, ge=1, le=5000)


@router.post("/query")
async def query_logs(req: LogQueryRequest) -> LogQueryResult:
    """日志查询：返回最近 `limit` 条匹配行（时间正序），`more` 表示还有更早匹配。"""
    try:
        return await asyncio.to_thread(
            query_log, Path(RuntimePaths.LOGS_DIR), req.file, req.pattern, req.is_regex, req.limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"日志文件不存在: {req.file}")
    except re.error as e:
        raise HTTPException(status_code=422, detail=f"非法正则: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
