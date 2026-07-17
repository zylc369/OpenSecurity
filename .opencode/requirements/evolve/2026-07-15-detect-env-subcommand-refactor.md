# detect_env.py 子命令重构 + 依赖检测体系完善

## §1 背景与目标

### 来源痛点

| 痛点 | 根因 | 影响 |
|---|---|---|
| 首次使用 10+ 条错误信息轰炸 | `_check_preinstall` 收集所有错误统一返回 | 用户不知所措 |
| pip_name bug | mcp/sentence_transformers/sqlite_vec 的 pip_name 全是 `"angr"` | 自动安装时装错包 |
| MCP 依赖检测断裂 | `_detect_mcp_deps` 只被已删除的 `run_detection` 调用 | plugin 永远检测不到 MCP 缺失 |
| `agents=["all"]` 语义 bug | `_agent_matches` 不识别 dep.agents 里的 `"all"` 值 | MCP 包在子 agent 检测时被跳过 |
| playwright chromium 未检测 | `check-preinstall` 只查 Python 包 import，不查浏览器二进制 | chromium 缺失但不报错 |
| 无一键安装能力 | install.sh 硬编码 pip 列表，与 PYTHON_PACKAGES 脱节 | 维护两份包列表 |
| ZHIPU_API_KEY 缺失时仍启动容器 | `_detect_mcp_deps` 不管 ZHIPU 有没有都碰容器 | 浪费资源 |
| `--check-preinstall` 是参数不是子命令 | argparse 风格不一致 | 与 install 子命令风格不统一 |

### 预期收益

- 上下文：首次使用从 10+ 条错误 → 1 条 install_guide
- 轮次：用户从"不知道装什么"→ "运行一个脚本"
- 速度：fail-fast 第一个缺失即停，不浪费时间检测后续
- 准确度：修复 pip_name bug + agents=["all"] bug + chromium 检测

## §2 技术方案

### 2.1 子命令结构

```
detect_env.py install                              # 安装全部依赖（install.sh 调用）
detect_env.py check-preinstall <agent> [--output]  # 按 agent 检测（plugin 调用）
```

- 删除 `--check-preinstall` 参数、`--force` 参数、默认缓存读取模式
- `--output` 仅 `check-preinstall` 可选参数

### 2.2 Dependency 新增字段

```python
@dataclass
class Dependency:
    ...
    platforms: list[str] = field(default_factory=list)            # 空=全平台; ["darwin"]=仅 macOS
    platform_install_hint: dict[str, str] = field(default_factory=dict)
    # 按 OS 的安装描述。有当前 OS → 用它; 无 → 降级到 install_hint
```

### 2.3 EXTERNAL_TOOLS 补充字段

每个工具补充 `platforms` 和 `platform_install_hint`：

| 工具 | platforms | platform_install_hint |
|---|---|---|
| ida_pro | `[]`（全平台） | `{}`（用 install_hint，付费软件手动装） |
| apktool | `[]` | `{"darwin": "brew install apktool", "linux": "...", "win32": "..."}` |
| jadx | `[]` | `{"darwin": "brew install jadx", ...}` |
| adb | `[]` | `{"darwin": "brew install --cask android-platform-tools", "linux": "sudo apt install adb", ...}` |
| otool | `["darwin"]` | `{}`（macOS 自带） |
| ldid | `["darwin"]` | `{"darwin": "brew install ldid"}` |
| GoReSym | `[]` | `{"darwin": "...", "linux": "...", "win32": "..."}`（GitHub release） |

### 2.4 `_agent_matches` 修复

```python
def _agent_matches(dep):
    if agent == "all":
        return True
    return not dep.agents or "all" in dep.agents or agent in dep.agents
```

三种语义统一：`[]`=所有 agent、`["all"]`=所有 agent、`["binary-analysis"]`=指定 agent

### 2.5 `_detect_mcp_deps` 改造（ZHIPU 门控）

ZHIPU_API_KEY 先检。未配置 → 跳过 Docker/容器管理。已配置 → 才管理容器。

### 2.6 `install` 子命令行为

1. Python 包：遍历 PYTHON_PACKAGES **全部** pip install（不按 agent 过滤，忽略 preinstall 标志）
   - conda 包（sage, required=False）：打印 conda 安装提示，不强制
