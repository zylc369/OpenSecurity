# Next.js App Router 安全分析方法论

> Next.js App Router 安全分析参考。聚焦 App Router 模式的安全分析，包括 RSC/flight data 分析、node_modules 源码审计、middleware 审计。

---

## 1. 识别 Next.js App Router

### 1.1 指纹识别

| 探测方法 | App Router 信号 | Pages Router 信号 |
|---------|----------------|-------------------|
| 响应头 `X-Powered-By` | `Next.js`（无版本号） | 同左 |
| HTML 中的 JS chunk | `/_next/static/chunks/main-app-*.js` | `/_next/static/chunks/main-*.js`（无 `app`） |
| `_buildManifest.js` | 存在且路径为 `/_next/static/{buildId}/_buildManifest.js` | 同左，但内容中页面路由列表不同 |
| 目录结构 | `app/` 目录（有 `layout.tsx`） | `pages/` 目录（有 `index.tsx`） |
| 响应头中的 Vary | `rsc, next-router-state-tree, ...` | 无 RSC 相关 Vary 参数 |

### 1.2 版本推断

- **黑盒**：通常无法获取精确版本号。可下载最近几个版本源码对比关键文件
- **白盒**：查看 `package.json` 中的 `next` 版本

### 1.3 关键路径约定

| 路径 | 说明 | 安全影响 |
|------|------|---------|
| `/_next/static/` | 静态资源（JS/CSS/字体） | 通常无安全风险，不经过 middleware |
| `/_next/data/` | Pages Router 的数据路由 | App Router 下不存在 |
| `/_next/{任意路径}` | App Router 下可能触发 404 页面渲染 | **404 页面仍经过 layout.tsx**，可能包含注入点 |
| `middleware.ts` | 请求拦截器 | 可能修改请求/响应头 |
| `app/layout.tsx` | 根布局（所有页面共用） | 通常包含全局注入点 |

---

## 2. RSC（React Server Components）安全分析

### 2.1 RSC 渲染模式判断

Next.js 通过 `RSC` **请求头**判断渲染模式：

| 请求 | base-server.js 判断 | app-render.js 判断 | 输出格式 |
|------|-------------------|-------------------|---------|
| 无 RSC 头 | `headers['rsc'] === '1'` → false | `headers['rsc'] !== undefined` → false | HTML（转义特殊字符） |
| `RSC: 1` | `=== '1'` → true | `!== undefined` → true | flight data（不转义） |
| **`RSC: `**（空字符串） | `=== '1'` → **false** | `!== undefined` → **true** | **flight data（不转义）** |

**关键发现**：当两个模块对同一请求头使用不同判断逻辑时（严格匹配 vs 存在性检查），空字符串值可能导致行为分歧。

### 2.2 flight data 安全分析

**flight data 格式**（React Flight Protocol）：

```
0:["$","html",null,{"lang":"en","children":[...]}]
1:["$","body",null,{"nonce":"<script>alert(1)</script>","children":[...]}]
```

**核心安全问题**：flight data 中的字符串值不做 HTML 转义（`<` 保持原样）。正常情况下无风险（CT 为 `text/x-component`，浏览器不解析），但如果 CT 被改为 `text/html`，浏览器会把 flight data 当 HTML 解析，未转义的 `<script>` 会被执行。

### 2.3 框架源码不一致性探测方法

**步骤**：

1. 在 `node_modules/next/dist/server/` 中搜索关键判断逻辑：
   ```
   grep -r "headers\['rsc'\]" node_modules/next/dist/
   grep -r "rsc.*===" node_modules/next/dist/server/
   ```

2. 对比不同文件中对同一请求头的判断方式：
   - `base-server.js`：请求调度，通常在入口处判断
   - `app-render.js`：渲染引擎，负责实际输出
   - `base-server.js` 搜索 `isRSCRequest` 关键词
   - `app-render.js` 搜索 `isRSCRequest` 关键词

3. 重点关注**严格匹配（`===`/`!==`）vs 存在性检查（`!== undefined`/`=== undefined`）**的差异

4. 测试空字符串、`0`、`false` 等边界值

**通用规则**：任何被多个模块独立判断的请求头，都可能存在不一致性。

---

## 3. Middleware 安全审计

### 3.1 Next.js middleware 特性

- 运行在 Edge Runtime（不是 Node.js）
- 每个匹配的请求都会经过
- 可以修改请求头和响应头
- 不能直接修改响应体

### 3.2 审计清单

| 检查项 | 说明 | 风险 |
|--------|------|------|
| CT 覆盖 | middleware 是否允许请求头覆盖响应的 Content-Type？ | flight data 被当 HTML 解析 |
| 请求头反射 | middleware 是否将请求头值写入响应头？ | HTTP 头注入 |
| 重定向逻辑 | middleware 是否有基于 URL 参数的重定向？ | 开放重定向 |
| 路径过滤 | middleware 的 matcher 配置是否覆盖了关键路径？ | 路径绕过 |
| 认证检查 | middleware 是否做了认证/授权检查？ | 认证绕过 |

