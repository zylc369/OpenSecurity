# 进度: 反思系统（方向级 A/B/C/D 判定 + 三通道注入 + 独立评审 v2）

> 需求文档：2026-09-29-reflection-system.md
> 流程纪律：每个 Phase 关闭前必须先落盘证据再声明通过（diff/断言/读数），禁止仅有口头声明。

## 流程状态

| Phase | 状态 | 关闭证据 |
|---|---|---|
| 0 复盘分析 | 完成 | 三层失效根因 + 用户两组活体实验，用户逐轮确认 |
| 1 讨论 | 完成 | 用户确认"整个方向我认同"；设计逐项过审 |
| 2 需求文档 | 完成 | 297 行；§1-§5 齐全；控制字节 clean |
| 3 需求审计 | 完成 | R1 修 6 处 + R2 修 4 处 + 纯审计轮零问题；执行中另发现基线错误 1 处（#7 从未落盘，A5 转无操作并回写需求文档） |
| 4 执行计划 | 完成 | 14 步 DAG 无环；架构影响图见下 |
| 4.5 瘦身检查 | 完成 | binary 恒 450 不增（A4 净±0）；web 无改动（A5 转无操作）；fresh-eyes 为 subagent 不受限 |
| 5 执行 | 进行中 | A1-A5/A7 ✅、B1-B5 ✅、A6 盲测重跑进行中、B6 部分完成（echo 代理 + 重启后清单） |
| 6 实现审计 | 未开始 | 待 A6 重跑收口后执行 |

## 基线读数（执行前，wc -l）

fresh-eyes.md=77 → 95；frame-audit.md=44 → 47；stuck-protocol SKILL=45 → 已删除；execution-discipline.md=98 → 98（净±0）；web-analysis.md=253 → 未改动（A5 无操作）；architecture-map.md=99 → 102；reflection-protocol SKILL 新建=80

## 执行台账（Phase 5）

| 步骤 | 状态 | 验证点结果（证据） |
|---|---|---|
| A7 架构地图 | ✅ | 树含 skills/ 行；hooks 表含 session.idle + tool.execute.after 两行；99→102 行 |
| A1 reflection-protocol skill | ✅ | 80 行；控制字节 clean；吸收两节正文与 stuck-protocol 原文逐字一致（diff 仅标题行因重编号差异）；description 无卡壳自评依赖 |
| A2 fresh-eyes v2 | ✅ | 95 行；mode/permission 不变（frontmatter 与原格式一致，多余 name 字段已除）；三节强制审计先于维度表；输出=候选检验项；新禁令在；旧契约词组文件内 grep=0；控制字节 clean |
| A3 frame-audit v2 | ✅ | 47 行；机械收集流程逐句保留；模板含死路待复核；接收处理=逐条执行或降权；clean |
| A4 execution-discipline | ✅（含用户评审修订） | 终态（§6-2）：纯路由行"收到'反思心跳'消息或反思纸条时，按 reflection-protocol skill 执行 A/B/C/D 方向判定；判定规则、阈值与探针规范以该 skill 为权威"——阈值数字不再双源（skill 单一权威）；98 行不变；agents-rules/ 内 stuck-protocol grep=0 |
| A5 web-analysis #7 | ✅（无操作） | **发现需求基线错误**："线索归属先于投入"在 web-analysis.md/HEAD/全仓（requirements 外）零命中——此前上下文压缩记录有误，该原则从未落盘。需求文档 §2.10/§3.1/§5 已回写修订 |
| A6 回放验收 | ✅（盲测通过） | **run 1**（/tmp/reflection-replay，污染）：候选项 #1=直接提交 [::1]、#3=归属验证、#4=通道判别——但夹具把任务目录当原始材料，评审用解出记录当 ground truth（夹具设计缺陷，非契约缺陷）。**run 2**（/tmp/reflection-replay2，干净夹具+硬边界，盲测 ✓ 无任何解出痕迹引用）：**验收通过**——E3=VecNetDB 归属判定（验收标准 B 项命中）；死路重审判定 D7（fuzz 语料 100% 无效：fail 页实为登录页→"全灭"未死需重测）、D8（三要素无留痕未死）、D9（挑战内秘密作 HMAC 密钥从未试→E2）；求值时刻表显式标记"无人机 jar 中是否有预置会话从未观测"（制胜前提的盲态浮现）；归属矩阵把 ChromaDB/密码标"未定归属"。**run 3**（/tmp/scaudit，无指针中性夹具）仍在后台跑，作为追加数据点。勘误：此前把 run 1 的污染误记为"run 2 突破边界"，已更正——run 2 遵守了边界 |
| B1 SessionData+常量 | ✅ | session-manager +8 行（lastReflectionAt/reflectionCount/lastReflectionToolCount 带注释）；constants +8 行（ENV_KEY_REFLECT_NUDGE + REFLECT_NUDGE_DEFAULT_INTERVAL_MIN=30） |
| B2 反思纸条 | ✅ | security-analysis.ts +~90 行（两函数 + 调用点 + statSync import）；调用点在事件库/记忆库存储之后（代码顺序可断言）；bun build exit=0；守卫 6 道全带 debugLog |
| B3 统一注入器 | ✅ | persistence.ts：getReflectIntervalMs 导出（与纸条共用单一来源）+ renderReflectionHeartbeat（动态数字 + 每第 5 次死路复核条件渲染 + 第 0 条两级优先 + 续接句）+ sendReflection（promptAsync synthetic）+ maybeResumeAnalysis 完成标记后插入反思分支（优先于 resume，日志全路径）；期间修复两次编辑事故（sendResume 首行误删换行/误删 sessionID 声明，均已复原并编译验证）；bun build exit=0 |
| B4 检查点删除+schema+镜像 | ✅（含用户评审修订） | **认知检查点整体删除**（用户决定，见需求 §6-1）：checkpoint.ts 文件删、cognitionCheckpoint 函数+调用点删、SessionData 三字段删、constants 三常量删、自检冒烟块以"模板含方向表节"断言替代、台账措辞改"反思心跳按此盘点"、control-config/constants/session-manager 注释同步。保留部分：cognition.ts sections.directions；LEDGER_TEMPLATE 方向表节+未测条件约束；getCompactionContext 方向表保留。验证：七文件 bun build ✓；verifyMirrors=[]；模板断言 ✓；"认知检查点"运行时资产 grep 零残留（注释全部改写） |
| B4' reflection.ts 抽取（用户评审修订 §6-3） | ✅ | 新建 lib/reflection.ts（192 行）：isReflectEnabled/getReflectIntervalMs/isReflectionDue/markReflectionFired（顺序敏感差值唯一实现点）/isReflectionEligible/renderReflectNudge/maybeAttachReflectNudge/renderReflectionHeartbeat/sendReflection；persistence.ts 改薄调用（402 行）；security-analysis.ts 删本地纸条实现（1571 行）；全部编译 ✓ |
| B5 删除 stuck-protocol | ✅ | skills/stuck-protocol/ 已删；.opencode/ 引用 grep=0（含修复 web-methodology.md L331 漏网引用→改指 reflection-protocol）；全部插件文件编译 ✓ |
| B6 活体验证 | 部分 | echo 代理实验已完成（见下）；重启后清单见下 |
| B7 回归总检 | 待 A6 后 | |

