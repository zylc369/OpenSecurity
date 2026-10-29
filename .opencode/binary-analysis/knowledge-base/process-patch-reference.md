# process_patch.py 完整参数参考

> 通用进程 Patch + 值捕获工具。替代手写 ctypes 脚本（OpenProcess/VirtualProtectEx/WriteProcessMemory 等样板代码）。
> 平台支持: 仅 Windows。

## 调用方式

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe TARGET.EXE \
  --patch 0x40234C:EB \
  --write-data 0x422600:4B435446 \
  --write-code 0x40234E:56578D... \
  --capture 0x422480:16 \
  --signal 0x42248C:DEADBEEF \
  --trigger click:1002 \
  --timeout 15 \
  --output "$TASK_DIR/patch_result.json"
```

## 参数详解

### 基础参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--exe PATH` | 是 | 目标可执行文件路径 |
| `--output PATH` | 是 | 输出 JSON 路径 |
| `--window-title STR` | 否 | 查找窗口的标题子串（默认用 exe 文件名去除扩展名） |

### 写入参数（格式: `ADDR:HEXBYTES`，可多次使用）

| 参数 | 说明 |
|------|------|
| `--patch ADDR:HEXBYTES` | 通用字节覆盖 |
| `--write-data ADDR:HEXBYTES` | 写入数据段（不刷新指令缓存） |
| `--write-code ADDR:HEXBYTES` | 写入代码段（自动 FlushInstructionCache，用于 code cave） |

### 捕获与同步参数

| 参数 | 格式 | 说明 |
|------|------|------|
| `--capture` | `ADDR:SIZE`（可多次） | 捕获指定地址和大小的内存数据 |
| `--signal` | `ADDR:VALUE`（单次） | 轮询等待 4 字节 DWORD 值出现（十六进制），用于同步 |
| `--trigger` | `ACTION:PARAM`（单次） | 触发动作，目前支持 `click:CTRL_ID`（通过 BM_CLICK 点击按钮） |

### 控制参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--timeout SEC` | 15 | 信号等待超时（秒） |
| `--settle SEC` | 2.0 | 无 `--signal` 时的等待时间（秒） |
| `--no-kill` | false | 完成后不终止进程（用于后续截图或 Frida attach） |

## 执行流程

```
启动进程 → 查找窗口(2s+8s超时) → OpenProcess → 写入数据 → 写入代码 → 应用补丁
→ 触发动作 → 等待信号/等待稳定 → 捕获数据 → 清理
```

**写入顺序**: data → code → patch。code cave 场景需先写数据再写代码。

## 输出 JSON 格式

```json
{
  "success": true,
  "pid": 12345,
  "hwnd": "0x00123456",
  "patches_applied": ["0x40234C:eb", "0x40234E:56578d..."],
  "captures": {
    "0x422480": {"hex": "4b435446...", "size": 16}
  },
  "signal_received": true,
  "error": null
}
```

### success 判定逻辑

- 未指定 `--signal`: 操作完成即 `success=true`
- 指定了 `--signal`: **必须收到信号**才算 `success=true`；进程崩溃或超时均返回 `success=false`

### `--no-kill` 后续操作

使用 `--no-kill` 后，进程保持存活。输出 JSON 包含 `pid` 和 `hwnd`，可用于：
- 截图: `$PYTHON_CMD $SHARED_DIR/scripts/gui_capture.py`
- Frida attach: `frida -p <pid>`
- 后续内存操作: 需自行编写 ctypes 脚本（process_patch.py 只能启动新进程，无法操作已有进程）

## 常见场景

### 场景 1: Patch 跳转 + 捕获计算结果

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe crackme.exe \
  --patch 0x401234:EB \
  --capture 0x422480:16 \
  --trigger click:1002 \
  --settle 3 \
  --output "$TASK_DIR/patch_result.json"
```

### 场景 2: Code cave 注入 + 信号同步

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe crackme.exe \
  --write-data 0x422600:4B435446 \
  --write-code 0x40234E:56578D6C... \
  --patch 0x401000:E949230000 \
  --signal 0x42248C:DEADBEEF \
  --trigger click:1002 \
  --timeout 15 \
  --output "$TASK_DIR/patch_result.json"
```

### 场景 3: 只读内存（不 patch）

```bash
"$PYTHON_CMD" "$SHARED_DIR/scripts/process_patch.py" \
  --exe target.exe \
  --capture 0x403000:256 \
  --no-kill \
  --settle 5 \
  --output "$TASK_DIR/mem_read.json"
```

---

## 文件级静态修补（替代方案）

process_patch.py 修补的是**运行中进程**的内存；需要产出修补后的**静态文件**时用以下三路:

```bash
# 1. dd 精确偏移写入（字节级最精确）
echo -ne '\x90\x90\x90\x90' | dd of=target.bin bs=1 seek=0x1234 conv=notrunc

# 2. xxd 管道批量替换
xxd target.bin | sed 's/0a0b0c0d/90909090/g' | xxd -r > patched.bin

# 3. IDA: Edit → Patch program → Change byte / idaapi.patch_byte(ea, 0x90)，再 Apply patches to input file
```

## 程序化修补 API

批量/流水线修补用 Python API 两选:

**Binary Ninja**: `bv.write(addr, b"\x90"*5)` NOP / `bv.write(addr, b"\x74")` JNZ→JZ 翻转 / `bv.write(addr, b"\xb8\x01\x00\x00\x00\xc3")` mov eax,1;ret 恒真 / `bv.save()`。

**LIEF（跨格式 ELF/PE/Mach-O 统一 API）**: `lief.parse()` → `add(section)` 加节（EXECINSTR|ALLOC）/ `header.entrypoint` 改入口 / `patch_pltgot("strcmp", addr)` 劫持导入函数到自写代码 → `write()` 落盘。适合加节注入与 GOT 劫持类结构性修改。
