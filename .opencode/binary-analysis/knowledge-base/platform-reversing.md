# 平台特定逆向（Platform-Specific Reversing）

> IoT 固件/内核模块/游戏引擎/汽车 CAN/U-Boot/硬件/WASM 等平台主题。macOS/iOS 见 mobile-analysis mobile-patterns.md; Windows .sys 见 kernel-driver-analysis.md; ARM64 见 arm64-reverse-methodology.md。

## §1 IoT 固件全链

**硬件四通道**: UART（串口 root shell，115200，4 针万用表认）/ JTAG（OpenOCD/J-Link，JTAGulator 自动探测）/ SPI（flashrom/CH341A 直读 8 针 SOIC）/ eMMC（读卡器/焊测试点）。

**解包链**: SquashFS（unsquashfs; 自定义压缩 -comp xz|lzma|lzo|gzip; magic hsqs）/ JFFS2（jefferson）/ UBI（ubireader）/ CPIO initramfs（cpio -idv）/ 设备树（dtc -I dtb -O dts）/ vmlinux-to-elf。

**架构要点**: ARM 函数指针 LSB=1 即 Thumb（Ghidra Processor Options 切）; MIPS 分支延迟槽+$gp→.got+lui+addiu 拼常数; qemu-arm/-mips(-el) -L sysroot + -g 1234 配 gdb-multiarch。

**RTOS**: FreeRTOS（xTaskCreate 函数指针/"IDLE"/"Tmr Svc" 任务串/xQueueSend-Receive）; Zephyr（k_thread_create/k_msgq/CONFIG_* 符号）; 裸机（0x0 或 0x08000000 STM32 中断向量表+while(1)+外设寄存器查手册）。

## §2 Linux .ko 与 eBPF（Windows .sys 见 kernel-driver-analysis.md）

.ko: modinfo / nm | grep -v " U "; **ioctl 定位 = file_operations 结构 .unlocked_ioctl 槽**（函数指针数组按位置识）。CTF 模式: alloc_chrdev_region+cdev_init 建 /dev → switch(cmd) → copy_from/to_user。
调试: qemu -kernel bzImage -initrd initrd.cpio -s -S -append "console=ttyS0 nokaslr"; gdb lx-symbols / add-symbol-file module.ko 0xaddr。
eBPF: bpftool prog list / dump xlated（反汇编）/ dump jited（原生码）; r0=返回 r1-5=参数 r10=帧指针，指令 8B。helper: map_lookup/update_elem、probe_read、trace_printk。BPF 过滤规则可用 Z3 求解; JIT 编译产物可经 dmesg 泄漏读原生汇编。

## §3 游戏引擎（IL2CPP 见 language-binary-reversing §4）

- **UE**: .pak 解包 UnrealPakTool/quickbms; Blueprint=Kismet 字节码（K2_SetTimer/DoOnce/Branch）; UObject 反射 StaticClass 识类型; FString UTF-16
- **Unity Mono**: Data/Managed/Assembly-CSharp.dll → ilspycmd 反编译; 资源提取 AssetRipper CLI; flag 藏点含 PlayerPrefs 存档/TextMesh/Shader 源码; patch 路径: dnlib（.NET 库）改 Assembly-CSharp.dll 的 Update 逻辑 → 回打包 → apktool b 重签
- **反作弊**: EAC（内核+完整性）/ BattlEye（注入+加密信道+截图）/ VAC（用户态+延迟封禁）; CTF 只绕特定检查——存档操纵常比运行时易
- **Lua 游戏**: luadec/unluac（5.1-5.3）/ luajit -bl + ljd; 识别 lua51.dll/lua_ 串; hook lua_pcall 截执行
- **Tauri**: 前端资产 Brotli 压缩嵌入可执行文件——`index.html` 交叉引用定位 asset 索引表 → dump 压缩 blob → Brotli 解压得前端源码; 索引表结构参照 tauri-codegen/src/embedded_assets.rs

## §4 汽车 CAN/UDS + 工控协议

`ip link set can0 type can bitrate 500000`; candump（-l 日志）/ cansniffer（高亮变化位）/ canplayer 重放 / cansend 7DF#0201...（OBD-II）。UDS: 0x27 Security Access（**逆 ECU 固件 seed-key 派生算法**）/ 0x2E WriteDID / 0x31 RoutineControl。三模式: seed-key 绕过/重放/UDS-KWP2000 提固件。

**工厂侧工控三协议**: Modbus 无认证——低频功能码藏数据（16 写多寄存器重点，pyshark filter='modbus' 取 data hex→ASCII; 交互用 pymodbus 库 read/write_registers）; FINS（OMRON）9600 端口+`U2Fsd`（Base64 "Salted__"）识别 OpenSSL 加密; S7（Siemens）TCP 102 弱认证直接提 DB 块/程序，S7-200 Smart 密码可固件提哈希或嗅探。梯形图=rung 转布尔方程→Z3 解。**IEC 60870-5-104**（2404 端口）: ASDU 格式——TI 类型标识定数据格式（1/3 单双点、9/13 测量值=监控向; 45/46/50 命令=控制向）+公共地址定站+IOA 定点号; raw socket 构包（emerging-ctf）。