2. post_install：playwright → `playwright install chromium`（复用已有 `_post_install_playwright()`）
3. 外部工具：遍历 EXTERNAL_TOOLS **全部**（不按 agent 过滤）→ 按 `platforms` 过滤当前 OS → 缺失的打印 `platform_install_hint`（按当前 OS，降级到 install_hint）
4. events MCP 基础设施（ZHIPU_API_KEY 门控，复用已有 `_detect_mcp_deps()` 改造版）：
   - 未配置 → 控制台打印后果说明 → 跳过 Docker/容器
   - 已配置 → Docker 不在 → 打印需手动安装 → 容器不存在 → pull+run → 停止 → start → 在跑 → 不动

### 2.7 `check-preinstall AGENT` 子命令行为

1. PYTHON_PACKAGES：按 `_agent_matches` 过滤（忽略 preinstall 标志，全部检测）→ fail-fast 第一个缺失
2. Playwright chromium：playwright 包通过后 → 检测 chromium 二进制（复用 `_detect_playwright_browser()`）→ fail-fast
3. 编译器 → fail-fast
4. IDA Pro（按 agent 过滤）→ fail-fast
5. EXTERNAL_TOOLS（按 `_agent_matches` + `platforms` 过滤，跳过当前 OS 不适用的工具）→ fail-fast
6. events MCP 基础设施（所有 agent 都查，ZHIPU_API_KEY 门控）：
   - 未配置 → stderr 日志 → 跳过 Docker/容器 → 不阻塞
   - 已配置 → Docker 不在 → fail-fast → 容器不存在 → fail-fast → 停止 → 静默 start → 在跑 → 静默通过
7. fail-fast → 返回 `install_guide`
8. 全部通过 → 写 cache → 返回 `success: true`

### 2.8 数据库路径（已改）

```
~/bw-security-analysis/db/knowledge/knowledge.db   # knowledge MCP
~/bw-security-analysis/db/events/                   # events MCP (Neo4j Docker bind mount)
```

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `.opencode/binary-analysis/scripts/detect_env.py` | 重构 | 核心改动：子命令 + Dependency 字段 + _agent_matches + install 函数 + check-preinstall 更新 |
| `.opencode/plugins/lib/env-check.ts` | 修改 | buildDetectEnvArgs: `--check-preinstall` → `check-preinstall` 子命令 |
| `.opencode/install.sh` | 修改 | pip install 部分改为调 `detect_env.py install` |
| `.opencode/install.ps1` | 修改 | 同上 |
| `.opencode/agents/binary-analysis.md` | 修改 | detect_env.py 命令引用更新 |
| `.opencode/agents/crypto-analysis.md` | 修改 | 同上 |
| `.opencode/binary-analysis/knowledge-base/opencode-plugin-debugging.md` | 修改 | `--force` → `check-preinstall all` |
| `.opencode/binary-analysis/knowledge-base/web-rendering.md` | 修改 | `--force` → `install` |

### §3.1 实施步骤拆分

**步骤 1. Dependency dataclass 新增字段**
- 文件: detect_env.py
- 预估行数: ~15 行（新增 2 个字段 + 默认值）
- 验证点: `python -c "from dataclasses import fields; ..."` 确认新字段存在且有默认值
- 依赖: 无

**步骤 2. EXTERNAL_TOOLS 补充 platforms + platform_install_hint**
- 文件: detect_env.py
- 预估行数: ~40 行（7 个工具 × ~5 行）
- 验证点: 遍历 EXTERNAL_TOOLS 确认每个工具有 platforms 字段；ldid/otool 为 `["darwin"]`
- 依赖: 步骤 1

**步骤 3. 修复 `_agent_matches`**
- 文件: detect_env.py
- 预估行数: ~3 行（加 `"all" in dep.agents` 条件）
- 验证点: `agents=["all"]` 在 agent="binary-analysis" 时返回 True
- 依赖: 无

**步骤 4. 改造 `_detect_mcp_deps`（ZHIPU 门控）**
- 文件: detect_env.py
- 预估行数: ~30 行（ZHIPU 先检 + 条件分支管理容器）
- 验证点: ZHIPU 未配置时 neo4j_status.message 含"ZHIPU_API_KEY 未配置"；不执行 docker 命令
- 依赖: 无

**步骤 5. 新增 `_run_install()` 函数**
- 文件: detect_env.py
- 预估行数: ~80 行（pip install 全部 + playwright chromium + 外部工具提示 + events MCP）
- 验证点: `detect_env.py install` 运行后 pip list 确认包安装；控制台有外部工具安装提示
- 依赖: 步骤 1-4

