# 自定义 VM 与字节码逆向 — 识别、ISA 重建、迷宫与保护器

> 二进制内嵌自定义虚拟机/字节码解释器/迷宫类题目时加载。
> 商业壳（VMProtect/Themida）的脱壳流程见 `packer-handling.md`; 符号执行配合见 `angr-symbolic-execution.md`。

## 触发条件

- 反编译看到 `while(1) switch(bytecode[pc++])` 或函数指针表分发
- 题目数据段有大段"非指令"数据被逐字节消费
- 方向输入 + 2D 网格（迷宫）
- movfuscator（全 mov）/Tigress/VMProtect 保护目标

## §1 识别与五步方法论

dispatcher 三形态: switch 型（CTF 常见）/ 表驱动 `handlers[op](&ctx)` / if 链。辅助信号: 高圈复杂度单函数、数据缓冲逐字节 xref。
五步: 找 dispatcher → 映射 opcode 五属性（值/操作/操作数字节/类型/副作用）→ 提取 bytecode → 写反汇编器（`OPCODES={op:(mnemonic,operand_bytes)}` 字典循环）→ 分析 check 逻辑（通常 XOR/ADD 变换比对常量表）→ 手动逆或 Z3。
输入空间小 → Unicorn 爆破; 嵌套 VM → 逐层提取或符号执行穿透。

## §2 ISA 模式

- **栈式**（类 JVM）: PUSH/POP/ADD/SUB/MUL/XOR/CMP（栈顶二元）/JMP/JZ/PRINT/READ/HALT——看栈效果命名
- **寄存器式**（类 x86）: `01 RR II II`(MOV imm16) / `0X R1 R2`(二元运算) / `0X AA AA`(跳转) / `0X RR AA`(LOAD) / SYSCALL/HALT——看编码格式
- **BF 三分析技巧**（详见 language-binary-reversing.md §6）: `,` 后 `+` 计数静态提取期望 ASCII / 读计数 oracle（正确字符消耗更多输入）/ 相等比较惯用语 `<[-<->] +<[>-<[-]]>[-<+>]` 命中时直接捞 tape 操作数。
- **Brainfuck 族**: `>` `<` `+` `-` `.` `,` `[` `]` 八指令锚点。**无界 tape 攻击面**: 解释器不检查磁带边界时（BF/Pikalang 类），指针从已知缓冲起点 `<<<<`/`>>>>` 移到 GOT 条目逐字节覆写 system——tape 指针即相对缓冲基址的任意读写原语。**BF JIT 变体**: 括号栈配对的 JIT 中不配对 `]` 弹出 prologue 存的 RWX tape 地址——`ret` 直跳 tape 执行 `+`/`-` 写入的 shellcode（值>127 用 `-` 省操作数）。**VM GC 共享引用 UAF**: slice/view 别名共享 slab，销毁别名+GC 释放共享块而父 buffer 仍引用——同 size class 的函数对象复用后经父 buffer 覆写代码指针; "只改长度不写数据"的 API 是边界检查盲区; 显式 GC 指令使释放确定性

## §2a 黑盒 fuzzing 发现指令集

dispatcher 静态分析过复杂（混淆/规模大）时的替代路线:
1. **测对齐**: 按多位宽（6-11 bit）dump 字节码找重复模式定 opcode 边界（变长指令集多位宽试）
2. **单指令 fuzz**: 一次一条观察寄存器/内存变化; 归约最小程序（每个效果找最短触发）
3. **构建 ISA**: 变长示例 `000=jmp 001=jmpz 010=call 011=label 1000=loadram 1001=saveram 110=loadi 11100=shl 11101=shr 111100=not 111101=and 111110=or 111111=setif`
4. 写汇编器/反汇编器工具化
5. **合成缺失原语**: XOR = `(a|b) & ~(a&b)`; ADD = 全加器进位链（逐位 sum=xor_(xor_(ai,bi),carry); carry=(ai&bi)|(carry&xor_(ai,bi))）——仅 AND/OR/NOT 可实现 XTEA 级算法。自修改 dispatch（opcode 每步轮换）场景改用 trace diffing（见 reverse-patterns.md §21）

