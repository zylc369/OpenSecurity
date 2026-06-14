# -*- coding: utf-8 -*-
"""summary: IDA Pro AI 智能分析命令 — 查询操作脚本

description:
  查询 IDA 数据库信息，输出结构化 JSON 供 AI 解析。
  通过环境变量 IDA_QUERY 指定查询类型，IDA_OUTPUT 指定输出文件路径。

  支持的查询类型（IDA_QUERY）:
    entry_points  — 枚举所有入口点（根据文件类型智能识别）
    functions     — 按模式匹配函数列表
    decompile     — 反编译指定函数（自动追踪 thunk 链到真实函数）
    disassemble   — 反汇编指定函数（自动追踪 thunk 链）
    func_info     — 查询单个函数的详细信息（自动追踪 thunk 链）
    xrefs_to      — 查询指定地址/函数的交叉引用（谁引用了它）
    xrefs_from    — 查询指定函数调用了哪些函数
    strings       — 搜索字符串及其引用位置
    imports       — 列出所有导入函数
    exports       — 列出所有导出函数
    segments      — 列出所有段信息（含异常信号标注）
    read_data     — 读取指定地址处的全局数据（string/bytes/pointer/auto）
    packer_detect — 检测加壳/混淆二进制（多维信号分析）

  地址参数格式:
    IDA_FUNC_ADDR / IDA_ADDR 同时接受函数名（如 main、sub_401000）
    和十六进制地址（如 0x401000）。

  调用方式:
    IDA_QUERY=entry_points IDA_OUTPUT=/tmp/result.json \\
      idat -A -S"/path/to/query.py" -L/tmp/idat.log target.i64

level: intermediate
"""

import fnmatch
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import env_str, env_int, env_bool, log, run_headless
from _utils import (
    get_func_name_safe,
    hex_addr,
    read_bytes_at,
    read_data_auto,
    read_pointer,
    read_string_at,
    resolve_addr,
    resolve_thunk,
)
from _analysis import (
    collect_entry_points,
    collect_imports,
    collect_segments,
    collect_strings,
    detect_packer,
)

import ida_auto
import ida_bytes
import ida_entry
import ida_funcs
import ida_idaapi
import ida_lines
import ida_nalt
import ida_xref
import idautils

try:
    import ida_hexrays
    _HAS_DECOMPILER = True
except ImportError:
    _HAS_DECOMPILER = False

MAX_MATCHES = 200
MAX_REFS_DISPLAY = 50
MAX_STRINGS_DISPLAY = 100


def _query_packer_detect():
    """检测加壳/混淆二进制。通过多维信号分析判断是否加壳。"""
    log("[*] 正在检测加壳/混淆特征...\n")

    seg_list, packer_name_from_seg, _ = collect_segments()
    entries, _, _, _ = collect_entry_points()
    _, import_count, _ = collect_imports()

    result = detect_packer(seg_list, packer_name_from_seg, entries, import_count)

    entry_count = ida_entry.get_entry_qty()

    result["stats"] = {
        "segment_count": len(seg_list),
        "function_count": ida_funcs.get_func_qty(),
        "import_count": import_count,
        "entry_points": entry_count,
    }

    if result["packer_detected"]:
        packer_name = result["packer_name"]
        confidence = result["confidence"]
        if packer_name and packer_name != "unknown":
            result["recommendation"] = f"检测到 {packer_name} 壳（置信度: {confidence}），建议先脱壳后分析。可尝试 {packer_name.lower()} -d <file> 脱壳后重新加载到 IDA。"
        else:
            result["recommendation"] = "检测到疑似加壳/混淆，建议先脱壳后分析。常见工具: upx -d、die（Detect It Easy）等。"
    else:
        result["recommendation"] = ""

    return result


def _resolve_func(addr_str):
    """将函数名或十六进制地址解析为 func_t 对象（含 thunk 自动追踪）。"""
    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return None, []
    func = ida_funcs.get_func(ea)
    if func is None:
        log(f"[!] 地址 {hex_addr(ea)} 不属于任何函数\n")
    return func, []


