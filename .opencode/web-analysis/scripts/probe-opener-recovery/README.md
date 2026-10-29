# probe-opener-recovery

验证 popup 内 `window.opener = null` 之后，父窗口 postMessage 到 popup 时 popup 收到的 `event.source` 是否仍为可用的父窗口引用。

## 断言

| 判据 | 期望 |
|---|---|
| msg1SrcNotNull | `true`（置 null 前 e.source 指向父窗口） |
| pong1Received | `true`（经 e.source 回发成功） |
| openerIsNull | `true`（确认 opener 已被置 null） |
| msg2SrcNotNull | `true`（**置 null 后** e.source 仍指向父窗口） |
| pong2Received | `true`（仍可经 e.source 回发） |

**结论语义**: recoveryWorks=true ⇒ `opener = null` 只清除 popup 侧存储的引用，不影响后续 postMessage 消息的 `event.source`（投递时求值、指向发送窗口）——置 null 不是断链防御。

## 运行

```bash
cd "$AGENT_DIR/scripts/probe-opener-recovery"
npm install            # puppeteer-core；node_modules 已 gitignore
CHROME_PATH="/path/to/chrome-for-testing" node probe_opener_recovery.js
```

已验证版本: Chrome for Testing 146.0.7680.153 / 148.0.7778.97 / 153.0.8010.36（mac arm64）。

关联知识: `$AGENT_DIR/knowledge-base/race-conditions.md` §4（与本目录互补: `probe-message-lifecycle` 验证源文档销毁侧 `e.source === null`，本探针验证发送方存活侧引用恢复）。
