# progress: 2026-10-03 信息枚举类方法论 + 验证 oracle + 栈布局计算器

需求文档: requirements/evolve/2026-10-03-info-enum-pwn-and-verify-oracle.md

## 步骤进度

- [x] 步骤 1: pwn-methodology.md §1 尾部新增「题型变体：信息枚举类」子节
  - 26 行纯新增（7 要素 + 调用模板），git diff 零删除
  - 验证: 题目指纹 grep 零出现（robocall/sunshinectf/CHUNK_DEPTH/sun{ 均无）; §2-§6 未动; 触发行未动
  - 过程修复: 编辑时误改 glibc-all-in-one → allin-one（1 处），当场发现并恢复，diff 复核零删除
- [x] 步骤 2: pwn-methodology.md §5 补充容器内 qemu gdbstub 通道 + dbg 模板
  - 纯新增 ~33 行（通道说明 + qemu -g 命令 + gdb commands 模板）
  - 验证: 三处"失真"表述（329/363/435 行区域）原文逐字未变; "不走 ptrace"/"不需要 SYS_PTRACE"两点齐备; dbg 模板与本会话已实证跑通的 dbg4.gdb 同构
- [x] 步骤 3: verification-patterns.md 新增「第零步」节 + 触发行扩展
  - 新增 ~28 行; 唯一删除行 = 触发行改列表格式（crackme 枚举原样保留）
  - 验证: 触发条件为可观察形态; CTFd 细节零展开（比需求上限更收敛）; 决策树及方案章节零改动
- [x] 步骤 4: stack_frame_calc.py 实现（.opencode/binary-analysis/scripts/，新文件）
  - 验证: ① compile 通过 ② 帧表提取 cancel_plan=0x430 / place_flag=0x2060（多次 sub 累计修复）③ --chain 链距 -0x560 与 gdb 实测一致 ④ --reach: 0x5A0 可达(0x120×5)、0x690 不可达(BFS 无解)——与实测泄漏互证; fixed-step 场景 0x880=0x440×2 正确 ⑤ 不可达 target 有界退出 <5s
  - 过程修复: objdump 正则两处（`>:` 行尾锚定、`rsp, 0x` 逗号空格）适配 llvm-objdump 格式; place_flag 连续 sub 累计
- [x] 步骤 5: 交叉验证收尾
  - 题目指纹 grep 计数 0（robocall/sunshinectf/CHUNK_DEPTH/navigator/sun{）
  - diff 范围: pwn-methodology +56 纯新增; verification-patterns +18/-1（唯一删除=触发行改列表格式，crackme 枚举保留）
  - writing-guide §3 五清单过: 准确性(全部来自本会话实证)/完整性(六要素+五渠道+三模式)/一致性($SHARED_DIR 变量引用)/可操作性(模板可复制+成功失败判断明确)/排版(一行一项)

## Phase 关闭证据汇总

- Phase 3 通过: 3 轮审计（2 修复+1 纯审零问题）
- Phase 4 通过: 3 文件影响面、零高风险改动
- Phase 6 通过: 3 轮审计（第 1 轮: 参数一致性/互引有效性过; 第 2 轮: 发现规则 9 违反——dataclass 字段与函数签名弱 list 注解，已修为 list[T]/list[str]/list[int] 参数化并三模式回归; 第 3 轮纯审零问题）

## 测试质量审计（用户质询后补做）

- 原测试覆盖: 8 项主路径（帧表/链距/可达/不可达/fixed-step/有界退出，与 gdb 实测互证）——**错误分支 0 覆盖**（模式 F 盲区）
- 补做边界矩阵 16 项 → 首跑 11/16，暴露 5 项:
  - 真工具 BUG ×1: 链尾函数名不校验（拼错静默通过）→ 已修（帧表存在性全链校验）
  - 测试自身问题 ×3: 非 ELF 断言文案 / 空 loops 预期（CLI 拦截合理）/ forbid 子串误报（"0x120×3" 含 "0×"）→ 已修
  - 已知限制 ×1: argparse 负数参数须等号形式（--target=-0x10），行为正确
- 复跑 16/16 全过 + 主路径回归（链距 0x560 / 0x690 不可达）不变
- 测试资产沉淀: scripts/stack_frame_calc_test.py（16 项矩阵可重跑）

## Review 轮（code review 子代理 + 修复）

- Review 结论: 核心算法无逻辑 bug（calc_chain/calc_reach 实跑验证）、16/16 测试过、PLANS 11 组合逐一对 CHUNK_DEPTH 核算无误、知识段无叙事词
- 发现并已修 7 项:
  1. **[中] 48/52 → 44/52**: 11 块×4=44 字节实证+8 字节推断=52（原数字自相矛盾 48+4+4=56>52）; writeup 与需求文档 §1 两处已改
  2. [低] 测试文件未跟踪 → git add（progress 声明与仓库状态对齐）
  3. [低] 测试硬编码绝对路径 → TOOL 从 __file__ 推导、ELF 从仓库根推导
  4. [低] docs/ 样本依赖 → 样本缺失自动 SKIP（不判 FAIL、退出码 0）
  5. [低] TimeoutExpired/parse_size 非法输入裸 traceback → 干净 sys.exit
  6. [低] mod 16 无区分力时误称"相位证据" → 仅 target%16∉增量余数集时输出模相位，否则输出"完备穷举证明"（BFS 上界覆盖全部可达部分和，无解即严格不可达）
  7. [低] extract_frames 启发式边界（[小,大] sub 顺序敏感 / and rsp 对齐不建模）→ docstring 声明 + "异常值回 gdb 校验"指引
- 修复后测试矩阵 18/18 全过（新增: 非法数值输入、不可达穷举证明文案 2 用例）+ 主路径回归（0x560 链距 / 0x690 不可达文案正确）
- 全部相关文件已暂存; IntMod 目录与本变更集无关，保持未跟踪

## 独立审计轮（code review 子代理后的全维度审计流程）

- 周期 1（两轮均有问题，共修复 10 个）:
  - writeup 分类 pwn→逆向（与结论一致）; 文件节补登 verify_flag.py/verify_win.png
  - verify_flag.py 重构: 登录态自举（state.json 缺失用 RC_USER/RC_PASS 自动登录）+ 路径自包含 + precheck 外置（playwright 上下文内 SystemExit 被 teardown 噪音淹没的真实 bug）+ fresh 死参数清除
  - solve.py 重构: 本地挂载参数化（脚本同目录）+ PLANS 携带块索引（消除展示名文本解析）+ CHUNK_DEPTH 启动自检（激活死常量）
  - stack_frame_calc.py: 参数组合互斥校验（--reach/--elf/--chain/--subs 静默忽略→显式报错）+ docstring 相位表述与实现同步 + frames 弱注解参数化 + 死分支清理
- 周期 2 第 1 轮（修 1 个）: frames=None→dict[str,FrameInfo]{} 类型歧义
- 周期 2 第 2 轮: 零问题（终态断言: verify precheck外置/无硬编码/无死参数; solve 11 PLAN 结构断言; calc 18/18 测试 + 0x560 链距回归）
- 周期 3: 两轮零问题，审计通过

## 用户质询"都不缺了？"后补测（暴露 3 个测试缺口，全部补齐）

- 缺口 A **[真缺陷]**: solve.py 重构后端到端从未跑过——首跑全 FAILED，根因 = 交付的 robocall 二进制无执行位（-rw-r--r--）且 solve.py 失败时零诊断信息。修复: ① 本地模式预检（robocall 存在/可执行 + flag.txt，缺任一干净退出带指引）② FAILED 输出附带 stderr 尾部 ③ robocall 交付物补执行位。修复后端到端全通（44 字节正确泄漏 + 缺口正确显示）
- 缺口 B: verify_flag.py 登录自举（ensure_state 重构代码）从未实测——真实凭据实测通过（state 缺失→RC_USER/RC_PASS 自动登录→提交→correct→exit=0）
- 缺口 C: 重复提交已 correct 题目的边界——实测 CTFd 对已解题重复提交仍返回 status='correct'，脚本判定兼容 ✓
- 纪律: 测试产物（state.json 含登录 cookie）测后即删，绝不入库
- 元教训: 审计周期 3"通过"的判定被本轮质询推翻——静态断言/自检≠端到端; "错误分支零覆盖"的病第三次以新形态出现（预检分支写完后没跑失败场景，直到真实失败才暴露）

## 最终交付物

| 文件 | 变更 |
|------|------|
| .opencode/binary-analysis/knowledge-base/pwn-methodology.md | +56: §1 信息枚举类子节(7要素+调用模板) / §5 容器 qemu gdbstub 通道+dbg 模板 |
| .opencode/binary-analysis/knowledge-base/verification-patterns.md | +18/-1: 第零步 oracle 节(五渠道+禁猜铁律) / 触发行扩展 |
| .opencode/binary-analysis/scripts/stack_frame_calc.py | 新增: --elf 帧表 / --chain 链距 / --reach 环可达性 BFS |

零高风险改动（无 prompt/Plugin/_base 触碰）; 既有内容 diff 零变化（除触发行格式化 1 行）

## 用户第三次质询后补测（4 缺口，含 2 个真缺陷）

- 缺口 1 **[真缺陷]**: solve.py --remote 重构后零覆盖——首跑块5 FAILED。手动 3 连单测全成功 → 判定偶发网络抖动; 根因 = remote 无重试机制（一次抖动永久 FAILED）。修复: leak_once 抽取 + 远程 3 次重试（本地确定性不重试）; remote 全量 11/11 复通 + 本地端到端回归复通
- 缺口 2 **[真缺陷·同类第三次]**: verify_flag.py 失效登录态实测 → playwright 上下文内 assert 被 teardown 吞噬（裸 traceback + 退出码丢失）——与 SystemExit 同病根。根治: run_session 函数化，块内全部 return 错误对象、块外统一 sys.exit; 失效态实测干净单行消息 + 真实 exit=1; 正常态复测 correct
- 缺口 3: 纯数据对象文件 --elf 兜底分支实测通过; 兜底文案修正（原"静态链接符号可见"表述误导）
- 缺口 4: WORDS 候选列表 space（已验证答案）前置 + 注释，重跑者免交 5 个错误候选
- 测试方法自察: 管道后 $? 取的是 tail 退出码非 python——一次自测误报 exit=0，改直跑复核
- 模式总结: playwright 上下文内 SystemExit/assert/raise 均会被 teardown 异步异常吞噬——任何在块内的失败表达必须用 return 传出到块外处理
