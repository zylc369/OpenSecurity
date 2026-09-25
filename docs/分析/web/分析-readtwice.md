# 分析-readtwice

要求：做出这道题。

> 提醒：
> 1. 知识库和记忆库沉淀了历史知识、经验，提示词对它们也有相关的描述，我建议你可以用它们试试。仅做提醒非强制，你可以自行判断用 知识库和记忆库 还是用 你自身的知识。
> 2. 优先动态分析，你用静态分析最终还要动态验证，那么直接用动态。

## 题目内容

### 题面（PwnSec CTF 2026）

| 项 | 值 |
|---|---|
| 比赛 | PwnSec CTF 2026（Jeopardy；2026-09-12 14:00 ～ 09-13 14:00 UTC） |
| 题目 | **readtwice**（#008；Web） |
| 分值 | 280 分 / 12 solves |
| 作者 | @Macabely |
| 题目页 | `https://pwnsec.ctf.ae/app/challenges/readtwice` |
| 描述（原文） | `This is not a revenge its a bookmark` |
| 关联题 | readonce（#006，139 分 / 61 solves）、readonce-revenge（#007，242 分 / 16 solves）；同作者 |
| flag 格式 | `pwnsec{...}` |
| 远程实例 | 比赛期间多次部署（`*.chal.ctf.ae`），赛终销毁；记录到的一版 `https://4aef1c8ea8230889.chal.ctf.ae` |

### 附件

`readtwice.zip`（密码 `infected`；同目录 `Attachments/readtwice/` 已存档）。解压共 15 个文件：

```
src/server.js           # Express：全部路由与状态机
src/views/*.ejs         # 页面模板（index / note / message / review + partials）
bot/bot.js              # 自动审查机器人（管理员会话 + 检查器 inspectDocument）
public/style.css
Dockerfile              # node:22-bookworm-slim + chromium（PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium）
docker-compose.yml      # 端口映射（3001:3000）与环境变量（PORT / APP_URL / FLAG / BOT_TOKEN / SESSION_SECRET）
src/package*.json  bot/package*.json   # 依赖清单与锁文件
```

### 目标与关键约束

- **目标**：让机器人的审查流程在第二次访问审查页时全部条件成立，使笔记脚本在挑战域以管理员身份执行，读取 `/api/flag` 并外带。
- 笔记 HTML 上限 **512 字符**（`/create` 路由的 `slice(0, 512)`）。
- 笔记入库前经**检查器**：无头 Chromium、**关闭 JavaScript、断网**，`page.setContent` 渲染后按 DOM 结构判定；不通过返回 400。
- 机器人持有管理员会话，固定流程：审查页（第一次）→ `/api/flag` → 就绪接口 → 访问提交的网址并停留 **10 秒**。
- 审查页**第二次访问且通过全部检查**（含 `Sec-Fetch-Site: none`、批准、`finalized` 等）才会输出笔记原文。

> 数据说明：描述原文、附件与实例信息取自竞赛平台页面与任务执行记录（逐字）；远程实例已随比赛结束销毁，无法二次核对。
