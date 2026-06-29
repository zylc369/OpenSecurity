# 源文档下载清单

> 创建: 2026-06-29
> 需求文档: `.opencode/requirements/evolve/2026-06-29-ctf-writeup-knowledge-evolution.md`

## Pwn 方向（第一批）

### how2heap 核心 PoC（GitHub raw，curl 批量下载）
| 文件 | raw URL | 覆盖技术 | 状态 |
|------|---------|---------|------|
| house_of_tangerine.c | `.../glibc_2.39/house_of_tangerine.c` | 无free堆利用 glibc2.34+ | ⬜ |
| house_of_water.c | `.../glibc_2.39/house_of_water.c` | smallbin变体 glibc2.36+ | ⬜ |
| large_bin_attack.c | `.../glibc_2.39/large_bin_attack.c` | 任意写原语(⚠2.42补) | ⬜ |
| house_of_botcake.c | `.../glibc_2.39/house_of_botcake.c` | UAF→重叠块 | ⬜ |
| tcache_stashing_unlink.c | `.../glibc_2.39/tcache_stashing_unlink_attack.c` | smallbin→tcache | ⬜ |
| safe_link_double_protect.c | `.../glibc_2.39/safe_link_double_protect.c` | safe-linking无泄漏绕过 | ⬜ |
| decrypt_safe_linking.c | `.../glibc_2.39/decrypt_safe_linking.c` | safe-linking编解码 | ⬜ |
| sysmalloc_int_free.c | `.../glibc_2.39/sysmalloc_int_free.c` | 无free堆利用 | ⬜ |
| tcache_poisoning.c | `.../glibc_2.39/tcache_poisoning.c` | 基础tcache毒化 | ⬜ |
| fastbin_reverse_into_tcache.c | `.../glibc_2.39/fastbin_reverse_into_tcache.c` | fastbin→tcache(⚠2.42补) | ⬜ |

raw URL 前缀: `https://raw.githubusercontent.com/shellphish/how2heap/master/`

### 博客/文档（webfetch 下载）
| 来源 | URL | 覆盖技术 | 状态 |
|------|-----|---------|------|
| ptr-yudai DiceCTF 2026 | 待查找 | 内核: MADV_DONTNEED+cross-cache+PTE overlap | ⬜待查找 |
| ctf-wiki kernel pwn | `https://ctf-wiki.org/pwn/linux/kernel-mode/` | 内核利用基础 | ⬜ |
| House of Apple (roderickchan) | 待查找（GitHub roderickwang 非此人） | IO_FILE wide-data vtable | ⬜待查找 |

## 逆向方向（第一批）

| 来源 | URL | 覆盖技术 | 状态 |
|------|-----|---------|------|
| D-810 README | `https://gitlab.com/eshard/d810/-/raw/master/README.md` | microcode层反混淆 | ⬜ |
| Hex-Rays microcode API | `https://www.hex-rays.com/blog/hex-rays-microcode-api-vs-obfuscating-compiler/` | microcode反混淆原理 | ⬜ |
| HexRaysDeob README | `https://github.com/RolfRolles/HexRaysDeob` | Hex-Rays反混淆 | ⬜ |
| GoReSym README | `https://raw.githubusercontent.com/mandiant/GoReSym/master/README.md` | Go符号恢复 | ⬜ |
| Mandiant Go internals | `https://www.mandiant.com/resources/blog/golang-internals-symbol-recovery` | Go逆向 | ⬜ |
| IDA 9.0 release notes | `https://docs.hex-rays.com/release-notes/9_0.md` | IDA 9.0新功能/API变化 | ⬜ |
| Triton DIMVA2018论文 | `https://github.com/JonathanSalwan/Triton/blob/master/publications/DIMVA2018-deobfuscation-salwan-bardin-potet.pdf` | VM去虚拟化原理 | ⬜ |
| QSynth BAR2020论文 | `https://github.com/JonathanSalwan/Triton/raw/master/publications/BAR2020-qsynth-robin-david.pdf` | 程序合成去混淆 | ⬜ |

## Web 方向（第一批）

| 来源 | URL | 覆盖技术 | 状态 |
|------|-----|---------|------|
| huli GoogleCTF 2024 | `https://blog.huli.tw/2024/06/28/google-ctf-2024-writeup/` | URL解析器/parseInt/[A-z]/cookie tossing/CSS trigram | ⬜已验证 |
| huli 0CTF 2023 | `https://blog.huli.tw/2023/12/11/0ctf-2023-writeup/` | CSS trigram exfil | ⬜ |
| huli HITCON/corCTF/SekaiCTF 2024 | `https://blog.huli.tw/2024/09/23/hitconctf-corctf-sekaictf-2024-writeup/` | bfcache/iframe reparenting/socket.io JSONP | ⬜ |
| huli idekCTF 2024 iframe | `https://blog.huli.tw/2024/09/07/idek-ctf-2024-iframe/` | iframe高级魔法 | ⬜ |
| huli DiceCTF 2024 | `https://blog.huli.tw/2024/02/12/dicectf-2024-writeup/` | connection pool/递归import | ⬜ |
| PortSwigger 原型链污染 | `https://portswigger.net/web-security/prototype-pollution` | PP sources/sinks/gadgets/RCE | ⬜已验证 |
| PortSwigger 单包攻击 | `https://portswigger.net/research/smashing-the-state-machine` | race condition/single-packet | ⬜ |
| cor.team corCTF 2025 | `https://www.cor.team/posts/corctf-2025-corctf-challenge-dev-2/` | 扩展timing侧信道 | ⬜ |
| cor.team corCTF 2024 | `https://www.cor.team/posts/corctf-2024-corctf-challenge-dev/` | Chrome扩展攻击 | ⬜ |
| SekaiCTF htmlsandbox | `https://blog.ankursundara.com/htmlsandbox-writeup/` | charset解析器差异 | ⬜ |
| huli XSS无括号 | `https://blog.huli.tw/2025/09/15/xss-without-semicolon-and-parentheses/` | XSS payload进化 | ⬜ |

## 密码学 + AI安全（第二批，暂列）

| 来源 | URL | 覆盖技术 | 状态 |
|------|-----|---------|------|
| pcw109550 write-up | `https://github.com/pcw109550/write-up` | 综合 crypto writeup | ⬜ |
| rkm0959 CTFWriteups | `https://github.com/rkm0959/CTFWriteups` | 综合 crypto writeup | ⬜ |
| OWASP LLM01 | `https://genai.owasp.org/llmrisk/llm01-prompt-injection/` | 提示注入 | ⬜ |
| Anthropic many-shot | `https://www.anthropic.com/research/many-shot-jailbreaking` | many-shot越狱 | ⬜ |
| PyRIT | `https://microsoft.github.io/PyRIT/` | 自动化红队工具 | ⬜ |
| promptfoo red-team | `https://www.promptfoo.dev/docs/red-team/strategies/` | 自动化越狱 | ⬜ |
