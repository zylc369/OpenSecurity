# -*- coding: utf-8 -*-
"""summary: 通用进程 Patch + 值捕获工具

description:
  通过命令行参数指定目标程序和 patch 点，自动完成进程管理、内存 patch、
  值捕获和触发操作。避免每次动态分析都手写 OpenProcess/VirtualProtectEx
  等样板代码。

  使用方式（通过 $PYTHON_CMD 运行）:
    $PYTHON_CMD $SCRIPTS_DIR/scripts/process_patch.py \\
      --exe TARGET.EXE \\
      --patch 0x40234C:EB \\
      --write-data 0x422600:4B43544646 \\
      --write-code 0x40234E:56578D... \\
      --capture 0x422480:16 \\
      --signal 0x42248C:DEADBEEF \\
      --trigger click:1002 \\
      --timeout 15 \\
      --output result.json

  平台支持: 仅 Windows（使用 ctypes + kernel32/user32）。

level: intermediate
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
import struct
import subprocess
import time

# Windows 常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PAGE_EXECUTE_READWRITE = 0x40

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)


def _parse_hex_bytes(hex_str):
    """将十六进制字符串转为字节串。如 'EB29' -> b'\\xeb\\x29'"""
    hex_str = hex_str.strip()
    if len(hex_str) % 2 != 0:
        raise ValueError(f"十六进制字符串长度必须为偶数: '{hex_str}'")
    return bytes.fromhex(hex_str)


def _parse_addr(addr_str):
    """解析地址字符串（支持 0x 前缀或纯十六进制）。"""
    return int(addr_str, 16)


def _parse_patch(spec):
    """解析 patch/write 参数: 'ADDR:HEXBYTES' -> (addr_int, bytes)。"""
    parts = spec.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"格式错误: '{spec}'，预期 ADDR:HEXBYTES")
    addr = _parse_addr(parts[0])
    data = _parse_hex_bytes(parts[1])
    return addr, data


def _parse_capture(spec):
    """解析 capture 参数: 'ADDR:SIZE' -> (addr_int, size_int)。"""
    parts = spec.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"格式错误: '{spec}'，预期 ADDR:SIZE")
    addr = _parse_addr(parts[0])
    size = int(parts[1])
    return addr, size


def _find_window(title_substring, timeout=10):
    """查找包含指定子串的顶层窗口。"""
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    result = [None]

    def callback(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        if title_substring.lower() in buf.value.lower():
            result[0] = hwnd
            return False
        return True

    wrapped_callback = WNDENUMPROC(callback)
    deadline = time.time() + timeout
    while time.time() < deadline:
        u32.EnumWindows(wrapped_callback, 0)
        if result[0]:
            return result[0]
        time.sleep(0.5)
    return None


def _read_mem(handle, addr, size):
    """从目标进程读取内存。"""
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(handle, addr, buf, size, ctypes.byref(n))
    if not ok:
        return None
    return buf.raw[: n.value]


def _write_mem(handle, addr, data):
    """向目标进程写入内存（自动 VirtualProtectEx）。"""
    old = wintypes.DWORD()
    k32.VirtualProtectEx(handle, addr, len(data) + 16, PAGE_EXECUTE_READWRITE, ctypes.byref(old))
    n = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(handle, addr, data, len(data), ctypes.byref(n))
    if not ok:
        err = ctypes.get_last_error()
        raise RuntimeError(f"WriteProcessMemory(0x{addr:X}) 失败: error={err}")


def _flush_cache(handle, addr, size):
    """刷新指令缓存。"""
    k32.FlushInstructionCache(handle, addr, size)


def _click_button(hwnd, ctrl_id):
    """通过 BM_CLICK 点击按钮控件。"""
    ctrl = u32.GetDlgItem(hwnd, ctrl_id)
    if not ctrl:
        raise RuntimeError(f"GetDlgItem({ctrl_id}) 返回 NULL")
    BM_CLICK = 0x00F5
    u32.PostMessageW(ctrl, BM_CLICK, 0, 0)


def build_parser():
    """构建命令行参数解析器。"""
    p = argparse.ArgumentParser(description="通用进程 Patch + 值捕获工具")
    p.add_argument("--exe", required=True, help="目标可执行文件路径")
    p.add_argument("--window-title", default="", help="查找窗口的标题子串（默认用 exe 文件名）")
    p.add_argument("--patch", action="append", default=[], metavar="ADDR:HEXBYTES",
                    help="补丁点: 地址:十六进制字节（可多次使用）")
    p.add_argument("--write-data", action="append", default=[], metavar="ADDR:HEXBYTES",
                    help="数据写入点: 地址:十六进制字节（可多次使用）")
    p.add_argument("--write-code", action="append", default=[], metavar="ADDR:HEXBYTES",
                    help="代码写入点: 地址:十六进制字节（自动 FlushInstructionCache，可多次使用）")
    p.add_argument("--capture", action="append", default=[], metavar="ADDR:SIZE",
                    help="值捕获: 地址:字节数（可多次使用）")
    p.add_argument("--signal", default="", metavar="ADDR:VALUE",
                    help="信号同步: 地址:期望值（十六进制），轮询等待")
    p.add_argument("--trigger", default="", metavar="ACTION:PARAM",
                    help="触发动作: click:CTRL_ID")
    p.add_argument("--timeout", type=int, default=15, help="信号等待超时（秒），默认 15")
    p.add_argument("--settle", type=float, default=2.0, help="触发后等待时间（秒），默认 2")
    p.add_argument("--no-kill", action="store_true", help="完成后不终止目标进程（用于后续截图等操作）")
    p.add_argument("--output", required=True, help="输出 JSON 路径")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    result = {
        "success": False,
        "pid": None,
        "hwnd": None,
        "patches_applied": [],
        "captures": {},
        "signal_received": False,
        "error": None,
    }

    # 解析参数
    patches = [_parse_patch(s) for s in args.patch]
    data_writes = [_parse_patch(s) for s in args.write_data]
    code_writes = [_parse_patch(s) for s in args.write_code]
    captures = [_parse_capture(s) for s in args.capture]

    signal_addr = None
    signal_value = None
    if args.signal:
        sa, sv = args.signal.split(":", 1)
        signal_addr = _parse_addr(sa)
        signal_value = int(sv, 16)

    window_title = args.window_title or os.path.splitext(os.path.basename(args.exe))[0]

    proc = None
    handle = None
    try:
        # 1. 启动目标进程
        proc = subprocess.Popen([args.exe])
        result["pid"] = proc.pid
        print(f"[+] 进程已启动: PID={proc.pid}")

        # 2. 查找窗口
        time.sleep(2)
        hwnd = _find_window(window_title, timeout=8)
        if not hwnd:
            raise RuntimeError(f"未找到窗口: '{window_title}'")
        print(f"[+] 窗口已找到: 0x{hwnd:08X}")
        result["hwnd"] = f"0x{hwnd:08X}"

        # 3. 打开进程
        handle = k32.OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
        if not handle:
            raise RuntimeError(f"OpenProcess 失败: PID={proc.pid}")
        print(f"[+] 进程句柄: 0x{handle:X}")

        # 4. 写入数据
        for addr, data in data_writes:
            _write_mem(handle, addr, data)
            result["patches_applied"].append(f"0x{addr:X}:{data.hex()}")
            print(f"[+] 写入数据: 0x{addr:X} ({len(data)} 字节)")

        # 5. 写入代码
        for addr, code in code_writes:
            _write_mem(handle, addr, code)
            _flush_cache(handle, addr, len(code))
            result["patches_applied"].append(f"0x{addr:X}:{code.hex()}")
            print(f"[+] 写入代码: 0x{addr:X} ({len(code)} 字节)")

        # 6. 应用补丁
        for addr, patch_bytes in patches:
            _write_mem(handle, addr, patch_bytes)
            result["patches_applied"].append(f"0x{addr:X}:{patch_bytes.hex()}")
            print(f"[+] 应用补丁: 0x{addr:X} -> {patch_bytes.hex()}")

        # 7. 触发动作
        if args.trigger:
            parts = args.trigger.split(":", 1)
            action = parts[0]
            if action == "click" and len(parts) == 2:
                ctrl_id = int(parts[1])
                _click_button(hwnd, ctrl_id)
                print(f"[+] 触发: click 控件 {ctrl_id}")
            else:
                print(f"[!] 未知触发动作: {args.trigger}")

        # 8. 等待信号
        if signal_addr is not None:
            print(f"[*] 等待信号: 0x{signal_addr:X} == 0x{signal_value:X} (超时 {args.timeout}s)")
            deadline = time.time() + args.timeout
            while time.time() < deadline:
                rc = proc.poll()
                if rc is not None:
                    print(f"[!] 进程已退出 (code={rc})")
                    break
                data = _read_mem(handle, signal_addr, 4)
                if data and len(data) >= 4:
                    val = struct.unpack("<I", data)[0]
                    if val == signal_value:
                        result["signal_received"] = True
                        print(f"[+] 信号已捕获")
                        break
                time.sleep(0.5)
            else:
                print(f"[!] 信号等待超时 ({args.timeout}s)")
        else:
            time.sleep(args.settle)

        # 9. 捕获数据
        for addr, size in captures:
            data = _read_mem(handle, addr, size)
            if data:
                result["captures"][f"0x{addr:X}"] = {"hex": data.hex(), "size": len(data)}
                print(f"[+] 捕获数据: 0x{addr:X} ({len(data)} 字节)")
            else:
                result["captures"][f"0x{addr:X}"] = {"hex": "", "size": 0}
                print(f"[!] 捕获失败: 0x{addr:X}")

        # 成功判定: 如果指定了 signal 但未收到，则不标记为成功
        if signal_addr is not None and not result["signal_received"]:
            result["success"] = False
            result["error"] = result.get("error") or "信号未收到（进程可能已崩溃或 patch 有误）"
        else:
            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        print(f"[!] 错误: {e}")
    finally:
        # 10. 清理
        if handle:
            k32.CloseHandle(handle)
        if proc and proc.poll() is None:
            if args.no_kill:
                print(f"[*] 进程保持存活 (--no-kill), PID={proc.pid}")
            else:
                time.sleep(0.5)
                try:
                    proc.kill()
                except Exception:
                    pass
                print(f"[+] 进程已终止")

    # 输出 JSON
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] 结果已写入: {args.output}")


if __name__ == "__main__":
    main()
