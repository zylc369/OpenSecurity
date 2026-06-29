# Web 方向源文档索引

> 创建: 2026-06-29

## 博客 Writeup（huli 系列 + cor.team + 其他）

| 文件 | 来源 | 赛事/年份 | 覆盖技术 |
|------|------|----------|---------|
| 2024-googlectf-huli.md | blog.huli.tw | GoogleCTF 2024 | URL parser绕过, parseInt宽松, [A-z]正则陷阱, cookie tossing, CSS trigram exfil, sanitizer序列化绕过, POSTVIEWER V3 hash碰撞 |
| 2023-0ctf-huli.md | blog.huli.tw | 0CTF 2023 | CSS trigram exfil（首发框架）, newdiary |
| 2024-hitcon-cor-sekai-huli.md | blog.huli.tw | HITCON/corCTF/SekaiCTF 2024 | bfcache污染, iframe reparenting, socket.io JSONP CSP绕过, corchat, private browsing响应拆分 |
| 2024-idekctf-iframe-huli.md | blog.huli.tw | idekCTF 2024 | iframe高级魔法, srcdoc+session history, sandbox/CSP继承差异 |
| 2024-dicectf-huli.md | blog.huli.tw | DiceCTF 2024 | connection pool阻塞, 递归@import leak, burnbin |
| 2025-xss-no-paren-huli.md | blog.huli.tw | 2025 | XSS无括号无分号payload进化 |
| 2025-corctf-challenge-dev-2.md | cor.team | corCTF 2025 | Chrome扩展content-script timing侧信道, replaceAll指数膨胀 |
| 2024-corctf-challenge-dev.md | cor.team | corCTF 2024 | Chrome扩展攻击 |
| 2024-sekaictf-htmlsandbox.md | blog.ankursundara.com | SekaiCTF 2024 | charset解析器差异, streaming HTML, ISO-2022-JP chunk切换 |

## 官方文档（PortSwigger）

| 文件 | 来源 | 覆盖技术 |
|------|------|---------|
| portswigger-prototype-pollution.md | portswigger.net | 原型链污染: sources(URL/JSON/web message), sinks, gadgets, client-side检测, server-side检测, RCE(child_process.fork/execSync) |
| portswigger-single-packet-attack.md | portswigger.net | 单包攻击: HTTP/2并发, 竞态条件, limit-overrun, last-byte sync, 方法论 |
