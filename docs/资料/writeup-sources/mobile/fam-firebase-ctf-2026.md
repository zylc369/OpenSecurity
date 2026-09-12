---
来源: https://exploitnotes.hashnode.dev/fam-ctf-the-library-to-the-endpoint-writeup
类型: websearch-summary（原文反爬 403，内容来自搜索引擎摘要，技术细节完整）
标题: FAM CTF: The Library to The Endpoint Writeup（Android Firebase 四阶段）
获取日期: 2026-09-12
---

# 概要

Android APK（fam-ctf.apk）四阶段 flag，围绕 Firebase 后端逐层深入：
Flag1 native（libfam.so 静态提取）→ Flag2 Firebase RTDB → Flag3 Firestore + App Check → Flag4 自定义签名 API。
工具：unzip/strings/objdump/jadx/curl/Burp/Frida/adb。

# Flag 2 — Firebase Realtime Database

APK 内 google-services.json / 反编译代码给出 RTDB URL 后，直接 curl/REST 访问 RTDB 路径。
auth 检查靠泄露的凭证/匿名认证通过。

# Flag 3 — Firestore + App Check

- 识别后端是 Firestore 而非 RTDB（API 端点/SDK 调用特征区分）
- 被挡原因 = App Check：请求需携带 App Check token
- getDebugToken()：App Check 的 debug token 被静态嵌在 app 内（native/资源）
- 静态提取 debug token → 调 App Check API 兑换成真实 App Check token → 携带访问 Firestore
- 教训：debug token 只应限 CI/模拟器构建，发布 APK 中绝不应携带

# Flag 4 — 自定义签名 API 的运行时伪造

app 暴露 native 签名函数：submitChallenge() 读 UI spinner 用户名，
调 computeSignature("POST", "/api/check", body) 签名后请求 /api/check。

- 静态逆向 computeSignature：外层拼接 method+SEP+path+SEP+body 交给内层未导出函数，
  内层是手写混淆算法——逐字节重写太慢且易错
- 运行时方案（更优）：hook JNI 边界的 computeSignature，把出站 body 换成 admin payload
  （{"username":"admin","role":"admin"}），再调原实现——app 自己的密钥和算法给伪造 body 正确签名：

```javascript
Java.perform(function () {
    var MainActivity = Java.use("com.ctf.fam.MainActivity");
    MainActivity.computeSignature.implementation = function (method, path, body) {
        var adminBody = '{"username":"admin","role":"admin"}';
        console.log("[!!!] FORCING SIGNATURE FOR: " + adminBody);
        var sig = this.computeSignature(method, path, adminBody);
        console.log("[+] FORGED SIGNATURE: " + sig);
        return sig;
    };
});
```

frida -U -p <pid> -l hook_sig.js 加载后从 app UI 触发请求，hook 换 body、native 层正确签名，replay 即可。

# 根因

- 密钥/flag/debug 凭证嵌入发布二进制（strings/反汇编可提取）
- 客户端签名方案的强度 = 密钥强度 × 执行环境完整性；client 可被 hook（Frida/Xposed）签任意 payload
- role:admin 类权限检查必须服务端强制，不能因"客户端签名校验通过"而信任
