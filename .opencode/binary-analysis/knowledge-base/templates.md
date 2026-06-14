# IDA Pro 分析模板参考

> AI 编排器在需要构造 idat 命令时参考。主 prompt 中不重复这些内容。

## 预检查脚本

每次 idat 调用前必须执行文件存在性 + 数据库锁检测：

```bash
# 1. 文件存在性
$PYTHON_CMD -c "import os, sys; p=sys.argv[1]; print('EXISTS' if os.path.isfile(p) else 'NOT_FOUND: '+p)" "<目标文件>"

# 2. 数据库锁检测（跨平台：Unix 用 fcntl，Windows 用 msvcrt）
$PYTHON_CMD -c "
import sys, os
target = sys.argv[1]
base, ext = os.path.splitext(target)
if ext == '.i64':
    lock_file = target
else:
    lock_file = base + '.id0'
if not os.path.exists(lock_file):
    print('NO_DB')
    sys.exit(0)
try:
    import fcntl
    with open(lock_file, 'r') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
    print('UNLOCKED')
except ImportError:
    import msvcrt
    try:
        f = open(lock_file, 'r')
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
        print('UNLOCKED')
    except (IOError, OSError):
        print('LOCKED')
        sys.exit(1)
except (IOError, OSError):
    print('LOCKED')
    sys.exit(1)
" "<目标文件路径>"
```

**锁检测 = LOCKED → 立即报错退出**。

## IDAT 调用模式

```bash
# IDAT 可执行文件检测
IDA_PATH="<上方 IDA Pro 路径>"
IDAT=$($PYTHON_CMD -c "
import os, sys
p = sys.argv[1]
for name in ['idat', 'idat.exe']:
    full = os.path.join(p, name)
    if os.path.isfile(full):
        print(full)
        break
else:
    print(''); sys.exit(1)
" "$IDA_PATH")

# 查询操作
IDA_QUERY=<类型> IDA_OUTPUT="$TASK_DIR/result.json" [IDA_FUNC_ADDR=<地址>] [IDA_PATTERN=<模式>] \
  "$IDAT" -A -S"$SHARED_DIR/query.py" -L"$TASK_DIR/idat.log" "<目标文件>"

# 更新操作（单操作）
IDA_OPERATION=<操作> IDA_OUTPUT="$TASK_DIR/result.json" [其他参数] \
  "$IDAT" -A -S"$SHARED_DIR/update.py" -L"$TASK_DIR/idat.log" "<目标文件>"

# 更新操作（批量）
IDA_OPERATION=batch IDA_BATCH_FILE="$TASK_DIR/ops.json" IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/update.py" -L"$TASK_DIR/idat.log" "<目标文件>"

# 初始分析流水线（首次分析时首选）
IDA_OUTPUT="$TASK_DIR/initial.json" \
  "$IDAT" -A -S"$SHARED_DIR/scripts/initial_analysis.py" -L"$TASK_DIR/initial.log" "<目标文件>"

# 沉淀脚本调用
IDA_FUNC_ADDR=<地址> IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/scripts/<脚本名>.py" -L"$TASK_DIR/idat.log" "<目标文件>"
```

## debug_dump 调用模板

```bash
# IDA 调试器 dump（运行到 OEP，dump 内存重建 PE）
IDA_OEP_ADDR=0x401000 IDA_PE_OUTPUT="$TASK_DIR/unpacked.exe" IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/scripts/debug_dump.py" -L"$TASK_DIR/debug.log" "<目标文件>"

# 不设 IDA_PE_OUTPUT 时自动从 IDA_OUTPUT 推导（去 .json 加 .pe）
IDA_OEP_ADDR=0x401000 IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/scripts/debug_dump.py" -L"$TASK_DIR/debug.log" "<目标文件>"
# 上面的命令会输出 PE 到 $TASK_DIR/result.pe
```

## force_create 反编译

```bash
# 反编译未识别函数（脱壳后常见：IDA 未自动识别函数）
IDA_QUERY=decompile IDA_FUNC_ADDR=0x4047CB IDA_FORCE_CREATE=1 IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/query.py" -L"$TASK_DIR/idat.log" "<目标文件>"
```

## Batch JSON 格式

```json
{
  "operations": [
    {"type": "rename", "old_name": "sub_401000", "new_name": "validate_password"},
    {"type": "set_func_comment", "func_addr": "0x401000", "comment": "验证用户密码"},
    {"type": "set_line_comment", "addr": "0x401050", "comment": "比较密码长度"}
  ]
}
```

