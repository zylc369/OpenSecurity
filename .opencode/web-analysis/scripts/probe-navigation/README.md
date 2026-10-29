# probe-navigation — 导航回放与请求元数据探针

> 验证：BFCache 挤出后 `history.go(-N)` 回放的请求头（`Sec-Fetch-Site: none`）；`location.href` / `reload` / 回放三类导航的 Sec-Fetch-* 差异。
> 何时用：需要复验"历史回放被当作用户操作"类断言；或分析依赖 Sec-Fetch-* 判断时做基线。

## 运行

```bash
cd "$AGENT_DIR/scripts/probe-navigation"
npm install            # puppeteer-core；node_modules 已 gitignore
export CHROME_PATH="/path/to/chrome-for-testing"
node probe_history.js
```

Chrome for Testing 路径示例：`~/.cache/puppeteer/chrome/<版本>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`

## 脚本与判据

| 脚本 | 端口 | 验证目标 | 成功判据（输出特征） |
|------|------|---------|--------------------|
| `probe_history.js` | 9969 | 8 次连续导航挤出 BFCache 后 `history.go(-9)` 回放 | 回放请求 `Sec-Fetch-Site=none`，摘要列出各请求头 |
| `probe_secfetch.js` | 9970 | `location.href` 导航 / `reload` / history 回放的 Sec-Fetch-* 对比 | SUMMARY 表列出各场景 site/dest/user/mode |

## 注意

- 判据基线：Chrome 146/148/153；换版本先跑基线对照
