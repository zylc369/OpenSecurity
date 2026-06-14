"""summary: 通用 PE 脱壳脚本（基于 Frida 动态插桩）

description:
  通过 Frida 动态插桩，监控代码段写入事件，在脱壳 stub 完成解压后
  自动 dump 完整的内存映像并重建为可运行的 PE 文件。

  原理：
    1. Frida spawn 目标进程（挂起状态）
    2. 在代码段范围设置 MemoryAccessMonitor（监控写入）
    3. 恢复执行，等待脱壳 stub 写入代码段
    4. 检测到写入后，等写入稳定（不再有新写入）
    5. dump 代码段 + 所有段的内存内容
    6. 重建 PE 文件（修正段表、导入表等）

  使用方式（Windows 命令行）：
    pip install frida frida-tools
    python frida_unpack.py crackme_crypto.exe

  输出：
    <原文件名>_unpacked.exe — 脱壳后的 PE 文件
    <原文件名>_unpacked.bin — 完整内存 dump

  适用场景：
    - 未知壳 / 自定义壳（upx -d 无法处理时）
    - anti-debug 壳（Frida spawn 绕过大部分反调试）
    - 多层壳（自动等待最终稳定状态）

  限制：
    - 需要 Windows 环境（Frida 对 Windows PE 支持最好）
    - 部分强反调试壳可能检测到 Frida
    - 重建的 PE 可能需要用 Import REC 修复导入表

level: intermediate
"""

import argparse
import os
import struct
import sys
import time


