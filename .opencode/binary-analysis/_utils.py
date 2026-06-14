# -*- coding: utf-8 -*-
"""summary: IDA Pro AI 智能分析命令 — 共享业务工具模块

description:
  提供所有工具脚本共享的业务逻辑工具函数，包括：
  1. resolve_thunk(start_ea) — thunk 链追踪到真实函数
  2. read_string_at(ea) — 读取 null-terminated 字符串
  3. read_bytes_at(ea, length) — 读取原始字节（hex + ASCII）
  4. read_pointer(ea) — 读取指针值（自适应 4/8 字节）
  5. read_data_auto(ea) — 自动判断数据类型并读取
  6. resolve_addr(addr_str) — 统一地址解析（函数名或十六进制地址）
  7. hex_addr(ea) — 格式化地址为 "0x..." 字符串
  8. get_func_name_safe(ea) — 安全获取函数名
  9. seg_perm_str(perm) — 段权限位转可读字符串
  10. estimate_entropy(ea, size) — Shannon 熵估算
  11. _PACKER_SEGMENT_PATTERNS — 已知壳段名模式字典

  依赖关系: _base.py → _utils.py → query.py / update.py / scripts/*.py
  本模块仅依赖 _base.py 的 log 函数和 IDAPython 模块，不依赖 query.py 或 update.py。

level: intermediate
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import log

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_name
import idautils


def resolve_addr(addr_str):
    """统一地址解析（函数名或十六进制地址）。

    支持格式: "0x401000", "401000", "main", "sub_401000" 等。
    返回解析后的地址（int），BADADDR 表示失败。
    """
    if not addr_str:
        return ida_idaapi.BADADDR
    try:
        ea = int(addr_str, 16)
        if 0 <= ea < ida_idaapi.BADADDR:
            return ea
    except ValueError:
        pass
    ea = ida_name.get_name_ea(ida_idaapi.BADADDR, addr_str)
    if ea == ida_idaapi.BADADDR:
        log(f"[!] 无法解析地址: {addr_str}\n")
    return ea


def hex_addr(ea):
    """格式化地址为 "0x..." 字符串。"""
    return f"0x{ea:X}"


def seg_perm_str(perm):
    """将段权限位转为可读字符串。"""
    s = ""
    if perm & 1:
        s += "x"
    if perm & 2:
        s += "w"
    if perm & 4:
        s += "r"
    return s if s else "none"


def estimate_entropy(ea, size):
    """对指定区域采样估算 Shannon entropy。"""
    sample_size = min(size, 1024)
    if sample_size <= 0:
        return 0.0
    freq = [0] * 256
    for i in range(sample_size):
        b = ida_bytes.get_byte(ea + i)
        freq[b] += 1
    entropy = 0.0
    for count in freq:
        if count > 0:
            p = count / sample_size
            entropy -= p * math.log2(p)
    return entropy


_PACKER_SEGMENT_PATTERNS = {
    "UPX": ["UPX", ".upx"],
    "MPRESS": [".nsp0", ".nsp1", ".nsp2"],
    "Themida": [".themida", ".winlice"],
    "VMProtect": [".vmp0", ".vmp1"],
    "ASPack": [".aspack"],
    "PECompact": [".pec2"],
    "Enigma": [".enigma1", ".enigma2"],
}


def get_func_name_safe(ea):
    """安全获取函数名，失败返回空字符串。"""
    name = ida_funcs.get_func_name(ea)
    return name if name else ""


def resolve_thunk(start_ea, max_depth=10):
    """追踪 thunk 链到真实函数。

    参数:
        start_ea: 起始地址（可以是 thunk 或普通函数）
        max_depth: 最大追踪深度（防无限循环）

    返回:
        (chain, real_func_ea)
        chain: [{"name": str, "addr": str}] — 经过的中间 thunk 列表（不含最终真实函数）
        real_func_ea: 最终真实函数的起始地址，BADADDR 表示追踪失败
    """
    chain = []
    func = ida_funcs.get_func(start_ea)
    if func is None:
        return chain, start_ea

    current_ea = func.start_ea
    visited = set()

    for _ in range(max_depth):
        if current_ea in visited:
            log(f"[!] thunk 追踪检测到循环，停止于 {hex_addr(current_ea)}\n")
            break
        visited.add(current_ea)

        func = ida_funcs.get_func(current_ea)
        if func is None:
            break

        is_thunk = False
        if func.flags & ida_funcs.FUNC_THUNK:
            is_thunk = True
        elif func.size() <= 5:
            targets = list(idautils.CodeRefsFrom(func.start_ea, 0))
            if len(targets) == 1:
                is_thunk = True

        if not is_thunk:
            break

        name = get_func_name_safe(current_ea)
        chain.append({"name": name, "addr": hex_addr(current_ea)})

        targets = list(idautils.CodeRefsFrom(func.start_ea, 0))
        if not targets:
            log(f"[!] thunk 函数 {name} 无跳转目标，停止追踪\n")
            break

        target_ea = targets[0]
        target_func = ida_funcs.get_func(target_ea)
        if target_func is None:
            log(f"[!] thunk 目标 {hex_addr(target_ea)} 不属于任何函数，停止追踪\n")
            break

        current_ea = target_func.start_ea

    if chain:
        log(f"[+] thunk 追踪: {' → '.join(c['name'] for c in chain)} → {get_func_name_safe(current_ea)}\n")

    return chain, current_ea


def read_string_at(ea, max_len=4096):
    """读取 null-terminated 字符串。

    返回:
        {"value": str, "length": int, "addr": str} 或 None（不可读）
    """
    if ea == ida_idaapi.BADADDR:
        return None
    chars = []
    for i in range(max_len):
        b = ida_bytes.get_byte(ea + i)
        if b == 0:
            break
        chars.append(chr(b))
    if not chars:
        return None
    value = "".join(chars)
    return {"value": value, "length": len(value), "addr": hex_addr(ea)}


def read_bytes_at(ea, length):
    """读取原始字节。

    返回:
        {"hex": str, "ascii": str, "length": int, "addr": str}
    """
    raw = []
    ascii_chars = []
    for i in range(length):
        b = ida_bytes.get_byte(ea + i)
        raw.append(f"{b:02X}")
        ascii_chars.append(chr(b) if 32 <= b < 127 else ".")
    return {
        "hex": " ".join(raw),
        "ascii": "".join(ascii_chars),
        "length": length,
        "addr": hex_addr(ea),
    }


def read_pointer(ea):
    """读取指针值（根据数据库位数自适应 4/8 字节）。

    返回:
        {"pointer_value": str, "addr": str}
    """
    try:
        import ida_ida
        bitness = ida_ida.inf_get_app_bitness()
        is_64 = bitness == 64
    except (AttributeError, ImportError):
        is_64 = True
    if is_64:
        ptr = ida_bytes.get_qword(ea)
    else:
        ptr = ida_bytes.get_dword(ea)
    return {"pointer_value": hex_addr(ptr), "addr": hex_addr(ea)}


def _is_plausible_pointer(ptr):
    """判断一个值是否像合法的内存地址指针。"""
    if ptr == 0 or ptr == ida_idaapi.BADADDR:
        return False
    if ptr < 0x10000:
        return False
    return ida_bytes.is_mapped(ptr)


def _is_string_at(ea, min_chars=2):
    """判断地址处是否有可读的字符串（至少 min_chars 个可打印字符 + null 结尾）。"""
    count = 0
    for i in range(4096):
        b = ida_bytes.get_byte(ea + i)
        if b == 0:
            return count >= min_chars
        if b < 32 or b > 126:
            return False
        count += 1
    return count >= min_chars


def read_data_auto(ea, size_hint=256):
    """自动判断数据类型并读取。

    按优先级: string → pointer(解引用) → bytes

    返回:
        dict — 包含 "type" 字段和对应类型的数据
    """
    if ea == ida_idaapi.BADADDR:
        return {"type": "error", "error": "BADADDR", "addr": hex_addr(ea)}

    if _is_string_at(ea):
        log(f"[*] auto 检测: 地址 {hex_addr(ea)} 处为字符串\n")
        result = read_string_at(ea)
        if result:
            result["type"] = "string"
            return result

    ptr_info = read_pointer(ea)
    try:
        ptr_val = int(ptr_info["pointer_value"], 16)
    except ValueError:
        ptr_val = 0

    if _is_plausible_pointer(ptr_val):
        log(f"[*] auto 检测: 地址 {hex_addr(ea)} 处为指针 → {hex_addr(ptr_val)}\n")
        result = {"type": "pointer", "addr": hex_addr(ea), "pointer_value": hex_addr(ptr_val)}
        if _is_string_at(ptr_val):
            deref = read_string_at(ptr_val)
            if deref:
                deref["type"] = "string"
                result["dereferenced"] = deref
            else:
                result["dereferenced"] = None
        else:
            result["dereferenced"] = None
        return result

    log(f"[*] auto 检测: 地址 {hex_addr(ea)} 处为原始字节\n")
    result = read_bytes_at(ea, min(size_hint, 64))
    result["type"] = "bytes"
    return result
