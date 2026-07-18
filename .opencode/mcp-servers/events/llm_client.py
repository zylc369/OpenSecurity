"""DeepSeek LLM 客户端 — 通过 DeepSeek API 调用 LLM。

继承 BaseOpenAIClient（而非 LLMClient），复用其验证错误重试逻辑：
当 LLM 返回的 JSON 字段名与 Pydantic model 不匹配时，BaseOpenAIClient 会追加
错误上下文并重试，让 LLM 自我纠正。

DeepSeek 不支持 OpenAI Responses API，因此重写：
- _create_completion / _create_structured_completion → 统一用 chat.completions.create
- _handle_structured_response → 处理 ChatCompletion 响应（而非 Responses API 的 output_text）
"""
import json
import logging
import typing

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig
from graphiti_core.llm_client.openai_base_client import BaseOpenAIClient

logger = logging.getLogger(__name__)


class DeepSeekLLMClient(BaseOpenAIClient):
    """通过 DeepSeek API 调用 LLM（继承 BaseOpenAIClient 的验证重试逻辑）。"""

    def __init__(
        self,
        config: LLMConfig | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        if config is None:
            config = LLMConfig()
        super().__init__(config, cache=False, max_tokens=max_tokens)

        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def _create_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel] | None = None,
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        """DeepSeek chat completion（json_object 模式 + thinking disabled）。"""
        # DeepSeek json_object 要求 prompt 含 "json"——确保满足
        msgs = list(messages)
        if not any("json" in str(m.get("content", "")).lower() for m in msgs):
            msgs[-1]["content"] = str(msgs[-1].get("content", "")) + "\n\nRespond in JSON format."

        request_kwargs: dict[str, typing.Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if temperature is not None:
            request_kwargs["temperature"] = temperature

        return await self.client.chat.completions.create(**request_kwargs)

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        """DeepSeek 不支持 Responses API → 统一走 chat completion。

        额外处理：graphiti prompt 的自然语言描述（如 "entities"）与 Pydantic model
        的字段名（如 "extracted_entities"）可能不一致。DeepSeek 会跟随 prompt 文本
        而非 schema 字段名。解决：把消息末尾的原始 JSON Schema 替换为简化版字段示例，
        用 Pydantic model 的真实字段名，强制 LLM 遵循。
        """
        self._simplify_schema_in_messages(messages, response_model)

        return await self._create_completion(
            model, messages, temperature, max_tokens, response_model,
        )

    @staticmethod
    def _simplify_schema_in_messages(
        messages: list[ChatCompletionMessageParam], response_model: type[BaseModel]
    ) -> None:
        """把 graphiti 注入的原始 JSON Schema 替换为简化版字段名示例。

        graphiti 基类在消息末尾追加 "Respond with a JSON object in the following format: {raw_schema}"。
        原始 schema 含 type/properties/anyOf/$defs/title 等元数据，DeepSeek 会回显。
        替换为只含字段名 + 类型默认值的简化示例，用 model 真实字段名。
        """
        if not messages:
            return

        content = str(messages[-1].get("content", ""))
        marker = "Respond with a JSON object in the following format:"
        idx = content.find(marker)
        if idx == -1:
            return

        try:
            schema = response_model.model_json_schema()
            example = DeepSeekLLMClient._schema_to_example(schema)
            example_str = json.dumps(example, indent=2, ensure_ascii=False)
        except Exception:
            return

        messages[-1]["content"] = (
            content[:idx]
            + "Respond with a JSON object in the following format "
            + "(use these EXACT field names, replace default values with actual data):\n\n"
            + example_str
        )

    @staticmethod
    def _schema_to_example(schema: dict, defs: dict | None = None) -> typing.Any:
        """递归把 JSON Schema 转为带默认值的 JSON 示例。"""
        if defs is None:
            defs = schema.get("$defs", schema.get("definitions", {}))
        if schema.get("type") == "object" or "properties" in schema:
            result: dict[str, typing.Any] = {}
            for key, prop in schema.get("properties", {}).items():
                result[key] = DeepSeekLLMClient._prop_to_example(prop, defs)
            return result
        return DeepSeekLLMClient._prop_to_example(schema, defs)

    @staticmethod
    def _prop_to_example(prop: dict, defs: dict) -> typing.Any:
        """把单个 JSON Schema 属性转为示例值。"""
        if "$ref" in prop:
            ref_name = prop["$ref"].split("/")[-1]
            if ref_name in defs:
                return DeepSeekLLMClient._schema_to_example(defs[ref_name])
            return {}

        if "anyOf" in prop or "oneOf" in prop:
            options = prop.get("anyOf") or prop.get("oneOf")
            for opt in options:
                if opt.get("type") != "null":
                    return DeepSeekLLMClient._prop_to_example(opt, defs)
            return None

        type_ = prop.get("type")

        if "allOf" in prop:
            merged = {}
            for sub in prop["allOf"]:
                if "$ref" in sub:
                    ref_name = sub["$ref"].split("/")[-1]
                    if ref_name in defs:
                        merged.update(DeepSeekLLMClient._schema_to_example(defs[ref_name]))
                elif "properties" in sub:
                    for k, v in sub["properties"].items():
                        merged[k] = DeepSeekLLMClient._prop_to_example(v, defs)
            return merged

        if type_ == "array":
            return []
        elif type_ == "string":
            return ""
        elif type_ == "object":
            return DeepSeekLLMClient._schema_to_example(prop, defs)
        elif type_ in ("number", "integer"):
            return 0
        elif type_ == "boolean":
            return False
        return None

    def _handle_structured_response(self, response: typing.Any) -> tuple[dict[str, typing.Any], int, int]:
        """重写：处理 ChatCompletion 响应（而非 Responses API 的 output_text）。"""
        result = response.choices[0].message.content or "{}"

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage") and response.usage:
            input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

        return json.loads(result), input_tokens, output_tokens

    async def _generate_response(
        self,
        messages: list,
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: typing.Any = None,
    ) -> tuple[dict[str, typing.Any], int, int]:
        """重写：调用 BaseOpenAIClient 后修复字段名不匹配。

        graphiti 的 prompt 文本使用的字段名（如 "entities"）有时与 Pydantic model
        的字段名（如 "extracted_entities"）不一致。BaseOpenAIClient 的重试机制能捕获
        部分错误，但 DeepSeek 可能反复犯同一错误。此方法在返回前做字段名映射。
        """
        result, input_tokens, output_tokens = await super()._generate_response(
            messages, response_model, max_tokens, model_size
        )

        if response_model is not None and isinstance(result, dict):
            result = self._coerce_field_names(result, response_model)
        elif response_model is not None and isinstance(result, list):
            # LLM 返回裸 list 而非 {"field": [...]} → 包装到唯一的 list 字段
            import typing as t
            for fname, finfo in response_model.model_fields.items():
                ann = getattr(finfo, "annotation", None)
                if hasattr(ann, "__origin__") and ann.__origin__ is list:
                    result = {fname: result}
                    logger.debug(f"裸 list 包装到字段: {fname}")
                    break

        return result, input_tokens, output_tokens

    @staticmethod
    def _coerce_field_names(
        data: dict[str, typing.Any], model_class: type[BaseModel]
    ) -> dict[str, typing.Any]:
        """修复 graphiti prompt 字段名与 Pydantic model 字段名的不一致。

        策略：对 model 的每个必需字段，如果 data 中缺失，尝试从已知同义名映射。
        常见模式：extracted_entities ↔ entities, entity_name ↔ name。
        """
        model_fields = model_class.model_fields

        for field_name in model_fields:
            if field_name in data:
                continue

            # 生成候选同义名列表
            candidates: list[str] = []
            # 常见前缀：extracted_ / entity_ / edge_
            for prefix in ("extracted_", "entity_", "edge_"):
                if field_name.startswith(prefix):
                    candidates.append(field_name[len(prefix):])
            # graphiti 里 edge 和 fact 互用
            if field_name in ("edges", "extracted_edges"):
                candidates.extend(["facts", "edges", "extracted_edges"])
            # 去掉复数/单数
            candidates.append(field_name.rstrip("s"))
            candidates.append(field_name + "s")

            for candidate in candidates:
                if candidate in data:
                    data[field_name] = data.pop(candidate)
                    logger.debug(f"字段名映射: {candidate} → {field_name}")
                    break

        # 反向映射：data 里的 entity_name / extracted_X → model 的 X
        model_field_names = set(model_fields.keys())
        for data_key in list(data.keys()):
            if data_key in model_field_names:
                continue
            for prefix in ("entity_", "extracted_", "edge_"):
                if data_key.startswith(prefix):
                    stripped = data_key[len(prefix):]
                    if stripped in model_field_names:
                        data[stripped] = data.pop(data_key)
                        logger.debug(f"反向字段名映射: {data_key} → {stripped}")
                        break

        # 递归修复嵌套 dict 里的字段名（如 extracted_entities 列表里的 entity_name → name）
        for field_name, field_info in model_fields.items():
            if field_name in data:
                inner_type = getattr(field_info, "annotation", None)
                if hasattr(inner_type, "__origin__") and inner_type.__origin__ is list:
                    args = typing.get_args(inner_type)
                    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                        items = data[field_name]
                        if isinstance(items, list):
                            data[field_name] = [
                                DeepSeekLLMClient._coerce_field_names(item, args[0])
                                if isinstance(item, dict) else item
                                for item in items
                            ]

        return data

