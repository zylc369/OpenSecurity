# -*- coding: utf-8 -*-
"""update.py rename 操作的单元测试。

不依赖 IDA Pro：通过 _fake_ida_runner.py 注入伪 IDAPython 模块，
以 headless 子进程方式运行真实 update.py，校验 JSON 输出与 IDA 调用。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPDATE_SCRIPT = PROJECT_ROOT / ".opencode" / "binary-analysis" / "update.py"
RUNNER = Path(__file__).resolve().parent / "_fake_ida_runner.py"

FAKE_NAMES = {"sub_401000": 0x401000}


def _run_update(tmp_path, **overrides):
    output_path = tmp_path / "output.json"
    calls_path = tmp_path / "ida_calls.jsonl"

    env = os.environ.copy()
    for key in list(env):
        if key.startswith("IDA_") or key.startswith("FAKE_IDA_"):
            env.pop(key)

    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "UPDATE_SCRIPT": str(UPDATE_SCRIPT),
        "IDA_OUTPUT": str(output_path),
        "FAKE_IDA_STATE": str(calls_path),
        "FAKE_IDA_NAMES": json.dumps(FAKE_NAMES),
    })

    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)

    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    payload = None
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))

    calls = []
    if calls_path.exists():
        calls = [
            json.loads(line)
            for line in calls_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    return proc, payload, calls


def _calls(calls, op):
    return [call for call in calls if call.get("op") == op]


class TestRenameSuccess:

    def test_rename_existing_symbol(self, tmp_path):
        proc, payload, calls = _run_update(
            tmp_path,
            IDA_OPERATION="rename",
            IDA_OLD_NAME="sub_401000",
            IDA_NEW_NAME="validate_password",
        )

        assert proc.returncode == 0, proc.stderr
        assert payload == {
            "success": True,
            "operation": "rename",
            "data": {
                "status": "success",
                "old_name": "sub_401000",
                "new_name": "validate_password",
                "addr": "0x401000",
            },
            "dry_run": False,
            "error": None,
        }
        assert _calls(calls, "set_name") == [{
            "op": "set_name",
            "ea": 0x401000,
            "name": "validate_password",
            "flags": 1,
        }]
        assert len(_calls(calls, "save_database")) == 1
        assert "重命名成功" in proc.stderr


class TestRenameDryRun:

    def test_dry_run_preview(self, tmp_path):
        proc, payload, calls = _run_update(
            tmp_path,
            IDA_OPERATION="rename",
            IDA_OLD_NAME="sub_401000",
            IDA_NEW_NAME="validate_password",
            IDA_DRY_RUN="1",
        )

        assert proc.returncode == 0, proc.stderr
        assert payload == {
            "success": True,
            "operation": "rename",
            "data": {
                "status": "dry_run",
                "old_name": "sub_401000",
                "new_name": "validate_password",
            },
            "dry_run": True,
            "error": None,
        }
        assert "[dry-run] 将重命名 sub_401000 → validate_password" in proc.stderr
        assert _calls(calls, "get_name_ea") == []
        assert _calls(calls, "set_name") == []
        assert _calls(calls, "save_database") == []


class TestRenameErrors:

    @pytest.mark.parametrize("overrides", [
        {"IDA_OLD_NAME": "", "IDA_NEW_NAME": "validate_password"},
        {"IDA_OLD_NAME": "sub_401000", "IDA_NEW_NAME": ""},
        {"IDA_OLD_NAME": None, "IDA_NEW_NAME": "validate_password"},
        {"IDA_OLD_NAME": "sub_401000", "IDA_NEW_NAME": None},
    ])
    def test_rename_requires_both_names(self, tmp_path, overrides):
        env = {"IDA_OPERATION": "rename"}
        env.update(overrides)

        proc, payload, calls = _run_update(tmp_path, **env)

        assert proc.returncode == 1
        assert payload["success"] is False
        assert payload["operation"] == "rename"
        assert payload["data"] is None
        assert payload["error"] == "重命名需要 IDA_OLD_NAME 和 IDA_NEW_NAME"
        assert _calls(calls, "set_name") == []
        assert _calls(calls, "save_database") == []

    def test_rename_nonexistent_symbol(self, tmp_path):
        proc, payload, calls = _run_update(
            tmp_path,
            IDA_OPERATION="rename",
            IDA_OLD_NAME="sub_deadbeef",
            IDA_NEW_NAME="validate_password",
        )

        assert proc.returncode == 1
        assert payload["success"] is False
        assert payload["operation"] == "rename"
        assert payload["data"] is None
        assert payload["error"] == "找不到符号: sub_deadbeef"
        assert _calls(calls, "set_name") == []

    def test_rename_invalid_address_as_old_name(self, tmp_path):
        proc, payload, calls = _run_update(
            tmp_path,
            IDA_OPERATION="rename",
            IDA_OLD_NAME="0xZZZZ",
            IDA_NEW_NAME="validate_password",
        )

        assert proc.returncode == 1
        assert payload["success"] is False
        assert payload["error"] == "找不到符号: 0xZZZZ"
        assert _calls(calls, "set_name") == []

    def test_rename_rejected_by_ida(self, tmp_path):
        proc, payload, calls = _run_update(
            tmp_path,
            IDA_OPERATION="rename",
            IDA_OLD_NAME="sub_401000",
            IDA_NEW_NAME="invalid name",
            FAKE_IDA_SET_NAME_RESULT="0",
        )

        assert proc.returncode == 1
        assert payload["success"] is False
        assert payload["error"] == "set_name 返回 False"
        set_name_calls = _calls(calls, "set_name")
        assert len(set_name_calls) == 1
        assert set_name_calls[0]["name"] == "invalid name"