## §5 跨环境执行与确定性密钥

- **GLIBC 符号版本 patch**: 字符串（GLIBC_2.25→2.27）+ **版本 hash 槽**双改（objdump -p 看 hash; ld.so 双重校验）→ qemu-riscv64 -L sysroot
- **小众 ISA**: help banner 常留自定义 opcode 文档（作者调试残留）先 strings; C-SKY（国产 TBox 常见）: IDA 插件/Ghidra 模块/csky-abiv2 工具链/qemu-csky
- **APK 确定性密钥反模式**: key=SHA-256(META-INF/CERT.RSA 证书)[:16] 离线可提; 审计 getSignature+MessageDigest 组合

## §6 U-Boot 与 NAND

U-Boot: legacy 头 27B（magic 0x27051956+hcrc+time+size+load+ep+dcrc）; FIT 用 dumpimage -l; QEMU `-M versatilepb -kernel u-boot.bin` 控制台 md.l dump; **环境变量在 flash 已知位置藏密码/启动命令**; secure boot 查 RSA 公钥内嵌+哈希比较时序。
NAND 网络: 函数完备——真值表 2^n 重建+模式识别（NOT=双输入并联 NAND/AND=NAND+NOT/OR=XOR=4 NAND/交叉耦合=锁存器）+反馈环=状态元件; 卡诺图/Quine-McCluskey 化简。

## §7 WASM 与小程序

WASM: wasm2c（转 C 最可读）/wasm-decompile/Ghidra 插件/DevTools。模型: 线性内存+间接调用 table。攻击面: 边界检查整型溢出/间接调用类型混淆（C/C++/Rust 来源模式照旧）。**文本级 patch**: `wasm2wat` → 编辑 WAT（翻转 i64.lt_s→i64.gt_s/改常量）→ `wat2wasm` 重打包——游戏类"证明生成与走子质量独立"时 patch minimax 让 AI 变差而证明仍有效; 比 wasm2c 重编译轻量。**运行时内存 patch（games-and-vms-2）**: Node instantiate 后 `new DataView(instance.exports.memory.buffer).setInt32(偏移, 值, true)` 直接改游戏状态（连胜计数/胜率 100%）——改运行时状态而非二进制，免懂完整逻辑; 变量偏移用 `wasm-objdump -x` 或搜已知常量定位。
微信小程序: 缓存 Windows `WeChat Files\Applet\` / macOS `~/Library/Containers/com.tencent.xinWeChat/.../Applet/` / Android `appbrand/pkg/`; wxappUnpacker（旧版 JS+WXML）/ **unveilr（新版字节码）**; 产出 grep https://|flag|secret。

## §8 硬件与高级架构

- **GPIO 协议重建**（HD44780 型）: CLK=翻转最多引脚自识别; 下降沿采样 D4-D7 nibble 拼字节; 4×20 屏 DRAM 非连续（L1=0x40/L2=0x14/L3=0x54）; RS=1 数据 0 命令
- **RISC-V 扩展**: clmul/clmulh（无进位乘=密码学特征）/Zk*（aes32esi/sm3p0/sm4ed）; CSR: mstatus/mtvec/mepc/satp; OpenOCD+J-Link 或 qemu -g 调试
- **RISC-V 基础静态速查**: 无 flags 寄存器（比较内联于 beq/bne）; 参数 a0-a7、返回 a0; s0-s11 callee-saved; sd/ld=64 位; W 后缀=32 位（addiw）; 压缩指令 2B 与标准 4B 混编。Capstone: `Cs(CS_ARCH_RISCV, CS_MODE_RISCVC | CS_MODE_RISCVC64)`——C 扩展必开否则错位; 静态 .text 典型偏移 0x10000（以 e_entry 确认）。反逆向三招: 假 flag 字符串常量（`n0t_th3_r34l` 类）/rdtime 计时防爆破/增量 XOR key（`key+=7` 按序还原不能并行）。运行 `qemu-riscv64 -L /usr/riscv64-linux-gnu/`
- **硬件加密两型**: MIPS OCTEON CP2（dmtc2/dmfc2 selector 0x100-0x40FF; AES key 0x0104-07）/ MCU MMIO（EFM32 0x400E0000 CTRL/CMD/KEYLA-D; 组合 key=两值 XOR; flat bin 强制 Thumb: T=1）
- **老平台**: MBR qemu -fda -s -S + gdb i8086 + b *0x7c00; Game Boy SM83 用 bgb——CP [HL] 比较时 *HL 内存面板直接看期望值
- **KVM Guest**: -lkvm//dev/kvm 即弃常规管线; strace -v -e ioctl 记 KVM_RUN/GET-SET_REGS（KVM_EXIT_HLT=基本块边界）+ gdb dump guest 内存 + 宿主跳表重建 dispatch 图
- **ROM XOR 对 bit-flip**: intended=C1^C2 线性——inferred^actual 汉明距定位候选翻转位（差分位而非常数本身）; 成对地址常数经 XOR/ADD/SUB 组合均可定向单 bit 攻击; 同构 rowhammer
