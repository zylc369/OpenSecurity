# 需求：sourcing-guide §3 覆盖度判断联动加强

> 创建: 2026-07-02
> 状态: ✅ 已完成（Phase 2-6 全通过，2026-07-02）
> 来源: 批次1（2026-07-02-gap-definition-clarity.md）§5 声明的联动后续
> 前置: 2026-07-02-gap-definition-clarity.md

## §1 背景与目标

**痛点**: 批次1 修复 evolve prompt 的 gap 两维定义时，发现 `knowledge-sourcing-guide.md` §3「价值判断」流程也有相同的"靠索引快判"风险：
- 现第2步「对照索引表」+ 第3步「有→跳过」隐含靠索引/grep 判定覆盖度
- 会漏掉"已有方向里覆盖不全/不准"的高价值素材（同 evolve prompt 旧版漏技术点级 gap 的病根）
- 若不联动修，evolve 用 sourcing-guide 选素材时仍会退回 grep 快判，与批次1 的 gap 定义口径不一致

**目标**: §3 判断流程明确"读对应知识库实际内容确认覆盖度（有无/准确/完整）"，与 evolve prompt 的 gap 两维定义一致。

## §2 技术方案

### 改动性质
- 修改 `security-analysis-evolve/knowledge-base/knowledge-sourcing-guide.md` §3 判断流程（1 处）
- 无新增文件、无脚本、无架构变更
- 风险：低（evolve agent 知识库文档修改）

### 改动点（§3 判断流程 L76-83）

当前：
```
1. 读文章标题/摘要/目录（webfetch 快速浏览，不保存）
2. 问: "知识库中有没有这个技术？"
   - 对照对应方向的 agent 知识库索引表
3. 有 → 跳过（除非文章提供了新角度或更完整的 payload）
4. 没有 → 高价值，下载
```

改为：
```
1. 读文章标题/摘要/目录（webfetch 快速浏览，不保存）
2. 问: "知识库中有没有这个技术？覆盖得准不准、全不全？"
   - 不能只看索引表或靠 grep 关键词判定（与 evolve Phase 0 的 gap 两维定义一致）
   - 必须读对应方向知识库的实际内容，确认：有无 / 准确 / 完整
3. 已覆盖且准确完整 → 跳过
4. 没有，或 有但不准/不全/提供了新角度或更完整 payload → 高价值，下载
```

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 改 §3 判断流程**
- 文件: `security-analysis-evolve/knowledge-base/knowledge-sourcing-guide.md`
- 预估: 改 1 段（4行→6行），净增 ~2 行（≤200）
- 验证点: Edit 成功；grep 确认"不能只看索引表或靠 grep"在；与 evolve prompt L254-256 口径一致
- 依赖: 无

**步骤 2. 自检（规则11 + writing-guide）**
- 验证点: 流程可操作（有明确动作：读内容）；与 evolve prompt gap 定义无矛盾

## §4 验收标准

### 功能验收
- [ ] §3 第2步明确"不能只看索引表/靠 grep，必须读实际内容确认有无/准确/完整"
- [ ] 第3-4步区分"已覆盖且准确完整→跳过" vs "不准/不全/新角度→下载"

### 一致性验收
- [ ] 与 evolve prompt 入口C 指引（L254-256 两维定义 + 禁止靠 grep）口径一致

### 架构验收
- [ ] 仅改 sourcing-guide 一个文件，不涉及其他

## §5 与现有需求文档的关系
- **批次1 的联动收尾**: 2026-07-02-gap-definition-clarity.md §5 声明"留待后续"，本文档完成该声明
- 至此 gap 两维定义在 evolve prompt（识别 gap）+ sourcing-guide（选素材）两处口径统一