def _resolve_func_with_thunk(addr_str):
    """解析函数地址并自动追踪 thunk 链。支持 IDA_FORCE_CREATE 自动创建未识别函数。

    返回:
        (func, thunk_chain, force_created)
        func: 真实函数的 func_t 对象，None 表示失败
        thunk_chain: [{"name": str, "addr": str}] — 中间 thunk 列表
        force_created: bool — 是否通过 force_create 创建了函数
    """
    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return None, [], False

    chain, real_ea = resolve_thunk(ea)
    func = ida_funcs.get_func(real_ea)
    if func is None and real_ea != ida_idaapi.BADADDR:
        if env_bool("IDA_FORCE_CREATE"):
            log(f"[*] 地址 {hex_addr(real_ea)} 不在任何函数内，IDA_FORCE_CREATE=1，正在尝试创建函数...\n")
            ok = ida_funcs.add_func(real_ea)
            if ok:
                ida_auto.auto_wait()
                func = ida_funcs.get_func(real_ea)
                if func:
                    log(f"[+] 函数创建成功: {get_func_name_safe(func.start_ea)} "
                        f"({hex_addr(func.start_ea)} - {hex_addr(func.end_ea)}, {func.size()} 字节)\n")
                    return func, chain, True
                log(f"[!] 函数创建失败: {hex_addr(real_ea)}，get_func 仍返回 None\n")
            else:
                log(f"[!] 函数创建失败: {hex_addr(real_ea)}，该地址处可能不是有效的函数入口\n")
        else:
            log(f"[!] 地址 {hex_addr(real_ea)} 不属于任何函数。设置 IDA_FORCE_CREATE=1 可自动创建\n")
    return func, chain, False


def _query_entry_points():
    """枚举所有入口点，根据文件类型智能识别入口。"""
    log("[*] 正在查询入口点...\n")
    entries, file_type, architecture, bits = collect_entry_points()

    result = {"entries": entries, "file_type": file_type, "total": len(entries),
              "architecture": architecture}
    if bits is not None:
        result["bits"] = bits
    log(f"[+] 找到 {len(entries)} 个入口点 (架构: {architecture}"
        + (f", {bits}bit" if bits else "")
        + ")\n")
    return result


def _query_functions():
    """按模式匹配函数列表。"""
    pattern = env_str("IDA_PATTERN", "")
    log(f"[*] 正在查询函数列表，模式: '{pattern or '(全部)'}'\n")

    functions = []
    count = 0
    for ea in idautils.Functions():
        name = get_func_name_safe(ea)
        if pattern and not fnmatch.fnmatch(name, pattern):
            continue
        func = ida_funcs.get_func(ea)
        functions.append({
            "name": name,
            "addr": hex_addr(ea),
            "size": func.size() if func else 0,
        })
        count += 1
        if count >= MAX_MATCHES:
            log(f"[!] 匹配结果超过 {MAX_MATCHES}，已截断\n")
            break

    log(f"[+] 找到 {len(functions)} 个函数\n")
    return {"functions": functions, "total": len(functions), "truncated": count >= MAX_MATCHES}


def _query_decompile():
    """反编译指定函数，自动追踪 thunk 链到真实函数。"""
    addr_str = env_str("IDA_FUNC_ADDR", "")
    log(f"[*] 正在反编译函数: {addr_str}\n")

    func, thunk_chain, force_created = _resolve_func_with_thunk(addr_str)
    if func is None:
        return {"error": f"无法解析函数: {addr_str}"}

    func_name = get_func_name_safe(func.start_ea)
    source_type = "disassembly"
    source = ""

    if _HAS_DECOMPILER:
        try:
            if not ida_hexrays.init_hexrays_plugin():
                log("[!] 反编译器初始化失败\n")
            else:
                cfunc = ida_hexrays.decompile(func.start_ea)
                if cfunc:
                    source = str(cfunc)
                    source_type = "decompiled"
                    log(f"[+] 反编译成功: {func_name} ({len(source.splitlines())} 行)\n")
                else:
                    log("[!] 反编译返回 None，回退到反汇编\n")
        except Exception as e:
            log(f"[!] 反编译失败: {e}，回退到反汇编\n")

    if not source:
        source = _generate_disassembly(func)
        log(f"[+] 反汇编成功: {func_name} ({len(source.splitlines())} 行)\n")

    result = {
        "func_name": func_name,
        "addr": hex_addr(func.start_ea),
        "source": source,
        "source_type": source_type,
        "size": func.size(),
    }
    if thunk_chain:
        result["thunk_chain"] = thunk_chain
    if force_created:
        result["force_created"] = True
    return result


