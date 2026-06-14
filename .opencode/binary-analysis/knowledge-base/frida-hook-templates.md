# Frida Hook 脚本模板

> AI 编排器在需要 Frida Hook 脚本时按需加载。
> **Frida 脚本必须使用 `$PYTHON_CMD` 运行**（需要 frida 包，安装在 venv 中）。
> 验证结果的完整决策树见 `verification-patterns.md`。本文件提供通用的 Hook 模板。

## 触发条件

- 需要拦截函数参数或返回值
- 需要读取运行时内存数据
- IDA 调试器失败后切换到 Frida 后备方案

---

## 版本兼容性说明

不同 Frida 版本的 API 有差异，以下列出常见替代方案：

| 旧 API | 替代方案 | 说明 |
|--------|---------|------|
| `Module.findBaseAddress(name)` | `Process.findModuleByName(name).base` | 更可靠，返回 Module 对象 |
| `Memory.readU32(ptr)` | `ptr.readU32()` | 直接在 NativePointer 上调用 |
| `Memory.writeU32(ptr, val)` | `ptr.writeU32(val)` | 直接在 NativePointer 上调用 |
| `Memory.patchCode(ptr, size, fn)` | `Memory.protect(ptr, size, 'rwx')` + `ptr.writeU8(val)` | `patchCode` 在某些版本可能 hang |

**建议**: 优先使用 `ptr.readXxx()` / `ptr.writeXxx()` 风格，而非 `Memory.readXxx()` 全局函数。

---

## 模板 1: 参数拦截 + 返回值读取

```python
"""Frida Hook — 拦截指定函数的参数和返回值

用法: $PYTHON_CMD hook_args.py <目标程序> <函数地址(hex)> [--timeout 30]
"""

import argparse
import json
import os
import sys
import time

import frida


JS_CODE = """
'use strict';

var targetAddr = ptr(TARGET_ADDR);
var funcName = TARGET_FUNC_NAME || "target";

Interceptor.attach(targetAddr, {
    onEnter: function(args) {
        this.args = [];
        for (var i = 0; i < 4; i++) {
            try {
                this.args.push({
                    idx: i,
                    value: args[i].toInt32(),
                    valueHex: args[i].toString(),
                });
            } catch(e) {
                this.args.push({idx: i, value: "error", error: e.toString()});
            }
        }
        send({type: "enter", func: funcName, args: this.args});
    },
    onLeave: function(retval) {
        send({type: "leave", func: funcName, retval: retval.toInt32(), retvalHex: retval.toString()});
    }
});
"""


def run_hook(target_path, func_addr, func_name="target", timeout=30):
    if not os.path.isfile(target_path):
        return {"success": False, "error": f"文件不存在: {target_path}"}

    pid = frida.spawn(target_path)
    session = frida.attach(pid)

    js = JS_CODE.replace("TARGET_ADDR", str(func_addr))
    js = js.replace("TARGET_FUNC_NAME", json.dumps(func_name))

    script = session.create_script(js)

    results = []

    def on_message(message, data):
        if message["type"] == "send":
            results.append(message["payload"])
            payload = message["payload"]
            if payload["type"] == "enter":
                args_str = ", ".join(f"arg{i}={a.get('valueHex', '?')}" for i, a in enumerate(payload.get("args", [])))
                print(f"[*] 进入 {payload['func']}({args_str})")
            elif payload["type"] == "leave":
                print(f"[*] 离开 {payload['func']} → {payload.get('retvalHex', '?')}")
        elif message["type"] == "error":
            print(f"[!] JS 错误: {message['stack']}")

    script.on("message", on_message)
    script.load()
    frida.resume(pid)

    try:
        time.sleep(timeout)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            session.detach()
        except Exception:
            pass
        if os.name == "nt":
            os.system(f"taskkill /PID {pid} /F >nul 2>&1")
        else:
            os.system(f"kill -9 {pid} 2>/dev/null")

    return {"success": True, "results": results, "count": len(results)}


def main():
    parser = argparse.ArgumentParser(description="Frida Hook 参数拦截")
    parser.add_argument("target", help="目标程序路径")
    parser.add_argument("address", help="函数地址（十六进制）")
    parser.add_argument("--name", default="target", help="函数名（用于日志）")
    parser.add_argument("--timeout", type=int, default=30, help="超时秒数")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    args = parser.parse_args()

    result = run_hook(args.target, int(args.address, 16), args.name, args.timeout)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"\n[+] 结果已写入: {args.output}")
    else:
        print(f"\n{output_json}")


if __name__ == "__main__":
    main()
```

---

## 模板 2: 内存读取 Hook

