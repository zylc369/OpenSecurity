# Unicorn 模拟执行脚本模板

> AI 编排器在需要模拟执行验证算法时按需加载。

## 触发条件

- 需要验证加密/解密算法是否正确
- 需要在不运行原始二进制的情况下测试函数输入/输出
- 需要对比标准实现与二进制实际行为

---

## 模板 1: IDAPython 脚本（idat headless 模式）

> 通过 idat headless 运行，直接从 IDA 数据库读取二进制数据。

```python
# -*- coding: utf-8 -*-
"""summary: Unicorn 模拟执行指定函数

description:
  从 IDA 数据库提取函数代码和所需段数据，用 Unicorn 模拟执行。
  通过环境变量 IDA_FUNC_ADDR 指定目标函数地址。

  IDA_FUNC_ADDR=0x401000 IDA_OUTPUT=$TASK_DIR/result.json \
    idat -A -S"scripts/unicorn_emulate.py" -L$TASK_DIR/emu.log target.i64

level: intermediate
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _base import env_str, log, run_headless
from _utils import hex_addr, resolve_addr

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_segment

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_MODE_64
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_EIP,
    UC_X86_REG_RAX, UC_X86_REG_RIP, UC_X86_REG_RSP, UC_X86_REG_RBP,
)


BASE_ADDR = 0x10000000
STACK_BASE = 0x7FF00000
STACK_SIZE = 0x100000
DATA_BASE = 0x80000000


def _collect_function_bytes(func):
    chunks = []
    for chunk in ida_funcs.func_tail_iterator_t(func):
        start = chunk.start_ea
        end = chunk.end_ea
        data = ida_bytes.get_bytes(start, end - start)
        if data:
            chunks.append((start, data))
    return chunks


def _collect_segment_bytes():
    segs = []
    seg = ida_segment.get_first_seg()
    while seg and seg.start_ea != ida_idaapi.BADADDR:
        size = seg.end_ea - seg.start_ea
        if size > 0 and size < 10 * 1024 * 1024:
            data = ida_bytes.get_bytes(seg.start_ea, size)
            if data:
                segs.append((seg.start_ea, data))
        seg = ida_segment.get_next_seg(seg.end_ea)
    return segs


def _setup_emulator(is_64, func_addr, func_bytes_list, all_segs):
    mode = UC_MODE_64 if is_64 else UC_MODE_32
    mu = Uc(UC_ARCH_X86, mode)

    mu.mem_map(BASE_ADDR, 0x10000000)

    for seg_addr, seg_data in all_segs:
        offset = seg_addr % 0x10000000
        end = offset + len(seg_data)
        if end > 0x10000000:
            seg_data = seg_data[:0x10000000 - offset]
        mu.mem_write(BASE_ADDR + offset, seg_data)

    for chunk_addr, chunk_data in func_bytes_list:
        offset = chunk_addr % 0x10000000
        mu.mem_write(BASE_ADDR + offset, chunk_data)

    mu.mem_map(STACK_BASE, STACK_SIZE)
    if is_64:
        mu.reg_write(UC_X86_REG_RSP, STACK_BASE + STACK_SIZE - 0x1000)
        mu.reg_write(UC_X86_REG_RBP, STACK_BASE + STACK_SIZE - 0x1000)
    else:
        mu.reg_write(UC_X86_REG_ESP, STACK_BASE + STACK_SIZE - 0x1000)
        mu.reg_write(UC_X86_REG_EBP, STACK_BASE + STACK_SIZE - 0x1000)

    return mu


def _main():
    addr_str = env_str("IDA_FUNC_ADDR", "")
    if not addr_str:
        return {"success": False, "error": "IDA_FUNC_ADDR 未设置", "data": None}

    ea = resolve_addr(addr_str)
    if ea == ida_idaapi.BADADDR:
        return {"success": False, "error": f"无法解析地址: {addr_str}", "data": None}

    func = ida_funcs.get_func(ea)
    if func is None:
        return {"success": False, "error": f"地址 {hex_addr(ea)} 不属于任何函数", "data": None}

    import ida_ida
    is_64 = ida_ida.inf_is_64bit()
    func_addr = func.start_ea
    func_size = func.size()

    log(f"[*] 模拟目标: {hex_addr(func_addr)} ({func_size} 字节, {'64' if is_64 else '32'}-bit)\n")

    func_bytes_list = _collect_function_bytes(func)
    all_segs = _collect_segment_bytes()

    try:
        mu = _setup_emulator(is_64, func_addr, func_bytes_list, all_segs)
    except Exception as e:
        return {"success": False, "error": f"Unicorn 初始化失败: {e}", "data": None}

    emulated_addr = BASE_ADDR + (func_addr % 0x10000000)
    end_addr = emulated_addr + func_size

    try:
        mu.emu_start(emulated_addr, end_addr, timeout=10 * 1000000)
    except Exception as e:
        return {"success": False, "error": f"模拟执行失败: {e}", "data": None}

    if is_64:
        ret_val = mu.reg_read(UC_X86_REG_RAX)
    else:
        ret_val = mu.reg_read(UC_X86_REG_EAX)

    log(f"[+] 模拟完成, 返回值: 0x{ret_val:X} ({ret_val})\n")

    return {
        "success": True,
        "data": {
            "func_addr": hex_addr(func_addr),
            "func_size": func_size,
            "return_value": ret_val,
            "return_value_hex": hex(ret_val),
        },
        "error": None,
    }


run_headless(_main)
```

