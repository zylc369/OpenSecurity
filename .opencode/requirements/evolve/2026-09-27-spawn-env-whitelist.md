# 需求: TS spawn env 白名单化（控制台 + MCP）

## §1 背景与目标

**来源**: 2026-09-27 env 污染链复盘的收尾动作（pending-items.md #1）。

**现状**: `plugins/lib/control-manager.ts` spawn 控制台时 env =
`{...process.env, OPENCODE_ROOT, DATA_DIR, HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE}`
（全量继承 + 4 键注入）; `plugins/lib/mcp-manager.ts` spawn 4 个 MCP server 时
**未传 env 选项**（Node 默认 = 全量继承 process.env）。

**问题**: 子进程环境干净依赖"用户 shell 恰好无敏感键"——巧合而非机制。
实证过的风险实例: agent shell 注入的业务键经开发者手动 nohup 进入控制台;
污染链拉起的 vite（pid 28208）持有 DEEPSEEK_API_KEY/JULIANG_API_KEY 存活数小时;
conda 系键（KMP_* 等）常态混入。

**目标**: 白名单机制保证——无论 opencode 主进程 env 含什么，控制台与 MCP
子进程环境恒为显式最小集。业务键泄漏面（ps eww / core dump / 子进程继承链）归零，
环境确定性不再受 shell 状态影响。

## §2 技术方案

### 2.1 白名单定义（已与用户逐键确认）

darwin / linux（共 4 键）:

| 键 | 来源 | 消费者（已实证） |
|---|---|---|
| `PATH` | 透传 `process.env.PATH` | detect_tools 工具搜索（`os.environ.get("PATH")`）、vite shebang `#!/usr/bin/env node`、全部子进程 exec |
| `HOME` | 透传 `process.env.HOME` | `DEFAULT_DATA_DIR = Path.home()/...`、detect_tools/detect_py_deps 顶层 `CACHE_DIR = expanduser("~/...")`（import 时求值）、launchd plist 路径 |
| `OPENCODE_ROOT` | plugin 注入（现有常量） | 引导键 |
| `DATA_DIR` | plugin 注入（现有常量） | 引导键; MCP 侧 `control_url.py:38` 定位 IPC sock 路径 |

明确排除（决策记录）:
- `TMPDIR`: 砍——`tempfile.gettempdir()` 自带回退 `/tmp`，功能不坏
- `LANG`: 砍——回退 C locale 可接受（弱影响: git 等子进程中文输出转义）
- `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`: 移除注入——控制台 `server.py:23-24`
  `setdefault` 为单一来源（位于 import 链最顶部，时机足够早）; 4 个 MCP server
  零 huggingface 系 import（已逐一验证），不需要
- 业务键（DEEPSEEK_API_KEY 等）: 原本就不注入，全量继承断掉后自然隔离

Windows（win32 分支按语义编写，无环境验证——关联 pending-items #5）:
透传 `PATH / USERPROFILE / HOMEDRIVE / HOMEPATH / TEMP / TMP / SystemRoot /
SystemDrive / ProgramFiles / ProgramFiles(x86)` + 同 2 个注入键。
（Windows 无这些系统键时 cmd 子进程/工具定位会异常，故透传面比 darwin 大;
LANG 与 darwin 决策一致——不透传。）

### 2.2 共用构造函数

`control-manager.ts` 新增并导出:

```ts
export function buildSpawnEnv(): Record<string, string>
```

- darwin/linux: `{PATH?, HOME?, OPENCODE_ROOT, DATA_DIR}`（PATH/HOME 在
  `process.env` 缺失时跳过该键，不写入 undefined）
- win32: 上表全集
- `mcp-manager.ts` import 该函数（现有依赖方向 mcp-manager → control-manager，
  不新增反向依赖）

### 2.3 前置迁移（必须先于白名单生效）

1. **GITHUB_TOKEN**: `config_manager.py` Keys 新增 `GITHUB_TOKEN`（source 默认
   ai_env）; `detect_tools.py:2224` 从 `os.environ.get("GITHUB_TOKEN")` 改为
   `ConfigManager.get_instance().get("GITHUB_TOKEN")`。否则白名单化后 env 通道
   断掉、工具下载加速静默降级。
2. **HF_ENDPOINT**: `model_assets.py:181` 删除 `os.environ.get("HF_ENDPOINT") or`
   前置段，只走 `ConfigManager.get("HF_ENDPOINT")`（Keys 已有该键）。

