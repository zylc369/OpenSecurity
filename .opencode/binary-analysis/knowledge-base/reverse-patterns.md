# 逆向分析模式速查（Reverse Patterns）

> 逆向 CTF/crackme/保护类目标时按模式查找。反混淆选型见 deobfuscation-selection.md; 反调试见 anti-debugging-bypass.md; VM 分析见 vm-bytecode-reversing.md; 校验结果验证见 verification-patterns.md。

## §1 字节独立变换（byte-wise uniform）检测与逆映射求解

模式: 输出每字节只依赖输入对应字节（无跨字节耦合）。

检测: ①改输入一位→输出只变一位 ②输入填同一字节→输出恒定重复。

求解（免逆向）: 逐值 0..255 填充输入运行 → 记录输出建 256 项映射+逆映射 → 对静态目标字节查逆映射恢复输入。映射非双射时用可打印约束消歧。

## §2 x86-64 反编译器陷阱

**符号扩展（movsx/cdqe）**:
- XOR 只参与低字节: `esi=0xffffffc7` → XOR 用 `esi & 0xff`（0xc7）
- 加法全 32 位回绕: `(r13 + esi) & 0xffffffff`
判别看 MOVZX/MOVSX/CDQE 实际宽度，别信反编译 int 表示。

**循环边界状态错位**: 汇编常 `jmp loop_middle` 首迭代从中段进入，loop_top 的 `mov r13, sbox[a]` 用的是 OLD a——反编译器会把先使用/先更新搞反，复现前对原始汇编写小样验证读取序。

通用: 反编译输出对 movsx/cdqe/循环边界一律抽查原始汇编。

## §3 信号驱动二叉树导航

模式: 程序用信号当二叉树遍历——节点 handler 动态装下一对信号（左右子树），叶 handler 打印退出。

识别: 多个 sigaction(SA_SIGINFO) + sigaltstack() + handler 装子信号/打印退出两类。

分析: LD_PRELOAD interposer 记录 sigaction 安装日志 → DFS 发信号遍历（每层看装了哪 2 个信号; 退出=叶子; 装新对=节点）→ 错叶回溯试兄弟。信号号=边标签，程序自身是树状态机。

## §4 校验逻辑分析三原则（详见 dynamic-analysis.md 策略 0）

比较方向判定（transform(输入)==目标 → 逆算法; transform(目标)==输入 → 免逆向直接应用）/ Memory Dumping（最终比较断点 dump 期望值）/ Decoy 检测（断最终比较，数比较次数取最后）。

## §5 位置索引 XOR 变体

`cipher[i] = plain[i] ^ key[i%k] ^ i`。症状: 已知前缀恢复的"key"逐位 +1 递增。破解: 先 `^i` 剥索引再按重复密钥法（基础版见 crypto-analysis classical-crypto.md §8）。

## §6 SMC 输入即密钥（详见 deobfuscation-selection.md §6）

每输入字符解密下一代码块。破解: 块首已知 opcode（函数序言）已知明文恢复 key=输入字符，逐块推进。函数序言锚点: `f3 0f 1e fa 55 48 89 e5`（endbr64;push rbp;mov rbp,rsp）。

## §7 多线程诱饵 + 信号 handler 藏真逻辑

三线程陷阱: ①诱饵假 AES 后 ud2 故意崩（耗时间）②真 flag 在 SIGSEGV handler 内 MBA 变换③内存清零线程④main rdtsc 检测到调试器**污染输出**（不崩溃给错数据）。

识别: 多 pthread_create + signal(SIGSEGV) + ud2 + rdtsc + SHA-256 IV 常量（0x6a09e667...）当查找表（非哈希——常量伪装）。

解法: 静态提取 handler 的 MBA 变换 + 查找表索引规则 + .rodata 交错数组 → Python 复现全程不跑调试器。输出污染型检测必须静态复现。

## §8 INT3 修补 + coredump 逐字符 oracle