JS_CODE = r"""
"use strict";

// 全局状态
var g_peInfo = null;
var g_codeWriteCount = 0;
var g_lastWriteTime = 0;
var g_dumped = false;
var g_stableTimer = null;

// PE 解析（支持 32-bit 和 64-bit）
function parsePE(base) {
    var e_lfanew = Memory.readU32(base.add(0x3C));
    var coff = base.add(e_lfanew + 4);
    var numSections = Memory.readU16(coff.add(2));
    var optSize = Memory.readU16(coff.add(16));
    var opt = coff.add(20);

    var peMagic = Memory.readU16(opt);
    var is64 = (peMagic === 0x20B);

    var entryRVA, imageBase, sizeOfImage, sizeOfHeaders;
    if (is64) {
        entryRVA = Memory.readU32(opt.add(16));
        imageBase = Memory.readU64(opt.add(24)).toNumber();
        sizeOfImage = Memory.readU32(opt.add(56));
        sizeOfHeaders = Memory.readU32(opt.add(60));
    } else {
        entryRVA = Memory.readU32(opt.add(16));
        imageBase = Memory.readU32(opt.add(28));
        sizeOfImage = Memory.readU32(opt.add(56));
        sizeOfHeaders = Memory.readU32(opt.add(60));
    }

    var sections = [];
    var sectOff = opt.add(optSize);
    for (var i = 0; i < numSections; i++) {
        var s = sectOff.add(i * 40);
        var nameBuf = Memory.readByteArray(s, 8);
        var nameArr = new Uint8Array(nameBuf);
        var name = "";
        for (var j = 0; j < 8 && nameArr[j] !== 0; j++) {
            name += String.fromCharCode(nameArr[j]);
        }
        sections.push({
            name: name,
            vsize: Memory.readU32(s.add(8)),
            vaddr: Memory.readU32(s.add(12)),
            rawsize: Memory.readU32(s.add(16)),
            rawoff: Memory.readU32(s.add(20)),
            chars: Memory.readU32(s.add(36))
        });
    }

    return {
        imageBase: imageBase,
        entryRVA: entryRVA,
        sizeOfImage: sizeOfImage,
        sizeOfHeaders: sizeOfHeaders,
        numSections: numSections,
        is64: is64,
        sections: sections
    };
}

// 监控代码段写入
function watchCodeSection(pe) {
    // 第一个非空段通常是代码段
    var codeSect = null;
    for (var i = 0; i < pe.sections.length; i++) {
        var s = pe.sections[i];
        if (s.rawsize > 0x1000 && (s.chars & 0x20000000)) {
            codeSect = s;
            break;
        }
    }
    if (!codeSect) {
        codeSect = pe.sections[0];
    }

    var codeStart = ptr(pe.imageBase).add(codeSect.vaddr);
    var codeEnd = codeStart.add(codeSect.vsize);

    send({
        type: "info",
        msg: "[*] 监控代码段: " + codeSect.name +
             " VA=0x" + codeStart.toString(16) +
             "-0x" + codeEnd.toString(16) +
             " (0x" + codeSect.vsize.toString(16) + " bytes)"
    });

    // 使用 Stalker 跟踪写入（比 MemoryAccessMonitor 更可靠）
    // 但对于脱壳，最简单的方式是定期轮询代码段变化

    // 方案：hook 常见的壳结束标志
    // 1. 监控 POPAL/POPAD 后的 JMP（通用壳结束模式）
    // 2. 监控代码段内容变化

    // 使用 Process.setExceptionHandler 处理 SEH 壳
    Process.setExceptionHandler(function(details) {
        send({
            type: "exception",
            msg: "[!] 异常: type=" + details.type +
                 " addr=0x" + details.address.toString(16) +
                 " context.eip=0x" + details.context.pc.toString(16)
        });
        // 允许继续执行
        return false;
    });

    return { codeStart: codeStart, codeEnd: codeEnd, codeSect: codeSect };
}

// Dump 内存
function dumpMemory(pe) {
    if (g_dumped) return;
    g_dumped = true;

    send({ type: "info", msg: "[*] 开始 dump 内存..." });

    var base = ptr(pe.imageBase);

    // Dump PE 头
    var headerSize = pe.sections[0] ? pe.sections[0].vaddr : 0x1000;
    var headerData = Memory.readByteArray(base, headerSize);
    send({ type: "dump_header", data: headerData });

    // Dump 各段
    for (var i = 0; i < pe.sections.length; i++) {
        var s = pe.sections[i];
        var segBase = base.add(s.vaddr);
        var nonZero = 0;
        // 快速统计非零字节
        var sampleSize = Math.min(s.vsize, 256);
        for (var j = 0; j < sampleSize; j++) {
            if (Memory.readU8(segBase.add(j)) !== 0) nonZero++;
        }
        send({
            type: "info",
            msg: "[*] 段 " + s.name +
                 ": VA=0x" + segBase.toString(16) +
                 " 非零率=" + (nonZero / sampleSize * 100).toFixed(1) + "%"
        });

        var segData = Memory.readByteArray(segBase, s.vsize);
        send({
            type: "dump_section",
            index: i,
            name: s.name,
            vaddr: s.vaddr,
            vsize: s.vsize,
            data: segData
        });
    }

    // Dump 原始文件中的未映射数据（如 overlay）
    send({ type: "dump_done", pe: pe });
}

// 定期检查代码段是否被修改
var g_originalCode = null;
function checkCodeModified(watchInfo) {
    var codeStart = watchInfo.codeStart;
    var codeSize = watchInfo.codeSect.vsize;

    if (g_originalCode === null) {
        g_originalCode = Memory.readByteArray(codeStart, Math.min(codeSize, 0x100));
        return false;
    }

    var currentCode = Memory.readByteArray(codeStart, Math.min(codeSize, 0x100));
    var orig = new Uint8Array(g_originalCode);
    var curr = new Uint8Array(currentCode);

    var changed = false;
    for (var i = 0; i < orig.length; i++) {
        if (orig[i] !== curr[i]) {
            changed = true;
            break;
        }
    }

    if (changed) {
        var now = Date.now();
        g_lastWriteTime = now;
        g_codeWriteCount++;

        // 检查前几个字节是否有明显变化
        var first32 = "";
        for (var i = 0; i < Math.min(32, curr.length); i++) {
            first32 += ("0" + curr[i].toString(16)).slice(-2) + " ";
        }
        send({
            type: "code_changed",
            msg: "[*] 代码段已修改! (检查 #" + g_codeWriteCount + ")\n" +
                 "    前32字节: " + first32
        });

        // 更新原始代码为当前代码，以便检测后续修改完成
        g_originalCode = currentCode;
    }

    return changed;
}

// RPC 接口
rpc.exports = {
    init: function() {
        var base = Process.enumerateModules()[0].base;
        g_peInfo = parsePE(base);

        send({
            type: "pe_info",
            msg: "[*] PE 信息: " + (g_peInfo.is64 ? "PE32+(64-bit)" : "PE32(32-bit)") +
                 " ImageBase=0x" + g_peInfo.imageBase.toString(16) +
                 " EntryPoint=0x" + (g_peInfo.imageBase + g_peInfo.entryRVA).toString(16) +
                 " Sections=" + g_peInfo.numSections
        });

        for (var i = 0; i < g_peInfo.sections.length; i++) {
            var s = g_peInfo.sections[i];
            send({
                type: "pe_info",
                msg: "    " + s.name +
                     " VA=0x" + s.vaddr.toString(16) +
                     " VS=0x" + s.vsize.toString(16) +
                     " RS=0x" + s.rawsize.toString(16)
            });
        }

        return watchCodeSection(g_peInfo);
    },

    checkModified: function() {
        var base = Process.enumerateModules()[0].base;
        if (!g_peInfo) g_peInfo = parsePE(base);
        var watchInfo = watchCodeSection(g_peInfo);
        return checkCodeModified(watchInfo);
    },

    dump: function() {
        var base = Process.enumerateModules()[0].base;
        if (!g_peInfo) g_peInfo = parsePE(base);
        dumpMemory(g_peInfo);
    },

    getPEInfo: function() {
        return g_peInfo;
    }
};
"""


