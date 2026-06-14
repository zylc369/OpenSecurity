# 移动端 MITM 方案选型指南

> 移动应用流量拦截的方案选择和常见陷阱。适用于：需要拦截/篡改移动应用的 HTTPS 通信。
> 触发条件：分析移动应用的网络通信，需要执行 MITM（中间人攻击）。

---

## 1. 四种 MITM 方案对比

| 方案 | 原理 | 适用场景 | 复杂度 | 能否注入到 APP |
|------|------|---------|--------|---------------|
| **A: DNS 重定向 + 代理** | 修改 DNS 将目标域名指向代理 IP，代理解密重加密 | 无 SSL pinning 的应用 | 低 | ✅ |
| **B: SSL bypass + 流量拦截** | Frida Hook 绕过 SSL pinning，Hook read/write 拦截流量，popen+curl 获取原始响应 | 有 SSL pinning，仅需日志/证明拦截（不需要 APP 显示篡改内容） | 高 | ❌ 仅日志 |
| **C: 系统CA注入** | 将代理 CA 证书安装到系统信任存储，绕过应用层验证 | Root 设备 + 非 Flutter 应用 | 中 | ✅ |
| **D: 系统CA + SSL Bypass + HTTPS 代理** | 安装 CA 到系统目录 + TrustBuiltinRoots 加载 + Frida 重定向流量到 HTTPS 代理 | Flutter 应用 + 需要让 APP 实际显示篡改内容 | 高 | ✅ |

---

## 2. 方案选择决策树

```
目标应用是否有 SSL Pinning？
├── 否 → 方案 A（DNS 重定向 + 代理）
│        配置简单，Burp/Charles 即可
│
├── 是 → 应用类型？
│        ├── Flutter 应用 → 是否需要让 APP 显示篡改内容？
│        │        ├── 是 → 方案 D（系统CA + SSL Bypass + HTTPS 代理）★ 推荐
│        │        │   安装自签 CA 到系统目录，TrustBuiltinRoots 会加载它
│        │        │   Frida Hook 重定向流量到本地 HTTPS 代理
│        │        │   详见下方 §2.5
│        │        │
│        │        └── 否（仅需日志证明）→ 方案 B（SSL bypass + read 拦截 + popen curl）
│        │            Flutter 不走 Java TLS，必须 Hook native 层
│        │            详见 $AGENT_DIR/knowledge-base/flutter-ssl-bypass.md
│        │
│        ├── 标准 Java/Kotlin → 方案 C 或 D
│        │   先尝试方案 C（安装系统 CA）
│        │   如果应用检查用户证书 → 方案 B 或 D
│        │
│        └── Unity/其他 Hybrid → 方案 B 或 D
│            通常不走 Java TLS，需要 Hook native
│
└── 不确定 → 先尝试方案 A，观察是否报证书错误
             报错 → 有 SSL pinning → 切换到对应方案
```

### 2.5 方案 D: 系统CA注入 + SSL Bypass + HTTPS 代理（Flutter 真实 MITM）

**核心思路**: Flutter 的 `TrustBuiltinRoots` 会加载 `/system/etc/security/cacerts/` 目录下所有系统 CA 证书。如果事先将自签 CA 安装到该目录，SSL bypass 调用 `TrustBuiltinRoots` 后，代理用该 CA 签发的站点证书就会被 BoringSSL 信任。

**前提条件**:
1. Root 权限（写入 /system 分区）
2. Flutter 应用的 `TrustBuiltinRoots` 偏移已通过 IDA 逆向确定
3. 主机上 openssl 可用（生成证书）

**完整步骤**:

```
步骤 1: 生成自签 CA + 站点证书
步骤 2: 安装 CA 到 Android 系统 CA 目录
步骤 3: 启动 HTTPS 代理（使用 CA 签发站点证书）
步骤 4: 设置 adb reverse 端口映射
步骤 5: Frida Hook（Root bypass + SSL bypass + 流量重定向）
步骤 6: 触发 APP 请求，代理篡改响应
```

**步骤 1: 生成证书**

