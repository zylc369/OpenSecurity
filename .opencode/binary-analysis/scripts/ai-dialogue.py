"""通用 AI 对话工具 — 通过 opencode serve 与目标模型对话

架构：
  本工具 → HTTP → 127.0.0.1:4096 (opencode serve) → 供应商 → 目标模型

能力：
  - 创建指定模型 + agent 的会话，获取 session_id
  - 用同一个 session_id 连续发消息（多轮对话，上下文自动保持）
  - 列出/删除会话
  - 上下文压缩（summarize）

agent 参数决定目标模型运行的 agent 上下文（system prompt、工具链、规则）。
例如 --agent ai-security-analysis 让目标模型在 ai-security-analysis agent 上下文中运行。
"""

import json
import logging
import socket
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4096
DEFAULT_TIMEOUT = 600
DEFAULT_IDLE_TIMEOUT = 600
SSE_POLL_INTERVAL = 15  # socket timeout for SSE read polling


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _request(method: str, url: str, body: dict | None = None,
             timeout: int = DEFAULT_TIMEOUT) -> dict:
    """发送 HTTP 请求到 opencode serve，返回 JSON 响应"""
    data = json.dumps(body, ensure_ascii=False).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw:
                return {}
            return json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode() if exc.fp else ""
        try:
            err = json.loads(raw)
        except json.JSONDecodeError:
            err = {"error": raw}
        raise RuntimeError(f"opencode API 错误 ({exc.code}): {err}") from exc


# ── 会话管理 ──────────────────────────────────────────────────