```python
"""Frida Hook — 读取指定地址处的内存数据

用法: $PYTHON_CMD hook_memory.py <目标程序> <地址(hex)> <大小> [--timeout 30]
"""

import argparse
import json
import os
import sys
import time

import frida


JS_CODE = """
'use strict';

var targetAddr = ptr(TARGET_ADDR);
var readSize = READ_SIZE;

rpc.exports = {
    readMemory: function() {
        try {
            var bytes = targetAddr.readByteArray(readSize);
            var hex = [];
            var arr = new Uint8Array(bytes);
            for (var i = 0; i < arr.length; i++) {
                hex.push(('0' + arr[i].toString(16)).slice(-2));
            }
            return {success: true, hex: hex.join(' '), size: arr.length};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }
};

// 也可在断点处自动读取
var breakAddr = ptr(BREAK_ADDR);
if (breakAddr.compare(ptr(0)) !== 0) {
    Interceptor.attach(breakAddr, {
        onEnter: function(args) {
            try {
                var bytes = targetAddr.readByteArray(readSize);
                var arr = new Uint8Array(bytes);
                var hex = [];
                for (var i = 0; i < arr.length; i++) {
                    hex.push(('0' + arr[i].toString(16)).slice(-2));
                }
                send({type: "memory", hex: hex.join(' '), size: arr.length});
            } catch(e) {
                send({type: "error", error: e.toString()});
            }
        }
    });
}
"""


def run_memory_read(target_path, addr, size, break_addr=0, timeout=30):
    if not os.path.isfile(target_path):
        return {"success": False, "error": f"文件不存在: {target_path}"}

    pid = frida.spawn(target_path)
    session = frida.attach(pid)

    js = JS_CODE.replace("TARGET_ADDR", str(addr))
    js = js.replace("READ_SIZE", str(size))
    js = js.replace("BREAK_ADDR", str(break_addr))

    script = session.create_script(js)

    results = []

    def on_message(message, data):
        if message["type"] == "send":
            results.append(message["payload"])
            payload = message["payload"]
            if payload.get("type") == "memory":
                print(f"[*] 内存: {payload['hex'][:80]}... ({payload['size']} 字节)")
            elif payload.get("type") == "error":
                print(f"[!] 错误: {payload['error']}")

    script.on("message", on_message)
    script.load()
    frida.resume(pid)

    try:
        time.sleep(timeout)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            session.detach()
        except Exception:
            pass
        if os.name == "nt":
            os.system(f"taskkill /PID {pid} /F >nul 2>&1")
        else:
            os.system(f"kill -9 {pid} 2>/dev/null")

    return {"success": True, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frida 内存读取")
    parser.add_argument("target", help="目标程序路径")
    parser.add_argument("address", help="读取地址（十六进制）")
    parser.add_argument("size", type=int, help="读取字节数")
    parser.add_argument("--break-at", default="0", help="断点地址（十六进制，可选）")
    parser.add_argument("--timeout", type=int, default=30, help="超时秒数")
    args = parser.parse_args()

    result = run_memory_read(
        args.target, int(args.address, 16), args.size,
        int(args.break_at, 16) if args.break_at != "0" else 0,
        args.timeout,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

---

## 模板 3: 比较函数 Hook（密码学逆向专用）

```javascript
// 注入到 Frida 的 JS 代码 — Hook memcmp/strcmp/CStringCompare 等
// 配合模板 1 的 Python 包装使用

'use strict';

// Hook memcmp — 捕获所有内存比较
var memcmp = Process.getModuleByName("libc.so").getExportByName("memcmp");
if (memcmp) {
    Interceptor.attach(memcmp, {
        onEnter: function(args) {
            this.buf1 = args[0];
            this.buf2 = args[1];
            this.size = args[2].toInt32();
        },
        onLeave: function(retval) {
            var size = Math.min(this.size, 64);
            var b1 = this.buf1.readByteArray(size);
            var b2 = this.buf2.readByteArray(size);
            send({
                type: "memcmp",
                size: this.size,
                result: retval.toInt32(),
                buf1_hex: Array.from(new Uint8Array(b1)).map(b => ('0'+b.toString(16)).slice(-2)).join(' '),
                buf2_hex: Array.from(new Uint8Array(b2)).map(b => ('0'+b.toString(16)).slice(-2)).join(' '),
            });
        }
    });
}

// Hook strcmp — 捕获字符串比较
var strcmp = Process.getModuleByName("libc.so").getExportByName("strcmp");
if (strcmp) {
    Interceptor.attach(strcmp, {
        onEnter: function(args) {
            this.s1 = args[0].readUtf8String();
            this.s2 = args[1].readUtf8String();
        },
        onLeave: function(retval) {
            send({
                type: "strcmp",
                result: retval.toInt32(),
                s1: this.s1,
                s2: this.s2,
            });
        }
    });
}
```

---

## 进程清理模板（必须遵循）

```python
import frida, time, os

pid = frida.spawn(target)
session = frida.attach(pid)
script = session.create_script(js_code)
script.load()
frida.resume(pid)

try:
    time.sleep(max_wait)
except Exception:
    pass
finally:
    try:
        session.detach()
    except Exception:
        pass
    if os.name == "nt":
        os.system(f"taskkill /PID {pid} /F >nul 2>&1")
    else:
        os.system(f"kill -9 {pid} 2>/dev/null")
```

**关键原则**:
- 超时后必须 kill 进程（GUI 程序不会自行退出）
- `session.detach()` 必须在 finally 中
- spawn + attach + resume 是标准流程，不要用 attach(pid) 直接附加到已运行进程
