# 需求：PwnSec-CTF-2026 仓库知识蒸馏（26 题全量）

## §1 背景与目标

**来源**: 已确认 `github.com/stack1245/PwnSec-CTF-2026` 是 readonce/readtwice 两题的解法来源仓库。全仓盘点：26 题（web 8 / pwn 6 / crypto 3 / reverse 4 / misc 3 / forensics 1），每题含 `challenge/`（原题源码）+ `writeup/{en,ko}.md` + `solve.py` + `analysis/`（实验记录）。26 个 en.md 已 100% 精读，对照本地知识库完成 gap 判定（Phase 0 报告已交付用户）。

**痛点**: 3 个方向级空白（JSC 引擎利用 / AI 语音模态攻击 / PHP 沙箱逃逸）+ 22 个技术点级缺口，此前遇同类题需从零摸索（单题 50+ 轮）。

**用户决策**（已确认）:
1. 全量执行 4 批，一次进化完成
2. 知识按方向归入对应 agent 知识库（web→web-analysis、crypto→crypto-analysis、pwn/reverse/misc 沙箱→binary-analysis、AI 语音→ai-security-analysis）；agent 无缺口（misc 的 pyjail/ycc 延续 binary-analysis sandbox-escape.md 现状）
3. 能验证的必须验证：源 writeup 有已证伪先例（readonce-revenge 的 "event.source = old WindowProxy" 被探针实验证伪），知识写入前必须读原题源码核实

**验证分级**（用户确认的投入边界）:
- Tier 1（全部 25 gap）: 读 `challenge/` 源码核实 writeup 声称的机制
- Tier 2: crypto 三题、freal、peekaboo、readonce（探针级）本地复跑 solve.py / 最小 PoC；jailincpython 远程实例已失效 → 本地仿真过滤器验证 payload（compile 通过 + 过滤器放行）；ycc 远程实例已失效 → 源码核实为主（challenge 含 Dockerfile+ycc.c，复现成本低则 Docker 跑）
- Tier 3: Death Ops 用原题 QEMU 脚本复跑；PHP Sandbox 以 php.ini + 公开研究（Calif）对照；**JSC 不编译 WebKit**（用户否决，1-2h 过长），以 diff.patch + REVISION + writeup 记录的本地验证证据静态核实
- Tier 4（浏览器行为）: G5/G9 写 puppeteer 探针验证（沿用 probe-message-lifecycle 三版本 Chrome 模式）

**预期收益**: 25 个 gap 全部闭环（2 新文件 + 16 文件补章节）；机制知识经源码/复跑/探针交叉验证后入库，错误机制不传播。

## §2 技术方案

### 2.1 Gap → 落位总表

**新文件（2 个，均为 >80 行的独立主题）**:

| Gap | 来源题 | 新文件 | 内容 |
|---|---|---|---|
| G1 | pwn/JavaScript After Core | `$SHARED_DIR/knowledge-base/jsc-exploitation.md` | JSC 对象模型（butterfly/IndexingHeader/Structure/JSValue 编码）× V8 对照表、FTL allocation-sinking 类漏洞利用模式、`generateHeapSnapshotForGCDebugging()` addrof、自描述 marker 消除物化顺序不确定、NaN-boxed 指针写入（真对象 + 伪造 double view 补偿）、StringImpl 替换、调试方法 |
| G2 | misc/Speaking Stephen | `$AGENT_DIR(ai)/knowledge-base/audio-modality-attacks.md` | ASR 转录文本→TTS SSML 跨解释器注入链、Whisper `non_speech_tokens` 抑制与组合 BPE token 绕过（token id 表）、可微分对抗音频优化目标函数（log-mel + teacher-forced CE + 16-bit 量化模拟）、ASR 歧义消解（双候选合成+对齐余弦比对）、双引擎转写互补 |

**现有文件补章节（16 个文件、23 个 gap）**:

