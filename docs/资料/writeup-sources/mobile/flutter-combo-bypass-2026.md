---
来源: https://infosecwriteups.com/i-wasted-3-days-intercepting-a-flutter-app-heres-what-actually-works-d3e9a4816818
类型: websearch-summary（原文反爬 403，内容来自搜索引擎摘要，技术细节完整）
标题: I Wasted 3 Days Intercepting a Flutter App. Here's What Actually Works.
获取日期: 2026-09-12
---

# 核心问题

Flutter app 拦截失败三天：app 打开但显示 "no internet"（非 SSL 错误、非证书警告）。
根因：仅 patch Flutter 层不够——部分 app 在 Flutter 初始化前通过 Java/WebView 层做连接性检查，
该检查走 Android 证书链（API 24+ 不信任用户 CA），Java 层先拒绝 → Flutter bypass 生效但 app 仍判无网。

# 双脚本组合（同时加载）

## Script 1: disable-flutter-tls-v1.js（NVISOsecurity 项目）

- 目标函数：BoringSSL `ssl_verify_peer_cert`（handshake.cc）
- 定位方式：内存字节模式匹配（byte pattern matching），内置 arm64/arm/x64/x86 四架构 × Android/iOS 的 pattern
- bypass：替换实现为恒返回 0（全部通过）
- timing 处理：Frida attach 时 libflutter.so 可能未加载完 → 模式匹配静默失败（无报错但 bypass 未生效）
  → 重试最多 5 次、间隔 1s；库找到后重置重试计数（pattern 搜索也获得完整重试次数）

## Script 2: universal_bypass.js（Java 层全覆盖）

1. X509TrustManager：注册自定义实现，checkClientTrusted/checkServerTrusted/getAcceptedIssuers 全空
2. SSLContext.init() hook：所有 SSLContext（含第三方库内部创建的）初始化时注入 bypass trust manager
3. HostnameVerifier：恒返回 true（证书校验与主机名校验是两步，过前者仍可能被后者拦）
4. WebViewClient.onReceivedSslError：调用 handler.proceed() 而非显示错误页
5. InAppWebViewClient（关键增量）：flutter_inappwebview 插件注册自己的 WebViewClient 子类
   `com.pichillilorenzo.flutter_inappwebview_android.webview.in_app_webview.InAppWebViewClient`
   —— hook 父类 WebViewClient 对该子类无效，必须按完整类名单独 hook
   —— 用 try/catch 包裹 Java.use()：app 不用该插件时类不存在，裸调用会炸掉整个脚本

# 脚本不够时的分层流量路径

1. Burp invisible proxy：iptables 重定向后 app 发 raw TCP（无 CONNECT 握手），不开 invisible proxy 会报
   "Client request violates HTTP protocol" 且 Intercept 无内容
2. iptables OUTPUT 链 DNAT：Flutter 直接 TCP 连接、无视系统代理，需内核级重定向
3. Burp CA 装入系统 store：bind mount 方式绕过只读分区（API 24+ 用户 CA 不被信任）
4. DNSChef：iptables 仍不奏效时（tcpdump 确认包从 443 离开设备去了别处），劫持 DNS 解析本身

# 排错

- 先看 Burp Event Log 再怀疑脚本：
  "Failed to negotiate TLS connection" = CA 不被信任 → 跑脚本或 bind mount
  "Client request violates HTTP protocol" = 未开 invisible proxy
  Event Log 全空 = 流量根本没到 Burp → tcpdump 看实际去向
