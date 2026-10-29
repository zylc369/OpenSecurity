# 移动端常见安全模式

> 移动应用中常见的安全机制及其分析方法。

## SSL Pinning（证书固定）

### 原理

应用在客户端硬编码服务器证书或公钥的哈希值，即使系统信任了中间人证书，应用也会拒绝连接。

### 检测方法

```bash
# 1. 搜索证书相关代码
jadx -d java_src app.apk
grep -r "CertificatePinner\|sslPin\|TrustManager\|X509TrustManager\|pinning" java_src/

# 2. 搜索配置文件中的 pin
grep -r "pin-set\|pin digest" unpacked/res/
```

### 绕过方法

**方法 1: Frida Hook（推荐）**

```javascript
// OkHttp CertificatePinner Hook
Java.perform(function() {
    var CertificatePinner = Java.use("okhttp3.CertificatePinner");
    CertificatePinner.check.overload("java.lang.String", "java.util.List").implementation = function(hostname, peerCertificates) {
        console.log("[*] SSL Pinning bypassed for: " + hostname);
    };
});
```

```javascript
// TrustManager Hook（通用）
Java.perform(function() {
    var TrustManager = Java.use("javax.net.ssl.X509TrustManager");
    var SSLContext = Java.use("javax.net.ssl.SSLContext");

    var TrustManagerImpl = Java.registerClass({
        name: "com.bypass.TrustManager",
        implements: [TrustManager],
        methods: {
            checkClientTrusted: function(chain, authType) {},
            checkServerTrusted: function(chain, authType) {},
            getAcceptedIssuers: function() { return []; }
        }
    });

    SSLContext.init.overload("[Ljavax.net.ssl.TrustManager;", "[Ljavax.net.ssl.KeyManager;", "java.security.SecureRandom").implementation = function(tms, kms, sr) {
        this.init([TrustManagerImpl.$new()], kms, sr);
    };
});
```

**方法 2: 修改 APK**

```bash
# 反编译 → 修改 smali 中的证书校验逻辑 → 重打包
apktool d app.apk -o unpacked
# 编辑 smali 中 CertificatePinner.check 相关代码
apktool b unpacked -o modified.apk
```

**iOS SSL Pinning 绕过**

```javascript
// NSURLSession delegate Hook
var delegate = ObjC.classes.NSURLSession;
// 或使用 SSL Kill Switch 2 (越狱越备)
```

---

## Root/越狱检测

### Android Root 检测

| 检测方法 | 分析位置 |
|---------|---------|
| 检查 su 命令 | `Runtime.exec("which su")` |
| 检查 Superuser.apk | `File.exists("/system/app/Superuser.apk")` |
| 检查 Magisk | `File.exists("/sbin/magisk")` |
| SafetyNet attestation | Google Play Services API |
| 检查 SELinux | 读取 /proc/self/attr/current |

### Root 检测绕过

```javascript
Java.perform(function() {
    // Hook File.exists() — 隐藏特定路径
    var File = Java.use("java.io.File");
    File.exists.implementation = function() {
        var path = this.getAbsolutePath();
        var blocked = ["/sbin/su", "/system/bin/su", "/system/xbin/su",
                       "/data/local/bin/su", "/system/app/Superuser.apk",
                       "/sbin/magisk"];
        if (blocked.indexOf(path) !== -1) {
            console.log("[*] Root check bypassed: " + path);
            return false;
        }
        return this.exists();
    };
});
```

### Native 层 Root 检测绕过

部分应用不仅通过 Java API 检测 Root，还通过 native 层的系统调用检测。Java 层 Hook 不够用，需要同时 Hook native 函数。

#### 检测的 native 系统调用

| 系统调用 | 用途 | 参数 |
|---------|------|------|
| `access(path, F_OK)` | 检查文件是否存在 | `access("/system/bin/su", 0)` |
| `stat(path, &buf)` | 获取文件信息 | `stat("/sbin/magisk", &buf)` |
| `openat(dirfd, path, flags)` | 尝试打开文件 | `openat(AT_FDCWD, "/sbin/su", O_RDONLY)` |
| `Runtime.exec()` 多重载 | 执行 shell 命令 | `exec("which su")`, `exec(new String[]{"which", "su"})` |