| Gap(s) | 来源题 | 目标文件 | 补充内容 |
|---|---|---|---|
| G3 | PHP Sandbox Escape | sandbox-escape.md 新 §PHP | disable_functions 非边界（static module entries 的 zif handler 仍驻留）、包装方法暴露序列化引擎（SplDoublyLinkedList::unserialize）、Serializable 共享 var_hash UAF（HashTable 扩容 → R:n 悬挂 → string 复用当 zval）、executor_globals→function_table 定位禁用函数 handler、伪造 Closure 调 zif_system、build 特定偏移（zend_function_entry 0x38）须远程验证 |
| G23 | ycc | sandbox-escape.md §语言实现安全 | lexer 解码与 codegen 转义是两个独立操作；属性名嵌入宿主语言字面量必须过同一编码器；`(char[]){...,0}` 字节数组绕引号 |
| G24 | jailincpython | sandbox-escape.md §1 | comprehension 赋值目标 `{... for obj.attr in {f}}`——赋值语句不可用时对特殊方法名的赋值通道；descriptor binding（`lambda x:x.__getattribute__` → `.__get__`）构造任意属性 getter；根级 glob `cat /*.txt` 应对随机文件名 |
| G4 | readonce | csp-bypass.md §2.3 | nonce 缺陷表新行：服务器模板创建的合法 nonce `<script src>`，src 由攻击者输入控制——无需偷 nonce；检测：找"URL 存入模板变量且渲染进 script src"的路由 |
| G6a | easy-leak | csp-bypass.md 新小节 | CSP 由反代（Caddy/nginx）注入而应用本身不加 → bot 直连上游端口（entrypoint.sh 的 php -S 127.0.0.1:900x）绕过；检测：diff 公开端口响应头 vs 直连上游 |
| G5 | readonce | client-side-attacks.md 新小节 | 命名窗口泄漏：`<form target=name>` GET 提交 + `open('',name)` 取回已有窗口读同源响应 body——绕 `default-src 'none'`（connect-src 拦 fetch 不拦导航/表单） |
| G7 | Neon Skies | client-side-attacks.md cookie tossing 深化 | 同名 `Domain=` shadowing 全链：无 `__Host-` 前缀 → sibling 子域写同名域 cookie；Cookie 头顺序（长 Path 先、同 Path 旧先）构造重复名；服务端重复 cookie 解析差异（Crystal last-wins，PHP 先见者胜——写"必须测目标栈"）；XSS 删 tossing cookie 后 refetch 读 host-only HttpOnly 真值（服务端渲染场景） |
| G8 | mouse in the house | xss-advanced.md §5 新类 | sanitizer 合法属性 → 库 gadget：DOMPurify 保留 `data-*`，PrismJS global.js 读 `data-prism-plugins`/`data-prism-plugin-path` 执行动态 import；80 字符 payload（`data:text/javascript,import(name)` 空属性 + `window.name` 存第二模块）；gadget 复用模式（跨题/跨应用复用同库 gadget 作 stage） |
| G9 | mouse in the house | race-conditions.md §4 补充 | e.source 存活侧：`window.opener = null` 不撤销 `event.source` 恢复的父引用（postMessage 的 source 在投递时求值，发送窗口存活即指向它）——与已沉淀"销毁→null"互补；防御含义：置 null opener 不是断链手段 |
| G10 | PHault | sqli-advanced.md | 无回显无时间差盲注替代 oracle：`SELECT..INTO @var` → `mysqli::query()` 返回 bool → `fetch_row()` on bool 触发 PHP fatal error（响应字节长度区分）；零行/多行行为构造条件位（`0 OR IF(cond,1,0) INTO @x`：真=多行 SQL 错误、假=零行 fatal error） |
| G25 | PwnSec Support | sqli-advanced.md | 空 joined 表使 `OR 1=1` 认证 bypass 失效（无结果行）→ UNION 构造函数期望的列形状（`' UNION SELECT 1,'root' --`） |
| G6b | easy-leak | bot-patterns.md §3 扩展 | bot 网络位置攻击面盘点：读 entrypoint.sh/docker-compose 找上游端口与 sidecar；bot 与容器同网络命名空间 → 127.0.0.1 全端口可达；检查清单形式 |
| G11 | Death Ops | pwn-kernel-methodology.md 新 §LKM | 可加载模块利用链：`/proc/modules` 泄模块独立随机化基址（Live 0xffffffffc... 行）；调用次数限制自续写（任意写重置 .bss 计数器）；模块 .text 本地内核可写 → patch 读原语进 open/release 空洞（count==8 读 / count==16 写复用同一入口）；模块内 `e8 disp32`（call _copy_from_user）重定位 → 内核 KASLR slide；seccomp 不拦 core dump usermode helper 路径 |
| G12 | Freal World | pwn-methodology.md | 无 libc 文件的内存 ELF 解析链：GOT 泄漏 → 页对齐回扫 ELF header → program headers → PT_DYNAMIC → GNU hash 解析符号；`__dso_handle` 自引用重定位泄 PIE（负索引选 R_X86_64_RELATIVE 条目）；mmap threshold 动态调整（free 一个 mmap 块抬阈值）+ 大块 pattern 填充 + 固定步进扫描必中 |
| G13 | Freal World | pwn-methodology.md | fenv 时序缺陷类：`fetestexcept` 在运算**之前**调用 → 溢出标志漏检 → 上溢结果（inf）参与后续逻辑（索引上限扩展）；识别：审计浮点代码的检查/运算顺序 |
| G14 | peekaboo | pwn-methodology.md + crypto-validation-patterns.md | `MAP_FIXED_NOREPLACE` 返回 `-EEXIST` 作地址占用 oracle → 对半二分（16GiB/22 探针定位 4KiB 页，成功探测立即 munmap）；EVP 参数审计：AAD/IV 语义看实际寄存器实参（非变量名），存储布局 `AAD‖tag‖ct` 的判定（解密 InvalidTag 时重审） |
| G15 | jump-v2 | pwn-methodology.md | seccomp 验证 oracle：未知 syscall 正常路径返回 `-ENOSYS` vs seccomp `ERRNO(1)` 返回 `-1` 的可观察差异；间接跳转主导 + SIMD 直线代码的二进制：提取执行基本块路径 + 内存写 + seccomp BPF 反而比重建静态控制流有效；MBA 函数逐指令翻译 Z3 表达式 + 运行时状态对照验证 |
| G16 | Zigerions | packer-handling.md 阶段 2.5.3 扩展 | 多层嵌套（ELF→PyInstaller→VMProtect→GB ROM→伪装 ELF）提取策略：Frida 替换 `ShellExecuteA`/MessageBox 返回值阻止 GUI 分叉 + 在解包完成点按固定 RVA 读资源（比完整脱壳短且可复现）；诱饵层识别：某层元数据（ROM opcode 表）与外层证据矛盾 → 分类 decoy 跳过 |
| G17 | Two Worlds | reverse-patterns.md 新 § | Heaven's Gate 逆向视角：`retf` selector 0x33/0x23 同一字节区域双模式解码——32 位路径验证前半输入、64 位路径验证后半；识别：见 retf + far selector 立即数就对同区域做双 ISA 反汇编 |
| G18 | Constellation | reverse-patterns.md 新 § | repack 对照法：用被分析程序对已知输入打包 → diff 官方文件与自产文件 → 推断容器格式字段/置换/密钥流；RS 擦除（GF(256) 高斯消元）作为逆向障碍的恢复；已知 magic（0x029d5011）作独立校验锚点 |
| G19 | PwnSec Support | vm-bytecode-reversing.md 新小节 | VM 题落点：guest 代码段与数据共享可写内存 + 任意字写原语 → 相对偏移 patch（随机化 padding 改变绝对地址但相对布局稳定）；`tostring(func):match("(%x+)$")` 从函数 repr 泄 guest 地址；NDJSON 指令流提取 DATA_BYTES 恢复嵌入源码 |
| G20 | Gap Gap | rsa-attacks.md 新 § | Common Prime RSA（p-1/q-1 共享素数 g）部分密钥暴露：d 中间 30 位空洞 → 联合模格（f1=x+a1 mod g 权重 1 + f2=y+N+1 mod g² 权重 2，移位 f1^i f2^j (N-1)^r，t=3 → 27 维）；d 补全后连分数：(ed-1)/(N-1) 的收敛子含 k/G → 601-bit 分母即 2g；a,b 由 (a+b)²-4ab 判别式恢复 |
| G21 | tap tap | prng-attacks.md 新 § | 未知模数截断高阶递推：模数接近 2^k → 零化多项式在截断后仍为短格向量（BKZ）；两独立零化多项式结式含 p^order → GCD 恢复模数；F_p[x] GCD 得特征多项式 → taps；状态恢复 BDD 格（居中 Z=W+2^47）+ Babai；坐标缩放（2^128-p 上界 m 倍 → 系数缩放 m）；`C[0]^-1` 倒推初态 |
| G22 | skill issue | exotic-algebra-attacks.md 新 § | 矩阵多项式 mod 隐藏素数：x 与 f(x) 交换 → 逐元素交叉相乘消 p → 短核向量含解（LLL）；标量矩阵歧义 → 对角差枚举 + GCD 恢复 p；块上三角扩展 → 线性化 Sylvester 方程序列；字节界 → LWE/CVP embedding + Babai；Fréchet 导数 f'(A) 消公共标量移位 |

