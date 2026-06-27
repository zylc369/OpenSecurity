# 需求：FactsDroid MITM 复盘进化

## §1 背景与目标

**来源**: FactsDroid 移动端 MITM 分析任务（2026-05-29），任务目录 `workspace/20260529_192558_da4c`。

**痛点数据**:
- 任务目录产生 **381 个文件**，其中 95 个 JS 脚本、74 个 Python 脚本、66 个 Frida 运行日志
- 最终有效产出仅 3 个脚本（root_bypass.js、ssl_bypass_final.js、mitm_v2.js）
- 最大浪费来源：架构判断错误导致所有 x86_64 分析作废；Flutter SSL bypass 没有方法论导致大量试错；MITM 方案选型没有指导；AI 路径遗忘导致无法使用已沉淀的知识库

**预期收益**:
- 下次遇到 Flutter 应用，SSL bypass 直接按方法论走，预计减少 50-70% 的试错脚本和对话轮次
- 彻底消除 AI 路径遗忘导致无法使用知识库的问题
- arm64 无符号逆向有可直接复用的 IDAPython 脚本模板

## §2 技术方案

### 方案 1: Flutter SSL Bypass 方法论

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/flutter-ssl-bypass.md`（新建）

**内容**:
1. 架构确认（第一步必做）：`uname -m` vs `getprop ro.product.cpu.abi`
2. 从设备拉取实际运行的 libflutter.so
3. 定位 TrustBuiltinRoots：字符串搜索 → ADRP+ADD 引用定位 → IDA 反编译确认
4. 调用策略：借鸡生蛋（Hook native peer 提取器，在其 onEnter 中调用）
5. spawn vs attach 策略：Flutter 必须用 spawn（SSL 初始化在启动阶段）
6. 常见失败模式：证书过期（R11 vs R13）、X509_STORE 内存布局

**归属**: `mobile-analysis/knowledge-base/`（Flutter 是移动端特有框架）

### 方案 2a: Plugin 注入频率 10→5 轮

**文件**: `$OPENCODE_ROOT/plugins/security-analysis.ts`（修改 1 行）

**改动**: 第 `shouldInject = session.systemTransformCount % 10 === 1` 改为 `% 5 === 1`

### 方案 2b: 环境信息缺失终止规则

**文件**: `$OPENCODE_ROOT/agents-rules/variable-initialization.md`（追加 3-5 行）

**内容**: 当系统提示中未看到"环境信息"段（含 `$OPENCODE_ROOT` 值）时，必须终止执行并告知用户分析环境出了问题，不要猜测路径。

### 方案 3: arm64 逆向方法论

**文件**: `$OPENCODE_ROOT/binary-analysis/knowledge-base/arm64-reverse-methodology.md`（新建）

**内容**:
1. arm64 字符串引用机制（ADRP+ADD）
2. IDAPython ADRP 搜索脚本模板（可直接复用）
3. 从字符串引用定位到函数的完整流程
4. arm64 常见调用约定和寄存器用途

**归属**: `binary-analysis/knowledge-base/`（arm64 逆向是通用问题）

### 方案 4: MITM 方案选型指南

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/mitm-methodology.md`（新建）

**内容**:
1. 三种 MITM 方案对比（DNS 重定向+代理、SSL bypass+流量拦截、代理证书注入系统 CA）
2. SSL bypass 与流量重定向的冲突分析（本次核心教训）
3. 方案选择决策树

**归属**: `mobile-analysis/knowledge-base/`（MITM 主要在移动端场景）

### 方案 5: Frida Native Shell 技巧

**文件**: `$OPENCODE_ROOT/binary-analysis/knowledge-base/frida-native-shell-tricks.md`（新建）

**内容**:
1. popen + fgets 替代 Java bridge（Java bridge TypeError 问题）
2. NativeFunction 包装 popen/pclose/fgets 的完整代码模板

**归属**: `binary-analysis/knowledge-base/`（native 技巧通用）

