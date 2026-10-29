# 进度: 2026-09-26-source-registry（信源注册表双层架构与调用即自进化）

> 需求: .opencode/requirements/evolve/2026-09-26-source-registry.md

## 状态: 已完成（审计通过: 2 轮修复 + 纯审计轮零问题）

### Phase 进度
- [x] Phase 0-1: 复盘与方案讨论（四轮迭代: 断链发现→生命周期→末位淘汰无状态化→双层+调用即进化; 用户逐轮否决拍脑袋设计）
- [x] Phase 2: 需求文档（§3.1 六步）
- [x] Phase 3: 审计需求（§3.1 每步 ≤200 行、验证点可执行、依赖顺序 1→2→3→4 / 5 并行 / 6 收尾——通过）
- [x] Phase 4: 执行计划确认（涉及 6 文件，架构影响: knowledge-scout/ 新增 data/ 层）
- [x] Phase 4.5: scout prompt 76 行 + 增量 < 450——跳过瘦身

### 步骤进度
- [x] 步骤 1: curated 注册表（16 源 + 2 聚集体: ctftime.org AG + d.hatena.ne.jp AG）
- [x] 步骤 2: 6 候选巡检分流——curated +2（alpacahack S1、shazzer O）; staging 4（cybersecurityelite pending 活跃但同题存疑 / zenn.dev AG 候选 / pepsipu 停更待 gap 对照 / ankursundara rejected 否决留档: 停更 2 年+已归档）
- [x] 步骤 3: sourcing-guide §1 重写（注册表机制+CTF Base API 细节保留）+ 新增 §1a 调用即自进化 / §1b 无状态末位判据 / §1c 审核转正
- [x] 步骤 4: scout prompt 三处（铁律第二例外 / 工作流程第 6 步 / 报告骨架信源维护行）
- [x] 步骤 5: distillation-methodology 阶段 1a 引用提取与计数（脚本运行时自动从 guide 提取权威正则，零双维护）+ 暂存文档标注已并入
- [x] 步骤 6: 回归 + 审计

### 审计记录
- 第 1 轮修复 3 处: $AGENT_DIR_DATA 幽灵变量→显式路径; 正则双处维护→脚本自动提取 guide 权威版（实测可跑）; staging status 枚举未写明
- 第 2 轮修复 3 处: 文档头描述旧 / §0a 表缺信源维护行（与 prompt 骨架对齐）/ 入表门槛只写 S1（补 S2/AG）
- 纯审计轮: 验收 4 条全过 / 一致性 ✓ / 正则单一权威 ✓ / 白名单未动 ✓ / architecture-map 含 data/ 节点 ✓

## 决策记录
- launchd 定时方案被用户否决（太重）→ 收敛为"调用即进化"（scout 出勤寄生四动作）
- 跨轮计数判据（连续 N 轮）被用户识破为伪指标 → 无状态当次判据（末位淘汰）
- directions+note 合并为 profile 自然语言（用户原则: 机器判定用固定字段，指导行为用自然语言）
- 双层数据（curated/staging + review 转正）由用户提出，解决 scout 零写入矛盾与自更新风险隔离
- 巡逻执行者选 evolve 不选 scout（表变更是知识资产变更，收口唯一大脑）; 日常数据呼吸归 scout（bash 例外）
- cybersecurityelite 活跃但与已蒸馏素材同题、营销文掺杂 → 不直入 curated，pending 待独立产出验证

## 下轮触发点
- 首次 /knowledge-search 出勤即自进化四动作的实战验证
- staging 首次审核转正（用户在 evolve 会话触发）
- zenn.dev AG 候选的定向产出密度探测

