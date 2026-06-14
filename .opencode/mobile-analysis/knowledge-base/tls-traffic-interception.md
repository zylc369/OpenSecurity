# TLS 流量拦截模式

> 通过 Frida Hook connect/read 系统调用，追踪 SSL 连接并识别 TLS 记录类型。适用于：需要拦截移动应用的 HTTPS 流量（通常与 SSL bypass 配合使用）。
> 触发条件：需要监控或拦截 TLS 加密流量（检测 HTTP 响应到达、统计流量、MITM 响应篡改）。

---

## 1. TLS 记录格式速查

TLS 协议在 TCP 之上封装了"记录"结构。每条 TLS 记录的第一个字节表示类型：

```
TLS 记录格式：
┌──────┬──────┬──────────────┐
│ 类型 │ 版本 │ 长度 | 数据  │
│ 1字节│2字节 │ 2字节 | ...   │
└──────┴──────┴──────────────┘

类型值：
0x16 = Handshake（握手：ClientHello、ServerHello 等）
0x17 = Application Data（应用数据：加密的 HTTP 请求/响应）
0x15 = Alert（警告/错误，如证书验证失败）
0x14 = ChangeCipherSpec（加密规格变更）
```

**拦截 HTTP 响应的关键**：当 `read()` 返回的数据第一个字节为 `0x17` 时，表示收到了加密的 HTTP 响应。

---

## 2. 完整拦截代码模板

```javascript
// tls_intercept.js — TLS 流量拦截模板
// 用途: 追踪 SSL 连接，识别 TLS Application Data（加密的 HTTP 响应）
// 使用方式: 与 SSL bypass 脚本合并使用

var libc = Process.getModuleByName("libc.so");

// === 步骤 1: 通过 connect() Hook 追踪 SSL 连接的 fd ===
// connect() 的 sockaddr 结构中包含目标端口，端口 443 = SSL 连接

var sslFd = -1;  // 记录 SSL 连接的文件描述符

Interceptor.attach(libc.getExportByName("connect"), {
    onEnter: function(args) {
        try {
            var sockaddr = args[1];
            var family = sockaddr.readU16();  // sockaddr.sa_family
            if (family === 2) {  // AF_INET (IPv4)
                // 端口在 sockaddr_in.sin_port，网络字节序（大端）
                var port = (sockaddr.add(2).readU8() << 8) | sockaddr.add(3).readU8();
                if (port === 443) {
                    sslFd = args[0].toInt32();
                    console.log("[NET] SSL connection on fd=" + sslFd);
                }
            }
        } catch(e) {}
    }
});

// === 步骤 2: 通过 read() Hook 检测 TLS AppData ===
// 当 read() 从 SSL fd 读取数据且首字节为 0x17 时，表示收到 HTTP 响应

var tlsReads = 0;

Interceptor.attach(libc.getExportByName("read"), {
    onEnter: function(args) {
        this._fd = args[0].toInt32();
        this._buf = args[1];  // 保存缓冲区指针
    },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len <= 0 || this._fd !== sslFd) return;

        try {
            var type = this._buf.readU8();  // 读取 TLS 记录类型
            if (type === 0x16) {
                console.log("[TLS] Handshake data on fd=" + this._fd + " len=" + len);
            } else if (type === 0x17) {
                tlsReads++;
                console.log("[TLS] AppData #" + tlsReads + " on fd=" + this._fd + " len=" + len);
                // 这里是拦截点：TLS 解密后的 HTTP 响应
                // 对于响应篡改，用 popen("curl ...") 获取原始响应
                // 详见 $SHARED_DIR/knowledge-base/frida-native-shell-tricks.md
            } else if (type === 0x15) {
                console.log("[TLS] Alert on fd=" + this._fd + " len=" + len);
            }
        } catch(e) {}
    }
});

console.log("[*] TLS traffic interception loaded");
```

---

## 3. 与 MITM 方案的关系

本模板是 MITM 方案 B（SSL bypass + 流量拦截，仅日志）的流量拦截组件。完整 MITM 方案选型（含可注入到 APP 的方案 D）见 `$AGENT_DIR/knowledge-base/mitm-methodology.md`。

典型组合：
1. SSL bypass（让应用信任系统 CA）→ 详见 `$AGENT_DIR/knowledge-base/flutter-ssl-bypass.md`
2. TLS 流量拦截（本文件）→ 检测 HTTP 响应到达
3. 响应篡改（popen + curl，仅日志）→ 详见 `$SHARED_DIR/knowledge-base/frida-native-shell-tricks.md` §2.2

> ⚠ 本文件描述的方案 B 只能日志/证明拦截，不能让 APP 显示篡改内容。如需真实 MITM 注入，使用方案 D（系统 CA + SSL Bypass + HTTPS 代理），详见 `$AGENT_DIR/knowledge-base/mitm-methodology.md` §2.5。

---

## 4. 注意事项

| 注意项 | 说明 |
|--------|------|
| fd 追踪局限 | 只追踪最近一个连接到 443 端口的 fd。如果应用同时有多个 SSL 连接，需改为数组存储 |
| 数据仍加密 | read() 看到的是 TLS 加密后的数据（0x17 开头），不能直接读取 HTTP 内容 |
| 延迟处理 | TLS AppData 到达后需要等待 BoringSSL 解密，篡改响应建议用 setTimeout 延迟 1-2 秒 |
| 与 DNS 重定向冲突 | 不要同时使用 DNS 重定向和此拦截模式，详见 `$AGENT_DIR/knowledge-base/mitm-methodology.md` §3 |
