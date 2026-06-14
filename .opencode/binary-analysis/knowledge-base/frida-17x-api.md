# Frida 17.x API 变化速查（通用）

> 从 frida 16.x 迁移到 17.x 时所有 API 变化的完整参考。适用于 PC 端（exe/dll/so/dylib）和移动端（APK/IPA）。

---

## 变化总览

| 领域 | 变化程度 | 说明 |
|------|---------|------|
| Module API | ⚠️ **重大变化** | `Module` 从静态对象变为构造函数 |
| Bridge API | ⚠️ **重大变化** | Java/ObjC/Swift Bridge 不再内置到 GumJS runtime |
| Memory API | ✅ 无变化 | `Memory.alloc`/`readU8`/`readByteArray`/`writeU32` 等均正常 |
| Process API | ✅ 无变化 | `Process.getModuleByName`/`enumerateModules` 等均正常 |
| NativeFunction | ✅ 无变化 | 类型 `'pointer'`/`'uint'`/`'size_t'`/`'void'` 均可用 |
| Interceptor | ✅ 无变化 | `Interceptor.attach`/`detach` 均正常 |
| Script | ✅ 无变化 | `Script.runtime` 返回 `"QJS"` 或 `"V8"` |

---

## Module API（重大变化）

### ❌ 已移除：Module 静态方法

```javascript
// frida 16.x 可用，17.x 报错
Module.findExportByName(null, 'memcpy');     // ❌ TypeError
Module.getExportByName(null, 'memcpy');       // ❌ TypeError
Module.findBaseAddress('libc.so');            // ❌ TypeError
Module.enumerateExports('libc.so');           // ❌ TypeError
```

**原因**: `Module` 从静态对象变为构造函数。

### ✅ 正确用法：通过 Process 实例方法

```javascript
// 获取模块
var mod = Process.getModuleByName('libc.so');
var base = mod.baseAddress;           // NativePointer
var size = mod.size;                  // number

// 查找导出
var memcpyAddr = Process.getModuleByName('libc.so').getExportByName('memcpy');

// 枚举导出
var exports = Process.getModuleByName('libnative.so').enumerateExports();

// 查找基址
var base = Process.getModuleByName('libc.so').baseAddress;
```

### ✅ Module 构造函数的静态方法

```javascript
// Module.getGlobalExportByName 是唯一仍存在的静态方法
var addr = Module.getGlobalExportByName('malloc');
```

---

## Bridge API（重大变化）

> **Frida 17.0.0 起，Java/ObjC/Swift Bridge 不再内置到 GumJS runtime。**

| 环境 | Bridge 状态 | 原因 |
|------|-----------|------|
| `frida` CLI (REPL) | ✅ 内置 | REPL 打包了全部三个 bridge |
| `frida-trace` | ✅ 内置 | 同上 |
| Python SDK `session.create_script(js_string)` | ❌ 不可用 | bridge 不在 runtime 中，`typeof Java === "undefined"` |
| Python SDK `frida.Compiler().build(ts)` | ✅ 可用 | 编译时将 bridge 打包进 bundle |
| 纯 Native Hook（Interceptor，不需要 Bridge） | ✅ 可用 | 不依赖 bridge |

### 影响

- **PC 端 ObjC Bridge**（macOS/iOS）：同样受影响，Python SDK 需 `import ObjC from "frida-objc-bridge"`
- **移动端 Java Bridge**（Android）：同上，需 `import Java from "frida-java-bridge"`
- **纯 Native Hook**（Interceptor）：不受影响，纯 JS 字符串仍可用

### Python SDK 使用 Bridge 的方案

```typescript
// script.ts — 显式 import bridge
import ObjC from "frida-objc-bridge";  // 或 frida-java-bridge / frida-swift-bridge
```

```python
# Python 端
compiler = frida.Compiler()
bundle = compiler.build("script.ts", project_root="/tmp/project")
script = session.create_script(bundle)
script.load()
```

前置条件: 项目目录需 `npm install frida-objc-bridge`（或 `frida-java-bridge`）。Bundle 约 750KB。

### 快速判断

```
脚本是否使用了 Java / ObjC / Swift Bridge？
├── 否（纯 Interceptor / Memory / NativeFunction）→ 直接 session.create_script(js)
├── 是，且使用 frida CLI → 直接 -l script.js（bridge 内置）
└── 是，且使用 Python SDK → 必须用 frida.Compiler 编译 TypeScript
```

---

## Memory / Process / NativeFunction / Interceptor（无变化）

```javascript
// 以下全部正常，用法与 16.x 完全一致
var buf = Memory.alloc(256);
buf.writeU32(0x41414141);
var val = buf.readU8();
var bytes = buf.readByteArray(16);

Process.id;                                     // 当前 PID
Process.arch;                                   // 架构
Process.enumerateModules();                      // 枚举模块

var fn = new NativeFunction(addr, 'pointer', ['pointer', 'size_t']);

Interceptor.attach(targetAddr, {
    onEnter: function(args) { console.log("arg0=" + args[0]); },
    onLeave: function(retval) { console.log("return=" + retval); }
});
```

---

## 迁移检查清单

- [ ] 搜索 `Module.findExportByName` → 替换为 `Process.getModuleByName(mod).getExportByName(name)`
- [ ] 搜索 `Module.getExportByName` → 同上
- [ ] 搜索 `Module.findBaseAddress` → 替换为 `Process.getModuleByName(mod).baseAddress`
- [ ] 搜索 `Module.enumerateExports` → 替换为 `Process.getModuleByName(mod).enumerateExports()`
- [ ] Python SDK 中使用了 `Java`/`ObjC`/`Swift`？→ 必须走 `frida.Compiler` 编译
- [ ] Memory/Process/Interceptor/NativeFunction → 无需修改
