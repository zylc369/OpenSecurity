"""纯函数单元测试 — 不需要 opencode serve"""
import json

import pytest


# ════════════════════════════════════════════════════════════
# _base_url
# ════════════════════════════════════════════════════════════

class TestBaseUrl:
    def test_standard(self, dialogue):
        assert dialogue._base_url("127.0.0.1", 4096) == "http://127.0.0.1:4096"

    def test_localhost(self, dialogue):
        assert dialogue._base_url("localhost", 8080) == "http://localhost:8080"

    def test_custom_host(self, dialogue):
        assert dialogue._base_url("10.0.0.5", 3000) == "http://10.0.0.5:3000"


# ════════════════════════════════════════════════════════════
# _parse_session
# ════════════════════════════════════════════════════════════

class TestParseSession:
    def _raw(self, **overrides):
        base = {
            "id": "ses_abc123",
            "title": "test session",
            "model": {"id": "deepseek-v4-flash", "providerID": "opencode-go"},
            "agent": "ai-security-analysis",
            "createdAt": 1700000000000,
        }
        base.update(overrides)
        return base

    def test_full_response(self, dialogue):
        result = dialogue._parse_session(self._raw())
        assert result["session_id"] == "ses_abc123"
        assert result["title"] == "test session"
        assert result["model_id"] == "deepseek-v4-flash"
        assert result["provider_id"] == "opencode-go"
        assert result["agent"] == "ai-security-analysis"
        assert result["created_at"] == 1700000000000

    def test_missing_title(self, dialogue):
        raw = self._raw()
        del raw["title"]
        result = dialogue._parse_session(raw)
        assert result["title"] == ""

    def test_time_created_fallback(self, dialogue):
        """createdAt 缺失时回退到 time.created"""
        raw = self._raw()
        del raw["createdAt"]
        raw["time"] = {"created": 1699000000000}
        result = dialogue._parse_session(raw)
        assert result["created_at"] == 1699000000000

    def test_no_timestamp(self, dialogue):
        raw = self._raw()
        del raw["createdAt"]
        result = dialogue._parse_session(raw)
        assert result["created_at"] == 0

    def test_empty_model(self, dialogue):
        raw = self._raw(model={})
        result = dialogue._parse_session(raw)
        assert result["model_id"] == ""
        assert result["provider_id"] == ""


# ════════════════════════════════════════════════════════════
# _parse_message_response
# ════════════════════════════════════════════════════════════

class TestParseMessageResponse:
    def _raw(self, **overrides):
        base = {
            "info": {
                "id": "msg_001",
                "modelID": "deepseek-v4-flash",
                "tokens": {"total": 100, "input": 80, "output": 20},
                "cost": 0.001,
            },
            "parts": [
                {"type": "text", "text": "Hello"},
            ],
        }
        base.update(overrides)
        return base

    def test_standard(self, dialogue):
        result = dialogue._parse_message_response(self._raw(), "ses_abc")
        assert result["session_id"] == "ses_abc"
        assert result["message_id"] == "msg_001"
        assert result["content"] == "Hello"
        assert result["model_id"] == "deepseek-v4-flash"
        assert result["tokens"]["total"] == 100
        assert result["cost"] == 0.001

    def test_multiple_text_parts_joined(self, dialogue):
        raw = self._raw(parts=[
            {"type": "text", "text": "Part1"},
            {"type": "text", "text": "Part2"},
            {"type": "text", "text": "Part3"},
        ])
        result = dialogue._parse_message_response(raw, "ses_abc")
        assert result["content"] == "Part1\nPart2\nPart3"

    def test_non_text_parts_filtered(self, dialogue):
        raw = self._raw(parts=[
            {"type": "text", "text": "KeepMe"},
            {"type": "image", "url": "http://example.com/x.png"},
            {"type": "tool_call", "name": "bash"},
            {"type": "text", "text": "AlsoKeep"},
        ])
        result = dialogue._parse_message_response(raw, "ses_abc")
        assert result["content"] == "KeepMe\nAlsoKeep"

    def test_empty_parts(self, dialogue):
        raw = self._raw(parts=[])
        result = dialogue._parse_message_response(raw, "ses_abc")
        assert result["content"] == ""

    def test_missing_info(self, dialogue):
        raw = {"parts": [{"type": "text", "text": "Hi"}]}
        result = dialogue._parse_message_response(raw, "ses_abc")
        assert result["content"] == "Hi"
        assert result["message_id"] == ""
        assert result["model_id"] == ""
        assert result["tokens"] == {}
        assert result["cost"] == 0

    def test_empty_text_in_part(self, dialogue):
        raw = self._raw(parts=[{"type": "text", "text": ""}])
        result = dialogue._parse_message_response(raw, "ses_abc")
        assert result["content"] == ""