def session_create(host: str, port: int, model_id: str, provider_id: str,
                   agent: str, title: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """创建新会话，返回 {"session_id": "...", ...}"""
    body = {
        "model": {"id": model_id, "providerID": provider_id},
        "agent": agent,
    }
    if title:
        body["title"] = title
    result = _request("POST", f"{_base_url(host, port)}/session", body, timeout=timeout)
    return _parse_session(result)


def session_list(host: str, port: int, limit: int = 20) -> list[dict]:
    """列出现有会话"""
    result = _request("GET", f"{_base_url(host, port)}/session?limit={limit}")
    if isinstance(result, list):
        return [_parse_session(s) for s in result]
    return []


def session_delete(host: str, port: int, session_id: str) -> bool:
    """删除会话"""
    result = _request("DELETE", f"{_base_url(host, port)}/session/{session_id}")
    return bool(result is True or (isinstance(result, dict) and result.get("result") is True))


def session_summarize(host: str, port: int, session_id: str) -> bool:
    """压缩会话上下文（保留关键信息，减少 token 占用）"""
    result = _request("POST", f"{_base_url(host, port)}/session/{session_id}/summarize")
    return bool(result is True or (isinstance(result, dict) and result.get("result") is True))


def session_messages(host: str, port: int, session_id: str) -> list[dict]:
    """获取会话的全部消息历史"""
    return _request("GET", f"{_base_url(host, port)}/session/{session_id}/messages")


# ── 发送消息（核心，v2 API + SSE 空闲超时） ──────────────────

def send_message(host: str, port: int, session_id: str, content: str,
                 model_id: str | None = None, provider_id: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT,
                 idle_timeout: int = DEFAULT_IDLE_TIMEOUT) -> dict:
    """向会话发送消息，返回 {"content": "回复文本", "session_id": "...", ...}

    使用 v2 API：提交 prompt（立即返回）→ 监听 SSE 事件流 → 空闲超时检测 → 取最终消息。
    空闲超时：只要持续有事件（模型输出块、工具执行等），就不会超时。
    只有连续 idle_timeout 秒无任何事件才超时。
    """
    base = _base_url(host, port)

    # 1. 提交 prompt（v2 API，立即返回）
    _request("POST", f"{base}/api/session/{session_id}/prompt", {
        "prompt": {"parts": [{"type": "text", "text": content}]},
    }, timeout=30)

    # 2. 监听 SSE 事件流，检测空闲超时
    _monitor_session_activity(host, port, session_id, idle_timeout)

    # 3. 取最新消息（用 v1 端点，返回格式与现有解析一致）
    result = _request("GET", f"{base}/session/{session_id}/messages")
    messages = result if isinstance(result, list) else result.get("data", result)

    # 找最新的 assistant 消息
    for msg in reversed(messages):
        role = msg.get("info", {}).get("role", msg.get("role", ""))
        if role == "assistant":
            return _parse_message_response(msg, session_id)

    return {"session_id": session_id, "content": "", "message_id": ""}


def _monitor_session_activity(host: str, port: int, session_id: str, idle_timeout: int):
    """监听 SSE 事件流，等待 session 处理完成。空闲超时：连续 idle_timeout 秒无事件则放弃。"""
    base = _base_url(host, port)
    url = f"{base}/api/event"
    req = Request(url)
    req.add_header("Accept", "text/event-stream")

    last_activity = time.time()
    buf = ""

    try:
        with urlopen(req, timeout=SSE_POLL_INTERVAL) as resp:
            while True:
                try:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk.decode()
                    last_activity = time.time()

                    while "\n\n" in buf:
                        raw_event, buf = buf.split("\n\n", 1)
                        event = _parse_sse_event(raw_event)
                        if not event:
                            continue
                        if event.get("sessionID") != session_id:
                            continue
                        etype = event.get("type", "")
                        if etype in ("session.next.step.ended", "session.next.step.failed"):
                            return
                except socket.timeout:
                    idle = time.time() - last_activity
                    if idle > idle_timeout:
                        raise TimeoutError(
                            f"Idle timeout: no activity for {idle:.0f}s (limit: {idle_timeout}s)"
                        )
    except TimeoutError:
        raise
    except Exception:
        pass  # SSE 连接异常不致命，继续取消息


def _parse_sse_event(raw: str) -> dict | None:
    """解析单个 SSE 事件块，提取 data JSON"""
    for line in raw.strip().split("\n"):
        if line.startswith("data:"):
            data = line[5:].strip()
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
    return None


# ── 响应解析 ──────────────────────────────────────────────────

def _parse_session(raw: dict) -> dict:
    """从 opencode session 响应提取关键字段"""
    return {
        "session_id": raw.get("id", ""),
        "title": raw.get("title", ""),
        "model_id": raw.get("model", {}).get("id", ""),
        "provider_id": raw.get("model", {}).get("providerID", ""),
        "agent": raw.get("agent", ""),
        "created_at": raw.get("createdAt", raw.get("time", {}).get("created", 0)),
    }


def _parse_message_response(raw: dict, session_id: str) -> dict:
    """从 opencode prompt 响应提取回复文本"""
    text_parts = []
    for part in raw.get("parts", []):
        if part.get("type") == "text":
            text_parts.append(part.get("text", ""))

    info = raw.get("info", {})
    return {
        "session_id": session_id,
        "message_id": info.get("id", ""),
        "content": "\n".join(text_parts),
        "model_id": info.get("modelID", ""),
        "tokens": info.get("tokens", {}),
        "cost": info.get("cost", 0),
    }


# ── CLI ───────────────────────────────────────────────────────

def build_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="通用 AI 对话工具 — 通过 opencode serve 与目标模型对话",
        prog="ai-dialogue",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # create
    cmd_create = sub.add_parser("create", help="创建新会话")
    cmd_create.add_argument("-t", "--target-model", required=True,
                            help="目标模型 ID，如 deepseek-v4-pro")
    cmd_create.add_argument("--agent", required=True,
                            help="目标模型运行的 agent（如 ai-security-analysis、binary-analysis、web-analysis）")
    cmd_create.add_argument("--provider", default="opencode-go",
                            help="模型供应商（默认: opencode-go）")
    cmd_create.add_argument("--title", default=None, help="会话标题")

    # send
    cmd_send = sub.add_parser("send", help="向会话发送消息（支持多轮）")
    cmd_send.add_argument("-s", "--session-id", required=True,
                          help="会话 ID（create 返回的 session_id）")
    cmd_send.add_argument("-p", "--prompt", required=True,
                          help="要发送的消息内容")

    # chat（一次性：create + send + delete）
    cmd_chat = sub.add_parser("chat", help="一次性对话（自动创建/删除会话）")
    cmd_chat.add_argument("-t", "--target-model", required=True,
                          help="目标模型 ID，如 deepseek-v4-pro")
    cmd_chat.add_argument("--agent", required=True,
                          help="目标模型运行的 agent（如 ai-security-analysis、binary-analysis、web-analysis）")
    cmd_chat.add_argument("-p", "--prompt", required=True,
                          help="要发送的消息内容")
    cmd_chat.add_argument("--provider", default="opencode-go",
                          help="模型供应商（默认: opencode-go）")

    # list
    cmd_list = sub.add_parser("list", help="列出会话")

    # messages
    cmd_msgs = sub.add_parser("messages", help="查看会话消息历史")
    cmd_msgs.add_argument("-s", "--session-id", required=True, help="会话 ID")

    # delete
    cmd_del = sub.add_parser("delete", help="删除会话")
    cmd_del.add_argument("-s", "--session-id", required=True, help="会话 ID")

    # summarize
    cmd_sum = sub.add_parser("summarize", help="压缩会话上下文")
    cmd_sum.add_argument("-s", "--session-id", required=True, help="会话 ID")

    # 通用参数
    for cmd in [cmd_create, cmd_send, cmd_chat, cmd_list, cmd_msgs, cmd_del, cmd_sum]:
        cmd.add_argument("--host", default=DEFAULT_HOST,
                         help=f"opencode serve 地址（默认: {DEFAULT_HOST}）")
        cmd.add_argument("--port", type=int, default=DEFAULT_PORT,
                         help=f"opencode serve 端口（默认: {DEFAULT_PORT}）")
        cmd.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                         help=f"HTTP 请求超时秒数（默认: {DEFAULT_TIMEOUT}）")
        cmd.add_argument("--idle-timeout", type=int, default=DEFAULT_IDLE_TIMEOUT,
                         help=f"SSE 空闲超时秒数——连续无事件则放弃（默认: {DEFAULT_IDLE_TIMEOUT}）")

    return p


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args()

    try:
        result = _dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def _dispatch(args) -> dict:
    cmd = args.command

    if cmd == "create":
        return session_create(args.host, args.port, args.target_model,
                              args.provider, args.agent, args.title, timeout=args.timeout)

    if cmd == "send":
        return send_message(args.host, args.port, args.session_id, args.prompt,
                            timeout=args.timeout, idle_timeout=args.idle_timeout)

    if cmd == "chat":
        sess = session_create(args.host, args.port, args.target_model,
                              args.provider, args.agent, title="one-shot",
                              timeout=args.timeout)
        sid = sess["session_id"]
        try:
            msg = send_message(args.host, args.port, sid, args.prompt,
                               timeout=args.timeout, idle_timeout=args.idle_timeout)
            msg["mode"] = "chat"
            return msg
        finally:
            session_delete(args.host, args.port, sid)

    if cmd == "list":
        sessions = session_list(args.host, args.port)
        return {"sessions": sessions}

    if cmd == "messages":
        msgs = session_messages(args.host, args.port, args.session_id)
        return {"session_id": args.session_id, "messages": msgs}

    if cmd == "delete":
        ok = session_delete(args.host, args.port, args.session_id)
        return {"session_id": args.session_id, "deleted": ok}

    if cmd == "summarize":
        ok = session_summarize(args.host, args.port, args.session_id)
        return {"session_id": args.session_id, "summarized": ok}

    return {"error": f"未知命令: {cmd}"}


if __name__ == "__main__":
    main()
