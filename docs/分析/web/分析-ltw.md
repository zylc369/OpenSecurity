# 分析-ltw（题目 `&lt;\w+`）

> 来源：SekaiCTF 2026（赛事周期 2026-06-27 16:00 → 2026-06-29 16:00 GMT+8）
> 平台：<https://ctf.sekai.team/challenges>

## 题目元信息

| 字段 | 值 |
|------|-----|
| 标题 | `&lt;\w+`（页面显示原文即此，如实记录） |
| 分类 | Web |
| 作者 | claustra01 |
| 分值 | 动态分值（截取时实测 439 分，随解题数变化；未观察 0 解初始值，不臆断） |
| 解题数 | 4 |
| Flag 格式 | `SEKAI{[\x20-\x7e]+}` |

> **命名约定**：本目录/文件用 `ltw`（取自挑战专属子域 `ltw.chals.sekai.team`）作文件系统短名，而非直接用标题 `&lt;\w+`——因标题含 `<`（Windows 禁用字符）和 `\`（Windows 路径分隔符），会令 `git clone` 在 Windows checkout 失败。真实标题以本文档内容为准。

> 标题与源码/漏洞之间是否存在关联，属解题阶段的判断，本文档不预先下结论。

## 题目描述（官网原文）

**Description：**
> HTML unescape + Regex to delete all = What can I do?

**Note：**
> This challenge does not have access to internet, use console.log to exfil :)

## 连接信息

- 靶机地址：**<https://ltw.chals.sekai.team>**
- 题目提交平台（admin bot + flag 提交）：<https://ctf.sekai.team/challenges>（需登录）

## 附件（页面可下载的题目材料，仅下载、未解压、未分析）

```
Attachments/ltw/
├── web_&lt;_w+.tar.gz   # 来自页面 "Attachments" 区（原始压缩包，未解压）
└── bot.ts            # 来自页面 Admin bot 区的 "Download config"（admin bot 配置，原始文件）
```

> 解压 `web_&lt;_w+.tar.gz`、阅读其内容、解读 bot.ts 都属解题阶段的工作，本文档不做。

## 提交入口（页面可见）

- **Admin bot**：页面提供输入框（填 note 的 UUID）+ Submit；旁边有 "Download config"（即上面的 `bot.ts`）。
- **Flag 提交**：页面提供输入框（填 `SEKAI{...}`）+ Submit。
- 两处提交均被 hCaptcha 保护（页面有 "This site is protected by hCaptcha" 提示）。

## 解题要求

### 1. 黑盒/白盒边界

- 题目官方提供可下载附件 `web_&lt;_w+.tar.gz`（未解压），**允许白盒分析**。
- 靶机 `https://ltw.chals.sekai.team` 可交互验证（注意 `/create` 有限速，自动脚本需控速）。

### 2. 不得作弊

- **禁止**搜索或查阅该题的现成 writeup / 解题脚本 / 公开 exploit。可查阅通用文档，但**不得直接套用他人针对本题的成品解**。

### 3. 自动提交验证能力（重要）

用户**不会手动验证**，解题方案必须自带端到端自动提交与验证闭环：触发 admin bot → 取回结果 → 提交 flag → 验证"正确/错误"，全程不依赖人工。

- 两处提交受 hCaptcha 保护（页面有提示），自动提交须解决 hCaptcha。

> 范围说明：本文档是题目落盘规格，**尚未编写可运行的提交脚本**（解题阶段产物）。

### 4. 产出要求

- 最终输出：一条 `SEKAI{...}` flag，并附提取该 flag 的原始证据。
- 提交验证必须在脚本内完成并报告"正确/错误"。

## 登录与凭证

- **登录方式**：访问 <https://ctf.sekai.team/login>，输入 team token 登录。
- **凭证位置**：`.privacy-data/sekai_ctf/team_token`（被 `.gitignore` 的 `/.privacy-data` 忽略，不进 git）。
- 不要把 token 写进本文档（`docs/` 进 git）。
