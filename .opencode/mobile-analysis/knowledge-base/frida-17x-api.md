# Frida 17.x API 变化速查（移动端补充）

> **通用 API 变化（Module/Memory/Process/Bridge 概述）已沉淀到通用知识库，请先读取:**
>
> `Read $SHARED_DIR/knowledge-base/frida-17x-api.md`
>
> 本文件仅包含移动端特有的补充说明。

---

## 移动端特有说明

### 1. Java Bridge 编译方案（移动端最常用）

Android Hook 需要使用 Java Bridge。Python SDK 中完整编译方案见 `$AGENT_DIR/knowledge-base/frida-17x-bridge.md`。

核心要点：
- Python SDK `session.create_script("Java.perform(...)")` ❌ 不可用（Java 为 undefined）
- 必须用 `frida.Compiler` 编译 TypeScript（`import Java from "frida-java-bridge"`）
- frida CLI 中 Java bridge 内置，可直接用

### 2. ObjC Bridge 编译方案（iOS）

iOS Hook 需要使用 ObjC Bridge：
- `import ObjC from "frida-objc-bridge"`
- 其余流程与 Java Bridge 相同（frida.Compiler 编译）

### 3. 移动端常见 Module 操作

```javascript
// 获取 libnative.so 的导出（Android）
var mod = Process.getModuleByName("libnative-lib.so");
var funcAddr = mod.getExportByName("target_func");

// 延迟加载场景（SO 可能尚未加载）
var mod = Process.findModuleByName("libnative-lib.so");
if (!mod) {
    // 等待 SO 加载后再 hook
}
```