## read_data 读取模式

| `IDA_READ_MODE` | 说明 | 额外参数 |
|-----------------|------|---------|
| `auto`（默认） | 自动判断数据类型并读取 | `IDA_READ_SIZE`（字节数，默认 64） |
| `string` | 读取 null-terminated 字符串 | 无 |
| `bytes` | 读取原始字节 | `IDA_READ_SIZE`（字节数，默认 64） |
| `pointer` | 读取指针值 | `IDA_DEREF=1` 解引用指针 |

```bash
# 示例：读取全局变量（自动模式）
IDA_QUERY=read_data IDA_ADDR=Str2 IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/query.py" -L"$TASK_DIR/idat.log" "<目标文件>"

# 示例：指针模式 + 解引用
IDA_QUERY=read_data IDA_ADDR=0x14013F008 IDA_READ_MODE=pointer IDA_DEREF=1 \
  IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SHARED_DIR/query.py" -L"$TASK_DIR/idat.log" "<目标文件>"
```

## 错误诊断

idat 执行失败时：
1. 检查返回码 `$?`
2. 读取 `-L` 日志文件末尾 50 行：`$PYTHON_CMD -c "import sys; lines = open(sys.argv[1], encoding='utf-8', errors='replace').readlines(); [print(l, end='') for l in lines[-50:]]" "$TASK_DIR/idat.log"`
3. 常见错误：
   - `Resource temporarily unavailable` → 数据库被锁
   - `ModuleNotFoundError` → 脚本路径错误
   - `qexit(1)` / exit code 1 → 脚本内部错误

---

## Windows PowerShell 命令模板

> Windows 上使用 PowerShell 执行。与上方 bash 模板一一对应。
> 关键差异: `VAR=xxx command` → `$env:VAR="xxx"; command`，路径分隔符 `\`。
> `$PYTHON_CMD` 由 Plugin 保证为 venv Python 绝对路径（含第三方包），无需区分平台。

### 预检查脚本

```powershell
# 1. 文件存在性
$PYTHON_CMD -c "import os, sys; p=sys.argv[1]; print('EXISTS' if os.path.isfile(p) else 'NOT_FOUND: '+p)" "<目标文件>"

# 2. 数据库锁检测
$PYTHON_CMD -c "
import sys, os, msvcrt
target = sys.argv[1]
base, ext = os.path.splitext(target)
if ext == '.i64':
    lock_file = target
else:
    lock_file = base + '.id0'
if not os.path.exists(lock_file):
    print('NO_DB'); sys.exit(0)
try:
    f = open(lock_file, 'r')
    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    f.close()
    print('UNLOCKED')
except (IOError, OSError):
    print('LOCKED'); sys.exit(1)
" "<目标文件路径>"
```

### 查询操作

```powershell
$env:IDA_QUERY = "<类型>"
$env:IDA_OUTPUT = "$TASK_DIR\result.json"
$env:IDA_FUNC_ADDR = "<地址>"
& "$IDAT" -A -S"$SHARED_DIR\query.py" -L"$TASK_DIR\idat.log" "<目标文件>"
```

### 更新操作（单操作）

```powershell
$env:IDA_OPERATION = "<操作>"
$env:IDA_OUTPUT = "$TASK_DIR\result.json"
$env:IDA_OLD_NAME = "<旧名>"
$env:IDA_NEW_NAME = "<新名>"
& "$IDAT" -A -S"$SHARED_DIR\update.py" -L"$TASK_DIR\idat.log" "<目标文件>"
```

### 初始分析流水线

```powershell
$env:IDA_OUTPUT = "$TASK_DIR\initial.json"
& "$IDAT" -A -S"$SHARED_DIR\scripts\initial_analysis.py" -L"$TASK_DIR\initial.log" "<目标文件>"
```

### debug_dump 调用

```powershell
$env:IDA_OEP_ADDR = "0x401000"
$env:IDA_PE_OUTPUT = "$TASK_DIR\unpacked.exe"
$env:IDA_OUTPUT = "$TASK_DIR\result.json"
& "$IDAT" -A -S"$SHARED_DIR\scripts\debug_dump.py" -L"$TASK_DIR\debug.log" "<目标文件>"
```

### 错误诊断

```powershell
# 读取日志末尾 50 行
$PYTHON_CMD -c "import sys; lines = open(sys.argv[1], encoding='utf-8', errors='replace').readlines(); [print(l, end='') for l in lines[-50:]]" "$TASK_DIR\idat.log"
```
