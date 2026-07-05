"""通用 AI 对话工具 — 通过 opencode serve 与目标模型对话

架构：
  本工具 → HTTP → 127.0.0.1:4096 (opencode serve) → 供应商 → 目标模型

能力：
  - 创建指定模型 + agent 的会话，获取 session_id
  - 用同一个 session_id 连续发消息（多轮对话，上下文自动保持）
  - 列出/删除会话
  - 上下文压缩（summarize）

agent 参数决定目标模型运行的 agent 上下文（system prompt、工具链、规则）。
例如 --agent build 让目标模型在 build agent 上下文中运行（裸模型基线）。
"""

import json
import logging
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4096
DEFAULT_TIMEOUT = 600


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


# ── 发送消息（核心） ──────────────────────────────────────────

def send_message(host: str, port: int, session_id: str, content: str,
                 model_id: str | None = None, provider_id: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> dict:
    """向会话发送消息，返回 {"content": "回复文本", "session_id": "...", "message_id": "..."}

    使用 v1 同步端点 POST /session/:id/message——阻塞直到模型完整生成后返回。
    timeout 控制 HTTP 请求超时（socket 级别，模型生成长内容时可能需要调大）。

    TODO: opencode serve 的 v2 API（prompt + SSE + wait）支持空闲超时检测——
    只要事件流持续推送（text.delta 等）就不超时。但当前实例 v2 执行引擎不可用
    （session.wait 返回 503），暂时回退 v1。
    """
    body: dict = {
        "parts": [{"type": "text", "text": content}],
        "tools": {},
    }
    if model_id and provider_id:
        body["model"] = {"providerID": provider_id, "modelID": model_id}

    result = _request(
        "POST",
        f"{_base_url(host, port)}/session/{session_id}/message",
        body,
        timeout=timeout,
    )
    return _parse_message_response(result, session_id)


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
                            help="目标模型运行的 agent（推荐 build：裸模型基线；其他如 binary-analysis）")
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
                          help="目标模型运行的 agent（推荐 build：裸模型基线；其他如 binary-analysis）")
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

    # scan（批量探测：按策略文件多轮对话，聚合输出）
    cmd_scan = sub.add_parser("scan", help="批量探测（按策略文件多轮对话，聚合输出 JSON）")
    cmd_scan.add_argument("--strategy", required=True,
                          help="策略文件路径（JSON，含 target_model/agent/stages）")
    cmd_scan.add_argument("--output", default=None,
                          help="输出文件路径（可选，默认输出到 stdout）")

    # 通用参数
    for cmd in [cmd_create, cmd_send, cmd_chat, cmd_list, cmd_msgs, cmd_del, cmd_sum, cmd_scan]:
        cmd.add_argument("--host", default=DEFAULT_HOST,
                         help=f"opencode serve 地址（默认: {DEFAULT_HOST}）")
        cmd.add_argument("--port", type=int, default=DEFAULT_PORT,
                         help=f"opencode serve 端口（默认: {DEFAULT_PORT}）")
        cmd.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                         help=f"HTTP 请求超时秒数（默认: {DEFAULT_TIMEOUT}）")

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


def scan_run(host, port, strategy_file, output_file=None, timeout=DEFAULT_TIMEOUT):
    """按策略文件批量探测：create → 按 stages 顺序 send → 聚合 → delete

    策略文件格式（JSON）:
        {
          "target_model": "deepseek-v4-pro",
          "provider": "opencode-go",
          "agent": "build",
          "stages": [
            {"name": "baseline", "prompts": ["问题1", "问题2"]},
            {"name": "injection", "prompts": ["payload1"]}
          ]
        }
    """
    with open(strategy_file, "r", encoding="utf-8") as f:
        strategy = json.load(f)

    target_model = strategy["target_model"]
    provider = strategy.get("provider", "opencode-go")
    agent = strategy["agent"]
    stages = strategy.get("stages", [])

    sess = session_create(host, port, target_model, provider, agent,
                          title="scan", timeout=timeout)
    sid = sess["session_id"]

    results = []
    try:
        for stage in stages:
            stage_name = stage.get("name", "")
            for prompt in stage.get("prompts", []):
                msg = send_message(host, port, sid, prompt, timeout=timeout)
                results.append({
                    "stage": stage_name,
                    "prompt": prompt,
                    "reply": msg.get("content", ""),
                })
    finally:
        session_delete(host, port, sid)

    output = {
        "session_id": sid,
        "target_model": target_model,
        "agent": agent,
        "results": results,
    }

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    return output


def _dispatch(args) -> dict:
    cmd = args.command

    if cmd == "create":
        return session_create(args.host, args.port, args.target_model,
                              args.provider, args.agent, args.title, timeout=args.timeout)

    if cmd == "send":
        return send_message(args.host, args.port, args.session_id, args.prompt,
                            timeout=args.timeout)

    if cmd == "chat":
        sess = session_create(args.host, args.port, args.target_model,
                              args.provider, args.agent, title="one-shot",
                              timeout=args.timeout)
        sid = sess["session_id"]
        try:
            msg = send_message(args.host, args.port, sid, args.prompt,
                               timeout=args.timeout)
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

    if cmd == "scan":
        return scan_run(args.host, args.port, args.strategy,
                        args.output, timeout=args.timeout)

    return {"error": f"未知命令: {cmd}"}


if __name__ == "__main__":
    main()
