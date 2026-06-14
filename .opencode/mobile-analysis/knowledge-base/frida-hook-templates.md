# Frida Hook 架构与模板

> Hook 架构模式、标准 Hook 模板、拦截器链 Hook 模式、Native Hook 要点。适配 frida 17.x。

---

## 项目内置 Hook 脚本

> 项目内置了一系列现成的 Frida hook 脚本，分析常见框架时可直接加载，无需手写。

### 加载方式

```bash
frida -H 127.0.0.1:$HOST_PORT -n <package_name> -l "$AGENT_DIR/scripts/hooks/<script_name>"
```

### 内置脚本清单

| 脚本 | 用途 |
|------|------|
| `okhttp3-hook.js` | OkHttp3 请求/响应拦截（headers + body）、拦截器链追踪、WebSocket 监控 |

> 本页后续模板是上述脚本的拆解说明，方便按需定制。

---

## 主动拦截 vs 被动拦截

| 场景 | 模式 | 说明 |
|------|------|------|
| Request headers | 主动拦截 | headers 是纯数据，无 side effect |
| Request body | 主动拦截 | 用 okio.Buffer 复制读取，但只在最终打印时读一次 |
| Response headers | 主动拦截 | 同 request headers |
| Response body | **被动拦截** | hook ResponseBody.string()/bytes()，不主动消耗 |
| Native 函数参数/返回值 | 被动拦截 | Interceptor.attach 的 onEnter/onLeave |

---

## 标准 Hook 模板

```javascript
// 统一日志函数
function tsLog(msg) {
    var d = new Date();
    var ts = d.getHours() + ":" +
        ("0" + d.getMinutes()).slice(-2) + ":" +
        ("0" + d.getSeconds()).slice(-2) + "." +
        ("00" + d.getMilliseconds()).slice(-3);
    console.log("[" + ts + "] " + msg);
}

// 安全获取 Java 类（不存在时不崩溃）
function tryUse(className) {
    try { return Java.use(className); } catch (e) { return null; }
}

// 数据提取函数：立即转纯 JS，不存 Java wrapper，不读 body
function extractInfo(javaObj) {
    return {
        field1: "" + javaObj.field1(),
        field2: "" + javaObj.field2(),
    };
}

function hookSomething() {
    var cls = tryUse("com.example.TargetClass");
    if (!cls) return;

    var overloads = cls.targetMethod.overloads;
    for (var i = 0; i < overloads.length; i++) {
        (function(overload) {
            overload.implementation = function(arg) {
                // 1. 立即提取数据为纯 JS 值
                var info = extractInfo(arg);

                // 2. 在原始调用前打印（即使原始调用抛异常也不丢失）
                tsLog("field1=" + info.field1 + " field2=" + info.field2);

                // 3. 调用原始方法
                var result = this.targetMethod(arg);

                // 4. 原始调用后打印结果
                try {
                    tsLog("result=" + result);
                } catch (e) {
                    tsLog("[hook error] " + e.message);
                }

                return result;
            };
        })(overloads[i]);
    }
}
```

### 关键点

1. **数据提取在原始调用前完成**，转为纯 JS 值
2. **打印在原始调用前**，确保即使异常也不丢失
3. **所有 Java 值用 `"" +` 转为 JS 原生值**
4. **遍历 overloads 时用 IIFE 捕获变量**
5. **统一用 tsLog 输出**

---

## Hook 构造函数模板

```javascript
function hookConstructor() {
    var cls = tryUse("com.example.TargetClass");
    if (!cls) return;

    cls.$init.overloads.forEach(function(overload) {
        overload.implementation = function() {
            tsLog("[*] new TargetClass() called with " + arguments.length + " args");
            for (var i = 0; i < arguments.length; i++) {
                tsLog("    arg" + i + ": " + arguments[i]);
            }
            return this.$init.apply(this, arguments);
        };
    });
}
```

---

## Hook 所有重载模板

```javascript
function hookAllOverloads(className, methodName) {
    var cls = tryUse(className);
    if (!cls || !cls[methodName]) return;

    var overloads = cls[methodName].overloads;
    for (var i = 0; i < overloads.length; i++) {
        (function(overload) {
            overload.implementation = function() {
                tsLog("[*] " + className + "." + methodName +
                      " called with " + arguments.length + " args");
                for (var j = 0; j < arguments.length; j++) {
                    tsLog("    arg" + j + ": " + arguments[j]);
                }
                var result = this[methodName].apply(this, arguments);
                tsLog("    result: " + result);
                return result;
            };
        })(overloads[i]);
    }
}
```

---

## 搜索并 Hook 模板（类名未知时）

```javascript
function searchAndHook(keyword) {
    Java.perform(function() {
        Java.enumerateLoadedClasses({
            onMatch: function(className) {
                if (className.indexOf(keyword) !== -1) {
                    tsLog("[+] Found: " + className);
                }
            },
            onComplete: function() {
                tsLog("[*] Class search complete");
            }
        });
    });
}
```

