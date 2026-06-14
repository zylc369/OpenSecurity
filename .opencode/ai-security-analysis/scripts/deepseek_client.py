#!/usr/bin/env python3
"""
LLM API 多轮对话客户端（兼容 DeepSeek/OpenAI 等兼容 API）

可复用的 LLM API 封装，支持：
- 多轮对话（自动维护上下文）
- 流式/非流式输出
- 思考模式开关
- JSON 输出模式
- 对话历史持久化（JSON）
- 命令行交互模式

用法:
    # 作为模块导入
    from deepseek_client import LLMClient
    client = LLMClient()
    response = client.chat("你好")

    # 指定 OpenAI 兼容 API
    client = LLMClient(base_url="https://api.openai.com/v1", api_key="sk-xxx")
    response = client.chat("Hello")

    # 命令行交互
    python deepseek_client.py --interactive --system "你是一个助手"

    # 单次调用
    python deepseek_client.py --message "你好" --model gpt-4o

兼容性:
    - API 兼容 OpenAI Chat Completions 格式（/chat/completions 端点）
    - 支持 openai Python 库和 raw requests 两种调用方式
    - 默认使用 DeepSeek API（base_url=https://api.deepseek.com）
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Optional, Union, List, Dict, Any
from dataclasses import dataclass, field, asdict


# ============================================================
# 配置
# ============================================================

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096


def _find_project_root() -> Path:
    """查找项目根目录（包含 .privacy-data 的目录）"""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / ".privacy-data").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _find_project_root()
PRIVACY_DATA_PATH = PROJECT_ROOT / ".privacy-data" / "privacy-data.json"


def load_api_key(path: Path = None) -> str:
    """
    加载 API Key，按以下优先级：
    1. 环境变量 LLM_API_KEY
    2. 环境变量 DEEPSEEK_API_KEY
    3. 环境变量 PRIVACY_DATA_PATH 指向的 JSON 文件
    4. 项目 .privacy-data/privacy-data.json（apiKey.deepSeek 字段）
    """
    # 环境变量优先
    for env_key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        key = os.environ.get(env_key, "").strip()
        if key:
            return key

    # 从 JSON 配置文件加载
    candidates = []
    if path:
        candidates.append(path)
    candidates.append(PRIVACY_DATA_PATH)

    # PRIVACY_DATA_PATH 环境变量
    env_path = os.environ.get("PRIVACY_DATA_PATH")
    if env_path:
        candidates.append(Path(env_path))

    for p in candidates:
        p = Path(p)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                key = data.get("apiKey", {}).get("deepSeek", "")
                if key:
                    return key
            except (json.JSONDecodeError, KeyError):
                continue
    return ""


# ============================================================
# 数据类
# ============================================================

@dataclass
class Message:
    """对话消息"""
    role: str  # system | user | assistant
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ConversationTurn:
    """一轮对话记录"""
    timestamp: float
    request_messages: List[Dict[str, str]]
    response_content: str
    response_reasoning: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    model: str = ""
    finish_reason: str = ""


@dataclass
class ConversationHistory:
    """对话历史"""
    turns: List[ConversationTurn] = field(default_factory=list)
    system_prompt: Optional[str] = None
    model: str = DEFAULT_MODEL
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_messages_for_api(self) -> List[Dict[str, str]]:
        """构造发给 API 的 messages 列表（含 system prompt + 所有历史）"""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for turn in self.turns:
            user_msgs = [m for m in turn.request_messages if m["role"] == "user"]
            if user_msgs:
                messages.append({"role": "user", "content": user_msgs[-1]["content"]})
            if turn.response_content:
                messages.append({"role": "assistant", "content": turn.response_content})
        return messages

    def save(self, path: Union[str, Path]):
        """保存对话历史到 JSON"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "system_prompt": self.system_prompt,
            "model": self.model,
            "metadata": self.metadata,
            "turns": [asdict(t) for t in self.turns],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ConversationHistory":
        """从 JSON 加载对话历史"""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        history = cls(
            system_prompt=data.get("system_prompt"),
            model=data.get("model", DEFAULT_MODEL),
            metadata=data.get("metadata", {}),
        )
        for t in data.get("turns", []):
            history.turns.append(ConversationTurn(**t))
        return history


# ============================================================
# LLM 客户端
# ============================================================