```bash
# 生成 CA 私钥和证书
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
  -subj "/CN=MITM CA/O=Security Research"

# 生成站点证书（用 CA 签发，含 SAN）
TARGET_HOST="api.target.com"
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/CN=$TARGET_HOST"
echo "subjectAltName=DNS:$TARGET_HOST" > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 365 -extfile san.ext
```

**步骤 2: 安装 CA 到系统目录**

```bash
# 计算文件名（Android 系统证书使用 subject_hash_old 命名）
HASH=$(openssl x509 -inform PEM -subject_hash_old -in ca.crt -noout)
# 例如输出: 5652bf85

# 确认 /system 可写
adb shell "mount | grep '/system'"  # 应显示 rw
# 如果只读: adb root && adb remount

# 推送证书
adb push ${HASH}.0 /system/etc/security/cacerts/
# 验证
adb shell ls -la /system/etc/security/cacerts/${HASH}.0
```

**步骤 3: 启动 HTTPS 代理**

使用 `$AGENT_DIR/scripts/mitm_proxy.py`（已沉淀的通用脚本）:

```bash
# --workdir 是必须参数，用于存放 CA 密钥和证书
python3 $AGENT_DIR/scripts/mitm_proxy.py \
  --workdir /tmp/mitm \
  --listen-port 44300 \
  --target-host api.target.com \
  --target-port 443 \
  --tamper-field text \
  --tamper-value "MITM HACKED!"
```

**步骤 4: 端口映射**

```bash
# adb reverse: 模拟器访问 127.0.0.1:44300 → 主机 :44300
adb reverse tcp:44300 tcp:44300
```

**步骤 5: Frida Hook 脚本关键部分**

需要三部分 Hook：
1. **SSL bypass** — 详见 `$AGENT_DIR/knowledge-base/flutter-ssl-bypass.md` §6 完整模板（TrustBuiltinRoots + native peer 捕获）
2. **DNS 重定向** + **端口重定向（含 IPv6 处理）** — 完整模板见下方 §3.4，使用时修改 `target.com` 和端口常量即可
3. **组合时序**：先启动 SSL bypass Hook，确保 TrustBuiltinRoots 在首次 HTTPS 请求前生效；再启动 DNS+connect Hook 重定向流量到代理

> ⚠ `indexOf("target.com")` 是子字符串匹配，如需精确匹配请改用 `=== "target.com"` 或正则。

**⚠ 关键时序**: TrustBuiltinRoots 必须在 APP 发起 HTTPS 请求之前被调用（由 Frida SSL bypass Hook 保证）。CA 安装必须在 APP 启动前完成。

---

## 3. 核心教训：SSL bypass 与流量重定向的冲突

### 3.1 问题描述

同时使用 **DNS 重定向（iptables）** 和 **SSL bypass（Frida Hook）** 时，两者会冲突：

1. DNS 重定向将流量导向代理 → 应用实际连接的是代理而非真实服务器
2. SSL bypass Hook 的 `TrustBuiltinRoots` / `native peer` 不会被触发
3. 因为 Flutter 的 SSL 握手在 native 层完成，连接对象变了（代理 vs 真实服务器），导致 SSL 上下文不同

### 3.2 方案 B：仅日志/证明拦截（不能注入到 APP）

如果只需要**证明拦截能力**（日志输出），不需要让 APP 显示篡改内容，可以用方案 B：

1. **SSL bypass**：Frida Hook 绕过证书验证（应用正常连接真实服务器）
2. **流量拦截**：Hook `read()`/`write()` 系统调用，在明文层拦截
3. **响应篡改**：在 `read()` Hook 中检测到目标内容后，用 `popen("curl ...")` 获取原始响应并替换（仅日志输出）

> ⚠ **如果需要让 APP 实际显示篡改内容，不要用方案 B**，应使用方案 D（详见 §2.5）。方案 B 的 popen+curl 只能获取和篡改数据用于日志，不能注入回 APP 的数据流。

