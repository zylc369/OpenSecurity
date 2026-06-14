# -*- coding: utf-8 -*-
import subprocess

import pytest

from ai.opencode import run_opencode


def _skip_if_no_opencode():
    try:
        subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("opencode 未安装")
    except subprocess.TimeoutExpired:
        pytest.skip("opencode --version 超时")


@pytest.fixture(autouse=True)
def check_opencode():
    _skip_if_no_opencode()


class TestSingleLinePrompt:

    def test_success(self):
        result = run_opencode("1+1等于几？只回答数字")
        assert result["success"] is True
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_result_keys(self):
        result = run_opencode("hi")
        assert "success" in result
        assert "message" in result
        assert isinstance(result["success"], bool)
        assert isinstance(result["message"], str)


class TestMultiLinePrompt:

    PROMPT = "依次回答以下问题，每行一个答案：\n1+1等于几？\n1+2等于几？\n9*66等于几？"

    def test_success(self):
        result = run_opencode(self.PROMPT)
        assert result["success"] is True
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_output_contains_answers(self):
        result = run_opencode(self.PROMPT)
        assert result["success"] is True
        message = result["message"]
        assert "2" in message
        assert "3" in message
        assert "594" in message

    def test_prompt_with_special_chars(self):
        prompt = '回答以下问题：\n第一行有\t制表符\n第二行有"双引号"\n第三行有$美元符号\n请逐行重复这些内容'
        result = run_opencode(prompt)
        assert result["success"] is True
        assert len(result["message"]) > 0
