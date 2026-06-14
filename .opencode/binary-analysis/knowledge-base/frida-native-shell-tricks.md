# Frida Native Shell 技巧

> 在 Frida 中执行 shell 命令和 HTTP 请求的 native 方法。适用于：Java bridge 不可用或不稳定时（如 Flutter 应用、纯 native 进程）。
> 触发条件：在 Frida 脚本中需要执行外部命令或发起 HTTP 请求，但 Java bridge 报 TypeError 或 `Java.available === false`。

---

## 1. 问题：Java bridge 不稳定

在以下场景中 `Java.perform()` 内的 Java API 调用可能失败：

| 场景 | 错误 |
|------|------|
| Flutter 应用（libflutter.so） | `TypeError: not a function` |
| 纯 native 进程 | `Java.available === false` |
| Java bridge 竞态 | 间歇性 TypeError |

典型失败代码：

```javascript
// ❌ 不稳定 — 可能报 TypeError
Java.perform(function() {
    var URL = Java.use("java.net.URL");
    var conn = URL.$new("https://example.com").openConnection();
    var code = conn.getResponseCode();  // TypeError: not a function
});
```

---

## 2. 解决方案：popen + fgets

直接通过 libc 的 `popen` 执行 shell 命令，用 `fgets` 读取输出。完全绕过 Java bridge。

### 2.1 完整代码模板

```javascript
// frida_native_shell.js — Native shell 工具函数
// 适用于 Frida CLI 和 Python SDK

// 初始化 libc 函数
var libc = Process.getModuleByName("libc.so");
var popenPtr = libc.getExportByName("popen");
var pclosePtr = libc.getExportByName("pclose");
var fgetsPtr = libc.getExportByName("fgets");

var popen = new NativeFunction(popenPtr, 'pointer', ['pointer', 'pointer']);
var pclose = new NativeFunction(pclosePtr, 'int', ['pointer']);
var fgets = new NativeFunction(fgetsPtr, 'pointer', ['int', 'int', 'pointer']);

/**
 * 执行 shell 命令并返回输出
 * @param {string} cmd - shell 命令
 * @param {number} [bufSize=4096] - 读取缓冲区大小
 * @returns {string} 命令输出（所有行合并）
 */
function shellExec(cmd, bufSize) {
    bufSize = bufSize || 4096;
    var cmdBuf = Memory.allocUtf8String(cmd);
    var modeBuf = Memory.allocUtf8String("r");
    
    var fp = popen(cmdBuf, modeBuf);
    if (fp.isNull()) {
        return "[ERROR] popen failed for: " + cmd;
    }
    
    var result = "";
    var lineBuf = Memory.alloc(bufSize);
    
    while (true) {
        var line = fgets(lineBuf, bufSize, fp);
        if (line.isNull()) break;
        result += lineBuf.readUtf8String();
    }
    
    pclose(fp);
    return result;
}

/**
 * 发起 HTTP GET 请求并返回响应体
 * 使用 curl 命令实现
 * @param {string} url - 目标 URL
 * @param {object} [opts] - 选项
 * @param {number} [opts.timeout=10] - 超时秒数
 * @param {string} [opts.proxy] - 代理地址（如 "http://127.0.0.1:8080"）
 * @returns {string} HTTP 响应体
 */
function httpGet(url, opts) {
    opts = opts || {};
    var timeout = opts.timeout || 10;
    var cmd = 'curl -s --max-time ' + timeout;
    
    if (opts.proxy) {
        cmd += ' --proxy ' + opts.proxy;
    }
    
    // 忽略证书错误（MITM 场景）
    cmd += ' -k';
    cmd += ' "' + url + '"';
    
    return shellExec(cmd);
}

// 使用示例
console.log("[*] Testing native shell...");
var output = shellExec("whoami");
console.log("[*] whoami: " + output.trim());

var response = httpGet("https://httpbin.org/get");
console.log("[*] HTTP GET response: " + response.substring(0, 200));
```

### 2.2 在 MITM 响应篡改中使用

```javascript
// 在 read() Hook 中篡改响应
Interceptor.attach(readPtr, {
    onLeave: function(retval) {
        if (retval.toInt32() <= 0) return;
        
        var data = this.buf.readUtf8String(retval.toInt32());
        // 检测到目标响应
        if (data && data.indexOf('"text"') !== -1) {
            // 用 curl 获取原始响应并篡改
            var origResponse = httpGet("https://api.target.com/data");
            var modifiedResponse = origResponse.replace(
                /"text"\s*:\s*"[^"]*"/,
                '"text": "tampered content"'
            );
            
            // 写回篡改后的响应
            var newBuf = Memory.allocUtf8String(modifiedResponse);
            this.buf.writeUtf8String(modifiedResponse);
            retval.replace(modifiedResponse.length);
            console.log("[+] Response tampered!");
        }
    }
});
```

---

## 3. 性能与安全注意事项

| 注意项 | 说明 |
|--------|------|
| 缓冲区大小 | 默认 4096，对于大输出需增大 `bufSize` |
| 命令注入 | `shellExec` 参数不要拼接用户可控输入 |
| 线程安全 | `popen` 在 Frida 的 JS 线程中执行，不会阻塞目标进程 |
| 超时 | curl 的 `--max-time` 防止卡死，默认 10 秒 |
| 编码 | 输出按 UTF-8 读取，非 UTF-8 会截断 |

---

## 4. 与其他知识库的关系

- Frida Hook 原则：`$AGENT_DIR/knowledge-base/frida-hook-templates.md`（PC 端模板）或 `$SHARED_DIR/knowledge-base/frida-hook-templates.md`（通用模板）
- MITM 方案选型（移动端）：`$OPENCODE_ROOT/mobile-analysis/knowledge-base/mitm-methodology.md`
- Flutter SSL bypass（移动端）：`$OPENCODE_ROOT/mobile-analysis/knowledge-base/flutter-ssl-bypass.md`
