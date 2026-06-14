# Frida Hook 核心原则与 Java Bridge 陷阱

> 编写任何 Frida Hook 前必须掌握的 4 条铁律 + Java Bridge 6 个陷阱 + 通用检查清单。适配 frida 17.x。

---

## 4 条铁律

### 铁律 1：不破坏被 Hook 对象的状态

**永远不要在 Hook 中消耗一次性资源。**

```
ResponseBody 是一次性流（one-shot stream）
  ├── body.string()   → 消耗 buffer，之后不可再读
  ├── body.bytes()    → 同上
  ├── body.byteStream() → 同上
  └── response.peekBody() → 看似安全，某些 OkHttp 版本会 SIGSEGV
```

**正确策略：被动拦截** — 不主动去读，hook 消费端，等 app 自己调用时拦截返回值：

```
❌ hook RealCall.execute → 主动调用 body.string() 打印 → 崩溃
✅ hook RealCall.execute → 只打印 request/response headers（不碰 body）
✅ hook ResponseBody.string() → 等 app 自己调用时拦截返回值打印
```

**RequestBody 可以用 okio.Buffer 安全读取**（`writeTo()` 是复制操作不消耗原始 body），但只在打印时读一次，不在循环/链式调用中反复读取。

**判断标准**：
- 该方法是否修改对象状态？→ 不能主动调用
- 该方法是否消耗底层资源（流/buffer/连接）？→ 不能主动调用
- 该方法是否是纯读取/复制？→ 可以

### 铁律 2：数据立即提取为纯 JS 值，不存 Java Wrapper

Frida 的 Java wrapper 是 JNI 引用，随时可能被 GC 回收。

```javascript
// ❌ 存了 Java wrapper，延迟使用时已被 GC
var savedRequest = request;
setTimeout(function() { savedRequest.url(); }, 100);  // "Wrapper is disposed"

// ✅ 立即用 "" + 强制转为 JS 原生值
var url = "" + request.url().toString();
var method = "" + request.method();
var headers = {};
var names = request.headers().names();
var it = names.iterator();
while (it.hasNext()) {
    var name = "" + it.next();
    headers[name] = "" + request.headers().get(name);
}
```

**规则：任何从 Java 对象取的值，在存入变量/对象/数组时，立刻 `"" +` 转为 JS 原生值。**

### 铁律 3：Hook 中的打印必须在原始调用之前

```javascript
// ❌ 打印在 this.proceed() 之后 — 如果 proceed() 抛异常，打印执行不到
overload.implementation = function(request) {
    var info = extract(request);
    var resp = this.proceed(request);
    printInfo(info);  // 可能执行不到
    return resp;
};

// ✅ 打印在原始调用之前 — 确保即使异常也不丢失
overload.implementation = function(request) {
    var info = extract(request);
    printInfo(info);
    var resp = this.proceed(request);
    return resp;
};
```

### 铁律 4：统一日志函数，禁止 console.log("")

```javascript
function tsLog(msg) {
    var d = new Date();
    var ts = d.getHours() + ":" +
        ("0" + d.getMinutes()).slice(-2) + ":" +
        ("0" + d.getSeconds()).slice(-2) + "." +
        ("00" + d.getMilliseconds()).slice(-3);
    console.log("[" + ts + "] " + msg);
}
```

**禁止** `console.log("")` — Frida 中空字符串 log 可能静默失败，吞掉后续输出。

---

## Java Bridge 6 个陷阱

### 陷阱 1：Java 方法包装器不是普通 JS Function

```javascript
// ❌ 不支持
this.someMethod.call(null, arg);
this.someMethod.apply(this, args);
this.someMethod.bind(this);

// ✅ 正确调用
this.someMethod(arg1, arg2);
var result = this.someMethod(arguments[0], arguments[1]);
```

### 陷阱 2：字符串类型混淆

```javascript
// ❌ 不确定类型时直接操作
str.length()   // Java String 方法？还是 JS 报错？
str.length     // JS 属性？还是 Java field？

// ✅ 先转为 JS string
var str = "" + someJavaObj.toString();
var len = str.length;  // JS 属性，100% 安全
```

### 陷阱 3：for 循环中的闭包变量捕获

