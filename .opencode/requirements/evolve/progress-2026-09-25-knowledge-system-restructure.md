# progress: 知识体系职责重构（scout 专职侦察 + evolve 独占进化）

需求: `2026-09-25-knowledge-system-restructure.md`（合并执行 `2026-09-23-evolve-prompt-slimming.md`）

| 步骤 | 状态 | 记录 |
|------|------|------|
| 1 scout agent | ✅ | `agents/knowledge-scout.md`（hidden: true + mode: subagent + tools 白名单 webfetch/read/bash/glob/grep——"不写知识库"机制化）; **plugin 白名单发现**: `AGENT_SCRIPT_DIRS` 是显式映射表非通用推导——`plugins/lib/constants.ts` 加 AGENT_KNOWLEDGE_SCOUT 常量 + GENERAL_SUB_AGENTS 收录 + 映射 3 处（node --check 过） |
| 2 sourcing-guide 迁移 | ✅ | git mv 至 knowledge-scout/knowledge-base/ + download_sources.py 随迁（谁执行谁持有）; 改造: §0 角色定位+gap 判定权威+§0a 报告格式、"教训"节洗为"常见错误模式"、§3 引用自足化; 叙事零命中、旧路径零残留 |
| 3 knowledge-search 命令 | ✅ | 五分支输入解析; 显式 subagent_type 派发（hidden 不依赖 description 路由）; "不沉淀只建议"入模板与约束; 无已删命令引用 |
| 4 evolve 重构 | ✅ | 入口 C 三路径（直接蒸馏含五分支速查/先搜后蒸含派 scout/给定文件）; gap 权威下沉指针; 索引表调整; 五场景走查过 |
| 5 distillation-methodology | ✅ | 对话入口 + 输入解析节（六形态详解）+ 先搜后蒸 + /knowledge-distill 清零; 修复: 双分隔线、§0 断链引用（evolve 视角 sourcing-guide 路径已失效→改派 scout 表述） |
| 6 命令删除 | ✅ | git rm knowledge-distill.md + evolve-from-writeups.md; 全仓零残留（requirements 历史豁免） |
| 7 瘦身执行 | ✅ | **641→439 行（<450 达标）**。X1+X2→architecture-map.md（含 scout 目录与 plugin 映射更新、归属速查/单向依赖/依赖方向/hooks/变量表全量）; X3 四维度量+价值评估合并单节; X4+X5+X11→evolution-playbook.md; X6→long-document-editing.md; X7 铁律原理+X9 自检清单→writing-guide §6/§7; X8 原因段压缩; X10→opencode-references.md。S1 交叉引用盘点: 外部零依赖（write-gzh 的"规则 3"是其文内编号）; **S8 发现 X10 误伤索引表**（吞掉 retrospective/writing-guide 行）→ 重建统一"知识库文档"索引表（8 KB 全量）; 五场景走查回归通过; 规则号 12 条全保留 |
| 8 hidden 知识沉淀 | ✅ | opencode-agent-format.md: 字段表加 hidden 行（语义/派发不受影响/适用场景/description 不再承担路由的注意点）+ 注入规则段补 hidden 过滤说明（源码 filter((a) => !a.hidden)） |
| 9 端到端 | ✅ | knowledge-search 五分支 5/5; 五场景走查过; 叙事词终扫零真残留（命中全为规则 8.0 元文本/正则自身/既有注释）; 蒸馏触发面确认收窄（commands 零 distill，唯 evolve 对话） |

## 关键机制记录

- **hidden agent 三处源码证据**: agent.ts:40（schema）/ tool/task.ts:131（派发按 name 不过滤）/ prompt.ts 四处（注入列表全过滤）——内置 compaction/title/summary 同用法
- **AGENT_SCRIPT_DIRS 白名单**: 新 agent 有专属目录必须在 constants.ts 加映射，否则其会话无 $AGENT_DIR
- **瘦身执行教训**: X10 类整节替换正则要先盘点节内是否含节外职责的条目（索引表误伤）——git diff 逐行核对删除内容

## 遗留

（原"hidden 运行时确认"遗留已由下述实测闭环，清空）

## 运行时测试（用户追问"测试过吗"触发，全部实测通过）

