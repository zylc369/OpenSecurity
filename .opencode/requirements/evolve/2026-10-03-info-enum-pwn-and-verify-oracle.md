# 需求: 信息枚举类题型方法论 + 验证 oracle 原则 + 栈布局计算器

## §1 背景与目标

### 来源

RoboCall (SunshineCTF 2026) 解题复盘（2026-10-03）。复盘结论：44/52 字节（11 块 × 4）实证泄漏后，剩余 8 字节缺口因"无验证渠道意识"连续两轮交付未验证猜测（全错）；栈帧距手算错误率 3/3（hex 减法 ×2、环增量公式 ×2），靠 qemu-gdb 逐步实测兜底。

### 痛点

1. `pwn-methodology.md` 只覆盖漏洞利用类题型（溢出/ROP/heap）。"信息枚举类"（程序无利用原语，靠泄漏原语逐块枚举秘密数据）无任何覆盖——此类题型下次出现仍要从零摸索打印原语审计点、栈深导航思路、可达性分析方法。
2. `pwn-methodology.md` §5 已记载两种 qemu 调试形态区分（宿主 `qemu-gdb` 正常可用 vs 容器内 gdb ptrace 失真），但**容器形态下的第三通道缺失**：容器内 `qemu-x86_64 -g <port> ./binary`（自带 gdbstub）+ 容器内 gdb `target remote :<port>`——remote 协议不经过 ptrace，断点/读寄存器/finish 全部正常。需要挂载目录 + stdin 管道的场景（本地复现远程交互流程）必须用容器形态，此通道是容器形态下唯一可用的符号级调试路径，缺失会让 AI 在容器里反复修 ptrace 权限（加 `--cap-add=SYS_PTRACE` 无效）后放弃调试。
3. `verification-patterns.md` 只覆盖**本地程序**验证（Unicorn/ctypes/GUI/Hook）。结论含不确定成分时（缺口需补全、候选需筛选）应先枚举**远程/外部验证渠道**（平台提交、复现、一致性重测）——此原则完全缺失，是两轮瞎猜交付的结构性根因。
4. 栈帧距链式累计与环组合可达性穷举无工具支撑。单次加法简单，但跨 5+ 层调用链的 16 进制累计 + 环半群 BFS 覆盖判定属于 AI 心算不可靠的运算（实证错误率 3/3）。

### 预期收益

- 四维度量：准确度（杜绝未验证猜测交付，实测同类场景浪费 2 轮+信任损失）、轮次（栈计算工具消除 2-3 轮手算纠错）、上下文（方法入库后不用现场重推）、速度。
- 进化产物均为**通用层**（binary-analysis/），PC CTF 与移动端场景均可引用。

## §2 技术方案

### 2.1 `pwn-methodology.md` §1 尾部新增子节「题型变体：信息枚举类（无利用原语）」

插入位置：§1 标准 8 步流程末尾、§2 之前。约 75 行。内容结构（按 knowledge-writing-guide 场景驱动三问组织，**全部抽象描述，禁用具体题目的数值/函数名/输入序列**）：

1. **识别信号**：程序输出全走固定字符串（无 printf/格式化串）、秘密数据（flag/密钥）在启动阶段被读入并打散/搬运进栈帧后函数返回（成为栈残留）、存在打印变量的输出原语。
2. **未初始化输出槽原语（审计点）**：手写 parse/转换函数（`raw_parse_int` 类）失败路径常见"直接 return 不写输出指针"缺陷 → 后续打印该槽即泄漏进入函数时的栈残留。审计方法：grep 所有"parse 后跟打印"的路径，检查 parse 失败分支是否写输出槽；利用时输入非数字使 parse 失败。注意：前序交互输入数字会污染槽。
3. **栈深导航**：菜单驱动程序所有出口若都是 `call <菜单函数>`（永不返回），各回路产生固定栈深增量（环）。泄漏槽对准目标数据的条件：Σ(环增量) == 目标数据相对基准的偏移。环增量必须实测（gdb 断点打印每次进入菜单函数的 rbp，两次差值），禁止手算——帧距公式 `callee_rbp = caller_rbp - caller_sub - 0x10`（ret+push rbp），易错点三条：① 用 caller 的 sub 不是 callee 的；② 会返回的临时调用不计入环增量；③ hex 减法必须用工具（`python -c` 或 stack_frame_calc.py）。
4. **可达性分析**：所有函数 sub rsp 为 16 倍数且无非 prologue push 时，环增量半群 ≡ 0 (mod 16)——部分目标偏移结构性不可达；连续数据副本（read 直读未清零区）可提供补充窗口但受同样模约束。判定用 `stack_frame_calc.py --reach` 穷举（AI 不可靠心算）。
5. **枚举收集**：每连接泄漏一个窗口（无 fork 的服务重连即新进程、栈布局不变）；程序若有全局延迟开关（如输入特定值跳过 nanosleep）优先关闭。
6. **缺口处理**：拿到 N-4 字节剩余数学不可达缺口时，转入验证 oracle 流程（见 `verification-patterns.md` 远程验证节），禁止直接交付语义猜测。
7. **调用模板**：stack_frame_calc.py 三模式示例（见 2.4）。

