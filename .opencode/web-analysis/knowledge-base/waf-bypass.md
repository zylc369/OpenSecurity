# WAF 绕过（识别/通用/产品矩阵/决策树）

> 何时用: payload 被 WAF/IDS 拦截，需要系统性绕过。payload 层细分（SQL/XSS/RCE/路径）在各自专题文件，本文是横向方法论与产品矩阵。
> 陷阱先读 §5（200≠绕过/大小限制/429≠WAF）。

## 1. WAF 识别（绕过前必做）

```bash
$(dirname $PYTHON_CMD)/wafw00f https://target.com
nmap --script=http-waf-detect,http-waf-fingerprint target.com
curl -s -I https://target.com | grep -iE "server|x-cdn|x-cache|cf-ray|x-sucuri|x-akamai"
```

行为指纹五步（透明代理无特征头时唯一手段）: 良性基线 → 显性攻击 `<script>alert(1)</script>` → 对比状态/阻断页/重置 → 阻断页暴露品牌 → 时间差（透明代理引入延迟）。

| WAF | 特征 | 阻断页 |
|---|---|---|
| Cloudflare | cf-ray / __cf_bm | "Attention Required!" |
| AWS WAF | x-amzn-RequestId | 403 JSON |
| ModSecurity | 规则 ID | "ModSecurity Action" |
| Akamai | AkamaiGHost / x-akamai-* | 错误参考号 |
| Imperva | X-CDN: Imperva / incap_ses_* | "Powered by Incapsula" |
| F5 BIG-IP | BIGipServer / TS cookie | "The requested URL was rejected"+support ID |
| Sucuri | X-Sucuri-ID | "Access Denied - Sucuri" |
| 阿里云 | - | "aliwaf" |
| 腾讯云 | - | "腾讯云Web应用防火墙" |
| 长亭雷池 | - | "雷池" |

429 是限流不是 WAF——降速/换 IP，payload 变异无效。

## 2. 通用绕过类别（速查）

编码: 单/双/三重 URL（%3C→%253C→%25253C）、IIS Unicode %u003c、超长 UTF-8 %C0%BC、HTML 实体 &#60;/&#x3c;、SQL hex 0x756E696F6E、大小写 SeLeCt、空字节 sel%00ect、八进制 \74。
注释/分割: SQL `/**/`、`/*!50000*/` 版本注释、UN/**/ION；PHP `sys/*x*/tem()`；XSS 分段 `"o<x>nmouseover=`。
空白字符: %09 %0A %0D %0B %0C %A0。
替代语法: UNION ALL SELECT、OR 2>1/||、BENCHMARK 代 SLEEP、MID 代 SUBSTRING、Function()/setTimeout 代 eval。
Chunked 分片: payload 切进多 chunk（WAF 不重组时单 chunk 无完整特征）。
HPP: `?a=sel&a=ect`——ASP.NET 拼接 `a=sel,ect`，WAF 只检一处（权威矩阵见 host-header-attacks.md §4）。

细分 payload 库: SQL → sqli-advanced.md / XSS → xss-advanced.md / RCE → command-injection.md / 穿越编码 → path-traversal-lfi.md / XSLT → xslt-injection.md / tamper 链 → sqli-advanced.md §9。

## 3. 产品绕过矩阵（时效性强，用前实测）

### Cloudflare
全角 Unicode 归一化差异；参数名 >128 字符跳检（vs）；JSON body 弱规则；**源站直连**（DNS 历史/Shodan `ssl.cert.subject.cn:target.com`/邮件头）找到即全绕；托管规则 vs OWASP CRS 两模式；免费版规则少。

### AWS WAF
body 只检前 8KB（CloudFront 16KB）——padding 越界；"超限放行"配置直接利用；regex 超时放行（复杂输入）；深层 JSON 嵌套；参数值 Base64 不自动解码；URI/body 规则覆盖面两头测。

### ModSecurity CRS
PL1 默认最弱（不检 %u0027）；报错拿规则 ID 定向绕；`/*!50000*/` MySQL 注释；multipart 畸形 boundary；SecRequestBodyNoFilesLimit 128KB——payload 放文件字段；CRS v4≫v3 先判版本；anomaly scoring 保持单违规低于阈值；SecRuleRemoveById 配置洞。

