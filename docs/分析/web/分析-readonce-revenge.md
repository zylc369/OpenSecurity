# 分析-readonce-revenge

要求：做出这道题。

> 提醒：
> 1. 知识库和记忆库沉淀了历史知识、经验，提示词对它们也有相关的描述，我建议你可以用它们试试。仅做提醒非强制，你可以自行判断用 知识库和记忆库 还是用 你自身的知识。
> 2. 优先动态分析，你用静态分析最终还要动态验证，那么直接用动态。

## 题目内容

### 题面（PwnSec CTF 2026）

| 项 | 值 |
|---|---|
| 比赛 | PwnSec CTF 2026（Jeopardy；2026-09-12 14:00 ～ 09-13 14:00 UTC） |
| 题目 | **readonce-revenge**（#007；Web / Hard） |
| 分值 | 251 分 / 15 solves（初）→ 242 分 / 16 solves（终）；动态分值 |
| 作者 | @Macabely（First blood：JordanSec） |
| 题目页 | `https://pwnsec.ctf.ae/app/challenges/readonce-revenge` |
| 描述（原文） | `this is really a revenge :)` |
| 关联题 | readonce（#006，139 分 / 61 solves）、readtwice（#008，280 分 / 12 solves） |
| flag 格式 | `pwnsec{...}` |
| 远程实例 | 比赛期间多次部署（`*.chal.ctf.ae`），赛终销毁；最后一版 `https://eb2735d8a9a959a2.chal.ctf.ae` |

### 附件

`readonce-revenge.zip`（密码 `infected`；同目录 `Attachments/readonce-revenge/` 已存档）。解压共 17 个文件：

```
src/server.js           # Express：全部路由与状态
src/views/*.ejs         # 8 个页面模板（index / note / message / review / review-document / sandbox + partials）
bot/bot.js              # 自动审查机器人（管理员会话 + 固定时序）
public/style.css
Dockerfile              # Node 22 + Chromium
docker-compose.yml      # 端口映射与环境变量（APP_URL / FLAG）
src/package*.json  bot/package*.json   # 依赖清单与锁文件
```

### 目标与关键约束

- **目标**：让机器人在挑战域页面执行自己笔记里的 XSS，以管理员身份读取 `/api/flag` 并外带。
- 笔记 HTML 上限 **128 字符**（`/create` 路由的 `slice(0, 128)`）。
- 机器人持有管理员会话，固定流程：审查页 → `/api/flag` → 就绪接口 → 访问提交的网址并停留 10 秒。
- 审查页**第二次访问且通过全部检查**才会进入"渲染笔记原文"分支（无 CSP，XSS 落点）。

> 数据说明：描述原文取自分析时的平台页面记录（逐字，英文）；页面快照在描述处被截断、无法二次核对，未发现中文版题面。