#### 完整绕过脚本

```javascript
// 同时覆盖 Java 层 + Native 层的 Root 检测
// 路径列表集中定义，新增路径只需改一处
var BLOCKED_PATHS = [
    "/sbin/su", "/system/bin/su", "/system/xbin/su",
    "/data/local/bin/su", "/system/app/Superuser.apk",
    "/sbin/magisk"
];

// === Java 层 ===

Java.perform(function() {
    // 1. File.exists() — 隐藏路径
    var File = Java.use("java.io.File");
    File.exists.implementation = function() {
        var path = this.getAbsolutePath();
        if (BLOCKED_PATHS.indexOf(path) !== -1) {
            console.log("[*] Root check bypassed (File.exists): " + path);
            return false;
        }
        return this.exists();
    };
    
    // 2. Runtime.exec() — 拦截命令执行（注意多重载）
    var Runtime = Java.use("java.lang.Runtime");
    Runtime.exec.overload('[Ljava.lang.String;', '[Ljava.lang.String;', 'java.io.File').implementation = function(cmdArray, envp, dir) {
        var cmd = cmdArray[0];
        if (cmd.indexOf("su") !== -1 || cmd.indexOf("magisk") !== -1) {
            console.log("[*] Root check bypassed (exec array): " + cmd);
            throw Java.use("java.io.IOException").$new("Permission denied");
        }
        return this.exec(cmdArray, envp, dir);
    };
    Runtime.exec.overload('java.lang.String').implementation = function(cmd) {
        if (cmd.indexOf("su") !== -1 || cmd.indexOf("magisk") !== -1 || cmd.indexOf("which") !== -1) {
            console.log("[*] Root check bypassed (exec string): " + cmd);
            throw Java.use("java.io.IOException").$new("Permission denied");
        }
        return this.exec(cmd);
    };
});

// === Native 层 ===
// access/stat/openat 三个 Hook 结构相同，用工厂函数生成

var libc = Process.getModuleByName("libc.so");

function hookNativePathCheck(funcName, pathArgIndex) {
    Interceptor.attach(libc.getExportByName(funcName), {
        onEnter: function(args) {
            var path = args[pathArgIndex].readUtf8String();
            if (BLOCKED_PATHS.indexOf(path) !== -1) {
                console.log("[*] Root check bypassed (" + funcName + "): " + path);
                this.isBlocked = true;
            }
        },
        onLeave: function(retval) {
            if (this.isBlocked) {
                retval.replace(-1);
            }
        }
    });
}

hookNativePathCheck("access", 0);   // access(path, mode)
hookNativePathCheck("stat", 0);     // stat(path, buf)

// openat 必须单独处理：在 onEnter 中替换路径参数，而非 onLeave 改返回值
// 原因：openat 会真正打开文件，产生文件描述符。如果只改返回值，
//       内核已经打开了 su 文件，fd 泄露到 /proc/self/fd/ 可被检测到
Interceptor.attach(libc.getExportByName("openat"), {
    onEnter: function(args) {
        try {
            var path = args[1].readUtf8String();  // openat 的路径在 args[1]（args[0] 是 dirfd）
            if (path && BLOCKED_PATHS.indexOf(path) !== -1) {
                console.log("[*] Root check bypassed (openat): " + path);
                // 替换路径参数为不存在的路径，从根本上阻止打开
                args[1] = Memory.allocUtf8String("/nonexistent_path_bypass");
            }
        } catch(e) {}
    }
});

console.log("[+] Root bypass loaded (Java + Native layers)");
```

**注意事项**：
- `Runtime.exec()` 有多个重载（String/String数组+envp+dir），需要分别 Hook
- `openat` 的第一个参数是 `dirfd`（通常是 `AT_FDCWD = -100`），路径在第二个参数 `args[1]`
- `access`/`stat` 用 onLeave 改返回值即可（只查询不产生副作用）
- `openat` 必须在 onEnter 中替换路径参数（不能等 onLeave，因为内核已经打开了文件，会泄露 fd）

### iOS 越狱检测

检测分为三层：ObjC API 层（fileExists / canOpenURL）、libc 层（stat/access/fopen/fork/getppid）、dyld 层（加载镜像名扫描）。逐层覆盖才能稳定绕过。