class LLMClient:
    """
    LLM API 多轮对话客户端（兼容 DeepSeek/OpenAI 等 OpenAI 兼容 API）

    特性:
    - 自动维护多轮对话上下文
    - 支持流式/非流式
    - 思考模式控制
    - JSON 模式
    - 对话历史持久化
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        system_prompt: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        thinking_enabled: bool = False,
        history_path: Optional[Union[str, Path]] = None,
    ):
        self.api_key = api_key or load_api_key()
        if not self.api_key:
            raise ValueError(
                "未找到 API Key。请通过以下方式之一提供:\n"
                "  1. 传参 api_key='...'\n"
                "  2. 环境变量 LLM_API_KEY 或 DEEPSEEK_API_KEY\n"
                "  3. 项目 .privacy-data/privacy-data.json 文件（apiKey.deepSeek 字段）"
            )

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking_enabled = thinking_enabled

        self.history = ConversationHistory(
            system_prompt=system_prompt,
            model=model,
        )
        self.history_path = Path(history_path) if history_path else None

        # 尝试用 openai 库，失败则用 requests
        self._use_openai = False
        try:
            from openai import OpenAI
            self._openai_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self._use_openai = True
        except ImportError:
            import requests
            self._requests = requests

    # ----------------------------------------------------------
    # 核心方法
    # ----------------------------------------------------------

    def chat(
        self,
        message: str,
        *,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        thinking_enabled: Optional[bool] = None,
        json_mode: bool = False,
        stream: bool = False,
        save_history: bool = True,
    ) -> str:
        """
        发送消息并获取回复（自动维护多轮上下文）

        Args:
            message: 用户消息
            system_prompt: 临时覆盖 system prompt（不持久化到 history）
            model: 临时覆盖模型
            temperature: 临时覆盖温度
            max_tokens: 临时覆盖最大 token
            thinking_enabled: 临时覆盖思考模式
            json_mode: 启用 JSON 输出模式
            stream: 启用流式输出
            save_history: 是否保存对话历史

        Returns:
            assistant 回复内容
        """
        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens
        thinking = thinking_enabled if thinking_enabled is not None else self.thinking_enabled

        messages = self._build_messages(message, system_prompt or self.history.system_prompt)
        start_time = time.time()

        if stream:
            return self._chat_stream(messages, model, temperature, max_tokens, thinking, json_mode)

        response_content, reasoning_content, usage, finish_reason = self._call_api(
            messages, model, temperature, max_tokens, thinking, json_mode
        )

        turn = ConversationTurn(
            timestamp=start_time,
            request_messages=messages,
            response_content=response_content,
            response_reasoning=reasoning_content,
            usage=usage,
            model=model,
            finish_reason=finish_reason,
        )
        self.history.turns.append(turn)

        if save_history and self.history_path:
            self.history.save(self.history_path)

        return response_content

    def chat_raw(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        thinking_enabled: Optional[bool] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        发送原始 messages 列表（不自动拼接历史）

        适用于需要完全控制消息格式的场景。

        Returns:
            完整的 API 响应数据（含 content, reasoning_content, usage 等）
        """
        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens
        thinking = thinking_enabled if thinking_enabled is not None else self.thinking_enabled

        content, reasoning, usage, finish_reason = self._call_api(
            messages, model, temperature, max_tokens, thinking, json_mode
        )

        return {
            "content": content,
            "reasoning_content": reasoning,
            "usage": usage,
            "finish_reason": finish_reason,
            "model": model,
        }

    def reset_history(self, system_prompt: Optional[str] = None):
        """重置对话历史"""
        self.history = ConversationHistory(
            system_prompt=system_prompt or self.history.system_prompt,
            model=self.model,
        )

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _build_messages(self, user_message: str, system_prompt: Optional[str]) -> List[Dict[str, str]]:
        """构造完整的 messages 列表"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for turn in self.history.turns:
            user_msgs = [m for m in turn.request_messages if m["role"] == "user"]
            if user_msgs:
                messages.append({"role": "user", "content": user_msgs[-1]["content"]})
            if turn.response_content:
                messages.append({"role": "assistant", "content": turn.response_content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _call_api(self, messages, model, temperature, max_tokens, thinking, json_mode):
        """调用 API（非流式）"""
        if self._use_openai:
            return self._call_openai(messages, model, temperature, max_tokens, thinking, json_mode)
        else:
            return self._call_requests(messages, model, temperature, max_tokens, thinking, json_mode)

    def _call_openai(self, messages, model, temperature, max_tokens, thinking, json_mode):
        """通过 openai 库调用"""
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if thinking:
            kwargs["thinking"] = {"type": "enabled"}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._openai_client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning_content", None)
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        return content, reasoning, usage, choice.finish_reason

    def _call_requests(self, messages, model, temperature, max_tokens, thinking, json_mode):
        """通过 requests 调用（openai 库不可用时的后备）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if thinking:
            payload["thinking"] = {"type": "enabled"}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = self._requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        reasoning = choice["message"].get("reasoning_content")
        usage = data.get("usage", {})
        return content, reasoning, usage, choice["finish_reason"]

    def _chat_stream(self, messages, model, temperature, max_tokens, thinking, json_mode):
        """流式输出（生成器）"""
        if not self._use_openai:
            print("⚠️  流式输出需要 openai 库，请安装: pip install openai", file=sys.stderr)
            return self._call_api(messages, model, temperature, max_tokens, thinking, json_mode)[0]

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if thinking:
            kwargs["thinking"] = {"type": "enabled"}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        stream = self._openai_client.chat.completions.create(**kwargs)
        full_content = []
        full_reasoning = []

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    print(delta.content, end="", flush=True)
                    full_content.append(delta.content)
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    full_reasoning.append(delta.reasoning_content)

        print()
        content = "".join(full_content)
        reasoning = "".join(full_reasoning) if full_reasoning else None

        turn = ConversationTurn(
            timestamp=time.time(),
            request_messages=messages,
            response_content=content,
            response_reasoning=reasoning,
            model=model,
        )
        self.history.turns.append(turn)
        if self.history_path:
            self.history.save(self.history_path)
        return content


