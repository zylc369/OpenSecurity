# 分析-apbq-rsa-iv（题目 apbq-rsa-iv）

> 来源：SekaiCTF 2026
> 平台：<https://ctf.sekai.team/challenges?challenge=crypto_apbq-rsa-iv>

## 题目元信息

| 字段 | 值 |
|------|-----|
| 标题 | apbq-rsa-iv |
| 分类 | Cryptography |
| 作者 | Neobeo |
| 分值 | 500（截取时 0 解） |
| 解题数 | 0 |
| Flag 格式 | `SEKAI{[\x20-\x7e]+}` |

## 题目描述（官网原文）

**Description：**
> Final boss of the apbq-rsa series.

## 附件（仅下载，未解压未分析）

```
Attachments/apbq-rsa-iv/
└── crypto_apbq-rsa-iv.tar.gz   # 1.8 KB，原始压缩包，未解压
```

## 提交入口（页面可见）

- **Flag 提交**：页面提供输入框（填 `SEKAI{...}`）+ Submit，受 hCaptcha 保护。
- 本题无 admin bot、无 Connection 靶机。

## 解题要求

> 沿用本比赛既定要求。

- **允许白盒**：题目提供源码附件 `crypto_apbq-rsa-iv.tar.gz`，解题阶段可解压分析。
- **不得作弊**：禁止查阅该题的现成 writeup / exploit；可查阅通用文档。
- **自动提交验证**：用户不手动验证，解题方案须自带提交 flag 并验证"正确/错误"的闭环（flag 提交受 hCaptcha）。

## 登录与凭证

- **登录方式**：访问 <https://ctf.sekai.team/login>，输入 team token 登录。
- **凭证位置**：`.privacy-data/sekai_ctf/team_token`（被 `.gitignore` 的 `/.privacy-data` 忽略，不进 git）。
