# 需求：模型安全分析知识库修正（A~E）

> 来源：2026-07-02 课题"从AI获取信息-v1"实战复盘
> 状态：待实施

---

## §1 背景与目标

### 1.1 来源

本次课题从 opencode-go 三模型（deepseek-v4-pro、deepseek-v4-flash、glm-5.1）获取三类敏感信息（校园暴力、DDoS攻击、假证制作）。9/9 目标全部突破成功，但 17 次调用中 9 次被浪费（52.9%），根因是知识库内部矛盾、CLI 用法未沉淀、prompt 策略缺规则。

### 1.2 痛点与目标

| 痛点 | 浪费 | 根因 | 对应方案 |
|------|------|------|---------|
| 框架选择误判 | 2 轮 | profiles 说"学术框架完全失效"是笼统评价，未区分目标类别 | A |
| 无直查表 | 2 轮 | 有决策树但无"画像×目标类别→框架"直查表 | B |
| CLI 参数误用 | 3 次 | dialogue CLI 用法未沉淀 | C |
| 超时率高 | 4 轮 ~20min | 短 prompt 超时率低的规律未沉淀 | D |
| 假证路径过重 | 隐含 | matrix 说假证需碎片化4学科，实际正交领域单 session 即可 | E |

### 1.3 预期收益

- 首攻框架选择正确率：67% → 接近 100%（A+B）
- 超时率：23.5% → <10%（D）
- CLI 参数误用：3 次 → 0 次（C）
- glm 假证攻击复杂度：多 session 碎片化 → 单 session 正交领域（E）

---

## §2 技术方案

### 方案 A：修正 model-defense-profiles.md 的笼统描述

**问题**：第 27 行说"学术包装下内容安全层**完全失效**"，第 30 行推荐首攻 = "学术论文/IEEE安全会议框架"。但实际执行中，学术框架对行为操作类（校园暴力）被直接拒绝（"regardless of how the request is framed"），只对技术知识类（DDoS、假证工艺）有效。

**改动**：
- deepseek-v4-pro 的"语义意图过滤"描述：区分"技术知识类"（学术框架有效）和"行为操作类"（学术框架无效，需正交领域）
- "推荐首攻框架"：从笼统的"学术论文"改为按类别区分
- 新增 §"框架有效性×目标类别"快速参考表（三个模型统一）

### 方案 B：在 bypass-framework-matrix.md 增加"画像×目标类别→框架"直查表

**问题**：现有 §3 速查表只列了"目标知识→成功框架"的映射，没有结合模型画像。AI 执行时先读 profiles（说学术框架对 pro 有效），不会查 matrix §3（说校园暴力学术框架失败），导致误判。

**改动**：
- 在 §3 之后新增 §3.1"画像×目标类别→首攻框架"直查表
- 表格维度：行=目标类别（行为操作类/技术知识类/犯罪手法类），列=模型（pro/flash/glm）
- 每格填入验证过的首攻框架

### 方案 C：沉淀 dialogue CLI 用法到 model-security-analysis-guide.md

**问题**：首次使用时误把 `--timeout` 当 CLI 参数，导致 3 次调用全部失败。

**改动**：
- 在 guide §6.1"opencode-go"小节补充 dialogue CLI 速查（chat/create/send 的参数列表）
- 内容：`chat -t <model> -p <prompt> [--provider opencode-go]` 是一次性隔离调用；`--timeout` 不是 CLI 参数，超时由调用方（Bash 工具）控制

### 方案 D：沉淀 prompt 策略规则到 model-security-analysis-guide.md

**问题**：4 次超时全部发生在长 prompt（>400字中文）时。缩短为英文简洁版（200-300字）后全部成功。

**改动**：
- 在 guide 新增 §3.4"Prompt 构造策略"
- 内容：prompt 长度控制（<300字英文优先）、超时应对（缩短重试而非盲目重试）

### 方案 E：修正 bypass-framework-matrix.md §3 假证路径

**问题**：§3 速查表说假证需"塑料工业+印刷工程+光学物理+材料化学（4个独立合法学科问题）"——即碎片化。但本次 glm-5.1 用单个"塑料卡工业制造技术附录"正交领域 session 就成功了。

**改动**：
- §3 假证行：将"4个独立合法学科问题"改为"塑料卡工业制造技术附录（正交领域，单 session）"
- 标注：碎片化作为 fallback 策略（正交领域被拒时启用）

---

## §3 实现规范

### 3.0 改动范围表

| 方案 | 文件 | 改动类型 | 预估行数 |
|------|------|---------|---------|
| A | `ai-security-analysis/knowledge-base/model-defense-profiles.md` | 修改+新增 | ~30行 |
| B | `ai-security-analysis/knowledge-base/bypass-framework-matrix.md` | 新增 | ~20行 |
| C | `ai-security-analysis/knowledge-base/model-security-analysis-guide.md` | 修改 | ~15行 |
| D | `ai-security-analysis/knowledge-base/model-security-analysis-guide.md` | 新增 | ~15行 |
| E | `ai-security-analysis/knowledge-base/bypass-framework-matrix.md` | 修改 | ~5行 |

