# ARM64 (AArch64) Pwn 方法论 — 调用约定、ROP 与缓解绕过

> 当目标为 ARM64 架构的 pwn 题（`file` 显示 ARM aarch64）时通过 Read 工具加载。
> ARM64 **逆向**方法论见 `arm64-reverse-methodology.md`（本文件讲漏洞利用）。
> x86_64 pwn 方法论见 `pwn-methodology.md`。

## 触发条件

- `file <binary>` 显示 `ELF 64-bit LSB executable, ARM aarch64`
- 或远程环境为 ARM64（Android/IoT/嵌入式 Linux）

## §1 AAPCS64 调用约定

| 角色 | 寄存器 | 说明 |
|------|--------|------|
| 参数 x0-x7 | 前 8 个整型/指针参数；多余入栈 | |
| 返回值 | x0 | |
| 帧指针 FP | x29 | |
| 链接寄存器 LR | x30 | **存返回地址（不在栈上！）** |
| 栈指针 | sp（=x31） | x31 双角色：sp / xzr（零寄存器） |
| 调用者保存 | x0-x18（除 x29/x30） | 函数内可自由覆盖 |
| 被调用者保存 | x19-x28 | 函数内使用前必须保存恢复 |

## §2 栈帧与返回机制（与 x86 最大差异）

```
序言: stp x29, x30, [sp, #-N]!    // 把 LR(x30) 也压栈，开 N 字节空间
      mov x29, sp                   // 设帧指针

尾言: ldp x29, x30, [sp], #N      // 从栈恢复 LR
      ret                           // ret = 跳到 x30（不是 pop 栈！）
```

**核心差异**：x86 的 `ret` 从栈 pop 返回地址；ARM64 的 `ret` 跳到 **x30 寄存器**。x30 是被 `ldp` 从栈上加载的。所以 **ARM64 ROP 的本质 = 控制栈上的 x30 值**。

## §3 ARM64 ROP

### gadget 形态
```
... ; ldp x29, x30, [sp], #0xN ; ret
```
从 sp 偏移处加载下一个 x30 并返回。每个 gadget 在栈上消耗一个槽位（被加载的 x30 值）。

溢出布局：
```
[padding 到 saved x29/x30][gadget1 地址(→新 x30)][...][gadget2 地址]...
```

### gadget 搜索
```bash
ROPgadget --binary <binary> --arch arm64 | grep "ldp x29, x30"
ropper --file <binary> --arch AARCH64 --search "ldp x29, x30"
```
**gadget 密度低**：不像 x86 "ret(0xc3)" 字节到处都是，ARM64 的 gadget 较少。

### ret2csu（通用 ROP 链）
libc 的 `__libc_csu_init` 风格函数常含：
```asm
ldp x19, x20, [sp, #0x10]
ldp x21, x22, [sp, #0x20]
ldp x23, x24, [sp, #0x30]
ldp x29, x30, [sp], #0x40
ret
```
从栈控 x19-x24 + x30，再配一个把寄存器搬进 x0 的 gadget（或 `blr x3` 类）即可控参数。

### one_gadget 不支持 ARM64
替代方案：ROP 调 `system("/bin/sh")` 或 ORW 链。
```python
context.update(arch='aarch64', os='linux')
# shellcraft 支持 aarch64
sc = shellcraft.aarch64.linux.sh()
```

## §4 PAC / BTI / MTE 绕过

| 缓解 | 机制 | 影响 | 绕过 |
|------|------|------|------|
| **PAC** (ARMv8.3) | 序言 `paciasp` 签名 x30，尾言 `autiasp` 验签 | 栈上 x30 被签名，覆盖任意值→验证失败崩溃 | ① 重用已签名指针（泄漏合法签好的 LR）② **最稳：data-oriented 攻击（改 modprobe_path/数据指针，不碰控制流）** |
| **BTI** (ARMv8.5) | 间接跳转目标须 `bti c/j/jc`，否则 SIGILL | gadget 入口须是 bti，缩小 gadget 池 | 不致命；纯 ret 链在无 PAC 时仍可用 |
| **MTE** (ARMv8.5) | 每 16 字节一个 4-bit 染色 tag | OOB/UAF 命中正确 tag 概率仅 1/16→SIGSEGV | 概率爆破（每试 1/16）或泄漏 tag 位 |

> **实操结论**：ARM64 现代 pwn **优先走 data-oriented**（覆盖数据指针/落点），其次才是"重用已签名指针 + ret 链"。纯栈溢出打 ROP 在 PAC 开启后基本走不通。

## §5 pwntools ARM64 速查

```python
context.update(arch='aarch64', os='linux')
# shellcode
sc = shellcraft.aarch64.linux.sh()       # 反弹 shell
sc = shellcraft.aarch64.linux.cat('/flag') # 读 flag
# ORW
sc  = shellcraft.aarch64.pushstr('/flag')
sc += shellcraft.aarch64.linux.open('sp', 0)
sc += shellcraft.aarch64.linux.read('ret', 'sp', 0x100)
sc += shellcraft.aarch64.linux.write(1, 'sp', 0x100)
```

## §6 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — 标准 pwn 流程、mitigations 速查、卡点突破（x86 视角）
- `$SHARED_DIR/knowledge-base/pwn-heap-methodology.md` — 堆利用（架构无关）
- `$SHARED_DIR/knowledge-base/arm64-reverse-methodology.md` — ARM64 逆向方法论
