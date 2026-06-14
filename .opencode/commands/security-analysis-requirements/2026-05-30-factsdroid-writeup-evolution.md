# 需求：FactsDroid Writeup 复盘进化（第二轮）

## §1 背景与目标

**来源**: 对 `docs/解题报告/mobile/factsdroid-mitm-writeup.md`（1687 行）的深度复盘，对照当前 mobile-analysis agent 知识库识别遗漏。

**发现的问题**:
- `mobile-methodology.md` 多路径决策树缺少 Flutter 应用识别和分析路径（路径 6），AI 遇到 Flutter 应用会盲走 Java 分析路径
- `mobile-patterns.md` Root bypass 的 openat Hook 用 onLeave 改返回值（可能泄露 fd），writeup 明确应在 onEnter 中替换路径参数
- 无 TLS 流量拦截模式参考（connect 追踪 fd + read 检测 TLS AppData），这是 MITM 流量拦截的标准模式
- `mitm-methodology.md` 方案 A（DNS 重定向）缺少具体技术细节（getaddrinfo Hook + connect 端口重定向字节序处理）

**预期收益**:
- AI 遇到 Flutter 应用直接进入正确路径，减少 3-5 轮试错
- openat Hook 策略修正后避免 fd 泄露
- TLS 流量拦截有可直接复用的模式
- DNS 重定向有字节序处理的正确参考

## §2 技术方案

### 方案 A: mobile-methodology.md 增加 Flutter 分析路径

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/mobile-methodology.md`（修改）

**改动**:
1. 在 APK 多路径决策树中增加路径 6（Flutter 应用分析）
2. 在场景 → 路径映射表中增加 Flutter 相关关键词行
3. Flutter 识别特征清单（libflutter.so + flutter_assets/ + kernel_blob.bin + 单 Activity）

### 方案 B: mobile-patterns.md openat Hook 策略修正

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/mobile-patterns.md`（修改）

**改动**: openat 从工厂函数中拆出来，改为 onEnter 中替换路径参数（避免 fd 泄露），保留工厂函数给 access 和 stat

### 方案 C: 新建 tls-traffic-interception.md

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/tls-traffic-interception.md`（新建）

**内容**:
1. TLS 记录格式速查（类型字段：0x16 Handshake / 0x17 AppData / 0x15 Alert）
2. connect() Hook 追踪 SSL fd 的完整代码模板
3. read() Hook 检测 TLS AppData 的完整代码模板
4. 与 MITM 方案的关系引用

### 方案 D: mitm-methodology.md 增加 DNS 重定向技术细节

**文件**: `$OPENCODE_ROOT/mobile-analysis/knowledge-base/mitm-methodology.md`（修改）

**改动**: 在 §3.3 方案 A（纯代理）段落后增加 DNS 重定向实现细节：
1. getaddrinfo Hook 做 DNS 重定向
2. connect Hook 做端口重定向（含大端序字节处理）
3. 注意事项（仅对无 SSL pinning 应用有效）

## §3 实现规范

### 改动范围表

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `mobile-analysis/knowledge-base/mobile-methodology.md` | 修改 | +35 行 |
| `mobile-analysis/knowledge-base/mobile-patterns.md` | 修改 | +15 行（net 0，拆 openat 但删工厂调用中的 openat 行） |
| `mobile-analysis/knowledge-base/tls-traffic-interception.md` | 新建 | ~90 行 |
| `mobile-analysis/knowledge-base/mitm-methodology.md` | 修改 | +40 行 |
| `agents/mobile-analysis.md` | 修改 | +1 行（索引条目） |

### 编码规则
- 知识库文件必须自包含
- 禁止硬编码绝对路径，使用 `$OPENCODE_ROOT`、`$AGENT_DIR`、`$SHARED_DIR` 变量
- 代码模板可直接复制使用

### §3.1 实施步骤拆分

**步骤 1. mobile-methodology.md 增加 Flutter 分析路径**
- 文件: `mobile-analysis/knowledge-base/mobile-methodology.md`
- 预估行数: +35 行
- 验证点: 决策树有路径 6 + 映射表有 Flutter 关键词 + 识别特征清单完整
- 依赖: 无

**步骤 2. mobile-patterns.md openat Hook 策略修正**
- 文件: `mobile-analysis/knowledge-base/mobile-patterns.md`
- 预估行数: +15 行
- 验证点: openat 在 onEnter 中替换路径参数 + access/stat 仍用工厂函数 + 注释说明原因
- 依赖: 无

**步骤 3. 新建 tls-traffic-interception.md**
- 文件: `mobile-analysis/knowledge-base/tls-traffic-interception.md`
- 预估行数: ~90 行
- 验证点: TLS 记录格式速查 + connect/read Hook 代码模板完整可复用 + 自包含性
- 依赖: 无

**步骤 4. mitm-methodology.md 增加 DNS 重定向技术细节**
- 文件: `mobile-analysis/knowledge-base/mitm-methodology.md`
- 预估行数: +40 行
- 验证点: getaddrinfo Hook + connect 端口重定向代码完整 + 字节序处理正确
- 依赖: 无

**步骤 5. mobile-analysis.md 索引更新**
- 文件: `agents/mobile-analysis.md`
- 预估行数: +1 行（tls-traffic-interception.md 索引条目）
- 验证点: 索引表包含新文件 + 触发条件描述准确
- 依赖: 步骤 3

## §4 验收标准

### 功能验收
- [ ] `mobile-methodology.md` 有路径 6（Flutter），包含识别特征和分析步骤
- [ ] `mobile-methodology.md` 场景映射表有 "Flutter"、"libflutter"、"Dart" 关键词行
- [ ] `mobile-patterns.md` openat Hook 在 onEnter 中替换路径参数（不是 onLeave 改返回值）
- [ ] `tls-traffic-interception.md` 包含 TLS 记录格式速查和完整的 connect+read Hook 代码模板
- [ ] `mitm-methodology.md` 方案 A 包含 getaddrinfo DNS Hook 和 connect 端口重定向的实现代码
- [ ] `mobile-analysis.md` 索引表包含 `tls-traffic-interception.md`

### 回归验收
- [ ] 所有已有知识库文件未被破坏
- [ ] mobile-methodology.md 的路径 1-5 不受影响
- [ ] mobile-patterns.md 的 access/stat Hook 仍正常工作

### 架构验收
- [ ] 新文件放置在 `mobile-analysis/knowledge-base/`（归属正确）
- [ ] 引用路径全部使用变量，无硬编码绝对路径

## §5 与现有需求文档的关系

本次进化独立于 `2026-05-30-factsdroid-mitm-evolution.md`。上一轮新建的 4 个知识库文件不修改（flutter-ssl-bypass.md、arm64-reverse-methodology.md、frida-native-shell-tricks.md 不动），本轮只修改/新建与本轮痛点直接相关的文件。
