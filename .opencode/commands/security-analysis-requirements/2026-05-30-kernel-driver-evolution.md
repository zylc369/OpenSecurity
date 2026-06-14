# 内核驱动分析能力进化

> 来源: ShadowGate 解题复盘（Commit 9f2b2412 沉淀的知识未被 agent 引用）
> 日期: 2026-05-30

---

## §1 背景与目标

ShadowGate（腾讯游戏安全大赛 2026）是一道 Windows 内核驱动 + VMProtect 混淆的逆向题。分析过程中沉淀了 `kernel-driver-analysis.md` 知识库（372 行），并修改了 `dynamic-analysis.md` 和 `packer-handling.md`。

**核心问题**: 沉淀的知识没有被 binary-analysis agent 引用。Agent 不知道知识库存在，无法自动识别内核驱动场景，也没有对应的分析方案。具体表现为:

1. Agent 知识库索引缺少 `kernel-driver-analysis.md` 条目
2. `classify_scene()` 没有 `kernel_driver` 场景标签，无法自动识别 .sys 文件
3. `analysis-planning.md` 缺少内核驱动场景模板
4. `packer-handling.md` 与 `kernel-driver-analysis.md` 内容重叠
5. 引用路径不规范（未使用 `$SHARED_DIR` 变量）
6. kd 会话封装模板不够自包含
7. 缺少双机调试环境自动检测
8. 缺少 VM 密码管理（安全隔离 AI 与密码）

**预期收益**: 下次遇到 .sys 文件时，Agent 能自动识别场景、加载正确知识库、执行双机调试分析路径。

---

## §2 技术方案

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.opencode/agents/binary-analysis.md` | 修改 | 知识库索引添加 kernel-driver-analysis.md 条目 |
| `.opencode/binary-analysis/_analysis.py` | 修改 | classify_scene() 添加 kernel_driver 场景检测 |
| `.opencode/binary-analysis/knowledge-base/analysis-planning.md` | 修改 | 添加 kernel-driver 场景模板 |
| `.opencode/binary-analysis/knowledge-base/packer-handling.md` | 修改 | 精简 VMP 内核驱动章节，引用 kernel-driver-analysis.md |
| `.opencode/binary-analysis/knowledge-base/kernel-driver-analysis.md` | 修改 | 完善 §2.2 封装模板，规范引用路径 |
| `.opencode/binary-analysis/knowledge-base/dynamic-analysis.md` | 修改 | 规范引用路径 |
| `.opencode/binary-analysis/scripts/detect_kernel_debug_env.py` | 新建 | 双机调试环境自动检测脚本 |
| `.opencode/binary-analysis/scripts/vm_login.py` | 新建 | VM 密码管理脚本（密码不经过 AI） |
| `.opencode/binary-analysis/scripts/registry.json` | 修改 | 注册新脚本 |
| `.gitignore` | 修改 | 添加 `.privacy-data/` 排除 |

### 2.2 数据格式

#### privacy-data.json 结构

```json
{
  "kernel_debug_vm": {
    "vmName": "虚拟机名（vmrun 使用）",
    "vmxPath": "VMX 文件路径",
    "accountName": "虚拟机系统登录账号名",
    "passwordEncoded": "Base64 编码的密码"
  }
}
```

路径: `.privacy-data/privacy-data.json`（项目目录下，已加入 .gitignore）

#### classify_scene() 新增输出

```json
{
  "scene_tags": ["kernel_driver"],
  "recommended_actions": [{
    "action": "kernel_driver_analysis",
    "priority": 0,
    "description": "检测到 Windows 内核驱动，需使用双机调试分析",
    "detail": "内核驱动 API 检测: IoCreateDevice, IofCompleteRequest"
  }],
  "knowledge_base_loads": ["kernel-driver-analysis.md"]
}
```

### 2.3 架构影响

```
改动层级:
  _analysis.py (层 2.5) — classify_scene() 增加 kernel_driver 分支
    ↓ 影响下游
  initial_analysis.py (层 3) — 无改动，自动获得新 scene_tags
    ↓ 影响下游
  analysis-planning.md — 新增 kernel-driver 场景模板
  binary-analysis.md — 知识库索引新增条目

新增脚本:
  detect_kernel_debug_env.py — 独立 Python 脚本（不依赖 IDAPython）
  vm_login.py — 独立 Python 脚本（不依赖 IDAPython）

