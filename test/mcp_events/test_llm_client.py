"""测试 DeepSeekLLMClient：真实 API 调用，不 mock。

测试链路：DeepSeekLLMClient → DeepSeek API → json_object 响应 → JSON 解析。
前置条件：.ai_env 有 DEEPSEEK_API_KEY。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))


def _load_ai_env():
    """读取 .ai_env 到 os.environ。"""
    ai_env = Path(__file__).resolve().parents[2] / ".opencode" / ".ai_env"
    if not ai_env.is_file():
        return
    for line in ai_env.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_ai_env()


class TestDeepSeekLLMClientCreation:
    """测试 DeepSeekLLMClient 创建和接口。"""

    def test_importable(self):
        from llm_client import DeepSeekLLMClient
        assert DeepSeekLLMClient is not None

    def test_inherits_llm_client(self):
        from graphiti_core.llm_client.client import LLMClient
        from llm_client import DeepSeekLLMClient
        assert issubclass(DeepSeekLLMClient, LLMClient)

    def test_generate_response_is_async(self):
        import inspect
        from llm_client import DeepSeekLLMClient
        assert inspect.iscoroutinefunction(DeepSeekLLMClient._generate_response)

    def test_creation_with_config(self):
        from graphiti_core.llm_client.config import LLMConfig
        from llm_client import DeepSeekLLMClient

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        config = LLMConfig(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)
        assert client.model == "deepseek-v4-pro"
        assert client.small_model == "deepseek-v4-flash"
        assert client.client is not None


class TestModelSelection:
    """测试 model_size → 模型名映射。"""

    def test_medium_uses_model(self):
        from graphiti_core.llm_client.config import LLMConfig, ModelSize
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key="fake",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            small_model="deepseek-v4-flash",
        )
        client = DeepSeekLLMClient(config=config)
        assert client._get_model_for_size(ModelSize.medium) == "deepseek-v4-pro"

    def test_small_uses_small_model(self):
        from graphiti_core.llm_client.config import LLMConfig, ModelSize
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key="fake",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            small_model="deepseek-v4-flash",
        )
        client = DeepSeekLLMClient(config=config)
        assert client._get_model_for_size(ModelSize.small) == "deepseek-v4-flash"

    def test_fallback_when_model_not_set(self):
        """config 不设 model 时 client 属性可访问。"""
        from graphiti_core.llm_client.config import LLMConfig
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(api_key="fake", base_url="https://api.deepseek.com")
        client = DeepSeekLLMClient(config=config)
        # BaseOpenAIClient 从 config 读取 model/small_model（None 时使用默认值）
        # 只要属性存在且可访问即可
        assert hasattr(client, "model")
        assert hasattr(client, "small_model")


class TestMessageConversion:
    """测试消息格式转换。"""

    def test_convert_messages(self):
        """graphiti Message 列表应转为 OpenAI 格式。"""
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.prompts.models import Message
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(api_key="fake", base_url="https://api.deepseek.com")
        client = DeepSeekLLMClient(config=config)

        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Extract entities."),
        ]
        # BaseOpenAIClient._convert_messages_to_openai_format
        result = client._convert_messages_to_openai_format(messages)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"


class TestRealAPICall:
    """真实 DeepSeek API 调用测试（消耗少量 token）。"""

    def test_generate_response_returns_dict(self):
        """generate_response 应返回解析后的 JSON dict。"""
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.prompts.models import Message
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)

        messages = [
            Message(
                role="system",
                content="Extract entities and return as JSON.",
            ),
            Message(
                role="user",
                content=(
                    "Extract entities from: 'Frida hooked verify_license at 0x4012A0.'\n\n"
                    'Respond with a JSON object in the following format:\n\n'
                    '{"extracted_entities": [{"name": "str", "entity_type_id": 0}]}'
                ),
            ),
        ]

        result = asyncio.run(client.generate_response(messages=messages, response_model=None, max_tokens=500))

        assert isinstance(result, dict), f"期望 dict，实际 {type(result)}: {result}"

    def test_thinking_disabled(self):
        """验证思考模式关闭——响应不应有 reasoning_content。"""
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from openai import AsyncOpenAI

        async def call():
            client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = await client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": 'Return {"ok": true} as JSON.'}],
                temperature=0,
                max_tokens=100,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            return response

        response = asyncio.run(call())
        msg = response.choices[0].message
        assert msg.content is not None
        parsed = json.loads(msg.content)
        assert isinstance(parsed, dict)
        # thinking disabled → reasoning_content 应该为 None 或不存在
        reasoning = getattr(msg, "reasoning_content", None)
        assert reasoning is None or reasoning == "", f"思考模式未关闭，reasoning_content={reasoning[:100]}"
