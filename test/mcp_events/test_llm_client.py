"""DeepSeekLLMClient 单元测试 + 真实 API 测试。

DeepSeekLLMClient 现在继承 AnthropicClient（不再继承 BaseOpenAIClient），
通过 tool use 实现服务端强制结构化输出。测试覆盖：
  - 继承关系和接口
  - thinking=disabled 注入
  - 真实 API 结构化输出正确性
"""
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))

# 加载 .ai_env（不存在时跳过，不崩 import）
_ai_env = Path(__file__).resolve().parents[2] / ".opencode" / ".ai_env"
if _ai_env.is_file():
    for line in _ai_env.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


class TestDeepSeekLLMClientCreation:
    """测试 DeepSeekLLMClient 创建和继承。"""

    def test_importable(self):
        from llm_client import DeepSeekLLMClient
        assert DeepSeekLLMClient is not None

    def test_inherits_anthropic_client(self):
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from llm_client import DeepSeekLLMClient
        assert issubclass(DeepSeekLLMClient, AnthropicClient)

    def test_generate_response_is_async(self):
        from llm_client import DeepSeekLLMClient
        assert inspect.iscoroutinefunction(DeepSeekLLMClient._generate_response)

    def test_creation_with_config(self):
        from graphiti_core.llm_client.config import LLMConfig
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key="fake-key",
            base_url="https://api.deepseek.com/anthropic",
            model="deepseek-v4-pro",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)
        assert client.model == "deepseek-v4-pro"
        assert client.client is not None


class TestThinkingDisabled:
    """验证 _generate_response 注入 thinking=disabled。"""

    def test_thinking_disabled_in_source(self):
        """源码里应该有 thinking disabled。"""
        from llm_client import DeepSeekLLMClient
        src = inspect.getsource(DeepSeekLLMClient._generate_response)
        assert 'thinking' in src, "_generate_response 应包含 thinking 参数"
        assert 'disabled' in src, "thinking 应设为 disabled"


class TestRealAPIStructuredOutput:
    """真实 DeepSeek Anthropic API 调用——验证 tool use 强制结构化输出。

    这是关键测试：如果 tool use 正常工作，字段名和结构必须 100% 正确。
    无需 _coerce_field_names / _coerce_structure 等补丁。
    """

    def test_extracted_entities_field_names_correct(self):
        """ExtractedEntities 的字段名必须正确（tool use 强制）。"""
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.prompts.models import Message
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key=api_key,
            base_url="https://api.deepseek.com/anthropic",
            model="deepseek-v4-flash",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)

        from graphiti_core.prompts.extract_nodes import ExtractedEntities

        messages = [
            Message(role="system", content="You are an entity extractor."),
            Message(
                role="user",
                content=(
                    "Extract entities from: 'binary-analysis agent used Ghidra to analyze sample.exe.'\n\n"
                    "Respond with a JSON object in the following format:\n\n"
                    + json.dumps(ExtractedEntities.model_json_schema())
                ),
            ),
        ]

        result, _, _ = asyncio.run(
            client._generate_response(messages, response_model=ExtractedEntities, max_tokens=500)
        )

        # tool use 强制 → 字段名必须正确
        assert "extracted_entities" in result, (
            f"字段名应包含 'extracted_entities'，实际: {list(result.keys())}"
        )
        entities = result["extracted_entities"]
        assert len(entities) > 0, "应该提取到实体"

        # 验证内层字段名也正确
        for entity in entities:
            assert "name" in entity, f"内层字段应有 'name'，实际: {list(entity.keys())}"

    def test_summarized_entities_structure_correct(self):
        """SummarizedEntities 必须是 list[dict]（不是扁平 dict）。"""
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.prompts.models import Message
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key=api_key,
            base_url="https://api.deepseek.com/anthropic",
            model="deepseek-v4-flash",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)

        from graphiti_core.prompts.extract_nodes import SummarizedEntities

        messages = [
            Message(role="system", content="You generate entity summaries."),
            Message(
                role="user",
                content=(
                    "Generate summaries for these entities:\n"
                    "- sample.exe: analyzed binary\n"
                    "- Ghidra: reverse engineering tool\n\n"
                    "Respond with a JSON object in the following format:\n\n"
                    + json.dumps(SummarizedEntities.model_json_schema())
                ),
            ),
        ]

        result, _, _ = asyncio.run(
            client._generate_response(messages, response_model=SummarizedEntities, max_tokens=500)
        )

        # tool use 强制 → 结构必须是 {"summaries": [{"name": str, "summary": str}]}
        assert "summaries" in result, f"字段名应包含 'summaries'，实际: {list(result.keys())}"
        summaries = result["summaries"]
        assert isinstance(summaries, list), f"summaries 应是 list，实际: {type(summaries)}"
        assert len(summaries) > 0, "应生成至少一个摘要"

        for s in summaries:
            assert isinstance(s, dict), f"每个摘要应是 dict，实际: {type(s)}"
            assert "name" in s, f"摘要应有 name 字段，实际: {list(s.keys())}"
            assert "summary" in s, f"摘要应有 summary 字段，实际: {list(s.keys())}"

    def test_no_schema_echo(self):
        """tool use 不应出现 schema 回显（type/properties/$defs 不在输出中）。"""
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.prompts.models import Message
        from llm_client import DeepSeekLLMClient

        config = LLMConfig(
            api_key=api_key,
            base_url="https://api.deepseek.com/anthropic",
            model="deepseek-v4-flash",
            small_model="deepseek-v4-flash",
            temperature=0,
        )
        client = DeepSeekLLMClient(config=config)

        from graphiti_core.prompts.extract_nodes import ExtractedEntities

        messages = [
            Message(role="system", content="You are an entity extractor."),
            Message(
                role="user",
                content="Extract entities from: 'Frida hooked verify_license function.'",
            ),
        ]

        result, _, _ = asyncio.run(
            client._generate_response(messages, response_model=ExtractedEntities, max_tokens=500)
        )

        result_str = json.dumps(result)
        assert '"type": "object"' not in result_str, "出现 schema 回显（type: object）"
        assert '"properties"' not in result_str, "出现 schema 回显（properties）"
        assert '"$defs"' not in result_str, "出现 schema 回显（$defs）"