### 3.3 CT 覆盖漏洞模式

```typescript
// 危险：允许请求头覆盖响应 CT
const contentType = request.headers.get('content-type')
if (contentType) {
  response.headers.set('Content-Type', contentType)  // 攻击者可控
}
```

**安全写法**：白名单验证 + 禁止覆盖为 `text/html`。

---

## 4. Bot 类 Next.js 题目分析

### 4.1 关键检查点

| 检查项 | 说明 |
|--------|------|
| Bot 访问方式 | `page.goto()` 直接导航 vs 页面内链接点击？直接导航不走 Next.js 客户端路由 |
| Cookie 域 | 绑定在哪个域名下？（决定了 Host 头必须匹配） |
| Bot 的 AE 头 | Docker 中的 Chromium 可能不支持 Brotli（AE 不含 `br`） |
| 有无外网 | Docker 网络隔离时，需要缓存中缓存或 DNS exfiltration |
| nonce 来源 | nonce 值是否来自请求头？（决定了是否有注入点） |

### 4.2 缓存键对齐检查

当 nginx 有缓存且 Bot 通过 Docker 内部域名访问时：

```
攻击者（外网）: Host: 46.62.153.171:4000  → 缓存主键含 46.62.153.171
Bot（内网）:    Host: proxy:4000           → 缓存主键含 proxy

→ 主键不匹配！攻击者投毒的缓存 Bot 命中不了
→ 解决：攻击者伪造 Host: proxy:4000
```

### 4.3 Vary 头对齐检查

```
投毒请求: RSC: "" (空字符串) → nginx 记录 rsc=""
Bot 请求:  (不发送 RSC 头)   → nginx 查找 rsc="" (缺失 = 空字符串)
→ 匹配！

投毒请求: Accept-Encoding: gzip, deflate     → nginx 记录 AE
Bot 请求:  Accept-Encoding: ???               → 必须精确匹配
→ 需要探测 Bot 的 AE 值
```

---

## 5. node_modules 压缩代码阅读技巧

### 5.1 定位关键文件

```
node_modules/next/dist/server/
├── base-server.js     # 请求调度器（入口）
├── app-render.js      # 渲染引擎
├── next-server.js     # 服务器主类
└── base-http/         # HTTP 处理基础
```

### 5.2 搜索策略

1. **从应用代码的 API 调用入手**：如 `headers()` → 搜索 `headers` 在框架中的实现
2. **按关键词搜索**：header 名称、配置项名称、函数名
3. **对比同一功能在不同文件中的实现**：差异即漏洞候选

### 5.3 阅读技巧

- 压缩代码中函数名通常保留，变量名可能被缩短
- 用格式化工具（prettier）先美化
- 关注 `===`、`!==`、`==`、`!=` 等比较运算符的差异
- 注意 `undefined`、`null`、`''`（空字符串）、`0` 等边界值的处理

---

## 6. 实战案例

### 6.1 future.js 攻击链（CyberGame 2026）

```
攻击链：
  ① 发送 GET /_next/pwn + RSC: "" + Content-Type: text/html + x-nonce: <script>XSS</script>
  ② middleware 覆盖 CT 为 text/html
  ③ base-server.js: RSC !== "1" → 选标准路由（不标记为 RSC 请求）
  ④ app-render.js: RSC !== undefined → 按 RSC 模式渲染 → flight data（不转义 nonce）
  ⑤ nginx 缓存：主键含 Host:proxy，二级键 rsc="" + AE="gzip, deflate"
  ⑥ Bot 访问 /_next/pwn → Host:proxy + 无 RSC + AE 匹配 → HIT
  ⑦ 浏览器把 flight data 当 HTML 解析 → <script> 执行 → XSS
  ⑧ 缓存中缓存：XSS 把 Cookie 写入 /_next/exfil 的缓存
  ⑨ 攻击者读取 /_next/exfil 的缓存 → 拿到 flag

关键发现：
  - 框架内部不一致性（base-server.js vs app-render.js 的 RSC 判断）
  - nginx 对空 header 和缺失 header 的处理差异
  - 缓存中缓存技术（无外网环境下的数据渗出）
```

> 缓存投毒的完整方法论（缓存键探测、AE 差异利用、缓存中缓存、Bot AE 探测）见 `$AGENT_DIR/knowledge-base/cache-poisoning.md`。
> 自动化探测脚本见 `$AGENT_DIR/scripts/cache_poison.py`。

### 6.2 黑盒探测可获取的信息

| 探测方法 | 可获取 | 不可获取 |
|---------|-------|---------|
| 响应头分析 | 框架类型、App Router 模式、Vary 头内容 | 精确版本号、框架内部逻辑 |
| buildId 获取 | 确认 App Router | 无 |
| 缓存行为测试 | 缓存路径范围、缓存键组成 | — |
| CT 覆盖测试 | middleware 是否允许 CT 覆盖 | — |
| 灰盒分析 | 下载最近版本源码对比 | 需要猜测版本范围 |
