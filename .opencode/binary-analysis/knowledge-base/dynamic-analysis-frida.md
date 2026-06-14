# 动态分析策略 — Frida 模式（后备）

> AI 编排器在 IDA 调试器失败时通过 Read 工具加载本后备方案。
> IDA 调试器为首选，详见 `dynamic-analysis.md`。
> **GUI 交互经验与 `dynamic-analysis.md` 保持一致。**
> **验证结果时的完整决策树见 `verification-patterns.md`。**
> **Hook 注入参数和 Hook 读取结果的模板见 `verification-patterns.md` 的"方案 C1"章节。**

## 触发条件

IDA 调试器失败时（强反调试、无法启动、WoW64 断点不工作）：

1. **算法验证**：静态分析推导出算法后，需要用实际输入/输出对比验证
2. **动态脱壳**：IDA 调试器 dump 失败（详见 `packer-handling.md` 阶段 3.5b）
3. **运行时数据追踪**：需要追踪特定函数的参数、返回值、内存状态
4. **GUI 程序自动化**：需要向 GUI 控件输入数据并读取结果

---

## GUI 程序分析策略（优先级排序）

> **以下策略与 `dynamic-analysis.md` 中的 GUI 策略保持一致，但使用 Frida 实现。**

### 策略 1（首选）：Hook 比较逻辑地址

**原理**：绕过整个 GUI 交互，用 `Interceptor.attach` hook 比较函数。

**Frida 实现**：

```javascript
Interceptor.attach(ptr(compare_addr), {
    onEnter: function(args) {
        // args[0], args[1] 是比较的两个操作数
        send({
            type: "compare",
            arg0: args[0].toInt32(),
            arg1: args[1].toInt32()
        });
    }
});
```

### 策略 2：GUI 自动化（Win32 API）

**关键经验（已验证，与 IDA 调试器文档一致）**：

#### 编辑控件文本设置

⚠ **`SetDlgItemTextA` 对 MFC 编辑控件可能不生效**（返回成功但内容未更新）。

**正确做法**：用 `SendMessage(WM_SETTEXT)` 直接发到编辑控件句柄：

```javascript
var user32 = Process.getModuleByName("user32.dll");
var SendMessageA = new NativeFunction(
    user32.getExportByName("SendMessageA"),
    "pointer", ["pointer", "uint", "pointer", "pointer"]
);
var WM_SETTEXT = 0x000C;
var textPtr = Memory.allocUtf8String("my_input");
var hwndEdit = GetDlgItem(hwndDialog, controlId);
SendMessageA(hwndEdit, WM_SETTEXT, ptr(0), textPtr);
```

#### 触发按钮点击

**禁止** `SendMessageA(BM_CLICK)` — 同步调用，MessageBox 会阻塞 JS 线程。

**正确做法**：用 `PostMessageA` 发送 `WM_COMMAND`（异步）：

```javascript
var PostMessageA = new NativeFunction(
    user32.getExportByName("PostMessageA"),
    "int", ["pointer", "uint", "pointer", "pointer"]
);
var WM_COMMAND = 0x0111;
PostMessageA(hwnd, WM_COMMAND, ptr(btnId), btn);
```

#### 读取结果

用 `EnumWindows` 遍历 `#32770`（Dialog）窗口读取标题。

---

## Frida 版本适配（Frida 16 → 17）

> **完整的 API 变化速查见 `$SHARED_DIR/knowledge-base/frida-17x-api.md`。**

Frida 17 对 API 做了破坏性变更，核心两点：

### 1. Module 静态方法已移除

```javascript
// ❌ 16.x 可用，17.x 报错
Module.getExportByName(null, "memcmp");
Module.findExportByName("user32.dll", "SendMessageA");

// ✅ 17.x 正确用法
Process.getModuleByName("user32.dll").getExportByName("SendMessageA");
Process.getModuleByName("libc.so").getExportByName("memcpy");
```

### 2. Bridge（Java/ObjC/Swift）不再内置

Python SDK 中需要 ObjC Bridge 时，必须用 `frida.Compiler` 编译 TypeScript：
```typescript
import ObjC from "frida-objc-bridge";
```
详见 `frida-17x-api.md` 的 "Bridge API" 章节。纯 Native Hook（Interceptor）不受影响。

### 未变化的 API（可继续使用）

| API | 状态 |
|-----|------|
| `ptr(0xaddr).readU8()` / `.readByteArray(n)` | ✅ 无变化 |
| `Memory.alloc()` / `Memory.allocUtf8String()` | ✅ 无变化 |
| `Process.getModuleByName()` / `.enumerateModules()` | ✅ 无变化 |
| `Interceptor.attach` / `.detach` | ✅ 无变化 |
| `NativeFunction` | ✅ 无变化 |

---

## 加壳程序动态分析模式

### 核心流程

```
spawn(挂起) → attach → create_script → resume → 轮询解壳 → dump/hook
```

### 检测解壳完成

轮询入口点地址的字节，直到变为合法指令：

```javascript
var b = ptr(0x401610).readU8();
if (b === 0x55) {
    // 解壳完成
}
```

或使用 `$SHARED_DIR/scripts/frida_unpack.py` 的内置监控机制。

---

## NativeFunction 调用限制

### 加壳/SEH 程序中的崩溃风险

在加壳或使用 SEH 的程序中，`NativeFunction` 直接调用可能崩溃：
- 原因：Frida JIT 机制与程序自身的 SEH handler 冲突
- 症状：`script has been destroyed` 或进程崩溃

### 替代方案

1. **Hook + 输入模拟**：用 `Interceptor.attach` hook 目标函数，通过 GUI 自动化触发
2. **纯 Python 本地验证**：在 Python 中重新实现算法，不依赖进程内调用
3. **Unicorn 模拟**：在 Unicorn CPU 模拟器中执行

---

## 进程清理模板

每次 Frida 脚本执行必须有严格超时和清理：

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

**关键原则**：
- 超时后必须 kill 进程（GUI 程序不会自行退出）
- `session.detach()` 必须在 finally 中
