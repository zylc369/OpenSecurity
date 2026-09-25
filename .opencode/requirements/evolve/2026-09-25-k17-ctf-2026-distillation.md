# K17-CTF-2026 整库蒸馏

## §1 背景与目标

- 来源: 用户指令"蒸馏 https://github.com/stack1245/K17-CTF-2026"
- 素材: 7 题（pwn×5、misc×1、web×1），源已归档 `docs/资料/writeup-sources/k17-ctf-2026/`（115 文件，计数与归档一致）
- 预期收益: 13 条 gap（1 方向级 + 12 技术点级）沉淀进 4 个既有知识库文件，零新建文件

## §2 技术方案（gap 落位总表）

| # | gap 内容（来源题） | 类型 | 落位 | 置信度 | 验证 |
|---|---|---|---|---|---|
| G3 | `__libc_start_main` 返回路径单字节 partial overwrite 重入 main（0x29ca8→0x29ca1，低 12 位 ASLR 不变）; 每次 call 重推返回地址 → 写与重定向跨两次调用流水线（huge binary 2） | 技术点级 | pwn-methodology Eternal Loop 族 | 高 | T1 反汇编 |
| G4 | 过滤只清当前 read 返回范围 buf[0:n] 不清历史后缀 → 逆序短写（大偏移→小偏移）安装 NUL 同时保留已建 ROP 后缀（waf） | 技术点级 | pwn-methodology 输入处理族 | 高 | T1+T3 远程 |
| G5 | 计数器与写位置状态分离: 归一化分支 counter-- 但 `buffer[strlen]` 仍填充 → 无界写; alnum 跳过归一化可保留指针终止字节（not json） | 技术点级 | pwn-methodology 索引/边界缺陷族 | 高 | T3 远程 |
| G6 | 逐 NUL 推进泄漏: 非 alnum 填充连吃 NUL + 尾部 alnum 填指针 NUL 字节 → %s 连续泄漏 canary/stack/PIE; 定长描述终止符恰好恢复 canary 首字节 0x00（not json） | 技术点级 | pwn-methodology 泄漏族 | 高 | T3 远程 |
| G7 | 等尺寸递归帧（rbp 每次 -0x70）+ 强制栈对齐帧 → 帧指针槽位置确定 → 单字节 saved rbp 改写按深度定位、leave;ret 枢轴进祖先缓冲区假帧（not json） | 技术点级 | pwn-methodology 栈迁移变体 | 高 | T3 远程 |
| G8 | 非 No-PIE 小二进制 gadget 素材: 指令立即数字节内非对齐 gadget（mov eax,imm32 内 pop rdi）、既有字符串后缀（"Wish\0" 含 "sh\0"）（make-a-wish / not json） | 技术点级 | pwn-methodology ROP 素材族 | 中高 | T3 远程 |
| G9 | 负索引别名相邻栈指针 → 任意 free → 栈上 House of Spirit → malloc 返回栈内存覆盖 ret; IBT/SHSTK 属性广告 ≠ 运行时强制（make-a-wish） | 技术点级 | pwn-methodology 负索引族 + pwn-heap §3a HoS | 高 | T1 魔数+T3 |
| G10 | vmsplice 管道缓冲区可变性: FIONREAD 只计不消费 + MAP_SHARED 页 vmsplice 后改源页 = 改未消费管道内容 → commit-reveal 后改写; 修复 = 先读入不可变 bytes（spot） | **方向级** | pwn-methodology 逻辑/时序漏洞族 | 高 | T1 源码+本地复现 |
| G1 | 分配尺寸 vs 应用初始化长度差: 464 初始化 / 472 usable → 尾部 0x1d0 的 _IO_wfile_jumps 保留 → %s 续读泄漏 libc（ihyh） | 技术点级 | pwn-heap FILE 段 | 高 | T3 本地标记 |
| G2 | tcache 投毒落入 libc 数据区: 472B 区域含 stdin 引用的 wide-data 状态 → 清空破坏 scanf → 快照运行时内容恢复后仅改末 qword（_IO_list_all）（ihyh） | 技术点级 | pwn-heap FILE/tcache 段 | 高 | T3 本地标记 |
| G11 | 服务端实体解码器 vs 浏览器字符引用消费差异: 解码正则 `;` 必选 → 无分号数字引用（&#104）只在浏览器侧复活 → 黑名单词进 id/name/href 构造 clobbering 锚点（whatsNew） | 技术点级 | html-parse-differentials 新增机制节 | 高 | T1 正则+Chrome 实证 |
| G12 | `<base>` 使属性校验与 URL 使用信任边界分离: getAttribute('href') 原始值过 startsWith 检查、.href 解析值被 base 改写指向攻击者域（whatsNew） | 技术点级 | html-parse-differentials 同新节 | 高 | T1 源码 L90/95/105 |
| G13 | HTMLCollection 多字段配置对象整体 clobbering: 重复 id 的多 name 属性 anchor 命名属性即配置字段; 长度限制下跨 category 分片（whatsNew） | 技术点级 | xss-advanced §5 补形态 | 中 | T3 远程 |

