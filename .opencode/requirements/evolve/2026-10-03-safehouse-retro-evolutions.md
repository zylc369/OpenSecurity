# SafeHouse 复盘进化：qemu 环境知识 + 本地靶场模板 + BPF 手解工具 + 片段复用范式

> 状态: 已完成（2026-10-03; 步骤 1-6 全过 + review 修复 6 项 + 测试 30/30 + syscall 表权威源全表核对; 执行记录见任务目录 evolve-progress.md）
> 来源复盘: 2026-10-02 SafeHouse pwn 任务（任务目录 20261002_094414_ab58_binary-analysis）

## §1 背景与目标

来源痛点（复盘数据支撑）：
- 痛点 1（~5 轮）: macOS 主机无 Linux ELF 执行能力，seccomp-tools 两次失败、容器两次重建才起靶场
- 痛点 2（~4 轮）: qemu-user 模拟下 gdb 报 `linux_ptrace_test_ret_to_nx`、strace 解码失真，纠缠修工具而非换观测手段
- 痛点 3（~6 轮）: SROP 方案完整设计后才发现 qemu-user 下 rt_sigreturn 仿真不可靠，推倒重来
- 痛点 4（~3 轮）: 0x0A 字节限制重试 20 次未识别系统性模式；复用含加密副作用的函数片段踩双重加密死锁

预期收益（四维）:
- 减少对话轮次 >30%（同类场景合计省 8-12 轮，环境类坑每道 Linux pwn 题复现）
- 提升分析速度（省 15-25 分钟环境/调试摸索）
- 提升准确度（避开 SROP 无效分支；消除人工字节序分解错误——复盘过程中手分解错 2 次）

## §2 技术方案

四个方案全部落现有文件/脚本目录，不新建知识文件，不改 Agent prompt：

**方案 A — pwn-methodology.md 增补 qemu-user 环境知识**（痛点 2+3）
- `§1 步骤 3（沙箱检查）` 补 1 行: seccomp-tools 在 qemu-user 下不可用时的手解指引（指向方案 C 脚本）
- `§4 卡点突破表` 加 1 行: qemu-user 下 gdb/strace 失真 → 标记输出二分 + ps 判死锁；SROP 仿真不可靠 → 用前最小验证、优先片段复用
- `§5 工具链` qemu-gdb 注记补 1 行: qemu-user 容器内 ptrace 限制说明

**方案 B — Docker amd64 靶场模板**（痛点 1）
- `pwn-methodology.md §5` "pwntools 调试模式"条目后增"本地靶场（Docker amd64）"小段: 容器参数（--platform linux/amd64 / -p / -v / --cap-add=SYS_PTRACE --security-opt seccomp=unconfined 的取舍）、靶标文件放置、模板脚本调用方式
- `$SHARED_DIR/scripts/pwn_lab_server.py`: 参数化 fork TCP 服务端（`--port/--binary/--strace`），替代本次现写的 server.py + strace_test.py

**方案 C — seccomp BPF 手解脚本**（痛点 1 的 seccomp-tools 失败分支）
- `$SHARED_DIR/scripts/seccomp_bpf_decode.py`: 从 idat disassemble JSON/文本提取栈上构造的 sock_filter 数组并解码
- 原理: 顺序扫描指令追踪 64 位寄存器立即数赋值 → `mov [rsp+X+Y], reg` 收集 qword 槽 → 值形态过滤（code ∈ {LD_ABS=0x20, JEQ=0x15, JGT=0x25, JGE=0x35, JSET=0x45, RET=0x06} 且 RET 的 k ∈ {0x7FFF0000, 0x80000000} 家族）→ 解码 `<HBB` + k → 输出指令表与白名单 syscall 名
- 内置常见 x86_64 syscall 号→名映射（覆盖白名单场景常见项，未知项显示号）

**方案 D — fork 双进程攻击面 + 片段复用范式**（痛点 4，本题核心知识 MD 权威化）
- `pwn-methodology.md §4` 卡点表加 1 行: fork 双进程（父 seccomp/子持 flag + socketpair 加密信道）架构的攻击面清单（截断溢出/有符号索引/单侧沙箱/ROP 构造跨进程请求），与"自定义加密协议还原"小节交叉引用
- `§4` 新增小节"函数片段复用（gadget 枯竭时的调用点复用）": 副作用表范式——每个复用片段必须列前置寄存器/副作用（内置加密、寄存器破坏）/出口消耗（epilogue `add rsp` 量）; 双重加密陷阱; LCG/pid 型 key 低 24 位恒定的重试判别法; 读循环 vs pivot read 两种 BSS 写入通道的字节限制差异

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `$SHARED_DIR/knowledge-base/pwn-methodology.md` | 增补（4 处） | +75 行内 |
| `$SHARED_DIR/scripts/pwn_lab_server.py` | 新增 | ~90 行 |
| `$SHARED_DIR/scripts/seccomp_bpf_decode.py` | 新增 | ~190 行 |