def _generate_disassembly(func):
    """生成函数的完整反汇编文本。"""
    lines = []
    for chunk in ida_funcs.func_tail_iterator_t(func):
        is_main = chunk.start_ea == func.start_ea
        if not is_main:
            lines.append(f"; --- 尾块: {hex_addr(chunk.start_ea)} - {hex_addr(chunk.end_ea)} ---")
        ea = chunk.start_ea
        while ea < chunk.end_ea and ea != ida_idaapi.BADADDR:
            disasm = ida_lines.generate_disasm_line(ea, ida_lines.GENDSM_REMOVE_TAGS)
            lines.append(f"{hex_addr(ea)}    {disasm}")
            ea = ida_bytes.next_head(ea, chunk.end_ea)
            if ea == ida_idaapi.BADADDR:
                break
    return "\n".join(lines)


def _query_disassemble():
    """反汇编指定函数，自动追踪 thunk 链到真实函数。"""
    addr_str = env_str("IDA_FUNC_ADDR", "")
    log(f"[*] 正在反汇编函数: {addr_str}\n")

    func, thunk_chain, force_created = _resolve_func_with_thunk(addr_str)
    if func is None:
        return {"error": f"无法解析函数: {addr_str}"}

    func_name = get_func_name_safe(func.start_ea)
    disasm = _generate_disassembly(func)
    log(f"[+] 反汇编成功: {func_name} ({len(disasm.splitlines())} 行)\n")

    result = {
        "func_name": func_name,
        "addr": hex_addr(func.start_ea),
        "disassembly": disasm,
        "size": func.size(),
    }
    if thunk_chain:
        result["thunk_chain"] = thunk_chain
    if force_created:
        result["force_created"] = True
    return result


def _query_func_info():
    """查询单个函数的详细信息，自动追踪 thunk 链到真实函数。"""
    addr_str = env_str("IDA_FUNC_ADDR", "")
    log(f"[*] 正在查询函数信息: {addr_str}\n")

    func, thunk_chain, force_created = _resolve_func_with_thunk(addr_str)
    if func is None:
        return {"error": f"无法解析函数: {addr_str}"}

    func_name = get_func_name_safe(func.start_ea)

    callers = []
    xb = ida_xref.xrefblk_t()
    for ref in xb.crefs_to(func.start_ea):
        caller_name = get_func_name_safe(ref)
        callers.append({"addr": hex_addr(ref), "func": caller_name})
        if len(callers) >= MAX_REFS_DISPLAY:
            break

    callees = []
    seen_callees = set()
    for chunk in ida_funcs.func_tail_iterator_t(func):
        ea = chunk.start_ea
        while ea < chunk.end_ea and ea != ida_idaapi.BADADDR:
            for ref in idautils.CodeRefsFrom(ea, 0):
                callee = ida_funcs.get_func(ref)
                if callee and callee.start_ea != func.start_ea and callee.start_ea not in seen_callees:
                    seen_callees.add(callee.start_ea)
                    callee_name = get_func_name_safe(callee.start_ea)
                    callees.append({"addr": hex_addr(callee.start_ea), "name": callee_name})
                    if len(callees) >= MAX_REFS_DISPLAY:
                        break
            if len(callees) >= MAX_REFS_DISPLAY:
                break
            ea = ida_bytes.next_head(ea, chunk.end_ea)
            if ea == ida_idaapi.BADADDR:
                break

    strings = []
    seen_str = set()
    for chunk in ida_funcs.func_tail_iterator_t(func):
        ea = chunk.start_ea
        while ea < chunk.end_ea and ea != ida_idaapi.BADADDR:
            for ref in idautils.DataRefsFrom(ea):
                if ref in seen_str:
                    continue
                seen_str.add(ref)
                s = ida_bytes.get_strlit_contents(ref, -1, ida_nalt.STRTYPE_C)
                if s:
                    strings.append({"value": s.decode("utf-8", errors="replace"), "addr": hex_addr(ref)})
                    if len(strings) >= MAX_STRINGS_DISPLAY:
                        break
            if len(strings) >= MAX_STRINGS_DISPLAY:
                break
            ea = ida_bytes.next_head(ea, chunk.end_ea)
            if ea == ida_idaapi.BADADDR:
                break

    prototype = ""
    try:
        prototype = str(func.prototype) if func.prototype else ""
    except Exception:
        pass

    _FUNC_STATIC = getattr(ida_funcs, "FUNC_STATIC", None)
    flags = []
    if func.flags & ida_funcs.FUNC_LIB:
        flags.append("library")
    if _FUNC_STATIC is not None and func.flags & _FUNC_STATIC:
        flags.append("static")
    if func.flags & ida_funcs.FUNC_FRAME:
        flags.append("frame")
    if func.flags & ida_funcs.FUNC_THUNK:
        flags.append("thunk")
    if func.flags & ida_funcs.FUNC_NORET:
        flags.append("noreturn")

    log(f"[+] 函数信息: {func_name} @ {hex_addr(func.start_ea)}\n")
    result = {
        "name": func_name,
        "addr": hex_addr(func.start_ea),
        "end_addr": hex_addr(func.end_ea),
        "size": func.size(),
        "flags": flags,
        "prototype": prototype,
        "callers": callers,
        "callees": callees,
        "strings": strings,
    }
    if thunk_chain:
        result["thunk_chain"] = thunk_chain
    if force_created:
        result["force_created"] = True
    return result


