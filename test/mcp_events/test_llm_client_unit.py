"""DeepSeekLLMClient 单元测试——直接测 6 个 BUG 修复逻辑，零 API 调用。

这 6 个 BUG 在写测试用例时没发现（用了简单数据碰巧没触发），在 compare_models.py
用复杂数据时全部爆发。这些单元测试确保修复逻辑正确工作。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers" / "events"))

from llm_client import DeepSeekLLMClient


# ─── 测试用的 Pydantic 模型（模拟 graphiti 的真实模型结构）───


class ExtractedEntity(BaseModel):
    name: str
    entity_type_id: int
    episode_indices: list[int] = []


class ExtractedEntities(BaseModel):
    extracted_entities: list[ExtractedEntity]


class EdgeDuplicate(BaseModel):
    duplicate_facts: list[str]
    contradicted_facts: list[str]


class NodeResolutions(BaseModel):
    entity_resolutions: list[dict]


# ─── BUG 1: Schema 回显 — _simplify_schema_in_messages ───


class TestSchemaSimplification:
    """BUG 1: DeepSeek json_object 回显 schema 元数据而非实际数据。"""

    def test_removes_raw_schema_metadata(self):
        """简化后消息不应包含 type/properties/anyOf/$defs 等 schema 元数据。"""
        messages = [{
            "role": "user",
            "content": (
                "Extract entities.\n\n"
                "Respond with a JSON object in the following format:\n\n"
                + json.dumps(ExtractedEntities.model_json_schema())
            ),
        }]
        DeepSeekLLMClient._simplify_schema_in_messages(messages, ExtractedEntities)

        content = messages[0]["content"]
        # 简化后不应有 schema 元数据关键词
        assert '"type": "object"' not in content, "简化后不应含 type: object"
        assert '"properties"' not in content, "简化后不应含 properties"
        assert '"$defs"' not in content, "简化后不应含 $defs"
        assert '"anyOf"' not in content, "简化后不应含 anyOf"

    def test_preserves_field_names_from_model(self):
        """简化后应保留 model 的真实字段名。"""
        messages = [{
            "role": "user",
            "content": "Extract.\n\nRespond with a JSON object in the following format:\n\n{}",
        }]
        DeepSeekLLMClient._simplify_schema_in_messages(messages, ExtractedEntities)

        content = messages[0]["content"]
        assert "extracted_entities" in content, "应保留 extracted_entities 字段名"

    def test_no_change_when_marker_absent(self):
        """消息里没有 schema 标记时不修改。"""
        messages = [{"role": "user", "content": "Just a normal message."}]
        original = messages[0]["content"]
        DeepSeekLLMClient._simplify_schema_in_messages(messages, ExtractedEntities)
        assert messages[0]["content"] == original


# ─── BUG 1 补充: _schema_to_example ───


class TestSchemaToExample:
    """_schema_to_example 应生成正确的类型默认值。"""

    def test_string_field(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = DeepSeekLLMClient._schema_to_example(schema)
        assert result == {"name": ""}

    def test_array_field(self):
        schema = {"type": "object", "properties": {"tags": {"type": "array"}}}
        result = DeepSeekLLMClient._schema_to_example(schema)
        assert result == {"tags": []}

    def test_integer_field(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = DeepSeekLLMClient._schema_to_example(schema)
        assert result == {"count": 0}

    def test_nested_ref(self):
        """$ref 应递归解析为嵌套示例。"""
        schema = {
            "$defs": {
                "Item": {"type": "object", "properties": {"id": {"type": "integer"}}}
            },
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Item"},
                }
            },
        }
        result = DeepSeekLLMClient._schema_to_example(schema)
        assert result == {"items": []}

    def test_anyOf_optional(self):
        """anyOf 含 null 的 Optional 字段应取第一个非 null 类型。"""
        schema = {
            "properties": {
                "value": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                }
            }
        }
        result = DeepSeekLLMClient._schema_to_example(schema)
        assert result == {"value": ""}


# ─── BUG 2: 字段名不匹配 — _coerce_field_names ───


class TestCoerceFieldNames:
    """BUG 2: graphiti prompt 用 entities/entity_name，model 用 extracted_entities/name。"""

    def test_forward_mapping_strips_prefix(self):
        """model 字段 extracted_entities 缺失 → 从 data 的 entities 映射。"""
        data = {"entities": [{"name": "foo", "entity_type_id": 0}]}
        result = DeepSeekLLMClient._coerce_field_names(data, ExtractedEntities)
        assert "extracted_entities" in result
        assert "entities" not in result

    def test_reverse_mapping_strips_prefix(self):
        """data 里 entity_resolutions → model 的 entity_resolutions（直接匹配则不变）。

        测试反向：data 里有 entity_name → model 字段 name。"""
        data = {"entity_name": "test", "entity_type_id": 0, "episode_indices": []}
        result = DeepSeekLLMClient._coerce_field_names(data, ExtractedEntity)
        assert "name" in result
        assert result["name"] == "test"
        assert "entity_name" not in result

    def test_nested_recursion(self):
        """嵌套列表里的 dict 字段名也要修复。"""
        data = {
            "extracted_entities": [
                {"entity_name": "foo", "entity_type_id": 0, "episode_indices": []},
                {"entity_name": "bar", "entity_type_id": 1, "episode_indices": []},
            ]
        }
        result = DeepSeekLLMClient._coerce_field_names(data, ExtractedEntities)
        entities = result["extracted_entities"]
        assert entities[0]["name"] == "foo"
        assert entities[1]["name"] == "bar"
        assert "entity_name" not in entities[0]

    def test_no_change_when_already_correct(self):
        """字段名已正确时不做任何修改。"""
        data = {
            "extracted_entities": [
                {"name": "foo", "entity_type_id": 0, "episode_indices": []}
            ]
        }
        result = DeepSeekLLMClient._coerce_field_names(data, ExtractedEntities)
        assert result == data

    def test_edge_facts_synonym(self):
        """edges/facts 互为同义词。"""
        data = {"facts": ["fact1"]}
        # 用一个 edges 字段的 model
        class EdgeModel(BaseModel):
            edges: list[str]
        result = DeepSeekLLMClient._coerce_field_names(data, EdgeModel)
        assert "edges" in result
        assert result["edges"] == ["fact1"]


# ─── BUG 4: output_text 属性不存在 — _handle_structured_response ───


class TestStructuredResponseHandling:
    """BUG 4: BaseOpenAIClient 期望 response.output_text，我们返回 ChatCompletion。"""

    def _mock_chat_completion(self, content: str, input_tokens=100, output_tokens=50):
        """构造模拟 ChatCompletion 响应。"""
        usage = SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens)
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=usage)

    def test_parses_json_content(self):
        """从 choices[0].message.content 提取 JSON。"""
        response = self._mock_chat_completion('{"key": "value"}')
        client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
        result, input_t, output_t = client._handle_structured_response(response)
        assert result == {"key": "value"}
        assert input_t == 100
        assert output_t == 50

    def test_handles_empty_content(self):
        """空 content 回退到 {}。"""
        response = self._mock_chat_completion("")
        client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
        result, _, _ = client._handle_structured_response(response)
        assert result == {}

    def test_handles_null_usage(self):
        """usage 为 null 时 token 计数为 0。"""
        message = SimpleNamespace(content='{"ok": true}')
        choice = SimpleNamespace(message=message)
        response = SimpleNamespace(choices=[choice], usage=None)
        client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
        result, input_t, output_t = client._handle_structured_response(response)
        assert input_t == 0
        assert output_t == 0


# ─── BUG 5+6: 集成验证（在 TestRealGraphitiModels 和端到端测试中覆盖）───
# BUG 5（json_object 要求 prompt 含 "json"）和 BUG 6（裸 list 包装）
# 的生产逻辑在 _create_completion 和 _generate_response 中，
# 被 test_llm_client.py 的 TestRealAPICall 和端到端 daemon/mcp_search 测试覆盖。
# 此处不做脱离生产代码的单元测试（避免测试复制的代码）。


# ─── 集成: 用 graphiti 真实 Pydantic 模型测试 schema 简化 ───


class TestRealGraphitiModels:
    """用 graphiti-core 的真实 Pydantic 模型测试 schema 简化。"""

    def test_extracted_entities_schema(self):
        """ExtractedEntities 的 schema 应正确简化。"""
        from graphiti_core.prompts.extract_nodes import ExtractedEntities
        schema = ExtractedEntities.model_json_schema()
        example = DeepSeekLLMClient._schema_to_example(schema)

        assert "extracted_entities" in example
        entities = example["extracted_entities"]
        assert isinstance(entities, list)
        # 空列表是正确的默认值

    def test_node_resolutions_schema(self):
        """NodeResolutions 的 schema 应正确简化（曾出 BUG 的模型）。"""
        from graphiti_core.prompts.dedupe_nodes import NodeResolutions
        schema = NodeResolutions.model_json_schema()
        example = DeepSeekLLMClient._schema_to_example(schema)

        assert "entity_resolutions" in example

    def test_field_coercion_with_real_model(self):
        """用真实 ExtractedEntities 测试字段名映射。"""
        from graphiti_core.prompts.extract_nodes import ExtractedEntities

        # DeepSeek 返回的典型格式（prompt 用了 entities/entity_name）
        data = {
            "entities": [
                {"entity_name": "sample.exe", "entity_type_id": 0, "episode_indices": [0]},
                {"entity_name": "Ghidra", "entity_type_id": 0, "episode_indices": [0]},
            ]
        }

        result = DeepSeekLLMClient._coerce_field_names(data, ExtractedEntities)

        # 验证映射后能通过 Pydantic 验证
        validated = ExtractedEntities(**result)
        assert len(validated.extracted_entities) == 2
        assert validated.extracted_entities[0].name == "sample.exe"
        assert validated.extracted_entities[1].name == "Ghidra"