### Akamai
三重/混合编码链；慢 POST 超时；深 JSON 嵌套；学习引擎有延迟——新模式初期放行；**penalty box 触发后限流数分钟，每次测试换 IP**；Pragma: akamai-x-check-cacheable 泄露路由。

### Imperva
HPP；UTF-8 BOM `\xEF\xBB\xBF` 错位解析；超长 Cookie 截断检测；WebSocket 升级后不检；Client Classification 拦 headless——用真实浏览器指纹；API 模块与 Web WAF 分离。

### F5 BIG-IP ASM
序列化数据检测弱；JSON/XML 切换走不同规则；元字符强制可双编码绕；transparent 学习模式不拦（先显性 payload 探）；signature+violation 两套都要绕；TS cookie 篡改重置会话。

### Sucuri
冷门标签 `<svg/onload>`、`<details/ontoggle>`、`<marquee onstart>`；MID()/CONV()；`..%252f`；WordPress 攻击面组合；方法切换。

### 国内
阿里云: chunked/重复 Content-Type（urlencoded+multipart 同现）/超长 URL。腾讯云: HPP/编码混合 `%75nion %73elect`。长亭雷池: 语义分析型——编码类弱，语法等价变形优先。

## 4. 网络层绕过

IP 源伪造（WAF 白名单内网/分源规则时）:
```
X-Forwarded-For / X-Real-IP / X-Originating-IP / True-Client-IP / CF-Connecting-IP / X-Client-IP / Forwarded: for= / X-Remote-IP / CDN-Src-IP
```
源站直连: DNS 历史 / Shodan 证书 / 邮件头 → 直连带原 Host 头。
CDN 缓存: 已缓存响应不过 WAF——投毒后命中。
连接状态: keep-alive 先正常后攻击（部分 WAF 降检）；绝对 URI 请求行 `GET http://target/path HTTP/1.1`；H2→H1 降级引走私；WebSocket 升级后流量不检。

## 5. 陷阱注记（判读必读）

1. **200 OK ≠ 绕过**: WAF 可能静默剥离 payload。验证用回显/时间/出网，非状态码。500 可能是 payload 到达后端（好信号）。
2. **大小限制**: AWS 8KB / CloudFront 16KB / Cloudflare 128KB / ModSec NoFilesLimit 128KB。超界不检但"超限阻断"配置反向会拦。
3. **429 = 限流非 WAF**。
4. **缓存的响应不过 WAF**。
5. **multipart 文件字段常跳检**——payload 放文件名/文件内容（若反射）。
6. **Content-Type 切换是首选**: urlencoded→JSON（规则普遍更弱）→multipart→text/xml。
7. **F5 学习模式全 200 无意义**——先探模式。
8. 响应判读: 基线 wc -c → 拦截 → 尝试，三元组（状态/长度/内容）对比。

## 6. 决策树

```
拦截?
├── ① 识别（§1）
├── ② 编码类（§2 + 各专题 payload 库）
├── ③ 协议层: Content-Type 切换/multipart 滥用/chunked/HPP/绝对 URI/H2 直连
├── ④ 路径类: /./、//、%61、;(Tomcat)、\(IIS)
├── ⑤ payload 变异: 注释/替代函数/双写/tamper 链
├── ⑥ 网络层: IP 伪造/源站直连/缓存/keep-alive（§4）
├── ⑦ 产品定向（§3）
├── ⑧ Java 后端: Ghost Bits 字符窄化 255 变体/字节 → ghost-bits-cast-attack.md
└── ⑨ 请求走私完全绕过 → request-smuggling.md
```
顺序: ②③ 成本低先试 → ⑤⑥ → ⑦⑧ 按指纹 → ⑨ 最后。每步用实际效果验证（§5）。

**反向场景——服务端校验客户端 JA4/JA4H 指纹**: 本文 §1 是识别 WAF 产品；当目标是服务端用 TLS ClientHello 哈希（JA4）与 HTTP 头序哈希（JA4H）校验客户端真伪时（Cloudflare/Akamai bot 检测），UA 伪造无效，需精确复刻头序或真实浏览器——战术见 `auth-attacks.md` §6。

防御换位: 参数化查询/输出编码+CSP 与 WAF 无关（根治层）；默认拒绝优于黑名单；WAF 日志告警。

**网络层增补**: TCP 分包绕内容防火墙——关键字拆到 TCP 包边界（s.send(b"GET /fla"); s.send(b"g.html ...")）。
