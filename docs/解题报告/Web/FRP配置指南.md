# FRP 配置指南——从零开始的安全配置

> 这份指南面向 FRP 初学者，重点讲清楚每个配置项是什么、为什么需要、怎么配。
>
> FRP 官方文档偏"参考手册"风格（列了所有配置但没解释为什么），这里用"教学"风格写。

## 目录

- [第一章：FRP 是什么、怎么工作](#第一章frp-是什么怎么工作)
- [第二章：安装和基本配置](#第二章安装和基本配置)
- [第三章：auth.token——最关键的安全配置](#第三章authtoken最关键的安全配置)
- [第四章：域名配置——subdomain vs customDomains](#第四章域名配置subdomain-vs-customdomains)
- [第五章：完整的安全配置模板](#第五章完整的安全配置模板)
- [第六章：常见问题](#第六章常见问题)

---

## 第一章：FRP 是什么、怎么工作

### 1.1 解决什么问题

你的服务跑在家里（或公司内网），没有公网 IP，外部用户访问不到。FRP 就是把内网服务"穿透"到公网。

### 1.2 两个角色

```
┌──────────────┐         ┌──────────────┐
│   frps       │         │   frpc       │
│  (服务端)    │         │  (客户端)    │
│              │         │              │
│  跑在 VPS 上 │◄────────│  跑在内网机器上│
│  有公网 IP   │  主动连接 │  没有公网 IP  │
└──────────────┘         └──────────────┘
```

- **frps**：运行在有公网 IP 的 VPS 上，监听端口，等待 frpc 连接
- **frpc**：运行在内网机器上，主动连接到 frps，注册"代理"（告诉 frps："把某某域名的流量转发给我"）

### 1.3 三个端口

| 端口名称 | 默认值 | 作用 | 谁在监听 |
|---------|--------|------|---------|
| bindPort | 7000 | frpc 连接 frps 用的端口 | frps |
| vhostHTTPPort | 无 | 接收 HTTP 请求、按域名路由的端口 | frps |
| localPort | 自定义 | 内网服务的真实端口 | frpc 转发到这里 |

举个例子：

```
frps.toml:
  bindPort = 7000          ← frpc 连接这个端口
  vhostHTTPPort = 80       ← 外部用户通过这个端口访问

frpc.toml:
  serverAddr = "你的VPS_IP"
  serverPort = 7000        ← 连接 frps 的 bindPort

  [[proxies]]
  type = "http"
  localPort = 8080         ← 内网服务跑在 8080
  subdomain = "www"        ← 匹配 www.你的域名.com

用户访问: http://www.你的域名.com/ → VPS:80 → frps → frpc → 内网:8080
```

---

## 第二章：安装和基本配置

### 2.1 下载

```bash
# 从 GitHub 下载最新版
# https://github.com/fatedier/frp/releases

# VPS 上只需要 frps
# 内网机器上只需要 frpc
```

### 2.2 服务端最小配置

```toml
# frps.toml（VPS 上）

bindPort = 7000                    # frpc 连接端口
vhostHTTPPort = 80                 # HTTP 虚拟主机端口
```

启动：

```bash
./frps -c frps.toml
```

### 2.3 客户端最小配置

```toml
# frpc.toml（内网机器上）

serverAddr = "你的VPS公网IP"
serverPort = 7000                  # 对应 frps 的 bindPort

[[proxies]]
name = "my-web"                    # 代理名称（随便起，不重复就行）
type = "http"                      # 代理类型
localIP = "127.0.0.1"             # 内网服务的 IP
localPort = 8080                   # 内网服务的端口
subdomain = "www"                  # 匹配 www.你的域名
```

启动：

```bash
./frpc -c frpc.toml
```

---

## 第三章：auth.token——最关键的安全配置

### 3.1 问题

上面的最小配置**没有认证**。任何人知道你的 VPS IP 和 bindPort，就能：
1. 连接你的 frps
2. 注册域名代理
3. 劫持你的流量

这正是 <靶机网站> 被攻破的原因。

### 3.2 解决方案：auth.token

```toml
# frps.toml（服务端）
bindPort = 7000
vhostHTTPPort = 80
auth.token = "一个很长的随机密码"       # ← 新增这一行
```

```toml
# frpc.toml（客户端）
serverAddr = "你的VPS公网IP"
serverPort = 7000
auth.token = "一个很长的随机密码"       # ← 和服务端一样的密码
```

两边 token 必须一致。不一致的话 frpc 连接时会被拒绝：

```
[W] login to the server failed: token is not valid
```

### 3.3 生成随机 token

```bash
# 方法1: openssl
openssl rand -hex 32
# 输出: a3f7b9c2d1e8f4a6b5c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1

# 方法2: python
python3 -c "import secrets; print(secrets.token_hex(32))"

# 方法3: 随便打一段话也行，只要够长够随机
```

### 3.4 新旧版本差异

FRP 的配置格式在不同版本之间有变化：

| 版本范围 | 配置格式 | 认证配置 |
|---------|---------|---------|
| v0.52+ | TOML（推荐） | `auth.token = "xxx"` |
| v0.37 - v0.51 | TOML 或 INI | `auth.token = "xxx"` |
| v0.34 及更早 | 仅 INI | `[common]` 下 `privilege_token = "xxx"` |

**如果你在老版本（<0.34）的文档里看到 `privilege_token`，在新版本中改成了 `auth.token`。**

检查你安装的版本：

```bash
./frps --version
# 或
./frpc --version
```

---

## 第四章：域名配置——subdomain vs customDomains

### 4.1 subdomain（推荐）

服务端指定一个根域名，客户端只能注册这个根域名下的子域名：

```toml
# frps.toml（服务端）
subdomainHost = "<靶机网站>"    # 根域名

# frpc.toml（客户端）
[[proxies]]
subdomain = "www"                   # 生成 www.<靶机网站>

# 另一个客户端
[[proxies]]
subdomain = "api"                   # 生成 api.<靶机网站>
```

**优点**：服务端控制了域名范围，客户端无法注册 `evil.com` 这样的外部域名。

### 4.2 customDomains

客户端可以注册任意域名：

```toml
# frps.toml（服务端）
# 不配置 subdomainHost

# frpc.toml（客户端）
[[proxies]]
customDomains = ["www.<靶机网站>", "api.example.com", "任意域名.com"]
```

**风险**：客户端可以注册任何域名。如果 frps 没有 auth.token，攻击者可以注册你的域名。

### 4.3 两者可以共存

```toml
# frps.toml
subdomainHost = "<靶机网站>"    # 限制 subdomain 的范围

# frpc.toml
[[proxies]]
name = "www"
subdomain = "www"                   # 只能是 xxx.<靶机网站>

[[proxies]]
name = "custom"
customDomains = ["other.com"]       # 仍然可以注册其他域名
```

如果想让 customDomains 也受限，可以不使用 customDomains，只用 subdomain。

### 4.4 vhostHTTPPort 的作用

只有配置了 `vhostHTTPPort`，FRP 才会做 HTTP 域名路由：

```toml
# frps.toml
bindPort = 7000          # frpc 连接端口
vhostHTTPPort = 8001     # HTTP 域名路由端口
# vhostHTTPSPort = 8002  # HTTPS 域名路由端口（可选）

# 工作方式：
# - 端口 7000: frpc 连接（二进制协议，不处理 HTTP）
# - 端口 8001: HTTP 请求（读取 Host 头，按域名路由到对应的 frpc）
# - 端口 8002: HTTPS 请求（需要配置 TLS 证书）
```

用户访问 `http://www.<靶机网站>:8001/` 时，请求到 VPS 的 8001 端口，frps 读取 Host 头 `www.<靶机网站>`，匹配到对应的 frpc 代理，转发过去。

---

## 第五章：完整的安全配置模板

### 5.1 服务端（frps.toml）

```toml
# === 基础配置 ===
bindPort = 7000                      # frpc 连接端口（建议改为非标准端口如 58921）
vhostHTTPPort = 8001                 # HTTP 虚拟主机端口
# vhostHTTPSPort = 8002              # HTTPS（如果需要）

# === 安全配置 ===
auth.token = "用 openssl rand -hex 32 生成"    # 认证 token（必须配置！）
subdomainHost = "<靶机网站>"     # 限制客户端只能注册子域名

# === 可选：Dashboard（管理面板）===
# webServer.addr = "127.0.0.1"       # 只监听本地（不要暴露到公网）
# webServer.port = 7500
# webServer.user = "admin"
# webServer.password = "另一个复杂密码"

# === 可选：端口白名单（限制客户端能注册的远程端口）===
# allowPorts = [
#   { start = 8001, end = 8001 },
#   { start = 9000, end = 9100 }
# ]
```

### 5.2 客户端（frpc.toml）

```toml
# === 连接配置 ===
serverAddr = "你的VPS公网IP"
serverPort = 7000                    # 对应 frps 的 bindPort
auth.token = "和服务端一样的token"     # 必须一致

# === HTTP 代理 ===
[[proxies]]
name = "www-web"
type = "http"
localIP = "127.0.0.1"
localPort = 8080                     # 本地 nginx/Spring Boot 的端口
subdomain = "www"                    # www.<靶机网站>

# 如果有多个子域名
[[proxies]]
name = "api-web"
type = "http"
localIP = "127.0.0.1"
localPort = 8080
subdomain = "api"                    # api.<靶机网站>
```

### 5.3 用 systemd 管理自启动

**服务端（VPS）：**

```ini
# /etc/systemd/system/frps.service
[Unit]
Description=FRP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable frps
sudo systemctl start frps
```

**客户端（内网机器）：**

```ini
# /etc/systemd/system/frpc.service
[Unit]
Description=FRP Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 第六章：常见问题

### Q1: frps.toml 和 frpc.ini 有什么区别？

FRP 0.52+ 推荐用 TOML 格式（`.toml`）。旧版本用 INI 格式（`.ini`）。两者只是文件格式不同，配置项名称是一样的。

### Q2: 为什么 `auth.token` 在官方文档里找不到？

官方文档的侧边栏叫"Authentication"，里面确实有写，但埋得很深。而且老版本叫 `privilege_token`，新版本才改叫 `auth.token`，容易混淆。

### Q3: 端口 8001 访问返回 "powered by frp" 的 404 页面

这说明 frps 在运行，但请求的 Host 头没有匹配到任何代理。检查：
1. frpc 是否正常运行并注册了代理
2. 请求的 Host 头是否和注册的域名一致

### Q4: "router config conflict" 错误

说明你想注册的域名/子域名已经被其他 frpc 注册了。检查是否有其他客户端占用了这个域名。

### Q5: "custom domain should not belong to subdomain host" 错误

frps 配置了 `subdomainHost`，而你用了 `customDomains` 注册了一个该 host 的子域名。改为用 `subdomain` 字段：

```toml
# 错误写法
customDomains = ["www.<靶机网站>"]

# 正确写法
subdomain = "www"
```

### Q6: 如何查看当前有哪些代理已注册

启动 frps 的 dashboard：

```toml
# frps.toml
webServer.addr = "127.0.0.1"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "your_password"
```

然后访问 `http://VPS_IP:7500`，登录后可以看到所有已注册的代理。

### Q7: 客户端断线重连

frpc 默认支持自动重连。如果连接断开，它会每隔几秒自动重试。不需要额外配置。

### Q8: 如何隐藏 FRP 的特征

1. **换非标准端口**：`bindPort = 58921` 而不是 7000
2. **隐藏版本信息**：FRP 默认不在 banner 中暴露版本，但 404 页面包含 "powered by frp"
3. **用 TLS 加密控制通道**：`transport.tls.enable = true`（0.52+ 版本支持）