### 2.2 `pwn-methodology.md` §5 补充容器内 qemu gdbstub 调试通道（约 15 行）

1. **补充（非修正）**：在 §5 两种 qemu 形态说明（宿主 qemu-gdb / 容器内 ptrace 失真）附近，补第三通道——容器内 `qemu-x86_64 -g <port> ./binary &` + gdb `target remote :<port>`：remote 协议不走 ptrace，断点/读寄存器/finish 正常；适用场景 = 需要目录挂载 + stdin 管道驱动交互流程的本地复现；明确"加 `--cap-add=SYS_PTRACE` 救不了容器内直接 ptrace，但此通道不需要该参数"。
2. **dbg 脚本模板**（~10 行 gdb commands）：多函数断点 `commands N / silent / printf "FUNC rbp=%p\n", $rbp / c / end` 静默打印模板（配 `set pagination off; set confirm off; file ./bin; target remote :1234`），用于环增量实测与栈布局校验。

### 2.3 `verification-patterns.md` 新增节「第零步：验证渠道枚举（远程/平台 oracle）与禁猜原则」

插入位置：`## 完整验证决策树` 之前。约 35 行。内容：

1. **触发条件**：分析结论含不确定成分——泄漏/恢复结果有缺口、存在多个候选（猜测的词/密钥/配置）、推断链含未经证实的假设。
2. **oracle 渠道清单**（按优先序）：① 目标平台提交接口（CTF 比赛结束后通常仍开放提交验证；网页类平台用项目内浏览器自动化工具操作）② 本地复现（构造已知假数据重放同样流程，比对输出）③ 一致性重测（同输入重跑两次以上，结果必须稳定）④ 官方源码/公开 writeup（题库仓库、搜索引擎）⑤ 字节级比对（部分恢复场景对照原始文件）。
3. **禁猜原则（铁律）**：未经任何 oracle 验证的候选结论，交付时必须标注「未验证 + 完整候选列表 + 各候选依据」，禁止使用"最终裁决/确定"类确信表述；已否定某候选需留否定证据（如平台返回 incorrect）。
4. 示例一句话：CTFd 系平台提交按钮与结果判定因主题而异，以 DOM dump + API 响应为准（细节检索记忆库），不展开。

### 2.4 新增 `binary-analysis/scripts/stack_frame_calc.py`（约 180 行）

独立纯 Python 工具（**不 import _base.py**，非 IDAPython 脚本，与 gui_*.py 同级的 CLI 工具）。三模式：

1. `--elf <binary>`：调用 objdump 提取每函数 `sub rsp` 值，输出帧表（函数名 → sub 值），供链式计算引用。
2. `--chain main,sp,ic,cp`（配合帧表或 `--subs 0x110,0x110,0x170`）：输出调用链每层 rbp 相对初始 rbp 的偏移（16 进制），消除手算。
3. `--reach --loops 0x120,0x400,0x410 --target 0x690 [--fixed-step 0x440]`：环组合可达性 BFS——判定目标偏移能否由环增量的非负组合（+ 可选固定步进的任意倍数）表示，输出一组组合方案或"不可达+模 16 相位证据"。搜索空间有界（上限 target + max(loops)，防死循环）。

**反模式对照**（evolution-playbook）：
- 非"简单计算写脚本"：环半群 BFS 覆盖判定是 AI 心算不可靠的算法（实证），且 16 进制多级累计错误率 3/3；
- 非"一次性特化"：输入完全通用（任意二进制/任意链/任意环集），不绑定任何具体题。

**类型规范**（规则 9）：`FrameInfo`/`ChainResult`/`ReachResult` dataclass，接口全注解，无裸 dict 传递。

## §3 实现规范

### 3.1 实施步骤

