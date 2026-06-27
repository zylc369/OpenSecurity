# Mobile Analysis Agent 基础设施搭建

> 日期: 2026-04-29（2026-04-30 修订）
> 来源: 架构讨论 — 用户需要分析 Android + iOS 移动端应用，当前仅支持 PC 二进制逆向
> 状态: 待实施

---

## §1 背景与目标

### 问题

当前 BinaryAnalysis Agent 完全围绕 IDA Pro 设计，无法处理移动端特有的分析需求：

1. **APK 分析**：需要 apktool 解包+反汇编（DEX→smali）→ jadx 反编译（DEX→Java）→ IDA Pro 分析 .so native 层。且存在多种分析路径：纯 Java/Kotlin 逻辑、smali 级精读（混淆严重时）、native 层、Hybrid/WebView 前端、Java↔Native 跨层调用，当前 Agent 不编排这些工具也无法选择路径
2. **IPA 分析**：需要 otool/nm 分析 Mach-O 符号 → IDA Pro 分析 .dylib/Mach-O，当前无相关能力
3. **移动端 Frida**：需要设备端 frida-server 部署（安全安装：随机名+随机路径+非默认端口）→ 主机端连接，与 PC 端 Frida 用法差异大
4. **多 Agent 架构缺失**：Plugin 无差别注入环境信息，config.json 无移动端工具配置，detect_env.py 不检测移动端工具，无设备状态管理

### 目标

1. **新增 mobile-analysis Agent**（primary agent），可分析 APK/IPA，编排移动端工具链，支持多分析路径选择
2. **Plugin 按 Agent 注入**不同环境信息：
   - binary-analysis：IDA Pro 路径、编译器、Python 包
   - mobile-analysis：移动端工具路径（从 config.json tools 按 agents 字段过滤）+ IDA Pro 路径 + 编译器 + Python 包
3. **config.json 重构**：删除 `scripts_dir`（由 Plugin 从 agent 名动态推导）；tools 值从"路径字符串"升级为"数据结构"（含 agent 过滤、必选标记、版本检测命令）
4. **detect_env.py 重构**：新增从 config.json 读取工具配置的能力，按 `version_cmd` 检测可用性，支持 `--agent` 参数按需检测
5. **压缩恢复**：COMPACT_REMINDER 动态化（agent 未知时提醒用户确认）；压缩状态通用部分 + 按 agent 动态追加

### 非目标（P1+）

- 移动端 Frida 完整集成（device.json 框架搭建在 P0，完整的设备管理 GUI 在 P1）
- 移动端工具封装脚本（apk_unpack.py 等，按需沉淀，不在基础设施中）
- IDA 远程调试移动设备 .so（P2，静态分析+Unicorn+Frida 已覆盖大部分场景）
- Web Analysis Agent（P3）
- Vulnerability Research Agent（P4）

### 约束

- binary-analysis/ 目录不动。mobile-analysis 通过 `$IDA_SCRIPTS_DIR` 路径引用 binary-analysis/ 下的 IDA 脚本和通用知识库
- binary-analysis Agent 的行为不受影响（回归验证）
- Agent prompt < 450 行
- env_cache.json 不拆分（all-in-one，Plugin 按需读取子集）

---

## §2 技术方案

### 2.1 目标架构

```
.opencode/
├── agents/
│   ├── binary-analysis.md        # 已有（轻微修改：删除 scripts_dir 依赖）
│   └── mobile-analysis.md        # 新增：移动应用分析 Agent
│
├── plugins/
│   └── security-analysis.ts      # 改造：按 Agent 注入 + 动态 compacting + tools 过滤
│
├── binary-analysis/              # 已有（不动）
│   ├── query.py                  # 通用 IDA 脚本，mobile-analysis 通过 $IDA_SCRIPTS_DIR 引用
│   ├── update.py
│   ├── scripts/
│   │   ├── detect_env.py         # 改造：新增从 config.json 读取工具配置
│   │   ├── create_task_dir.py    # 通用，mobile-analysis 通过 $IDA_SCRIPTS_DIR 引用
│   │   ├── gui_*.py              # PC 专用，仅 binary-analysis 使用
│   │   └── process_patch.py      # PC 专用
│   └── knowledge-base/
│       ├── frida-hook-templates.md    # 通用 Frida 模板，mobile-analysis 也引用
│       ├── unicorn-templates.md       # 通用 Unicorn 模板
│       ├── gui-automation.md          # PC 专用
│       └── ...
│
└── mobile-analysis/              # 新增：移动端工具与知识库
    ├── README.md
    ├── scripts/                  # 预留，未来放 mobile 特有脚本
    │   └── registry.json         # 初始为空
    └── knowledge-base/
        ├── android-tools.md      # Android 工具安装 + CLI 参考
        ├── ios-tools.md          # iOS 工具安装 + CLI 参考
        ├── mobile-methodology.md # 移动端分析方法论（多路径分析决策）
        ├── mobile-frida.md       # 移动端 Frida（安全部署 + 连接 + Hook）
        └── mobile-patterns.md    # 常见安全模式（证书固定、root 检测等）
```

**变量约定**：

| 变量 | 含义 | binary-analysis | mobile-analysis |
|------|------|----------------|-----------------|
| `$SCRIPTS_DIR` | 本 Agent 的工具目录 | `.opencode/binary-analysis/` | `.opencode/mobile-analysis/` |
| `$IDA_SCRIPTS_DIR` | 共享 IDA Pro 通用脚本目录 | 等于 `$SCRIPTS_DIR` | `.opencode/binary-analysis/` |

两个变量各指一个目录，不存在"一个变量指向两个目录"。mobile-analysis 的 Agent prompt 中：
- 自身知识库和脚本 → `$SCRIPTS_DIR/knowledge-base/xxx.md`、`$SCRIPTS_DIR/scripts/xxx.py`
- 通用 IDA 脚本 → `$IDA_SCRIPTS_DIR/query.py`、`$IDA_SCRIPTS_DIR/scripts/initial_analysis.py`
- 通用 Frida/Unicorn 模板 → `$IDA_SCRIPTS_DIR/knowledge-base/frida-hook-templates.md`

