# 需求：writeup 知识进化能力 — 搜索/下载/提炼/沉淀

> **已废弃** — 被 `2026-06-30-writeup-knowledge-evolution-v2.md` 替代。

> 创建: 2026-06-30
> 状态: Phase 2
> 来源: 用户要求"能自己搜索 writeup、下载，并基于 writeup 沉淀知识到知识库"

## §1 背景与目标

**痛点**: 本次进化中暴露的问题：
1. AI 有"下载"能力但不知道"去哪里找"（缺乏渠道清单）
2. 批量下载了大量低价值文章（缺乏价值判断标准）
3. 只下载不提炼（缺乏标准化的提炼流程）
4. 用户指定已有 writeup 文件时，没有标准化的"读取→沉淀"流程

**目标**: 建立可复用的"writeup → 知识库"工作流，支持两种模式：
- Mode A: AI 自主搜索+下载+学习（用户说方向）
- Mode B: 用户指定文件/目录，AI 读取+沉淀

**预期收益**:
- 准确度: 沉淀的知识有源文档交叉验证
- 速度: 有渠道清单+价值判断，不再盲目批量下载
- 轮次: 标准化流程减少"怎么做"的讨论轮次

## §2 技术方案

### 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `$SHARED_DIR/knowledge-base/knowledge-sourcing-guide.md` | **新建** | 渠道速查 + 下载方法 + 价值判断 + 提炼流程 |
| `$OPENCODE_ROOT/agents/security-analysis-evolve.md` | **修改** | Phase 0 前增加"入口路径 C: writeup 知识进化" |
| `docs/资料/writeup-sources/_download_sources.py` | **修改** | 从硬编码列表泛化为支持 --url/--github 参数 |

### 架构位置

```
knowledge-sourcing-guide.md   → "怎么获取素材并判断价值"（进化前读）
         ↓ 提炼出技术点
knowledge-writing-guide.md    → "怎么写好知识库条目"（写作时读）
```

### 关键设计决策

1. **sourcing-guide 放 `$SHARED_DIR/knowledge-base/`**：所有方向共用，与 writing-guide 同级
2. **evolve prompt 增加入口路径 C**：不走完整 Phase 2-3（需求文档/审计），因为知识库文件不涉及代码改动；但仍需遵守 writing-guide 规范 + 源文档交叉验证
3. **_download_sources.py 泛化**：保持向后兼容（无参数=运行硬编码列表），增加 --url 和 --github 参数

## §3 实现规范

### 改动范围表

| 文件 | 新增行数 | 修改行数 | 风险 |
|------|---------|---------|------|
| knowledge-sourcing-guide.md | ~120 | 0 | 低（新文件） |
| security-analysis-evolve.md | ~30 | 0 | 中（修改 Agent prompt，需检查行数 < 600） |
| _download_sources.py | ~40 | ~5 | 低（向后兼容） |

### §3.1 实施步骤拆分

**步骤 1. 创建 `knowledge-sourcing-guide.md`**
- 文件: `$SHARED_DIR/knowledge-base/knowledge-sourcing-guide.md`
- 预估行数: ~120 行
- 验证点: 人工读一遍确认自包含性；对照 writing-guide 确认职责不重叠
- 内容: §1 渠道速查表 + §2 下载方法 + §3 价值判断 + §4 提炼流程

**步骤 2. 修改 evolve agent prompt 增加"入口路径 C"**
- 文件: `$OPENCODE_ROOT/agents/security-analysis-evolve.md`
- 预估行数: +30 行
- 验证点: 检查 evolve prompt 展开后行数 < 600；新入口路径不与现有 Phase 0-6 冲突
- 依赖: 步骤 1

**步骤 3. 泛化 `_download_sources.py`**
- 文件: `docs/资料/writeup-sources/_download_sources.py`
- 预估行数: +40 行修改
- 验证点: `python3 _download_sources.py --help` 显示参数；无参数运行仍向后兼容
- 无依赖（独立于步骤 1-2）

**步骤 4. 更新 evolve agent 的知识库文档索引**
- 文件: `$OPENCODE_ROOT/agents/security-analysis-evolve.md`
- 预估行数: +1 行
- 验证点: 索引表中有 knowledge-sourcing-guide.md 条目
- 依赖: 步骤 1

## §4 验收标准

### 功能验收
- [ ] knowledge-sourcing-guide.md: 渠道速查表覆盖 Pwn/Web/Crypto/RE/Mobile/AI 方向
- [ ] knowledge-sourcing-guide.md: 价值判断标准明确（高价值 vs 低价值 + 判断流程）
- [ ] evolve prompt: 入口路径 C 定义了 Mode A/Mode B 两种触发
- [ ] evolve prompt: 简化沉淀流程明确（获取→gap→提炼→写入→索引→审计）
- [ ] _download_sources.py: --url 参数可下载单个 URL
- [ ] _download_sources.py: --github 参数可下载仓库目录
- [ ] _download_sources.py: 无参数运行向后兼容

### 回归验收
- [ ] evolve prompt 行数 < 600（不触发强制瘦身）
- [ ] knowledge-writing-guide.md 未被修改（职责分离）
- [ ] 现有知识库文件无影响

### 架构验收
- [ ] knowledge-sourcing-guide.md 在 $SHARED_DIR/knowledge-base/（通用层）
- [ ] _download_sources.py 在 docs/资料/writeup-sources/（不散落到根目录）

## §5 与现有需求文档的关系

- 本需求是 `2026-06-29-ctf-writeup-knowledge-evolution.md` 的方法论沉淀
- 那个需求做了"第一次 writeup 进化"（具体内容），本需求做"进化能力本身"（可复用流程）
- 两者关系: 本需求让未来的 writeup 进化不再需要每次从头讨论"怎么做"
