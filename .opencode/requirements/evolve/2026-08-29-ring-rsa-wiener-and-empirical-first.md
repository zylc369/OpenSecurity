# 需求：环 RSA 广义 Wiener 沉淀 + 实证优先/自测先行纪律固化

> 日期：2026-08-29 ｜ 来源：hello (apbq-rsa-iv) 破题会话复盘 ｜ 状态：已实施（2026-08-29，审计通过）

## §1 背景与目标

**来源痛点**（hello 会话实测数据）：

| 痛点 | 数据 |
|------|------|
| P1 一个完整回合被纯理论推演耗尽，零可执行动作产出，用户被迫干预 | 该回合 0 工具调用 |
| P2 环 RSA（`Z_N[x]/(x^n-r)`）知识库零覆盖（grep 全库验证），攻击理论全程从零推导 | ~30min 推演 |
| P3 λ≠(p^n-1)(q^n-1) 解密陷阱无任何来源覆盖，naive 解密 ~30% 出乱码 | 自测 20 种子实测 6 败 |
| P4 `set_int_max_str_digits` 踩坑 1 次 | fetch 首跑失败 |

**目标**：
1. 环 RSA 广义 Wiener 打法（识别/攻击/验证/升级阶梯/λ 陷阱）沉淀进 `rsa-attacks.md`，三处路由表各补一行
2. "廉价实验优先"与"生成器自测先行"固化为纪律（共享片段 1 行 + crypto methodology 细则）
3. `set_int_max_str_digits` 一行沉淀

## §2 技术方案

| # | 文件 | 改动 | 内容 |
|---|------|------|------|
| 1 | `crypto-analysis/knowledge-base/rsa-attacks.md` | 新增 §4a（§4 之后 §5 之前） | 环 RSA 广义 Wiener 全打法：指纹、原理、validate_kd 代码、λ 陷阱+CRT 解密代码、升级阶梯（收敛子→半收敛子→网格→BD）、失败原因表 |
| 2 | 同上 | §1 体检表 +1 行；决策树 +1 行 | "密文是多项式 + e ≈ N^n → §4a" |
| 3 | `agents/crypto-analysis.md` | 阶段 A 路由表 +1 行 | 同上症状 → `rsa-attacks.md §4a` |
| 4 | `crypto-analysis/knowledge-base/crypto-methodology.md` | §2 流程后 +执行纪律小节；§4 +int 上限提示 | 廉价实验优先（细则）+ 生成器自测先行（细则）；`sys.set_int_max_str_digits` |
| 5 | `agents-rules/execution-discipline.md` | 纪律表 +1 行 | 廉价实验优先（通用版，一行） |

**内容分工（防重复）**：通用纪律一行进共享片段；crypto 场景细则（含 nc 新实例风险）进 methodology；环 RSA 专属升级阶梯只存在于 §4a，methodology/路由表只指向不展开。

## §3 实现规范

- 遵守 `knowledge-writing-guide.md`：写场景/检查/利用；不写经验来源、不引用题目名/记忆库 id；代码可执行（sage 语法标注）；跨文件引用用 `$AGENT_DIR`
- 所有新增代码片段必须通过语法编译检查（`compile()`）
- 术语与现库一致：连分数/收敛子/半收敛子/判别式/商环
- 不引入 GUI 操作描述；不引用 docs/ 目录

### §3.1 实施步骤

```
步骤 1. rsa-attacks.md 新增 §4a（~65 行，含 2 个 sage 代码块）
  - 验证点: 提取两个代码块分别 compile() 通过；人工读自包含性（不知道原题也能用）
步骤 2. rsa-attacks.md §1 体检表 +1 行 + 决策树 +1 行（依赖 步骤 1）
  - 验证点: grep 确认两处 §4a 引用存在且表格列数对齐
步骤 3. crypto-analysis.md 阶段 A 路由表 +1 行（依赖 步骤 1）
  - 验证点: wc -l = 141 < 450；表格格式与相邻行一致
步骤 4. crypto-methodology.md §2 +执行纪律、§4 +int 上限（独立）
  - 验证点: compile() 代码块通过；与 §7 注意无重复（§7 讲"验证明文"，本节讲"执行顺序"）
步骤 5. execution-discipline.md 纪律表 +1 行（独立，高风险共享片段）
  - 验证点: 表格 3 列格式对齐；一行内表述自包含；与"持续推进"行不冲突而是互补
```

## §4 验收标准

**功能验收**：
- [ ] 新读者（AI）仅凭 §4a 可完成环 RSA 题攻击+解密，无需原题上下文
- [ ] λ 陷阱醒目且给出可执行解法代码
- [ ] 升级阶梯 4 级各有触发条件
- [ ] 3 个路由入口（agent prompt 阶段 A、rsa-attacks §1、决策树）都能路由到 §4a
**回归验收**：
- [ ] rsa-attacks.md 原有 §1-§13 内容零改动（除 §1 表和决策树的增量行）
- [ ] crypto-methodology.md 原有章节零删改
- [ ] execution-discipline.md 既有行零改动
**架构验收**：
- [ ] 无新文件（全部追加到现有文件，符合"不确定时先放现有文件"）
- [ ] 依赖方向无变化（纯知识库+prompt 文档改动）
- [ ] crypto-analysis.md 展开后 < 450 行

## §5 与现有需求文档的关系

无重叠。最近的 `2026-08-28-ctf-toolbox-coverage.md` 讲工具覆盖，本需求讲知识/纪律沉淀，互不影响。