| 测试 | 结果 |
|------|------|
| 配置解析 | `opencode agent list` exit=0, knowledge-scout (primary) 在列 |
| **注入过滤** | binary-analysis 的 task 类型列表 11 类**不含 scout**（"零注入其他 agent"达成） |
| scout 调度 | `opencode run --agent knowledge-scout` 直接可用; `$AGENT_DIR` 正确指向 knowledge-scout/ |
| tools 白名单 | 工具清单 bash/glob/grep/read/webfetch/websearch——无 write/edit |
| **命令端到端** | `opencode run --command knowledge-search '端口扫描技术'` 完整跑通: 派发 scout → 真实侦察（naabu/ZBanner/nmap 隐身扫描 gap 对照 + 2 篇落盘 + 结构化报告: 建议沉淀清单含"结构性"标注/素材路径/遗留）→ 原样呈现 + 询问是否转 evolve——行为与设计完全一致 |
| evolve 新 prompt | 会话实测: 入口 C 三路径名正确、索引表 8 条（426 行版生效） |

**测试暴露并修复的两个真问题**（独立复审未覆盖、静态分析无法发现）:
1. **hidden 不过滤 task 注入列表**——registry.ts describeTask 只过滤 `mode !== "primary"`，hidden 完全不在链路（此前把 prompt.ts 的 hidden 过滤错误推广，属源码误判）。修复: scout 改 `mode: primary` + `hidden: true` 组合（primary 从 task 列表消失、hidden 从切换菜单消失; 内置 compaction/title/summary 同款组合; task 显式派发按 name 解析不受影响）
2. **frontmatter 中文行内注释破坏 YAML 解析**（值连同注释被整体当字符串）——frontmatter 只留纯值，机制说明移正文

教训追加: **行为性断言（"hidden 会过滤注入"）必须实测或追到确切代码行**——本次错误源于把 A 处的 hidden 过滤语义推广到 B 处列表; `opencode run --agent/--command` 是 agent/命令的端到端测试利器。

## 独立复审修复（8 findings 全修）

| # | 级 | 内容 | 修复 |
|---|---|------|------|
| H-1 | 高 | tools 逗号字符串致**全项目配置解析失败**（实机 `opencode agent list` 报错，任何重启即断; 复审者临时目录实测出正确格式） | 改映射形式 + `"*": false` 前置（只列 true 不拒绝未列工具——schema 是逐工具 allow/deny 规则非白名单）; 修复后实机验证 exit=0 |
| M-1 | 中 | 白名单缺 websearch（sourcing-guide 指定 ai-security 方向用 websearch 替代 CTF Base，路径不可执行） | 加 `websearch: true` |
| M-2 | 中 | agent-format.md 三处 tools 文档写逗号字符串/JSON 数组——与 schema（Record<String,Boolean>）不符，是 H-1 的直接诱因 | 三处改映射形式 + 补白名单语义（`"*": false` 前置 + 工具名小写） |
| L-1 | 低 | architecture-map 的 evolve 目录树只列 2 KB，缺 3 个新 KB（暗示穷尽但不真穷尽） | 补全 6 KB |
| L-2 | 低 | 规则 4"参照开头的架构图"失效自引（架构图已提取） | 改"参照 architecture-map.md" |
| L-3 | 低 | 规则 4 落位清单与地图归属速查双头维护且口径不一（规则 4 版未覆盖 web/crypto/ai 方向） | 规则 4 收敛为指针，明细归地图单处维护（426 行） |
| I-1 | 信息 | progress 遗留项"瘦身状态标记待更新"过时 | 本文件遗留节改写（状态已更新） |
| I-2 | 信息 | 规则 8.0（prompt）与 writing-guide §6（KB）各持禁令一半 | 设计如此（prompt 保核心/KB 保详解）; 记录: 未来修改叙事规则需两侧同步 |

## 教训（执行层）

- **frontmatter 修改必须实机验证解析**（`opencode agent list`）——静态字段检查验不出 schema 形态错误; 本次靠独立复审的实机测试兜住
- **tools 字段是 allow/deny 映射**，白名单语义必须 `"*": false` 前置——文档错误（M-2）先于本次存在，踩坑才暴露
