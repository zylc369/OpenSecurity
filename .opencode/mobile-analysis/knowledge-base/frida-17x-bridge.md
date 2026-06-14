# Frida 17.x Bridge 编译与使用指南（移动端）

> Frida 17.0.0 起，Java/ObjC/Swift Bridge 不再内置到 GumJS 运行时。
> **通用 API 变化速查**见 `$SHARED_DIR/knowledge-base/frida-17x-api.md`。
> 本文档专注于移动端（Android Java / iOS ObjC）的 Bridge 编译和使用细节。

---

## 变化背景

**Frida 17.0.0 重大变化**：Java/ObjC/Swift Bridge 不再捆绑在 GumJS runtime 中。

| Bridge | npm 包名 |
|--------|---------|
| Java Bridge | `frida-java-bridge` |
| ObjC Bridge | `frida-objc-bridge` |
| Swift Bridge | `frida-swift-bridge` |

这意味着：使用 `session.create_script(source)` 注入纯 JS 字符串时，全局对象 `Java`、`ObjC`、`Swift` **不存在**（`typeof Java === "undefined"`）。

---

## 方案一：frida CLI（最简单）

直接使用 `frida` 命令行加载 JS 脚本，无需任何额外步骤：

```bash
# Java Hook — REPL 内置 Java bridge，直接用
frida -H 127.0.0.1:6656 -n com.target.app -l hook.js
```

```javascript
// hook.js — Java bridge 自动可用
Java.perform(function() {
    var cls = Java.use("com.example.TargetClass");
    cls.targetMethod.implementation = function() {
        console.log("[*] hooked!");
        return this.targetMethod.apply(this, arguments);
    };
});
```

---

## 方案二：Python SDK + Compiler（推荐用于自动化）

### 前置条件

1. 项目目录需要有 `package.json` + `node_modules/frida-java-bridge`
2. 使用 TypeScript 脚本（`.ts`），显式 import bridge

### 项目初始化（首次）

```bash
mkdir -p /tmp/frida-project && cd /tmp/frida-project
npm init -y
npm install frida-java-bridge
# 如需 ObjC Bridge: npm install frida-objc-bridge
```

### TypeScript 脚本（显式 import）

```typescript
// hook.ts
import Java from "frida-java-bridge";

console.log("Java available:", Java.available);

if (Java.available) {
    Java.perform(function() {
        console.log("Java.androidVersion:", Java.androidVersion);
        
        var cls = Java.use("com.example.TargetClass");
        cls.targetMethod.implementation = function() {
            console.log("[*] hooked!");
            return this.targetMethod.apply(this, arguments);
        };
    });
}
```

### Python 调用代码

```python
import frida
import sys

def on_diagnostics(diag):
    print("[DIAG]", diag, file=sys.stderr)

def on_message(message, data):
    if message["type"] == "send":
        print(f"[SEND] {message['payload']}")
    elif message["type"] == "error":
        print(f"[ERROR] {message['description']}")
    else:
        print(f"[MSG] {message}")

# 1. 编译 TypeScript（显式 import bridge）
compiler = frida.Compiler()
compiler.on("diagnostics", on_diagnostics)
bundle = compiler.build("hook.ts", project_root="/tmp/frida-project")
# bundle 约 750KB（含 frida-java-bridge 运行时）

# 2. 连接设备
device = frida.get_device_manager().add_remote_device("127.0.0.1:6656")
pid = device.get_process("com.target.app").pid
session = device.attach(pid)

# 3. 用编译产物创建脚本
script = session.create_script(bundle)
script.on("message", on_message)

# 4. 加载
script.load()
print("Script loaded!")
```

### 关键参数

| 参数 | 说明 |
|------|------|
| `project_root` | 必须是包含 `node_modules/frida-java-bridge` 的目录 |
| `bundle` | 编译产物（约 750KB），直接传给 `session.create_script()` |
| 编译产物内容 | 包含 TypeScript 编译结果 + frida-java-bridge 运行时 + source map |

---

## 方案三：Python SDK + Compiler + ObjC Bridge

```typescript
// hook_ios.ts
import ObjC from "frida-objc-bridge";

console.log("ObjC available:", ObjC.available);

if (ObjC.available) {
    var hook = ObjC.classes.UIViewController["- viewDidLoad"];
    Interceptor.attach(hook.implementation, {
        onEnter: function(args) {
            console.log("[*] viewDidLoad called");
        }
    });
}
```

```bash
npm install frida-objc-bridge
```

Python 代码与方案二相同，只改 `.ts` 文件和 npm 包。

---

## 方案四：Python SDK 纯 Native Hook（无需 Bridge）

如果只需要 Native Hook（Interceptor），不需要 Java/ObjC Bridge：

```python
import frida

device = frida.get_device_manager().add_remote_device("127.0.0.1:6656")
session = device.attach(pid)

# 纯 JS 字符串，不需要 Compiler
js_code = """
var mod = Process.getModuleByName('libnative.so');
var funcAddr = mod.getExportByName('target_func');

Interceptor.attach(funcAddr, {
    onEnter: function(args) {
        console.log("[*] target_func called, arg0=" + args[0]);
    },
    onLeave: function(retval) {
        console.log("[*] return=" + retval);
    }
});
"""

# 直接用纯 JS 字符串即可
script = session.create_script(js_code)
script.on("message", lambda msg, data: print(msg))
script.load()
```

