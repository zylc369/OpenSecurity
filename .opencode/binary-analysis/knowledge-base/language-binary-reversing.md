# 语言特定二进制逆向（Language-Specific Binary Reversing）

> 识别目标语言/运行时后按本文对应节处理。混淆处理见 deobfuscation-selection.md; VM 见 vm-bytecode-reversing.md; Go/Rust/Swift/Kotlin/C++ 系见 §1 编译器指纹与 deobfuscation-selection §5 符号恢复。

## §0 编译器识别指纹

strings/符号识别编译器:
| 编译器 | 特征 |
|---|---|
| GCC | `__gmon_start__`, `__libc_csu_init` |
| MSVC | `_mainCRTStartup` |
| MinGW | `mingw_initltsdrot_force` |
| Go | `go.buildid`, `main.main`, `runtime.main` |

## §1 Python 字节码

dis.dis 五 tip: LOAD_CONST+COMPARE_OP=期望值 / BINARY_XOR=变换 / BUILD_TUPLE=目标数组 / FOR_ITER+BINARY_SUBSCR=遍历输入 / CALL_FUNCTION ord=字符转整数。

opcode 重映射恢复: 找被改 opcode.pyc → diff 标准 → {new:original} 映射 → patch 回去再反编译。捷径: 挑战自带定制解释器时把 uncompyle6 装进它的环境。

版本: uncompyle6≤3.8; 3.9+ 用 pycdc; alpha 版 opcode 不同需编译对应版本（pyc 跳 16 字节头 marshal.loads）。

## §2 Pyarmor 8/9 静态脱壳

Lil-House/Pyarmor-Static-Unpack-1shot; 签名 `PY`+六位数字（≤7 的 PYARMOR 格式不支持）。`shot.py <scripts目录>`（需配套 pyarmor_runtime）; 反汇编输出为准，实验性反编译仅参考。PyInstaller 先解包（`python pyinstxtractor.py binary.exe` → `binary.exe_extracted/`）。

## §3 隐蔽代码载体

- **DOS stub**: PE 头前的 stub 异常大=藏 16 位 DOS 程序; DOSBox/IDA 16 位加载; 找 int 16h
- **UEFI**: `7z x` 解固件 + `file | grep PE32+`; 重点 DXE 驱动与 boot services
- **Makefile**: $(eval) 递归图灵完备; 转移表解码后查 bbchallenge.org 忙海狸库; make -n/-d 调试

## §4 Unity IL2CPP

PC=GameAssembly.dll / Android=libil2cpp.so。Il2CppDumper 恢复符号; 失败=global-metadata.dat 加密→追加载路径找解密。密钥派生: `SHA256(companyName + "\n" + productName)`。

## §5 HarmonyOS HAP/ABC

.hap 是 ZIP; .abc 用 abc-decompiler（jadx-dev-all.jar）。CLI 必须 `java -cp ... jadx.cli.JdxCLI -m simple --log-level ERROR -d out modules.abc`（java -jar 会进 GUI）; simple 模式避免 SSA 失败; 报错≠失败看 sources/。

## §6 Brainfuck（JIT/GC/tape 变体见 vm-bytecode-reversing.md）

- 静态提取: `,` 后 `+` 计数=期望 ASCII（`-`为 256-n; `[-]` 清格分段独立）
- 读计数 oracle: 正确字符消耗更多输入——统计 `,` 执行次数逐位爆破
- 惯用语检测: 相等比较 `<[-<->] +<[>-<[-]]>[-<+>]` 命中时 tape[ptr-2]=输入 tape[ptr-1]=期望
- 插桩变体（10K+ 指令大程序）: 自写解释器带 tape 观察跑探针输入，找"错误计数 cell"（每错一字符 +1 的格子）——逐位换字符看该 cell 是否不增即正确位; ~40 位×95 字符=3800 次运行分钟级

## §7 Transpile 到 C + 覆盖率侧信道

Transpile 到 C 后 `-O3` 自动简化; **LLVM IR 变体**: 自定义 VM 字节码经自制反汇编器逐 opcode 映射 LLVM IR（`INC reg → %reg = add i32 %reg, 1`）→ `opt -O3 -S` 内联+常量折叠（1300 行→约 150 行案例）→ 反编译揭示算法。

VM 字节码转 C 语句 + `gcc -O3`——常量折叠/死代码消除自动简化。数据依赖分支加密经 XDebug coverage JSON 泄漏中间值集合（branchless 实现是防御也是弱点识别信号）。

## §8 聚合效应爆破 + 非双射替换

鸡蛋依赖（偏移依赖未知原始值）→ 爆破聚合效应 S mod 256（256 种）+自洽验证，勿爆指数状态。非双射 S-box（len(set)<len 检测）逆向多候选四消歧: 已知前缀/侧信道/可打印/重加密验证。

