#!/usr/bin/env python3
"""
LLM 应用模拟器

通用的 LLM 应用行为模拟器，用于本地测试提示注入 payload。
通过 LLMClient 调用任意 OpenAI 兼容 API，模拟目标 LLM 应用的行为。

核心能力：
- 接收任意 system prompt + user input，调用 LLM，返回结构化结果
- 支持单轮/多轮/批量查询
- 从 LLM 输出中自动提取结构化信息（分数、等级等）

用法:
    # 作为模块
    from llm_sim import LLMSimulator
    sim = LLMSimulator(system_prompt="你是一个评分助手")
    result = sim.query("论文文本...")
    print(result.content)
    print(result.extracted_data)

    # 自定义 LLM 配置
    sim = LLMSimulator(
        system_prompt="你是一个评分助手",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
    )

    # 命令行
    python llm_sim.py --system-prompt "你是一个助手" --input "你好"
    python llm_sim.py --system-prompt "评分标准..." --input-file essay.txt
    python llm_sim.py --system-prompt "评分标准..." --input-file essay.docx
"""

import json
import re
import sys
import time
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from deepseek_client import LLMClient


# ============================================================
# 数据类
# ============================================================

@dataclass
class QueryResult:
    """查询结果"""
    raw_response: str
    reasoning: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    model: str = ""
    finish_reason: str = ""
    elapsed_seconds: float = 0.0
    extracted_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 响应解析器
# ============================================================

class ResponseParser:
    """
    从 LLM 输出中提取结构化信息

    支持提取的通用字段：
    - grade: 字母等级（A-F，含 +/-）
    - score: 数值分数（0-100 或 0-10 等格式）
    - 其他自定义字段通过 extract_patterns 方法添加
    """

    # 通用分数提取模式（从严格到宽松）
    SCORE_PATTERNS = [
        r'(?:##?\s*)?[Ss]core[:\s]*(\d{1,3})\s*/\s*100',
        r'(?:##?\s*)?[Ss]core[:\s]*(\d{1,3})',
        r'(\d{1,3})\s*/\s*100',
        r'[Ss]core[:\s]*(\d{1,3}(?:\.\d+)?)',
    ]

    # 通用等级提取模式
    GRADE_PATTERNS = [
        r'(?:##?\s*)?[Gg]rade[:\s]*\**\s*([A-F][\+\-]?)\s*\**',
        r'(?:##?\s*)?Final\s+[Gg]rade[:\s]*\**\s*([A-F])\s*\**',
        r'([A-F][\+\-]?)\s*[\(\s]*\d{1,3}\s*/\s*100',
        r'[Ll]etter\s+[Gg]rade[:\s]*([A-F])',
    ]

    @classmethod
    def extract(cls, text: str) -> Dict[str, Any]:
        """从文本中提取结构化信息"""
        result = {}

        # 提取分数
        for pat in cls.SCORE_PATTERNS:
            m = re.search(pat, text)
            if m:
                try:
                    result["score"] = int(float(m.group(1)))
                except ValueError:
                    pass
                break

        # 提取等级
        for pat in cls.GRADE_PATTERNS:
            m = re.search(pat, text)
            if m:
                result["grade"] = m.group(1).upper()[0]
                break

        return result

    @classmethod
    def extract_patterns(cls, text: str, patterns: Dict[str, str]) -> Dict[str, Any]:
        """
        使用自定义正则模式提取信息

        Args:
            text: 要解析的文本
            patterns: {字段名: 正则表达式} 字典

        Returns:
            {字段名: 匹配值} 字典
        """
        result = {}
        for name, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                result[name] = m.group(1) if m.groups() else m.group(0)
        return result


# ============================================================
# LLM 模拟器
# ============================================================

