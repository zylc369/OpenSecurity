# -*- coding: utf-8 -*-
"""summary: BinaryAnalysis 共享分析逻辑模块

description:
  提供 query.py 和 scripts/initial_analysis.py 共享的分析函数，包括：
  1. collect_segments() — 段信息收集 + 壳段名检测
  2. collect_entry_points() — 入口点枚举 + 架构/位数识别
  3. collect_imports() — 导入表枚举
  4. collect_strings() — 字符串搜索
  5. detect_packer() — 加壳/混淆检测
  6. classify_scene() — 场景分类（仅 initial_analysis 使用）

  依赖关系: _base.py → _utils.py → _analysis.py → query.py / scripts/initial_analysis.py
  本模块不含 run_headless() 调用，可安全被其他模块 import。

level: intermediate
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import log
from _utils import (
    _PACKER_SEGMENT_PATTERNS,
    estimate_entropy,
    get_func_name_safe,
    hex_addr,
    seg_perm_str,
)

import ida_bytes
import ida_entry
import ida_funcs
import ida_ida
import ida_loader
import ida_nalt
import ida_segment
import idautils


def collect_segments():
    """收集段信息，检测壳段名异常。

    返回:
        (seg_list, packer_name, packer_confidence)
        seg_list: [{"name", "start", "end", "size", "perm", "anomaly_hints"}]
        packer_name: 检测到的壳名或 None
        packer_confidence: "high"/"none"
    """
    log("[*] 正在收集段信息...\n")
    seg_list = []
    packer_name = None
    packer_confidence = "none"
    total_size = 0

    qty = ida_segment.get_segm_qty()
    for i in range(qty):
        seg = ida_segment.getnseg(i)
        if seg is None:
            continue
        total_size += seg.end_ea - seg.start_ea

    for i in range(qty):
        seg = ida_segment.getnseg(i)
        if seg is None:
            continue
        name = ida_segment.get_segm_name(seg)
        size = seg.end_ea - seg.start_ea
        anomaly_hints = []

        name_upper = name.upper()
        for packer, patterns in _PACKER_SEGMENT_PATTERNS.items():
            for pat in patterns:
                if name_upper == pat.upper() or name_upper.startswith(pat.upper()):
                    anomaly_hints.append(f"known_packer_segment:{packer}")
                    if packer_confidence != "high":
                        packer_name = packer
                        packer_confidence = "high"
                    break

        if total_size > 0 and size > total_size * 0.9:
            anomaly_hints.append("oversized_segment")

        seg_type = ""
        try:
            seg_type = ida_segment.segm_class(seg)
        except Exception:
            pass

        seg_list.append({
            "name": name,
            "start": hex_addr(seg.start_ea),
            "end": hex_addr(seg.end_ea),
            "size": size,
            "type": seg_type,
            "perm": seg_perm_str(seg.perm),
            "anomaly_hints": anomaly_hints,
        })

    log(f"[+] 段信息收集完成: {len(seg_list)} 个段\n")
    return seg_list, packer_name, packer_confidence


def collect_entry_points():
    """枚举入口点，识别架构和文件类型。

    返回:
        (entries, file_type, architecture, bits)
    """
    log("[*] 正在收集入口点...\n")
    entries = []
    seen = set()

    proc_name = ida_ida.inf_get_procname()
    arch_map = {
        "metapc": "x86",
        "ARM": "arm",
        "ARM64": "arm64",
        "aarch64": "arm64",
    }
    architecture = arch_map.get(proc_name, proc_name)

    bits = None
    if architecture == "x86":
        if ida_ida.inf_is_64bit():
            bits = 64
        elif ida_ida.inf_is_32bit_exactly():
            bits = 32
        else:
            bits = 16
    elif architecture == "arm64":
        bits = 64
    elif architecture == "arm":
        bits = 32

    file_type_name = ""
    try:
        file_type_name = ida_loader.get_file_type_name().lower()
    except Exception:
        pass

    if "dll" in file_type_name or "dynamic link library" in file_type_name:
        file_type = "dll"
    elif "shared object" in file_type_name or "elf" in file_type_name:
        file_type = "so"
    elif "pe" in file_type_name or "executable" in file_type_name or "coff" in file_type_name:
        file_type = "exe"
    elif "mach-o" in file_type_name:
        file_type = "macho"
    else:
        file_type = "unknown"

    qty = ida_entry.get_entry_qty()
    for i in range(qty):
        ordinal = ida_entry.get_entry_ordinal(i)
        addr = ida_entry.get_entry(ordinal)
        if addr in seen:
            continue
        seen.add(addr)
        name = ida_entry.get_entry_name(ordinal)
        if not name:
            name = f"entry_{ordinal}"

        name_lower = name.lower()
        if name_lower in ("_init", "init", ".init"):
            etype = "init"
        elif name_lower in ("_fini", "fini", ".fini"):
            etype = "fini"
        elif name.startswith("."):
            etype = "init_array"
        elif name_lower in ("main", "_main", "wmain", "winmain", "wwinmain",
                            "dllmain", "driverentry"):
            etype = "main"
        elif "jni" in name_lower:
            etype = "jni"
        elif name_lower in ("_start", "start"):
            etype = "crt_entry"
        else:
            etype = "entry"

        func = ida_funcs.get_func(addr)
        entries.append({
            "name": name,
            "addr": hex_addr(addr),
            "type": etype,
            "ordinal": ordinal,
            "size": func.size() if func else 0,
        })

    if file_type in ("dll", "so"):
        for ea in idautils.Functions():
            if ea in seen:
                continue
            name = get_func_name_safe(ea)
            is_export = ida_bytes.is_mapped(ea) and name and not name.startswith("sub_")
            if not is_export:
                continue
            seen.add(ea)
            func = ida_funcs.get_func(ea)
            entries.append({
                "name": name,
                "addr": hex_addr(ea),
                "type": "export",
                "ordinal": -1,
                "size": func.size() if func else 0,
            })

    log(f"[+] 入口点收集完成: {len(entries)} 个\n")
    return entries, file_type, architecture, bits


def collect_imports():
    """枚举导入表。

    返回:
        (modules, total_functions, import_names_set)
    """
    log("[*] 正在收集导入表...\n")
    modules = []
    total_functions = 0
    import_names_set = set()

    def _enum_module(idx):
        mod_name = ida_nalt.get_import_module_name(idx)
        if not mod_name:
            mod_name = f"module_{idx}"
        funcs = []

        def _import_cb(ea, name, ordinal):
            actual_name = name if name else f"ord_{ordinal}"
            funcs.append({"name": actual_name, "addr": hex_addr(ea), "ordinal": ordinal})
            import_names_set.add(actual_name)
            return True

        ida_nalt.enum_import_names(idx, _import_cb)
        if funcs:
            return {"module": mod_name, "functions": funcs, "count": len(funcs)}, len(funcs)
        return None, 0

    qty = ida_nalt.get_import_module_qty()
    for i in range(qty):
        entry, count = _enum_module(i)
        if entry:
            modules.append(entry)
            total_functions += count

    log(f"[+] 导入表收集完成: {len(modules)} 个模块, {total_functions} 个函数\n")
    return modules, total_functions, import_names_set


def collect_strings(pattern="", max_count=200):
    """搜索字符串及其引用位置。

    参数:
        pattern: 子串匹配模式（空=全部）
        max_count: 最大返回数量

    返回:
        strings_list: [{"value", "addr", "length", "xrefs"}]
    """
    log(f"[*] 正在收集字符串 (pattern='{pattern}', max={max_count})...\n")
    strings_list = []
    for s in idautils.Strings(False):
        if len(strings_list) >= max_count:
            break
        value = str(s)
        if pattern and pattern.lower() not in value.lower():
            continue
        ea = s.ea
        xrefs = []
        for xref in idautils.XrefsTo(ea, 0):
            func_name = get_func_name_safe(xref.frm)
            xrefs.append({"from": hex_addr(xref.frm), "func": func_name})
            if len(xrefs) >= 10:
                break
        strings_list.append({
            "value": value,
            "addr": hex_addr(ea),
            "length": len(value),
            "xrefs": xrefs,
        })

    log(f"[+] 字符串收集完成: {len(strings_list)} 个\n")
    return strings_list


def detect_packer(segments, packer_name_from_seg, entry_points, import_count):
    """加壳/混淆检测（多维信号分析）。

    参数:
        segments: collect_segments() 返回的段列表
        packer_name_from_seg: collect_segments() 返回的壳名
        entry_points: collect_entry_points() 返回的入口列表
        import_count: 导入函数总数

    返回:
        {"packer_detected", "confidence", "packer_name", "signals"}
    """
    log("[*] 正在执行加壳检测...\n")
    signals = []

    if packer_name_from_seg:
        signals.append({
            "type": "segment_name_match",
            "detail": f"已知壳段名: {packer_name_from_seg}",
            "weight": "high",
        })

    func_count = ida_funcs.get_func_qty()
    ep_count = len(entry_points)
    if func_count <= 2 and ep_count > 0:
        signals.append({
            "type": "function_count",
            "detail": f"仅 {func_count} 个函数但存在 {ep_count} 个入口点",
            "weight": "high",
        })
    elif func_count <= 5 and ep_count > 0:
        signals.append({
            "type": "function_count",
            "detail": f"仅 {func_count} 个函数",
            "weight": "medium",
        })

    if import_count == 0:
        signals.append({
            "type": "import_count",
            "detail": "无导入函数",
            "weight": "high",
        })
    elif import_count <= 3:
        signals.append({
            "type": "import_count",
            "detail": f"仅 {import_count} 个导入函数",
            "weight": "medium",
        })

    for seg in segments:
        if seg["size"] >= 64:
            ea = int(seg["start"], 16)
            entropy = estimate_entropy(ea, seg["size"])
            if entropy > 7.0:
                signals.append({
                    "type": "high_entropy",
                    "detail": f"段 {seg['name']} 熵={entropy:.2f}",
                    "weight": "medium",
                })

    high_count = sum(1 for s in signals if s["weight"] == "high")
    medium_count = sum(1 for s in signals if s["weight"] == "medium")

    if packer_name_from_seg:
        confidence = "high"
        detected_name = packer_name_from_seg
    elif high_count >= 2:
        confidence = "high"
        detected_name = "unknown"
    elif high_count >= 1 and medium_count >= 1:
        confidence = "medium"
        detected_name = "unknown"
    elif medium_count >= 2:
        confidence = "low"
        detected_name = "unknown"
    else:
        confidence = "none"
        detected_name = None

    packer_detected = confidence in ("high", "medium")

    if packer_detected:
        log(f"[+] 加壳检测: 已检测到加壳 (置信度={confidence}, 壳={detected_name})\n")
    else:
        log("[+] 加壳检测: 未检测到加壳\n")

    return {
        "packer_detected": packer_detected,
        "confidence": confidence,
        "packer_name": detected_name,
        "signals": signals,
    }


def classify_scene(packer_info, strings, import_names, architecture, file_type, packages=None):
    """场景分类 — 根据 packer/crypto/GUI 等信号生成场景标签和推荐操作。

    参数:
        packer_info: detect_packer() 返回的字典
        strings: collect_strings() 返回的列表
        import_names: collect_imports() 返回的名称集合
        architecture: 架构字符串
        file_type: 文件类型字符串
        packages: detect_env.py 输出的 data.packages 字典（可选）
                  {"frida": {"available": True/False, ...}, ...}

    返回:
        {"scene_tags", "recommended_actions", "knowledge_base_loads",
         "crypto_signals", "gui_indicators", "error_strings_count"}
    """
    log("[*] 正在进行场景分类...\n")
    scene_tags = []
    recommended_actions = []
    knowledge_base_loads = []

    # 内核驱动检测（优先级最高: .sys 文件的 file_type 为 "exe"，不能靠 file_type 区分，
    # 通过导入的内核驱动特有 API 识别）
    _kernel_driver_apis = {
        "IoCreateDevice", "IofCompleteRequest", "IoCreateSymbolicLink",
        "IoDeleteDevice", "IoDeleteSymbolicLink",
    }
    _kernel_match = _kernel_driver_apis & import_names
    if len(_kernel_match) >= 2:
        scene_tags.append("kernel_driver")
        recommended_actions.append({
            "action": "kernel_driver_analysis",
            "priority": 0,
            "description": "检测到 Windows 内核驱动，需使用双机调试分析",
            "detail": f"内核驱动 API: {sorted(_kernel_match)}",
        })
        knowledge_base_loads.append("kernel-driver-analysis.md")

    if packer_info["packer_detected"]:
        scene_tags.append("packed")
        recommended_actions.append({
            "action": "unpack",
            "priority": 1,
            "description": "二进制已加壳，优先脱壳",
            "detail": f"壳类型: {packer_info.get('packer_name', 'unknown')}，置信度: {packer_info['confidence']}",
        })
        knowledge_base_loads.append("packer-handling.md")

    crypto_signals = []
    string_values = " ".join(s["value"] for s in strings)
    if "0123456789ABCDEF" in string_values or "0123456789abcdef" in string_values:
        crypto_signals.append("hex_table")
    if "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" in string_values:
        crypto_signals.append("base64_table")

    # 增强: 通过字符串值检测算法名称（排除易误报的短词如 des/cast/idea，
    # 它们由下方 import 函数名通道覆盖）
    crypto_algo_keywords = ["md5", "sha", "sha1", "sha256", "sha512", "aes", "rc4",
                            "rc2", "blowfish", "twofish", "chacha", "salsa", "serpent",
                            "camellia", "rsa", "ecc", "ecdsa"]
    string_values_lower = string_values.lower()
    for kw in crypto_algo_keywords:
        if kw in string_values_lower and kw not in crypto_signals:
            crypto_signals.append(f"algo_name:{kw}")

    # 增强: 通过导入函数名检测密码学 API（"des" 已移除，由 "decrypt"/"encrypt" 覆盖，
    # 避免匹配 DestroyWindow 等常见非密码学导入）
    crypto_import_patterns = ["crypt", "hash", "md5", "sha", "aes", "rsa",
                              "cipher", "encrypt", "decrypt", "digest", "sign", "verify"]
    crypto_imports = []
    for name in import_names:
        name_lower = name.lower()
        if any(kw in name_lower for kw in crypto_import_patterns):
            crypto_imports.append(name)

    if crypto_signals or crypto_imports:
        scene_tags.append("crypto")
        recommended_actions.append({
            "action": "crypto_analysis",
            "priority": 2 if "packed" not in scene_tags else 3,
            "description": "检测到密码学特征，加载密码学识别文档",
            "detail": f"信号: {crypto_signals + crypto_imports}",
        })
        knowledge_base_loads.append("crypto-validation-patterns.md")

    gui_indicators = []
    for name in import_names:
        if any(kw in name for kw in [
            "CreateWindow", "DialogBox", "MessageBox", "SetDlgItemText",
            "GetDlgItemText", "ShowWindow", "SendMessage", "PostMessage",
        ]):
            gui_indicators.append(name)

    if gui_indicators:
        scene_tags.append("gui")
        frida_available = packages.get("frida", {}).get("available", False) if packages else False
        recommended_actions.append({
            "action": "gui_interaction",
            "priority": 2 if "packed" not in scene_tags else 4,
            "description": "检测到 GUI 程序，可能需要动态交互",
            "detail": f"GUI API: {gui_indicators[:10]}",
            "frida_available": frida_available,
        })
        knowledge_base_loads.append("dynamic-analysis.md")
        if frida_available:
            knowledge_base_loads.append("dynamic-analysis-frida.md")

    error_strings = [s for s in strings if any(
        kw in s["value"].lower()
        for kw in ["error", "fail", "wrong", "invalid", "incorrect", "denied"]
    )]
    if error_strings:
        recommended_actions.append({
            "action": "error_message_analysis",
            "priority": 2 if "packed" not in scene_tags else 3,
            "description": "发现错误提示字符串，可用于定位关键比较逻辑",
            "detail": f"示例: {[s['value'][:50] for s in error_strings[:5]]}",
        })

    if not scene_tags:
        scene_tags.append("standard")

    recommended_actions.sort(key=lambda a: a["priority"])

    log(f"[+] 场景分类: {scene_tags}\n")
    log(f"[+] 推荐操作数: {len(recommended_actions)}\n")

    return {
        "scene_tags": scene_tags,
        "recommended_actions": recommended_actions,
        "knowledge_base_loads": list(dict.fromkeys(knowledge_base_loads)),
        "crypto_signals": crypto_signals,
        "gui_indicators": gui_indicators,
        "error_strings_count": len(error_strings),
    }