**步骤 6. 更新 `_check_preinstall`（chromium 检测 + events MCP 逻辑 + platforms 过滤 + 忽略 preinstall）**
- 文件: detect_env.py
- 预估行数: ~40 行（加 chromium 检测分支 + events MCP ZHIPU 门控逻辑 + platforms 过滤 + 删除 `if not dep.preinstall: continue`）
- 验证点: playwright 包通过但 chromium 缺失 → fail-fast；ZHIPU 未配置 → 不检查 Docker；Linux 上跳过 ldid/otool
- 依赖: 步骤 3-4

**步骤 7. 重构 `main()`（子命令）**
- 文件: detect_env.py
- 预估行数: ~30 行（argparse 子命令 + 删除旧模式）
- 验证点: `detect_env.py install` 和 `detect_env.py check-preinstall binary-analysis` 正确路由
- 依赖: 步骤 5-6

**步骤 8. 更新 env-check.ts（子命令参数）**
- 文件: env-check.ts
- 预估行数: ~5 行（`--check-preinstall` → `check-preinstall`）
- 验证点: bun bundle 成功；buildDetectEnvArgs 输出正确参数
- 依赖: 步骤 7

**步骤 9. 更新 install.sh / install.ps1（调 detect_env.py install）**
- 文件: install.sh, install.ps1
- 预估行数: ~20 行（Step 3-5 合并为 `detect_env.py install`；末尾验证改为 `detect_env.py check-preinstall all`）
- 验证点: bash -n install.sh 通过；install.ps1 逻辑正确；不再有硬编码 pip 列表
- 依赖: 步骤 7

**步骤 10. 更新引用旧命令的文档**
- 文件: agents/binary-analysis.md, agents/crypto-analysis.md, knowledge-base/opencode-plugin-debugging.md, knowledge-base/web-rendering.md
- 预估行数: ~15 行（6 处引用，逐个替换 `--check-preinstall` → `check-preinstall`、`--force` → `check-preinstall all` 或 `install`）
- 验证点: grep 确认无 `--check-preinstall` / `--force` 残留
- 依赖: 步骤 7

## §4 验收标准

### 功能验收

| 验收项 | 验证方式 |
|---|---|
| `detect_env.py install` 安装全部 Python 包 | 运行后 pip list 确认 |
| `detect_env.py install` 安装 playwright chromium | `playwright install` 检测 |
| `detect_env.py install` 打印缺失外部工具的安装建议 | 控制台输出 platform_install_hint |
| `detect_env.py install` events MCP ZHIPU 门控 | ZHIPU 未配置时不执行 docker 命令 |
| `detect_env.py check-preinstall <agent>` fail-fast | 缺第一个必需依赖即停 |
| `detect_env.py check-preinstall` chromium 检测 | playwright 包在但 chromium 缺 → fail-fast |
| `detect_env.py check-preinstall` events MCP ZHIPU 门控 | ZHIPU 未配置 → 不阻塞 |
| `_agent_matches` 修复 | `agents=["all"]` 匹配所有 agent |
| Dependency 新字段 | platforms + platform_install_hint 存在 |
| env-check.ts 子命令参数 | buildDetectEnvArgs 输出 `check-preinstall` 而非 `--check-preinstall` |
| install.sh 调 detect_env.py install | 不再有硬编码 pip 列表 |

### 回归验收

| 验收项 | 验证方式 |
|---|---|
| knowledge MCP server 启动 | server.py 语法检查 + DB_PATH 正确 |
| events MCP server 启动 | server.py + graphiti_config.py 语法检查 |
| env_cache.json 写入 | check-preinstall 成功后 cache 有数据 |
| install_guide 生成 | fail-fast 时 JSON 含 install_guide 字段 |

### 架构验收

| 验收项 | 验证方式 |
|---|---|
| 无死代码 | run_detection 已删除；无未调用函数 |
| 依赖方向正确 | detect_env.py 不引用 mcp-servers 代码 |
| 数据库路径统一 | knowledge → db/knowledge/；events → db/events/ |

## §5 与现有需求文档的关系

- `.opencode/requirements/evolve/2026-07-14-events-mcp-implementation.md` — events MCP 实施文档，本文档与其无冲突，本文档聚焦 detect_env.py 重构
- 无前置依赖需求
