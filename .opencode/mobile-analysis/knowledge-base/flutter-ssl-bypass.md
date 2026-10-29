# Flutter 应用 SSL Pinning Bypass 方法论

> Flutter 应用的 SSL pinning 在 native 层实现（libflutter.so），不经过 Java TLS。本文档描述完整的定位和绕过流程。
> 适用于：Flutter 编译的 Android/iOS 应用，需要拦截 HTTPS 流量时。

---

## 1. 架构确认（第一步必做）

Flutter 应用可能包含多个架构的 libflutter.so。**必须先确认设备实际运行的架构**，否则所有分析作废。

```bash
# 方法 1：直接查设备（推荐）
adb shell uname -m
# 输出 aarch64 → arm64-v8a
# 输出 x86_64 → x86_64

# 方法 2：查系统属性
adb shell getprop ro.product.cpu.abi
```

**常见错误**：模拟器显示 `x86_64` 但实际运行 `aarch64`（ARM 翻译层）。以 `uname -m` 为准。

确认架构后，从设备拉取实际运行的 libflutter.so：

```bash
# 找到应用的数据目录
adb shell pm path com.target.app
# package:/data/app/~~xxx/com.target.app-xxx/base.apk

# 拉取对应架构的 libflutter.so
adb pull /data/app/~~xxx/com.target.app-xxx/lib/arm64/libflutter.so ./
```

---

## 2. 定位 TrustBuiltinRoots 函数

Flutter SSL pinning 的核心是 `TrustBuiltinRoots` 函数，它在 libflutter.so 的 Dart VM 中。该函数接收 `SSLFilter` 的 native peer 指针，负责将系统 CA 证书加载到 SSL 上下文。

### 2.1 字符串搜索

在 IDA 中搜索字符串 `TrustBuiltinRoots`：

```python
# IDAPython：搜索 TrustBuiltinRoots 字符串
import idautils
import idc

for s in idautils.Strings():
    if "TrustBuiltinRoots" in str(s):
        addr = s.ea
        print("Found at 0x%X: %s" % (addr, str(s)))
```

如果字符串存在，通过交叉引用定位到函数。

### 2.2 ADRP+ADD 引用定位（无符号 libflutter.so）

Flutter Engine 通常是无符号的（剥离了符号表），字符串通过 arm64 的 ADRP+ADD 指令对引用。需要用 IDAPython 脚本搜索：

```python
# IDAPython：ADRP+ADD 字符串引用搜索
# 详见 $SHARED_DIR/knowledge-base/arm64-reverse-methodology.md
import idautils
import idc
import ida_bytes

target_str = "TrustBuiltinRoots"
results = []

for seg in idautils.Segments():
    seg_start = idc.get_segm_start(seg)
    seg_end = idc.get_segm_end(seg)
    seg_name = idc.get_segm_name(seg)
    
    # 在 .rodata 中搜索字符串
    if '.rodata' in seg_name or '.data' in seg_name:
        ea = seg_start
        while ea < seg_end:
            s = idc.get_strlit_contents(ea)
            if s and target_str in s.decode('utf-8', errors='ignore'):
                print("[+] String '%s' at 0x%X" % (target_str, ea))
                # 查找交叉引用
                for xref in idautils.XrefsTo(ea):
                    func = idc.get_func_name(xref.frm)
                    print("    Referenced from 0x%X (func: %s)" % (xref.frm, func))
                    results.append((ea, xref.frm, func))
                break
            ea = idc.next_head(ea, seg_end)

if not results:
    print("[-] String not found, trying manual search with Search > Text")
```

### 2.3 反编译确认

找到引用字符串的函数后，反编译确认特征：

- 函数接收一个指针参数（native peer）
- 通过 `peer + 偏移` 访问 X509_STORE
- 调用 `X509_STORE_add_cert` / `X509_STORE_set_default_paths` 等 OpenSSL API

---