**依赖方向**：mobile-analysis **只读** `$IDA_SCRIPTS_DIR/` 下的所有文件，**不修改**。如需定制，在 `$SCRIPTS_DIR/` 下创建独立版本。

### 2.2 config.json 结构变更

**变更前**：
```json
{
  "ida_path": "/Applications/IDA Professional 9.1.app/Contents/MacOS",
  "scripts_dir": "/Users/.../.opencode/commands/ida-pro-analysis-scripts"
}
```

**变更后**：
```json
{
  "ida_path": "/Applications/IDA Professional 9.1.app/Contents/MacOS",
  "tools": {
    "apktool": {
      "path": "apktool",
      "agents": ["mobile-analysis"],
      "required": true,
      "version_cmd": ["--version"],
      "description": "APK 解包+反汇编工具"
    },
    "jadx": {
      "path": "jadx",
      "agents": ["mobile-analysis"],
      "required": true,
      "version_cmd": ["--version"],
      "description": "DEX→Java 反编译器"
    },
    "adb": {
      "path": "adb",
      "agents": ["mobile-analysis"],
      "required": true,
      "version_cmd": ["version"],
      "description": "Android Debug Bridge"
    },
    "otool": {
      "path": "otool",
      "agents": ["mobile-analysis"],
      "required": false,
      "version_cmd": [],
      "description": "Mach-O 文件查看器（macOS 自带）"
    },
    "ldid": {
      "path": "ldid",
      "agents": ["mobile-analysis"],
      "required": false,
      "version_cmd": [],
      "description": "iOS 伪签名工具"
    }
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 工具可执行文件路径。支持两种形式：**裸名**（如 `"apktool"`）→ 通过 `shutil.which()` 在 PATH 中查找，跨平台兼容；**绝对路径**（如 `"/opt/homebrew/bin/apktool"`）→ 直接检查文件存在性。推荐使用裸名，避免升级工具后路径失效 |
| `agents` | string[] | 哪些 Agent 需要此工具（Plugin 按此字段过滤注入） |
| `required` | boolean | 缺失时是否阻止 Agent 继续（true → detect_env.py 标记 error） |
| `version_cmd` | string[] | 用于检测版本的 CLI 参数数组（**不含工具名本身**，仅参数部分，如 `["version"]`、`["--version"]`）；为空数组 `[]` 时表示该工具不支持版本查询，仅检测命令存在性，版本字段写入 `null`（JSON null，非字符串 `"null"`） |
| `description` | string | 人类可读描述，用于环境信息展示 |

**删除 `scripts_dir`**：脚本目录由 Plugin 从 agent 名动态推导，不再手动配置。

**tools 字段为手动配置**：用户创建 config.json 时手动填入工具路径。detect_env.py 读取 config.json tools，按 `version_cmd` 执行检测，将可用性/版本写入 env_cache.json。Plugin 读取 env_cache.json 获取检测结果，读取 config.json tools 获取路径和 agent 过滤信息。

### 2.3 Plugin 改造方案

**核心机制**：`sessionAgentMap` 已跟踪 `sessionID → agent`。所有 hook 中查表分支。

**2.3.1 system.transform（环境信息注入）**

```
流程：
1. 尝试从 input.sessionID 查 sessionAgentMap → 获取 agentName
2. input.sessionID 为 undefined（该 hook 中 sessionID 可选）→ agentName 为 undefined → 注入通用环境信息（IDA 路径 + 全部 tools + BA_PYTHON + packages）
3. agentName 已知 → 注入该 agent 的环境信息子集
```

| 注入项 | binary-analysis | mobile-analysis | 来源 |
|--------|----------------|-----------------|------|
| IDA Pro 路径 | 注入 | 注入 | config.json ida_path |
| `$SCRIPTS_DIR` | `.opencode/binary-analysis/` | `.opencode/mobile-analysis/` | Plugin 动态推导 |
| `$IDA_SCRIPTS_DIR` | `.opencode/binary-analysis/` | `.opencode/binary-analysis/` | Plugin 动态推导（所有 Agent 均注入，新增 Agent 时无需改 Plugin） |
| 编译器 | 注入 | 注入（移动端也可能需要编译求解器、Frida gadget 等） | env_cache.json compiler |
| Python 包 | 注入（全部） | 注入（全部） | env_cache.json packages |
| 外部工具路径 | 不注入 | 注入（config.json tools 中 agents 含 mobile-analysis 的） | config.json 过滤 + env_cache.json 可用性 |
| BA_PYTHON | 注入 | 注入 | env_cache.json venv_python |

**外部工具路径过滤逻辑**：
```ts
function getToolsForAgent(agentName: string, config: ConfigData): ToolInfo[] {
  if (!config.tools) return [];
  return Object.entries(config.tools)
    .filter(([, tool]) => !tool.agents || tool.agents.includes(agentName))
    .map(([name, tool]) => ({ name, ...tool }));
}
```
agentName 未知时不过滤，注入全部 tools。

**2.3.2 脚本目录推导**

```ts
const AGENT_SCRIPT_DIRS: Record<string, string> = {
  "binary-analysis": join(directory, ".opencode", "binary-analysis"),
  "mobile-analysis": join(directory, ".opencode", "mobile-analysis"),
};
const IDA_SCRIPTS_DIR = join(directory, ".opencode", "binary-analysis");