| 检测方法 | 分析位置 | 绕过 hook 点 |
|---------|---------|------------|
| 路径存在检查 | `FileManager.fileExists(atPath:)` 遍历 Cydia/Sileo/bash 清单 | `-[NSFileManager fileExistsAtPath:]` 返回 NO |
| URL scheme 可达 | `UIApplication.canOpenURL` 探测 `cydia://`/`sileo://`/`zbra://`/`filza://` | `-[UIApplication canOpenURL:]` 对越狱 scheme 返回 NO |
| dyld 镜像扫描 | `_dyld_get_image_name` 枚举找 MobileSubstrate/TweakInject | `_dyld_get_image_name` 返回值重写为良性名 |
| fork 探测 | 非越狱沙箱禁止 fork（返回 -1），越狱后返回有效 PID | `fork` 返回值替换 -1 |
| getppid 探测 | 正常父进程是 launchd(1)，越狱后可能不同 | `getppid` 返回值替换 1 |
| libc 直接路径检查 | `stat`/`access`/`fopen` 检查同一路径清单 | `libsystem_kernel.dylib` 各导出 + 同样的路径过滤 |
| /etc/passwd 异常 | 非 JB 设备该文件为默认内容 | 低频，按需 hook fopen |

**Swift private 方法陷阱**：检测方法声明为 `private`（无 `@objc` thunk）时，ObjC selector 不可达，无法按类名 hook——改为 hook 它们调用的 OS 函数（上表第三列）。selector 被剥离/混淆的真实 app 同样适用此策略。

**组合 drop-in 脚本**（覆盖两大 ObjC 检测 + 三个 libc 信号）：

```javascript
// frida -U -f com.target.app --no-pause -l ios-jb-bypass.js
setTimeout(function () {
    var blockedPaths = ['/Applications/Cydia.app', '/Applications/Sileo.app',
        '/Applications/Zebra.app', '/Applications/Filza.app',
        '/private/var/lib/apt/', '/private/var/lib/cydia/',
        '/usr/bin/ssh', '/usr/libexec/sshd', '/bin/bash',
        '/etc/apt/', '/var/lib/undecimus/', '/usr/share/jailbreak/'];
    var blockedSchemes = ['cydia', 'sileo', 'zbra', 'filza', 'undecimus'];

    // 1. NSFileManager.fileExistsAtPath: — 一个 hook 覆盖整个路径清单
    var NSFM = ObjC.classes.NSFileManager;
    Interceptor.attach(NSFM['- fileExistsAtPath:'].implementation, {
        onEnter: function (args) {
            var p = new ObjC.Object(args[2]).toString();
            for (var i = 0; i < blockedPaths.length; i++) {
                if (p.indexOf(blockedPaths[i]) === 0) { this.block = true; break; }
            }
        },
        onLeave: function (retval) { if (this.block) retval.replace(0); }
    });

    // 2. UIApplication.canOpenURL: — URL scheme 检测
    var UIApp = ObjC.classes.UIApplication;
    Interceptor.attach(UIApp['- canOpenURL:'].implementation, {
        onEnter: function (args) {
            var u = new ObjC.Object(args[2]).toString();
            for (var i = 0; i < blockedSchemes.length; i++) {
                if (u.indexOf(blockedSchemes[i] + '://') === 0) { this.block = true; break; }
            }
        },
        onLeave: function (retval) { if (this.block) retval.replace(0); }
    });

    // 3. fork/getppid 伪造（libsystem_kernel.dylib）
    var kernLib = Process.findModuleByName('libsystem_kernel.dylib');
    if (kernLib) {
        var fork = kernLib.findExportByName('fork');
        if (fork) Interceptor.attach(fork, {
            onLeave: function (retval) { retval.replace(-1); }
        });
        var getppid = kernLib.findExportByName('getppid');
        if (getppid) Interceptor.attach(getppid, {
            onLeave: function (retval) { retval.replace(1); }
        });
    }

    // 4. dyld 镜像名重写 — 检测只见良性库
    var dyldLib = Process.findModuleByName('libdyld.dylib');
    if (dyldLib) {
        var dyld = dyldLib.findExportByName('_dyld_get_image_name');
        if (dyld) Interceptor.attach(dyld, {
            onLeave: function (retval) {
                var name = retval.readCString();
                if (name && /Substrate|TweakInject|frida|libtweakinject/.test(name)) {
                    retval.replace(Memory.allocUtf8String('libSystem.B.dylib'));
                }
            }
        });
    }

    console.log('[*] iOS JB bypass hooks armed');
}, 500);
```

