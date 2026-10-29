# probe-cookie-scope — Cookie 作用域与 SameSite 行为探针

> 验证：SameSite Lax+POST 2 分钟宽限（`Lax-allowing-unsafe`）的适用范围——是否覆盖显式声明 `SameSite=Lax` 的 cookie。
> 何时用：需要复验宽限范围；或分析依赖"跨站 POST 是否携带会话 cookie"的判断时做基线。

## 运行

```bash
cd "$AGENT_DIR/scripts/probe-cookie-scope"
npm install            # puppeteer-core；node_modules 已 gitignore
export CHROME_PATH="/path/to/chrome-for-testing"
node probe_lax_grace.js
```

Chrome for Testing 路径示例：`~/.cache/puppeteer/chrome/<版本>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`

## 脚本与判据

| 脚本 | 端口 | 验证目标 | 成功判据（输出特征） |
|------|------|---------|--------------------|
| `probe_lax_grace.js` | 9011 | 同一响应同时种下"未声明 SameSite"与"显式 `SameSite=Lax`"两个 cookie，从跨站页面 POST | 接收端 Cookie 头只含未声明者（`u=unspecified`），显式 Lax（`t`）不出现 |

## 注意

- 对照前提：种 cookie 方与发起 POST 方必须跨 site（`localhost` 与 `127.0.0.1` 是不同 site；同 host 不同端口是同 site，实验会失真）
- 判据基线：Chrome 146/148/153；换版本先跑基线对照