## 3. 调用策略：借鸡生蛋

`TrustBuiltinRoots` 本身不是导出函数，无法直接通过地址调用。需要找到调用它的上下文。

### 3.1 定位 native peer 提取器

搜索 `SSLFilter` 相关函数，找到从 Dart 对象提取 native peer 的函数。通常特征：

```c
// 典型的 native peer 提取器
void* sub_XXXXX(void* dart_obj) {
    return *(void**)(dart_obj + 16);  // peer 在 offset 16
}
```

### 3.2 Hook 策略

Hook native peer 提取器，在其 `onEnter` 中获取 peer 指针，然后用 `NativeFunction` 调用 `TrustBuiltinRoots`：

```javascript
// Frida: 借鸡生蛋调用 TrustBuiltinRoots（纯 native，不需要 Java.perform）
var libflutter = Process.getModuleByName("libflutter.so");

// TrustBuiltinRoots 地址（从 IDA 确认）
var TrustBuiltinRoots = new NativeFunction(
    libflutter.base.add(0xXXXXXX),  // 替换为实际偏移
    'pointer',
    ['pointer']
);

// Hook native peer 提取器（sub_XXXXX）
var peerExtractor = libflutter.base.add(0xYYYYYY);  // 替换为实际偏移
Interceptor.attach(peerExtractor, {
    onEnter: function(args) {
        // args[0] 就是 native peer
        var peer = args[0];
        
        // 调用 TrustBuiltinRoots(peer) 重新加载系统 CA
        try {
            TrustBuiltinRoots(peer);
            console.log("[+] TrustBuiltinRoots called with peer: " + peer);
        } catch (e) {
            console.log("[-] TrustBuiltinRoots failed: " + e);
        }
    }
});
```

### 3.3 X509_STORE 内存布局

`TrustBuiltinRoots` 内部访问 X509_STORE 的路径：

```
peer (native peer 指针)
  └─ *(peer + 16) = SSL 对象指针
       └─ *(SSL对象 + 104) = X509_STORE 指针
```

验证公式（在 Frida 中）：

```javascript
// 验证 X509_STORE 路径
var peer = args[0];
var sslObj = peer.add(16).readPointer();
var store = sslObj.add(104).readPointer();
console.log("[*] X509_STORE at: " + store);
```

---

## 4. spawn vs attach 策略

### 4.1 为什么 Flutter 必须用 spawn

Flutter 应用的 SSL 初始化在启动阶段（`Dart_Initialize` → 创建 `SSLFilter`）。如果用 attach 模式：

- SSL 已经初始化完成，`TrustBuiltinRoots` 已经执行过
- Hook 来不及生效，SSL pinning 已经在起作用
- Root 检测也在启动阶段执行，attach 时应用已经退出

### 4.2 spawn 模式用法

```bash
# Frida CLI spawn 模式
frida -U -f com.target.app -l bypass.js --no-pause

# Python SDK spawn 模式
import frida
device = frida.get_usb_device()
pid = device.spawn(["com.target.app"])
session = device.attach(pid)
script = session.create_script(open("bypass.js").read())
script.load()
device.resume(pid)
```

### 4.3 spawn 失败排查

spawn 模式偶尔失败（`Failed to spawn: unable to connect to remote frida-server`）：

| 现象 | 原因 | 解决 |
|------|------|------|
| `unable to connect` | frida-server 未运行或端口不通 | 重启 frida-server |
| `unable to connect` | adb 连接不稳定 | `adb kill-server && adb start-server` |
| `process crashed` | 应用检测到 Frida | 反检测措施见 `$AGENT_DIR/knowledge-base/mobile-frida.md` |
| 间歇性失败 | 设备性能不足或 frida-server 竞争 | 重试 2-3 次；如果持续失败，改 attach + 手动先 kill 再 attach |
| Android 10 上稳定复现 `remote connection error` | frida < 17.15.2 的已知 bug（XOM 使 libstagefright execute-only，payload 无法运行） | 升级 frida/frida-server 到 ≥17.15.2，无需绕 |