**识别"绕不过"的情形**：以上全部生效但 app 仍崩溃/退出 → 大概率是二进制完整性校验（对 `__TEXT` 段算 SHA-256 与硬编码值 memcmp）。此类不依赖文件存在或系统调用，需定位 memcmp 比较点直接 patch（改恒等）或在每个校验窗口前恢复原始字节。

---

## 代码混淆

### ProGuard / R8（Android）

**识别特征**:
- 类名/方法名为 `a.b.c`、`a.b.d` 等短名
- 反编译后大量无意义命名
- 通常保留了 Application/Activity 等关键类名

**分析策略**:

```
1. jadx --deobf 反编译 → jadx 自动重命名（a→a_b_c）
2. 搜索字符串常量 → 从字符串反推方法用途
3. 搜索 API 调用 → 从系统调用反推逻辑
4. 检查 mapping 文件（如果有的话）→ 还原原始名称
5. 结合 smali 精读 → jadx 不可读的部分
```

### OLLVM / 控制流平坦化

**识别特征**:
- 大量 switch/dispatcher 结构
- while(1) 循环内 switch
- IDA Pro 中 CFG 呈"意大利面条"状

**分析策略**:

```
1. 识别 dispatcher 变量（通常是一个整数）
2. 追踪 dispatcher 的赋值链
3. 还原真实的控制流（忽略混淆的跳转）
4. 使用 IDA Pro 的 HexRays 反编译 + 手动修正
5. 如无法还原 → 使用动态分析（Frida Hook）绕过
```

### 字符串混淆（String Encryption）运行时还原

**识别特征**（jadx 反编译输出）：
- 界面/逻辑字符串字面量消失，取而代之 `SomeDeobfuscator.getString(-548601664941L)` 形态调用
- 常见混淆库：`com.joom.paranoid`（`Deobfuscator$app$Release.getString(long)`）、DexGuard 字符串加密（同类 long/short 参数模式）

**还原方法**（无需逆向解密算法，直接调用解密器）：
1. jadx 中收集所有传给 getString 的 long 参数值（grep 调用点）
2. Frida 批量调用还原：

```javascript
Java.perform(function() {
    var f = Java.use("com.joom.paranoid.Deobfuscator$app$Release");
    // 替换为实际收集到的 long 值列表
    var longs = [-548601664941, -3140818349, -28910622125, -308083496365, -338148267437];
    for (var i = 0; i < longs.length; i++) {
        console.log(longs[i] + " -> " + f.getString(longs[i]));
    }
});
```

**要点**：getString 是纯解密函数（输入 long → 输出明文），静态对照调用点上下文（哪个方法取了这个字符串）即可知道每条明文的用途。

---

## 反调试

### 常见反调试技术

| 技术 | 平台 | 检测方法 |
|------|------|---------|
| `ptrace(PTRACE_TRACEME)` | Android | 检查 `/proc/self/status` 的 TracerPid |
| `android.os.Debug.isDebuggerConnected()` | Android | Java 层调试检测 |
| `sysctl` 检查 P_TRACED flag | iOS | BSD 层调试检测 |
| 检测断点指令 | 通用 | 代码完整性校验 |
| 时间检测（rdtsc） | 通用 | 检测单步执行 |

### 反调试绕过

```javascript
// Android: Hook ptrace
var libc = Process.getModuleByName("libc.so");
Interceptor.attach(libc.getExportByName("ptrace"), {
    onEnter: function(args) {
        if (args[0].toInt32() === 0) {  // PTRACE_TRACEME
            console.log("[*] Anti-debug: ptrace(TRACEME) bypassed");
            args[0] = ptr(-1);  // 改为无效请求
        }
    }
});

// Android: Hook Debug.isDebuggerConnected
Java.perform(function() {
    var Debug = Java.use("android.os.Debug");
    Debug.isDebuggerConnected.implementation = function() {
        console.log("[*] Anti-debug: isDebuggerConnected bypassed");
        return false;
    };
});
```