```javascript
// ❌ 所有回调共享同一个变量
for (var i = 0; i < exports.length; i++) {
    var exp = exports[i];
    Interceptor.attach(exp.address, {
        onEnter: function() { console.log(exp.name); }  // 永远是最后一个！
    });
}

// ✅ 用 IIFE 捕获当前值
for (var i = 0; i < exports.length; i++) {
    (function(exportName, exportAddr) {
        Interceptor.attach(exportAddr, {
            onEnter: function() { console.log(exportName); }
        });
    })(exports[i].name, exports[i].address);
}
```

必须在以下场景使用 IIFE：
- 遍历 `method.overloads` 数组
- 遍历 `module.enumerateExports()` 结果
- 任何循环中创建 `Interceptor.attach` 或 `Java.use` 回调

### 陷阱 4：Java Wrapper 的 GC 问题

```javascript
// ❌ 存了 Java wrapper，延迟使用时已被 GC
var savedObj = someJavaObj;
setTimeout(function() { savedObj.method(); }, 100);  // "Wrapper is disposed"

// ✅ 立即提取为纯 JS 值
var info = { url: "" + request.url().toString() };
```

**Java wrapper 不能跨调用栈帧存储。如果需要在后续使用，必须在当前帧立即提取为纯 JS 值。**

### 陷阱 5：Callback 包装类的 GC 问题

```javascript
// ❌ callback 会被 GC 回收
overload.implementation = function(callback) {
    var wrapped = new WrappedCallback(callback);
    this.enqueue(wrapped);
};

// ✅ 用 Java.retain() 阻止 GC
overload.implementation = function(callback) {
    var origCb = Java.retain(callback);
    this.enqueue(origCb);
};
```

### 陷阱 6：registerClass 类名必须唯一

```javascript
// ❌ 重复注册同名类会报错
var Wrapped = Java.registerClass({ name: "com.hook.MyCallback", ... });

// ✅ 用计数器保证唯一
var counter = 0;
var Wrapped = Java.registerClass({ name: "com.hook.MyCb" + (++counter), ... });
```

---

## frida 17.x Bridge 使用规则

> **详见 `$AGENT_DIR/knowledge-base/frida-17x-bridge.md`**。核心要点：

| 场景 | 方式 |
|------|------|
| frida CLI (`frida -l hook.js`) | 直接用 `Java.perform(...)` — REPL 内置 bridge |
| Python SDK + Java Hook | **必须** 用 `frida.Compiler` 编译 TypeScript（`import Java from "frida-java-bridge"`） |
| Python SDK + 纯 Native Hook | 直接 `session.create_script(js_string)` — 不需要 bridge |

**禁止** 在 Python SDK 中直接 `session.create_script("Java.perform(...)")` — frida 17.x Java bridge 不内置。

---

## 通用 Hook 检查清单

### 数据安全
- [ ] Response body：是否在 hook 中主动调用了消耗方法？改为被动拦截
- [ ] Request body：是否用了 `okio.Buffer` + `writeTo()` + `readUtf8()`？且只在打印时读一次？
- [ ] body 读取次数：是否在循环/链式调用中反复读取 body？改为只读一次

### Java Bridge
- [ ] 字符串操作：对 Java 返回值做 JS 操作前，是否用 `"" + value` 转为 JS string？
- [ ] Wrapper 存储：是否存了 Java wrapper 并在后续使用？改为立即提取纯 JS 值
- [ ] 闭包变量：for 循环中是否用了 IIFE 捕获变量？
- [ ] overloads 遍历：是否遍历了所有重载？
- [ ] Callback GC：enqueue 的 callback 是否用了 `Java.retain()`？
- [ ] registerClass 唯一性：动态注册的类名是否有唯一后缀？

### 代码结构
- [ ] 打印时机：关键信息打印是否在原始方法调用之前？
- [ ] 统一日志：是否用统一的 tsLog 函数？是否有 console.log("")？
- [ ] try-catch：hook 逻辑是否包裹在 try-catch 中？
- [ ] Native hook 位置：是否放在 `Java.perform()` 外面？
- [ ] 延迟加载：SO 库是否做了延迟加载等待？

### 17.x 兼容性
- [ ] Module API：是否使用了 `Module.findExportByName`？替换为 `Process.getModuleByName(mod).getExportByName(name)`
- [ ] Bridge 编译：Python SDK 中使用 Java Hook 时是否走了 `frida.Compiler`？

### 链式调用（拦截器链）特殊检查
- [ ] ThreadLocal 状态：是否用 tid 做线程隔离？
- [ ] 头完整性：是否用头数量增长判断 request 完整性？
- [ ] 状态清理：isOuterCall 时是否清理了所有 ThreadLocal 状态？