**宿主态实时观察**: VM 的 sp/ip/stack/heap 都是宿主栈变量——r2 `f sp @ rbp-0x160` 等 flag 标记后进 `V!` 面板模式，四面板同屏（`?v [ip]; pd 1 @ [ip]` 下一 VM 指令 / `pxQ @ sp` 栈 / `pxQ @ heap` / `afvd` 变量），dispatch 分支处条件断点+`ds` 单步看每拍状态。宿主代码静态反编译不友好时此路比静态快; `e io.cache=true` 免破坏性 patch opcode。

## §3 迷宫题

识别: 方向输入 + 2D 数组 + x,y 追踪 + 终点判赢。
提取: 按 WIDTH/HEIGHT 切网格，值分布猜编码（最多=墙/路，唯一值=起终）。
求解: BFS 返回方向串（deque + visited）。
输出转换——方向编码五变体: WASD | UDLR | 方向键扫描码（↑0x48 ↓0x50 ←0x4B →0x4D）| 数字 1-4 | hex opcode。

## §4 商业保护器

**VMProtect 六步**: 搜 pushad/pushfd 入口 → VM context 结构 → handler 表（去不透明谓词）→ 逐 handler 记语义 → Pin/DynamoRIO 指令级 trace → 重建逻辑。
**Tigress 五特性**: split handlers / 嵌套 VM / 加密 bytecode（fetch 前动态解密）/ 多态 handlers。
**难度表**: VMProtect·Themida 高（CISC 大 handler 集）/ Tigress 中高 / movfuscator 中（全 mov 无 dispatcher 特征）/ CTF 自制低中。
工具: Pin/DynamoRIO（trace）/ REVEN（录制回放）/ Miasm（IR 提升）/ Sleigh（复用规范）。

**补集**: VMProtect 识别锚点 .vmp0/.vmp1 节+熵>7.5+push/pop 密集入口+mutation engine（同 opcode 每 build handler 不同，脚本不可跨版本复用）; devirt 工具 VMPAttack（IDA 自动识别 handler）/NoVmp（VTIL）。**CTF 策略: 操作追踪优于完全 devirtualize**——Frida hook dispatch 记 handler 索引+栈状态，聚焦 VM 内对输入的操作（比较/加密）即可，全还原很少必要。Themida dump（AI 无头路径）: Frida 反反调试脚本跑起进程 → 内存特征定位 OEP（入口节熵降+API 调用模式）→ Frida 读全内存段 dump → 自写脚本重建导入表（脱壳后 IAT 重建的自动化: 扫 dump 中 IAT 指针回填名称）→ 修复后按 normal 分析（识别 .themida/.winlice 节+内核级反调试三合一）。

## §5 Ghidra Sleigh 处理器

复现型 VM 写 .slspec（define space/register/token + `:指令 is 模式 { P-code 语义 }`）→ Ghidra 原生反汇编+反编译 bytecode。单次题目用 Python 反汇编器更快。

## §6 关联文件

- `$SHARED_DIR/knowledge-base/packer-handling.md` — 壳处理总策略
- `$SHARED_DIR/knowledge-base/angr-symbolic-execution.md` — VM 题的符号执行/Unicorn 爆破
- `$SHARED_DIR/knowledge-base/deobfuscation-selection.md` — 混淆处理选型

## §7 格式串 %hhn 虚拟机

VM 用 printf 格式串实现: %hhn 把已打印字符数（mod 256）写入指针字节，`%Nc%hhn` 序列=任意字节内存写原语。反编译四步:
1. 指令类型统计: `sed -e 's/[[:digit:]]\+/1/g' program.fs | sort | uniq -c | sort -nr`（数字归一化后 uniq——任何"少量模式×大量参数"序列通用）
2. 写反编译器: 每 `%N...%hhn` 对=一次内存写（地址来自参数指针槽，值来自计数 N）
3. 识别算法: 通常字节线性方程组，地址映射符号变量
4. Z3 求解（可打印约束+写序列约束）