def _query_xrefs_to():
    """查询指定地址/函数的交叉引用（谁引用了它）。"""
    addr_str = env_str("IDA_ADDR", "") or env_str("IDA_FUNC_ADDR", "")
    log(f"[*] 正在查询交叉引用（to）: {addr_str}\n")

    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return {"error": f"无法解析地址: {addr_str}"}

    refs = []
    for xref in idautils.XrefsTo(ea, 0):
        func_name = get_func_name_safe(xref.frm)
        xref_type = _xref_type_str(xref.type)
        refs.append({
            "from": hex_addr(xref.frm),
            "from_func": func_name,
            "type": xref_type,
        })
        if len(refs) >= MAX_REFS_DISPLAY:
            break

    log(f"[+] 找到 {len(refs)} 个交叉引用\n")
    return {"target": hex_addr(ea), "target_name": get_func_name_safe(ea), "refs": refs, "total": len(refs)}


def _query_xrefs_from():
    """查询指定函数调用了哪些函数。"""
    addr_str = env_str("IDA_FUNC_ADDR", "")
    log(f"[*] 正在查询交叉引用（from）: {addr_str}\n")

    func, _ = _resolve_func(addr_str)
    if func is None:
        ea = resolve_addr(addr_str)
        if ea == ida_idaapi.BADADDR:
            return {"error": f"无法解析地址: {addr_str}"}
        refs = []
        for xref in idautils.XrefsFrom(ea, 0):
            to_func = get_func_name_safe(xref.to)
            refs.append({"to": hex_addr(xref.to), "to_func": to_func, "type": _xref_type_str(xref.type)})
            if len(refs) >= MAX_REFS_DISPLAY:
                break
        return {"source": hex_addr(ea), "source_name": get_func_name_safe(ea), "refs": refs, "total": len(refs)}

    refs = []
    seen = set()
    for chunk in ida_funcs.func_tail_iterator_t(func):
        ea = chunk.start_ea
        while ea < chunk.end_ea and ea != ida_idaapi.BADADDR:
            for xref in idautils.XrefsFrom(ea, 0):
                to_func = get_func_name_safe(xref.to)
                key = (xref.to, xref.type)
                if key not in seen:
                    seen.add(key)
                    refs.append({
                        "from": hex_addr(ea),
                        "to": hex_addr(xref.to),
                        "to_func": to_func,
                        "type": _xref_type_str(xref.type),
                    })
                    if len(refs) >= MAX_REFS_DISPLAY:
                        break
            ea = ida_bytes.next_head(ea, chunk.end_ea)
            if ea == ida_idaapi.BADADDR:
                break

    log(f"[+] 找到 {len(refs)} 个引用\n")
    return {
        "source": hex_addr(func.start_ea),
        "source_name": get_func_name_safe(func.start_ea),
        "refs": refs,
        "total": len(refs),
    }


def _xref_type_str(xref_type):
    """将交叉引用类型转为可读字符串。"""
    mapping = {
        0: "unknown",
        1: "offset",
        2: "write",
        3: "read",
        4: "text",
        5: "data",
        16: "near_call",
        17: "near_jump",
        18: "far_call",
        19: "far_jump",
    }
    return mapping.get(xref_type, f"type_{xref_type}")


def _query_strings():
    """搜索字符串及其引用位置。"""
    pattern = env_str("IDA_PATTERN", "")
    log(f"[*] 正在搜索字符串，模式: '{pattern or '(全部)'}'\n")

    strings_list = collect_strings(pattern, MAX_STRINGS_DISPLAY)

    truncated = len(strings_list) >= MAX_STRINGS_DISPLAY
    if truncated:
        log(f"[!] 字符串结果超过 {MAX_STRINGS_DISPLAY}，已截断\n")

    log(f"[+] 找到 {len(strings_list)} 个字符串\n")
    return {"strings": strings_list, "total": len(strings_list), "pattern": pattern, "truncated": truncated}