编码规则:
- 知识条目遵守零来源叙事（无题目名/赛事名/"实测"）; 触发条件写代码形态/可观察形态
- 脚本自包含（argparse + --help 可读）; 不依赖 $SHARED_DIR 其他模块（纯独立工具，不进 _base/_utils 依赖链）
- 知识库文件引用脚本用 `$SHARED_DIR/scripts/...` 变量路径

### §3.1 实施步骤拆分

步骤 1. pwn-methodology.md 方案 A 增补（qemu-user 三处）
  - 文件: pwn-methodology.md
  - 预估行数: ~16 行
  - 验证点: 人工读自包含性; `grep -n "qemu" pwn-methodology.md` 确认新增行与既有 qemu-gdb 条目无矛盾; 叙事词 grep 零命中
  - 依赖: 无

步骤 2. pwn-methodology.md 方案 B 知识增补（Docker 靶场条目）
  - 文件: pwn-methodology.md
  - 预估行数: ~14 行
  - 验证点: 条目含完整 docker run 命令可复制执行; 引用 pwn_lab_server.py 路径为 $SHARED_DIR 变量形式
  - 依赖: 无（脚本调用方式先写，步骤 3 落脚本）

步骤 3. pwn_lab_server.py 靶场脚本
  - 文件: $SHARED_DIR/scripts/pwn_lab_server.py
  - 预估行数: ~90 行
  - 验证点: `python -c compile` 过; `--help` 输出参数说明; 在 Docker amd64 容器内实际起服务并 nc 连通（用 SafeHouse service 做被测目标）
  - 依赖: 步骤 2（命令行接口需与知识条目一致）

步骤 4. seccomp_bpf_decode.py 手解脚本
  - 文件: $SHARED_DIR/scripts/seccomp_bpf_decode.py
  - 预估行数: ~190 行
  - 验证点: compile 过; `--help` 过; 用 SafeHouse 任务目录 main_disas.json 实测——输出 21 条指令且白名单恰为 read/write/close/mmap/mprotect/brk/rt_sigreturn/exit_group 八项
  - 依赖: 无

步骤 5. pwn-methodology.md 方案 D 增补（fork 双进程行 + 片段复用小节）
  - 文件: pwn-methodology.md
  - 预估行数: ~45 行
  - 验证点: 人工读; 叙事词 grep 零命中; 与 §4"自定义加密协议还原"小节为交叉引用而非重复（加密握手细节不重写）
  - 依赖: 无

步骤 6. 收尾自检与 progress 记录
  - 文件: 任务目录 progress.md（本进化任务的执行记录，写入 $ROOT_TASK_DIR/evolve-progress.md）
  - 预估行数: ~30 行
  - 验证点: 全部改动文件过语法检查（.py compile / .md 人工+不可见字节扫描）; 叙事词全文件 grep 清零; 行数统计与 §3 表对账
  - 依赖: 步骤 1-5

## §4 验收标准

**功能验收**:
- A: pwn-methodology.md 含 qemu-user 调试限制条目（触发条件为可观察错误形态）
- B: 按 §5 新条目的 docker 命令 + pwn_lab_server.py 可在干净容器内起可 nc 的靶场（端到端实测）
- C: seccomp_bpf_decode.py 对 SafeHouse main_disas.json 输出 8 项白名单，与已知答案一致
- D: 片段复用小节含副作用表范式与双重加密陷阱条目

**回归验收**:
- pwn-methodology.md 既有章节（§1-§5 原有内容）零删改（除引用衔接）
- 两个新脚本不影响既有 scripts/ 目录任何脚本（零 import 依赖）

**架构验收**:
- 脚本落位 $SHARED_DIR/scripts/（独立 Python 工具，不违反 _base←_utils 依赖方向）
- 知识条目引用一律 $SHARED_DIR 变量路径
- 不改动 agents/ prompt、plugins/、query.py/update.py

## §5 与现有需求文档的关系

- 无直接关联需求文档; 与既有知识文件 pwn-methodology.md 的 §5 工具链"pwntools 调试模式（macOS）"条目为衔接扩展关系（该条目已覆盖 qemu-gdb 单机调试，本需求补 Docker 靶场与 qemu-user 限制，不重复）