# 向后兼容别名
DeepSeekClient = LLMClient


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="LLM API 多轮对话客户端（兼容 DeepSeek/OpenAI）")
    parser.add_argument("--api-key", help="API Key（默认从环境变量或 privacy-data 读取）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名称")
    parser.add_argument("--system", help="System prompt")
    parser.add_argument("--message", "-m", help="单次消息（不进入交互模式）")
    parser.add_argument("--temperature", "-t", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--thinking", action="store_true", help="启用思考模式")
    parser.add_argument("--json", action="store_true", help="启用 JSON 输出模式")
    parser.add_argument("--stream", action="store_true", help="启用流式输出")
    parser.add_argument("--history", help="对话历史保存路径（JSON）")
    parser.add_argument("--load-history", help="加载已有对话历史文件")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")

    args = parser.parse_args()

    client = LLMClient(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        system_prompt=args.system,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        thinking_enabled=args.thinking,
        history_path=args.history,
    )

    if args.load_history:
        client.history = ConversationHistory.load(args.load_history)
        print(f"✅ 已加载 {len(client.history.turns)} 轮对话历史")

    if args.message:
        response = client.chat(args.message, stream=args.stream, json_mode=args.json)
        if not args.stream:
            print(response)
    elif args.interactive or not args.message:
        print("🤖 LLM 多轮对话客户端（输入 /quit 退出，/reset 重置历史）")
        print(f"   模型: {args.model} | API: {args.base_url} | 思考: {'开' if args.thinking else '关'} | 流式: {'开' if args.stream else '关'}")
        print("-" * 60)

        while True:
            try:
                user_input = input("\n👤 你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 再见！")
                break

            if not user_input:
                continue
            if user_input == "/quit":
                print("👋 再见！")
                break
            if user_input == "/reset":
                client.reset_history()
                print("🔄 对话历史已重置")
                continue
            if user_input.startswith("/system "):
                client.history.system_prompt = user_input[8:]
                print("📝 System prompt 已更新")
                continue
            if user_input == "/history":
                for i, turn in enumerate(client.history.turns, 1):
                    print(f"\n--- 第 {i} 轮 ---")
                    print(f"User: {turn.request_messages[-1]['content'][:100]}...")
                    print(f"Assistant: {turn.response_content[:100]}...")
                continue

            print("\n🤖 助手: ", end="")
            response = client.chat(user_input, stream=args.stream, json_mode=args.json)
            if not args.stream:
                print(response)


if __name__ == "__main__":
    main()
