# 需求: 信号驱动 VM 观测与求解知识进化（A+B+C）

> 状态: 已实施+补测+评审修复闭环（2026-10-03。初测正常路径→补测 5 边界（修 2 真 bug）→ code review 揪出 3 真 bug（每信号槽交叉分发/无 SA_SIGINFO 防护/oldact 泄露致递归）+3 次要问题（pread 安全读/信号 32-33 排除/stdio 预分配）→ v2 全修，9 模式 22 断言全过; 回归: scripts/sigwrap_tracer_test.c + run_sigwrap_tests.sh）→ 终审再修 3 项（GPTR 裸解引用崩→safe_read / 多线程 fopen 竞态→constructor 预初始化 / SIGWRAP_MAX 运行期参数归 env_late）+ 补 2 模式（lowaddr/altstack），终态 11 模式 27 断言全过
> 来源复盘: 2026-10-02 IntMod 信号驱动 VM 逆向任务（Unicorn 全模拟泥潭 15+ 轮、Z3 三连败、LD_PRELOAD 方案现场发明）
> 产出策略: 把本次高成本买来的三项能力（unicorn 已知限制判定、信号包装器观测、线性哈希代数求解）沉淀为下次第 1 轮即可命中的知识/工具

---

## §1 背景与目标

### 痛点（数据支撑）

| 痛点 | 浪费 | 根因（结构层缺失） |
|------|------|-------------------|
| Unicorn 全程序模拟信号驱动 VM 失败（TF 不触发/SMC 页 TB 不续/until=0 三坑连环调试） | ~15 轮 | unicorn-templates.md 无 2.1.2 已知限制清单、无"单函数调用 vs 全程序模拟"选择判据 |
| LD_PRELOAD 信号包装器方案晚期才出现 | 数轮+发明成本 | 知识库无该观测模式；scripts/ 无可复用模板 |
| Z3 求解 3 次 unknown（实际方程权重方向反了） | 3 轮 | 无"mod 素数线性哈希识别 → 高斯消元优先 + 已知输入自检"判据 |

### 目标

1. 同类任务（信号驱动 VM / 信号混淆二进制）开工第一轮即可判定模拟路线可行性，不再陷入 unicorn 泥潭
2. 信号包装器观测从"现场发明 ~150 行 C"变为"取模板改环境变量"
3. 线性哈希类校验直接走代数求解路径，权重方向错误被自检纪律拦截

---

## §2 技术方案

### 改动文件清单

| 文件 | 改动 | 类型 |
|------|------|------|
| `$SHARED_DIR/knowledge-base/unicorn-templates.md` | 增补 §Unicorn 2.1.2 已知限制 + §模拟模式选择判据 | 知识增补 |
| `$SHARED_DIR/knowledge-base/vm-bytecode-reversing.md` | 增补 §dispatcher 第四形态: 信号驱动 | 知识增补 |
| `$SHARED_DIR/scripts/sigwrap_tracer.c` | 新建通用信号包装器模板 | 新工具 |
| `$SHARED_DIR/knowledge-base/reverse-patterns.md` | 增补 §mod 素数线性哈希识别与求解 | 知识增补 |
| `$SHARED_DIR/knowledge-base/dynamic-analysis.md` | LD_PRELOAD 小节加 1-2 行交叉引用 | 知识增补 |
| `$OPENCODE_ROOT/agents/binary-analysis.md` | vm-bytecode-reversing 索引触发行加导入表形态键（1 行） | Agent prompt 微调（高风险类，需验证） |

### 内容设计

**A. unicorn-templates.md 增补**（追加到"常见陷阱"章节之后）:

1. **§Unicorn 2.1.2 已知限制（x86-64）**——四条实测限制:
   - `EFLAGS.TF` 经 `reg_write` 写入后**不产生单步 trap**。TF 单步需手动模拟: INTR hook 对 intno=1 递送信号 + 进入 handler 前清 CPU 的 TF 位 + sigreturn 恢复时按 ucontext EFL 的 TF 重挂; 且 INTR(1) 触发时 unicorn 报告的 EFLAGS 已清 TF，构造 ucontext 时必须显式回填 TF 位（内核语义: TF 保留在信号帧）
   - **SMC 页 TB 不自动续**: 被 hook 监听写操作的 RWX 页（自修改槽）执行一个翻译块后 `emu_start` 返回，需外层 while 重启循环驱动; `ctl_remove_cache` 只能保证重翻译，不能保证连续执行
   - `emu_start(begin, 0)` 的 until=0 存在提前停止路径，until 一律传具体地址（如 RET 哨兵）
   - **综合判定**: 信号递送（手动构造 ucontext/sigreturn）+ TF 单步 + SMC 三者叠加的全程序模拟不可行——遇信号驱动 VM 直接转 LD_PRELOAD 原生观测（见 vm-bytecode-reversing §信号驱动）或 Unicorn 单函数调用