变换输出点 patch 0xCC（printf '\xcc' | dd conv=notrunc）+ ulimit -c unlimited → 逐字符跑 → strings core 找计算结果对比期望。coredump 捕获 INT3 崩溃瞬间完整内存（主动埋点制造受控 oracle，区别于 自然崩溃分析）。适用: 变换复杂但输出点明确可批量重跑。

## §9 信号 handler 链验证 oracle

main 自发 SIGINT N 次，每 handler 验一个字符，通过后 signal() 装下一个 handler（链式）。破解: LD_PRELOAD hook signal()——被调用=当前字符正确（要装下一环），逐字符爆破。与 §3 信号树同族: 树是导航（信号=边），链是验证（signal()=正确性信号），共性是信号 API 间接调用都可 hook 当侧信道。

## §10 四叉树递归图像格式

专有图像格式 = 四叉树: 命令字节 bit3..0 对应四象限（位 1=递归细分/位 0=叶+3 字节 RGB）。调试: 每次 parse 打印递归深度+流偏移——深度不匹配=位序/叶大小错的第一信号（象限位序 4 排列逐一试）。元规律: CTF 专有图像/压缩格式几乎总是 quadtree/LZ77 变体/Huffman 流，识别信号是"短命令字节后跟更多命令或定宽叶数据"的递归结构。

## §11 运行时密钥捕获与静态参数提取双捷径

- **LD_PRELOAD hook 加密函数族**: EVP_CipherInit_ex/EVP_DecryptInit_ex 的 key 参数即密钥，fwrite 落盘后透传原函数。哈希导入/复杂派生**别逆向，让程序自己解析**——hook 它最终调的 OpenSSL/IO/网络函数。key 跨运行确定性。破坏性样本 Docker 隔离+只挂副本
- **侧信道实现参数全在数据段**: cache 侧信道 S-box 也要查找表在内存（如值 0x340=bit1/0x100=bit0），静态提取即可，不需特殊硬件
- 模拟器类目标检查全部 dispatch 分支的非标准 opcode（隐藏函数触发器）

## §12 图像 XOR 掩码平滑度评分

`key=(mask*x-y)&0xFF` 类坐标相关密钥含少量未知参数→逐区域爆破 256 mask，相邻像素差分绝对值之和最小者胜。自然图像平滑度是可靠评分。

## §13 位图可视化两型

- **数学分类器位图**: Newton 收敛性分类复平面坐标→结果按网格打印即 ASCII art。识别: 坐标对输入+迭代函数+点数=尺寸暗示（2600=130×20）+5 像素高字体惯例
- **渲染像素直提**: 程序渲染文本比对像素→.rdata 期望像素 blob（XOR 常量加密）直接提取 reshape 存图→tesseract + 字符集白名单 OCR。共性: flag 在视觉模式里，先想画出来/OCR 出来

## §14 可逆哈希 MITM + VM 未初始化内存

输出侧可逆（fmix64/末尾乘法可逆）→ 正向枚举前半+逆向枚举后半取状态交集: 95^6→2×95^3（43 万倍）。VM 内存未初始化保持全零时依赖内存的混合项退化为常量，先确认内存初值。FNV 变体识别: 0x100000001b3 + 0x9e3779b185ebca87 + fmix64（MurmurHash3 finalizer 0xff51afd7ed558ccd/0xc4ceb9fe1a85ec53）。

## §15 博弈论 + PRNG 反馈环

Bounded Nim: 每堆 Grundy=`pile%(k+1)`，全 XOR 非零=N 位（程序自动赢）/零=P 位（程序 PRNG 走，可能非法步）。**PRNG 状态可能被用户走子更新**（程序自己走不更新）→必须模拟完整反馈闭环。GDB 硬件观察点发现哪些状态变量受用户输入影响。

## §16 内核模块 ioctl 动态探测