**回归确认项（Phase 0 判定已覆盖，执行时复核而非重写）**: readonce-revenge/readtwice 机制（race-conditions.md §4 等）、pickle 受限逃逸（deserialization.md :89-104）、pyjail 核心（sandbox-escape.md §1）、core_pattern 落点（pwn-kernel-methodology.md :62）。

### 2.2 探针产出（Tier 4 验证）

| 探针目录 | 断言 | 依据 |
|---|---|---|
| `web-analysis/scripts/probe-named-window-leak/` | `form target` + `open('',name)` 可读同源命名窗口响应 body（CSP `default-src 'none'` 下仍成立） | G5 |
| `web-analysis/scripts/probe-opener-recovery/` | popup 内 `window.opener = null` 后，父窗口 `postMessage` 到 popup，popup 收到的 `e.source === 父窗口引用`（非 null） | G9 |

命名遵循既有规范：目录 `probe-<行为域>`、文件 `probe_<断言>.js`、自包含（README + package.json）。验证通过后沉淀；**验证若推翻 writeup 结论，知识按实测写并在该步 progress 记录差异**。

### 2.3 源归档

26 题的 `writeup/en.md` + `solve.py` → `docs/资料/writeup-sources/pwnsec-ctf-2026/<category>/<title>/`（category 按仓库原分：web/pwn/crypto/reverse/misc/forensics）。仅归档这两个文件（flag/instance.json/analysis 不拷）。这是"写入"操作（规则 11 例外允许）。

