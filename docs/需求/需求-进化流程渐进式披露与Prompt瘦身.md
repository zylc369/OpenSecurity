# 需求：进化流程渐进式披露 + Prompt 瘦身

## 1. 背景与目标

### 1.1 背景

`ida-pro-analysis.md` 经过两轮进化（壳检测、静态分析脱壳），从 496 行增长到 622 行（+26%）。每次进化约增加 120 行。按此趋势，3-4 轮进化后将超过 1000 行，导致：
- AI 注意力稀释，关键规则被淹没在细节中
- 每次调用都要加载完整 prompt，浪费上下文窗口
- 进化成本越来越高（每次都要检查 1000+ 行的兼容性）

### 1.2 目标

1. **进化命令增加瘦身机制**：在 `security-analysis-evolve.md` 中增加"Prompt 瘦身检查"环节，自动检测并提取可外置的内容
2. **对当前 prompt 执行首次瘦身**：将加壳策略（~124 行）和脚本生成规则（~70 行）提取到知识库文件

### 1.3 评估维度

| 维度 | 改进 |
|------|------|
| 减少上下文 | 主 prompt 622 → ~430 行，减少 31% |
| 减少对话轮次 | 不变 |
| 提升分析速度 | prompt 更精简，AI 解析更快 |
| 提升准确度 | 按需加载减少注意力稀释 |

---

## 2. 技术方案

### 2.1 架构变更

```
.opencode/commands/
├── ida-pro-analysis.md                 # 命令 prompt（AI 编排器，目标 < 450 行）
└── ida-pro-analysis-scripts/           # 工具脚本
    ├── _base.py                        # 层 1
    ├── _utils.py                       # 层 2
    ├── query.py                        # 层 3
    ├── update.py                       # 层 3
    ├── scripts/                        # 沉淀脚本库
    │   └── registry.json
    ├── ida-pro-analysis-knowledge-base/ # 🆕 知识库（按需加载）
    │   ├── packer-handling.md          #   加壳处理策略（完整流程）
    │   └── script-generation.md        #   脚本生成与沉淀规则
    └── README.md
```

### 2.2 渐进式披露规则

**阈值**：
- 软阈值 450 行：超过时，Phase 4.5 自动分析可提取内容
- 硬阈值 600 行：超过时，**必须**先瘦身再添加新内容

**提取原则**：
1. **仅提取"特定场景才需要"的内容**：每次调用都需要的内容留在主 prompt
2. **主 prompt 保留核心规则**：触发条件 + 禁止操作 + 一行引用说明（3-10 行）
3. **引用使用相对路径**：`$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/<文件名>`（可移植）
4. **知识库文件自包含**：每个文件可独立理解，不依赖主 prompt 的上下文

**引用格式**（主 prompt 中的写法）：
```markdown
### 加壳/混淆二进制处理策略

触发条件: `packer_detect` 返回 `packer_detected: true`。

检测到加壳时，使用 Read 工具读取 `$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/packer-handling.md` 获取完整处理流程。

**关键规则**（无论是否读取详细策略都必须遵守）：
- 禁止: `functions`/`func_info`/`strings`/`xrefs_*`/`update.py`
- 允许: `decompile`/`disassemble`/`read_data`/`segments`（仅用于分析解壳 stub）
```

### 2.3 首次瘦身内容

| 提取内容 | 当前行数 | 目标文件 | 主 prompt 保留 |
|---------|---------|---------|--------------|
| 加壳/混淆处理策略（完整三阶段流程 + 模式参考表 + 脱壳机模板） | ~124 行 | `packer-handling.md` | 触发条件 + 禁止规则（~10 行） |
| 脚本生成与沉淀规则（骨架模板 + 编码规则表 + 质量保障） | ~70 行 | `script-generation.md` | 一行引用说明（~3 行） |

### 2.4 evolve 命令变更

在 `security-analysis-evolve.md` 中：

1. **更新架构图**：增加 `ida-pro-analysis-knowledge-base/` 目录
2. **在 Phase 4 和 Phase 5 之间插入 Phase 4.5**：Prompt 瘦身检查
3. **增加反模式**：不在主 prompt 中保留可提取的详细流程

---

## 3. 实现规格

### 3.1 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `security-analysis-evolve.md` | 修改 | 增加架构图 + Phase 4.5 + 反模式 |
| `ida-pro-analysis.md` | 修改 | 替换加壳策略和脚本生成章节为引用 |
| `ida-pro-analysis-knowledge-base/packer-handling.md` | 新建 | 从主 prompt 提取的加壳处理策略 |
| `ida-pro-analysis-knowledge-base/script-generation.md` | 新建 | 从主 prompt 提取的脚本生成规则 |

### 3.2 执行顺序

1. 先更新 `security-analysis-evolve.md`（增加瘦身机制）
2. 创建知识库目录和文件
3. 瘦身 `ida-pro-analysis.md`

---

## 4. 验收标准

### 4.1 功能验收

- [ ] `security-analysis-evolve.md` 包含 Phase 4.5 瘦身检查环节
- [ ] `security-analysis-evolve.md` 架构图包含知识库目录
- [ ] `ida-pro-analysis.md` 行数 < 450 行
- [ ] `packer-handling.md` 包含完整的三阶段流程、常见模式表、脱壳机模板
- [ ] `script-generation.md` 包含骨架模板、编码规则表、质量保障清单
- [ ] 主 prompt 中的引用使用相对路径 `$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/<文件名>`

### 4.2 回归验收

- [ ] 主 prompt 中仍包含加壳策略的触发条件和核心禁止规则
- [ ] 主 prompt 中仍包含脚本生成的引用说明（AI 知道去哪里找规则）
- [ ] 知识库文件自包含，可独立理解

### 4.3 架构验收

- [ ] 知识库目录位于 `$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/`（与脚本同层）
- [ ] 引用使用相对路径，不使用绝对路径

---

## 5. 与现有文档的关系

| 现有文档 | 关系 |
|---------|------|
| [需求-加壳检测与异常分析增强](需求-加壳检测与异常分析增强.md) | 其产出的加壳策略内容被提取到 `packer-handling.md` |
| [需求-加壳二进制静态分析脱壳流程](需求-加壳二进制静态分析脱壳流程.md) | 其产出的脱壳流程被提取到 `packer-handling.md` |
