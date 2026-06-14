# -*- coding: utf-8 -*-
"""summary: IDA 调试器脱壳 dump 脚本

description:
  在 IDA 调试器中运行目标程序到 OEP 断点，dump 内存段并重建 PE 文件。
  适用于任何壳（UPX/ASPack/自定义壳），只要壳不检测调试器。

  使用方式（idat headless）：
    IDA_OEP_ADDR=0x401000 IDA_PE_OUTPUT=/tmp/unpacked.exe IDA_OUTPUT=/tmp/result.json \
      idat -A -S"scripts/debug_dump.py" -L/tmp/debug.log target.i64

  环境变量：
    IDA_OEP_ADDR: OEP 地址（十六进制，必填）
    IDA_PE_OUTPUT: PE dump 输出文件路径（可选，缺省从 IDA_OUTPUT 推导）
    IDA_OUTPUT: JSON 结果输出路径（必填，由 run_headless 使用）

level: intermediate
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _base import env_str, log, run_headless

import ida_bytes
import ida_dbg
import ida_ida
import ida_idaapi
import ida_segment


def _load_debugger():
    filetype = ida_ida.inf_get_filetype()
    if filetype == ida_ida.f_PE:
        ida_dbg.load_debugger("win32", 0)
        log("[*] 已加载 win32 调试器插件\n")
        return True
    elif filetype == ida_ida.f_ELF:
        ida_dbg.load_debugger("linux", 0)
        log("[*] 已加载 linux 调试器插件\n")
        return True
    elif filetype == ida_ida.f_MACHO:
        log("[!] Mach-O 格式暂不支持 dump（本轮仅支持 PE/ELF）\n")
    else:
        log(f"[!] 不支持的文件类型: {filetype}\n")
    return False


def _parse_oep_addr(oep_str):
    try:
        return int(oep_str, 16) if oep_str.startswith("0x") or oep_str.startswith("0X") else int(oep_str)
    except ValueError:
        try:
            return int(oep_str, 16)
        except ValueError:
            return ida_idaapi.BADADDR


def _check_mz(addr):
    magic = ida_bytes.get_bytes(addr, 2)
    return magic is not None and magic == b"MZ"


def _detect_image_base():
    """在 refresh_debugger_memory() 之后调用，自动检测 image base。

    检测顺序:
      1. ida_ida.inf_get_baseaddr() — 非零直接返回
      2. 标准加载地址检查（32-bit: 0x400000, 64-bit: 0x140000000）— 检查 MZ 签名
      3. IDA 段数据库降级 — seg = get_first_seg(); if seg: return seg.start_ea

    返回:
      int — image base 地址，BADADDR 表示检测失败
    """
    base = ida_ida.inf_get_baseaddr()
    if base != 0:
        log(f"[+] IDA 返回 image base: 0x{base:X}\n")
        return base

    log("[*] IDA 返回 image base 为 0，尝试自动检测...\n")

    if ida_ida.inf_is_64bit():
        candidates = [0x140000000, 0x400000]
    else:
        candidates = [0x400000, 0x1000000]

    for addr in candidates:
        if _check_mz(addr):
            log(f"[+] 在标准地址检测到 MZ 签名: 0x{addr:X}\n")
            return addr

    seg = ida_segment.get_first_seg()
    if seg is not None:
        log(f"[+] 降级检测: 使用 IDA 段起始地址 0x{seg.start_ea:X}\n")
        return seg.start_ea

    log("[!] 无法检测 image base\n")
    return ida_idaapi.BADADDR


def _dump_segments_from_pe(image_base):
    """从 PE section table 直接读取段数据。

    不依赖 IDA 段数据库。内部自行解析 DOS header → COFF header → section table。

    参数:
        image_base: image base 地址（必须有效，MZ 签名可读）

    返回:
        [(start_ea, bytes)] — 段数据列表，空列表表示失败
    """
    log(f"[*] 从 PE header 读取段数据，image_base=0x{image_base:X}\n")

    dos_header = ida_bytes.get_bytes(image_base, 64)
    if dos_header is None or len(dos_header) < 64 or dos_header[0:2] != b"MZ":
        log("[!] PE header 读取失败: 无效 DOS header\n")
        return []

    e_lfanew = struct.unpack_from("<I", dos_header, 0x3C)[0]
    nt_sig = ida_bytes.get_bytes(image_base + e_lfanew, 4)
    if nt_sig is None or nt_sig != b"PE\x00\x00":
        log("[!] PE header 读取失败: 无效 PE 签名\n")
        return []

    file_header_offset = e_lfanew + 4
    file_header = ida_bytes.get_bytes(image_base + file_header_offset, 20)
    if file_header is None or len(file_header) < 20:
        log("[!] PE header 读取失败: 无法读取 COFF header\n")
        return []

    num_sections = struct.unpack_from("<H", file_header, 2)[0]
    opt_header_size = struct.unpack_from("<H", file_header, 16)[0]

    section_table_rva = file_header_offset + 20 + opt_header_size
    section_table_data = ida_bytes.get_bytes(image_base + section_table_rva, num_sections * 40)
    if section_table_data is None or len(section_table_data) < num_sections * 40:
        log("[!] PE header 读取失败: 无法读取段表\n")
        return []

    seg_data = []
    for i in range(num_sections):
        sec_offset = i * 40
        vsize = struct.unpack_from("<I", section_table_data, sec_offset + 8)[0]
        va = struct.unpack_from("<I", section_table_data, sec_offset + 12)[0]

        if vsize == 0:
            continue

        seg_start = image_base + va
        log(f"[*] 正在 dump PE 段 {i}: 0x{seg_start:X} ({vsize} 字节)\n")
        data = ida_bytes.get_bytes(seg_start, vsize)
        if data is None:
            log(f"[!] 读取 PE 段 {i} 失败: 0x{seg_start:X}\n")
            continue
        seg_data.append((seg_start, data))

    log(f"[+] 从 PE header 读取完成，共 {len(seg_data)} 个段\n")
    return seg_data


def _dump_segments_ida():
    """降级: 使用 IDA 段数据库遍历读取段数据（含 None 检查）。

    返回:
        [(start_ea, bytes)] — 段数据列表，空列表表示失败
    """
    log("[*] 降级: 使用 IDA 段数据库遍历段\n")
    seg = ida_segment.get_first_seg()
    if seg is None:
        log("[!] IDA 段数据库为空（调试器模式下常见）\n")
        return []

    seg_data = []
    while seg is not None and seg.start_ea != ida_idaapi.BADADDR:
        size = seg.end_ea - seg.start_ea
        if size <= 0:
            log(f"[!] 跳过无效段: 0x{seg.start_ea:X} (大小={size})\n")
            seg = ida_segment.get_next_seg(seg.end_ea)
            continue
        log(f"[*] 正在 dump IDA 段: 0x{seg.start_ea:X} - 0x{seg.end_ea:X} ({size} 字节)\n")
        data = ida_bytes.get_bytes(seg.start_ea, size)
        if data is None:
            log(f"[!] 读取段失败: 0x{seg.start_ea:X}\n")
            seg = ida_segment.get_next_seg(seg.end_ea)
            continue
        seg_data.append((seg.start_ea, data))
        seg = ida_segment.get_next_seg(seg.end_ea)
    log(f"[+] IDA 段遍历完成，共 {len(seg_data)} 个段\n")
    return seg_data


def _detect_elf_class(image_base):
    """检测 ELF 文件类别（32-bit 或 64-bit）。

    返回:
        int — 32 或 64，0 表示检测失败
    """
    ident = ida_bytes.get_bytes(image_base, 20)
    if ident is None or len(ident) < 16:
        return 0
    if ident[0:4] != b"\x7fELF":
        return 0
    ei_class = ident[4]
    if ei_class == 1:
        return 32
    elif ei_class == 2:
        return 64
    return 0


def _dump_elf_segments(image_base):
    """从 ELF program header 读取可加载段数据。

    参数:
        image_base: image base 地址

    返回:
        [(start_ea, bytes, vaddr, memsz)] — 段数据列表
    """
    log(f"[*] 从 ELF header 读取段数据，image_base=0x{image_base:X}\n")

    ident = ida_bytes.get_bytes(image_base, 64)
    if ident is None or len(ident) < 16 or ident[0:4] != b"\x7fELF":
        log("[!] ELF header 读取失败: 无效 ELF 魔数\n")
        return []

    ei_class = ident[4]
    is_64 = ei_class == 2

    if is_64:
        e_phoff = struct.unpack_from("<Q", ident, 32)[0]
        e_phentsize = struct.unpack_from("<H", ident, 54)[0]
        e_phnum = struct.unpack_from("<H", ident, 56)[0]
    else:
        e_phoff = struct.unpack_from("<I", ident, 28)[0]
        e_phentsize = struct.unpack_from("<H", ident, 42)[0]
        e_phnum = struct.unpack_from("<H", ident, 44)[0]

    seg_data = []
    for i in range(e_phnum):
        ph_offset = e_phoff + i * e_phentsize
        ph_data = ida_bytes.get_bytes(image_base + ph_offset, e_phentsize)
        if ph_data is None:
            continue

        if is_64:
            p_type = struct.unpack_from("<I", ph_data, 0)[0]
            p_flags = struct.unpack_from("<I", ph_data, 4)[0]
            p_offset = struct.unpack_from("<Q", ph_data, 8)[0]
            p_vaddr = struct.unpack_from("<Q", ph_data, 16)[0]
            p_filesz = struct.unpack_from("<Q", ph_data, 32)[0]
            p_memsz = struct.unpack_from("<Q", ph_data, 40)[0]
        else:
            p_type = struct.unpack_from("<I", ph_data, 0)[0]
            p_offset = struct.unpack_from("<I", ph_data, 4)[0]
            p_vaddr = struct.unpack_from("<I", ph_data, 8)[0]
            p_filesz = struct.unpack_from("<I", ph_data, 16)[0]
            p_memsz = struct.unpack_from("<I", ph_data, 20)[0]

        PT_LOAD = 1
        if p_type != PT_LOAD or p_memsz == 0:
            continue

        seg_start = image_base + p_vaddr
        log(f"[*] 正在 dump ELF LOAD 段 {i}: vaddr=0x{p_vaddr:X} ({p_memsz} 字节)\n")

        data = ida_bytes.get_bytes(seg_start, p_memsz)
        if data is None:
            log(f"[!] 读取 ELF 段 {i} 失败: 0x{seg_start:X}\n")
            continue
        seg_data.append((seg_start, data, p_vaddr, p_memsz))

    log(f"[+] 从 ELF header 读取完成，共 {len(seg_data)} 个 LOAD 段\n")
    return seg_data


def _rebuild_elf(seg_data, image_base, output_path):
    """重建 ELF 文件（简化版: 保留 ELF header + 更新 program headers）。

    参数:
        seg_data: _dump_elf_segments 返回的段数据列表
        image_base: image base 地址
        output_path: 输出文件路径
    """
    log("[*] 开始重建 ELF 文件...\n")

    is_64 = _detect_elf_class(image_base) == 64

    if is_64:
        e_ehsize = 64
        e_phoff = struct.unpack_from("<Q", ida_bytes.get_bytes(image_base, 64), 32)[0]
        e_phentsize = struct.unpack_from("<H", ida_bytes.get_bytes(image_base, 64), 54)[0]
        e_phnum = struct.unpack_from("<H", ida_bytes.get_bytes(image_base, 64), 56)[0]
    else:
        e_ehsize = 52
        e_phoff = struct.unpack_from("<I", ida_bytes.get_bytes(image_base, 52), 28)[0]
        e_phentsize = struct.unpack_from("<H", ida_bytes.get_bytes(image_base, 52), 42)[0]
        e_phnum = struct.unpack_from("<H", ida_bytes.get_bytes(image_base, 52), 44)[0]

    elf_header = bytearray(ida_bytes.get_bytes(image_base, e_ehsize))

    ph_total = e_phnum * e_phentsize
    ph_raw = bytearray(ida_bytes.get_bytes(image_base + e_phoff, ph_total))

    seg_map = {}
    for start_ea, data, vaddr, memsz in seg_data:
        seg_map[vaddr] = data

    header_size = max(e_ehsize, e_phoff + ph_total)
    output = bytearray(header_size)
    header_data = ida_bytes.get_bytes(image_base, header_size)
    if header_data:
        output[0:header_size] = header_data[0:header_size]

    output[e_phoff:e_phoff + ph_total] = ph_raw[0:ph_total]

    for i in range(e_phnum):
        ph_off = i * e_phentsize
        if is_64:
            p_type = struct.unpack_from("<I", ph_raw, ph_off + 0)[0]
            p_vaddr = struct.unpack_from("<Q", ph_raw, ph_off + 16)[0]
            p_filesz = struct.unpack_from("<Q", ph_raw, ph_off + 32)[0]
            p_memsz = struct.unpack_from("<Q", ph_raw, ph_off + 40)[0]
            p_align = struct.unpack_from("<Q", ph_raw, ph_off + 48)[0]
        else:
            p_type = struct.unpack_from("<I", ph_raw, ph_off + 0)[0]
            p_vaddr = struct.unpack_from("<I", ph_raw, ph_off + 8)[0]
            p_filesz = struct.unpack_from("<I", ph_raw, ph_off + 16)[0]
            p_memsz = struct.unpack_from("<I", ph_raw, ph_off + 20)[0]
            p_align = struct.unpack_from("<I", ph_raw, ph_off + 28)[0]

        if p_type != 1 or p_memsz == 0:
            continue

        aligned_filesz = (p_memsz + (p_align - 1)) & ~(p_align - 1) if p_align > 0 else p_memsz

        if p_vaddr in seg_map:
            data = seg_map[p_vaddr]
            copy_size = min(len(data), p_memsz)
            file_offset = len(output)

            if is_64:
                struct.pack_into("<Q", ph_raw, ph_off + 8, file_offset)
                struct.pack_into("<Q", ph_raw, ph_off + 32, copy_size)
            else:
                struct.pack_into("<I", ph_raw, ph_off + 4, file_offset)
                struct.pack_into("<I", ph_raw, ph_off + 16, copy_size)

            output.extend(data[0:copy_size])
            padding = aligned_filesz - copy_size
            if padding > 0:
                output.extend(b"\x00" * padding)
        else:
            log(f"[!] ELF 段 vaddr=0x{p_vaddr:X} 未找到对应内存数据\n")

    output[e_phoff:e_phoff + ph_total] = ph_raw[0:ph_total]

    with open(output_path, "wb") as f:
        f.write(output)

    log(f"[+] ELF 文件已写入: {output_path} ({len(output)} 字节)\n")
    log("[!] 注意: 输出 ELF 不含符号表重建，仅用于 IDA 加载分析\n")
    return True


def _resolve_dump_output():
    """确定 dump 输出文件路径。

    从 IDA_PE_OUTPUT 环境变量读取（兼容旧用法），未设置时从 IDA_OUTPUT 推导。
    根据文件类型自动调整扩展名: PE → .pe，ELF → .elf。

    返回:
        str — dump 输出路径，空字符串表示失败
    """
    dump_output = env_str("IDA_PE_OUTPUT", "")
    if not dump_output:
        json_output = env_str("IDA_OUTPUT", "")
        if not json_output:
            return ""
        base = json_output
        if base.endswith(".json"):
            base = base[:-5]
        filetype = ida_ida.inf_get_filetype()
        if filetype == ida_ida.f_ELF:
            dump_output = base + ".elf"
        else:
            dump_output = base + ".pe"
    return dump_output


def _rebuild_pe(seg_data, image_base, oep_addr, output_path):
    log("[*] 开始重建 PE 文件...\n")

    dos_header_size = 64
    dos_header = ida_bytes.get_bytes(image_base, dos_header_size)
    if dos_header is None or len(dos_header) < dos_header_size:
        log("[!] 无法读取 DOS header\n")
        return False

    if dos_header[0:2] != b"MZ":
        log("[!] 无效的 DOS 签名\n")
        return False

    e_lfanew = struct.unpack_from("<I", dos_header, 0x3C)[0]
    nt_sig = ida_bytes.get_bytes(image_base + e_lfanew, 4)
    if nt_sig is None or nt_sig != b"PE\x00\x00":
        log("[!] 无效的 PE 签名\n")
        return False

    file_header_offset = e_lfanew + 4
    file_header = ida_bytes.get_bytes(image_base + file_header_offset, 20)
    num_sections = struct.unpack_from("<H", file_header, 2)[0]
    opt_header_size = struct.unpack_from("<H", file_header, 16)[0]

    opt_header_offset = file_header_offset + 20
    opt_header = bytearray(ida_bytes.get_bytes(image_base + opt_header_offset, opt_header_size))

    magic = struct.unpack_from("<H", opt_header, 0)[0]
    is_pe32_plus = (magic == 0x20B)
    log(f"[*] PE 格式: {'PE32+' if is_pe32_plus else 'PE32'}，段数: {num_sections}\n")

    if is_pe32_plus:
        entry_point_off = 16
        image_base_off = 24
        image_base_fmt = "<Q"
    else:
        entry_point_off = 16
        image_base_off = 28
        image_base_fmt = "<I"

    oep_rva = oep_addr - image_base
    struct.pack_into("<I", opt_header, entry_point_off, oep_rva & 0xFFFFFFFF)
    log(f"[*] 已修正入口点 RVA: 0x{oep_rva:X}\n")

    section_table_offset = opt_header_offset + opt_header_size
    section_headers = bytearray(ida_bytes.get_bytes(image_base + section_table_offset, num_sections * 40))

    seg_map = {}
    for start_ea, data in seg_data:
        seg_map[start_ea] = data

    total_raw_size = section_table_offset + num_sections * 40
    raw_offset = total_raw_size

    for i in range(num_sections):
        sec_offset = i * 40
        va = struct.unpack_from("<I", section_headers, sec_offset + 12)[0]
        vsize = struct.unpack_from("<I", section_headers, sec_offset + 8)[0]
        raw_size = (vsize + 0x1FF) & ~0x1FF

        struct.pack_into("<I", section_headers, sec_offset + 16, raw_size)
        struct.pack_into("<I", section_headers, sec_offset + 20, raw_offset)

        total_raw_size = raw_offset + raw_size
        raw_offset = total_raw_size

    output = bytearray(total_raw_size)

    header_copy_size = section_table_offset + num_sections * 40
    header_data = ida_bytes.get_bytes(image_base, header_copy_size)
    if header_data:
        output[0:header_copy_size] = header_data[0:header_copy_size]

    output[opt_header_offset:opt_header_offset + opt_header_size] = opt_header[0:opt_header_size]
    output[section_table_offset:section_table_offset + num_sections * 40] = section_headers[0:num_sections * 40]

    for i in range(num_sections):
        sec_offset = i * 40
        va = struct.unpack_from("<I", section_headers, sec_offset + 12)[0]
        vsize = struct.unpack_from("<I", section_headers, sec_offset + 8)[0]
        raw_off = struct.unpack_from("<I", section_headers, sec_offset + 20)[0]
        raw_sz = struct.unpack_from("<I", section_headers, sec_offset + 16)[0]

        seg_start = image_base + va
        if seg_start in seg_map:
            data = seg_map[seg_start]
            copy_size = min(len(data), raw_sz, vsize)
            output[raw_off:raw_off + copy_size] = data[0:copy_size]
        else:
            log(f"[!] 段 {i} (VA=0x{va:X}) 未找到对应内存数据，填充零\n")

    with open(output_path, "wb") as f:
        f.write(output)

    log(f"[+] PE 文件已写入: {output_path} ({len(output)} 字节)\n")
    log(f"[+] 入口点 RVA: 0x{oep_rva:X}，段数: {num_sections}\n")
    log("[!] 注意: 输出 PE 不含 IAT 重建，仅用于 IDA 加载分析\n")
    return True


class DumpHook(ida_dbg.DBG_Hooks):
    def __init__(self, oep_addr, dump_output_path):
        ida_dbg.DBG_Hooks.__init__(self)
        self.oep_addr = oep_addr
        self.dump_output_path = dump_output_path
        self.result = {"success": False, "error": None, "data": None}

    def dbg_run_to(self, pid, tid=0, ea=0):
        ida_dbg.refresh_debugger_memory()
        is_64 = ida_ida.inf_is_64bit()
        pc = ida_dbg.get_reg_val("RIP" if is_64 else "EIP")
        log(f"[*] 断点命中: PC=0x{pc:X}，目标 OEP=0x{self.oep_addr:X}\n")

        if pc != self.oep_addr:
            log("[!] PC 不等于 OEP，继续运行\n")
            ida_dbg.request_continue_process()
            ida_dbg.run_requests()
            return

        image_base = _detect_image_base()
        if image_base == ida_idaapi.BADADDR:
            self.result["error"] = "无法检测 image base"
            ida_dbg.request_exit_process()
            ida_dbg.run_requests()
            return

        log(f"[+] Image Base: 0x{image_base:X}\n")

        filetype = ida_ida.inf_get_filetype()
        is_elf = filetype == ida_ida.f_ELF

        if is_elf:
            seg_data = _dump_elf_segments(image_base)
            if not seg_data:
                seg_data_raw = _dump_segments_ida()
                if seg_data_raw:
                    seg_data = [(ea, d, 0, len(d)) for ea, d in seg_data_raw]
            if not seg_data:
                self.result["error"] = "dump ELF 内存段失败"
                ida_dbg.request_exit_process()
                ida_dbg.run_requests()
                return
            success = _rebuild_elf(seg_data, image_base, self.dump_output_path)
            self.result["success"] = success
            self.result["data"] = {
                "dump_output_path": self.dump_output_path,
                "oep_addr": hex(self.oep_addr),
                "image_base": hex(image_base),
                "segments_dumped": len(seg_data),
                "format": "elf",
            }
            if not success:
                self.result["error"] = "ELF 重建失败"
        else:
            seg_data = _dump_segments_from_pe(image_base)
            if not seg_data:
                seg_data = _dump_segments_ida()
            if not seg_data:
                self.result["error"] = "dump 内存段失败"
                ida_dbg.request_exit_process()
                ida_dbg.run_requests()
                return
            success = _rebuild_pe(seg_data, image_base, self.oep_addr, self.dump_output_path)
            self.result["success"] = success
            self.result["data"] = {
                "dump_output_path": self.dump_output_path,
                "oep_addr": hex(self.oep_addr),
                "image_base": hex(image_base),
                "segments_dumped": len(seg_data),
                "format": "pe",
            }
            if not success:
                self.result["error"] = "PE 重建失败"

        ida_dbg.request_exit_process()
        ida_dbg.run_requests()

    def dbg_process_exit(self, pid, tid, ea, code):
        log(f"[*] 调试进程已退出，退出码: {code}\n")
        return 0


def _main():
    oep_str = env_str("IDA_OEP_ADDR", "")
    dump_output_path = _resolve_dump_output()

    if not oep_str:
        return {"success": False, "error": "未设置 IDA_OEP_ADDR 环境变量", "data": None}
    if not dump_output_path:
        return {"success": False, "error": "IDA_OUTPUT 和 IDA_PE_OUTPUT 均未设置", "data": None}

    oep_addr = _parse_oep_addr(oep_str)
    if oep_addr == ida_idaapi.BADADDR:
        return {"success": False, "error": f"无效的 OEP 地址: {oep_str}", "data": None}

    log(f"[*] OEP: 0x{oep_addr:X}\n")
    log(f"[*] Dump 输出路径: {dump_output_path}\n")

    if not _load_debugger():
        return {"success": False, "error": "调试器加载失败（仅支持 PE/ELF）", "data": None}

    hook = DumpHook(oep_addr, dump_output_path)
    hook.hook()

    log(f"[*] 启动调试器，运行到 OEP: 0x{oep_addr:X}\n")
    ida_dbg.run_to(oep_addr)

    state = ida_dbg.get_process_state()
    while state != 0:
        ida_dbg.wait_for_next_event(1, 0)
        state = ida_dbg.get_process_state()

    hook.unhook()
    return hook.result


run_headless(_main)
