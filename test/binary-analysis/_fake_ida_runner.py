# -*- coding: utf-8 -*-
"""用伪 IDAPython 模块运行 update.py，供单元测试在无 IDA Pro 环境执行。

环境变量:
  UPDATE_SCRIPT            — 目标脚本路径（必填）
  FAKE_IDA_STATE           — IDA 调用记录 JSONL 路径（可选）
  FAKE_IDA_NAMES           — 符号表 JSON，如 {"sub_401000": 4198400}
  FAKE_IDA_SET_NAME_RESULT — "1"/"0"，模拟 set_name 返回值
"""

import json
import os
import sys
import types

BADADDR = 0xFFFFFFFFFFFFFFFF
STATE_PATH = os.environ.get("FAKE_IDA_STATE", "")
SET_NAME_RESULT = os.environ.get("FAKE_IDA_SET_NAME_RESULT", "1") == "1"

if STATE_PATH:
    with open(STATE_PATH, "w", encoding="utf-8") as _f:
        _f.write("")


def _record(op, **kwargs):
    if not STATE_PATH:
        return
    entry = {"op": op}
    entry.update(kwargs)
    with open(STATE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_names():
    raw = os.environ.get("FAKE_IDA_NAMES", "{}")
    data = json.loads(raw) if raw else {}
    return {str(name): int(addr) for name, addr in data.items()}


_NAMES = _load_names()


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _install_fake_ida():
    _module("ida_idaapi", BADADDR=BADADDR)

    def get_name_ea(from_ea, name):
        _record("get_name_ea", from_ea=from_ea, name=name)
        return _NAMES.get(name, BADADDR)

    def set_name(ea, name, flags):
        _record("set_name", ea=ea, name=name, flags=flags)
        return SET_NAME_RESULT

    _module("ida_name", get_name_ea=get_name_ea, set_name=set_name, SN_NOWARN=1)

    def save_database(path):
        _record("save_database", path=path)
        return 1

    _module("ida_loader", save_database=save_database)

    def set_cmt(ea, comment, repeatable):
        _record("set_cmt", ea=ea, comment=comment, repeatable=repeatable)
        return True

    _module("ida_bytes", set_cmt=set_cmt)
    _module("ida_funcs", get_func=lambda ea: None, get_func_name=lambda ea: "")
    _module("idautils")
    _module("ida_auto", auto_wait=lambda: None)
    _module("ida_kernwin", cvar=types.SimpleNamespace(batch=1), msg=lambda msg: None)

    def qexit(code):
        raise SystemExit(code)

    _module("ida_pro", qexit=qexit)
    sys.modules["ida_hexrays"] = None


def main():
    script = os.environ.get("UPDATE_SCRIPT", "")
    if not script:
        sys.stderr.write("UPDATE_SCRIPT 未设置\n")
        return 2
    _install_fake_ida()
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    sys.argv = [script]
    import runpy

    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