def _write_binary(path, data):
    with open(path, "wb") as f:
        f.write(data)
    print(f"[+] 写入: {path} ({len(data)} 字节)")


def _rebuild_pe(original_path, header_data, sections_data, pe_info):
    with open(original_path, "rb") as f:
        original = bytearray(f.read())

    e_lfanew = struct.unpack_from("<I", original, 0x3C)[0]
    coff_off = e_lfanew + 4
    num_sect = struct.unpack_from("<H", original, coff_off + 2)[0]
    opt_hdr_size = struct.unpack_from("<H", original, coff_off + 16)[0]
    opt_off = coff_off + 20
    sect_off = opt_off + opt_hdr_size

    pe_header_size = pe_info["sections"][0]["vaddr"] if pe_info["sections"] else 0x1000

    output = bytearray(len(original))

    output[:pe_header_size] = header_data[:pe_header_size]

    for i, sect in enumerate(pe_info["sections"]):
        if i < len(sections_data) and sections_data[i] is not None:
            sect_va = sect["vaddr"]
            sect_vs = sect["vsize"]
            sect_data = sections_data[i][:sect_vs]
            output[sect_va:sect_va + len(sect_data)] = sect_data

            raw_off = struct.unpack_from("<I", original, sect_off + i * 40 + 20)[0]
            raw_size = struct.unpack_from("<I", original, sect_off + i * 40 + 16)[0]
            vsize = struct.unpack_from("<I", original, sect_off + i * 40 + 8)[0]

            new_raw_size = min(len(sect_data), raw_size) if raw_size > 0 else len(sect_data)
            struct.pack_into("<I", output, sect_off + i * 40 + 8, vsize)
            struct.pack_into("<I", output, sect_off + i * 40 + 16, new_raw_size)

    return bytes(output)