依赖方向: 无违规（只修改 _analysis.py 下游消费方，不反向依赖）
```

---

## §3 实现规范

### 3.0 通用规范

- 所有知识库文件中的引用路径使用 `$SHARED_DIR/knowledge-base/<文件名>` 格式
- 新建脚本放在 `$SHARED_DIR/scripts/` 下（通用能力）
- `.privacy-data/` 目录加入 `.gitignore`

### §3.1 实施步骤拆分

#### 步骤 1. 知识库索引 + 引用路径规范（方案 A + D）

- 文件: `binary-analysis.md`、`dynamic-analysis.md`、`packer-handling.md`、`kernel-driver-analysis.md`
- 预估行数: 修改 4 个文件，合计约 10 行改动
- 验证点:
  1. `binary-analysis.md` 知识库索引包含 `kernel-driver-analysis.md` 条目，触发条件合理
  2. `dynamic-analysis.md` 引用路径改为 `$SHARED_DIR/knowledge-base/kernel-driver-analysis.md`
  3. `kernel-driver-analysis.md` 内部引用（如有）使用 `$SHARED_DIR` 变量
- 依赖: 无

#### 步骤 2. 精简 packer-handling.md VMP 内核驱动章节（方案 C）

- 文件: `packer-handling.md`
- 预估行数: 修改约 15 行（将详细策略替换为"识别 + 重定向"）
- 验证点:
  1. `packer-handling.md` 的 VMP 内核驱动章节精简为识别特征 + 引用 `kernel-driver-analysis.md`
  2. 不再与 `kernel-driver-analysis.md` 内容重复
  3. 触发条件仍为: VMP 段 + .sys 文件
- 依赖: 步骤 1（引用路径已规范）

#### 步骤 3. classify_scene() 增加 kernel_driver 场景（方案 B — 代码部分）

- 文件: `_analysis.py`
- 预估行数: 修改约 25 行
- 验证点:
  1. `classify_scene()` 新增 kernel_driver 检测逻辑:
     - 条件: `import_names` 包含内核驱动特有 API（`IoCreateDevice`、`IofCompleteRequest`、`IoCreateSymbolicLink` 中任意 2 个）
     - 注意: `file_type` 对 .sys 文件返回 `"exe"`（.sys 是 PE 格式），不能用于检测
     - 注意: `entries` 不传入 `classify_scene()`，不能直接检查 DriverEntry。但内核驱动特有 API 足够区分
     - 输出: `scene_tags` 包含 `"kernel_driver"`，`knowledge_base_loads` 包含 `"kernel-driver-analysis.md"`
     - 优先级: 0（最高，packed 之前）
  2. 已有场景标签不受影响（packed/crypto/gui/standard 仍正常工作）
  3. 语法检查通过
- 依赖: 无

#### 步骤 4. analysis-planning.md 增加 kernel-driver 场景模板（方案 B — 文档部分）

- 文件: `analysis-planning.md`
- 预估行数: 新增约 30 行
- 验证点:
  1. 新增"场景：kernel_driver（内核驱动）"模板
  2. 模板包含: 步骤表（环境检测→双机调试→分析）、预期耗时、失败切换
  3. 场景组合优先级更新: kernel_driver 提前（优先于 packed）
  4. 内容自包含，不依赖主 prompt 上下文
- 依赖: 步骤 3（scene_tags 已有 kernel_driver）

#### 步骤 5. 完善 kernel-driver-analysis.md §2.2 封装模板（方案 E）

- 文件: `kernel-driver-analysis.md`
- 预估行数: 修改约 50 行
- 验证点:
  1. `KDSession.exec_commands()` 方法不再有注释省略，完整实现
  2. 包含: .logopen → 写命令到 stdin → 等待 → .logclose → g → qd 完整流程
  3. 模板可独立使用，不依赖读者猜测实现细节
  4. 人工审读确认自包含性
- 依赖: 步骤 1（引用路径已规范）

#### 步骤 6. 新建 detect_kernel_debug_env.py（方案 F）

- 文件: `detect_kernel_debug_env.py`（新建）
- 预估行数: 新增约 150 行
- 验证点:
  1. `python detect_kernel_debug_env.py --output env.json` 执行成功
  2. 检测项:
     - vmrun 是否可用
     - VM 是否在运行（通过 vmrun list）
     - kd.exe 是否存在（从 WinDbg Store 版路径搜索 + 常见路径）
     - VM 是否配置了 NET 调试传输（通过 vmrun runProgramInGuest 执行 bcdedit /dbgsettings）
     - VM 是否配置了自动登录
  3. 输出 JSON 包含每项检测结果 + 缺失项的修复指引
  4. 不依赖 IDAPython（纯 Python + subprocess 调用 vmrun）
  5. 语法检查通过
- 依赖: 无

#### 步骤 7. 新建 vm_login.py（方案 G）

- 文件: `vm_login.py`（新建）
- 预估行数: 新增约 80 行
- 验证点:
  1. `python vm_login.py --help` 执行成功，显示用法
  2. 从 `.privacy-data/privacy-data.json` 读取 VM 配置
  3. 密码为 Base64 编码存储，运行时解码
  4. 通过 vmrun 实现登录（vmrun writeVariable 设置自动登录，或 runProgramInGuest 执行 reg add）
  5. 脚本不输出密码到 stdout（只输出操作结果）
  6. `.privacy-data/` 已加入 .gitignore
  7. 当 `.privacy-data/privacy-data.json` 不存在时，输出友好错误信息和创建指引
  8. 语法检查通过
- 依赖: 无

#### 步骤 8. 更新 registry.json + agent prompt

- 文件: `registry.json`、`kernel-driver-analysis.md`
- 预估行数: 修改约 30 行
- 验证点:
  1. `registry.json` 新增 detect_kernel_debug_env 和 vm_login 两个条目
  2. `kernel-driver-analysis.md` §7 工具部署清单更新，引用新脚本
  3. JSON 格式正确（`python -c "import json; json.load(open(...))"`）
  4. agent prompt 中 kernel-driver-analysis.md 的知识库索引条目触发条件准确
- 依赖: 步骤 6、步骤 7

#### 步骤 9. .gitignore 更新

- 文件: `.gitignore`（项目根目录）
- 预估行数: 新增 1 行
- 验证点:
  1. `.privacy-data/` 在 .gitignore 中
  2. `git status` 不再追踪 `.privacy-data/` 下的文件
- 依赖: 无

---

## §4 验收标准

### 功能验收

- [ ] FA-1: binary-analysis agent 知识库索引包含 kernel-driver-analysis.md，触发条件为"目标为 Windows 内核驱动"
- [ ] FA-2: `classify_scene()` 对 .sys 文件输出 `kernel_driver` 场景标签
- [ ] FA-3: `analysis-planning.md` 包含 kernel-driver 场景模板，步骤完整
- [ ] FA-4: `packer-handling.md` VMP 内核驱动章节精简，不与 kernel-driver-analysis.md 重复
- [ ] FA-5: 所有知识库文件引用路径使用 `$SHARED_DIR` 变量
- [ ] FA-6: `kernel-driver-analysis.md` §2.2 封装模板完整可执行
- [ ] FA-7: `detect_kernel_debug_env.py --output env.json` 执行成功，输出结构化检测结果
- [ ] FA-8: `vm_login.py --help` 执行成功，密码不输出到 stdout
- [ ] FA-9: `registry.json` 包含两个新脚本条目
- [ ] FA-10: `.privacy-data/` 在 .gitignore 中

### 回归验收

- [ ] RA-1: 已有 scene_tags（packed/crypto/gui/standard）不受影响
- [ ] RA-2: 已有知识库文件（dynamic-analysis.md、packer-handling.md）内容无破坏性改动
- [ ] RA-3: `_analysis.py` 语法检查通过，已有函数行为不变

### 架构验收

- [ ] AA-1: 依赖方向合规（_analysis.py 下游消费，不反向依赖）
- [ ] AA-2: 新建脚本位于 `$SHARED_DIR/scripts/`（通用层）
- [ ] AA-3: 密码管理脚本不依赖 IDAPython

---

## §5 与现有需求文档的关系

无冲突。本次改动涉及:
- `_analysis.py` — 上次改动在 2026-05-30 之前，不冲突
- `analysis-planning.md` — 上次改动在 2026-05-24，本次追加章节
- `packer-handling.md` — 上次改动即 Commit 9f2b2412，本次修改同一章节
- `registry.json` — 上次改动在 2026-05-03，本次追加条目
