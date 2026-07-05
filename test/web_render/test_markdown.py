# -*- coding: utf-8 -*-
"""_html_to_markdown() HTML 转 Markdown 测试。"""
import pytest


class TestHtmlToMarkdown:
    """_html_to_markdown(html) 使用 markdownify 库转换。"""

    def test_basic_conversion(self, render_mod):
        """基本 HTML 标签转换。"""
        html = "<h1>Title</h1><p>Paragraph</p>"
        md = render_mod._html_to_markdown(html)
        assert "# Title" in md
        assert "Paragraph" in md

    def test_links_converted(self, render_mod):
        """<a> 标签转为 Markdown 链接格式。"""
        html = '<a href="https://example.com">link text</a>'
        md = render_mod._html_to_markdown(html)
        assert "[link text]" in md
        assert "https://example.com" in md

    def test_empty_html(self, render_mod):
        """空 HTML 返回空或仅空白。"""
        md = render_mod._html_to_markdown("")
        assert md is not None  # markdownify 对空输入返回空字符串

    def test_heading_style_atx(self, render_mod):
        """标题使用 ATX 风格（# 前缀）。"""
        html = "<h2>Section</h2>"
        md = render_mod._html_to_markdown(html)
        assert "## Section" in md

    def test_returns_string(self, render_mod):
        result = render_mod._html_to_markdown("<p>test</p>")
        assert isinstance(result, str)