---

## 5. 常见失败模式

### 5.1 证书过期

SSL bypass 成功但应用仍拒绝连接。检查代理工具使用的 CA 证书：

```bash
# 查看证书有效期
openssl x509 -in ca.crt -noout -dates
# 如果 notAfter 已过期，需要重新生成

# 常见问题：Let's Encrypt R11 vs R13 交叉签名链
# 旧证书可能使用已过期的 R11 中间 CA
# 解决：更新代理工具的证书，或使用最新的根证书
```

### 5.2 libflutter.so 版本差异

不同 Flutter 版本的 libflutter.so 偏移不同。**必须用设备上实际运行的 libflutter.so 分析**，不能用其他版本。

```bash
# 确认 libflutter.so 的版本
adb shell md5sum /data/app/*/com.target.app-*/lib/arm64/libflutter.so
# 与本地分析版本对比
md5sum ./libflutter.so
```

### 5.3 Flutter 编译模式

| 编译模式 | 特征 | 影响 |
|---------|------|------|
| Debug | 包含调试符号、Dart VM Service | 容易分析和 Hook |
| Profile | 部分优化 | 中等难度 |
| Release | 完全优化、符号剥离 | 需要字符串+ADRP 定位 |

Release 模式下 `TrustBuiltinRoots` 字符串可能被优化掉。替代方案：
1. 搜索 `X509_STORE_add_cert` 导入，反向定位调用者
2. 搜索 `SSL_CTX_set_verify` 调用链
3. 直接 Hook OpenSSL 层（`SSL_CTX_set_verify` 设为 NULL）

---

## 6. 完整 Bypass 脚本模板

```javascript
// flutter_ssl_bypass.js — Flutter SSL Pinning Bypass
// 使用方式: frida -U -f com.target.app -l flutter_ssl_bypass.js --no-pause
//
// 注意: TrustBuiltinRoots 是 native 函数，Interceptor 是 native API，
//       不需要 Java.perform（纯 native 操作）
//
// 使用前必须修改:
//   TRUST_BUILTIN_ROOTS_OFFSET — TrustBuiltinRoots 偏移（从 IDA 确认）
//   PEER_EXTRACTOR_OFFSET — native peer 提取器偏移（从 IDA 确认）

var TRUST_BUILTIN_ROOTS_OFFSET = 0xXXXXXX;  // TODO: 从 IDA 确认
var PEER_EXTRACTOR_OFFSET = 0xYYYYYY;        // TODO: 从 IDA 确认

var libflutter = Process.getModuleByName("libflutter.so");
console.log("[*] libflutter base: " + libflutter.base);

var TrustBuiltinRoots = new NativeFunction(
    libflutter.base.add(TRUST_BUILTIN_ROOTS_OFFSET),
    'pointer',
    ['pointer']
);

Interceptor.attach(libflutter.base.add(PEER_EXTRACTOR_OFFSET), {
    onEnter: function(args) {
        var peer = args[0];
        console.log("[*] Captured native peer: " + peer);
        try {
            TrustBuiltinRoots(peer);
            console.log("[+] TrustBuiltinRoots called — system CA loaded");
        } catch (e) {
            console.log("[-] Error: " + e);
        }
    }
});

console.log("[+] Flutter SSL bypass script loaded");
```

---

## 7. 替代路线：BoringSSL 验证函数模式扫描法

TrustBuiltinRoots 借鸡生蛋法（§2-§6）依赖逆向定位偏移。社区标准替代方案是 **disable-flutter-tls**（NVISOsecurity 维护，Frida Codeshare: `TheDauntless/disable-flutter-tls-v1`）：

```bash
frida -U -f com.example.target --codeshare TheDauntless/disable-flutter-tls-v1 --no-pause
```