.ko 题动态探测 ioctl 比静态逆向 stripped 模块快。读状态命令里常有 **decoy 出口**（status=2 假/1 真）——DFS 标 bad 跨 reset 保留，踩 decoy 后 reset 清 visited 重扫。解算器用最小静态二进制: `gcc -nostdlib -static -Os -fno-builtin -Wl,--gc-sections`+strip，base64 分块过 netcat。

## §17 后门共享库检测

GDB 正常/直跑失败 → ①ldd 查非标准库路径 ②strings|diff 可疑库 vs 系统库（差异=注入）③反汇编被 patch 函数找 getuid/geteuid 条件（suid 在调试器下降权，后门按此切换行为）。

## §18 binfmt 内核模块 RC4 flat binary

register_binfmt 的 load_binary 回调拦截 magic 文件→内存解密→跳入口。RC4 key 常在 **movabs 指令立即数**（非数据段）。解密后是 flat binary 无 ELF 头——从 vm_mmap 取基址，`objdump -b binary -m i386:x86-64 -D` 或 Ghidra Raw Binary 指定基址。

## §19 ELF section header 破坏

运行只需 program headers（PT_LOAD），section header 是分析工具元数据。破坏 e_shoff/e_shnum/e_shstrndx→工具崩但程序跑。修复: `printf '\x00'*8 | dd of=binary bs=1 seek=40 conv=notrunc`（e_shoff 置零）或 readelf -l。flag 常附坏 section 后，magic 字节定位+简单解密。

## §20 多线程 VM channel 分析

线程角色按 channel 读写分类（流水线顺序浮现）; 特定 opcode 断点提常量表; **语义反转检查**（返回 0=有效非零=拦截）; futex 返回值/线程 ID 是意外常量源（unlock_pi 无主 mutex 返 EPERM 参与）。BFS 状态机: 已知前后缀按位逆序枚举+状态集过滤，利用跨位约束省爆破。

## §21 VM trace diffing

opcode 被每步轮换的自修改 dispatch: dispatch 断点逐步 dump `(opcode, stack)` → Python 重放 trace（不碰字节码/不碰 shuffle）→ 两单点差异输入的 trace diff→相同 mul/mod 序列=真实算法。trace 是输入的确定性函数，dispatch 花招只影响编码不影响执行序列。比 §1 五步法重，适合自修改场景。

**纯 opcode trace（无数据值）重建**: 按地址排序+去重恢复代码布局 → 跳转/call/ret 切基本块 → trace 顺序映射分支 taken/not-taken。排序算法类: partition 比较的分支方向泄漏元素两两相对大小——仅凭分支方向恢复输入全序。分支决策本身携带数据信息（无数据值也泄漏）。

## §22 多层自解密 JIT 爆破引擎

N 层限时自解密: oracle 用**结构特征**（对 key 解出的代码含恰好 2 个 call read@plt）非试运行。引擎: mmap 原地址 MAP_FIXED + 解算器编译到 `-Wl,-Ttext-segment=0x10000000` 非重叠 + patch read@plt 注候选 + 层尾 patch ret + fork-per-candidate（COW 免拷贝）+ 大 BSS 放 /dev/shm 父 MAP_SHARED 子 MAP_PRIVATE。性能: Python 2/s → ptrace 119/s → JIT 1000/s → +32 workers 3500/s。陷阱: 层间 call/jmp 都试; BSS 超 MemSiz 多映射; SHA-NI 不依赖 cpuinfo 标示。

## §23 内嵌数据符号直接提取

未 strip + 语义符号名（EMBEDDED_ZIP/ENCRYPTED_*）→ readelf -s 取偏移大小 → PK\x03\x04 定 ZIP 边界 → 已知明文（license 自身）XOR 解。不运行程序不过期检查。

## §24 前缀哈希逐位分解

每前缀独立哈希（无链接）: N digest ↔ N-1 字符。检测: 改末字符只变末行。攻击: 逐位 ×charset 次执行比对对应行——byte-at-a-time 的哈希等价。

