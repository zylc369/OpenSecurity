# 分析-oneline6ryp7o（题目 oneline6ryp7o）

> 来源：SekaiCTF 2026
> 平台：<https://ctf.sekai.team/challenges?challenge=crypto_oneline6ryp7o>

## 题目元信息

| 字段 | 值 |
|------|-----|
| 标题 | oneline6ryp7o |
| 分类 | Cryptography |
| 作者 | Neobeo |
| 难度 | EASY |
| 分值 | 50（动态评分 decay，截取时 241 解） |
| 解题数 | 241 |
| 标签 | ⭐、67 |
| Flag 格式 | `SEKAI{[\x20-\x7e]+}`（提交框 placeholder） |

## 题目描述（官网原文）

> how hard can six seven be

```
assert __import__('re').match('SEKAI{[67]{67}}$',flag:=input()) and not int.from_bytes(flag.encode())%~(6+~7)**67
```

## 连接信息

- 无靶机、无 admin bot、无连接地址。

## 附件（仅下载，未解压未分析）

- 无附件（整题内容即上方描述）。

## 提交入口（页面可见）

- **Flag 提交**：详情面板提供输入框（placeholder 为 `SEKAI{[\x20-\x7e]+}`）。
- 本题无 admin bot、无 Connection 靶机。

## 解题要求

> 沿用本比赛既定要求。

- **允许白盒**：整题内容即描述中的 Python 断言，解题阶段可对其分析。
- **不得作弊**：禁止查阅该题的现成 writeup / exploit；可查阅通用文档。
- **自动提交验证**：用户不手动验证，解题方案须自带提交 flag 并验证"正确/错误"的闭环。

## 登录与凭证

- **登录方式**：访问 <https://ctf.sekai.team/login>，输入 team token 登录。
- **凭证位置**：`.privacy-data/sekai_ctf/team_token`（被 `.gitignore` 的 `/.privacy-data` 忽略，不进 git）。