---

## 完整性校验

### 常见校验方式

| 方式 | 分析方法 |
|------|---------|
| APK 签名校验 | 提取签名证书对比 → 搜索 `PackageManager.GET_SIGNATURES` |
| .so 文件哈希校验 | 定位校验代码 → Patch 跳过 |
| dex CRC 校验 | 搜索 `CRC32`/`Adler32` 调用 |
| assets 文件校验 | 搜索 `MessageDigest`/`DigestUtils` |

### 绕过方法

```
1. 定位校验函数（搜索相关 API 调用）
2. Frida Hook 使校验函数始终返回成功
3. 或直接 Patch 二进制（条件跳转 → 无条件跳转）
```

---

## IPC 安全漏洞

### 概述

Android 应用的四大组件（Activity/Service/Receiver/Provider）可以通过 `android:exported` 属性暴露给其他应用。如果 exported 组件没有配合 permission 保护，任何第三方应用都可以触发它，导致未授权操作。

这是移动端最常见的架构级漏洞之一，不需要 Frida、不需要 root，只需要标准 Android API。

### Exported Component 审计清单

在 `AndroidManifest.xml` 中逐个检查以下危险信号：

| 组件类型 | 危险信号 | 检查方法 |
|---------|---------|---------|
| `<service>` | `exported="true"` 且无 `android:permission` | grep `exported.*true` 后检查同标签是否有 `permission` 属性 |
| `<receiver>` | `exported="true"` 且无 `android:permission` | 同上 |
| `<provider>` | `exported="true"` 且无 `android:permission` | 同上，额外检查 `grantUriPermissions` |
| `<activity>` | `exported="true"` 且无 intent-filter（不应导出） | 非入口 Activity 不应 exported |

**快速审计命令**：

```bash
# 列出所有 exported 组件及其 permission 状态
apktool d app.apk -o unpacked
grep -n 'exported="true"' unpacked/AndroidManifest.xml
# 对每个匹配行，检查同一标签是否有 android:permission 属性
```

**关键判断**：

- `exported="true"` + 有 `android:permission` → ✅ 有保护（需检查 permission 级别）
- `exported="true"` + 无 `android:permission` → 🚨 无保护，任何应用可调用
- `exported="true"` + `<intent-filter>` → 在 Android 12+ 必须显式设 `exported="true"`，旧版本默认 exported

### Permission 配置审计

**正确 vs 错误对比**：

```xml
<!-- ❌ 错误：exported 但无 permission -->
<service android:exported="true" android:name=".SecurityService"/>

<!-- ❌ 错误：用了 normal/dangerous 级别 permission（第三方可申请） -->
<permission android:name="com.example.MY_PERM" android:protectionLevel="normal"/>
<service android:exported="true" android:permission="com.example.MY_PERM" .../>

<!-- ✅ 正确：signature 级别 permission（只有同签名应用可获取） -->
<permission android:name="com.example.MY_PERM" android:protectionLevel="signature"/>
<uses-permission android:name="com.example.MY_PERM"/>
<service android:exported="true" android:permission="com.example.MY_PERM" .../>
```

**protectionLevel 含义**：

| 级别 | 谁能获取 | 安全性 |
|------|---------|--------|
| `normal` | 所有应用 | ❌ 无保护 |
| `dangerous` | 用户授权 | ❌ 用户可能被诱导授权 |
| `signature` | 同签名应用 | ✅ 安全 |
| `signatureOrSystem` | 同签名或系统应用 | ✅ 安全 |

### Broadcast 劫持

**场景**：`BroadcastReceiver` 是 `exported=true` 且无 permission 保护，任何应用可以向它发送恶意广播。

**攻击步骤**：

```bash
# 1. 从 Manifest 中找到 Receiver 的 action 名称
#    <action android:name="com.example.SOME_ACTION"/>

# 2. 发送广播（携带 extras 伪造参数）
adb shell am broadcast \
    -n com.example/.TargetReceiver \
    -a com.example.SOME_ACTION \
    --es key 'value'

# 3. 如果 Receiver 转发给 Service，直接攻击 Receiver 通常更隐蔽
#    因为 Receiver 不验证发送者身份
```