### 2.4 launchd plist 一致性

`launchd_setup.py` 生成的 plist `EnvironmentVariables` 对照新白名单核对:
plist 是控制台另一条 spawn 路径（launchd 启动），其 env 集应与 buildSpawnEnv
语义一致（HOME/PATH/2 引导键）; OFFLINE 若 plist 中存在则移除——plist 启动
同样经过 `server.py` 的 setdefault（单一来源原则，与 plugin 链路移除注入一致）。

### 2.5 不改动项

- opencode 主进程及其余 plugin spawn 链路（agent shell 注入、Bun.spawn 等）——
  本次范围外
- `.ai_env` 格式、ConfigManager source 黑名单制语义
- 4 个 MCP server 的 Python 代码

## §3 实现规范

| 文件 | 改动类型 | 预估行数 |
|---|---|---|
| services/config_manager.py | Keys +1 | +2 |
| services/detect_tools.py | env 读取迁移 | ~4 改 |
| services/model_assets.py | env 通道删除 | ~2 改 |
| plugins/lib/control-manager.ts | 新函数 + spawn env 替换 + OFFLINE 移除 | ~45 |
| plugins/lib/mcp-manager.ts | spawn 加 `env: buildSpawnEnv()` | ~3 |
| services/launchd_setup.py | plist env 对照核对（按需） | ~10 |
| tests/test_integration.py | 白名单断言用例 | ~45 |
| tests/test_control.py | GITHUB_TOKEN/HF_ENDPOINT 读取路径用例 | ~25 |

编码规则: Python 改动后 `python -c compile`; TS 改动后 bun import 冒烟 +
真实 spawn 验证; 所有日志走 `debugLog`（plugin 侧）。

### §3.1 实施步骤

```
1. GITHUB_TOKEN 迁移
   - 文件: config_manager.py, detect_tools.py, tests/test_control.py
   - 预估行数: ~30
   - 验证点: compile 通过; test_control 中 config_meta 断言含 GITHUB_TOKEN
     （source=ai_env）; 新用例: .ai_env 配置后 detect_tools 读取路径可拿到值
   - 依赖: 无

2. HF_ENDPOINT env 通道收敛
   - 文件: model_assets.py
   - 预估行数: ~4
   - 验证点: compile; grep 确认 model_assets 无 os.environ HF_ENDPOINT 残留;
     现有 .ai_env 配置路径测试绿
   - 依赖: 无

3. buildSpawnEnv + 控制台 spawn 白名单化
   - 文件: control-manager.ts
   - 预估行数: ~45
   - 验证点: bun import 冒烟无错; kill 控制台后用 startControl 实测 spawn
     —— health ok; ps eww 实测子进程 environ 键集合 == {PATH, HOME,
     OPENCODE_ROOT, DATA_DIR}（±macOS 运行时自动补的 LC_CTYPE/__CF*）;
     OFFLINE 两键由 server.py setdefault 后存在于运行态（getenv 非 None）
   - 依赖: 无

4. MCP spawn 白名单化
   - 文件: mcp-manager.ts
   - 预估行数: ~3
   - 验证点: 4 MCP stdio 握手 + tools/list 全通（现成握手方法）; MCP 进程
     ps eww 键集合同上; test_proxy_mcp 2/2
   - 依赖: 3

5. launchd plist 对照核对
   - 文件: launchd_setup.py（按需）
   - 预估行数: ~10
   - 验证点: compile; plist EnvironmentVariables 与白名单语义一致
   - 依赖: 3

6. 集成测试白名单断言
   - 文件: tests/test_integration.py
   - 预估行数: ~45
   - 验证点: 独立进程全量绿——spawn 出的控制台子进程 environ 键集合断言
     == 白名单（防未来回归的全自动防线）
   - 依赖: 3, 4

7. 全量回归矩阵
   - 文件: 无新改动（执行既有测试 + 手动实测项）
   - 预估行数: 0
   - 验证点: test_control 全量; e2e 双套（remote/real）; test_proxy_mcp;
     test_integration; vite 拉起实测（kill vite → 控制台重启 → 前端 200）;
     模型下载子进程实测（offline 剥离逻辑在白名单态工作）;
     agent 切换自举实测（detect_py_deps scan exit 0）
   - 依赖: 1-6

8. 归档
   - 文件: progress 档案条目, pending-items.md（#1 勾选移入已完成）,
     knowledge-base 如有新模式
   - 预估行数: ~30
   - 验证点: pending-items #1 状态 ☑ 含日期与证据
   - 依赖: 7
```