2. **§模拟模式选择判据**——表格: 纯计算函数（无 libc 依赖）→ 单函数调用（映射 .text+栈+数据区，设 rdi/rsi/rdx，RET 哨兵压栈）; 需要 libc → PLT hook 全程序（无信号/无 SMC 时可行）; 含信号 handler / TF 单步 / 自修改 RWX → 放弃模拟转原生观测

**B. vm-bytecode-reversing.md 增补 §dispatcher 第四形态: 信号驱动**:

- **识别形态**: 导入表仅 `sigaction/sigaltstack/mmap` 等信号与内存 API（无 printf 族输入）+ 主循环出现 `int3/ud2/除零` 三 trap 轮转（mode 字段切换）+ RWX mmap 区 16 字节槽
- **执行机制**: handler(SA_SIGINFO) 作 VM dispatcher; TF 单步执行型——handler 生成 3 字节真 x86 指令写槽、置 EFLAGS.TF、改 ucontext RIP 指向槽，每条指令 trap 一次; 寄存器文件 = ucontext gregs（R8-R12 作数据寄存器、R13/R14 作辅助/verdict）
- **观测手段**: LD_PRELOAD 信号处理器包装器——模板 `$SHARED_DIR/scripts/sigwrap_tracer.c`，Docker 原生环境可用（qemu-user 下 ucontext 改 RIP 会段错误、Docker Desktop qemu 模拟容器无 ptrace 故 gdb 亦不可用——环境判定矩阵）
- **状态化解密指令流**: 指令块解密密钥/种子随 vmctx（PC/hash/expected）逐条演变时，静态批量解密不可行; 解法: 信号包装器 dump 每 trap 的 vmctx → Unicorn 单函数调用原解码函数逐条解码
- **verdict 掩码**: `R14 |= imm ^ diff` 型校验，全过 ⟺ 每组 diff == imm; 求解见 reverse-patterns §mod 素数线性哈希

**C. sigwrap_tracer.c 通用模板**（~115 行 C）:

- 包装 `sigaction`: 捕获目标程序注册的 handler，替换为 wrapper（记录原 handler，调用前后各 dump 一次）
- 环境变量: `SIGWRAP_LOG`（输出文件，默认 /tmp/sigwrap.log）、`SIGWRAP_GPTR`（全局指针地址 hex——每 trap 追加 dump 其指向结构）、`SIGWRAP_STATE_OFF`（该结构内 state 指针偏移）、`SIGWRAP_DSTATE`（dump state 前 N 字节）、`SIGWRAP_MAX`（trap 上限，默认 3000000）
- 每 trap 固定输出: `T#<n> s=<sig> rip=<rip> code=<rip 前 8 后 8 字节，经 /proc/self/mem pread 安全读，未映射页输出 ?> r8..r15/rdi/rsi/rax/rbx/rcx/rdx/rbp/rsp efl`; handler 返回后输出 `-> rip=<new> efl=<new>`（观察 handler 改写 RIP/EFL 的效果，含 TF 置位）
- 平台限定 x86-64 Linux（依赖 ucontext gregs/REG_* 宏，其他架构不编译）; 无 sa_sigaction 或非 SA_SIGINFO 注册直接透传

**D. reverse-patterns.md 增补 §mod 素数线性哈希识别与求解**:

- 识别: 校验函数含 `% 小素数`（65521=Adler 系、65537、10007 等）且递推形如 `h = (b + r*h) % P` → 线性: `h = Σ b[i]·r^i`
- 权重方向纪律: 逆序递推（i 从 n-1 递减到 0）时 b[0] 权重 r^0=1、b[n-1] 权重 r^(n-1); 方向写反方程组整体镜像，解出"寄存器逆序"排列的假解
- 自检纪律（先于任何求解器）: 取一个已知输入跑原程序/原函数拿 k 组真值，代入方程组须 n/n 全过——不过则先修权重方向
- 求解: 同一 N 字节被 k 组 (r, target) 校验 → k×N mod P 线性方程组 → 高斯消元（P 素数，除法用模逆 pow(a,-1,P)）; 解出字节全部 < 256 是正确性强信号; 再逆推前置混合链（乘法常数为奇时用 `pow(imm, -1, 1<<64)` 求模 2^64 逆元，add→sub、rol→ror、xor/swap 自逆）
- 优先级判据: 结构线性 → 先代数后求解器; 仅当混合非线性（无代数结构）且约束少时才上 Z3/angr

**E. dynamic-analysis.md 交叉引用**: LD_PRELOAD 相关小节加一行——信号处理器级观测（wrap sigaction）见 vm-bytecode-reversing §信号驱动 + sigwrap_tracer.c

**F. agent prompt 索引触发行微调**（1 行）: `vm-bytecode-reversing.md` 触发条件追加"导入表仅 sigaction/sigaltstack 等信号 API"——让"还没识别出是 VM"的阶段即可命中

### 架构影响