class LLMSimulator:
    """
    通用 LLM 应用模拟器

    用途：
    - 本地测试提示注入 payload（无需访问实际目标系统）
    - 稳定性测试（同一 payload 多次提交）
    - 跨场景测试（同一 payload 不同 system prompt）
    - 渐进式攻击实验
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        thinking_enabled: bool = False,
        output_dir: Optional[Path] = None,
    ):
        """
        Args:
            system_prompt: 目标应用的 system prompt（推断或已知的）
            api_key: LLM API Key
            base_url: LLM API base URL
            model: 模型名称
            thinking_enabled: 是否开启思考模式
            output_dir: 查询结果输出目录
        """
        self.client = LLMClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            thinking_enabled=thinking_enabled,
        )
        self.system_prompt = system_prompt
        self.thinking_enabled = thinking_enabled
        self.output_dir = output_dir

    def query(
        self,
        user_input: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 1.0,
        json_mode: bool = False,
        extract_patterns: Optional[Dict[str, str]] = None,
    ) -> QueryResult:
        """
        单轮查询

        Args:
            user_input: 用户输入（论文文本、prompt 等）
            system_prompt: 临时覆盖 system prompt
            temperature: LLM 温度
            json_mode: 是否启用 JSON 输出模式
            extract_patterns: 自定义提取模式 {字段名: 正则}

        Returns:
            QueryResult 查询结果
        """
        sp = system_prompt or self.system_prompt
        messages = []
        if sp:
            messages.append({"role": "system", "content": sp})
        messages.append({"role": "user", "content": user_input})

        start_time = time.time()
        result = self.client.chat_raw(
            messages,
            temperature=temperature,
            thinking_enabled=self.thinking_enabled,
            json_mode=json_mode,
        )
        elapsed = time.time() - start_time

        qr = self._build_result(result, elapsed, extract_patterns)

        if self.output_dir:
            self._save_result(qr)

        return qr

    def query_multiturn(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 1.0,
        extract_patterns: Optional[Dict[str, str]] = None,
    ) -> QueryResult:
        """
        多轮查询

        传入完整的 messages 列表，用于模拟多轮对话场景。
        如果 messages 中没有 system prompt，自动使用构造时的 system_prompt。

        Args:
            messages: 完整的消息列表
            temperature: LLM 温度
            extract_patterns: 自定义提取模式
        """
        has_system = any(m["role"] == "system" for m in messages)
        if not has_system and self.system_prompt:
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        start_time = time.time()
        result = self.client.chat_raw(
            messages,
            temperature=temperature,
            thinking_enabled=self.thinking_enabled,
        )
        elapsed = time.time() - start_time

        return self._build_result(result, elapsed, extract_patterns)

    def query_batch(
        self,
        inputs: List[str],
        *,
        temperature: float = 1.0,
        extract_patterns: Optional[Dict[str, str]] = None,
    ) -> List[QueryResult]:
        """
        批量查询（用于稳定性测试：同一 payload 多次提交）

        Args:
            inputs: 用户输入列表
            temperature: LLM 温度
            extract_patterns: 自定义提取模式

        Returns:
            QueryResult 列表
        """
        results = []
        for i, user_input in enumerate(inputs):
            qr = self.query(
                user_input,
                temperature=temperature,
                extract_patterns=extract_patterns,
            )
            results.append(qr)
            if i < len(inputs) - 1:
                time.sleep(1)  # 避免速率限制
        return results

    def _save_result(self, result: QueryResult):
        """保存查询结果"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"query_{int(time.time())}.json"
        path = self.output_dir / filename
        path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_result(
        self,
        raw: Dict[str, Any],
        elapsed: float,
        extract_patterns: Optional[Dict[str, str]] = None,
    ) -> QueryResult:
        """从 API 响应构造 QueryResult（提取结构化信息）"""
        extracted = ResponseParser.extract(raw["content"])
        if extract_patterns:
            extracted.update(ResponseParser.extract_patterns(raw["content"], extract_patterns))
        return QueryResult(
            raw_response=raw["content"],
            reasoning=raw.get("reasoning_content"),
            usage=raw.get("usage"),
            model=raw.get("model", ""),
            finish_reason=raw.get("finish_reason", ""),
            elapsed_seconds=round(elapsed, 2),
            extracted_data=extracted,
        )


# ============================================================
# 工具函数
# ============================================================

def read_docx(path: str) -> str:
    """读取 .docx 文件内容"""
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_input_file(path: str) -> str:
    """读取输入文件（支持 .txt / .md / .docx）"""
    p = Path(path)
    if p.suffix == ".docx":
        return read_docx(path)
    return p.read_text(encoding="utf-8")


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="LLM 应用模拟器")
    parser.add_argument("--system-prompt", required=True, help="System prompt")
    parser.add_argument("--input", help="直接传入输入文本")
    parser.add_argument("--input-file", help="输入文件路径（.txt/.md/.docx）")
    parser.add_argument("--api-key", help="LLM API Key")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="API base URL")
    parser.add_argument("--model", default="deepseek-chat", help="模型名称")
    parser.add_argument("--thinking", action="store_true", help="启用思考模式")
    parser.add_argument("--temperature", "-t", type=float, default=1.0)
    parser.add_argument("--output-dir", help="结果输出目录")

    args = parser.parse_args()

    # 获取输入
    if args.input_file:
        user_input = read_input_file(args.input_file)
        print(f"📄 已加载输入文件: {args.input_file} ({len(user_input)} 字符)")
    elif args.input:
        user_input = args.input
    else:
        print("❌ 请提供 --input 或 --input-file 参数")
        sys.exit(1)

    # 创建模拟器
    sim = LLMSimulator(
        system_prompt=args.system_prompt,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        thinking_enabled=args.thinking,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )

    # 查询
    print("\n🔍 正在查询...\n")
    result = sim.query(user_input, temperature=args.temperature)

    # 输出结果
    print("=" * 60)
    if result.reasoning:
        print(f"💭 思考过程:\n{result.reasoning[:500]}...\n")
    print(f"📝 完整回复:\n{result.raw_response}")
    if result.extracted_data:
        print(f"\n📊 提取数据: {result.extracted_data}")
    print(f"\n⏱ 耗时: {result.elapsed_seconds}s")
    if result.usage:
        print(f"Token 用量: {result.usage}")
    print("=" * 60)


if __name__ == "__main__":
    main()