function getScriptDir(agentName: string | undefined): string {
  return AGENT_SCRIPT_DIRS[agentName || ""]
    || AGENT_SCRIPT_DIRS["binary-analysis"];
}
```

`$IDA_SCRIPTS_DIR` 固定指向 `binary-analysis/`，所有 Agent 均注入（无需按 agent 判断）。新增 Agent 时只需在 `AGENT_SCRIPT_DIRS` 中添加条目，`$IDA_SCRIPTS_DIR` 逻辑不变。

**2.3.3 compacting（压缩时注入）**

COMPACT_REMINDER 从硬编码字符串改为动态生成：

```ts
function getCompactionReminder(agentName: string | undefined): string {
  if (agentName) {
    const promptPath = `.opencode/agents/${agentName}.md`;
    return `## 压缩恢复指令（压缩时必须保留）

上下文刚被压缩。继续分析前必须：
1. 重新读取 agent prompt（${promptPath}）获取完整规则
2. 恢复 $SCRIPTS_DIR、$IDA_SCRIPTS_DIR、$TASK_DIR 等关键变量（见 agent prompt 的"变量丢失自愈"章节）`;
  }
  // 拿不到 agent name → 提醒用户确认（不做静默 fallback）
  return `## 压缩恢复指令（压缩时必须保留）

上下文刚被压缩。继续分析前必须：
1. 请告知当前使用的是哪个 Agent（如 binary-analysis、mobile-analysis）
2. 根据 Agent 名读取对应的 agent prompt（.opencode/agents/<agent-name>.md）
3. 恢复 $SCRIPTS_DIR、$IDA_SCRIPTS_DIR、$TASK_DIR 等关键变量`;
}
```

压缩状态保留提示（通用部分 + 按 agent 动态追加，**不写"X 特有"标签**）：

```
通用部分（所有 Agent 共用）：
  - 分析目标文件路径和类型
  - 已识别的关键函数/类及其地址/名称和用途
  - 已发现的分析结论
  - 当前分析阶段和待完成步骤
  - 失败记录（已尝试方向，避免重复）
  - 验证结果和置信度
  - 用户显式约束

binary-analysis 动态追加：
  - IDA 数据库路径
  - 已执行的 idat 查询和结果摘要

mobile-analysis 动态追加：
  - 已解包路径
  - 已识别的 native 库列表（.so / .dylib）
  - 当前设备连接状态（device_id、frida_server 运行/端口）
```

**2.3.4 设备状态注入（mobile-analysis）**

> 来自项目内置的 Frida 管理经验：设备信息必须持久化到任务目录，否则 frida 连接不稳定。

mobile-analysis 的 workspace 任务目录下应有 `device.json`：

**Android 设备示例**：
```json
{
  "device_id": "emulator-5554",
  "device_type": "android",
  "frida_server": {
    "running": true,
    "device_port": 6656,
    "host_port": 6655,
    "binary_name": "x7k2m9"
  }
}
```

**iOS 设备示例**：
```json
{
  "device_id": "a1b2c3d4e5f6...",
  "device_type": "ios",
  "frida_server": {
    "running": true
  }
}
```

**字段说明**：

| 字段 | Android | iOS | 说明 |
|------|---------|-----|------|
| `device_id` | adb 序列号（如 `emulator-5554`） | UDID（如 `a1b2c3d4...`） | 设备唯一标识 |
| `device_type` | `"android"` | `"ios"` | 设备类型 |
| `frida_server.running` | ✅ | ✅ | frida-server 是否在运行 |
| `frida_server.device_port` | ✅（设备端监听端口） | ❌ | iOS 通过 USB 直连，无需端口转发 |
| `frida_server.host_port` | ✅（主机端映射端口，通过 `adb forward` 建立） | ❌ | 同上 |
| `frida_server.binary_name` | ✅（随机名，如 `x7k2m9`） | ✅（随机名） | frida-server 二进制文件名（随机化，防检测） |

**定位：device.json 是"任务级设备快照"，记录当前任务正在使用的设备，不是设备注册表。** 每个任务目录最多一个 device.json，记录该任务绑定的设备。任务切换时创建新任务目录和新 device.json，互不干扰。

**创建责任方和时机**：
- **由 Agent 自行创建**：mobile-analysis Agent 在首次连接设备时（如执行 `adb devices` 后选择设备），在 `$TASK_DIR` 下创建 `device.json`
- **Plugin 不负责创建**：Plugin 只读取已有的 device.json，在 compacting 和 system.transform 中注入设备状态路径提示
- **生命周期**：device.json 随任务目录存在，任务结束自动保留

**设备选择流程（Agent 首次操作设备时执行）**：

```
1. 执行 `adb devices`（Android）或 `idevice_id -l`（iOS）获取当前在线设备列表
2. 检查 $TASK_DIR/device.json 是否存在
   ├── 不存在 → 进入设备选择流程
   └── 存在 → 读取 device_id，校验设备是否在线（见下方校验规则）
3. 设备选择流程：
   a. 在线设备数 = 0 → 告知用户"未检测到设备"，提示连接步骤，等待用户操作后重试
   b. 在线设备数 = 1 → 自动选择该设备，创建 device.json（device_type 根据 adb/idevice 来源自动判断 "android" 或 "ios"）
   c. 在线设备数 > 1 → 列出所有设备（含 device_id + 型号/别名），请用户选择，创建 device.json（device_type 同理）
4. device.json 创建后，后续所有设备操作使用记录的 device_id
5. device_type 字段由 Agent 根据设备检测来源自动设置："android"（通过 adb 检测到的设备）或 "ios"（通过 idevice 检测到的设备）
```

**device.json 校验规则（每次需要操作设备时执行）**：

| 场景 | 条件 | 处理 |
|------|------|------|
| 设备离线 | device.json 存在，但 `adb devices`（Android）或 `idevice_id -l`（iOS）中该 device_id 不在线 | 告知用户"上次使用的设备 XXX 已离线"，列出当前在线设备供选择，或等待设备重新连接。**不自动切换设备**（避免操作错误设备） |
| 设备更换 | device.json 存在且在线，但用户要求使用另一个设备 | 更新 device.json 为新设备 |
| 多设备都在线 | device.json 记录的设备在线，且其他设备也在线 | 使用 device.json 记录的设备（保持任务连续性），除非用户明确要求切换 |
| 无 device.json 且无设备 | 首次操作，`adb devices`（Android）和 `idevice_id -l`（iOS）均为空 | 告知用户连接设备，提供连接指引（USB 调试/Wi-Fi adb），等待用户操作后重试 |
| 无 device.json 且有设备 | 首次操作，有设备在线 | 按设备选择流程处理（1台自动选，多台用户选） |

**device.json 与 compacting**：

压缩恢复时，mobile-analysis Agent 从 device.json 读取上次设备信息，但**必须重新校验设备在线状态**后再操作（设备可能已断开）。

**2.3.5 ConfigData / EnvData 接口变更**

```ts
// ConfigData（config.json 对应的 TS 接口）
interface ConfigData {
  ida_path?: string;
  tools?: Record<string, {
    path: string;
    agents?: string[];
    required?: boolean;
    version_cmd?: string[];
    description?: string;
  }>;
  // 删除 scripts_dir
}

