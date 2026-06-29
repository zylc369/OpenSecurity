# 已验证来源溯源表（本会话 webfetch 亲自抓取）

> 透明度说明：标 ✅ = 本会话已用 webfetch 成功抓取并核对内容；标 [结构] = 仅验证了该入口的结构形态（可据此定位具体条目）。未在本表出现的题目级 writeup URL 一律视为"待核对"，不写入报告正文作事实断言。

## A. 工具官方文档 / 发行说明（✅）
| 工具 | 验证内容 | URL |
|------|---------|-----|
| IDA 9.0 发行说明 | idalib 无头处理、RISC-V 反编译器、WASM 反汇编器+loader、nanoMIPS、C++ try/catch、FLIRT(Go/Rust)、ida_struct/enum 移除、venv 支持、ida-plugin.json | https://docs.hex-rays.com/release-notes/9_0.md |
| IDA 9.1 发行说明 | ARM64 ILP32、ARM MVE/Helium、RISC-V 原子+intrinsics、Tricore、ea_t→int/qstring→str | https://docs.hex-rays.com/release-notes/9_1.md （via ?ask=）|
| IDA 9.4 beta 发行说明 | Dyld Shared Cache 重写、Swift ABI、ARM SVE2/SME、Hexagon/QDSP6+MBN loader、Pathfinder widget、Deep Links、统一 Scripts 窗口 | https://docs.hex-rays.com/release-notes/9_4beta.md （via ?ask=）|
| IDA 发行说明总览 | 版本列表 9.0–9.4beta / 8.x / 7.x | https://docs.hex-rays.com/products/ida/news/ |
| Ghidra 12.0 WhatsNew | PyGhidra 3.0 取代 Jython 默认、Z3 concolic 仿真器(SymbolicSummaryZ3)、仿真API重构(JIT)、NDS32/AndeStar v5、Data Graph、GhidraGo URL、filesystem mirror | https://raw.githubusercontent.com/NationalSecurityAgency/ghidra/Ghidra_12.0_build/Ghidra/Configurations/Public_Release/src/global/docs/WhatsNew.md |
| Ghidra releases 列表 | 12.1.2(2026-06) / 12.1 / 12.0(2025-12) / 11.4.x | https://github.com/NationalSecurityAgency/ghidra/releases |
| Binary Ninja Python API | v5.3；LLIL/MLIL/HLIL、Workflow、TypeLibrary/TypeArchive、FirmwareNinja、Debugger、RenderLayer | https://api.binary.ninja/ |
| angr 文档目录 | 内置 deobfuscator 模块(string_obf_finder/api_obf_finder/hash_lookup_api_deobfuscator)、反编译器 DREAM/SAILR/Phoenix 结构化、presets(basic/fast/full/malware) | https://docs.angr.io/ |
| Triton 主页 | DSE+污点；x86/x64/ARM32/AArch64/RISC-V；Z3/Bitwuzla；生态 QSynthesis/Titan/TritonDSE/Ponce | https://triton-library.github.io/ |
| D-810 README | eshard；IDA microcode 反混淆插件；基于 RolfRolles/HexRaysDeob；IDA≥7.5+Py3.7+z3；default_instruction_only.json | https://gitlab.com/eshard/d810/-/raw/master/README.md |

## B. 基础论文 / 演讲（✅，来自 Triton 主页链接）
| 主题 | 出处 | URL |
|------|------|-----|
| VM 去虚拟化（通用方法奠基） | DIMVA 2018, Salwan/Bardin/Potet | https://github.com/JonathanSalwan/Triton/blob/master/publications/DIMVA2018-deobfuscation-salwan-bardin-potet.pdf |
| QSynth 程序合成去混淆(MBA/编码/虚拟化) | BAR 2020, David/Coniglio/Ceccato | https://github.com/JonathanSalwan/Triton/raw/master/publications/BAR2020-qsynth-robin-david.pdf |
| Greybox 程序合成攻击数据流混淆 | BlackHat USA 2021, Robin David | https://github.com/JonathanSalwan/Triton/raw/master/publications/BHUSA2021-David-Greybox-Program-Synthesis.pdf |
| Hex-Rays microcode 对抗混淆编译器 | Rolf Rolles / Hex-Rays 博客 | https://www.hex-rays.com/blog/hex-rays-microcode-api-vs-obfuscating-compiler/ |
| HexRaysDeob 插件 | Rolf Rolles | https://github.com/RolfRolles/HexRaysDeob |

## C. 语言/格式逆向工具（✅）
| 工具 | 验证内容 | URL |
|------|---------|-----|
| GoReSym (Mandiant) | Go 符号/类型/moduledata/pclntab 恢复；支持 Go1.2–1.24；处理 stripped/UPX；IDAPython goresym_rename.py | https://raw.githubusercontent.com/mandiant/GoReSym/master/README.md ；blog: https://www.mandiant.com/resources/blog/golang-internals-symbol-recovery |

## D. 挑战/writeup 入口（[结构] / ✅）
| 资源 | 性质 | URL |
|------|------|-----|
| CTFtime writeups 索引 | ✅ 列表形态已验证（按 event/task/tag），可检索 reverse | https://ctftime.org/writeups |
| CTFtime 事件任务页 | [结构] 形态已验证，如 DEFCON 2025 Quals | https://ctftime.org/event/2604/tasks/ |
| sajjadium/ctf-archives | ✅ 按 CTF/年份 组织的**挑战原始包**归档（含 CTFtime 任务链接），1.5k star | https://github.com/sajjadium/ctf-archives |
| PersianCats writeups | ✅ 老题 writeup 子集（ctf-archives 内引用） | https://github.com/sajjadium/ctf-writeups |

## E. 待进一步核对（本会话未抓取，仅供方向，不作事实引用）
- 各赛事具体题目级 writeup URL（DEFCON/Google/HITCON/SekaiCTF/0CTF/RealWorld 2023-2025 的单题 writeup）
- Rust/Zig/Nim/Crystal 逆向专门 writeup
- 国产加固最新特征（梆梆/爱加密/乐固/360）2024-2025 writeup
- iOS 17/18 新保护、Frida 17.x 变化的实战 writeup
- WASM 逆向单题 writeup
