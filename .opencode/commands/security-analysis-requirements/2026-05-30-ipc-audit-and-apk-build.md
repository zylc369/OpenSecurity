# 需求文档：Android IPC 审计知识 + APK 构建脚本

> 来源：AndroPseudoProtect 分析复盘（2026-05-30）
> 痛点：IPC 漏洞模式未沉淀 + 手动编译 APK 占 50% 时间

---

## §1 背景与目标

### 方案 A：Android IPC 安全审计知识

**背景**：mobile-patterns.md 覆盖了 SSL Pinning、Root 检测、混淆、反调试，但缺少 IPC 漏洞模式（exported component、permission 缺失、broadcast 劫持、service 伪造）。本次 AndroPseudoProtect 分析中，IPC 漏洞是核心攻击面，但知识库中没有对应指导。

**目标**：在 mobile-patterns.md 中新增「IPC 安全漏洞」章节，覆盖 exported component 审计清单、常见 permission 配置错误、broadcast/service 劫持利用方法。

**预期收益**：下次遇到类似应用时，AI 直接按清单审计 IPC 组件，减少 1-2 轮探索。

### 方案 B：命令行 APK 构建脚本

**背景**：本次分析中手动编译 PoC APK 花了 4 分钟（5 步手工操作），包括 aapt2 compile → link → javac → d8 → zip → zipalign → apksigner，期间遇到 3 个错误需要逐一排查。

**目标**：创建 `build_apk.py` 脚本，一键完成从源码目录到签名 APK 的全过程。

**预期收益**：从 4 分钟缩短到 30 秒，减少 3-4 轮调试。

---

## §2 技术方案

### 方案 A：在 mobile-patterns.md 末尾追加章节

**改动文件**：`$OPENCODE_ROOT/mobile-analysis/knowledge-base/mobile-patterns.md`

**新增内容**：`## IPC 安全漏洞` 章节，包含：

1. Exported Component 审计清单（表格形式，列出组件类型 + 危险信号 + 检查方法）
2. Permission 配置审计（正确 vs 错误示例对比）
3. Broadcast 劫持利用（攻击步骤 + payload 示例）
4. Service 伪造利用（攻击步骤 + payload 示例）
5. 防御建议（表格化，每条防御对应一个攻击向量）

**预估行数**：~100 行

### 方案 B：创建 build_apk.py 脚本

**新增文件**：`$OPENCODE_ROOT/mobile-analysis/scripts/build_apk.py`

**功能**：
- 输入：源码目录（含 AndroidManifest.xml + java 源码 + res 资源）
- 输出：签名 APK 文件
- 自动检测 Android SDK 路径（ANDROID_HOME 环境变量）
- 自动检测最新 build-tools 版本
- 自动检测最新 platform 版本
- 支持自定义 keystore（默认使用 debug.keystore）
- 完整的错误处理和进度输出

**更新文件**：`$OPENCODE_ROOT/mobile-analysis/scripts/registry.json`
- 追加 build_apk 的注册条目

**预估行数**：~150 行 Python

---

## §3 实施规范

### §3.1 实施步骤拆分

**步骤 1. 方案 A：在 mobile-patterns.md 末尾追加 IPC 安全漏洞章节**
- 文件：`$OPENCODE_ROOT/mobile-analysis/knowledge-base/mobile-patterns.md`
- 预估行数：+100 行
- 验证点：
  1. 人工阅读确认内容准确、自包含
  2. 确认引用路径使用 `$AGENT_DIR`/`$SHARED_DIR` 变量
  3. 确认不与现有章节重复
  4. grep 确认无"经验来源"等禁止内容

**步骤 2. 方案 B：创建 build_apk.py 脚本**
- 文件：`$OPENCODE_ROOT/mobile-analysis/scripts/build_apk.py`（新建）
- 预估行数：~150 行
- 验证点：
  1. `python -c "compile(open('<file>').read(), '<file>', 'exec')"` 语法检查通过
  2. `$PYTHON_CMD build_apk.py --help` 输出使用说明
  3. 使用本次 AndroPseudoProtect PoC 项目做端到端构建验证
  4. 构建产物可被 `adb install` 安装

**步骤 3. 方案 B：更新 registry.json**
- 文件：`$OPENCODE_ROOT/mobile-analysis/scripts/registry.json`
- 预估行数：+12 行
- 验证点：
  1. `python -c "import json; json.load(open('<file>'))"` JSON 格式正确
  2. 与现有条目格式一致

**步骤 4. 方案 B：更新 mobile-analysis agent prompt 索引**
- 文件：`$OPENCODE_ROOT/agents/mobile-analysis.md`
- 预估行数：+2 行（在工具清单的移动端工具表中追加一行）
- 验证点：
  1. 表格格式与现有条目一致

### 依赖关系

步骤 1 独立，步骤 2 → 步骤 3 → 步骤 4 有序依赖。

---

## §4 验收标准

### 功能验收

- [ ] mobile-patterns.md 包含「IPC 安全漏洞」章节，覆盖 exported/permission/broadcast/service 四个维度
- [ ] build_apk.py 可从源码目录生成签名 APK
- [ ] registry.json 包含 build_apk 注册条目
- [ ] mobile-analysis.md 工具清单包含 build_apk

### 回归验收

- [ ] 现有 mobile-patterns.md 的 SSL Pinning、Root 检测等章节未被破坏
- [ ] 现有 registry.json 的 manage_frida、dex_dump、mitm_proxy 条目未被破坏
- [ ] mobile-analysis.md 的其他工具表条目未被破坏

### 架构验收

- [ ] 新增脚本放在 `$OPENCODE_ROOT/mobile-analysis/scripts/`（移动端特有）
- [ ] 新增知识放在 `$OPENCODE_ROOT/mobile-analysis/knowledge-base/`（移动端特有）
- [ ] 未引入新的目录或文件位置
- [ ] 依赖方向正确：mobile-analysis 不引用 web-analysis 的内容

---

## §5 与现有需求文档的关系

无直接关联。本次改进是独立的知识沉淀 + 工具增强。