// EnvData（env_cache.json 对应的 TS 接口）
interface EnvData {
  data?: {
    venv_python?: string;
    compiler?: { available: boolean; type: string; path: string; vcvarsall?: string };
    python_arch?: string;
    packages?: Record<string, { available: boolean; version: string }>;
    ida_pro?: { available: boolean; path: string };
    tools?: Record<string, { available: boolean; version: string | null }>;
  };
}
// 注：tools 字段包含 config.json 中所有工具的检测结果
// version 为 null 表示工具不支持版本查询（version_cmd 为空）或工具不可用
```

### 2.4 detect_env.py 重构

**核心变更：新增 `_detect_tools(config)` 函数，从 config.json 读取工具配置并检测可用性。`path` 支持裸名（推荐）和绝对路径，跨平台兼容。**

```python
def _resolve_tool_path(path):
    """解析工具路径：绝对路径检查文件存在性，裸名通过 which 查找。
    返回 (resolved_path, found)，resolved_path 为实际可执行路径或原始 path。
    跨平台：Windows 上 shutil.which 自动处理 PATHEXT（.exe/.cmd 等），
    绝对路径在 Windows 上也尝试 PATHEXT 自动补全。"""
    if os.path.isabs(path):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return (path, True)
        # Windows: 尝试 PATHEXT 自动补全（如 apktool → apktool.exe）
        if os.name == "nt":
            for ext in os.environ.get("PATHEXT", ".exe;.cmd;.bat").split(";"):
                candidate = path + ext
                if os.path.isfile(candidate):
                    return (candidate, True)
        return (path, False)
    resolved = shutil.which(path)
    if resolved:
        return (resolved, True)
    return (path, False)

def _detect_tools(config, agent=None, errors=None):
    """从 config.json 读取 tools 配置，逐个执行 version_cmd 检测可用性"""
    if errors is None:
        errors = []
    tools = config.get("tools", {})
    result = {}
    for name, cfg in tools.items():
        # 按 agent 过滤：指定 agent 时只检测该 agent 的工具
        if agent and cfg.get("agents") and agent not in cfg.get("agents", []):
            continue
        path = cfg.get("path", "")
        version_cmd = cfg.get("version_cmd", [])
        resolved, found = _resolve_tool_path(path)
        if found:
            version = _get_tool_version(resolved, version_cmd)
            result[name] = {"available": True, "version": version}
        else:
            result[name] = {"available": False, "version": None}
            if cfg.get("required", False):
                errors.append(f"必需工具 {name} 未找到: {path}")
    return result