### 补充 A: Root Bypass 知识补全

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/mobile-patterns.md`（修改 Root 检测绕过章节）

**内容**: 补充 Native 层 Hook（access/stat/openat）和 Runtime.exec 多重载覆盖

### 补充 B: mobile-analysis prompt 强化 Frida 知识库必读

**文件**: `$OPENCODE_ROOT/agents/mobile-analysis.md`（追加 2-3 行规则）

**内容**: 首次需要操作 frida-server 时必须先读取 `$AGENT_DIR/knowledge-base/mobile-frida.md`

## §3 实现规范

### 改动范围表

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `mobile-analysis/knowledge-base/flutter-ssl-bypass.md` | 新建 | ~180 行 |
| `binary-analysis/knowledge-base/arm64-reverse-methodology.md` | 新建 | ~150 行 |
| `mobile-analysis/knowledge-base/mitm-methodology.md` | 新建 | ~100 行 |
| `binary-analysis/knowledge-base/frida-native-shell-tricks.md` | 新建 | ~60 行 |
| `agents-rules/variable-initialization.md` | 追加 | +5 行 |
| `plugins/security-analysis.ts` | 修改 | 改 1 行 |
| `mobile-analysis/knowledge-base/mobile-patterns.md` | 修改 | +35 行 |
| `agents/mobile-analysis.md` | 追加 | +5 行 |
| `agents/binary-analysis.md` | 追加 | +2 行 |

### 编码规则
- 知识库文件必须自包含（不依赖主 prompt 上下文即可理解）
- 禁止硬编码绝对路径，使用 `$OPENCODE_ROOT`、`$AGENT_DIR`、`$SHARED_DIR` 变量
- IDAPython 脚本模板必须可直接复制到 IDA Console 运行
- 知识库文件写"什么场景、怎么检查、怎么利用"，不写"经验来源"

### §3.1 实施步骤拆分

**步骤 1. 新建 `flutter-ssl-bypass.md`**
- 文件: `mobile-analysis/knowledge-base/flutter-ssl-bypass.md`
- 预估行数: ~180 行
- 验证点: 人工通读确认自包含性 + 引用路径使用 `$AGENT_DIR`/`$SHARED_DIR` 变量

**步骤 2. 新建 `arm64-reverse-methodology.md`**
- 文件: `binary-analysis/knowledge-base/arm64-reverse-methodology.md`
- 预估行数: ~150 行
- 验证点: IDAPython 脚本模板可复制到 IDA Console 运行（语法正确）+ 自包含性

**步骤 3. 新建 `mitm-methodology.md`**
- 文件: `mobile-analysis/knowledge-base/mitm-methodology.md`
- 预估行数: ~100 行
- 验证点: 自包含性 + 决策树逻辑清晰

**步骤 4. 新建 `frida-native-shell-tricks.md`**
- 文件: `binary-analysis/knowledge-base/frida-native-shell-tricks.md`
- 预估行数: ~60 行
- 验证点: 代码模板语法正确 + 自包含性

**步骤 5. 修改 `agents-rules/variable-initialization.md`**
- 文件: `agents-rules/variable-initialization.md`
- 预估行数: +5 行
- 验证点: 规则表述明确，"终止执行"指令无歧义
- 依赖: 无

**步骤 6. 修改 `plugins/security-analysis.ts`**
- 文件: `plugins/security-analysis.ts`
- 预估行数: 改 1 行（`% 10` → `% 5`）
- 验证点: `node --check plugins/security-analysis.ts`
- 依赖: 无

**步骤 7. 修改 `mobile-patterns.md` Root bypass 章节**
- 文件: `mobile-analysis/knowledge-base/mobile-patterns.md`
- 预估行数: +35 行
- 验证点: 代码示例语法正确 + 与已有 Root 检测绕过章节衔接自然
- 依赖: 无

**步骤 8. 修改 `mobile-analysis.md` prompt 强化 Frida 必读**
- 文件: `agents/mobile-analysis.md`
- 预估行数: +3 行
- 验证点: 规则位置在核心规则段（不只是知识库索引段）
- 依赖: 无

**步骤 9. 更新 mobile-analysis agent 知识库索引**
- 文件: `agents/mobile-analysis.md`（知识库索引表）
- 预估行数: +2 行（flutter-ssl-bypass.md 和 mitm-methodology.md 的索引条目）
- 验证点: 索引表包含所有新建的 mobile-analysis 文件 + 触发条件描述准确
- 依赖: 步骤 1、3

**步骤 10. 更新 binary-analysis agent 知识库索引**
- 文件: `agents/binary-analysis.md`（知识库索引表）
- 预估行数: +2 行（arm64-reverse-methodology.md 和 frida-native-shell-tricks.md 的索引条目）
- 验证点: 索引表包含所有新建的 binary-analysis 文件 + 触发条件描述准确
- 依赖: 步骤 2、4

## §4 验收标准

### 功能验收
- [ ] `flutter-ssl-bypass.md` 覆盖架构确认、定位、调用、spawn 策略、失败模式 5 个主题
- [ ] `arm64-reverse-methodology.md` 包含可直接复用的 IDAPython ADRP 搜索脚本模板
- [ ] `mitm-methodology.md` 包含方案对比表和决策树
- [ ] `frida-native-shell-tricks.md` 包含 popen/fgets 完整代码模板
- [ ] `variable-initialization.md` 包含"环境信息缺失时终止执行"规则
- [ ] `security-analysis.ts` 注入频率已改为 5 轮
- [ ] `mobile-patterns.md` Root bypass 章节补充了 Native 层 Hook
- [ ] `mobile-analysis.md` prompt 包含"首次操作 frida 必须先读 mobile-frida.md"规则
- [ ] `mobile-analysis.md` 知识库索引表包含所有新建的 mobile-analysis 文件
- [ ] `binary-analysis.md` 知识库索引表包含所有新建的 binary-analysis 文件

### 回归验收
- [ ] 所有已有知识库文件未被破坏（内容完整、路径引用正确）
- [ ] `security-analysis.ts` 语法检查通过
- [ ] `agents-rules/variable-initialization.md` 改动不影响其他 agent 的规则加载

### 架构验收
- [ ] 所有新文件放置在正确的目录（归属规则符合进化 prompt 的架构图）
- [ ] 新文件之间无循环依赖
- [ ] 引用路径全部使用变量（`$OPENCODE_ROOT`/`$AGENT_DIR`/`$SHARED_DIR`），无硬编码绝对路径

## §5 与现有需求文档的关系

本次进化独立于之前所有需求文档。不修改已有需求文档的任何内容。