---

## 拦截器链 Hook 模式

框架的拦截器链是嵌套结构，`proceed` 会被每层调用一次：

```
proceed(req0)                          ← 最外层，request 不完整
  → InterceptorA.intercept(chain1)
    → chain1.proceed(req1)             ← InterceptorA 可能修改了 request
      → InterceptorB.intercept(chain2)
        → chain2.proceed(req2)         ← InterceptorB 可能又修改了 request
          → CallServerInterceptor      ← 真正发送网络请求
```

**问题**：最外层的 request 头不完整（拦截器还没修改），最内层才完整。

**解决方案**：用头数量增长判断完整性，只在头增长时打印：

```javascript
var chainThreadMap = {};
var lastChainHeaderCount = {};

function hookInterceptorChain() {
    var cls = tryUse("okhttp3.internal.http.RealInterceptorChain");
    if (!cls || !cls.proceed) return;

    for (var i = 0; i < cls.proceed.overloads.length; i++) {
        (function(overload) {
            overload.implementation = function(request) {
                var tid = Process.getCurrentThreadId();
                var isOuterCall = !chainThreadMap[tid];

                if (isOuterCall) {
                    chainThreadMap[tid] = true;
                    lastChainHeaderCount[tid] = 0;
                }

                // 提取当前层 request 信息（纯 JS 值，不含 body）
                var headerCount = 0;
                try {
                    var names = request.headers().names();
                    var it = names.iterator();
                    while (it.hasNext()) {
                        it.next();
                        headerCount++;
                    }
                } catch (e) {}

                // 只在头数量增长时打印（说明拦截器添加了新头）
                if (headerCount > lastChainHeaderCount[tid]) {
                    lastChainHeaderCount[tid] = headerCount;
                    tsLog("[" + tid + "] Request headers count: " + headerCount);
                    // 打印完整 headers...
                }

                var resp = this.proceed(request);

                if (isOuterCall) {
                    delete chainThreadMap[tid];
                    delete lastChainHeaderCount[tid];
                    try {
                        tsLog("[" + tid + "] Response code: " + resp.code());
                    } catch (e) {}
                }

                return resp;
            };
        })(cls.proceed.overloads[i]);
    }
}
```

---

## Native Hook 模板

### 要点：Native Hook 不能放在 `Java.perform()` 内

```javascript
// ❌ 错误：Native Hook 不应嵌套在 Java.perform() 内（结构混乱，容易出问题）
Java.perform(function() {
    Process.findModuleByName(...);  // 虽然语法上可以，但应独立执行
});

// ✅ 正确
Java.perform(function() { /* Java hooks */ });
hookNativeCrypto();  // 独立执行 Native Hook
```

### SO 库延迟加载

```javascript
function hookNative() {
    var libName = "libnative-lib.so";
    function doHook() {
        var mod = Process.findModuleByName(libName);
        if (!mod) return false;
        // 执行 hook...
        return true;
    }
    if (!doHook()) {
        var timer = setInterval(function() {
            if (doHook()) clearInterval(timer);
        }, 1000);
    }
}
```

### JNI 函数参数读取

```javascript
Interceptor.attach(addr, {
    onEnter: function(args) {
        // args[0] = JNIEnv*, args[1] = jobject/jclass, args[2] = 第一个 Java 参数
        var env = Java.vm.getEnv();
        var str = env.getStringUtfChars(args[2], null).readUtf8String();
    }
});
```

---

## 调试策略

### 逐步启用 Hook

```javascript
function hookJava() {
    hookRealCall();           // 第一步：验证基础 Hook 工作
    // hookResponseBodyString();  // 第二步：验证 body 拦截
    // hookWebSocket();            // 第三步：扩展
}
```

### 区分异常类型

| 现象 | 类型 | 处理方式 |
|------|------|---------|
| `[Error: xxx]` 在 Frida console | JS 异常 | try-catch 可捕获 |
| App 闪退，Frida 断开连接 | Native 崩溃 | 排查 hook 是否破坏对象状态 |
| `TypeError: not a function` | API 调用错误 | 检查上下文（17.x Module 变化？） |
| "Wrapper is disposed" | Java wrapper GC | 立即用 `"" +` 提取为纯 JS 值 |
| console.log 后无输出 | console.log("") 吞输出 | 用统一 tsLog 函数 |

### Hook 点选择优先级

```
优先 hook 高层 API：
  RealCall.execute / enqueue    → 拿到完整 Request 和 Response

避免 hook 内部实现类：
  CallServerInterceptor         → 内部细节，版本间可能变化

优先 hook 接口方法：
  ResponseBody.string()         → 接口层，各版本实现不同但接口稳定
```
