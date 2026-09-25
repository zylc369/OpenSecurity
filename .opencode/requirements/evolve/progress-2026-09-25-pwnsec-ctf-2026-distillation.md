# 进度：PwnSec-CTF-2026 仓库知识蒸馏

> 需求文档: 2026-09-25-pwnsec-ctf-2026-distillation.md（22 步）

## 步骤进度

| 步骤 | 状态 | 备注 |
|---|---|---|
| 1 归档+环境 | ✅ | 51 文件（26 en.md + 25 solve.py；Spiny Trace 为 partial 无 solve.py，需求预期 52 → 实际 51）；flint 0.8.0 + sympy 1.14.0 已装 |
| 2 G1 JSC | ✅ | 核实: diff.patch（addressOf/describe/readFile 被注释、generateHeapSnapshotForGCDebugging 未注释=保留）、win() 契约、TAG=WebKit-7624.1.16.11.4；jsc-exploitation.md 65 行 + v8 互引 + prompt 索引 |
| 3 G2 音频 | ✅ | 核实: optimize_audio.py:55 STE 量化前向、teacher-forced 目标、compare_espeak.py 余弦+RMSE 对齐、TARGET_TEXT payload；audio-modality-attacks.md + prompt 索引 |
| 4 G3 PHP | ✅ | 核实: php.ini（disable_functions 含 system/exec/unserialize/pcntl_*、open_basedir=/home/ctf/scripts:/tmp）、readflag.c setuid(0) 读 /flag、Dockerfile=php-src master；sandbox-escape.md §2d + Calif 链接 |
| 5 G23+G24 | ✅ | 核实: ycc.c——esc 函数用于 map key(:558)/参数名(:569) 但 member access 裸拼; main.py 正则+点数过滤; 仿真验证: 原始 pattern fullmatch=True、788B、2 dots、compile OK; §1 补 comprehension 目标 + 新增编译器转义不一致节 |
| 6 G4+G6a | ✅ | 核实: readonce server.js:131 req.query.u→new URL + sandbox.ejs `<script nonce src="<%= url %>"`; easy-leak entrypoint.sh 4×php -S 127.0.0.1:900x + Caddy :3000 CSP 注入; csp-bypass.md nonce 表+1 行 + §2.3.1 反代 CSP 节; 顺手修既有 "CTF 题" 叙事词 |
| 7 G5+G9 探针 | ✅ | probe-named-window-leak + probe-opener-recovery; **三版本 Chrome 146/148/153 全过**（153 二进制损坏已重装）; named: fetchBlocked=true+secretLeaked=true ×3; opener: recoveryWorks=true ×3; 初版探针 CSP 误加 sandbox allow-scripts 被自查纠正 |
| 8 G5+G9 知识 | ✅ | client-side-attacks.md 命名窗口节 + race-conditions.md §4 存活侧 + 探针 README 交叉引用; "ctF" 假阳性=reactFiber 子串（记录: 回归 grep 用词边界） |
| 9 G7 | ✅ | 核实: admin.ecr:18 `<%= @flag %>` 无转义（对比 :11 @username 有 escape）; neon_skies.cr:14 request.cookies[] Hash 语义; bot conf.js:75 host-only httpOnly Strict 无 __Host-; cookie tossing 节重写扩充; web-vulnerabilities.md 无重复 |
| 10 G8 | ✅ | 核实: server.js DOMPurify 默认配置 + script-src 含 data: + global.js 模块加载; **esm.sh 36ad7f8 打包版源码确认** H() 读 [data-prism-*] + load() 拼接 import(path+id+".js") + 空 id + #fragment 吞 .js + window.name 二段模块; xss-advanced.md §5 gadget 类 |
| 11 G10+G25 | ✅ | 核实: PHault analysis/oracle.md（根路由源码披露 + 4557/4744B 响应表 + INTO @x 语义）; PwnSec Support observations.md:9 UNION payload + 空 sessions; sqli-advanced.md 增补节 ×2; 修既有 "CTF 最快" |
| 12 G6b | ✅ | bot-patterns.md §3.1a 网络位置盘点表; 修既有 2 处场景叙事（"Web CTF Bot"/"CTF 中 flag Cookie"）; 并行 Edit 同文件失败教训→串行 |
| 13 G11 | ✅ | 核实: shadowops.ko 段表/符号（open@0x0 size30、write@0x30 size92、used@.bss）+ capstone 反汇编（0x57 e8 call 0x5c、cmp rdx,0x10、lock xadd used、cmp eax,2）全与 writeup 一致; **QEMU 本地复跑成功**（TCG 无 KVM、serial tcp、timeout 40→240 适配慢启动）输出 flag{test_flag_for_ctf_challenge} exit=0; pwn-kernel-methodology.md §7f |
| 14 G12+G13 | ✅ | **Docker amd64 复跑成功**: freal 完整链（PIE→mmap threshold→OOB→内存 ELF→GNU hash→__environ→栈 ROP）输出 flag{fake_flag}（本地占位 flag 不匹配 pwnsec 正则属预期）; Rosetta 需显式 --platform linux/amd64; pwn-methodology.md §4 表 +4 行 |
| 15 G14+G15 | ✅ | prob 本地复现尝试多轮未通（shellcode 跑飞，strace 证明用户代码在执行、环境机制正常）→ **降级为独立验证核心断言**: 最小 C 程序证实 MAP_FIXED_NOREPLACE 覆盖已映射区返回 -1/EEXIST=17、不覆盖成功（并发现区间左闭右开边界语义已写入知识）; EVP 审计写入 crypto-validation-patterns.md; MBA 与 deobfuscation-selection.md 判定非重复（化简 vs 求解不同主题） |
| 16 G16 | ✅ | 核实: run_frida.py + trace.js/dump_module.js（ShellExecuteA/MessageBoxW hook + RVA 读取 + module-dump）; packer-handling.md 嵌套提取策略 |
| 17 G17+G18 | ✅ | 核实: portal33.exe file 0xaca 处 `6a 33 e8 00000000 83 04 24 05 cb` Heaven's Gate 坐实（writeup 的 0x4016b3=gate 目标即 64 位侧序言，初读偏因单模式解码——陷阱本身进知识）; reverse-patterns.md §55/§56; 修既有 2 处 CTF 叙事 |
| 18 G19 | ✅ | writeup --trace 布局（data=0x10000..0x3f9d04/code=0x3f9d10..0x6b2fd0）+ 相对偏移公式与 vm-bytecode-reversing.md §8 一致; 修既有 3 处 CTF 叙事 |
| 19 G20 | ✅ | **复跑成功**: solve_local.py（默认读已捕获 remote-output.txt，跳过 instance 加载）输出 pwnsec{a037f98cd3e49a5f} 与 flag 文件一致; 格参数与 analysis/derivation.md 对照一致; rsa-attacks.md §12a |
| 20 G21 | ✅ | **复跑成功**: 纯附件本地跑通，flag 含 3 days/3 seconds 字样 exit=0; prng-attacks.md §10; 修既有 1 处 CTF 叙事 |
| 21 G22 | ✅ | chall.py 依赖 sage 无法本地生成（动态复跑降级）; **静态对照核实**: solve.py 的 fmpz_mat.lll/交换关系 gcd 恢复模数/f(x)=x^4097+3x^257+11x^17+42x+99 代入验证/babai_closest 与 writeup 阶段一致; exotic-algebra-attacks.md §14a; 修既有 1 处叙事 |
| 22 全量回归 | ✅ | 20 文件叙事词词边界扫描清零; prompt 索引 2 行在位; 交叉引用 5/5 存在; 探针 README 判据齐; 归档 49 文件（25 题全量）; 回归修复 3 处既有叙事词 + 记录 2 个 grep 假阳性模式 |
| Phase 6 审计 | ✅ | 轮1: 章节顺序修正（prng §10→§8a 前移、exotic §15→§14a 前移至决策节前）; 轮2: prompt 展开 441/451 复核、引用格式抽读、diff 审查（17 删除行全为叙事修正、核心零删除）; 纯审计轮零问题通过 |

## 原题核实记录

（执行中追加：步骤 / 核实对象 / writeup 声称 / 源码证据 / 一致性结论）

## 复跑记录

（Tier 2/3 复跑：命令 / 退出码 / 输出）

## 差异与修正

- 归档计数: partial 题（forensics/Spiny Trace 1）无 solve.py，归档总数 51 非 52，非缺失。
- **题目总数修正**: Phase 0 报告与需求文档写"26 题"系计数错误——实际 **25 题**（web 8 + pwn 6 + crypto 3 + reverse 4 + misc 3 + forensics 1 = 25），归档 24×2+1 = 49 文件全部在位、无缺失。
- 步骤 22 回归修复: pwn-methodology/rsa-attacks/ai-security-analysis 各 1-2 处既有叙事词中性化; grep 假阳性记录——`reactFiber` 子串匹配 `ctF`（大小写不敏感无词边界时）、务必用 `\b` 词边界。
- peekaboo 本地复现未跑通全链（环境适配成本超预期），核心断言已独立验证（MAP_FIXED_NOREPLACE EEXIST 最小 C 实验），见步骤 15 备注。
- skill issue 动态复跑受 sage 依赖限制，降级为 solve.py 静态实现对照（一致），见步骤 21 备注。
