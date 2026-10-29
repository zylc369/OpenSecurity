---
description: 知识搜索 — 从 writeup 信源扫描侦察: gap 对照、价值评估、素材下载、侦察报告（含建议沉淀清单）。任何 agent 的分析中需要外部 writeup 情报时使用; 沉淀与蒸馏走 security-analysis-evolve。
---

## 角色与目标

触发知识侦察（派发 knowledge-scout 子 agent 执行）。

**本命令是薄触发器**：只做输入解析 → 派发 → 原样呈现报告三件事。侦察方法论（信源表、gap 判定、价值判断、报告格式）唯一权威在 knowledge-scout 的 `$AGENT_DIR/knowledge-base/knowledge-sourcing-guide.md`，此处禁止重复。

## 输入解析（$ARGUMENTS）

| $ARGUMENTS 值 | 行为 |
|---------------|------|
| 空字符串 | **默认全方向**: 六方向（binary/mobile/web/crypto/ai-security/forensics）各派发一个独立 scout 子任务，全部完成后汇总总表呈现 |
| `all` | 同上（显式写法） |
| 方向名（上述六者之一） | 限定该方向做 gap 对照 |
| 信源 URL | 直接从该信源页扫描 |
| 其他文本 | 原样作为搜索主题。不限六方向——OSINT、域渗透、云安全、工控等任何安全主题 |

$ARGUMENTS

## 执行: 派发

用 task 工具派发，`subagent_type: "knowledge-scout"`（显式指定——该 agent 为 hidden，不依赖描述路由），每个方向/主题一个独立子任务，prompt 模板:

```
任务: 知识侦察。

输入: <输入>
时间范围: 最近 90 天（信源页无日期的条目保守跳过）; 委派方另有指定则从之。

要求:
1. 方法论（信源表/gap 判定/价值判断/下载方法/报告格式）唯一权威:
   $AGENT_DIR/knowledge-base/knowledge-sourcing-guide.md
2. 只侦察不沉淀: 不写知识库、不改任何 agent prompt; 值得沉淀的内容列入报告"建议沉淀清单"
3. 素材是一个完整库（Git 仓库/题目集）时不要整库处理——报告说明并建议转 security-analysis-evolve 走整库蒸馏

回传报告: 按 sourcing-guide §0a 报告格式逐节输出。
```

## 收到报告后

- 单方向/主题: **原样呈现**侦察报告，不做二次加工、不自行追加分析。
- 全方向: 汇总各方向为总表（每方向一行: 候选数/建议沉淀数/遗留数），下方附建议沉淀清单与遗留合并。

## 约束

- 禁止在当前会话直接执行侦察（收口在 scout）
- 禁止根据报告直接沉淀——沉淀是 security-analysis-evolve 的职责（把素材路径与建议清单交它处理）
- 派发 prompt 中的路径保持 `$AGENT_DIR` 变量形式（scout 会话中正确指向其专属目录）