**常见利用场景**：

| 场景 | action | 影响 |
|------|--------|------|
| 禁用安全功能 | `STOP_SECURITY` / `STOP_PROTECTION` | 安全服务停止 |
| 启动未授权操作 | `START_*` 类 action | 触发付费/危险操作 |
| 修改配置 | `UPDATE_CONFIG` / `SET_*` | 篡改应用状态 |
| 绕过认证 | 携带伪造 token 的 extras | 伪造合法调用 |

### Service 伪造

**场景**：`Service` 是 `exported=true` 且无 permission 保护，任何应用可以 `startService` 或 `bindService`。

**攻击步骤**：

```bash
# 1. 从 Manifest 找到 Service 类名
#    <service android:exported="true" android:name=".SecurityService"/>

# 2. 通过 am startservice 发送指令
adb shell am startservice \
    -n com.example/.SecurityService \
    -a com.example.START_SECURITY \
    --es security_token 'extracted_token'

# 3. 验证 Service 状态变化
adb shell dumpsys activity services com.example
```

### Token 提取配合 IPC 攻击

当 IPC 组件需要 token 认证时，token 通常可以从以下位置提取：

| Token 位置 | 提取方法 | 难度 |
|-----------|---------|------|
| Java 代码硬编码 | jadx 反编译 → 搜索字符串常量 | 低 |
| Native library（.so） | `strings lib/*.so` → 搜索特征前缀 | 低 |
| SharedPreferences | adb shell `cat /data/data/pkg/shared_prefs/*.xml`（需 root） | 中 |
| APK 资源文件 | apktool 解包 → 搜索 res/assets | 低 |
| 运行时从 APK 提取 | PackageManager.getSourceDir() → ZipInputStream → strings | 低 |

**运行时提取示例（PoC 代码片段）**：

```java
// 从 victim APK 中提取 .so 文件并搜索 token
ApplicationInfo info = pm.getApplicationInfo(victimPackage, 0);
ZipInputStream zis = new ZipInputStream(new FileInputStream(info.sourceDir));
// 遍历 ZIP 条目，找到 lib/*/libxxx.so
// 在二进制数据中搜索已知前缀的可打印字符串
```

### 快速验证流程

不需要写 PoC 就能快速验证 IPC 漏洞：

```bash
# Step 1: 确认 victim 应用已安装
adb shell pm list packages | grep <victim>

# Step 2: 启动 victim 的目标组件（通过 exported Service）
adb shell am startservice -n <pkg>/.<Service> -a <ACTION> --es <key> '<value>'

# Step 3: 检查组件状态变化
adb shell dumpsys activity services <pkg>
adb shell dumpsys activity broadcasts <pkg>

# Step 4: 如果验证成功，再开发正式 PoC APK
```

### 防御建议

| 防御点 | 具体措施 | 阻断的攻击 |
|--------|---------|-----------|
| Component exported | 不需要外部访问的组件设 `exported="false"` | 所有 IPC 攻击 |
| Permission 保护 | exported 组件加 `android:permission` + `protectionLevel="signature"` | 第三方应用调用 |
| Sender 验证 | 代码中检查 `Binder.getCallingUid()` 和包名 | 即使 token 泄露 |
| Token 动态化 | 运行时生成 token，存储在 Android Keystore 中 | 静态提取攻击 |
| Intent 验证 | 验证 intent 的 action、extras 类型和值范围 | 参数注入 |

---

## Android 逆向模式

### JNI RegisterNatives 混淆

Java native 方法无对应 Java_ 前缀符号 + JNI_OnLoad 存在 = RegisterNatives 手动注册（名与符号解耦）。定位: JNI_OnLoad → RegisterNatives(env,clazz,methods,n) → methods 数组 {name,signature,fnPtr} 三元组 → fnPtr 即真 handler。静态分析选 lib/**x86_64**/（Ghidra 反编译质量最好）。

### Java 层验证整体绕过三捷径

