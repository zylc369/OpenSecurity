# -*- coding: utf-8 -*-
"""sploitus_search.py 单元测试。

测试策略：mock requests.post，不依赖网络。
覆盖：请求构造、响应解析、错误处理、limit 截断、命令行入口。
"""
import json
import sys
from unittest.mock import patch, MagicMock
from requests.exceptions import Timeout, ConnectionError as ReqConnError

import pytest


# ─── 请求构造 ──────────────────────────────────────────


def test_request_url(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"exploits": [], "exploits_total": 0},
        )
        sploitus.search("test query")
        args, kwargs = mock_req.post.call_args
        assert args[0] == sploitus.SPLOITUS_API_URL


def test_request_body(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        sploitus.search("Apache 2.4.49", exploit_type="exploits", sort="default", limit=5, offset=0)
        body = mock_req.post.call_args.kwargs["json"]
        assert body["query"] == "Apache 2.4.49"
        assert body["type"] == "exploits"
        assert body["sort"] == "default"
        assert body["title"] is False
        assert body["offset"] == 0


def test_request_headers(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        sploitus.search("test")
        headers = mock_req.post.call_args.kwargs["headers"]
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"
        assert headers["Origin"] == "https://sploitus.com"
        assert "User-Agent" in headers
        assert "Referer" in headers


def test_referer_encoding(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        sploitus.search("Apache path traversal")
        headers = mock_req.post.call_args.kwargs["headers"]
        assert "Apache+path+traversal" in headers["Referer"]


def test_timeout_passed(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        sploitus.search("test")
        assert mock_req.post.call_args.kwargs["timeout"] == sploitus.DEFAULT_TIMEOUT


# ─── 响应解析 ──────────────────────────────────────────


def test_success_returns_results(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "exploits": [
                    {"id": "E1", "title": "Apache Path Traversal", "type": "exploit", "href": "https://ex.com/1"},
                    {"id": "E2", "title": "Apache RCE", "type": "exploit", "href": "https://ex.com/2"},
                ],
                "exploits_total": 2,
            },
        )
        result = sploitus.search("Apache")
        assert result["success"] is True
        assert result["query"] == "Apache"
        assert result["total_matches"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Apache Path Traversal"


def test_empty_results(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200, json=lambda: {"exploits": [], "exploits_total": 0}
        )
        result = sploitus.search("nonexistent")
        assert result["success"] is True
        assert result["total_matches"] == 0
        assert result["results"] == []


def test_limit_truncation(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "exploits": [{"id": f"E{i}", "title": f"T{i}", "type": "exploit", "href": ""} for i in range(20)],
                "exploits_total": 20,
            },
        )
        result = sploitus.search("test", limit=5)
        assert len(result["results"]) == 5


def test_limit_capped_at_max(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "exploits": [{"id": f"E{i}", "title": f"T{i}", "type": "exploit", "href": ""} for i in range(50)],
                "exploits_total": 50,
            },
        )
        result = sploitus.search("test", limit=999)
        assert len(result["results"]) <= sploitus.MAX_LIMIT


# ─── 错误处理 ──────────────────────────────────────────


def test_timeout_error(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.exceptions = __import__("requests.exceptions", fromlist=["Timeout", "ConnectionError"])
        mock_req.post.side_effect = Timeout("timed out")
        result = sploitus.search("test")
        assert result["success"] is False
        assert "超时" in result["error"]


def test_connection_error(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.exceptions = __import__("requests.exceptions", fromlist=["Timeout", "ConnectionError"])
        mock_req.post.side_effect = ReqConnError("connection refused")
        result = sploitus.search("test")
        assert result["success"] is False
        assert "网络连接失败" in result["error"]


def test_http_429(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(status_code=429)
        result = sploitus.search("test")
        assert result["success"] is False
        assert "速率限制" in result["error"]


def test_http_499(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(status_code=499)
        result = sploitus.search("test")
        assert result["success"] is False
        assert "限流" in result["error"]


def test_http_500(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(status_code=500)
        result = sploitus.search("test")
        assert result["success"] is False
        assert "500" in result["error"]


def test_json_decode_error(sploitus):
    with patch.object(sploitus, "requests") as mock_req:
        mock_req.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(side_effect=json.JSONDecodeError("invalid", "doc", 0)),
        )
        result = sploitus.search("test")
        assert result["success"] is False
        assert "JSON" in result["error"]