已覆盖不重复沉淀: House of Apple 2 核心链（pwn-heap 落点 A）、格式串栈指针链两段写（pwn-methodology）、DOM clobbering 基本式（xss-advanced §5）、HoS 基本式（pwn-heap §3a）、栈 pivot 方法族（L191）、canary 基础泄漏法（L128）、base 劫持基本式（dangling-markup）、WAF 实体编码列表（waf-bypass）。

## §3 实现规范

- 改动范围: 4 个既有知识库文件局部 Edit，零新建文件、零代码脚本
- 编码规则: 知识零来源叙事（无题名/赛事名/来源）; 触发条件+步骤+判断标准; 具体值（offset/魔数/payload）
- 全部条目为"补条目/补行"形态，插入对应表格或小节，编号单调

### §3.1 实施步骤

1. pwn-methodology.md 补 G3/G4/G5/G6/G7/G8/G10（7 条，约 18 行）
   - 文件: binary-analysis/knowledge-base/pwn-methodology.md
   - 预估行数: ≤ 20
   - 验证点: 7 条各自落在预定表格行; 语法（markdown 表格完整性）; 词边界叙事扫描零新增
   - 依赖: 无
2. pwn-methodology.md 补 G9 + pwn-heap §3a 补栈上 HoS 变体句（约 4 行）
   - 文件: 同上 + pwn-heap-methodology.md
   - 预估行数: ≤ 6
   - 验证点: 两处各一句; 表格/段落完整
   - 依赖: 步骤 1（同文件串行）
3. pwn-heap-methodology.md 补 G1/G2（约 7 行）
   - 文件: pwn-heap-methodology.md
   - 预估行数: ≤ 8
   - 验证点: FILE 段与 tcache 段各就位
   - 依赖: 步骤 2（同文件串行）
4. html-parse-differentials.md 新增 §2.5 服务端解码器差异（G11+G12，约 16 行）
   - 文件: web-analysis/knowledge-base/html-parse-differentials.md
   - 预估行数: ≤ 18
   - 验证点: 章节编号单调（2.5 在 2.4 后）; §3/§4/§5 编号不变; 自包含
   - 依赖: 无
5. xss-advanced.md §5 补 G13（约 3 行）
   - 文件: web-analysis/knowledge-base/xss-advanced.md
   - 预估行数: ≤ 4
   - 验证点: clobbering 段落完整; 与 L95 基本式不重复
   - 依赖: 无
6. 回归检查（阶段五 7 项）+ 独立复审派发
   - 文件: progress 记录
   - 验证点: 扫描命令与结果留痕; 复审 findings 全修

## §4 验收标准

- 功能: 13 条 gap 全部落位，内容含触发条件/操作/判断标准
- 回归: 4 文件既有结构不变（编号单调、收尾节位置）; 叙事词扫描零新增; git diff 无核心内容删除
- 架构: 零新建文件; 归属符合 architecture-map（方向专属进各方向 KB）; prompt 索引无需变更（均为既有已索引文件）

## §5 与现有需求文档关系

- 独立任务; 模式沿用 PwnSec-CTF-2026 蒸馏（已完结）的补条目范式