---

## 模板 2: 纯 Python 脚本（不依赖 IDA）

> 在 Python 进程中直接运行，需要手动提供二进制数据。适用于算法验证。
> **必须使用 `$PYTHON_CMD` 运行**（需要 unicorn 包，安装在 venv 中）。

```python
"""Unicorn 模拟执行 — 纯 Python 模板

从文件加载二进制数据，用 Unicorn 模拟执行指定函数。
"""

import struct
import sys

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_MODE_64
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP,
    UC_X86_REG_RAX, UC_X86_REG_RSP, UC_X86_REG_RIP,
)


def emulate_function(binary_path, func_offset, func_size, base_addr=0x400000, is_64=False):
    with open(binary_path, "rb") as f:
        binary_data = f.read()

    mode = UC_MODE_64 if is_64 else UC_MODE_32
    mu = Uc(UC_ARCH_X86, mode)

    map_size = ((len(binary_data) + 0xFFF) // 0x1000) * 0x1000 + 0x10000
    mu.mem_map(base_addr, map_size)
    mu.mem_write(base_addr, binary_data)

    STACK_BASE = 0x7FF00000
    STACK_SIZE = 0x100000
    mu.mem_map(STACK_BASE, STACK_SIZE)

    if is_64:
        mu.reg_write(UC_X86_REG_RSP, STACK_BASE + STACK_SIZE - 0x1000)
    else:
        mu.reg_write(UC_X86_REG_ESP, STACK_BASE + STACK_SIZE - 0x1000)

    # 写入测试数据到数据区
    DATA_BASE = 0x80000000
    mu.mem_map(DATA_BASE, 0x10000)
    test_input = b"test_input_data"
    mu.mem_write(DATA_BASE, test_input)

    func_addr = base_addr + func_offset
    end_addr = func_addr + func_size

    try:
        mu.emu_start(func_addr, end_addr, timeout=10 * 1000000)
    except Exception as e:
        print(f"[!] 模拟失败: {e}")
        return None

    if is_64:
        return mu.reg_read(UC_X86_REG_RAX)
    else:
        return mu.reg_read(UC_X86_REG_EAX)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"用法: $PYTHON_CMD {sys.argv[0]} <二进制文件> <函数偏移(hex)> <函数大小>")
        sys.exit(1)

    binary_path = sys.argv[1]
    func_offset = int(sys.argv[2], 16)
    func_size = int(sys.argv[3])

    result = emulate_function(binary_path, func_offset, func_size)
    if result is not None:
        print(f"[+] 返回值: {result} (0x{result:X})")
```

---

## 常见陷阱

| 陷阱 | 说明 |
|------|------|
| 地址映射不一致 | IDA 数据库地址 ≠ Unicorn 映射地址。需要对齐或使用固定 BASE |
| 栈空间不足 | 默认 1MB 栈足够大多数函数，但递归函数可能溢出 |
| 未处理系统调用 | 模拟不包含 OS API 调用（如 malloc、printf）。遇到时需手动 hook 返回值 |
| 浮点指令 | Unicorn 默认不映射浮点寄存器。需要时手动映射 |
| 自修改代码 | 某些壳/保护会修改自身代码。需要在写操作后重新读取 |
| 函数边界判断 | `emu_start` 的结束地址不一定是下一条指令。用 `emu_stop()` 在 hook 中手动停止更可靠 |
