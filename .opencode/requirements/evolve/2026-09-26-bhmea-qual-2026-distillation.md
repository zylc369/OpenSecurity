# BlackHat MEA Qualification CTF 2026 整库蒸馏

## §1 背景与目标

- 来源: 用户指定仓库 https://github.com/stack1245/BlackHat-MEA-Qualification-CTF-2026
- 素材: 14 题（pwn×3 含内核 / web×4 / crypto×3 / reverse×3 / forensics×2），已归档 `docs/资料/writeup-sources/blackhat-mea-qual-2026/`（147 文件，含 analysis 原文 14 篇精读）
- 预期收益: 23 条技术点级 gap 沉淀到 16 个既有知识库文件（零新建），其中高价值方向级 3 条（kmalloc 分区随机化回收策略、GCM tag 部分泄漏代数链、目标侧 CDP/WebDriver 暴露攻击面）

## §2 技术方案（gap → 落位总表）

| # | Gap | 落位文件 | 价值 |
|---|---|---|---|
| G1 | 受限写宽度 GOT 重定向链拼装（7 字节 atol: 三 GOT 各指二进制内小片段、寄存器残留 rdx 复用、__stack_chk_fail→main 循环当重入） | pwn-methodology.md（Eternal Loop 区） | 高 |
| G2 | OR-only 写原语的 ASLR 兼容筛选（只能 0→1 时目标值位约束不符→重连重试） | pwn-methodology.md（同区） | 中高 |
| G3 | 尺寸字段篡改使渲染 stride 失配泄漏（width OR 扩宽→渲染输出混入结构体后续内存） | pwn-methodology.md（泄漏段） | 中高 |
| G4 | ret 链不受 IBT 限制; 终落点选 libc 内满足寄存器条件的合法函数内部路径; 返回点自动复位支持多轮累积写 | pwn-methodology.md L203 并句 | 中 |
| G5 | seccomp filter 当数据 oracle（逐位 syscall 探测 + 提取 cBPF 指令用户态重实现，kernel load EINVAL 也能做） | pwn-methodology.md L50 附近并句 | 中 |
| G6 | stdout 真身前 64B 伪造读原语（不动 vtable、_IO_USER_BUF 防 free 假 buf、setbuf 触发 flush）+ COPY relocation 低地址指针跳板（双重间接任意写） | pwn-heap-methodology.md（FILE UAF 技巧区扩 2 条） | 高 |
| G7 | CONFIG_KMALLOC_PARTITION_RANDOM 下 UAF 回收（cache index=hash_64(call_site^seed,4) 16 分区、双 call-site 并行候选、安全失败+fresh VM 重试预算、实测 ~12%; GFP_KERNEL_ACCOUNT 与 MEMCG=n 不分 cache; qemu64 不暴露 SMEP/SMAP→ret2usr） | pwn-kernel-methodology.md（堆喷/回收区） | 高（方向级） |
| G8 | PREFETCH 时序 KASLR oracle（mapped ~0.7µs vs unmapped ~22µs、2MiB 步进扫 _text、自地址+确定 unmapped 校准） | pwn-kernel-methodology.md（KASLR 段） | 中 |
| G9 | rdtsc 参与校验值计算（非仅时序检查）: 双 rdtsc 角色区分（外层 anti-debug timeout vs 内层参与 validator 值且 EDX clobber 致非确定）、Unicorn 固定 tsc 跑纯函数、EDX=0 常是出题本意 | anti-debugging-bypass.md | 中 |
| G10 | SIGTRAP dispatcher 分 stage 解密的还原法（handler 入口+解密后双断点 dump 内存、逐 stage 拼接，替代全量 trace） | anti-debugging-bypass.md L84 并句 | 低-中 |
| G11 | 双硬件断点（输入读点/结果比较点）+ CONTEXT rewind + 逐字节 0..255 枚举固定匹配 → self-modifying verifier 的 960B 唯一 preimage 逆算（one-shot pipe 服务器保真实栈上下文） | dynamic-analysis.md（调试自动化区新小节） | 高 |
| G12 | 会话绑定状态模块的 Frida oracle 法（提取 .pyd 脱离原进程输出不同→attach 原进程 PyGILState_Ensure+Python C API 调原函数）+ named pipe 验证协议 oracle 化（命令枚举、独立 block 判定） | dynamic-analysis-frida.md | 高 |
| G13 | 主机标识派生密钥材料（SHA256(username_hostname)→X25519 私钥）+ PCAP 明文 HTTP/2 gRPC 握手公钥验证关联 | malware-analysis.md（§2 加密通信解密区） | 中 |
| G14 | Defender quarantine 恢复（ResourceData 公开 RC4 固定 key 解层 + WIN32_STREAM_ID 流解析 + stream id=1 原始样本数据） | windows-forensics.md | 高 |
| G15 | 本地 LLM 工具痕迹取证（~/.ollama/history 明文 prompt 含敏感数据、systemd/auditd EXECVE/Trash 交叉重建行为链） | forensics-methodology.md | 中高 |
| G16 | CSS 注入边界的解析器职责差异: 服务端 CSS validator（AST 级）视 `/*</style>...*/` 为 comment，HTML raw-text tokenizer 不认 CSS comment 语法、`</style>` 实际终结; 防御=独立 stylesheet 资源或 HTML 语境转义 | html-parse-differentials.md 新 §2.7（标题七种机制） | 高 |
| G17 | 站内记录型端点当外带接收器（owner-only pickup log/trace 端点记录 beacon URL 全 query，无 OOB 基建需求） | file-upload.md L65 外带排序处并句 | 中 |
| G18 | CSS 逐字符 oracle 的 cascade 冲突工程（多候选规则同元素 background 覆盖→候选存 custom property + background-image 多 layer 合成命中） | xss-advanced.md L133 并句 | 中 |
| G19 | 目标侧 CDP/ChromeDriver 端口暴露攻击面（渲染服务用户 JS 可达 loopback 的 --allowed-origins='*' ChromeDriver→直接 WebDriver 协议操控高权限实例; 多页面拆单命令绕单页时限; 像素灰度 codeword 信道：数据编码进亮度条/中央像素读，抗 JPEG 有损不依赖 OCR） | browser-automation.md 新 §9 | 高 |
| G20 | QuickTime dref `alis` external data reference + chunk offset 0 → FFmpeg 读任意绝对路径（enable_drefs/use_absolute_path 需显式开）; JPEG comment `Lavc*` 指纹识别 FFmpeg 后端 | file-upload.md §7 FFmpeg 链并条 | 高 |
| G21 | RSA Hamming weight 解密 oracle（blinds 乘法+modular halving 的 weight 保持性判 parity: h_i 不变→parity 0 / h 变 g 不变→parity 1; 模糊位用 z=3m carry 消歧; m=(-u·n) mod 2^L 重建） | rsa-attacks.md（oracle 段并条） | 中高 |
| G22 | AES-GCM tag 部分泄漏（nibble 轮换）完整代数链: 等长消息差分 ΔT=ΔP·H^4 消 CTR/mask→Frobenius 逆 (H^4)^(2^126) 恢复 H→ASCII hex 域 5-bit 编码+稀疏性压 nullity→AES_K(0)=H 验证恢复 key→GHASH 线性消前 3 CTR 块+长度差分暴露 E4[1]→256 枚举 E4[0]→J0 闭式 N=(J0+[128]·H)/H² 恢复 nonce | symmetric-and-hash.md（GCM 段并条） | 高 |
| G23 | 稀疏多项式 oracle（8 次查询）: 坐标取自 {1,2,3} 使 M[i,j]≤3^11、输出整线性关系的 LLL 短向量筛真实单项式（705432 弱组合枚举过滤）、6×6 子行列式 GCD 恢复模数 | lattice-attacks.md 新 §5i | 高 |

