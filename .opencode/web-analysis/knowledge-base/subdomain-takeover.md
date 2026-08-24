# 子域接管（Subdomain Takeover）

> DNS 记录（CNAME/NS/MX）指向已下线的云资源/过期第三方服务，攻击者认领该资源名从而控制子域内容。
> 加载时机: 子域 CNAME 指向外部服务且返回 NXDOMAIN/服务商错误页；NS/MX 指向过期域；`*.target.com` 通配。
> **核心洞察: CNAME 存在 ≠ 可接管**——只有指向的资源"未被认领且可认领"才行（S3 返回 403=bucket 存在私有=不可利用；`NoSuchBucket` 404 才可）。

## §1 检测流程与指纹表

```
1. 收集子域（amass/subfinder/assetfinder/crt.sh/SecurityTrails）
2. dig CNAME sub.target.com +short
3. CNAME 目标 NXDOMAIN 或服务商错误页 → 对照指纹
4. 匹配 → 服务商处认领
```

| 服务商 | CNAME | 指纹 |
|---|---|---|
| AWS S3 | `*.s3.amazonaws.com` | `NoSuchBucket` (404) |
| GitHub Pages | `*.github.io` | `There isn't a GitHub Pages site here` |
| Heroku | `*.herokuapp.com` | `No such app` |
| Azure | `*.azurewebsites.net` 等 | 默认页/NXDOMAIN |
| Shopify | `*.myshopify.com` | `Sorry, this shop is currently unavailable` |
| Fastly | Fastly edge | `Fastly error: unknown domain` |
| 其他 | Pantheon/Tumblr/WordPress.com/Zendesk/Unbounce/Ghost/Surge.sh/Fly.io | 各自品牌 404 页 |

工具: `subjack`｜`nuclei -t takeovers/`｜`dnsreaper`｜`subzy`；可利用服务商参考: can-i-take-over-xyz（GitHub）。

## §2 CNAME 接管认领流程

- **AWS S3**: 确认 `NoSuchBucket` → 从 CNAME 提取 bucket 名 → `aws s3 mb s3://sub.target.com --region <region>`（名全局、website 端点分区域）→ 传 index.html → 开静态托管
- **GitHub Pages**: 建 repo → CNAME 文件内容 `sub.target.com` → 开 Pages。**org 已验证域名不可被他人认领**
- **Heroku**: `heroku create <name>` → `heroku domains:add sub.target.com` → 部署 PoC
- CloudFront 需特定 distribution 配置，非单纯认领

## §3 NS 接管（高危——控制全 zone）

```
target.com NS → ns1.expireddomain.com
攻击者注册 expireddomain.com → 控制 target.com 全部 DNS（A/MX/TXT）
```
检测: `dig NS target.com +short` → 每个 NS 域 `whois` 查过期/可注册 → `dig A ns1.x` 查 NXDOMAIN；子授权 zone 单独查。
影响: 全域接管｜任意 CA DNS-01 签 DV 证书（完整 MITM）｜改 SPF/DKIM/DMARC 以目标域名发认证邮件。

## §4 MX 接管（邮件拦截）

MX 指向已停用邮件服务且租户可认领（典型: Google Workspace/M365 租户过期 MX 仍在）→ 建新租户认领域名 → **收密码重置邮件** → 邮件认证账号可重置。

## §5 通配符与二阶链

- **通配符**: `*.target.com` 通配 CNAME 到可认领服务 → 全部未定义子域可接管。检测: `dig A random1234567.target.com` 有解析即通配存在
- **二阶接管**: `sub.target.com CNAME → other.target.com CNAME → dead-service.com`——链必须跟到底
- **SPF 子域接管**: SPF 含 `include:sub.target.com` 时接管该子域 → 改其 TXT 授权自己的邮件服务器 → 以 `target.com` 名义发伪造邮件

## §6 接管后影响评估

```
共享父域 cookie? → 会话劫持
CORS 信任 *.target.com? → 跨源读（见 cors-misconfiguration.md §5）
CSP 白名单 *.target.com? → 加载脚本绕 CSP
OAuth redirect_uri 含子域? → token 窃取
可签 TLS 证书? → 完整 MITM
```

## §7 防御要点

下线云资源同步删 DNS 记录（Critical）｜监控 CNAME 目标 NXDOMAIN｜删记录前先认领保留资源名｜审计 NS 授权域续费（Critical）｜避免通配 CNAME 到第三方｜CT 日志监控。

## §8 关联文件

- `$AGENT_DIR/knowledge-base/cors-misconfiguration.md` — §5 子域链（takeover 作为跳板）
- `$AGENT_DIR/knowledge-base/host-header-attacks.md` — Host 路由