## §25 矩阵验证格解法

识别: 分组×系数矩阵==64 位常数 + 解必须可打印 + 爆破空间大 → CVP。SageMath: 格基 [系数|I×1000]，目标减 Σc×mid(79)，LLL+Babai。两阶段: 格解前 N 字符→AES key 解密→VM 字节码 mod 2^32 线性系统（sympy）。见 crypto-analysis lattice-attacks.md 工具梯度。

## §26 决策树函数混淆

200+ 自动生成函数（f315732804 数字名，多项式比较分左右子）: Ghidra headless 批量提 CMP 立即数 + 已知输出格式约束传播级联 + 英文单词消歧。树是 dispatcher 真逻辑在叶——脚本提取不逐函数逆向。

## §27 GF(2^8) 高斯消元

加法=XOR 乘法=0x1b 归约（AES 0x11b 多项式）。gf_mul 双循环 + gf_inv 256 爆破 + 增广消元（行异或 gf_mul(factor,pivot行)）。识别: N² 字节矩阵 + XOR 行操作 + 0x1b/0x11b 常数 + flag 长=√矩阵。原始解向量（pre-AES-GCM）才是 flag。

## §28 ROPfuscation 分析

算法编进 250KB ROP 链（magic_buf 符号）+ mov esp,eax;ret pivot 进入。GDB 脚本链头 4 字节步进读地址逐 gadget x/3i; 重复序列=unrolled 循环; ret imm16 跳大块; 10 万 gadget 压缩到 ~1000 行伪代码。链功能等价普通代码——ret 替代顺序执行而已。

## §29 隐藏执行路径三型

main 看似平凡时查: ①**C++ 析构**——__cxa_atexit 注册的回调 post-main 执行（.init_array 注册/__cxa_finalize 断点 trace）②**死分支**——恒假比较（cmp 常量≠变量）藏真验证，patch 立即数进入（83 7d f4 01→00）; fork+pipe 结构（父写退/子读续）是伴随信号 ③**时间锁**——time()/localtime()+大整数时间戳常数（2012≈1.35B）; faketime LD_PRELOAD 免改系统钟（手写等价: LD_PRELOAD 覆写 time() 返回常量冻结时间种子 PRNG，rand() 同法返回常量——非确定性源全冻结后复杂 VM 变 tractable oracle）; tm_year 自 1900 差/tm_mon 从 0 起。

## §30 单行 Python 布尔电路 Z3

2000+ 分号+walrus 链+混淆 XOR `(x|i)&~(x&i)`+输入当大整数。解: 分号拆分→逐条翻译 Z3（移位访问=LShR(ari,shift)）→断言 result==0→sat 后 to_bytes。秒级。

## §31 滑窗 popcount 差分递推

16 位窗期望 popcount 数组: `bit[i+16] = bit[i] + (expected[i+1]-expected[i])` 差分递推——只爆破初始窗口（popcount==expected[0]，约数千有效值），后续位全确定。识别: 定长窗口汉明重+期望数组（长度=总位-窗口+1）。

## §32 键盘 LED Morse 外设信道

KDSETLED ioctl 闪灯编码 Morse。捕获: strace -e ioctl（免物理观察; 先 patch ptrace 反调试）。短闪 250ms=dit/长 750ms=dah/字符间 3×词间 7×。通则: "人眼观察"的输出都有 syscall 轨迹。

## §33 syscall 副作用内存破坏

rt_sigprocmask 向输出指针写 sigset_t——输入解析传指针到安全变量附近: 特定字符（0x3A-0x40）触发→syscall 清零相邻变量高字节→大值变小值。审计: 字符→syscall 映射例程+指针可控=任意清零原语。

## §34 MFC 事件处理定位

