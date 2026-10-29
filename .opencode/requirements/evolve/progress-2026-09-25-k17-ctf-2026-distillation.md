# K17-CTF-2026 蒸馏进度

## 任务
蒸馏 https://github.com/stack1245/K17-CTF-2026（7 题: pwn×5 / misc×1 / web×1）
需求文档: 同目录 2026-09-25-k17-ctf-2026-distillation.md

## 阶段记录

### 阶段一: 获取与盘点 ✓
- 克隆到临时区，归档 `docs/资料/writeup-sources/k17-ctf-2026/`（排除 .git）
- 计数验证: 源 115 = 归档 115 ✓; 归档名跨平台扫描全过 ✓
- 主读文档: 7 × en.md + 6 × analysis（notes/evidence）= 13 篇

### 阶段二: 精读与 gap 判定 ✓
- 技术点清单 34 条 → gap 判定 13 条（1 方向级 G10 vmsplice + 12 技术点级）
- 已覆盖不沉淀: Apple 2 核心链/格式串两段写/clobbering 基本式/HoS 基本式/pivot 族/canary 基础/base 基本式/WAF 实体编码列表
- 每条 gap 已读对照文件实际内容（pwn-methodology L185-229 表格区、pwn-heap §3a/落点 A、xss-advanced §5、html-parse-differentials 全文、waf-bypass L33、dangling-markup L27/L41）

### 阶段三: 验证分级 ✓
- G3 T1: libc 反汇编 0x29ca6 `callq *%rax` → 0x29ca8 `mov %eax,%edi` → `call exit` 实证
- G4 T1+T3: __gets 反汇编 testb/memset 调用 + 远程 exploit 成功
- G9 T1: `imulq $0x66666667`（div-5 魔数）×2 + 本地 probe LOCAL_CODE_EXECUTION_OK
- G10 T1: main.py L18 FIONREAD → L33 生成 r2 → L44 才 read(128) 时序实证 + 本地复现 "It landed on 67."
- G11 T1: filter.js L239 正则 `;` 必选 + Chrome 153 实证 + 远程成功
- G12 T1: updates.js L90 getAttribute/L95 startsWith 校验 vs L105 new URL(next.href) 使用分离
- G1/G2/G5/G6/G7/G8/G13: writeup 自带本地标记（LOCAL_HOUSE_OF_APPLE_OK）或远程 flag 端到端（T3）
- G4 独立 T2 仿真跳过决策: 已有三层证据（源码行为+远程成功+writeup 描述），边际价值低

### 阶段四: 写入 ✓（§3.1 六步全执行）
1. pwn-methodology G3/G4/G5/G6/G7/G8/G10 ✓（7 条: Eternal Loop ④、递归帧 rbp 枢轴新行、逐 NUL 推进泄漏新行、计数器状态分离并入索引族、vmsplice 新行、逆序短写新行、gadget 素材扩展）
2. G9 负索引取模变体（索引族②）+ pwn-heap HoS 栈上变体/IBT-SHSTK 注记 ✓
3. pwn-heap G1/G2（FILE UAF 两条前置技巧: 初始化长度差保尾泄漏、快照恢复）✓
4. html-parse-differentials §2.5（服务端解码器差异 + base 双表征分离）✓
5. xss-advanced §5 G13（HTMLCollection 多字段配置 + 实体引用构造 + 分片）✓
6. 回归检查执行中

### 阶段五: 回归检查 ✓（全过）
- [x] 叙事词扫描 4 文件新增行零命中（修复后终验仍零）
- [x] 章节编号单调（自查发现"四种→五种"失配并修复; 复审后升级为 §2.6+六种）
- [x] 交叉引用路径存在
- [x] 归档完整性 115=115
- [x] 探针契约 N/A（零新探针）
- [x] git diff: 最终 24 insertions / 6 deletions（删除均为被替换原行，核心内容零删除）
- [x] prompt 索引: 4 文件均既有已索引（web-analysis L189-190、binary-analysis L220-221），零变更

### 阶段六: 独立复审 ✓（一轮收敛）
findings 9 条（中 4 / 低 2 / 信息 3），处理:
- 中1 "Wish\0"偏移硬错误（sh 在偏移 2 非 1）→ 已修复
- 中2 "循环自维持"与流水线句矛盾 → 改"返回点自动复位到已知退出路径、改写可反复进行"
- 中3 base 段错章节+计数失真 → 独立为 §2.6、标题改"六种机制"
- 中4 "标签名复活"不成立（tokenizer 标签名状态不解码字符引用）→ 改"标签名不适用"注记
- 低5 栈上变体 30B 数字不闭合 → 澄清"可控区只需 16B chunk 头，用户区越界写正是利用本身"
- 低6 逆序短写第④步时序前提缺失 → 补"读满即 break、退出判断先于过滤"前提
- 信息7 两处归一化机制描述重复 → 保留（利用/审计互补视角）
- 信息8 既有 L206 裸 | → **复核为误报**（repr 证实已是转义 \|）
- 信息9 正面记录（464/472/0x1d0 自洽、0x29ca8 机制自洽、HTMLCollection 超集关系、引用路径全部有效）
修复项逐一回归验证通过; 按方法论不递归复审。

### 用户触发 review（第三轮，全量 6 findings 已修）
- 中1 whatsNew 题名违反零来源铁律 → 换通用 `w&#105dget`→`widget`（含"六个"→"N 个"通用化; `&#104→h` 机制示例统一改 `&#105→i`）
- 中2 0xa1 误标为 call rax 地址 → 改"序列起始的 mov 指令地址（mov 0x29ca1/call 0x29ca6）+ 只跳 call 时 rax 是返回值非函数指针"
- 中3 假 FILE 原语: 删除错误的"_IO_buf_end 约束"论述（flush 路径不受其约束，已反写为明确豁免句）+ `_flags` 补必需位（置 0x800 清 0x8，典型 0xfbad1800，与既有轻量原语行对齐）
- 低4 "两条前置技巧"实为三条 → 计数修正
- 低5 `new URL()` 表述误导 → 改为 href IDL 属性按 document.baseURI 解析机制
- 低6 splice/sendfile 过度泛化 → 收窄为 vmsplice 专属（sendfile 的 MAP_SHARED 文件变体注明为不同向量）
- 正面确认 6 项（464/472/0x1d0 算术、栈上 HoS、逆序 NUL、实体差异、交叉引用、markdown 完整性）
- 终验: whatsNew/&#104 零残留、叙事零命中、表格完整

## 遗留
- 无


