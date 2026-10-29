---
来源: https://ctfbase.com/api/v1/writeups/20260830_asisctf2026_proxy_dough （预览，全文需 Pro）
     https://portswigger.net/research/css-the-bomb-inside-your-inbox （无关）
     技术验证: https://developers.cloudflare.com/images/optimization/features/ （onerror=redirect 官方语义）
     https://blog.voorivex.team/cloudflare-image-proxy-as-a-cspt-gadget-a-cross-origin-cspt-exploit （CSPT gadget）
类型: preview
获取日期: 2026-09-12
---

# Proxy Dough — ASIS CTF 2026 (web, medium)

## 题目结构

- `/api/proxy?url=...` SSRF 图片代理：`parse_url($url)` 校验 scheme=https 且 host=img.proxydough.net（严格 strtolower 比较）
- 通过 `file_get_contents($url, false, $context)` 抓取：`ignore_errors=true`、`follow_location` 默认开（最多 20 跳）、TLS 校验开
- 最终 body 原样回显给客户端（Content-Type: image/png）
- `/api/recipe` 仅对 `REMOTE_ADDR` 为 127.0.0.1/::1 的客户端返回 flag
- 目标：让源站 PHP 经代理连自己的 loopback recipe 端点

## 解法核心

1. **Cloudflare /cdn-cgi/image/onerror=redirect/ gadget**：img.proxydough.net 是 Cloudflare 代理且开了 Image Resizing。
   请求 `https://img.proxydough.net/cdn-cgi/image/onerror=redirect/<source-url>`——当 source image 无法转换时，
   Cloudflare 返回 **307 Location 指向原始 source URL**。攻击者构造的 source URL 使 307 的 Location 可控。
2. **WHATWG vs PHP 反斜杠 authority 解析差异**：Cloudflare（WHATWG URL 解析，`\` 当 `/`）认为 host 在 zone 内；
   构造 `http://img.proxydough.net\@127.0.0.1/api/recipe` 类 URL——WHATWG 把 `\` 归一为 `/`（host=img.proxydough.net），
   而 PHP 跟随 307 时按自己的解析把 `\@` 前当作 userinfo、host 取 127.0.0.1。
3. PHP file_get_contents 跟随 307 → 连接 127.0.0.1/api/recipe → REMOTE_ADDR=127.0.0.1 → flag 回显。

## 约束（Cloudflare 官方文档）

- onerror=redirect 只对**同 zone**（子域可）的 source image 生效，跨 zone 被忽略
- 307/308 重定向保留 method/body/headers（对 CSPT 链关键）

## 相关标签

ssrf, cloudflare, image_resizing, cdn_cgi, url_parsing_differential, backslash_authority,
whatwg_vs_rfc3986, onerror_redirect, php, file_get_contents, follow_location, loopback, 307_redirect