def _get_tool_version(resolved_path, version_cmd):
    """执行 version_cmd 获取版本字符串。
    version_cmd 为空列表时返回 None（表示不支持版本查询）。
    version_cmd 仅含参数（不含工具名）。
    跨平台兼容：使用列表形式传参，不依赖 shell。"""
    if not version_cmd:
        return None
    try:
        r = subprocess.run([resolved_path] + version_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return (r.stdout.strip() or r.stderr.strip()).split("\n")[0] or None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None
```

**新增 `--agent` 参数**：

```bash
# 检测全部工具（默认）
python3 detect_env.py

# 仅检测 binary-analysis 需要的工具
python3 detect_env.py --agent binary-analysis

# 仅检测 mobile-analysis 需要的工具
python3 detect_env.py --agent mobile-analysis
```

agent name 未找到 → 默认检测全部。工具检测结果写入 env_cache.json 的 `data.tools` 字段（与 ConfigData.tools 结构对应）。

**detect_env.py 不写 config.json**。config.json 由用户手动创建和维护。detect_env.py 只读 config.json 中的 tools 配置。

### 2.5 mobile-analysis Agent 设计

**角色**：移动应用逆向分析编排器。输入 APK/IPA + 分析需求，自动识别文件类型，编排工具链，根据分析场景选择最佳路径。

**APK 多分析路径**：

```
APP 分析需求
  │
  ├── 场景：Java/Kotlin 逻辑分析（如追踪按钮点击→监听器）
  │     └── 路径：apktool 解包 → jadx 反编译 → 源码中搜索监听器绑定 → 追踪调用链
  │
  ├── 场景：Smali 级精读（混淆严重，jadx 产出不可读）
  │     └── 路径：apktool 解包+反汇编 → 直接分析 smali 代码 → 结合 jadx 对照视图
  │
  ├── 场景：Native 层分析（.so 算法/保护机制）
  │     └── 路径：apktool 解包 → 识别 lib/ 下的 .so → IDA Pro 分析（通过 $IDA_SCRIPTS_DIR）
  │
  ├── 场景：Hybrid/WebView（前端渲染、JS Bridge）
  │     └── 路径：apktool 解包 → 检查 assets/ 和 res/ 中的前端资源 → mitmproxy 抓包
  │
  └── 场景：Java↔Native 跨层调用（JNI）
        └── 路径：jadx 找到 JNI 声明 → IDA Pro 分析 native 实现 → Frida 跨层 Hook 验证
```

**IPA 分析路径**：

```
IPA 分析需求
  │
  ├── 路径：unzip 解包 → otool/nm 分析符号 → IDA Pro 分析 Mach-O/dylib
  │
  └── 路径：解包 → 检查 Frameworks/ → otool/nm 分析符号 → IDA Pro 深度分析
```

**Agent prompt 结构**（预估 ~400 行）：

| 章节 | 行数 | 内容 |
|------|------|------|
| 元信息 + 角色 | ~15 | description="移动应用逆向分析编排器"、mode=primary、permission |
| 运行环境 + 变量 | ~55 | `$SCRIPTS_DIR`、`$IDA_SCRIPTS_DIR`、`$TASK_DIR`、`$BA_PYTHON` 初始化 |
| 阶段 0：环境检测 | ~20 | 调用 `$IDA_SCRIPTS_DIR/scripts/detect_env.py`，读取 env_cache.json |
| 阶段 A：初始分析 | ~50 | 文件类型检测（APK/IPA）→ 多路径分流 → 按场景选择工具链 |
| 阶段 B：分析规划 | ~25 | 场景驱动 + 知识库按需加载 |
| 阶段 C：执行监控 | ~40 | 执行纪律 + 循环控制 |
| 逆向核心原则 | ~15 | 适配移动端的分析原则 |
| 工具清单 | ~65 | 移动端工具 + IDA Pro 脚本引用（标注 `$IDA_SCRIPTS_DIR`） |
| 知识库索引 | ~35 | 按需加载的知识库文件列表 + 触发条件 |
| 输出格式 + 其他 | ~45 | 输出模板、后续交互、安全规则 |

### 2.6 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `agents/mobile-analysis.md` | **新增** | 移动端分析 Agent prompt（~400 行，含多路径分析决策） |
| `mobile-analysis/README.md` | **新增** | 移动端工具目录结构说明 |
| `mobile-analysis/scripts/registry.json` | **新增** | 脚本注册表（初始空数组） |
| `mobile-analysis/knowledge-base/android-tools.md` | **新增** | Android 工具安装 + CLI 参考（apktool 解包反汇编、jadx 反编译、adb） |
| `mobile-analysis/knowledge-base/ios-tools.md` | **新增** | iOS 工具安装 + CLI 参考（otool、ldid、insert_dylib，class-dump 作为可选工具提及） |
| `mobile-analysis/knowledge-base/mobile-methodology.md` | **新增** | 移动端分析方法论（APK/IPA 结构、多路径分析决策树、场景→路径映射） |
| `mobile-analysis/knowledge-base/mobile-frida.md` | **新增** | 移动端 Frida：安全部署（随机名+随机路径+非默认端口）、设备连接、Java/ObjC Bridge Hook、防检测技术 |
| `mobile-analysis/knowledge-base/mobile-patterns.md` | **新增** | 常见安全模式（证书固定绕过、root/越狱检测、混淆识别） |
| `plugins/security-analysis.ts` | **修改** | 重构 ConfigData/EnvData 接口 + tools 过滤注入 + 动态 COMPACT_REMINDER + 通用 compaction 状态动态追加 + 删除 scripts_dir |
| `binary-analysis/scripts/detect_env.py` | **修改** | 新增 _detect_tools 从 config.json 读取工具配置，新增 `--agent` 参数，工具检测结果写入 env_cache.json data.tools |
| `agents/binary-analysis.md` | **修改** | 变量初始化 fallback：删除 config.json scripts_dir 依赖，改为项目结构推导 |
| `binary-analysis/environment-setup.md` | **修改** | config.json 结构说明同步更新（数据结构化 tools） |
| `binary-analysis/context-persistence.md` | **修改** | Plugin 架构说明同步更新（按 Agent 注入、动态 compacting） |
| `binary-analysis/knowledge-base/gui-automation.md` | **修改** | `$SCRIPTS_DIR` 来源描述从"config.json scripts_dir"改为"Plugin 环境信息注入" |
| `commands/gui-interact-pc.md` | **修改** | `$SCRIPTS_DIR` fallback 从 config.json scripts_dir 改为项目结构推导 |
| `commands/security-analysis-docs/setup-guide.md` | **修改** | config.json 模板删除 scripts_dir，新增结构化 tools 说明，验证清单更新 |
| `AGENTS.md` | **修改** | 项目概述更新（新增 `.opencode/` Agent 架构说明，≤30 行） |
| `~/bw-security-analysis/config.json` | **修改** | 删除 scripts_dir，tools 值升级为数据结构 |

---

## §3 实现规范

### 编码规则

- Agent prompt 遵循渐进式披露原则（核心规则 < 450 行，详细内容放知识库）
- 知识库文件必须自包含（不依赖主 prompt 上下文即可理解）
- Plugin 改造保持向后兼容（binary-analysis 的行为不受影响）
- **路径只用相对路径**，禁止硬编码绝对路径
- **压缩状态描述不用"X 特有"标签**，改为通用部分 + 按 agent 动态追加
- **config.json tools 为唯一工具配置源**，detect_env.py 和 Plugin 均从此读取
- **env_cache.json 不拆分**，所有环境数据存一个文件，Plugin 按需读取子集

### 改动范围表

| 改动类型 | 文件数 | 预估总行数 | 风险等级 |
|---------|--------|-----------|---------|
| 新增 Agent prompt | 1 | ~400 | 中（AI 行为变更） |
| 新增知识库 | 5 | ~700 | 低（文档） |
| 新增其他文件 | 2 | ~120 | 低（README+registry） |
| 修改 Plugin | 1 | ~180 行改动 | 高（影响所有 Agent） |
| 修改 detect_env.py | 1 | ~100 行改动 | 中（影响环境检测） |
| 修改 binary-analysis.md | 1 | ~20 行改动 | 高（Agent 行为回归） |
| 修改环境文档 | 5 | ~80 行改动 | 低（文档） |
| 修改 AGENTS.md | 1 | ~30 行改动 | 低（文档） |
| 修改 config.json | 1 | ~40 行改动 | 低（配置） |

### §3.1 实施步骤拆分

```
步骤 1. 创建 mobile-analysis 目录结构
  - 文件: mobile-analysis/README.md, mobile-analysis/scripts/registry.json
  - 预估行数: ~80
  - 验证点: 目录存在、README.md 包含目录结构+变量约定说明、registry.json 为合法 JSON 空数组
  - 依赖: 无

步骤 2. 创建 Android 工具知识库
  - 文件: mobile-analysis/knowledge-base/android-tools.md
  - 预估行数: ~150
  - 内容要点:
    1. apktool 安装 + CLI 参考（d|decode 解包+反汇编 DEX→smali，b|build 重打包）
    2. jadx 安装 + CLI 参考（-d 输出目录，--deobf 反混淆）
    3. adb 安装 + CLI 参考（devices、shell、push、forward、install）
    4. 常用命令组合示例
  - 验证点: 文件存在，内容自包含可独立理解，术语正确（apktool=解包+反汇编，jadx=反编译）
  - 依赖: 无

步骤 3. 创建 iOS 工具知识库
  - 文件: mobile-analysis/knowledge-base/ios-tools.md
  - 预估行数: ~150
  - 内容要点:
    1. otool/nm 用法（Mach-O 分析、符号表查看）
    2. ldid 安装 + 用法（伪签名）
    3. insert_dylib/optool 安装 + 用法（动态库注入）
    4. macOS 自带工具（codesign、security）
    5. class-dump（可选，brew 无包，需从 GitHub releases 手动安装）
  - 验证点: 文件存在，内容自包含可独立理解
  - 依赖: 无

步骤 4. 创建移动端分析方法论知识库
  - 文件: mobile-analysis/knowledge-base/mobile-methodology.md
  - 预估行数: ~150
  - 内容要点:
    1. APK 结构说明（META-INF/、lib/、res/、assets/、AndroidManifest.xml、classes.dex）
    2. IPA 结构说明（Payload/、Frameworks/、Info.plist）
    3. **多路径分析决策树**（Java→smali→native→Hybrid→跨层，含场景→路径映射表）
    4. 各路径的初始分析步骤和知识库加载规则
  - 验证点: 文件存在，包含完整的多路径决策树和场景映射，自包含可独立理解
  - 依赖: 步骤 2、步骤 3（引用工具名）

步骤 5. 创建移动端 Frida 知识库
  - 文件: mobile-analysis/knowledge-base/mobile-frida.md
  - 预估行数: ~150
  - 内容要点:
    1. **安全安装 frida-server**（基于项目内置经验）：
       - 随机二进制名 + 随机目录名（cryptographic randomness，不含"frida"关键字）
       - 非默认端口（从 6655 起动态分配）
       - adb push + chmod 755 → 通过 adb shell 启动
    2. 设备连接（adb forward + frida.get_device()）
    3. **device.json 规范**：参照 §2.3.4 定义的任务级设备快照结构（device_id + device_type + frida_server），设备选择和校验逻辑
    4. 设备失联处理（中断执行 → 提醒用户 → adb devices 列出可用设备 → 用户选择）
    5. Java Bridge Hook 模板 + Objective-C Bridge Hook 模板
    6. **防检测技术**：frida-server 重命名、端口随机、Magisk/KernelSU 隐藏、Xposed 检测绕过
  - 验证点: 文件存在，包含安全安装流程和防检测技术，自包含可独立理解
  - 依赖: 无

步骤 6. 创建移动端安全模式知识库
  - 文件: mobile-analysis/knowledge-base/mobile-patterns.md
  - 预估行数: ~120
  - 内容要点: 证书固定（SSL Pinning）绕过方法、root/越狱检测绕过、代码混淆识别策略、反调试检测规避、完整性校验绕过
  - 验证点: 文件存在，每种模式独立可读，自包含可独立理解
  - 依赖: 无

步骤 7. 创建 mobile-analysis Agent prompt
  - 文件: agents/mobile-analysis.md
  - 预估行数: ~400
  - 内容要点:
    1. YAML frontmatter: description、mode=primary、permission
    2. 角色定义：移动应用逆向分析编排器
    3. 变量初始化：$SCRIPTS_DIR、$IDA_SCRIPTS_DIR、$TASK_DIR、$BA_PYTHON
    4. 阶段 0：调用 $IDA_SCRIPTS_DIR/scripts/detect_env.py
    5. 阶段 A：文件类型检测 + 多路径分析决策（场景→路径→工具）
    6. 阶段 B：场景驱动的分析规划
    7. 阶段 C：执行纪律 + 循环控制
    8. 工具清单：移动端工具（bash 调用）+ IDA Pro 脚本（通过 $IDA_SCRIPTS_DIR 调用）
    9. 知识库索引：列出步骤 2-6 创建的知识库文件 + 触发条件 + 通用知识库（$IDA_SCRIPTS_DIR/knowledge-base/*.md）的触发条件
  - 验证点:
    1. 行数 < 450
    2. 包含 $SCRIPTS_DIR 和 $IDA_SCRIPTS_DIR 两个变量的正确初始化
    3. 多路径分析决策树在 prompt 中有骨架（详细逻辑在 mobile-methodology.md）
    4. 知识库索引完整（列出所有知识库文件 + 触发条件 + 路径用变量表示）
    5. 与 binary-analysis.md 的风格和结构保持一致
  - 依赖: 步骤 1-6（引用知识库文件名和目录结构）

步骤 8. 更新 config.json 为结构化格式
  - 文件: ~/bw-security-analysis/config.json
  - 预估行数: ~40 行改动
  - 改动内容:
    1. 删除 scripts_dir 字段
    2. tools 值从 `"工具名": "路径字符串"` 升级为 `"工具名": { path, agents, required, version_cmd, description }`
  - 验证点:
    1. JSON 语法正确
    2. 每个 tools 条目包含 path + agents + version_cmd + required 字段
    3. agents 数组中只包含已有的 agent 名（"binary-analysis" / "mobile-analysis"）
  - 依赖: 步骤 7（agent 名 "mobile-analysis" 已确定）

步骤 9. 重构 detect_env.py
  - 文件: binary-analysis/scripts/detect_env.py
  - 预估行数: ~100 行改动
  - 改动内容:
    1. 新增 _resolve_tool_path(path) 函数：绝对路径检查文件存在性+可执行（Windows 上额外尝试 PATHEXT 自动补全），裸名通过 shutil.which() 查找（跨平台，Windows 自动补 .exe/.cmd）
    2. 新增 _detect_tools(config, agent=None) 函数：读取 config.json tools → 按 agent 过滤 → 调用 _resolve_tool_path 检查可用性 → 逐工具执行 version_cmd → 输出可用性+版本
    3. 新增 _get_tool_version(resolved_path, cmd) 函数：执行 cmd 捕获版本字符串（cmd 为空列表时返回 None，表示不支持版本查询）
    4. 新增 --agent 参数：指定 agent 名时只检测该 agent 的 tools（按 tools[].agents 过滤）
    5. agent 未知 → 检测全部
    6. 工具检测结果写入 env_cache.json data.tools 字段（version 为 null 表示不支持版本查询或不可用）
    7. required=true 的工具缺失时写入 errors，标记 success=false
  - 验证点:
    1. `python -c "compile(...)"` 语法检查通过
    2. 无 --agent 时检测全部 config.json tools
    3. 有 --agent mobile-analysis 时仅检测 agents 含 "mobile-analysis" 的工具
    4. path 为裸名（如 "apktool"）时通过 shutil.which() 找到 → available: true
    5. path 为绝对路径时通过 os.path.isfile() 检查 → 可用/不可用
    6. version_cmd 为空时 version 为 null（非 "unknown"）
    7. env_cache.json 输出包含 data.tools 字段，结构正确
    8. 已有工具逻辑（venv、compiler、packages、ida_pro）不受影响
  - 依赖: 步骤 8（config.json 已有结构化 tools）

步骤 10. 改造 Plugin — 按 Agent 注入 + 动态 compacting
  - 文件: plugins/security-analysis.ts
  - 预估行数: ~180 行改动
  - 改动内容:
    1. ConfigData 接口：删除 scripts_dir，新增结构化 tools 定义
    2. EnvData 接口：新增 tools 字段用于外部工具检测结果
    3. 新增 AGENT_SCRIPT_DIRS 常量 + IDA_SCRIPTS_DIR 常量（固定指向 binary-analysis/）
    4. 新增 getToolsForAgent(agentName, config) 过滤函数
    5. 新增 getCompactionReminder(agentName) 动态生成函数（含 undefined→用户确认逻辑，所有 Agent 统一包含 $SCRIPTS_DIR、$IDA_SCRIPTS_DIR、$TASK_DIR）
    6. 新增 getCompactionContext(agentName) 通用部分+动态追加函数
    7. system.transform：查 sessionAgentMap → 分支注入（环境信息 + tools 过滤 + 脚本目录推导），所有 Agent 均注入 $IDA_SCRIPTS_DIR
    8. compacting：按 agent 使用对应的 COMPACT_REMINDER 和 compaction context，TASK_DIR 恢复仍需共用逻辑；envSummary 中的 scriptsDir 从 agentName 动态推导（复用 getScriptDir），不再读取 config.scripts_dir
    9. 删除所有 scripts_dir 相关逻辑（包括 compacting 和 system.transform 中）
  - 验证点:
    1. `node --check` 编译通过
    2. binary-analysis 注入环境信息含 $SCRIPTS_DIR（binary-analysis/）+ $IDA_SCRIPTS_DIR（binary-analysis/），与改造前行为一致（回归）
    3. mobile-analysis 注入环境信息含 $SCRIPTS_DIR（mobile-analysis/）+ $IDA_SCRIPTS_DIR（binary-analysis/）+ 过滤后的移动端 tools
    4. system.transform 中 agentName undefined 时注入 all-in 通用信息
    5. COMPACT_REMINDER agentName undefined 时提示用户确认（不静默 fallback）
    6. compaction context 动态追加正确（binary-analysis 有 IDA 数据库，mobile-analysis 有已解包路径）
  - 依赖: 步骤 7（agent 名）、步骤 8（结构化 tools）、步骤 9（env_cache 结构）

步骤 11. 更新 binary-analysis.md 变量初始化
  - 文件: agents/binary-analysis.md
  - 预估行数: ~20 行改动
  - 改动内容:
    1. bash fallback：删除 `c.get('scripts_dir', ...)` 中的 config.json 读取，改为项目结构推导：
       ```bash
       SCRIPTS_DIR="$(pwd)/.opencode/binary-analysis"
       IDA_SCRIPTS_DIR="$SCRIPTS_DIR"
       ```
    2. PowerShell fallback：同理
    3. 添加 `$IDA_SCRIPTS_DIR` fallback（等于 `$SCRIPTS_DIR`，因为 binary-analysis 的两个变量指向同一目录）
  - 验证点:
    1. 不再引用 config.json 的 scripts_dir
    2. fallback 正确推导到 .opencode/binary-analysis/
    3. Plugin 注入的 $SCRIPTS_DIR / $IDA_SCRIPTS_DIR 优先级高于 fallback
    4. $IDA_SCRIPTS_DIR 与 $SCRIPTS_DIR 均有 fallback
  - 依赖: 步骤 10（Plugin 已改为动态推导）

步骤 12. 更新环境文档
  - 文件: binary-analysis/environment-setup.md, binary-analysis/context-persistence.md, binary-analysis/knowledge-base/gui-automation.md, commands/gui-interact-pc.md, commands/security-analysis-docs/setup-guide.md
  - 预估行数: ~80 行改动
  - 改动内容:
    1. environment-setup.md: 更新 config.json 结构说明（结构化 tools、删除 scripts_dir）
    2. context-persistence.md: 更新 Plugin 架构说明（多 Agent 注入、动态 compacting）
    3. gui-automation.md: $SCRIPTS_DIR 来源从 "config.json scripts_dir" 改为 "Plugin 环境信息注入"
    4. gui-interact-pc.md: $SCRIPTS_DIR fallback 删除 config.json 依赖
    5. setup-guide.md: config.json 模板更新为结构化格式（删除 scripts_dir），新增 mobile-analysis Agent 说明，删除验证清单中 scripts_dir 相关验证项（第 105 行），新增 tools 字段验证项
  - 验证点: 各文档内容与实际代码行为一致，无过时引用
  - 依赖: 步骤 10（Plugin 改造完成）

步骤 13. 更新 AGENTS.md
  - 文件: AGENTS.md（项目根目录）
  - 预估行数: ~30 行改动（整体重写）
  - 改动内容:
    1. 项目概述：IDAPython 脚本 + OpenCode 多 Agent 安全分析集合
    2. `.opencode/` 目录下 Agent 索引（名称 + 一句话职责、如何切换）
    3. 测试命令（pytest / bats）
    4. 外部参考资源
    5. 特殊说明（中文日志/注释）
  - 验证点: 行数 ≤ 35，涵盖多 Agent 架构，不包含 Agent 的行为细节（细节在各自 prompt 中）
  - 依赖: 步骤 1-12 全部完成

步骤 14. 回归验证
  - 文件: 无新文件
  - 预估行数: 0
  - 验证点:
    1. binary-analysis Agent 环境注入与改造前完全一致（IDA 路径、编译器、Python 包、BA_PYTHON）
    2. binary-analysis Agent 工作流正常（查询 + 反编译 + 更新）
    3. mobile-analysis Agent 能被 OpenCode 识别为 primary agent（Tab 切换可见）
    4. mobile-analysis Agent prompt 加载正确（$SCRIPTS_DIR + $IDA_SCRIPTS_DIR 均被注入）
    5. detect_env.py 从 config.json 读取工具，输出 data.tools 结构正确
    6. binary-analysis.md 变量初始化不依赖 config.json scripts_dir
    7. COMPACT_REMINDER 在 agent 已知时指向正确路径，未知时提示用户确认
    8. compaction context 通用部分一致，动态追加部分按 agent 正确差异化
  - 依赖: 步骤 1-13 全部完成
```

---

## §4 验收标准

### 功能验收

| # | 验收项 | 通过条件 |
|---|--------|---------|
| F1 | mobile-analysis Agent 可用 | OpenCode Tab 切换可见，Agent 加载无报错，环境信息含 $SCRIPTS_DIR + $IDA_SCRIPTS_DIR |
| F2 | APK 初始分析 | 提供 APK 文件，Agent 能编排 apktool 解包+反汇编 + jadx 反编译 + 识别 native libs |
| F3 | APK 多路径选择 | Agent 能根据分析需求选择正确路径（Java 逻辑 / smali / native / Hybrid） |
| F4 | IPA 初始分析 | 提供 IPA 文件，Agent 能编排解包 + otool/nm 分析 + 识别 frameworks |
| F5 | IDA Pro 联动 | 识别到 .so/.dylib 时，Agent 通过 $IDA_SCRIPTS_DIR 调用 query.py/initial_analysis.py |
| F6 | 知识库按需加载 | Agent 在不同场景下加载对应知识库（mobile + binary-analysis 共享知识库） |
| F7 | 环境检测按 Agent | detect_env.py --agent mobile-analysis 仅检测 mobile tools，--agent binary-analysis 不加移动端工具 |
| F8 | 工具配置统一 | config.json tools 为唯一配置源，detect_env.py 和 Plugin 均从此读取，无硬编码工具列表 |

### 回归验收

| # | 验收项 | 通过条件 |
|---|--------|---------|
| R1 | binary-analysis 环境注入不变 | Plugin 注入的 IDA Pro + compiler + packages 信息与改造前一致 |
| R2 | binary-analysis 工作流正常 | 查询 + 反编译 + 更新操作端到端通过 |
| R3 | 压缩恢复正常 | binary-analysis 和 mobile-analysis 压缩后 TASK_DIR 精确恢复，COMPACT_REMINDER 正确指向或提示用户 |
| R4 | config.json 无 scripts_dir | Plugin 和 detect_env.py 均不依赖 scripts_dir，路径动态推导 |
| R5 | binary-analysis.md fallback 正确 | 变量初始化不依赖 config.json scripts_dir，fallback 推导到 .opencode/binary-analysis/ |
| R6 | detect_env.py 原有功能正常 | venv/compiler/packages/ida_pro 检测不受 tools 扩展影响 |

### 架构验收

| # | 验收项 | 通过条件 |
|---|--------|---------|
| A1 | mobile-analysis.md < 450 行 | wc -l 验证 |
| A2 | 知识库文件自包含 | 每个知识库文件不依赖主 prompt 即可理解 |
| A3 | 依赖方向正确 | mobile-analysis/ 不被 binary-analysis/ 引用（单向） |
| A4 | 无循环依赖 | Plugin → config.json → env_cache.json，无反向依赖 |
| A5 | config.json 为唯一工具配置源 | detect_env.py 不硬编码工具列表，全从 config.json 读取 |
| A6 | 压缩状态无硬编码 agent 名 | COMPACT_REMINDER 动态生成，compaction context 动态追加，不写 "X 特有" 标签 |
| A7 | AGENTS.md 薄 | ≤35 行，只含索引不含详细行为规则 |

---

## §5 与现有需求文档的关系

| 需求文档 | 关系 |
|---------|------|
| 2026-04-29-directory-and-plugin-rename.md | 本需求在重命名基础上进行（数据目录已是 bw-security-analysis） |
| 2026-04-28-task-dir-persistence.md | mobile-analysis 复用 create_task_dir.py（通过 $IDA_SCRIPTS_DIR 路径引用）+ 新增 device.json 设备状态 |
| 2026-04-22-plugin-and-architecture-improvements.md | 本需求的 Plugin 改造是该需求的延伸（从无差别注入到按 Agent 注入 + 动态 compacting） |
| 2026-04-22-environment-dependency-hardening.md | detect_env.py 重构遵循该需求建立的环境检测框架，从硬编码改为配置驱动 |
| 2026-04-24-gui-visual-automation.md | GUI 自动化是 PC 专用功能，仅 binary-analysis 使用，不影响 mobile-analysis |

### Frida 管理经验（已内置）

> frida-scripts 项目的 library 模块（adb、port、install_record 等）和 hook 脚本已合并到本项目中：
> - `mobile-analysis/scripts/library/` — Frida 生命周期管理库（9 个模块）
> - `mobile-analysis/scripts/hooks/` — Frida JS hook 脚本

经验沉淀位置：

| 经验 | 沉淀位置 |
|------|---------|
| 随机文件名+目录名（不含 frida 关键字） | mobile-frida.md 安全安装章节 |
| 非默认端口 + adb forward | mobile-frida.md 连接章节 |
| install_record.json + fcntl.LOCK_EX | mobile-analysis/scripts/library/install_record.py |
| 15 种 ErrorCode | mobile-frida.md 故障排查章节 |
| su 检测 + root 权限升级 | mobile-frida.md 设备准备章节 |