# ════════════════════════════════════════════════════════════
# build_parser
# ════════════════════════════════════════════════════════════

class TestBuildParser:
    def test_create_requires_model_and_agent(self, dialogue):
        parser = dialogue.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["create"])  # 缺少必传参数

    def test_create_minimal(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["create", "-t", "deepseek-v4-pro", "--agent", "build"])
        assert args.command == "create"
        assert args.target_model == "deepseek-v4-pro"
        assert args.agent == "build"
        assert args.provider == "opencode-go"
        assert args.host == "127.0.0.1"
        assert args.port == 4096
        assert args.timeout == 600

    def test_create_with_all_args(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args([
            "create", "-t", "glm-5.1", "--agent", "ai-security-analysis",
            "--provider", "custom", "--title", "My Session",
            "--host", "10.0.0.1", "--port", "8080", "--timeout", "300",
        ])
        assert args.target_model == "glm-5.1"
        assert args.agent == "ai-security-analysis"
        assert args.provider == "custom"
        assert args.title == "My Session"
        assert args.host == "10.0.0.1"
        assert args.port == 8080
        assert args.timeout == 300

    def test_chat_requires_model_agent_prompt(self, dialogue):
        parser = dialogue.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["chat"])

    def test_chat_minimal(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["chat", "-t", "deepseek-v4-flash", "--agent", "build", "-p", "hi"])
        assert args.command == "chat"
        assert args.target_model == "deepseek-v4-flash"
        assert args.agent == "build"
        assert args.prompt == "hi"

    def test_send_requires_session_and_prompt(self, dialogue):
        parser = dialogue.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["send", "-s", "ses_123"])  # 缺 -p

    def test_send_minimal(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["send", "-s", "ses_123", "-p", "hello"])
        assert args.command == "send"
        assert args.session_id == "ses_123"
        assert args.prompt == "hello"

    def test_delete(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["delete", "-s", "ses_123"])
        assert args.command == "delete"
        assert args.session_id == "ses_123"

    def test_list(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_messages(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["messages", "-s", "ses_123"])
        assert args.command == "messages"

    def test_summarize(self, dialogue):
        parser = dialogue.build_parser()
        args = parser.parse_args(["summarize", "-s", "ses_123"])
        assert args.command == "summarize"

    def test_no_subcommand(self, dialogue):
        parser = dialogue.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ════════════════════════════════════════════════════════════
# _request error handling（mock，不访问网络）
# ════════════════════════════════════════════════════════════

class TestRequestErrorHandling:
    def test_http_error_with_json_body(self, dialogue, monkeypatch):
        from urllib.error import HTTPError
        from io import BytesIO

        def fake_urlopen(req, timeout):
            raise HTTPError(
                url="http://test", code=400,
                hdrs=None,
                fp=BytesIO(json.dumps({"_tag": "InvalidRequestError", "message": "bad payload"}).encode()),
                msg="Bad Request",
            )

        monkeypatch.setattr(dialogue, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="400"):
            dialogue._request("POST", "http://test/session")

    def test_http_error_with_non_json_body(self, dialogue, monkeypatch):
        from urllib.error import HTTPError
        from io import BytesIO

        def fake_urlopen(req, timeout):
            raise HTTPError(
                url="http://test", code=500,
                hdrs=None,
                fp=BytesIO(b"<html>Internal Server Error</html>"),
                msg="Server Error",
            )

        monkeypatch.setattr(dialogue, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="500"):
            dialogue._request("POST", "http://test/session")
