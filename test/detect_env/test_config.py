# -*- coding: utf-8 -*-
"""环境配置与缓存测试。

覆盖：_get_opencode_root（路径推导）、_load_ai_env（.ai_env 解析）、
_ensure_ai_env_template（模板创建）、_load_cache / _save_cache（缓存 TTL/损坏）。

文件系统交互用 tmp_path 隔离；模块级常量（AI_ENV_FILE/CACHE_FILE）用 monkeypatch 重定向。
"""
import json
import os
import time
from pathlib import Path

import pytest


class TestGetOpencodeRoot:
    """_get_opencode_root() 路径推导（环境变量优先 + 脚本位置 fallback）。"""

    def test_env_var_priority(self, env, monkeypatch, tmp_path):
        """OPENCODE_ROOT 指向有效目录时优先使用。"""
        monkeypatch.setenv("OPENCODE_ROOT", str(tmp_path))
        assert env._get_opencode_root() == str(tmp_path)

    def test_env_var_invalid_fallback(self, env, monkeypatch):
        """环境变量指向不存在的目录时 fallback 到脚本位置推导。"""
        monkeypatch.setenv("OPENCODE_ROOT", "/nonexistent/path/xyz")
        root = env._get_opencode_root()
        # fallback：detect_env.py 在 .opencode/binary-analysis/scripts/，往上三级 = .opencode
        assert Path(root).name == ".opencode"

    def test_no_env_var_fallback(self, env, monkeypatch):
        """无环境变量时从脚本位置推导。"""
        monkeypatch.delenv("OPENCODE_ROOT", raising=False)
        root = env._get_opencode_root()
        assert Path(root).name == ".opencode"


class TestLoadAiEnv:
    """_load_ai_env() 解析 .ai_env（KEY=VALUE），setdefault 合并进 os.environ。"""

    def test_parses_key_value(self, env, monkeypatch, tmp_path):
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("IDA_PRO_HOME=/opt/ida\nDEBUG=1\n", encoding="utf-8")
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))
        monkeypatch.delenv("IDA_PRO_HOME", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)

        env._load_ai_env()

        assert os.environ.get("IDA_PRO_HOME") == "/opt/ida"
        assert os.environ.get("DEBUG") == "1"

    def test_skips_comments_and_blanks(self, env, monkeypatch, tmp_path):
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("# 注释行\n\nIDA_PRO_HOME=/ida\n  \n", encoding="utf-8")
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))
        monkeypatch.delenv("IDA_PRO_HOME", raising=False)

        env._load_ai_env()

        assert os.environ.get("IDA_PRO_HOME") == "/ida"

    def test_skips_lines_without_equals(self, env, monkeypatch, tmp_path):
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("NO_EQUAL_SIGN\nIDA_PRO_HOME=/ida\n", encoding="utf-8")
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))
        monkeypatch.delenv("IDA_PRO_HOME", raising=False)
        monkeypatch.delenv("NO_EQUAL_SIGN", raising=False)

        env._load_ai_env()

        assert os.environ.get("IDA_PRO_HOME") == "/ida"
        assert "NO_EQUAL_SIGN" not in os.environ

    def test_setdefault_not_override_existing(self, env, monkeypatch, tmp_path):
        """系统 env 优先级高于 .ai_env（setdefault 不覆盖已存在 key）。"""
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("MY_TEST_VAR=from_file\n", encoding="utf-8")
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))
        monkeypatch.setenv("MY_TEST_VAR", "from_system")

        env._load_ai_env()

        assert os.environ["MY_TEST_VAR"] == "from_system"

    def test_no_file_silent(self, env, monkeypatch, tmp_path):
        """文件不存在时静默返回（无异常）。"""
        monkeypatch.setattr(env, "AI_ENV_FILE", str(tmp_path / "nonexistent"))
        env._load_ai_env()  # 不应抛异常

    @pytest.mark.skipif(os.name == "nt", reason="Windows 权限模型不同")
    def test_read_failure_warns(self, env, monkeypatch, tmp_path, capsys):
        """文件存在但读取失败（权限）时走 _warn 诊断，不静默吞。"""
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("K=V\n", encoding="utf-8")
        ai_env.chmod(0o000)
        try:
            if os.access(str(ai_env), os.R_OK):
                pytest.skip("当前用户可读无权限文件（如 root）")
            monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))
            env._load_ai_env()
            captured = capsys.readouterr()
            assert "读取 .ai_env 失败" in captured.err
        finally:
            ai_env.chmod(0o644)  # 恢复以便 tmp_path 清理


