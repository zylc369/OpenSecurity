"""文本匿名化（Anonymizer 静态方法类）——存储前清洗敏感信息。

对齐 PentAGI 的 anonymizer.Replacer.ReplaceString()（300+ 正则模式的
核心安全子集，覆盖安全分析场景最常见的敏感信息类型）。
"""
from __future__ import annotations

import re


class Anonymizer:
    """敏感信息 → 占位符（无状态，全静态）。"""

    PATTERNS: list[tuple[str, str]] = [
        # IPv4 地址
        (r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b", "<IP>"),
        # 数据库连接字符串（含密码，必须在邮箱之前匹配）
        (
            r"(?i)(?:postgres|mysql|mongodb|redis)://\w+:[^\s@]+@[^\s]+",
            "<DB_CONNECTION>",
        ),
        # SSH 连接字符串
        (r"ssh\s+\w+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<SSH_CONNECTION>"),
        # 邮箱
        (r"[\w.+-]+@[\w-]+\.[\w.-]+", "<EMAIL>"),
        # OpenAI API key
        (r"sk-[a-zA-Z0-9]{20,}", "<API_KEY>"),
        # AWS access key
        (r"AKIA[A-Z0-9]{16}", "<AWS_KEY>"),
        # 通用 password/secret/token/key 赋值
        (
            r"(?i)(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token|key)"
            r"\s*[=:]\s*['\"]?[^\s'\"]+",
            "<CREDENTIAL>",
        ),
        # Bearer token
        (r"(?i)Bearer\s+[A-Za-z0-9\-._~+/]+=*", "<BEARER_TOKEN>"),
        # 独立域名（不匹配 URL 路径内的）
        (r"(?<![\w./-])(?:[\w-]+\.)+(com|net|org|io|cn|ru|edu|gov)(?![\w/])", "<DOMAIN>"),
    ]

    _COMPILED = [(re.compile(p), r) for p, r in PATTERNS]

    @staticmethod
    def anonymize(text: str) -> str:
        """清洗文本中的敏感信息，替换为占位符。"""
        for pattern, replacement in Anonymizer._COMPILED:
            text = pattern.sub(replacement, text)
        return text
