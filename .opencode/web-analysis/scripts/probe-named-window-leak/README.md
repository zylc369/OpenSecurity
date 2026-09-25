# probe-named-window-leak

验证 CSP `default-src 'none'` 下的命名窗口泄漏：`<form target>` GET 提交到同源端点 + `open('', name)` 取回已存在的命名窗口读响应 body。

## 断言

| 判据 | 期望 |
|---|---|
| fetchBlocked | `true`（fetch 被 `default-src 'none'` 拦截——对照组，证明 CSP 生效） |
| formOpenedWindow | `true`（form target 导航不被 default-src 拦截） |
| reopenedIsWindow | `true`（`open('', 'flagwin')` 返回已存在命名窗口） |
| readBack | `true`（读到窗口 body） |
| secretLeaked | `true`（innerText 含 secret JSON） |

**结论语义**: secretLeaked=true ⇒ `connect-src/default-src 'none'` 只拦 fetch/XHR，不拦表单导航与命名窗口读取——同源响应可经此通道外带。

## 运行

```bash
cd "$AGENT_DIR/scripts/probe-named-window-leak"
npm install            # puppeteer-core；node_modules 已 gitignore
CHROME_PATH="/path/to/chrome-for-testing" node probe_form_target_read.js
```

已验证版本: Chrome for Testing 146.0.7680.153 / 148.0.7778.97 / 153.0.8010.36（mac arm64）。

关联知识: `$AGENT_DIR/knowledge-base/client-side-attacks.md` 命名窗口泄漏节。
