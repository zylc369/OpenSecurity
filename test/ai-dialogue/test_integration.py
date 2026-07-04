"""集成测试 — 需要运行中的 opencode serve (127.0.0.1:4096)

运行方式：pytest test/ai-dialogue/test_integration.py -v
"""
import pytest

from conftest import TEST_MODEL, TEST_PROVIDER, TEST_AGENT


# ════════════════════════════════════════════════════════════
# session_create + session_delete
# ════════════════════════════════════════════════════════════

class TestSessionCreateDelete:
    def test_create_returns_session_id(self, serve):
        mod, host, port = serve
        result = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="test_create")
        assert result["session_id"].startswith("ses_")
        assert result["model_id"] == TEST_MODEL
        assert result["provider_id"] == TEST_PROVIDER
        assert result["agent"] == TEST_AGENT
        # 清理
        mod.session_delete(host, port, result["session_id"])

    def test_create_without_title(self, serve):
        mod, host, port = serve
        result = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT)
        assert result["session_id"].startswith("ses_")
        mod.session_delete(host, port, result["session_id"])

    def test_delete_returns_true(self, serve):
        mod, host, port = serve
        sess = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="to_delete")
        ok = mod.session_delete(host, port, sess["session_id"])
        assert ok is True

    def test_delete_nonexistent_session(self, serve):
        """删除不存在的 session 应该报错而非静默成功"""
        mod, host, port = serve
        with pytest.raises(Exception):
            mod.session_delete(host, port, "ses_nonexistent_xyz")


# ════════════════════════════════════════════════════════════
# session_list
# ════════════════════════════════════════════════════════════

class TestSessionList:
    def test_list_returns_list(self, serve):
        mod, host, port = serve
        result = mod.session_list(host, port)
        assert isinstance(result, list)

    def test_list_after_create_contains_session(self, serve):
        mod, host, port = serve
        sess = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="list_test")
        try:
            sessions = mod.session_list(host, port)
            ids = [s["session_id"] for s in sessions]
            assert sess["session_id"] in ids
        finally:
            mod.session_delete(host, port, sess["session_id"])


# ════════════════════════════════════════════════════════════
# send_message
# ════════════════════════════════════════════════════════════

class TestSendMessage:
    def test_send_returns_content(self, serve):
        mod, host, port = serve
        sess = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="send_test")
        try:
            result = mod.send_message(host, port, sess["session_id"], "回复OK", timeout=120)
            assert result["session_id"] == sess["session_id"]
            assert len(result["content"]) > 0
            assert result["message_id"].startswith("msg_")
            assert result["model_id"] == TEST_MODEL
            assert "total" in result.get("tokens", {})
        finally:
            mod.session_delete(host, port, sess["session_id"])

    def test_send_multiturn_context_preserved(self, serve):
        """同一 session_id 多次 send，上下文应保持"""
        mod, host, port = serve
        sess = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="multiturn")
        try:
            # 第一轮：告诉模型一个秘密
            r1 = mod.send_message(host, port, sess["session_id"],
                                  "记住数字42，下一轮我会问你", timeout=120)
            assert len(r1["content"]) > 0

            # 第二轮：问模型刚才的数字
            r2 = mod.send_message(host, port, sess["session_id"],
                                  "我上一轮告诉你的数字是什么？只回复数字", timeout=120)
            assert "42" in r2["content"]
        finally:
            mod.session_delete(host, port, sess["session_id"])


# ════════════════════════════════════════════════════════════
# chat（create + send + delete 一次性）
# ════════════════════════════════════════════════════════════

class TestChat:
    def test_chat_one_shot(self, serve):
        """chat 等价于手动 create + send + delete"""
        mod, host, port = serve
        sess = mod.session_create(host, port, TEST_MODEL, TEST_PROVIDER, TEST_AGENT, title="one-shot")
        sid = sess["session_id"]
        try:
            msg = mod.send_message(host, port, sid, "回复OK", timeout=120)
            msg["mode"] = "chat"
            assert msg["mode"] == "chat"
            assert len(msg["content"]) > 0
        finally:
            mod.session_delete(host, port, sid)

    def test_chat_via_dispatch(self, serve):
        """通过 _dispatch 测试 chat 命令的完整流程"""
        mod, host, port = serve
        import argparse
        args = argparse.Namespace(
            command="chat",
            target_model=TEST_MODEL,
            agent=TEST_AGENT,
            prompt="回复OK",
            provider=TEST_PROVIDER,
            host=host,
            port=port,
            timeout=120,
        )
        result = mod._dispatch(args)
        assert result["mode"] == "chat"
        assert len(result["content"]) > 0
        assert "session_id" in result