1. **新工程直调 native**: 新建工程用相同包名/类名/方法签名 + loadLibrary 原 .so → 直接调 native 函数，全部 Java 验证（PIN/随机/root 检测）绕过
2. **DEX 运行时 patch 重建**: native 经 /proc/self/maps+mprotect XOR patch DEX（仅 Dalvik<21）→ 从 .so 提 key+offset 对静态 DEX 同 patch + **重算 checksum/SHA-1** 再反编译
3. **LocalBroadcastManager 破局**: 本地广播 adb 发不进——onReceive 体克隆内联进 onCreate+输出改 Log.d → apktool b 重打包 + debug keystore 签名 → logcat 看明文

### Native 反检测 so 替换法

**场景**：某个 .so 内的反 Frida/反 root 检测过强（高度混淆 + 字符串加密，静态无法分析、常见 bypass 脚本全部失效，app 启动即崩）。

**思路**：不再绕过检测，直接把该 .so 换成空壳——检测代码根本不运行。

**步骤**：
1. 确认跑检测的是哪个 so：崩溃回溯中的 `base.apk!libxxx.so (offset ...)` 即检测载体
2. 写空壳 stub.c：只含 `JNI_OnLoad` 返回 JNI_VERSION + 业务必需的 JNI 导出函数（签名保持，函数体直接 return）

```c
#include <jni.h>
JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved) {
    return JNI_VERSION_1_6;
}
// 按 Ghidra 中原 so 的导出表，补齐同签名空实现，例如:
// JNIEXPORT jstring JNICALL Java_com_xxx_stringFromJNI(JNIEnv *env, jobject t) { return (*env)->NewStringUTF(env, ""); }
```

3. NDK 按目标架构编译（arm64 示例，clang 在 `$NDK_HOME/toolchains/llvm/prebuilt/<host>/bin/` 下）：
   `aarch64-linux-android24-clang stub.c -shared -fPIC -o libxxx.so`
   → 替换 APK 中对应 `lib/<arch>/libxxx.so`
4. 重签安装：`java -jar uber-apk-signer-1.3.0.jar -a app.apk` → `adb uninstall <pkg>` → `adb install app-aligned.apk`

**代价**：被替换 so 中的业务逻辑（如 flag 校验、解密）一并失效——适用于"检测 so 与业务 so 分离"的 app；若同一 so 既检测又藏 flag，替换后需从另一个 so 或纯 Java 层继续分析。

### 动态三式

> Firebase 相关的完整攻击面（RTDB/Firestore/App Check/签名伪造）见 `$AGENT_DIR/knowledge-base/mobile-firebase-backend.md`。

- **Firebase Cloud Functions 直调**: 认证后 Frida 构造 payload（uid+值+时间戳）直调 getHttpsCallable("validateX")——AppCheck 信任客户端构造
- **Frida 调类方法免抓包**: 秘密在方法里直接 Java.use 调，不用绕证书锁定
- **logcat 密钥泄漏**: `adb logcat | grep -iE "agreement|ephemeral|shared|key"` 收集后重建 AES 参数
- **JNI 签名绕过**: 断 XOR 解密后 dump 明文 key + baksmali 改**被签参数**重打包——免逆完整签名算法


---

## macOS/iOS 逆向补集

- **objc_msgSend 调度**: RDI=self, RSI=selector; selector 在 __objc_methname 节——交叉引用找实现。lldb: `expression -l objc -O -- [[Cls new] meth]`。method_exchangeImplementations/class_replaceMethod=反篡改 swizzle
- **Swift**: VWT（类型操作）/PWT（动态分发）; swift_allocObject/release/once; String ≤15B 内联。__swift5_types/__swift5_proto Ghidra Swift 模块解析
- **iOS 脱壳**: LC_ENCRYPTION_INFO cryptid=1=FairPlay → frida-ios-dump -H <IP> -p 22 / Clutch / bfdecrypt
- **fat 二进制**: lipo -info / -thin arm64 -output
- **注入**: DYLD_INSERT_LIBRARIES（hardened runtime/SIP 屏蔽系统件）; DYLD_PRINT_LIBRARIES 看加载
- **越狱检测绕过**: 三向量完整 hook 集（NSFileManager/canOpenURL/dyld/fork/getppid）见上方「iOS 越狱检测」小节；libc access 层路径命中 Cydia//bin/sh//etc/apt 清单时 retval.replace(-1)
- iOS 固件/平台其他主题见 binary-analysis platform-reversing.md
