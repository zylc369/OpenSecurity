"""DeepSeek LLM 客户端 — 通过 DeepSeek Anthropic API 调用 LLM。

使用 Anthropic 的 tool use 机制实现结构化输出：
  - tool_choice={"type": "tool"} 强制模型按 input_schema 输出
  - 服务端约束字段名和结构，无需应用层补丁

DeepSeek 的 Anthropic API 端点：https://api.deepseek.com/anthropic
兼容性：支持 input_schema / tool_choice / thinking=disabled
"""
import json
import logging
import typing

from anthropic import AsyncAnthropic
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DeepSeekLLMClient(AnthropicClient):
    """通过 DeepSeek Anthropic API 调用 LLM。

    继承 graphiti 原生 AnthropicClient，复用其 tool use 结构化输出机制。
    唯一改动：注入 thinking={"type": "disabled"}（DeepSeek 默认启用思考模式，
    与 tool_choice 不兼容）。
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        if config is None:
            config = LLMConfig()

        # 创建指向 DeepSeek Anthropic 端点的 AsyncAnthropic 客户端
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=1,
        )

        super().__init__(config=config, client=client, max_tokens=max_tokens)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> tuple[dict[str, typing.Any], int, int]:
        """调用 DeepSeek Anthropic API。

        和父类 AnthropicClient._generate_response 的区别：
        1. 注入 thinking={"type": "disabled"}（DeepSeek 默认启用思考模式，与 tool_choice 不兼容）
        2. max_tokens 不走 _resolve_max_tokens（DeepSeek 模型不在 Anthropic 的已知模型列表里，
           _resolve_max_tokens 会截断到 8192，这里直接用传入值）

        不在此方法里记录 token（父类 generate_response 统一记录，避免重复计数）。
        """
        import anthropic

        system_message = messages[0]
        user_messages: list[dict[str, str]] = [
            {"role": m.role, "content": m.content} for m in messages[1:]
        ]

        tools, tool_choice = self._create_tool(response_model)

        try:
            result = await self.client.messages.create(
                system=system_message.content,
                max_tokens=max_tokens,
                temperature=self.temperature,
                messages=user_messages,
                model=self.model,
                tools=tools,
                tool_choice=tool_choice,
                thinking={"type": "disabled"},
            )
        except anthropic.RateLimitError as e:
            raise RateLimitError(f"Rate limit exceeded: {e}") from e
        except anthropic.APIError as e:
            if "refused to respond" in str(e).lower():
                raise RefusalError(str(e)) from e
            raise

        input_tokens = getattr(result.usage, "input_tokens", 0) if result.usage else 0
        output_tokens = getattr(result.usage, "output_tokens", 0) if result.usage else 0

        # 从 tool_use 响应提取结构化数据
        for content_item in result.content:
            if content_item.type == "tool_use":
                if isinstance(content_item.input, dict):
                    return content_item.input, input_tokens, output_tokens
                return json.loads(str(content_item.input)), input_tokens, output_tokens

        # 降级：从文本提取 JSON
        for content_item in result.content:
            if content_item.type == "text":
                try:
                    return json.loads(content_item.text), input_tokens, output_tokens
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"No structured response from model: {result.content}")