**已覆盖跳过**（不重复沉淀）: hash length extension（symmetric-and-hash §5）、PHP max_input_vars 剥 CSP（csp-bypass §2.1.1）、分段检查+拼接后二次解码（ghost-bits 五维模型）、LSB parity oracle 基础（rsa-attacks L255）、GCM forbidden attack 基础（L192）、ctypes CDLL 同 libc srand/rand 同步（prng-attacks L57）、pipe_buffer 回收族（pwn-kernel 对象表）、setcontext+61（pwn-heap L198）、Go 符号恢复（language-binary §10）、PyInstaller 多层容器（packer-handling L105）、seccomp 规则反汇编还原基础（pwn-methodology L50）、io_uring personality 喷射（已有）、题目特定数字/布局。

## §3 实现规范

- 全部并入既有文件零新建; 交叉引用用 `$AGENT_DIR`/`$SHARED_DIR` 变量
- 知识零来源叙事铁律: 无题名/赛事名/来源标注
- 具体版本数字仅保留有跨版本判别价值的（如 glibc 行为分界），纯 offset 不落

### §3.1 实施步骤

步骤 1. pwn 方向写入（pwn-methodology G1-G5 / pwn-heap G6 / pwn-kernel G7-G8）
  - 文件: 3 个
  - 预估行数: ~40 行
  - 验证点: 语法（表格完整行首尾 |）/叙事词零命中/章节编号未破坏
  - 依赖: 无
步骤 2. reverse/dynamic 方向写入（anti-debugging G9-G10 / dynamic-analysis G11 / dynamic-analysis-frida G12 / malware-analysis G13）
  - 文件: 4 个
  - 预估行数: ~40 行
  - 验证点: 同上 + L84 并句上下文连贯
  - 依赖: 无
步骤 3. forensics 方向写入（windows-forensics G14 / forensics-methodology G15）
  - 文件: 2 个
  - 预估行数: ~20 行
  - 验证点: 同上
  - 依赖: 无
步骤 4. web 方向写入（html-parse-differentials G16 / xss-advanced G18 / browser-automation G19 / file-upload G17+G20）
  - 文件: 4 个
  - 预估行数: ~45 行
  - 验证点: §2 标题"六种"→"七种"机制; 章节编号连续
  - 依赖: 无
步骤 5. crypto 方向写入（rsa-attacks G21 / symmetric-and-hash G22 / lattice-attacks G23）
  - 文件: 3 个
  - 预估行数: ~35 行
  - 验证点: 数学表述与源文一致（对照 analysis 原文逐条核）; 章节编号
  - 依赖: 无
步骤 6. 回归检查 + 独立复审
  - 叙事扫描（词边界版）/ 表格完整性 / 章节单调 / 交叉引用存在 / git diff 审阅
  - 验证点: 全部零问题后向用户汇报
  - 依赖: 步骤 1-5

## §4 验收标准

- 功能: 23 条 gap 全部落位，表述含触发条件/步骤/判断标准
- 回归: 4 个方向 16 文件的既有章节结构零破坏; prompt 索引无需变更（全部既有已索引文件）
- 架构: 零新文件、零 docs/ 引用、归属符合 architecture-map

## §5 与现有需求文档的关系

- 方法沿续 2026-09-25-k17-ctf-2026-distillation.md（同入口 C 直接蒸馏）
- 上一任务"gap 判定宽严校准"教训应用: 每条 gap 先 grep 查证再判定（本表 13 条已覆盖跳过即查证产物）; 中间原语逐个查（setcontext/COPY relocation 等均单独查证后才定并入或跳过）