bp SendMessageW 过滤 poi(@esp+8)==0x111（WM_COMMAND 按钮事件）; WM_INITDIALOG(0x110)=OnInitDialog 常藏解密。静态: AFX_MSGMAP_ENTRY 交叉引用枚举全部消息处理。

## §35 VM 顺序密钥链爆破

块输出 key 链式喂下一块（禁整体并行）+ 块内迭代变换不可逆（1000+ 次 xorshift×乘）→ 逐块顺序+块内 OpenMP 爆破（2^24 块/`gcc -O3 -fopenmp` 分钟级）。识别: opcode 整体 XOR 常量混淆出 ASCII 样字节码+CHECK opcode。不可逆变换的设计意图就是爆破。

## §36 BWT 无终结符逆变换

无 '$' 时逆变换产 n 个旋转候选全有效——领域约束过滤（二进制首位 '1'/多轮 XOR 轮次结构/flag 前缀）。

## §37 OpenType 连字隐写

GSUB 表 ligature 映射=所见非所码的密码。fontTools TTFont 读 subtable.ligatures 或 `ttx font.otf` 转 XML grep LigatureSubst。识别: 定制字体+渲染"看起来不对"。

## §38 GLSL shader VM

纹理=内存+VRAM 的图灵完备 VM。GPU 并行每像素每帧只记最后一次写→多次 VRAM 写丢 75%+/STORE 补丁互覆。解: program.png 即字节码，Python 顺序模拟（解密补丁顺序 apply+绘图全保留）。识别: shader 挑战+PNG 程序文件+"渲染花屏"。

## §39 指令计数器当密码状态

专职寄存器逐指令递增参与每字节变换→路径依赖不可解析逆。识别: 手写汇编+只递增寄存器+变换引用它。解: Unicorn 全模拟逐字节爆破（try_byte(prefix,cand) 比对输出前缀）。

## §40 竞态+cdqe 符号扩展组合

TOCTOU 窗口（检查 skill_id 后 sleep）内换技能→读 0xFFFFFFFF 伤害→cdqe 符号扩展成 64 位 -1→INT64_MAX-(-1) 溢出负值秒杀。要素: 检查与使用间窗口+32→64 符号扩展+目标贴类型上限。

## §41 ESP32/Xtensa ROM 符号图

`r2 -a xtensa -b 32` + esp32.rom.ld 当符号 flag（0x40000000=ets_printf 等）→ 数百调用立解析; 应用层对照 esp-idf 公开示例源码（http_server URI handler 模式）。小众架构先找厂商 SDK 链接脚本。

## §42 批量 crackme 自动化

数百同构 crackme: objdump -M intel 解析 add/sub rdi,N + cmp rdi,target 链→逆序撤销（add→减）代数逆推免执行。glob 全部二进制按序输出字符。同构批量题先摸一个定模式再脚本化。

## §43 像素藏码+模拟器库揭示架构

base64 图→RGBA 光栅序拼接=指令流→按库揭示的 ISA 反汇编（UnicornJS=ARM）。多层混淆先找模拟器库名定架构。

## §44 psadbw 绝对差和方程

SSE2 psadbw: 8 组字节 |差| 求和→方程 |a[i]-k[i]| 之和=C 非线性但可打印约束每组 95² 爆破; 多解叠前缀/频率/后续迭代消歧。识别: MBR+xmm+psadbw 循环。

## §45 DNN 逐层求逆

可逆激活（sigmoid⁻¹=-ln(1/x-1)）+方阵权重→从输出逐层 `v = (σ⁻¹(v)-b)·W⁻¹`; 输入预变换（1/x）也要逆。识别: sigmoid/tanh+矩阵乘+.rodata 浮点权重数组+方阵。

## §46 BPF JIT 读原生汇编

反汇编器输出不可读时: `echo 1 > /proc/sys/net/core/bpf_jit_enable` → dmesg grep flen= 读 JIT 后 x64 汇编。识别: SO_ATTACH_FILTER/AF_PACKET/sock_fprog（8 字节 sock_filter 数组）。与 Z3-BPF 约束重建互补。

