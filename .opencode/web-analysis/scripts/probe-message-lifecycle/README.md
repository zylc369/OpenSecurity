# probe-message-lifecycle — 跨文档 postMessage 投递与窗口身份探针

> 验证：消息跨文档切换投递时 `e.source` 的取值（源文档已销毁 → `null`）、pagehide/自导航时序、身份比较 `e.source === viewer.contentWindow` 的翻转条件。
> 何时用：需要复验上述行为断言；或与其他版本/环境结果对照时做基线。

## 运行

```bash
cd "$AGENT_DIR/scripts/probe-message-lifecycle"
npm install            # puppeteer-core；node_modules 已 gitignore
export CHROME_PATH="/path/to/chrome-for-testing"
node race_nosandbox.js
```

Chrome for Testing 路径示例：`~/.cache/puppeteer/chrome/<版本>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`

## 脚本与判据

| 脚本 | 端口 | 验证目标 | 成功判据（输出特征） |
|------|------|---------|--------------------|
| `race_nosandbox.js` | 9974 | 沙箱 iframe 身份竞态：pagehide 发消息后投递时的 `e.source` 与过滤结果 | `eq=false`、`[probe] e.source===null: true`、`PASSED FILTER` |
| `pagehide_race_demo.js` | 9974 | 同上，含切换前窗口快照对照 | 同上，另 `e.source===savedBeforeSwitch: false` |
| `probe_selfnav.js` | 9973 | 发送方先发消息再自导航：是否送达、`e.source` 取值 | `PARENT GOT MSG` + `e.source===null: true` |
| `probe_selfnav2.js` | 9972 | 同上 + 父页面忙阻塞事件循环强制"投递时源文档已销毁"时序 | 同上 |
| `probe_selfnav3.js` | 9971 | 自导航 + pagehide 发消息组合 | 同上 |

## 注意

- 9974 端口被两个 race 脚本共用，不要同时运行
- 判据基线：Chrome 146/148/153；换版本先跑基线对照