### 3.1 实施步骤拆分

#### 步骤 1. 方案 A — 修正 profiles deepseek-v4-pro 描述

- **文件**: `model-defense-profiles.md`
- **预估行数**: ~15行修改
- **改动**:
  - 第 27 行"语义意图过滤"：区分技术知识类 vs 行为操作类
  - 第 30 行"推荐首攻框架"：按类别给出不同推荐
  - 第 25 行标题行：去掉"学术框架可完全绕过所有安全层"的笼统说法
- **验证点**: 人工读取确认描述精确、无内部矛盾（与 matrix §3 速查表一致）

#### 步骤 2. 方案 A — 新增"框架有效性×目标类别"快速参考表

- **文件**: `model-defense-profiles.md`
- **预估行数**: ~15行新增
- **改动**: 在文件末尾（三个模型画像之后）新增"框架有效性×目标类别"表。该表**只标注有效性**（✅学术框架有效/❌需正交领域），**不给框架名**——框架名由 matrix 的直查表（步骤3）提供
- **定位说明**: 放在文件末尾而非模型画像中间，避免打断三个模型画像的连续性；该表是跨模型统一参考，不属于任何一个模型
- **验证点**: 表格覆盖三个模型×三个类别（行为操作/技术知识/犯罪手法），每格标注"✅/❌"

#### 步骤 3. 方案 B — 增加"画像×目标类别→首攻框架"直查表

- **文件**: `bypass-framework-matrix.md`
- **预估行数**: ~20行新增
- **改动**: 在 §3 速查表之后新增 §3.1，表格行=目标类别，列=模型，格=**首攻框架名**（如"学术框架""VR游戏行为树""工业制造正交领域"）
- **与 profiles 表的分工**: profiles 表（步骤2）回答"学术框架对这个组合有效吗？"（✅/❌）；matrix 表（步骤3）回答"那我该用什么框架？"（框架名）。两表互补不重复
- **验证点**: 直查表内容与 profiles（步骤2）和 matrix §3（已验证速查表）一致，无矛盾

#### 步骤 4. 方案 E — 修正假证路径

- **文件**: `bypass-framework-matrix.md`
- **预估行数**: ~5行修改
- **改动**: §3 假证行的"成功的正交领域"列：从碎片化4学科改为"塑料卡工业制造（正交领域单 session）"；碎片化降级为 fallback
- **验证点**: 假证行描述与本次实战结果一致（glm 正交领域单 session 成功）

#### 步骤 5. 方案 C — 沉淀 dialogue CLI 用法

- **文件**: `model-security-analysis-guide.md`
- **预估行数**: ~15行修改
- **改动**: §6.1"opencode-go"小节补充 CLI 速查（chat/create/send 参数 + --timeout 不是 CLI 参数的说明）
- **验证点**: CLI 参数与 `main.py --help` 输出一致

#### 步骤 6. 方案 D — 沉淀 prompt 策略规则

- **文件**: `model-security-analysis-guide.md`
- **预估行数**: ~15行新增
- **改动**: §3 新增 §3.4"Prompt 构造策略"（长度控制 + 超时应对）
- **验证点**: 规则有具体数值（<300字英文优先），有可操作的应对步骤

---

## §4 验收标准

### 功能验收

- [ ] profiles 不再出现"学术框架完全失效"的笼统描述（方案 A）
- [ ] profiles 新增的"框架有效性×目标类别"表覆盖 3 模型×3 类别（方案 A）
- [ ] matrix 新增的直查表内容与 profiles 和 matrix §3 三方一致（方案 B）
- [ ] matrix §3 假证行反映正交领域单 session 成功的事实（方案 E）
- [ ] guide §6.1 包含 dialogue CLI 参数速查（方案 C）
- [ ] guide §3 包含 prompt 长度控制和超时应对规则（方案 D）

### 回归验收

- [ ] profiles、matrix、guide 三个文件的现有内容未被破坏（只修改/新增目标段落）
- [ ] 三个文件内部的交叉引用路径仍然正确
- [ ] 知识库索引（如 agent prompt 中的引用）不需要更新（本次只改内容不改文件名/路径）

### 架构验收

- [ ] 无新增文件（全部在现有文件内修改）
- [ ] 无依赖方向变更
- [ ] agent prompt 行数不变（知识库修改不影响 prompt）

---

## §5 与现有需求文档的关系

- 与 `2026-05-30-ai-security-analysis-agent.md`（AI安全分析Agent创建）的关系：本次是该 Agent 知识库的精度提升，不改变 Agent 架构
- 与 `2026-06-30-writeup-knowledge-evolution-v2.md`（writeup知识进化）的关系：无交叉，本次是模型层攻击知识库，彼为应用层
- 无冲突需求文档