## §47 纯算术指令级逆推

只含寄存器算术（add/sub/xor/rol/ror）无内存副作用的变换完全可逆: IDAPython trace 非跳转指令 → 逆序+交换逆对（add↔sub/rol↔ror/xor 自逆）→ Keystone 汇编 → Unicorn 以输出值为初值执行读回输入。**PEB 静默换目标陷阱**: BeingDebugged 可能在两个比较目标间选择（不退出只换数据）——trace 前置 0 或识别双分支。

## §48 无 call 函数链

栈上函数指针链表+改 saved RBP（指向下帧）与返回地址（下一函数）→ leave;ret 链式推进无 CALL。破坏反编译 call/ret 平衡。识别: 大量 leave;ret 小块无对应 call + IDA "stack frame is too big"。分析: 逐块 patch 让 IDA 单独处理+人工按链重建执行序。

## §49 父写子代码 strace dump

子进程全 int3 垃圾、父进程 process_vm_writev 逐 trap 前写真指令: `strace -f -e trace=process_vm_writev -e write=all -o trace.log` 一次跑全记录 → 正则提 (addr,bytes) → 生成 IDA patch_byte 脚本落盘真码。通用: tracer 改写 tracee 代码对父的 strace 完全透明（process_vm_writev/POKEDATA/写 /proc/pid/mem 三载体同适用）。

## §50 重叠组约束传播

重叠 3 元组（(1,2,3)(2,3,4)...）每组 SHA-256 循环 XOR 乱序存: 爆破 95³ 全组合匹配密文块 → 块末 2 字符=下块首 2 字符重叠约束连接重建顺序（后缀-前缀拼接，De Bruijn 图路径型）。O(95^n)→O(95³)。

## §51 游戏/框架平台五则

- **Roblox 版本历史**: assetdelivery API（.ROBLOSECURITY cookie）拿旧版 place——最新版常是诱饵; .rbxlbin 的 INST/PROP/PRNT 块解析 Script.Source 跨版本 diff
- **Godot 加密 pck**: KeyDot 从可执行文件提 key → gdsdecomp 解包
- **Electron**: asar extract → find *.node/*.so → JS 层常含明文验证流程 → 逆 native（XOR+旋转链）
- **npm 混淆包**: require 后自动解密——getOwnPropertyNames 枚举隐藏方法（__getFullFlag__/_debug 族）直接调
- **Rust serde_json**: 反编译 Visitor 的 visit_map/visit_seq 层级恢复嵌套 schema; 字段名按序拼接常即 flag

## §52 Verilog 硬件时序倒推

历史移位寄存器 tap 条件（H[0]=1 类+mod 聚合）+ 每操作精确时钟周期数建模（投币 3/选成功 7/失败 5/取消 4-2 从状态机数出）→ 从 tap 要求值倒推各周期动作 → 输入序列。识别: .v + always @(posedge clk) + 门控在历史值上的 case。

## §53 Ruby/Perl polyglot 双约束

=begin..=end（Ruby 块注释）vs =begin..=cut（Perl POD）——同文件两解释器跑不同代码。约束联立: 数学性质定字符集 + 硬编码逆序对计数表定排列（`result.insert(inv[i], remaining.pop(i))` 逆序重建——知 inv 数组反推 permutation 的通用原语）。

## §54 冷门平台三则

- **SGX**: ECALL 分发表（函数指针数组）可逆; 认证协议重实现: ECDH P-256 → CMAC-AES-128 派生 SK → AES-GCM 解密（确定性派生）
- **Glulx**: 字典表 grep 开发者动词（xyzzy/plugh）进 debug 房; 校验是 Z_2^32 线性 → Sage solve_right 直接解
- **EBCDIC**: decode('cp500') 转码; 大写+下划线过滤适配 flag 格式; take-N-skip-N 交错识别