### 2.4 架构影响

- 无代码改动、无接口变更、无依赖方向问题（纯知识库 .md + 2 个 agent prompt 索引行）
- agent prompt 修改属高风险类：仅各加 1 行知识库索引（binary-analysis.md :230 表、ai-security-analysis.md :232 区），触发条件列按规范写代码形态；加行后检查展开行数仍在限内（binary-analysis.md 现状需复核，若超 450/600 红线仅记录不处理——索引行 1 行不触发实质变化，瘦身需求另行执行）
- jsc-exploitation.md 在 v8-browser-exploitation.md 头部加 1 行互引（"JSC 目标见 …"），反之亦然

## §3 实现规范

### 3.1 改动范围表

| 类型 | 文件 | 动作 |
|---|---|---|
| 新建 | jsc-exploitation.md、audio-modality-attacks.md | Write 创建（各 ~85/~75 行） |
| 编辑 | §2.1 所列 16 个知识库文件 | Edit 局部插入（单文件单批 ≤70 行） |
| 编辑 | agents/binary-analysis.md、agents/ai-security-analysis.md | 各 +1 行索引 |
| 新建 | 2 个探针目录 | Write（探针 + README + package.json） |
| 新建 | docs/资料/writeup-sources/pwnsec-ctf-2026/** | cp 归档 52 文件 |
| 新建 | progress 文档 | 任务进度记录 |

### 3.2 编码规则

- 知识三问结构（什么时候用/怎么检查/怎么利用）+ 双键（技术词 + 代码形态触发情境）
- 零来源叙事（规则 8.0 铁律）：无 CTF/赛事/题目名/实测/复盘/PwnSec 字样；外部技术文献链接（Zheng-Nitaj 论文、Calif 研究、HITCON MRSA 等）允许保留为"参考"
- 排版：列表项/表格单元格内不句中折行；代码块只装命令/代码/结构
- 跨文件引用用 `$AGENT_DIR`/`$SHARED_DIR` 变量
- 每条知识附可操作步骤/payload/成功失败判据；版本边界标注（如 PHP 8.6 build、Chrome 探针版本）

### §3.1 实施步骤

> 每步流程：读原题源码核实 → 写入 → 验证点 → progress 记录（`progress-2026-09-25-pwnsec-ctf-2026-distillation.md`，与本需求文档同目录）。行数为知识文档新增行（不含源码阅读）。**同文件多步必须串行执行（依赖列已标注）；不同文件的步骤可并行。**

**批次 0 准备**

步骤 1. 源归档 + 环境检查
- 文件: docs/资料/writeup-sources/pwnsec-ctf-2026/**（新建 52 文件）；venv 检查
- 预估行数: 0（cp 操作）
- 验证点: 归档目录树 26 题 × {writeup-en.md, solve.py} 齐全（`find … | wc -l` = 52）；`$PYTHON_CMD -c "import flint, sympy"` 通过，缺失则 `$PYTHON_CMD -m pip install python-flint==0.8.0 sympy==1.14.0`（与原仓 requirements.txt 同版本）后复验
- 依赖: 无

**批次 1 方向级（P0）**

步骤 2. G1 JSC 知识文件
- 文件: jsc-exploitation.md（新建）；v8-browser-exploitation.md 头部 +1 行互引；agents/binary-analysis.md +1 索引行
- 预估行数: ~87
- 验证点: ① 原题核实记录——读 challenge/ 的 diff.patch、REVISION、README.md，核对 writeup 声称的 win() 契约与 shell 加固项 ② 文件自包含通读（三问结构 + 双键齐备）③ grep 叙事词清零 ④ 索引行触发条件为代码形态
- 依赖: 1

步骤 3. G2 音频攻击知识文件
- 文件: audio-modality-attacks.md（新建）；agents/ai-security-analysis.md +1 索引行
- 预估行数: ~76
- 验证点: ① 原题核实——读 analysis/optimize_audio.py（目标函数是否含量化模拟）与 compare_espeak.py（余弦比对逻辑），核对 token id 表与 writeup 一致 ② 自包含通读 ③ 叙事词清零
- 依赖: 1

步骤 4. G3 PHP 沙箱章节
- 文件: sandbox-escape.md 新 §PHP
- 预估行数: ~55
- 验证点: ① 原题核实——读 challenge/public/src/php.ini（disable_functions/open_basedir 清单）与 readflag.c setuid，核对 writeup 的 8.6.0-dev/0x38 zend_function_entry 声称有源码或研究支撑 ② 叙事词清零 ③ 与 §1 Python 的"环境变量 RCE"节无重复
- 依赖: 1

步骤 5. G23+G24 沙箱补两节
- 文件: sandbox-escape.md（§语言实现安全新节 + §1 补模式）
- 预估行数: ~35
- 验证点: ① ycc.c 的 y_map_get 代码生成路径确认无 C 转义（grep 属性嵌入点）② jailincpython main.py 过滤器确认（ASCII/800B/2 dots/无引号数字括号）③ 本地仿真：提取 main.py 过滤逻辑喂 G24 payload——过滤器放行 + `compile(payload, '<s>', 'exec')` 语法通过（不实际执行 os.system）④ 叙事词清零
- 依赖: 4

**批次 2 Web（P1）**

步骤 6. G4+G6a CSP 两模式
- 文件: csp-bypass.md（§2.3 表 +1 行；新小节反代 CSP）
- 预估行数: ~55
- 验证点: ① readonce challenge/src/server.js 的 /review→currentReview.document.url 存储路径 + sandbox.ejs 的 nonce script src 模板确认 ② easy-leak challenge 的 entrypoint.sh 四端口 + Caddy CSP 注入确认（bot 直连路径存在）③ 叙事词清零
- 依赖: 1

步骤 7. G5+G9 浏览器探针（编写+运行）
- 文件: web-analysis/scripts/probe-named-window-leak/、probe-opener-recovery/（各: probe_*.js + README + package.json）
- 预估行数: ~160（探针代码）
- 验证点: 两个探针在 Chrome（mac_arm 缓存的 146/148/153 三版本，逐版本跑）输出断言全通过；若断言失败 → 停下按实测修正知识方向，progress 记录
- 依赖: 1

步骤 8. G5+G9 知识写入
- 文件: client-side-attacks.md（命名窗口新小节）、race-conditions.md（§4 存活侧补充 + 探针引用）
- 预估行数: ~40
- 验证点: ① 知识描述与探针实测输出一致 ② client-side-attacks.md（命名窗口节）与 race-conditions.md（§4）的探针引用路径用 $AGENT_DIR 且目录存在 ③ 叙事词清零
- 依赖: 7

步骤 9. G7 cookie tossing 深化
- 文件: client-side-attacks.md（:145 节重写扩充）
- 预估行数: ~45
- 验证点: ① neon_skies.cr 的 HTTP::Cookies#<< 行为 + admin.ecr 无转义 sink 确认 ② Cookie 头排序规则与 RFC 6265 §5.4 语义一致 ③ 服务端解析差异写"须实测目标栈"并给 Crystal/PHP 两例 ④ 与 web-vulnerabilities.md 的 cookie/session 相关内容无重复（先 grep 对照，重复则引用）⑤ 叙事词清零
- 依赖: 1, 8（同文件 client-side-attacks.md 串行）

步骤 10. G8 DOM 属性 gadget
- 文件: xss-advanced.md（§5 新类）
- 预估行数: ~35
- 验证点: ① mouse in the house challenge 的 note 渲染 + DOMPurify 配置确认 data-* 存活 ② PrismJS global.js 的 data-prism-* 读取与 import 行为（writeup 引用的 esm.sh 源或本地 node_modules 复核）③ payload 80 字符约束与原文一致 ④ 叙事词清零
- 依赖: 1

步骤 11. G10+G25 SQL 两点
- 文件: sqli-advanced.md
- 预估行数: ~45
- 验证点: ① PHault 无附件——读 analysis/oracle.md 的请求/响应证据（4557/4744 字节）核对机制描述 ② PwnSec Support challenge 的 check_admin() SQL（l3af 提取的 lua 或 writeup 引用）确认空表 UNION 语境 ③ 叙事词清零
- 依赖: 1

步骤 12. G6b bot 网络盘点
- 文件: bot-patterns.md（§3 扩展）
- 预估行数: ~30
- 验证点: ① easy-leak entrypoint.sh + docker-compose 的网络拓扑与知识描述一致 ② 检查清单可执行（每项有命令或文件位置）③ 叙事词清零
- 依赖: 1

**批次 3 二进制（P1）**

步骤 13. G11 LKM 利用链
- 文件: pwn-kernel-methodology.md 新 §LKM
- 预估行数: ~70
- 验证点: ① 原题核实——解包 rootfs.cpio.gz 提取 shadowops.ko + blackops，核对 writeup 的段布局（.text/.data/.bss 偏移、used 位置）与 e8 disp32 偏移 ② QEMU 复跑（原题 dist/ 启动脚本）solve.py 本地 flag 输出 ③ 叙事词清零
- 依赖: 1

步骤 14. G12+G13 内存 ELF + fenv
- 文件: pwn-methodology.md
- 预估行数: ~65
- 验证点: ① 本地复跑 freal solve.py（x86-64 ELF 须在 Docker `linux/amd64` 容器内跑，原 Dockerfile 为基，socat 包装 + 本地 echo flag）退出码 0 ② fetestexcept 调用顺序在 freal 二进制反汇编中可见（容器内 objdump 确认）③ 叙事词清零
- 依赖: 1

步骤 15. G14+G15 地址 oracle + seccomp oracle
- 文件: pwn-methodology.md、crypto-validation-patterns.md
- 预估行数: ~75
- 验证点: ① 本地复跑 peekaboo solve.py（x86-64 ELF + libcrypto.so.3，Docker `linux/amd64` 容器内跑，本地 dummy flag 解密通过）② jump-v2 的 analysis/filters.bin 存在且 writeup 的 BPF 约束描述与文件可对照 ③ MBA→Z3 一节与 `deobfuscation-selection.md` 已有 MBA 内容无重复（先 grep 对照）④ 叙事词清零
- 依赖: 1, 14（同文件 pwn-methodology.md 串行）

步骤 16. G16 嵌套提取
- 文件: packer-handling.md（阶段 2.5.3 扩展）
- 预估行数: ~35
- 验证点: ① Zigerions analysis/run_frida.py 的 ShellExecuteA 替换 + RVA 读取逻辑与知识描述一致 ② 叙事词清零
- 依赖: 1

步骤 17. G17+G18 逆向两模式
- 文件: reverse-patterns.md（新 2 §）
- 预估行数: ~40
- 验证点: ① Two Worlds challenge/portal33.exe 的 0x4016b3 retf 序列（objdump -d 可见；mac objdump 不支持 PE 时容器内跑或 Python 按 VA 直接读字节 `48 ca 33 00`）核实 ② Constellation 的 repack 对照描述与 writeup 一致 ③ 叙事词清零
- 依赖: 1

步骤 18. G19 VM 落点
- 文件: vm-bytecode-reversing.md（新小节）
- 预估行数: ~20
- 验证点: ① PwnSec Support challenge 的 l3afvm --trace 布局（code/data 区间）与相对偏移描述一致 ② 叙事词清零
- 依赖: 1

**批次 4 密码学（P2）**

步骤 19. G20 Common Prime RSA
- 文件: rsa-attacks.md 新 §
- 预估行数: ~55
- 验证点: ① 本地复跑 Gap Gap solve.py（GAP_GAP_SAMPLE=1 用附件 sample）通过 ② 格构造参数（权重/t=3/27 维）与 analysis/derivation.md 一致 ③ 叙事词清零
- 依赖: 1

步骤 20. G21 未知模数递推
- 文件: prng-attacks.md 新 §
- 预估行数: ~50
- 验证点: ① 本地复跑 tap tap solve.py（纯附件）通过——flag 含"3 days/3 seconds"字样即成功 ② 结式/BDD 描述与 analysis/derivation.md 一致 ③ 叙事词清零
- 依赖: 1

步骤 21. G22 矩阵多项式
- 文件: exotic-algebra-attacks.md 新 §
- 预估行数: ~50
- 验证点: ① 本地复跑 skill issue solve.py（附件输出）通过 ② Sylvester/CVP 阶段描述与 solve.py 实现对照 ③ 叙事词清零
- 依赖: 1

**批次 5 收尾**

步骤 22. 全量回归
- 文件: 无新改动（发现问题则回对应步骤修复）
- 预估行数: 0
- 验证点: ① 全部改动文件（范围限 `.opencode/` 下的知识库 + agent prompt + 探针；**不含 docs/ 归档**——归档目录名本身含仓库名属正常）grep 叙事词（`CTF|比赛|赛事|题目|实测|亲测|复盘|验证过|writeup`）清零，flag 串 `pwnsec{...}` 不得出现在知识示例中 ② 2 个 agent prompt 索引行存在且触发条件为代码形态 ③ 交叉引用路径（$AGENT_DIR/$SHARED_DIR）全部存在 ④ 探针目录 README 判据完整 ⑤ 归档 52 文件在位
- 依赖: 2-21

## §4 验收标准

**功能验收**:
- 25 个 gap（G1-G25）全部落位：2 新文件 + 16 文件补章节内容齐全（对照 §2.1 表逐条核）
- 2 个探针三版本 Chrome 断言通过并沉淀
- 26 题源归档 52 文件在位
- Tier 2/3 复跑记录（crypto 三题、freal、peekaboo、Death Ops QEMU、jailincpython 仿真）进 progress 文档

**回归验收**:
- 已覆盖项（pickle/pyjail 核心/readonce 系机制/core_pattern）内容未被本次改动破坏（diff 复核）
- 16 个被编辑知识库文件的既有章节结构完整（章节标题清单前后对比）
- agent prompt 展开后行数不超红线（或已记录）

**架构验收**:
- 归属正确：crypto 知识仅在 crypto-analysis、AI 语音仅在 ai-security-analysis、web 仅在 web-analysis、pwn/reverse/沙箱在 binary-analysis
- 无 docs/ 目录运行时依赖（归档是写入例外）
- 依赖方向无违反（纯 .md，无代码耦合）

## §5 与现有需求文档的关系

- `2026-09-23-mechanism-corrections-and-retro-methodology.md`: 同源仓库的先序需求（readonce-revenge/readtwice 机制修正）。本需求的 G9 是其 e.source 知识的互补面（存活侧 vs 销毁侧），写入同一 §4。
- `2026-09-23-evolve-prompt-slimming.md`: 无冲突。本需求对 agent prompt 仅 +2 索引行；若 binary-analysis.md 触发瘦身红线，在瘦身需求执行时一并处理，本需求只记录。
- C2 待决项（老文档去向）: 与本需求无关，不受影响。
