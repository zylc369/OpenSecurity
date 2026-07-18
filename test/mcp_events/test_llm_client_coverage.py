"""DeepSeekLLMClient 补充单元测试——覆盖 review 发现的未测分支。

零 API 成本，全部用 mock/SimpleNamespace 测试。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))

from llm_client import DeepSeekLLMClient


# ─── _prop_to_example 完整分支覆盖 ───


class TestPropToExampleBranches:
    """覆盖 _prop_to_example 的所有类型分支。"""

    def test_ref_not_in_defs(self):
        """$ref 指向的 def 不存在 → 返回 {}。"""
        result = DeepSeekLLMClient._prop_to_example({"$ref": "#/$defs/NonExistent"}, {})
        assert result == {}

    def test_oneOf_branch(self):
        """oneOf（非 anyOf）应正确解析。"""
        prop = {"oneOf": [{"type": "string"}, {"type": "null"}]}
        result = DeepSeekLLMClient._prop_to_example(prop, {})
        assert result == ""

    def test_oneOf_all_null(self):
        """anyOf/oneOf 全是 null → 返回 None。"""
        prop = {"anyOf": [{"type": "null"}]}
        result = DeepSeekLLMClient._prop_to_example(prop, {})
        assert result is None

    def test_allOf_branch(self):
        """allOf 应合并多个 subschema 的属性。"""
        prop = {
            "allOf": [
                {"properties": {"a": {"type": "string"}}},
                {"properties": {"b": {"type": "integer"}}},
            ]
        }
        result = DeepSeekLLMClient._prop_to_example(prop, {})
        assert result == {"a": "", "b": 0}

    def test_allOf_with_ref(self):
        """allOf 含 $ref 应解引用并合并。"""
        defs = {"Base": {"type": "object", "properties": {"id": {"type": "integer"}}}}
        prop = {
            "allOf": [
                {"$ref": "#/$defs/Base"},
                {"properties": {"name": {"type": "string"}}},
            ]
        }
        result = DeepSeekLLMClient._prop_to_example(prop, defs)
        assert result == {"id": 0, "name": ""}

    def test_boolean_type(self):
        result = DeepSeekLLMClient._prop_to_example({"type": "boolean"}, {})
        assert result is False

    def test_number_type(self):
        result = DeepSeekLLMClient._prop_to_example({"type": "number"}, {})
        assert result == 0

    def test_unknown_type_returns_none(self):
        result = DeepSeekLLMClient._prop_to_example({"type": "custom_type"}, {})
        assert result is None

    def test_no_type_returns_none(self):
        result = DeepSeekLLMClient._prop_to_example({}, {})
        assert result is None

    def test_nested_object_preserves_defs(self):
        """BUG 修复：嵌套 object 递归不应丢失 defs。"""
        defs = {"Inner": {"type": "object", "properties": {"value": {"type": "string"}}}}
        prop = {
            "type": "object",
            "properties": {
                "inner": {"$ref": "#/$defs/Inner"},
            },
        }
        result = DeepSeekLLMClient._prop_to_example(prop, defs)
        assert result == {"inner": {"value": ""}}, f"嵌套 $ref 应保留 defs，实际: {result}"


# ─── _simplify_schema_in_messages 边界 ───


class TestSimplifySchemaEdgeCases:
    """覆盖 _simplify_schema_in_messages 的边界条件。"""

    def test_empty_messages_noop(self):
        """空 messages 列表不崩溃。"""
        DeepSeekLLMClient._simplify_schema_in_messages([], BaseModel)

    def test_missing_content_key(self):
        """message 没有 content 键不崩溃。"""
        messages = [{"role": "user"}]
        DeepSeekLLMClient._simplify_schema_in_messages(messages, BaseModel)
        # 不崩溃即可

    def test_exception_swallowed_silently(self):
        """model_json_schema 抛异常时静默跳过（不修改消息）。"""
        class BrokenModel:
            @classmethod
            def model_json_schema(cls):
                raise RuntimeError("broken")

        messages = [{"role": "user", "content": "Original content.\n\nRespond with a JSON object in the following format:\n\n{}"}]
        original = messages[0]["content"]
        DeepSeekLLMClient._simplify_schema_in_messages(messages, BrokenModel)
        # 异常被吞，消息不变
        assert messages[0]["content"] == original


# ─── _handle_structured_response 错误路径 ───


class TestStructuredResponseErrorPaths:
    """覆盖 _handle_structured_response 的错误路径。"""

    def test_invalid_json_raises(self):
        """content 不是合法 JSON → 抛 JSONDecodeError。"""
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json {"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
        with pytest.raises(json.JSONDecodeError):
            client._handle_structured_response(response)

    def test_missing_usage_attribute(self):
        """response 没有 usage 属性 → token 计数为 0。"""
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
        )
        client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
        result, input_t, output_t = client._handle_structured_response(response)
        assert result == {"ok": True}
        assert input_t == 0
        assert output_t == 0


# ─── _coerce_field_names 补充分支 ───


class TestCoerceFieldNamesEdgeCases:
    """覆盖 _coerce_field_names 的未测分支。"""

    def test_edge_prefix_strip(self):
        """edge_ 前缀正向映射。"""
        class EdgeModel(BaseModel):
            edge_summary: str

        data = {"summary": "test"}
        result = DeepSeekLLMClient._coerce_field_names(data, EdgeModel)
        assert "edge_summary" in result

    def test_extracted_prefix_reverse(self):
        """extracted_ 前缀反向映射。"""
        class MyModel(BaseModel):
            count: int

        data = {"extracted_count": 5}
        result = DeepSeekLLMClient._coerce_field_names(data, MyModel)
        assert result.get("count") == 5

    def test_nested_non_basemodel_list(self):
        """列表元素不是 BaseModel 时不递归（避免崩溃）。"""
        class MyModel(BaseModel):
            values: list[str]

        data = {"values": ["a", "b"]}
        result = DeepSeekLLMClient._coerce_field_names(data, MyModel)
        assert result["values"] == ["a", "b"]


# ─── BgeM3Embedder.create 预计算向量分支 ───


class TestBgeM3EmbedderPrecomputedVector:
    """覆盖 BgeM3Embedder.create 的预计算向量输入分支。"""

    def test_precomputed_int_vector(self):
        """传入整数列表（预计算向量）应原样返回。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        import asyncio
        result = asyncio.run(emb.create([1.0, 2.0, 3.0]))
        assert result == [1.0, 2.0, 3.0]

    def test_empty_list_input(self):
        """空列表不崩溃。"""
        from graphiti_config import BgeM3Embedder
        emb = BgeM3Embedder()
        import asyncio
        result = asyncio.run(emb.create([]))
        assert result == []