- 全部为 knowledge-base 增补 + scripts/ 新增 + agent prompt 单行微调，无代码依赖方向变化、无 Plugin 改动
- sigwrap_tracer.c 为独立 C 模板，不进入 _base/_utils 依赖链

---

## §3 实现规范

- 知识内容遵守 knowledge-writing-guide: 场景驱动三问、具体值、自包含、`$SHARED_DIR` 变量引用、无来源叙事词（规则 8 零容忍）
- 编辑 >300 行文件遵守 long-document-editing.md（unicorn-templates 281 行、vm-bytecode-reversing 83 行、reverse-patterns 271 行、dynamic-analysis 293 行——均用 Edit 定点插入，不全量重写）
- C 模板可移植: 无 GNU 扩展依赖过重（_GNU_SOURCE + dlsym RTLD_NEXT 为必要最小集）

### §3.1 实施步骤拆分

**步骤 1. unicorn-templates.md 增补已知限制与选择判据**
- 文件: `$SHARED_DIR/knowledge-base/unicorn-templates.md`
- 预估行数: +55
- 验证点: ①人工通读自包含 ②`grep -c "TF\|SMC\|until"` ≥ 3 ③不可见字节扫描干净 ④触发情境键为代码形态
- 依赖: 无

**步骤 2. vm-bytecode-reversing.md 增补信号驱动形态章节**
- 文件: `$SHARED_DIR/knowledge-base/vm-bytecode-reversing.md`
- 预估行数: +60
- 验证点: ①自包含通读 ②含识别形态（导入表 sigaction 极简 + 三 trap 轮转）与环境判定矩阵 ③引用 sigwrap_tracer.c 用 `$SHARED_DIR` 路径 ④SIGFPE 计数侧信道等反调试视角内容引用 anti-debugging-bypass.md 而非重写 ⑤无叙事词
- 依赖: 无

**步骤 3. sigwrap_tracer.c 新建**
- 文件: `$SHARED_DIR/scripts/sigwrap_tracer.c`
- 预估行数: ~115
- 验证点: ①Docker 内 `gcc -shared -fPIC -O2` 编译零 error ②端到端: 现场构造最小信号测试程序（sigaction 注册 SIGTRAP 的 SA_SIGINFO handler + 触发 int3，~25 行 C）作载体，LD_PRELOAD 运行后 T#1 行含 sig/rip/gregs、`->` after 行存在 ③环境变量开关生效（SIGWRAP_GPTR 配置时出现 state dump 行）
- 依赖: 无（测试载体用现成 ELF 即可）

**步骤 4. reverse-patterns.md 增补 + dynamic-analysis.md 交叉引用**
- 文件: `$SHARED_DIR/knowledge-base/reverse-patterns.md`（+28）、`dynamic-analysis.md`（+2）
- 预估行数: +30
- 验证点: ①自包含 ②含权重方向纪律与自检纪律 ③引用 §27 GF(2^8) 不重复（场景区分: GF(2^8) 是 RS 擦除、本条是 mod 素数线性哈希校验）④无叙事词
- 依赖: 无

**步骤 5. agent prompt 索引触发行微调 + 知识库索引核对**
- 文件: `$OPENCODE_ROOT/agents/binary-analysis.md`（1 行）
- 预估行数: 改 1 行（净 0）
- 验证点: ①`grep -n "vm-bytecode" agents/binary-analysis.md` 触发行含 sigaction 形态键 ②展开行数仍 < 450（当前 276）③其余索引行不动
- 依赖: 步骤 2（知识存在后触发行才有意义）

---

## §4 验收标准

### 功能验收
- [ ] unicorn-templates.md: 四条限制 + 选择判据表齐全，TF 手动模拟三步骤完整（递送/清位/重挂）
- [ ] vm-bytecode-reversing.md: 第四形态含识别/机制/观测/状态化解码/求解引用五要素
- [ ] sigwrap_tracer.c: Docker 编译通过 + 实测 trap 行输出正确
- [ ] reverse-patterns.md: 权重方向 + 自检纪律 + 高斯消元 + 逆推（含模 2^64 逆元）四要素
- [ ] agent prompt 触发行更新

### 回归验收
- [ ] 四个知识文件原有内容零破坏（diff 只见增补）
- [ ] 现有 scripts/ 脚本不受影响（纯新增）
- [ ] agent prompt 展开行数 < 450

### 架构验收
- [ ] 无文件散落到架构树之外; 脚本落 scripts/、知识落 knowledge-base/ ✓ 归属规则
- [ ] 依赖方向无变化; sigwrap_tracer.c 独立
- [ ] 跨文件引用全部 `$SHARED_DIR` 变量

---

## §5 与现有需求文档的关系

- requirements/evolve/ 当前无待实施文档，本需求为首份，无冲突
- 与记忆库 id 7515（IntMod 解法流水线）互补: 记忆库供检索命中，本需求把可执行部分（模板代码/判据/纪律）固化到 MD 知识库与 scripts/——MD 为权威全文
