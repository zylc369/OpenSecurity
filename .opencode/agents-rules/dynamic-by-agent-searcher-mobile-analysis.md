<domain_sources>

## 领域：移动分析

### 优先来源

1. **Android Developer Reference** — `https://developer.android.com/reference/`
   官方 Android API。webfetch 不可用（OAuth 登录墙），改用 `websearch` 搜索 `site:developer.android.com <类名>` 查询特定 API 行为。

2. **Frida Documentation** — `https://frida.re/docs/home/`
   JavaScript API、Interceptor、Module.findExportByName、Java.perform 模式。版本相关的特性：使用 `websearch` 配合 "frida <version> <api>"。

3. **iOS Developer Reference** — `https://developer.apple.com/documentation/`
   Objective-C / Swift 运行时 API，常见越狱检测模式。

4. **jadx / apktool** — `https://github.com/skylot/jadx` / `https://ibotpeaches.github.io/Apktool/`
   反编译工具用法、manifest 解析、smali 编辑。

5. **Android Security bulletins** — `https://source.android.com/docs/security/bulletin`
   Android 平台、内核、媒体框架的月度 CVE 列表。webfetch 不可用（OAuth 登录墙），改用 `websearch` 搜索 `site:source.android.com <CVE> bulletin`。替代 CVE 源：NVD — `https://nvd.nist.gov/`。

6. **Oversecured / NowSecure 漏洞指南** — `https://blog.oversecured.com/` / `https://www.nowsecure.com/blog/`
   Android 应用漏洞类别（Intent 重定向、WebView 滥用、IPC 滥用）。

7. **Frida snippets 社区** — `https://codeshare.frida.re/`
   社区共享的 Frida hook 脚本。

8. **OWASP MASTG/MASVS** — `https://mas.owasp.org/MASTG/`
   移动安全测试标准方法论 + MASVS 要求项 + 测试用例 ID。

9. **Frida GitHub** — `https://github.com/frida/frida`
   版本兼容、平台 bug、release notes 在 issues。

10. **objection** — `https://github.com/sensepost/objection`
    Frida 之上的运行时探索框架，移动渗透事实标准。

11. **MobSF** — `https://github.com/MobSF/Mobile-Security-Framework-MobSF`
    开源移动安全自动化分析框架。

12. **r2frida** — `https://github.com/nowsecure/r2frida`
    radare2 + Frida 联动，native library 分析利器。

### 查询术语约定

- 包含操作系统+版本：`"Android 13"`、`"iOS 17"`、`"arm64-v8a"`
- 混淆相关：`"DexGuard"`、`"Allatori"`、`"Bangcle"`、`"Tencent legu"`
- hook 相关：包含目标层（`"Java layer"`、`"JNI bridge"`、`"native library"`）
- WebView 攻击相关：包含桥接（`"JavascriptInterface"`、`"addJavascriptInterface"`、`"WKWebView"`）
- iOS 侧：`"class-dump"`、`"Theos"`、`"tweak"`、`"jailbreak detection bypass"`、`"fishhook"`、`"Cydia Substrate"`
- SSL Pinning 绕过：`"SSL pinning bypass"`、`"OkHttp CertificatePinner"`、`"Network Security Config"`、`"TrustManager"`
- 反检测：`"anti-debug"`、`"anti-frida"`、`"Magisk Hide"`、`"Zygisk"`
- 加固厂商全名：`"Bangcle (梆梆)"`、`"360 jiagu"`、`"DexProtector"`
</domain_sources>
