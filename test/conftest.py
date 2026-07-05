# -*- coding: utf-8 -*-
"""测试根级 conftest：注册自定义 pytest mark。"""

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires real browser/playwright (auto-skip if unavailable)"
    )