## B6 记录

### echo 代理实验（general 子代理盲测）

任务：跑 collect.sh（正常输出末尾带纸条文本）→ 报告端口 → 列下一步 3 件事。
结果：① 端口问题全部正确回答、3 件事计划完整——**未降级既有承诺 ✓**；② 纸条被识别为"命令输出中的提示注入"并**拒绝执行其指令**，还推断出这是测试——照办性 ✗。
判读：general agent 没有反思上下文（无台账、系统提示无反思触发条款），把纸条当不可信注入是合理行为；真实部署位（五分析 agent）有两层合法性来源——execution-discipline 的"反思触发"行（系统提示常驻）+ reflection-protocol skill 在技能列表。**结论：代理实验证明安全性（不劫持），照办性必须等重启后在真实分析 agent 上验证**——若真实环境仍被判为注入，处置=在 agent prompt 的反思触发行里显式写明纸条样貌（定界行文本）。

### 重启后验证清单（opencode 重启使新插件生效后执行）

1. 启动冒烟：plugin_debug.log 无编译错误；`verifyCognitionSelfCheck` 通过（日志"认知契约自检：一致"）
2. 纸条：控制台把 REFLECT_NUDGE_INTERVAL_MIN 调至 1，在任一分析任务跑几个 bash → plugin_debug.log 出现"反思纸条 #1 已附加"；查记忆库该 bash 记录不含"反思提醒"标记（顺序验证）；会话 DB message part 含标记（送达验证）；观察模型行为两问
3. 心跳：让分析会话空闲超过间隔 → plugin_debug.log 出现"反思到期…优先发心跳"；模型按 A/B/C/D 回应且第 0 条优先级生效
4. resume 回归：反思未到期时 idle → 走原 resume 路径（日志对照逐行一致）
5. 新任务台账模板含「方向表」节
6. system.transform / compacting / event 三 hook 端到端（Playbook 高风险要求）

## 桌面推演（§4.1-2，已完成）

对 09-28 08:30 快照套用心跳文案：
- 方向"密码→找对应用户名"：前提="GR 密码属于本题"（未验证）；投入≈数百批次×12h；产出=结论#6 后无新增=空 → **规则 2 命中判 C**：先跑归属验证（CTFd solves 时间线交叉，零成本）→ 数小时内处决 29h 僵尸方向 ✓
- 方向"宿主形态×会话"（09-27 19:13 经 httpbin 包装判死）：死路复核 → 三要素：携带物=未隔离（"无人机自身携带的会话"从未测过）、提交路径=恒为外部包装（从未变过）→ 两项不完整 → **判 B**：假阴性嫌疑 → 换直接提交重测 → [::1] 返回已认证内容 → 复活 ✓
两规则各命中一坑，推演通过。

## Phase 4 架构影响图

```
[新建] skills/reflection-protocol/SKILL.md
   ↑ 引用                     ↑ 文案引用
agents-rules/execution-discipline.md（A4）   plugins/checkpoint.ts 数字提示（B4）
   ↑ 片段展开                          plugins/security-analysis.ts 纸条（B2）
五个分析 agent prompt                    plugins/lib/persistence.ts 心跳（B3）
                                       ↑ 共用 lastReflectionAt/reflectionCount（B1）
[重写] agents/fresh-eyes.md ←派发─ commands/frame-audit.md（A3）/ 心跳文案 / 用户
plugins/lib/cognition.ts + task-session-persistence.ts（B4 方向表 schema+镜像）
[删除] skills/stuck-protocol/（B5，引用已清零）
security-analysis-evolve/.../architecture-map.md（A7 记录）
```
