---
description: 知识蒸馏 — 对整库/离线知识库（Git 仓库、题目集、内部文档库）全量精读、gap 判定、验证分级、沉淀到知识库。薄触发器：解析输入后派发给 security-analysis-evolve agent 执行
---

## 角色与目标

触发"整库蒸馏"流程（evolve agent 的深度蒸馏入口，与 `/evolve-from-writeups` 的散篇扫描互补: 那个追新宽度，本命令整库榨干深度）。

**本命令是薄触发器**：只做输入解析 → 派发 → 呈现报告三件事。蒸馏方法论（六阶段流程、Tier 验证分级、回归清单、独立复审）唯一权威是 `$AGENT_DIR/knowledge-base/distillation-methodology.md`，此处禁止重复。

## 输入解析（$ARGUMENTS）

| $ARGUMENTS 值 | 行为 |
|---------------|------|
| Git 仓库 URL（github.com/.../repo 或含 `/tree/<ref>/<子目录>` 的链接） | 克隆到临时区 → 全量蒸馏; `/tree` 子目录链接以该子目录为盘点范围 |
| GitHub 单篇文件 URL（含 `/blob/`） | 提示用户: 散篇场景走 `/evolve-from-writeups`，不进入整库流程 |
| 本地路径 | 直接盘点该目录 → 全量蒸馏 |
| `--focus <方向>` 附加参数（可在主参数前或后，解析时先剥离再取主参数） | 限定蒸馏该方向（`binary`/`mobile`/`web`/`crypto`/`ai-security`/`forensics` 之一），其余方向只盘点跳过 |
| 空字符串（用户调用 `/knowledge-distill` 未带参数） | 报错提示: 整库蒸馏必须指定 Git URL 或本地路径（无默认对象，与 `/evolve-from-writeups` 的默认 all 不同） |
| 其他文本（非 URL 非路径，如散篇主题词） | 报错提示: 整库蒸馏需指定 Git 仓库 URL 或本地路径; 散篇/主题场景走 `/evolve-from-writeups` |

$ARGUMENTS

## 执行：派发

用 task 工具派发给 `security-analysis-evolve` agent，派发 prompt 用下方模板（替换 `<输入>` 与 `<focus>` 为解析后的值，无 focus 则删除该行）:

```
任务: 整库知识蒸馏（你的 Phase 0 入口 C 的仓库/离线库形态，走完整六阶段流程）。

输入: <输入>
方向限定: <focus>

执行要求:
1. 六阶段流程、Tier 验证分级、回归检查清单、独立复审的唯一权威是
   $AGENT_DIR/knowledge-base/distillation-methodology.md，逐阶段执行，禁止跳过
2. 素材获取若为 Git 仓库: 克隆到临时区（--depth 1; LFS 仓库先 GIT_LFS_SKIP_SMUDGE=1），
   本地路径则直接盘点; 盘点计数必须交叉验证后才可进入精读
3. gap 判定逐篇两维执行，禁止只看索引或 grep 关键词判"已覆盖"
4. 写入前必须读 $SHARED_DIR/knowledge-base/knowledge-writing-guide.md 并全部遵守
5. 写入本身走完整进化流程: 需求文档（含 §3.1 分步）+ progress 到
   $OPENCODE_ROOT/requirements/evolve/
6. 流程末尾按方法论阶段六**直接派发独立复审子任务**（不询问用户），findings 全部修复后回归
7. 源素材全量归档到 docs/资料/writeup-sources/<来源名>/（产出原始资料属例外）

回传报告格式: 严格遵守方法论 §7 完成报告要素清单，逐项不得缺漏
```

## 收到报告后

向用户**原样呈现**蒸馏报告，不做二次加工、不自行追加分析。

## 约束

- 禁止在当前会话直接执行蒸馏流程（专业流程收口在 evolve agent）
- 散篇信源/单篇 writeup 一律走 `/evolve-from-writeups`（互引）
- 派发 prompt 中的路径引用保持 `$AGENT_DIR`/`$SHARED_DIR`/`$OPENCODE_ROOT` 变量形式（evolve agent 系统提示中有定义，保证可移植）