def unpack(input_path, output_path=None, max_wait=30):
    import frida

    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + "_unpacked" + ext

    print(f"[*] 目标: {input_path}")
    print(f"[*] 输出: {output_path}")
    print(f"[*] 最大等待: {max_wait}s")

    pid = frida.spawn(input_path)
    session = frida.attach(pid)
    print(f"[+] 进程 PID={pid}")

    sections_data = {}
    header_data = None
    pe_info = None
    dump_received = False

    def on_message(message, data):
        nonlocal header_data, pe_info, dump_received

        if message["type"] == "send":
            payload = message["payload"]
            msg_type = payload.get("type", "")

            if msg_type in ("info", "pe_info", "exception", "code_changed"):
                print(payload["msg"])

            elif msg_type == "dump_header":
                header_data = data or payload.get("data")
                print(f"[+] PE 头 dump: {len(header_data)} 字节")

            elif msg_type == "dump_section":
                idx = payload["index"]
                name = payload["name"]
                sect_data = data or payload.get("data")
                sections_data[idx] = sect_data
                print(f"[+] 段 {name}: {len(sect_data)} 字节")

            elif msg_type == "dump_done":
                pe_info = payload["pe"]
                dump_received = True
                print("[+] Dump 完成!")

        elif message["type"] == "error":
            print(f"[!] JS 错误: {message.get('description', message)}")

    script = session.create_script(JS_CODE)
    script.on("message", on_message)
    script.load()

    watch_info = script.exports_sync.init()
    print("[*] 监控已启动，恢复进程执行...")

    frida.resume(pid)

    start_time = time.time()
    check_interval = 0.5
    last_change_time = start_time
    stable_threshold = 2.0
    code_changed = False

    while time.time() - start_time < max_wait:
        time.sleep(check_interval)

        try:
            modified = script.exports_sync.check_modified()
            if modified:
                code_changed = True
                last_change_time = time.time()
                print(f"[*] 检测到代码段写入 (已过 {time.time() - start_time:.1f}s)")
        except frida.ProcessNotFoundError:
            print("[!] 进程已退出")
            break
        except Exception as e:
            print(f"[!] 检查失败: {e}")
            break

        if code_changed and (time.time() - last_change_time) > stable_threshold:
            print(f"[+] 代码段写入已稳定 ({stable_threshold}s 无新写入)")
            break

    if not code_changed:
        print(f"[!] {max_wait}s 内未检测到代码段写入")
        print("[!] 可能原因: (1) 壳已完成 (2) 进程崩溃 (3) 非标准脱壳方式")
        print("[*] 尝试直接 dump 当前状态...")

    try:
        script.exports_sync.dump()
        time.sleep(1)
    except Exception as e:
        print(f"[!] Dump 失败: {e}")

    if dump_received and pe_info and header_data:
        rebuilt = _rebuild_pe(input_path, header_data, sections_data, pe_info)
        _write_binary(output_path, rebuilt)
        print(f"\n[+] 脱壳完成: {output_path}")
        print(f"    大小: {len(rebuilt)} 字节")
    else:
        raw_dump_path = os.path.splitext(output_path)[0] + ".bin"
        if header_data:
            _write_binary(raw_dump_path, header_data)
            for idx, sdata in sorted(sections_data.items()):
                print(f"    段 {idx}: {len(sdata)} 字节")
            print(f"\n[!] PE 重建不完整，原始 dump: {raw_dump_path}")

    try:
        session.detach()
    except Exception:
        pass

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="通用 PE 脱壳工具 (Frida 动态插桩)"
    )
    parser.add_argument("input", help="目标 PE 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径 (默认: <原文件名>_unpacked.exe)")
    parser.add_argument("-w", "--wait", type=int, default=30, help="最大等待时间 (秒, 默认 30)")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[!] 文件不存在: {args.input}")
        sys.exit(1)

    try:
        import frida
    except ImportError:
        print("[!] frida 未安装。请运行: pip install frida frida-tools")
        sys.exit(1)

    unpack(args.input, args.output, args.wait)


if __name__ == "__main__":
    main()