def _query_imports():
    """列出所有导入函数。"""
    log("[*] 正在查询导入表...\n")
    modules, total, _ = collect_imports()
    log(f"[+] 找到 {len(modules)} 个导入模块，共 {total} 个导入函数\n")
    return {"modules": modules, "total_modules": len(modules), "total_functions": total}


def _query_exports():
    """列出所有导出函数。"""
    log("[*] 正在查询导出表...\n")

    exports = []
    eqty = ida_entry.get_entry_qty()
    for i in range(eqty):
        ordinal = ida_entry.get_entry_ordinal(i)
        ea = ida_entry.get_entry(ordinal)
        if ea == ida_idaapi.BADADDR:
            continue
        name = ida_entry.get_entry_name(ordinal)
        if not name:
            name = get_func_name_safe(ea)
        exports.append({
            "name": name,
            "addr": hex_addr(ea),
            "ordinal": ordinal,
        })

    log(f"[+] 找到 {len(exports)} 个导出函数\n")
    return {"exports": exports, "total": len(exports)}


def _query_segments():
    """列出所有段信息，含异常信号标注。"""
    log("[*] 正在查询段信息...\n")

    seg_list, detected_packer, packer_confidence = collect_segments()

    result = {"segments": seg_list, "total": len(seg_list)}

    if detected_packer:
        result["packer_warning"] = {
            "detected": True,
            "packer_name": detected_packer,
            "confidence": packer_confidence,
        }
        log(f"[!] 壳检测警告: {detected_packer}（置信度: {packer_confidence}）\n")
    else:
        result["packer_warning"] = {"detected": False, "packer_name": None, "confidence": "none"}

    log(f"[+] 找到 {len(seg_list)} 个段\n")
    return result


def _query_read_data():
    """读取指定地址处的全局数据。"""
    addr_str = env_str("IDA_ADDR", "")
    mode = env_str("IDA_READ_MODE", "auto")
    size = env_int("IDA_READ_SIZE", 64)
    do_deref = env_bool("IDA_DEREF")

    log(f"[*] 正在读取数据: {addr_str}，模式: {mode}\n")

    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return {"error": f"无法解析地址: {addr_str}"}

    if mode == "string":
        result = read_string_at(ea)
        if result is None:
            return {"error": f"地址 {hex_addr(ea)} 处无可读字符串"}
        result["type"] = "string"
        return result

    if mode == "bytes":
        result = read_bytes_at(ea, size)
        result["type"] = "bytes"
        return result

    if mode == "pointer":
        ptr_info = read_pointer(ea)
        result = {"type": "pointer", "addr": ptr_info["addr"], "pointer_value": ptr_info["pointer_value"]}
        if do_deref:
            try:
                ptr_val = int(ptr_info["pointer_value"], 16)
            except ValueError:
                ptr_val = 0
            deref = read_data_auto(ptr_val)
            result["dereferenced"] = deref
        else:
            result["dereferenced"] = None
        return result

    result = read_data_auto(ea, size_hint=size)
    log(f"[+] 数据读取完成: 类型={result.get('type', 'unknown')}，地址={hex_addr(ea)}\n")
    return result


_QUERY_HANDLERS = {
    "entry_points": _query_entry_points,
    "functions": _query_functions,
    "decompile": _query_decompile,
    "disassemble": _query_disassemble,
    "func_info": _query_func_info,
    "xrefs_to": _query_xrefs_to,
    "xrefs_from": _query_xrefs_from,
    "strings": _query_strings,
    "imports": _query_imports,
    "exports": _query_exports,
    "segments": _query_segments,
    "read_data": _query_read_data,
    "packer_detect": _query_packer_detect,
}


def _main():
    query_type = env_str("IDA_QUERY", "")
    if not query_type:
        log("[!] 未指定查询类型（IDA_QUERY 为空）\n")
        return {"success": False, "query": None, "data": None, "error": "IDA_QUERY 环境变量未设置"}

    handler = _QUERY_HANDLERS.get(query_type)
    if handler is None:
        available = ", ".join(sorted(_QUERY_HANDLERS.keys()))
        log(f"[!] 不支持的查询类型: {query_type}，可用类型: {available}\n")
        return {"success": False, "query": query_type, "data": None, "error": f"不支持的查询类型: {query_type}，可用: {available}"}

    log(f"[*] 查询类型: {query_type}\n")
    data = handler()

    if isinstance(data, dict) and "error" in data and "success" not in data:
        return {"success": False, "query": query_type, "data": None, "error": data["error"]}

    return {"success": True, "query": query_type, "data": data, "error": None}


run_headless(_main)