## §4 验收标准

**功能验收**:
- 控制台 spawn 后 health ok; /api/config/meta、entity-search 422 契约正常
- 4 MCP 握手 + tools/list 全通; ocr/proxy 工具直调成功
- vite dev（.ai_env dev=1 时）正常拉起，前端 200
- 模型下载子进程（offline 剥离逻辑）正常
- agent 切换自举（env-check 第一层）通过
- .ai_env 配置 GITHUB_TOKEN 后工具下载加速生效; HF_ENDPOINT 走 .ai_env 生效

**回归验收**: §3.1 步骤 7 矩阵全绿。

**架构验收**:
- mcp-manager → control-manager 依赖方向不变，无反向依赖
- 白名单断言用例进 test_integration（自动化防线，非仅手动验证）
- 生产控制台 ps eww 业务键 = 0（机制保证，非环境巧合）

## §5 与现有需求文档的关系

- `pending-items.md` #1（TS spawn env 白名单化）: 本需求实施完成后勾选
- `progress-2026-09-26-backend-oop-refactor.md`: env 污染链系列修复的延续
  （`_refresh_env_from_ai_env` 删除、launchd plist 修复为本次前置）
- `pending-items.md` #5（Windows 分支）: 本需求 win32 分支仅语义编写，
  验证仍归 #5 跟踪
- `pending-items.md` #2（agent shell 业务键注入收紧）: 独立事项，不在本范围

## §6 实施结果（2026-09-27 完成）

全部 8 步按 §3.1 执行完毕，验证全绿（test_control 86/86、test_integration 6/6
含新场景 6 污染免疫、e2e 双套、4 MCP 握手、vite 前端 200、scan 68 包、
生产控制台 environ 恰好 4 键敏感键 0）。

实施中的方案修订（相对 §2）:
1. **MCP 白名单实现改为 `/usr/bin/env -i` 包装**: §2.2 原设想
   environment 字段提供白名单——实施时实测发现 opencode 对
   mcp.environment 是**合并语义**（`env: {...process.env, ...mcp.environment}`，
   opencode 源码 mcp/index.ts 实证），TS 侧无法剔除继承键。改为
   command 前置 `/usr/bin/env -i KEY=VAL ...`（exec 层清空一切父 env，
   机制保证）。win32 无 env 命令保持合并语义（归 pending-items #5）。
2. **HF_ENDPOINT 补注册**: 实施时发现 §2.3 所述"Keys 已有该键"有误——
   model_assets 此前用裸字符串查询。已补 Keys 常量 + ConfigField
   （config_meta 27→29 键，与 GITHUB_TOKEN 同批）。
3. **模型下载子进程未做真实网络下载实测**（避免副作用）: 静态验证
   剥离逻辑所需 PATH/HOME 均在白名单内，已缓存模型加载链（embed）实测正常。
4. **（用户审查修正）launchd plist 的 PATH/HOME 改 fail-fast**: 原实现
   缺失时静默塞默认值（死 PATH）——掩盖 spawn 链异常且难排查; 改为缺失抛
   RuntimeError。_plist_content 调用链: routes/remote.py:203（远程节点
   launchd 常驻开关）→ install() → _plist_content()，功能在用。
5. **（用户审查修正）.ai_env 模板补新键**: _TEMPLATE 静态文本补
   GITHUB_TOKEN/HF_ENDPOINT 注释行（配置页 meta 驱动不受影响，模板为新用户
   引导）; detect_tools docstring 修正为"从 .ai_env 读取（无 env 通道）"——
   get() 实现是纯文件解析，原"优先"表述不准确。
6. **（用户决策）MCP 回退 env 清理**: 修订 1 的 env -i 包装实施并验证后，
   经威胁模型讨论回退——MCP 是纯自研薄壳（零 huggingface import、零子进程、
   不读业务键），env 继承无执行面消费，清理必要性弱; 保持 opencode 合并
   语义直跑（与历史行为一致）。控制台白名单不受影响。env -i 机制知识
   备档 opencode-references.md 供未来收紧时使用。

生效时点: 控制台白名单即时生效（生产 60468）; MCP 白名单 command 在
opencode 下次重启后生效（注册发生在 opencode 启动时）。