---

## 自动化脚本中的 Bridge 项目管理

对于需要 Java Bridge 的自动化脚本（如 DEX dump），推荐：

```python
import os
import subprocess
import tempfile

FRIDA_PROJECT_DIR = os.path.join(tempfile.gettempdir(), "frida-bridge-project")

def ensure_bridge_project():
    """确保 frida-bridge 项目目录存在且有 frida-java-bridge"""
    if not os.path.isdir(FRIDA_PROJECT_DIR):
        os.makedirs(FRIDA_PROJECT_DIR, exist_ok=True)
    
    package_json = os.path.join(FRIDA_PROJECT_DIR, "package.json")
    if not os.path.isfile(package_json):
        with open(package_json, 'w') as f:
            f.write('{"name": "frida-bridge", "version": "1.0.0"}')
    
    node_modules = os.path.join(FRIDA_PROJECT_DIR, "node_modules")
    if not os.path.isdir(os.path.join(node_modules, "frida-java-bridge")):
        subprocess.run(
            ["npm", "install", "frida-java-bridge"],
            cwd=FRIDA_PROJECT_DIR,
            capture_output=True,
            check=True
        )

def compile_java_hook(ts_source_code, ts_filename="hook.ts"):
    """编译包含 Java bridge 的 TypeScript 脚本"""
    ensure_bridge_project()
    
    ts_path = os.path.join(FRIDA_PROJECT_DIR, ts_filename)
    with open(ts_path, 'w') as f:
        f.write(ts_source_code)
    
    compiler = frida.Compiler()
    return compiler.build(ts_filename, project_root=FRIDA_PROJECT_DIR)
```

---

## 错误排查

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| `TypeError: Cannot read property 'perform' of undefined` | `Java` 为 `undefined`，使用了纯 JS 字符串 | 改用 `frida.Compiler` 编译 TypeScript |
| `Error: Cannot find module 'frida-java-bridge'` | 项目目录缺少 npm 包 | 在 `project_root` 目录执行 `npm install frida-java-bridge` |
| 编译后 `Java.available` 仍为 `false` | 目标进程无 Java VM（纯 native 进程） | 换用 attach 到含 Java VM 的进程 |
| `bundle` 过大（> 1MB） | source map 未压缩 | 使用 `frida_compile` 的压缩选项 |
| `npm install` 失败 | 无 Node.js 环境 | 安装 Node.js（`brew install node`） |

---

## 超时排查 SOP

### 症状

- CLI: `Failed to load script: timeout was reached`
- Python SDK: `frida.TransportError: timeout was reached`（在 `create_script()` 时）
- 任何脚本（包括几十字节的纯 Native 脚本）都无法加载

### 根因

frida-server 进程进入异常状态（残留 agent 未清理、进程僵死等），导致后续所有脚本注入超时。

### 排查流程（严格按顺序执行）

```
1. 确认症状：尝试加载一个最小纯 Native 脚本
   Python: session.create_script('console.log("ping"); rpc.exports={ping:function(){return 42;}};')
   CLI: echo 'console.log("ping");' > /tmp/ping.js && frida -U -p <PID> -l /tmp/ping.js

2. 最小脚本也超时 → frida-server 异常 → 重启 frida-server
   adb shell "kill -9 $(adb shell 'ps -A | grep <frida_server_name> | awk \"{print \\$2}\"')"
   sleep 2
   adb shell "nohup /data/local/tmp/<frida_server_path> -D &"
   sleep 3
   确认: adb shell "ps -A | grep <frida_server_name>"

3. 重启后系统性重试所有方案（按优先级）：
   a. CLI + Java bridge（最简单，优先试）→ frida -U -p <PID> -l hook.js
   b. Python SDK 纯 Native → session.create_script(small_js)
   c. Python SDK + Compiler（仅在 a/b 都不需要时）

   ⚠️ 关键：重启 server 后必须重新尝试所有方案，不能只试一个就放弃！
   之前的教训：重启后只测了 Python SDK 纯 Native（成功），没有重新试 CLI + Java bridge，
   误判为"Java bridge 在模拟器上不可用"。实际上重启后 CLI + Java bridge 完全正常。

4. 如果重启后 CLI + Java bridge 仍超时：
   - 检查 frida client 和 server 版本是否匹配（frida --version vs 下载的 server 版本）
   - 尝试 kill 目标 app 后重新启动再 attach
   - 尝试 spawn 模式：frida -U -f com.target.app -l hook.js
```

### 超时 vs 脚本错误区分

| 现象 | 类型 | 处理 |
|------|------|------|
| `timeout was reached`（加载阶段） | frida-server 异常 | 按 SOP 重启 server |
| `Error: Java is not defined`（运行阶段） | 脚本问题 | 用 Compiler 或改用 CLI |
| 脚本加载成功但运行时报错 | 业务逻辑问题 | 检查脚本内容 |
| Python SDK 大 bundle（>500KB）超时 | 传输速度问题 | 优先改用 CLI |