class TestEnsureAiEnvTemplate:
    """_ensure_ai_env_template() 不存在时创建模板，存在时跳过。"""

    def test_creates_template_when_absent(self, env, monkeypatch, tmp_path, capsys):
        ai_env = tmp_path / ".ai_env"
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))

        env._ensure_ai_env_template()

        assert ai_env.is_file()
        content = ai_env.read_text(encoding="utf-8")
        assert "IDA_PRO_HOME=" in content
        # 成功提示走 stderr（不污染 --check-preinstall 的 stdout JSON）
        captured = capsys.readouterr()
        assert "已创建环境变量配置模板" in captured.err
        assert captured.out == ""

    def test_preserves_existing_file(self, env, monkeypatch, tmp_path):
        """已存在的 .ai_env 不被覆盖（用户内容优先）。"""
        ai_env = tmp_path / ".ai_env"
        ai_env.write_text("USER_CUSTOM=value\n", encoding="utf-8")
        monkeypatch.setattr(env, "AI_ENV_FILE", str(ai_env))

        env._ensure_ai_env_template()

        assert ai_env.read_text(encoding="utf-8") == "USER_CUSTOM=value\n"


class TestLoadSaveCache:
    """_load_cache / _save_cache 缓存读写（24h TTL）。"""

    def _setup_cache(self, env, monkeypatch, tmp_path):
        """重定向缓存到临时目录。"""
        cache_file = tmp_path / "env_cache.json"
        monkeypatch.setattr(env, "CACHE_FILE", str(cache_file))
        monkeypatch.setattr(env, "CACHE_DIR", str(tmp_path))
        return cache_file

    def test_save_then_load(self, env, monkeypatch, tmp_path):
        cache_file = self._setup_cache(env, monkeypatch, tmp_path)
        data = {"packages": {"capstone": {"available": True}}}

        env._save_cache(data)
        assert cache_file.is_file()

        loaded = env._load_cache()
        assert loaded == data

    def test_load_nonexistent(self, env, monkeypatch, tmp_path):
        self._setup_cache(env, monkeypatch, tmp_path)
        assert env._load_cache() is None

    def test_force_skips_cache(self, env, monkeypatch, tmp_path):
        """force=True 时即使有有效缓存也返回 None。"""
        cache_file = self._setup_cache(env, monkeypatch, tmp_path)
        env._save_cache({"packages": {"x": {"available": True}}})

        assert env._load_cache(force=True) is None

    def test_expired_cache_returns_none(self, env, monkeypatch, tmp_path):
        """超过 CACHE_TTL 的缓存视为过期。"""
        cache_file = self._setup_cache(env, monkeypatch, tmp_path)
        # 写入一个时间戳已过期的缓存
        expired = {"timestamp": time.time() - env.CACHE_TTL - 1, "data": {"packages": {}}}
        cache_file.write_text(json.dumps(expired), encoding="utf-8")

        assert env._load_cache() is None

    def test_corrupted_json_warns(self, env, monkeypatch, tmp_path, capsys):
        """损坏的 JSON 走 _warn 诊断后返回 None（触发重新检测）。"""
        cache_file = self._setup_cache(env, monkeypatch, tmp_path)
        cache_file.write_text("{ this is not valid json !!!", encoding="utf-8")

        assert env._load_cache() is None
        captured = capsys.readouterr()
        assert "env_cache.json 解析失败" in captured.err

    def test_save_creates_cache_dir(self, env, monkeypatch, tmp_path):
        """CACHE_DIR 不存在时 _save_cache 自动创建。"""
        nested = tmp_path / "nested" / "cache_dir"
        monkeypatch.setattr(env, "CACHE_DIR", str(nested))
        monkeypatch.setattr(env, "CACHE_FILE", str(nested / "env_cache.json"))

        env._save_cache({"packages": {}})

        assert nested.is_dir()
        assert (nested / "env_cache.json").is_file()