```javascript
// 方案 B 的核心思路（伪代码，展示流程，不可直接运行）
// 完整 connect+read 拦截模板见 $AGENT_DIR/knowledge-base/tls-traffic-interception.md
// 响应篡改（popen+curl）见 $SHARED_DIR/knowledge-base/frida-native-shell-tricks.md §2.2
Interceptor.attach(libc.getExportByName("read"), {
    onEnter: function(args) { this.fd = args[0]; this.buf = args[1]; },
    onLeave: function(retval) {
        if (this.fd !== sslFd) return;       // sslFd 由 connect() Hook 追踪得到
        var len = retval.toInt32();
        if (len <= 0) return;
        var type = this.buf.readU8();        // TLS 记录类型字节
        if (type === 0x17) {                 // 0x17 = Application Data（加密的 HTTP）
            // TLS AppData 到达 — 可配合延迟后篡改
        }
    }
});
```

### 3.3 方案 A（纯代理）适用时

如果应用**没有 SSL pinning**，直接用 DNS 重定向 + 代理（Burp/Charles）更简单：

```bash
# iptables 重定向（Android）
adb shell iptables -t nat -A OUTPUT -p tcp --dport 443 -j DNAT --to-destination PROXY_IP:PROXY_PORT

# 或使用 adb forward + Burp
adb forward tcp:8080 tcp:8080
# 在应用中配置 HTTP 代理（如果应用支持）
```

### 3.4 DNS 重定向实现细节

当 iptables 不可用或需要更精细控制时，可以用 Frida Hook 实现 DNS 重定向和端口重定向：

**Hook getaddrinfo 做 DNS 重定向**：

```javascript
// ⚠ 预分配字符串到全局变量，避免 GC 回收导致崩溃
var redirectStr = Memory.allocUtf8String("127.0.0.1");

Interceptor.attach(libc.getExportByName("getaddrinfo"), {
    onEnter: function(args) {
        try {
            var host = args[0].readUtf8String();
            // ⚠ indexOf 是子字符串匹配，可能误匹配 not-target.com 等域名
            // 如需精确匹配，改用: host === "api.target.com"
            if (host && host.indexOf("target.com") !== -1) {
                args[0] = redirectStr;
                console.log("[DNS] Redirected " + host + " → 127.0.0.1");
            }
        } catch(e) {}
    }
});
```

**Hook connect 做端口重定向（支持 IPv4 + IPv6）**：

```javascript
var targetPort = 443;
var proxyPort = 44300;  // 代理监听的端口

Interceptor.attach(libc.getExportByName("connect"), {
    onEnter: function(args) {
        try {
            var sockaddr = args[1];
            var family = sockaddr.readU16();

            if (family === 2) {  // AF_INET (IPv4)
                // 端口在 sockaddr 结构中，大端序（网络字节序）
                // 读取: (byte0 << 8) | byte1
                // 写入: byte0 = port >> 8, byte1 = port & 0xFF
                var currentPort = (sockaddr.add(2).readU8() << 8) | sockaddr.add(3).readU8();
                if (currentPort === targetPort) {
                    sockaddr.add(2).writeU8(proxyPort >> 8);
                    sockaddr.add(3).writeU8(proxyPort & 0xFF);
                    console.log("[NET] IPv4 Port redirect: " + targetPort + " → " + proxyPort);
                }
            } else if (family === 10) {  // AF_INET6 (IPv6)
                var currentPort6 = (sockaddr.add(2).readU8() << 8) | sockaddr.add(3).readU8();
                if (currentPort6 === targetPort) {
                    // getaddrinfo("127.0.0.1") 可能同时返回 IPv6 (::1)
                    // adb reverse 只处理 IPv4，需要将 IPv6 重写为 IPv4
                    var newAddr = Memory.alloc(16);  // sizeof(sockaddr_in)
                    newAddr.writeU16(2);              // AF_INET
                    newAddr.add(2).writeU8(proxyPort >> 8);
                    newAddr.add(3).writeU8(proxyPort & 0xFF);
                    newAddr.add(4).writeU8(127);       // 127.0.0.1
                    newAddr.add(5).writeU8(0);
                    newAddr.add(6).writeU8(0);
                    newAddr.add(7).writeU8(1);
                    args[1] = newAddr;
                    args[2] = ptr(16);                 // sockaddr_in 长度
                    console.log("[NET] IPv6→IPv4 redirect: [::1]:" + targetPort + " → 127.0.0.1:" + proxyPort);
                }
            }
        } catch(e) {}
    }
});
```