```
步骤 1. pwn-methodology.md §1 尾部新增「题型变体：信息枚举类」子节
  - 文件: pwn-methodology.md（§1 末尾、§2 之前插入）
  - 预估行数: ~80 行（含 stack_frame_calc 三模式调用模板，示例参数用通用演示值）
  - 验证点: ① grep 确认无来源叙事词（robocall/sunshinectf/CHUNK_DEPTH 等题目指纹及本题实测环值零出现）② 自包含读一遍（不依赖上下文可理解）③ §2-§6 既有内容零改动（diff 仅新增块）④ 文档头触发行不动（"二进制+nc"已覆盖此题型）
  - 依赖: 无

步骤 2. pwn-methodology.md §5 补充容器内 qemu gdbstub 通道 + dbg 模板
  - 文件: pwn-methodology.md §5（两种 qemu 形态说明附近）
  - 预估行数: ~15 行（纯新增，不改既有表述）
  - 验证点: ① grep '失真' 三处既有表述原文逐字不变（用内容特征比对，不依赖行号——前序步骤插入会使行号漂移）② 新增通道说明含"不走 ptrace"与"--cap-add 无效但本通道不需要"两点 ③ dbg 模板可被直接复制执行（语法自检）
  - 依赖: 步骤 1（同文件顺序编辑）

步骤 3. verification-patterns.md 新增「第零步：验证渠道枚举」节 + 扩展文档触发行
  - 文件: verification-patterns.md（决策树之前）+ 文档头「## 触发条件」节
  - 预估行数: ~37 行
  - 验证点: ① 新节触发条件写"可观察形态"（结论含缺口/多候选/未证实假设），非主题词 ② 文档头触发行补"泄漏/恢复结果含缺口或存在多候选需要筛选时"（现有 crackme 枚举保留）③ CTFd 细节不超过一句话（不与被拒的 B 重叠）④ 既有决策树及方案章节零改动
  - 依赖: 无

步骤 4. stack_frame_calc.py 实现
  - 文件: binary-analysis/scripts/stack_frame_calc.py（新增）
  - 预估行数: ~180 行
  - 验证点: ① `python -c compile` 语法通过 ② `--elf` 对回归样本实测：`docs/分析/二进制安全/分析-RoboCall/robocall` 提取帧表含 cancel_plan=0x430 ③ `--chain` 手算对照（main→sp→ic→oi→cp = -0x560，与 gdb 实测一致）④ `--reach` 复现结论：loops={0x120,0x400,0x410,0x430,0x440,0x4C0} 时 target=0x5A0 可达（组合 5×0x120）、0x690 不可达（mod 相位证据）——与实测泄漏结果互证 ⑤ --reach 对不可达 target 有界退出（<5s）
  - 依赖: 无

步骤 5. 交叉验证收尾
  - 文件: 无新增改动（步骤 1 已含调用模板）
  - 预估行数: 0 行（纯验证步骤）
  - 验证点: ① knowledge-writing-guide §3 五清单对两个改动文档逐条过 ② 全部改动文件 grep 题目指纹零出现 ③ git diff 复核：pwn-methodology 除 §1 新子节与 §5 补充块外零变化、verification-patterns 除新节与触发行外零变化 ④ progress 文件落盘（progress-2026-10-03-info-enum-pwn-and-verify-oracle.md）
  - 依赖: 步骤 1-4 全部完成
```

## §4 验收标准

### 功能验收

- [ ] pwn-methodology 新子节含：识别信号/原语审计点/栈深导航（帧距公式+三易错点）/可达性分析/枚举收集/缺口转 oracle 六要素，自包含
- [ ] §5 qemu gdbstub 补充后，AI 能据其直接写出可运行的容器内 qemu gdbstub 调试命令（模板自检）
- [ ] verification-patterns 新节触发条件为可观察形态，oracle 清单五渠道齐全，禁猜原则含交付格式要求
- [ ] stack_frame_calc.py 三模式可运行（robocall 二进制作回归样本，结论与 gdb 实测互证）

### 回归验收

- [ ] pwn-methodology §1-§4、§6 既有内容 diff 零变化；§5 仅新增补充块（三处"失真"表述原文不变）
- [ ] verification-patterns 既有决策树与方案章节 diff 零变化（文档头触发行按步骤 3 扩展）
- [ ] 不触碰 agent prompt / Plugin / _base/_utils/_analysis / query.py / update.py（零高风险改动）

### 架构验收

- [ ] 新脚本落 `binary-analysis/scripts/`（通用层），纯 Python 无 IDA 依赖、无对 _base 的 import
- [ ] 知识文件落 `binary-analysis/knowledge-base/`（通用层），符合归属规则
- [ ] 无循环依赖、无跨方向目录引用

## §5 与现有需求文档的关系

- `browser-automation-consolidation.md`（web-analysis 浏览器操作域）：管"怎么操作浏览器"，本需求的 oracle 节管"什么时候必须找验证渠道"——不重叠、不互引。
- `2026-09-29-phase-close-evidence-discipline.md`（evolve 流程证据纪律）：管进化流程自身的 Phase 关闭证据；本需求禁猜原则管**分析交付物**的验证纪律——互补层面，不冲突。
- `2026-09-29-pyright-introduction.md`：pyrightconfig 仅存在于 `mcp-servers/`（已核实 binary-analysis/ 无 pyrightconfig.json），步骤 4 不适用 pyright，以 `python -c compile` + 三模式运行时验证 + 回归样本互证替代。
