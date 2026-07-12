<domain_sources>

## 领域：Web 分析

### 优先信息源

1. **PortSwigger Web Security Academy** — `https://portswigger.net/web-security/`
   权威的漏洞类型：XSS、SQLi、SSRF、缓存投毒、原型污染、请求走私。使用 `websearch` 搜索 "portswigger <vuln-class>"。

2. **OWASP** — `https://owasp.org/www-community/attacks/`
   攻击分类法和速查表（`https://cheatsheetseries.owasp.org/`）。

3. **HackerOne Hacktivity** — `https://hackerone.com/hacktivity`
   真实世界的已披露报告 —— 非标准漏洞的金矿。
   注：该页为 SPA，webfetch 不可用，改用聚合镜像 `https://github.com/reddelexc/hackerone-reports`。

4. **PayloadsAllTheThings** — `https://github.com/swisskyrepo/PayloadsAllTheThings`
   XSS、SSRF、LFI、命令注入等的现成 payload。

5. **HackTricks** — `https://book.hacktricks.xyz/`
   攻击技巧百科，更新比 PayloadsAllTheThings 更频繁，覆盖 Web/网络/云等场景。

6. **CVE/NVD** — `https://nvd.nist.gov/` + `https://www.cve.org/`
   通用漏洞库，用于跨框架反查 CVE 编号与受影响版本范围。
   注：cve.org 为 SPA，webfetch 不可用；CVE 详情反查走 NVD（`https://nvd.nist.gov/vuln/search`）。

7. **Exploit-DB** — `https://www.exploit-db.com/`
   已公开 exploit 归档，含 web 板块，可按 CVE/平台/类型检索。

8. **PortSwigger Research** — `https://portswigger.net/research/`
   Web 安全原始研究发布地（缓存投毒起源论文、HTTP 请求走私系列、最新攻击面研究）。

9. **Nuclei Templates** — `https://github.com/projectdiscovery/nuclei-templates`
   PoC 模板库，可按漏洞类型/CVE 反查实际检测逻辑与 payload。

10. **框架专属安全公告**：
    - Laravel: `https://github.com/laravel/framework/security/advisories`
    - Django: `https://docs.djangoproject.com/en/stable/releases/security/`
    - Spring: `https://spring.io/security`
    - Next.js: `https://github.com/vercel/next.js/security/advisories`
    - Express/Node (npm): `https://github.com/advisories?query=type%3Areviewed+ecosystem%3Anpm`
    - Ruby on Rails: `https://github.com/rails/rails/security/advisories`
    - Node.js 平台本体: `https://github.com/nodejs/security-wg`

11. **HTTP RFCs** — `https://www.rfc-editor.org/`
    头部语义/缓存指令/方法行为存疑时直接查 RFC：RFC 9110（HTTP Semantics）、RFC 9112（HTTP/1.1）、RFC 9113（HTTP/2）、RFC 9114（HTTP/3）、RFC 7234（Caching）。

12. **缓存投毒参考资料** — `https://portswigger.net/web-security/web-cache-poisoning`
    专门针对缓存投毒/缓存欺骗攻击。

### 查询术语约定

- 包含框架+版本：`"Laravel 11"`、`"Next.js 14"`、`"Spring Boot 3.2"`
- 对于 payload：包含绕过类型（`"XSS filter bypass"`、`"WAF bypass"`、`"CSP bypass"`）
- 对于缓存：包含缓存层（`"Cloudflare cache"`、`"Varnish cache"`、`"nginx fastcgi cache"`）
- 对于走私：包含变体（`"CL.TE"`、`"TE.CL"`、`"TE.TE"`、`"H2.TE"`、`"H2.CL"`、`"H2.H2"`）
- 对于 CRLF：包含 `"CRLF injection"`、`"HTTP response splitting"`
</domain_sources>