## §9 FRACTRAN 与 Erlang BEAM

FRACTRAN: 交换分子分母逆运行; 素数因子分解编码（指数=ASCII）。BEAM: `beam_disasm:file` 反汇编; NFA 型（select_val+send 消息队列）提取转移表→积自动机→BFS 最短接受串→DFS 字典序最小。

## §10 Go 反编译模式（符号恢复见 deobfuscation-selection §5）

布局: GoString{ptr,len} 16B 非零终止 / GoSlice{ptr,len,cap} 24B / Interface 16B / map→hmap / chan→hchan。(ptr,int64)=字符串、(ptr,i64,i64)=slice。runtime 函数族: newproc=go / chansend1 / chanrecv1 / selectgo / closechan / deferproc+deferreturn（LIFO）/ concatstrings。embed.FS: grep "embed"+文件签名。`go version -m` 提取 -ldflags -X 注入值; 等长替换 patch（backing array 定长）。

## §11 Rust 反编译模式

Option/Result={判别式,value}; String 24B 堆/&str 16B。**panic 金矿**: `strings | grep "panicked at"` 含路径行号（release 也保留）。**xmmword 提取**: 字面量缓冲 16B xmmword 在 .rodata，`mov reg, xmmword [rip+off]` 定位后逐 dword 逆混淆 dump。单态化=相似函数成群。rustfilt/cargo-bloat。

## §12 Kotlin 协程状态机

invokeSuspend 内 switch(this.label) 每个 suspend 点一状态——追 label 理解异步流。特征: $Companion/copy()+componentN()/Intrinsics.checkNotNull/tableswitch(when)。jadx 最佳; Native 版 konan 字符串+ARC 无反射。

## §13 Haskell 两路

识别: libHSbase/hs_main/Z-encoding（zd=.）。路线 1: hsdecomp 反编译 closure; 失败 monkey-patch 同版本 GHC 编译 print targetClosure 提取 .text patch 进去强制求值。路线 2: .cmm 直接读; 指数递归串用 size memoization+段边界二分定位（勿物化 O(2^n)）。

## §14 Rust 沙箱逃逸两型

①**lifetime soundness bug**: 钉死版本的 Rust 沙箱+禁 unsafe→查该版本后修复的 soundness issue（如 #25860 变异性 bug 把引用扩 'static→安全代码 UAF）。②**#[no_mangle] 静态链接遮蔽**: 用户 crate 与 harness 同二进制静态链接，extern "C" 同名函数链接期遮蔽 libc 符号（prctl 返 0→seccomp 永不装）。防御: libc::syscall 直连 / -Wl,-Bsymbolic。

## §15 Nuitka 模块 stub 注入

Nuitka/PyInstaller onefile 运行时仍走 sys.path（CWD 优先）——旁放假模块（strings 挑名）+ __getattr__ 万能 stub 记录全部调用，免反编译拿算法。与 Pyarmor 静态脱壳（§2）互补。

## §16 Go 双协程 VM + Cosmopolitan APE

双协程 VM: 两 goroutine 经 channel 产消（A 执行 B 验证）。hchan: +0x00 qcount/+0x10 buf/+0x28 sendx/+0x38 recvq。GDB source runtime-gdb.py → info goroutines / goroutine N bt 映射双栈。
Cosmopolitan APE: polyglot（ELF+PE+Mach-O 同时合法）; 按 ELF 加载忽略 stub; 入口 _start→__init_cosmo 检测 OS 内存 patch; __sys_* 包装抽象 syscall。

## §17 D 语言与 C++ 布局

D: _D 前缀+长度前缀 mangling; Phobos _D3std; 模板变体函数成群（逆序逐个撤销双 XOR）。C++: string SSO ≤15 内联 {ptr,size,union{cap,buf[16]}}; vector 三指针; map 红黑树节点; vtable [typeinfo,dtor,methods]; c++filt _ZTI 揭 RTTI。

## §18 .NET NativeAOT 与 LLVM IR

**NativeAOT**: 无 IL 纯原生代码，dnSpy/ILSpy/dotPeek 全部无效。识别锚点: `System.Private.CoreLib` 字符串（运行时内嵌）; 类型元数据被重组（非标准 #Strings/#US 堆，不能按常规元数据表解析）; 字符串=长度前缀 UTF-16（非 null 终止）。分析路径: 按 native 流程走（IDA/Ghidra），导出表/字符串交叉引用切入。

**LLVM IR (.ll)**: 直接编译运行动态验证（静态读 IR 慢且易错）:
```bash
llc task.ll --x86-asm-syntax=intel   # IR → x86 汇编（Intel 语法）
gcc -c task.s -o file.o && gcc file.o -o file
```
