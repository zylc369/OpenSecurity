# -*- coding: utf-8 -*-
"""summary: IDA Pro AI 智能分析命令 — 更新操作脚本

description:
  更新 IDA 数据库（重命名、注释等），操作后自动保存数据库。
  通过环境变量 IDA_OPERATION 指定操作类型。

  支持的操作类型（IDA_OPERATION）:
    rename           — 重命名符号（函数/全局数据）
    set_func_comment — 设置函数注释
    set_line_comment — 设置行内注释
    batch            — 批量执行多个操作（从 JSON 文件读取）

  通用可选参数:
    IDA_DRY_RUN=1 — 只预览操作不实际执行

  调用方式:
    IDA_OPERATION=rename IDA_OLD_NAME=sub_401000 IDA_NEW_NAME=validate_password IDA_OUTPUT=/tmp/result.json \\
      idat -A -S"/path/to/update.py" -L/tmp/idat.log target.i64

    IDA_OPERATION=batch IDA_BATCH_FILE=/tmp/ops.json IDA_OUTPUT=/tmp/result.json \\
      idat -A -S"/path/to/update.py" -L/tmp/idat.log target.i64

level: intermediate
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import env_str, env_bool, log, run_headless
from _utils import hex_addr, resolve_addr

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_loader
import ida_name

try:
    import ida_hexrays
    _HAS_DECOMPILER = True
except ImportError:
    _HAS_DECOMPILER = False


def _save_database():
    """保存数据库。"""
    try:
        ida_loader.save_database("")
        log("[+] 数据库已保存\n")
        return True
    except Exception as e:
        log(f"[!] 保存数据库失败: {e}\n")
        return False


def _op_rename(old_name, new_name, dry_run):
    """重命名符号。"""
    log(f"[*] 重命名: {old_name} → {new_name}\n")

    if dry_run:
        log(f"[*] [dry-run] 将重命名 {old_name} → {new_name}\n")
        return {"status": "dry_run", "old_name": old_name, "new_name": new_name}

    ea = ida_name.get_name_ea(ida_idaapi.BADADDR, old_name)
    if ea == ida_idaapi.BADADDR:
        log(f"[!] 找不到符号: {old_name}\n")
        return {"status": "error", "old_name": old_name, "new_name": new_name, "error": f"找不到符号: {old_name}"}

    ok = ida_name.set_name(ea, new_name, ida_name.SN_NOWARN)
    if ok:
        log(f"[+] 重命名成功: {old_name} → {new_name} @ {hex_addr(ea)}\n")
        return {"status": "success", "old_name": old_name, "new_name": new_name, "addr": hex_addr(ea)}
    else:
        log(f"[!] 重命名失败: {old_name} → {new_name}（可能名称不合法或冲突）\n")
        return {"status": "error", "old_name": old_name, "new_name": new_name, "error": "set_name 返回 False"}


def _op_set_func_comment(func_addr_str, comment, dry_run):
    """设置函数注释。"""
    log(f"[*] 设置函数注释: {func_addr_str} ← \"{comment}\"\n")

    ea = resolve_addr(func_addr_str)
    if ea == ida_idaapi.BADADDR:
        return {"status": "error", "func_addr": func_addr_str, "error": f"无法解析地址: {func_addr_str}"}

    func = ida_funcs.get_func(ea)
    if func is None:
        log(f"[!] 地址 {hex_addr(ea)} 不属于任何函数\n")
        return {"status": "error", "func_addr": func_addr_str, "error": f"地址 {hex_addr(ea)} 不属于任何函数"}

    if dry_run:
        log(f"[*] [dry-run] 将设置函数注释 @ {hex_addr(func.start_ea)}: \"{comment}\"\n")
        return {"status": "dry_run", "func_addr": hex_addr(func.start_ea), "comment": comment}

    results = []

    ok = ida_bytes.set_cmt(func.start_ea, comment, 0)
    if ok:
        log(f"[+] 反汇编注释已设置 @ {hex_addr(func.start_ea)}\n")
        results.append(f"反汇编注释 @ {hex_addr(func.start_ea)}")
    else:
        log(f"[!] 反汇编注释设置失败 @ {hex_addr(func.start_ea)}\n")

    if _HAS_DECOMPILER:
        try:
            if not ida_hexrays.init_hexrays_plugin():
                log("[!] 反编译器初始化失败，跳过反编译器注释\n")
            else:
                cfunc = ida_hexrays.decompile(func.start_ea)
                if cfunc:
                    tl = ida_hexrays.treeloc_t()
                    tl.ea = func.start_ea
                    tl.itp = ida_hexrays.ITP_BLOCK1
                    cfunc.set_user_cmt(tl, comment)
                    cfunc.save_user_cmts()
                    log(f"[+] 反编译器注释已设置 @ {hex_addr(func.start_ea)}\n")
                    results.append(f"反编译器注释 @ {hex_addr(func.start_ea)}")
                else:
                    log(f"[!] 反编译失败，跳过反编译器注释\n")
        except Exception as e:
            log(f"[!] 反编译器注释设置异常: {e}\n")

    return {"status": "success", "func_addr": hex_addr(func.start_ea), "comment": comment, "details": results}


def _op_set_line_comment(addr_str, comment, dry_run):
    """设置行内注释。"""
    log(f"[*] 设置行内注释: {addr_str} ← \"{comment}\"\n")

    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return {"status": "error", "addr": addr_str, "error": f"无法解析地址: {addr_str}"}

    if dry_run:
        log(f"[*] [dry-run] 将设置行内注释 @ {hex_addr(ea)}: \"{comment}\"\n")
        return {"status": "dry_run", "addr": hex_addr(ea), "comment": comment}

    ok = ida_bytes.set_cmt(ea, comment, 0)
    if ok:
        log(f"[+] 行内注释已设置 @ {hex_addr(ea)}\n")
        return {"status": "success", "addr": hex_addr(ea), "comment": comment}
    else:
        log(f"[!] 行内注释设置失败 @ {hex_addr(ea)}\n")
        return {"status": "error", "addr": hex_addr(ea), "error": "set_cmt 返回 False"}


def _op_batch(batch_file, dry_run):
    """批量执行操作。"""
    log(f"[*] 批量操作模式，文件: {batch_file}\n")

    if not batch_file:
        return {"status": "error", "error": "IDA_BATCH_FILE 未指定"}

    if not os.path.isfile(batch_file):
        return {"status": "error", "error": f"批量操作文件不存在: {batch_file}"}

    try:
        with open(batch_file, "r", encoding="utf-8") as f:
            batch_data = json.load(f)
    except Exception as e:
        return {"status": "error", "error": f"读取批量操作文件失败: {e}"}

    operations = batch_data.get("operations", [])
    if not operations:
        log("[!] 批量操作列表为空\n")
        return {"executed": 0, "failed": 0, "details": []}

    log(f"[*] 共 {len(operations)} 个操作待执行\n")
    if dry_run:
        log("[*] dry-run 模式: 仅预览，不实际执行\n")

    executed = 0
    failed = 0
    details = []

    for i, op in enumerate(operations):
        op_type = op.get("type", "")
        log(f"[*] 操作 [{i + 1}/{len(operations)}] 类型: {op_type}\n")

        if op_type == "rename":
            result = _op_rename(op.get("old_name", ""), op.get("new_name", ""), dry_run)
        elif op_type == "set_func_comment":
            result = _op_set_func_comment(op.get("func_addr", ""), op.get("comment", ""), dry_run)
        elif op_type == "set_line_comment":
            result = _op_set_line_comment(op.get("addr", ""), op.get("comment", ""), dry_run)
        else:
            log(f"[!] 未知操作类型: {op_type}\n")
            result = {"status": "error", "error": f"未知操作类型: {op_type}"}

        details.append(result)
        if result.get("status") == "success" or result.get("status") == "dry_run":
            executed += 1
        else:
            failed += 1

    log(f"[+] 批量操作完成: 成功 {executed}，失败 {failed}\n")
    return {"executed": executed, "failed": failed, "total": len(operations), "details": details}


def _main():
    operation = env_str("IDA_OPERATION", "")
    if not operation:
        log("[!] 未指定操作类型（IDA_OPERATION 为空）\n")
        return {"success": False, "operation": None, "data": None, "error": "IDA_OPERATION 环境变量未设置"}

    dry_run = env_bool("IDA_DRY_RUN")
    result_data = None

    if operation == "rename":
        old_name = env_str("IDA_OLD_NAME", "")
        new_name = env_str("IDA_NEW_NAME", "")
        if not old_name or not new_name:
            return {"success": False, "operation": operation, "data": None, "error": "重命名需要 IDA_OLD_NAME 和 IDA_NEW_NAME"}
        result_data = _op_rename(old_name, new_name, dry_run)

    elif operation == "set_func_comment":
        func_addr = env_str("IDA_FUNC_ADDR", "")
        comment = env_str("IDA_COMMENT", "")
        if not func_addr or not comment:
            return {"success": False, "operation": operation, "data": None, "error": "函数注释需要 IDA_FUNC_ADDR 和 IDA_COMMENT"}
        result_data = _op_set_func_comment(func_addr, comment, dry_run)

    elif operation == "set_line_comment":
        addr = env_str("IDA_ADDR", "")
        comment = env_str("IDA_COMMENT", "")
        if not addr or not comment:
            return {"success": False, "operation": operation, "data": None, "error": "行内注释需要 IDA_ADDR 和 IDA_COMMENT"}
        result_data = _op_set_line_comment(addr, comment, dry_run)

    elif operation == "batch":
        batch_file = env_str("IDA_BATCH_FILE", "")
        result_data = _op_batch(batch_file, dry_run)

    else:
        return {
            "success": False,
            "operation": operation,
            "data": None,
            "error": f"不支持的操作类型: {operation}",
        }

    if not dry_run:
        _save_database()

    if isinstance(result_data, dict) and "error" in result_data and "success" not in result_data:
        return {"success": False, "operation": operation, "data": None, "error": result_data["error"]}

    return {"success": True, "operation": operation, "data": result_data, "dry_run": dry_run, "error": None}


run_headless(_main)
