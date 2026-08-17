# -*- coding: utf-8 -*-
"""summary: 一键初始分析流水线

description:
  在单次 idat 调用内完成信息收集和场景分类，替代多次独立 query.py 调用。
  输出结构化 JSON，包含：segments、entry_points、imports、strings、packer_detect、
  以及自动生成的场景分类建议和推荐下一步操作。

  使用方式（idat headless）：
    IDA_OUTPUT=$TASK_DIR/<初始分析结果>.json \
      idat -A -S"scripts/initial_analysis.py" -L$TASK_DIR/<初始分析日志>.log target.i64

  环境变量：
    IDA_OUTPUT: 输出文件路径（必填）
    IDA_STRINGS_PATTERN: 可选，过滤字符串的子串模式（默认返回全部）
    IDA_MAX_STRINGS: 可选，最大字符串数量（默认 200）

level: intermediate
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _base import env_int, env_str, log, run_headless
from _analysis import (
    collect_entry_points,
    collect_imports,
    collect_segments,
    collect_strings,
    detect_packer,
)

import ida_funcs


def _main():
    segments, packer_name_from_seg, packer_conf = collect_segments()
    entries, file_type, architecture, bits = collect_entry_points()
    modules, total_functions, _ = collect_imports()

    func_count = ida_funcs.get_func_qty()
    packer_info = detect_packer(segments, packer_name_from_seg, entries, total_functions)

    # 加壳二进制字符串降噪: 壳代码中的字符串多为乱码，减少数量节省上下文
    pattern = env_str("IDA_STRINGS_PATTERN", "")
    max_strings = env_int("IDA_MAX_STRINGS", 200)
    strings_reduced = False
    if packer_info["packer_detected"] and func_count <= 5 and not pattern:
        max_strings = 20
        strings_reduced = True
        log(f"[+] 加壳检测: 字符串数量限制为 {max_strings}（原始默认 200）\n")
    strings = collect_strings(pattern, max_strings)

    log("[+] 初始分析流水线完成\n")

    return {
        "success": True,
        "data": {
            "segments": {
                "description": "内存段列表。用法：段名异常（UPX0/Themida 等）是加壳信号；kernel_driver 场景查 .data/.rdata 定位常量",
                "list": segments,
                "total": len(segments),
            },
            "entry_points": {
                "description": "入口点与目标形态。用法：file_type/architecture/bits 决定后续脚本的平台分支（如 arm64 .so 走字符串引用定位法）",
                "entries": entries,
                "file_type": file_type,
                "architecture": architecture,
                "bits": bits,
                "total": len(entries),
            },
            "imports": {
                "description": "导入表（modules[].functions[] 含完整函数名）。场景判断主信号：内核 API（IoCreateDevice/WdfDriverCreate/FltRegisterFilter）→ kernel_driver；CreateWindow/DialogBox/MessageBox → gui；CryptEncrypt/BCrypt/hash 类符号 → crypto。JNI 场景查 Java_ 开头导出定位 native 方法",
                "modules": modules,
                "total_functions": total_functions,
            },
            "strings": {
                "description": "字符串列表。场景判断信号：算法名/特征常量（AES S-box、ChaCha 'expand 32-byte k'、hex/base64 表）→ crypto；'Wrong/Correct/flag' 类提示 → 定位比较逻辑的 xrefs 锚点",
                "list": strings,
                "total": len(strings),
                "pattern": pattern,
            },
            "packer_detect": {
                "description": "加壳检测结论（detect_packer 的数百特征匹配）。packer_detected=true → packed 场景，先脱壳再分析（方案见 analysis-planning.md）",
                **packer_info,
            },
            "strings_reduced": strings_reduced,
            "stats": {
                "description": "规模统计。function_count≤5 且 packer_detected=true → 典型加壳形态（字符串已自动降噪到 20 条）",
                "function_count": func_count,
                "segment_count": len(segments),
                "import_count": total_functions,
                "string_count": len(strings),
                "entry_point_count": len(entries),
            },
        },
        "error": None,
    }


run_headless(_main)