> **为什么要处理 IPv6？** `getaddrinfo("127.0.0.1")` 在 Android 上可能同时返回 AF_INET（127.0.0.1）和 AF_INET6（::ffff:127.0.0.1 或 ::1）的结果。应用可能优先使用 IPv6 结果，而 `adb reverse` 只处理 IPv4 的 127.0.0.1，导致连接不通。

**字节序说明**：

端口号在 `sockaddr_in` 结构中以**网络字节序（大端序）**存储：
```
sockaddr_in 结构：
┌──────────┬──────────┬──────────┐
│ family   │ port     │ addr     │
│ 2 bytes  │ 2 bytes  │ 4 bytes  │
│ offset 0 │ offset 2 │ offset 4 │
└──────────┴──────────┴──────────┘

port 的大端序存储：
  443   = 0x01BB → 字节 [0x01, 0xBB]
  44300 = 0xAD0C → 字节 [0xAD, 0x0C]

读取: port = (byte[0] << 8) | byte[1]
写入: byte[0] = port >> 8, byte[1] = port & 0xFF
```

**⚠ 重要提醒**：DNS 重定向仅适用于**无 SSL pinning** 的应用。对 Flutter 应用或启用了 SSL pinning 的应用，DNS 重定向会导致 SSL bypass Hook 不被触发（详见 §3.1）。

---

## 4. 常见失败模式

| 现象 | 原因 | 解决 |
|------|------|------|
| 代理捕获不到流量 | 应用使用固定 IP，不走 DNS | 用 iptables 按目标 IP 重定向（注意模拟器 crash 风险，见下方） |
| SSL bypass 后仍握手失败 | CA 证书过期或代理证书链不完整 | 更新代理 CA 证书，检查完整链 |
| Hook read() 只看到加密数据 | SSL bypass 未生效或 Hook 时机不对 | 确认 TrustBuiltinRoots 已被成功调用 |
| 篡改后应用崩溃 | 篡改的数据长度变化导致 Content-Length 不匹配 | 篡改后同步更新 Content-Length 头 |
| Frida 崩溃 | Java bridge 不稳定（Flutter 应用） | 用 native popen/fgets 替代 Java bridge，详见 `$SHARED_DIR/knowledge-base/frida-native-shell-tricks.md` |
| iptables DNAT 导致 app crash | 模拟器上 OUTPUT 链 DNAT 影响 perfetto_hprof 等系统组件，导致 SIGSEGV | 不要在模拟器上用 iptables DNAT；改用 Frida getaddrinfo+connect hook |
| DNS redirect 后代理收不到连接 | getaddrinfo 返回 IPv6 (::1)，app 使用 IPv6 连接但 adb reverse 只处理 IPv4 | connect hook 必须处理 AF_INET6，将 IPv6 转为 IPv4 127.0.0.1（见 §3.4 模板） |
| Memory.allocUtf8String 后 GC 回收 | 在 getaddrinfo hook 的 onEnter 中局部分配字符串，函数返回后可能被 GC | 预分配到全局变量：`var redirectStr = Memory.allocUtf8String("127.0.0.1")` |

---

## 5. 与其他知识库的关系

- Flutter SSL bypass 详见 `$AGENT_DIR/knowledge-base/flutter-ssl-bypass.md`
- TLS 流量拦截（connect 追踪 fd + read 检测 AppData）详见 `$AGENT_DIR/knowledge-base/tls-traffic-interception.md`
- Frida native shell 技巧详见 `$SHARED_DIR/knowledge-base/frida-native-shell-tricks.md`
- Frida 反检测和设备操作详见 `$AGENT_DIR/knowledge-base/mobile-frida.md`