- **目标函数**：BoringSSL `ssl_verify_peer_cert`（handshake.cc）——证书校验的总入口
- **定位方式**：内存字节模式匹配，内置 arm64/arm/x64/x86 × Android/iOS 的 pattern 集，无需手工逆向偏移
- **bypass**：替换实现恒返回 0（校验通过）
- **版本适配**：pattern 随 Flutter SDK 版本变化，脚本更新滞后时旧 pattern 匹配失败——此时回落到 reFlutter 或 §6 手工偏移法

### 7.1 timing 陷阱：库未加载完导致静默失败

Frida attach 时 `libflutter.so` 可能尚未加载完 → 模式匹配跑空、脚本无报错退出 → **看似加载了 bypass 实际未生效**。自写脚本必须带重试：

```javascript
function tryHook() {
    var mod = Process.findModuleByName("libflutter.so");
    if (!mod) return false;
    // 执行 pattern 扫描 + hook...
    return true;
}
var attempts = 0;
var timer = setInterval(function () {
    if (tryHook() || ++attempts >= 5) clearInterval(timer);
}, 1000);
```

---

## 8. Java 层组合 hook（与 Flutter bypass 同时加载）

**为什么必须双层**：部分 app 在 Flutter 初始化前，通过 Java/WebView 层做连接性检查——该检查走 Android 证书链（API 24+ 不信任用户安装的 CA）。只 patch Flutter 层时：BoringSSL 已放行，但 Java 层先拒绝了连接，app 显示 "no internet"（不是 SSL 错误）。

Java 层五个 hook 点（一个脚本全覆盖）：

| # | Hook 点 | 作用 |
|---|--------|------|
| 1 | `X509TrustManager` 自定义实现注册 | checkClientTrusted/checkServerTrusted/getAcceptedIssuers 全空实现 |
| 2 | `SSLContext.init()` | 拦截初始化，把 bypass TrustManager 注入**所有** SSLContext（含第三方库内部创建的） |
| 3 | `HostnameVerifier` | 恒返回 true——证书校验与主机名校验是两步，过前者仍会被后者拦 |
| 4 | `WebViewClient.onReceivedSslError` | 改调 `handler.proceed()`，否则 app 内 WebView 遇 Burp 证书直接停载 |
| 5 | `InAppWebViewClient`（flutter_inappwebview 插件） | **必须按完整类名单独 hook**：插件注册自己的 WebViewClient 子类 `com.pichillilorenzo.flutter_inappwebview_android.webview.in_app_webview.InAppWebViewClient`，hook 父类 WebViewClient 对它无效 |

第 5 点的类可能不存在（app 未用该插件），`Java.use()` 裸调用会抛异常炸掉整个脚本——每个 hook 点独立 try/catch。

TrustManager/SSLContext/HostnameVerifier 的完整 hook 代码见 `$AGENT_DIR/knowledge-base/mobile-patterns.md` SSL Pinning 小节（通用模板一致）。

---

## 9. 排错速查（组合场景）

| 现象 | 根因 | 处理 |
|------|------|------|
| bypass 脚本加载无报错，但流量抓不到 | libflutter.so 未加载完，pattern 跑空（§7.1） | 加重试逻辑；或 spawn 模式重跑 |
| app 显示 "no internet"（非证书报错） | Java/WebView 层连接检查先于 Flutter 初始化被拒（§8） | Flutter + Java 双脚本同时加载 |
| WebView 页面加载不出来，其余流量正常 | InAppWebViewClient 子类未被 hook（§8 第 5 点） | 按完整类名补 hook |
| Burp 报 "Client request violates HTTP protocol" | iptables 重定向后 app 发 raw TCP 无 CONNECT 握手 | Burp listener 开 invisible proxying 模式 |
| Burp Event Log 全空 | 流量根本没到 Burp | 设备上 tcpdump 看实际去向，再决定 iptables/DNSChef |
