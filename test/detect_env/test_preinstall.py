# -*- coding: utf-8 -*-
"""_check_preinstall 预装依赖检查编排测试。

覆盖：agent 过滤、required/optional 分级、python(tool) 分发检测、
install_hint 生成（python 动态生成 / tool 用 dep 字段）、find_spec 异常上抛。

用 monkeypatch 替换 PYTHON_PACKAGES/EXTERNAL_TOOLS 为测试专用列表，
mock find_spec 和 _resolve_tool，不依赖真实环境。
"""
import importlib.util

import pytest


def _mock_find_spec(found_names):
    """生成 find_spec mock：found_names 中的返回真值（已装），其余返回 None（缺失）。"""
    def finder(name):
        return True if name in found_names else None
    return finder


class TestCheckPreinstall:
    """_check_preinstall(agent) 预装依赖检查。"""

    def test_all_present_success(self, env, monkeypatch):
        """所有必需依赖齐全 → success。"""
        pkgs = [env.Dependency(name="pkg_a", kind="python", preinstall=True,
                               agents=["test"], required=True)]
        tools = [env.Dependency(name="tool_a", kind="tool", preinstall=True,
                                agents=["test"], required=True)]
        monkeypatch.setattr(env, "PYTHON_PACKAGES", pkgs)
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", tools)
        monkeypatch.setattr(importlib.util, "find_spec", _mock_find_spec({"pkg_a"}))
        monkeypatch.setattr(env, "_resolve_tool", lambda d: ("/path/tool_a", True))

        result = env._check_preinstall("test")
        assert result["success"] is True
        assert result["errors"] == []

    def test_required_python_missing(self, env, monkeypatch):
        """必需 Python 包缺失 → error 含动态生成的 install_hint。"""
        dep = env.Dependency(name="sage", kind="python", preinstall=True,
                             agents=["crypto"], required=True, pip_name="sage",
                             conda_name="sage", installer="conda")
        monkeypatch.setattr(env, "PYTHON_PACKAGES", [dep])
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [])
        monkeypatch.setattr(importlib.util, "find_spec", _mock_find_spec(set()))

        result = env._check_preinstall("crypto")
        assert result["success"] is False
        assert len(result["errors"]) == 1
        err = result["errors"][0]
        assert err["package"] == "sage"
        assert "conda install" in err["install_hint"]
        assert "sage" in err["install_hint"]

    def test_required_tool_missing(self, env, monkeypatch):
        """必需工具缺失 → error 用 dep 自带的 install_hint。"""
        dep = env.Dependency(name="ida_pro", kind="tool", preinstall=True,
                             agents=["binary-analysis"], required=True,
                             install_hint="IDA Pro 未检测到。设置 IDA_PRO_HOME")
        monkeypatch.setattr(env, "PYTHON_PACKAGES", [])
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [dep])
        monkeypatch.setattr(env, "_resolve_tool", lambda d: ("", False))

        result = env._check_preinstall("binary-analysis")
        assert result["success"] is False
        assert result["errors"][0]["install_hint"] == "IDA Pro 未检测到。设置 IDA_PRO_HOME"

    def test_optional_missing_not_blocking(self, env, monkeypatch):
        """可选依赖（required=False）缺失不阻塞 → success。"""
        dep = env.Dependency(name="GoReSym", kind="tool", preinstall=True,
                             agents=["binary-analysis"], required=False)
        monkeypatch.setattr(env, "PYTHON_PACKAGES", [])
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [dep])
        monkeypatch.setattr(env, "_resolve_tool", lambda d: ("", False))

        result = env._check_preinstall("binary-analysis")
        assert result["success"] is True
        assert result["errors"] == []

    def test_agent_filtering(self, env, monkeypatch):
        """全量检测写 cache（find_spec 调用所有 preinstall 包），errors 按 agent 过滤。

        业务逻辑：find_spec 对所有 preinstall 包都调用（收集版本写 cache），
        但 errors 只报匹配当前 agent 的缺失包。
        """
        pkgs = [
            env.Dependency(name="binary_pkg", kind="python", preinstall=True,
                           agents=["binary-analysis"], required=True),
            env.Dependency(name="mobile_pkg", kind="python", preinstall=True,
                           agents=["mobile-analysis"], required=True),
        ]
        monkeypatch.setattr(env, "PYTHON_PACKAGES", pkgs)
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [])

        # 所有包都缺失 → find_spec 返回 None
        monkeypatch.setattr(importlib.util, "find_spec", _mock_find_spec(set()))

        result = env._check_preinstall("binary-analysis")
        # errors 只含 binary_pkg（agent 过滤），不含 mobile_pkg
        assert result["success"] is False
        packages_in_errors = [e["package"] for e in result["errors"]]
        assert "binary_pkg" in packages_in_errors
        assert "mobile_pkg" not in packages_in_errors
        # cache 中两个包都记录了（全量检测）
        assert "binary_pkg" not in result["data"]["packages"]  # 缺失的不进 packages
        # mobile_pkg 也被 find_spec 检测了（只是缺失不进 packages，errors 被过滤）

    def test_no_agents_means_all(self, env, monkeypatch):
        """agents 为空列表 → 对所有 agent 都检查。"""
        dep = env.Dependency(name="common_pkg", kind="python", preinstall=True,
                             agents=[], required=True)
        monkeypatch.setattr(env, "PYTHON_PACKAGES", [dep])
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [])
        monkeypatch.setattr(importlib.util, "find_spec", _mock_find_spec({"common_pkg"}))

        # 任意 agent 都应检查 common_pkg
        for agent in ["binary-analysis", "mobile-analysis", "crypto-analysis", "any-agent"]:
            result = env._check_preinstall(agent)
            assert result["success"] is True

    def test_find_spec_exception_reraises(self, env, monkeypatch, capsys):
        """find_spec 抛异常时不静默吞——_warn 后上抛（让 detect_env 非零退出暴露问题）。"""
        dep = env.Dependency(name="bad", kind="python", preinstall=True,
                             agents=["x"], required=True)
        monkeypatch.setattr(env, "PYTHON_PACKAGES", [dep])
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [])

        def raising(name):
            raise RuntimeError("find_spec broken")
        monkeypatch.setattr(importlib.util, "find_spec", raising)

        with pytest.raises(RuntimeError, match="find_spec broken"):
            env._check_preinstall("x")
        captured = capsys.readouterr()
        assert "find_spec(bad) 异常" in captured.err

    def test_non_preinstall_skipped(self, env, monkeypatch):
        """非 preinstall 依赖不在预装检查范围内（由全量检测处理）。"""
        pkgs = [
            env.Dependency(name="auto_pkg", kind="python", preinstall=False, required=True),
            env.Dependency(name="pre_pkg", kind="python", preinstall=True, required=True),
        ]
        monkeypatch.setattr(env, "PYTHON_PACKAGES", pkgs)
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", [])

        checked = []
        def tracking(name):
            checked.append(name)
            return True
        monkeypatch.setattr(importlib.util, "find_spec", tracking)

        env._check_preinstall("any")
        assert checked == ["pre_pkg"]  # auto_pkg 被跳过

    def test_multiple_errors_collected(self, env, monkeypatch):
        """多个必需依赖同时缺失 → 一次性收集所有 errors。"""
        pkgs = [env.Dependency(name="pkg1", kind="python", preinstall=True,
                               agents=["x"], required=True, pip_name="pkg1")]
        tools = [
            env.Dependency(name="tool1", kind="tool", preinstall=True,
                           agents=["x"], required=True, install_hint="hint1"),
            env.Dependency(name="tool2", kind="tool", preinstall=True,
                           agents=["x"], required=True, install_hint="hint2"),
        ]
        monkeypatch.setattr(env, "PYTHON_PACKAGES", pkgs)
        monkeypatch.setattr(env, "EXTERNAL_TOOLS", tools)
        monkeypatch.setattr(importlib.util, "find_spec", _mock_find_spec(set()))
        monkeypatch.setattr(env, "_resolve_tool", lambda d: ("", False))

        result = env._check_preinstall("x")
        assert result["success"] is False
        assert len(result["errors"]) == 3
        packages = [e["package"] for e in result["errors"]]
        assert set(packages) == {"pkg1", "tool1", "tool2"}
