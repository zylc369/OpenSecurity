# 分析-ppp（题目 ppp，id pwn_ppp）

> 来源：SekaiCTF 2026 · 平台 https://ctf.sekai.team （公开可访问，无需登录）

## 题目元信息

| 字段 | 值 |
|------|------|
| 标题 | ppp |
| 标识（id） | `pwn_ppp` |
| 分类 | pwn |
| 作者 | Marc |
| 分值 | 50 |
| 解题数 | 212 |
| Flag 格式 | `SEKAI{[\x20-\x7e]+}` |

> 分值与解题数为比赛进行中的实时值（页面 API 抓取于 2026-06-28），比赛结束后可能变化，此处仅作快照。

> Flag 格式照录自页面 Sanity Check 题描述原文，未作注解。

## 题目描述（官网原文）

```
*insert your typical "you might need a 0day for this" description*

> [!NOTE]
> This is a 0day challenge and we are hoping you keep th{is|ese} 0day{|s} to yourself until the vulnerabilit{y|ies} {is|are} patched.

> [!CONNECTION]
> nc ppp.chals.sekai.team 1337
```

## 连接信息

- `nc ppp.chals.sekai.team 1337`

## 附件（仅下载，未解压未分析）

| 文件 | 位置 | 大小 |
|------|------|------|
| `pwn_ppp.tar.gz` | `docs/分析/二进制安全/Attachments/ppp/pwn_ppp.tar.gz` | 868037 字节 |

原始下载地址（页面所给）：
`https://sekaictf-2026-files.storage.googleapis.com/uploads/6b1b34827cff01538866cece9100bbbcad4c887127c0460a945ff43a69b9c384/pwn_ppp.tar.gz`

文件头校验为 gzip（`1F 8B`），未解压、未读取内部内容。

## 提交入口

页面题目处的 Flag 提交框。

## 解题要求

用户本次未指定（白盒/黑盒、是否禁 writeup、是否自动提交等均未指定）。
