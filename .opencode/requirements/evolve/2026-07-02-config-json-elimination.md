# 需求文档: 消除 config.json，外部工具收口到 detect_env.py（结构化重构）

## §1 背景与目标

**来源**: 2026-07-02 与用户讨论。当前外部工具（apktool/jadx/adb/IDA Pro 等）通过 `~/bw-security-analysis/config.json` 配置，存在三类问题：

1. **文档错误**: README.md L87 称"detect_env.py 写入 config.json"，但实际 detect_env 只读不写（写的是 env_cache.json）。security-analysis.ts L617 报错文案也称"应由 AI 调用 detect_env.py 完成初始化"，但 detect_env 不创建 config.json。文档与代码矛盾。
2. **配置脆弱**: config.json 靠用户手敲 JSON（或 AI 引导写），少个逗号即崩；config.json 不存在会触发 Plugin abort + 命令拦截，是一类故障源。
3. **架构割裂**: 工具的"声明"（有哪些工具、属哪个 agent）散落在 config.json，而 Python 包的声明在 detect_env.py，两套机制不统一。

**目标**:
1. 删除 config.json 依赖，外部工具声明收口到 detect_env.py 的 `EXTERNAL_TOOLS` registry（与 Python 包的 `PYTHON_PACKAGES` 并列，统一用 `Dependency` dataclass）
2. IDA Pro 路径改由 `.ai_env` 文件的 `IDA_PRO_HOME` 环境变量提供（替代 config.json 的 ida_path），detect_env.py 自动创建 `.ai_env` 模板
3. Plugin 改为从 env_cache.json 读取 ida_pro/tools 状态（单源），删除 config.json 读取逻辑
4. 用 `Dependency` dataclass 规范化 `REQUIRED_PACKAGES`（现 dict 字段越加越多，无约束）
5. 清理所有 config.json 相关文档/prompt 提示

**预期收益**（四维度量）:
- 上下文: Plugin 不再双源拼装（config + env_cache），代码简化
- 轮次: 新机器配置免手敲 JSON，省 1-2 轮（IDA 路径改为填 `.ai_env` 的 KEY=VALUE，比 JSON 友好）
- 准确度: 消除 config.json 格式错误故障源 + 文档代码矛盾

**不兼容声明**: 直接删除 config.json 依赖，不做迁移。现有用户重启后 detect_env 重新检测（IDA 靠 `.ai_env` 的 IDA_PRO_HOME，detect_env 首次运行自动生成 `.ai_env` 模板引导填写）。

## §2 技术方案

### 2.1 数据结构: Dependency dataclass

统一 Python 包和外部工具的元数据。两个 registry 共用此结构：

```python
@dataclass
class Dependency:
    name: str                              # python: import名; tool: 标识名(ida_pro/apktool)
    kind: Literal["python", "tool"]        # 驱动检测分发
    required: bool = True
    preinstall: bool = False               # True=用户预装只检测不自动装; False=自动安装
    agents: list[str] = field(default_factory=list)   # 空=所有 agent
    description: str = ""
    install_hint: str = ""                 # 缺失时展示给用户的具体指引
    # --- python 专属 ---
    pip_name: str | None = None
    conda_name: str | None = None
    installer: Literal["pip", "conda"] = "pip"
    post_install: bool = False
    version_via: str | None = None         # None | "importlib:PKG"
    # --- tool 专属 ---
    version_cmd: list[str] = field(default_factory=list)
    env_var: str = ""                      # 路径来源(空=靠 PATH which; IDA=IDA_PRO_HOME)
```

**无 scan_paths 字段**（用户明确要求不支持扫描逻辑）。IDA Pro 纯靠 `IDA_PRO_HOME` 环境变量。

### 2.2 两个 registry

- `PYTHON_PACKAGES: list[Dependency]` — 现有 `REQUIRED_PACKAGES` dict 重构而来（angr/triton/z3/capstone/.../sage）
- `EXTERNAL_TOOLS: list[Dependency]` — 现有 config.json tools 字段收口而来（ida_pro/apktool/jadx/adb/otool/ldid/goresym）

### 2.3 工具路径发现（统一分发）

```python
def _resolve_tool(dep: Dependency) -> tuple[str, bool]:
    if dep.env_var:
        home = os.environ.get(dep.env_var, "")   # .ai_env 启动时已 merge 进 os.environ
        if home:
            idat = "idat.exe" if os.name == "nt" else "idat"
            cand = os.path.join(home, idat)
            if os.path.isfile(cand):
                return (cand, True)
        return ("", False)   # 声明了 env_var 但没配/路径错 → 直接失败
    # 无 env_var → 靠 PATH which（apktool/jadx 等）
    r = shutil.which(dep.name)
    return (r or dep.name, bool(r))
```

- IDA Pro (`env_var="IDA_PRO_HOME"`): 没配就 preinstall 失败，install_hint 指引填 `.ai_env`
- apktool/jadx (`env_var=""`): 靠 PATH which

### 2.4 .ai_env 机制

- **位置**: `$OPENCODE_ROOT/.ai_env`（OPENCODE_ROOT = `.opencode` 父目录，非 cwd）
- **文件名**: `.ai_env`（不用 `.env`，避免与通用 .env 语义冲突）
- **加载者**: detect_env.py 独占（自写简单解析器，KEY=VALUE，忽略 # 注释和空行，不引入 python-dotenv 依赖）。启动时 merge 进 `os.environ`（不覆盖已存在的系统 env，即系统 env 优先级高于 .ai_env）
- **创建**: detect_env.py 首次运行（`.ai_env` 不存在）自动创建带注释模板（含 `IDA_PRO_HOME=` 待填行）
- **OPENCODE_ROOT 定位**: detect_env.py 通过 `os.environ.get("OPENCODE_ROOT")` 读取。Plugin 在 constants.ts 计算后立即 `process.env.OPENCODE_ROOT = OPENCODE_ROOT`，runProcess 的 `{...process.env}` 自动传播到 detect_env 子进程（两条调用路径都覆盖）

**.ai_env 模板**（detect_env.py 自动生成）:
```ini
# bw-security-analysis 环境变量配置
# 按需填写，填完保存即可（detect_env 下次自动读取）

# IDA Pro 安装目录（含 idat 的目录）
IDA_PRO_HOME=
```

### 2.5 env_cache.json 输出结构扩展

detect_env.py 把检测结果写入 `~/bw-security-analysis/env_cache.json`（现有），扩展字段：

- `ida_pro`: 增加 `idat_path`（resolved idat 全路径，供 Plugin 拼 `$IDAT`）
- `tools`: 每个工具增加 `description`、`resolved_path`（供 Plugin 注入环境信息段）

### 2.6 Plugin 改动

- `constants.ts`: 加 `process.env.OPENCODE_ROOT = OPENCODE_ROOT`；删 `CONFIG_FILE` 常量
- `security-analysis.ts`:
  - 删 `ConfigData`/`ToolConfig` interface、`getToolsForAgent` 函数
  - `EnvData` interface 扩展（tools 加 description/resolved_path；ida_pro 加 idat_path）
  - `system.transform`（L609-624）: 删 config.json 存在性 abort → 改依赖 env_cache.json
  - `shell.env`（L715-719）: `$IDAT` 从 env_cache 的 `ida_pro.idat_path` 读，不再 config 拼。**时序依赖**: env_cache 由 agent 初始化时跑 detect_env 生成（24h TTL），checkPreinstall 只跑 `--check-preinstall` 不生成 env_cache。正常流程下 env_cache 在 $IDAT 首次需要前已生成（agent 阶段 A 跑 detect_env）；env_cache 不存在时 $IDAT 不注入，binary-analysis agent 自愈流程跑 `detect_env --force` 后恢复（见步骤 10）
  - `buildEnvSection`（L175-223）: ida/tools 段全改读 env_cache（envInfo），不再读 config
  - `tool.execute.before`（L775-796）: 删 config.json 拦截分支（checkPreinstall 已兜底环境就绪）

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响级别 |
|------|---------|---------|
| `binary-analysis/scripts/detect_env.py` | 重构（dataclass + .ai_env + registry） | 高（所有 agent 依赖） |
| `plugins/security-analysis.ts` | 删 config 读取逻辑，改读 env_cache | 高（所有 agent 环境注入） |
| `plugins/lib/constants.ts` | 加 process.env.OPENCODE_ROOT，删 CONFIG_FILE | 中 |
| `agents/binary-analysis.md` | 删 L43 config.json 写入指引；"变量丢失自愈"段补充 $IDAT 兜底（$IDAT 未注入时跑 `detect_env --force` 生成 env_cache） | 中 |
| `agents/security-analysis-evolve.md` | 删 L447 config.json idat 路径引用 | 低 |
| `binary-analysis/environment-setup.md` | 删"配置文件结构"章节，改述 .ai_env | 中 |
| `binary-analysis/context-persistence.md` | 删 config.json 描述 | 低 |
| `binary-analysis/knowledge-base/task-initialization.md` | 删 config.json 提及 | 低 |
| `binary-analysis/knowledge-base/subsession-orchestration.md` | 删 config.json 提及（delegate_timeout） | 低 |
| `binary-analysis/knowledge-base/opencode-plugin-debugging.md` | 删 config.json 调试章节 | 低 |
| `commands/gui-interact-pc.md` | 删 config.json scripts_dir 提及 | 低 |
| `docs/项目介绍/新机器配置指南.md` | 删 §5 创建配置文件，改述 .ai_env | 中 |
| `README.md` / `README.en.md` | 删配置 IDA Pro 章节的 config.json 描述 | 中 |

### §3.1 实施步骤拆分

**步骤 1. detect_env.py: 新增 Dependency dataclass + .ai_env 基础设施**
  - 文件: `binary-analysis/scripts/detect_env.py`
  - 改动: 新增 `Dependency` dataclass、`_get_opencode_root()`、`.ai_env` 解析器（`_load_ai_env()`，解析 KEY=VALUE，**用 `os.environ.setdefault(key, value)` 合并**——系统 env 优先级高于 .ai_env，避免 .ai_env 覆盖用户 shell export 的值）、首次创建模板逻辑（`_ensure_ai_env_template()`）
  - 预估行数: ~80 行新增
  - 验证点: `python -c "compile(...)"` 通过；手动删 .ai_env 后跑 detect_env，确认模板自动生成
  - 依赖: 无

**步骤 2. detect_env.py: REQUIRED_PACKAGES dict → PYTHON_PACKAGES list[Dependency]**
  - 文件: `binary-analysis/scripts/detect_env.py`
  - 改动: dict 重构为 list[Dependency]；`run_detection`/`_detect_package`/`_install_package`/`_check_preinstall` 中遍历逻辑从 dict.items() 改为遍历 list + 读 dataclass 字段（dep.pip_name/dep.required 等）
  - 预估行数: ~90 行修改
  - 验证点: `python detect_env.py --force` 跑通，输出 packages 检测结果与重构前一致
  - 依赖: 步骤 1

**步骤 3. detect_env.py: 新增 EXTERNAL_TOOLS registry + 工具检测改造（删 config.json 读取）**
  - 文件: `binary-analysis/scripts/detect_env.py`
  - 改动:
    - 新增 `EXTERNAL_TOOLS` list[Dependency]（ida_pro/apktool/jadx/adb/otool/ldid/goresym）
    - 新增 `_resolve_tool(dep)` 统一分发（见 §2.3），**替换**现有 `_resolve_tool_path`（L303，后者仅处理 path 字符串，不感知 env_var；新函数 dataclass 驱动，统一入口）
    - `_resolve_tool` 只负责路径解析；版本检测仍由现有 `_get_tool_version`（L321）负责，`_detect_tools` 串联两者（resolve → 若 found → get_version）
    - 改 `_detect_ida_pro`（L287）从读 config.json → 调 `_resolve_tool(ida_pro_dep)`，包装返回 `{available, path, idat_path}`（idat_path = resolved 全路径，供 Plugin 拼 $IDAT）
    - 改 `_detect_tools`（L334）从读 config.json → 遍历 EXTERNAL_TOOLS（按 agent 过滤 agents 字段）
    - 删所有 `open(config_file)` 读取代码（L289/L476-491）
  - 预估行数: ~120 行修改/新增
  - 验证点: `python detect_env.py --force` 输出含 ida_pro（配了 IDA_PRO_HOME 时 available + idat_path）+ tools（apktool 等按 PATH 检测）；不读 config.json
  - 依赖: 步骤 2

**步骤 4. detect_env.py: _check_preinstall 扩展支持 tool 类**
  - 文件: `binary-analysis/scripts/detect_env.py`
  - 改动: `_check_preinstall(agent)` 遍历 PYTHON_PACKAGES + EXTERNAL_TOOLS 中 preinstall=True 且 agents 匹配的条目；按 kind 分发（python→find_spec，tool→_resolve_tool）；缺失收集到 errors（含 install_hint）一次性返回
  - 预估行数: ~50 行修改
  - 验证点: `python detect_env.py --check-preinstall binary-analysis` 检查 ida_pro；`--check-preinstall mobile-analysis` 检查 apktool/jadx/adb；缺失时 errors 含 install_hint
  - 依赖: 步骤 3

**步骤 5. detect_env.py: env_cache.json 输出结构扩展**
  - 文件: `binary-analysis/scripts/detect_env.py`
  - 改动: `_save_cache` 的 data 中 tools 每项加 description/resolved_path；ida_pro 加 idat_path
  - 预估行数: ~20 行修改
  - 验证点: `python detect_env.py --force` 后读 env_cache.json，结构含新字段
  - 依赖: 步骤 3

**步骤 6. constants.ts: 注入 process.env.OPENCODE_ROOT**
  - 文件: `plugins/lib/constants.ts`
  - 改动: OPENCODE_ROOT 定义后加 `process.env.OPENCODE_ROOT = OPENCODE_ROOT;`
  - ⚠ 不在此步删 CONFIG_FILE：security-analysis.ts（步骤 9）仍引用它，提前删会导致步骤 7-8 的 node --check 失败。CONFIG_FILE 删除推迟到步骤 9（引用全部清除后）
  - 预估行数: ~1 行新增
  - 验证点: `node --check constants.ts` 通过
  - 依赖: 无（与步骤 1-5 并行）

**步骤 7. security-analysis.ts: EnvData 扩展（纯增量，不删任何定义）**
  - 文件: `plugins/security-analysis.ts`
  - 改动: `EnvData.data` 扩展（tools 项加 description/resolved_path；ida_pro 加 idat_path）。此步只加字段，不删 ConfigData/ToolConfig/getToolsForAgent——它们的消费者（buildEnvSection 步骤 8 改、system.transform/shell.env 步骤 9 改）尚未清除，提前删会导致中间态编译失败
  - 预估行数: ~15 行新增
  - 验证点: `node --check` 通过（纯增量，不破坏现有引用）
  - 依赖: 步骤 6

**步骤 8. security-analysis.ts: buildEnvSection 改读 env_cache（含两处调用方同步）**
  - 文件: `plugins/security-analysis.ts`
  - 改动:
    - `buildEnvSection`（L158）的 ida 段从 `config.ida_path` → `envInfo.ida_pro.idat_path`；tools 段从 `config.tools` + `getToolsForAgent` → 遍历 `envInfo.tools`（含 description/resolved_path/version）；函数签名去掉 config 参数
    - ⚠ 同步改两处调用方（签名变更必须与调用方同步骤，否则编译失败）: L492 `buildEnvSection(agentName, config || {}, envInfo, sid)` → 去掉 config；L647 同理
    - 删 `getToolsForAgent` 函数（L63，其唯一消费者是 buildEnvSection，改造后无引用）
    - ⚠ 不删 ConfigData/ToolConfig：ConfigData 仍被 system.transform(L609)/shell.env(L716) 引用，ToolConfig 被 ConfigData.tools 引用，推迟到步骤 9
  - 中间态说明: 此步后 system.transform 的 L647 调用已去 config 参数，但 L609 的 `const config = readJsonSafe(CONFIG_FILE)` 仍在（config 变量读而不用，TS 允许）。L609-624 的 abort 逻辑删除推迟到步骤 9
  - 预估行数: ~60 行修改
  - 验证点: `node --check` 通过（L492/L647 调用方已同步去 config 参数）
  - 依赖: 步骤 7

**步骤 9. security-analysis.ts + constants.ts: 清除全部 config 引用**
  - 文件: `plugins/security-analysis.ts`、`plugins/lib/constants.ts`
  - 改动（全面清理 CONFIG_FILE/ConfigData 的所有引用点，盘点如下）:
    - L9: 删 `CONFIG_FILE` import
    - L387/L394: 删启动调试日志中的 `CONFIG_FILE` / `existsSync(CONFIG_FILE)` 两行
    - L488: compacting hook 删 `const config = readJsonSafe<ConfigData>(CONFIG_FILE, sid)`（步骤 8 已改 L492 调用去 config，此变量已无消费者）
    - L609-624: system.transform 删 config.json 存在性 abort 整块（含 L612/617 错误消息）+ 删 `const config = readJsonSafe`
    - L715-719: shell.env 的 `$IDAT` 改从 env_cache 读 `ida_pro.idat_path`（读 ENV_CACHE_FILE）；删 `const config = readJsonSafe<ConfigData>(CONFIG_FILE)`
    - L775-796: tool.execute.before 删 config.json 拦截分支（L776 existsSync 整块）
    - L44: 删 `ConfigData` interface（此时所有引用已清除）
    - L36: 删 `ToolConfig` interface（ConfigData 删后无消费者）
    - `constants.ts` L25: 删 `CONFIG_FILE` 常量定义
  - 预估行数: ~70 行修改/删除
  - 验证点: `node --check security-analysis.ts` + `node --check constants.ts` 通过；`rg "CONFIG_FILE|ConfigData|ToolConfig" .opencode/plugins/` 返回 0
  - 依赖: 步骤 8

**步骤 10. 文档清理: 删除 config.json 相关提示**
  - 文件: binary-analysis.md、security-analysis-evolve.md、environment-setup.md、context-persistence.md、task-initialization.md、subsession-orchestration.md、opencode-plugin-debugging.md、gui-interact-pc.md、新机器配置指南.md、README.md、README.en.md
  - 改动: 删除/改写所有 config.json 引用（写入指引、配置文件结构章节、调试说明等），改述为 `.ai_env` + IDA_PRO_HOME 机制
  - ⚠ `subsession-orchestration.md` 的 `delegate_timeout_minutes`：调研确认代码从未读取此字段（grep 零代码命中，仅文档声称"通过 config.json 配置"）。属于"文档声称但未实现"的历史遗留。本次直接删除该配置说明，超时时间保持代码默认值（10 分钟）。不迁移到 .ai_env（避免为未实现特性新增配置入口）
  - 预估行数: ~40 行修改（分散在 11 个文件）
  - 验证点: `rg "config\.json" .opencode/agents .opencode/binary-analysis .opencode/commands README.md README.en.md docs/项目介绍` 返回 0（排除 requirements/evolve 历史文档）
  - 依赖: 步骤 9

**步骤 11. 端到端验证**
  - 执行验证点:
    1. 删除 `~/bw-security-analysis/config.json` 和 `env_cache.json`，跑 `detect_env.py --force`，确认 `.ai_env` 自动生成、检测正常
    2. `.ai_env` 填入 `IDA_PRO_HOME=<真实路径>`，重跑，确认 ida_pro available + idat_path 写入 env_cache
    3. `detect_env.py --check-preinstall binary-analysis`（IDA_PRO_HOME 未配时返回 errors 含 install_hint；配了时 success:true）
    4. Plugin 加载（opencode 启动）确认 system.transform 注入环境信息段含 IDA/tools、shell.env 注入 $IDAT
  - 依赖: 步骤 1-10

## §4 验收标准

### 功能验收
- [ ] config.json 不再被任何代码读取（detect_env.py、security-analysis.ts、constants.ts 无引用）
- [ ] detect_env.py 用 `Dependency` dataclass 定义 PYTHON_PACKAGES + EXTERNAL_TOOLS
- [ ] detect_env.py 首次运行自动生成 `$OPENCODE_ROOT/.ai_env` 模板
- [ ] detect_env.py 读取 `.ai_env` 的 IDA_PRO_HOME 并检测 IDA（配了→available，没配→preinstall 失败含 install_hint）
- [ ] `_check-preinstall <agent>` 检查该 agent 全部 preinstall 依赖（python+tool），缺失一次性返回 errors
- [ ] env_cache.json 含 ida_pro.idat_path 和 tools[].description/resolved_path
- [ ] Plugin 的 `$IDAT` 从 env_cache.json 读取（不再 config 拼）
- [ ] Plugin 不再有 config.json 存在性 abort / 命令拦截逻辑

### 回归验收
- [ ] detect_env.py 语法检查通过
- [ ] security-analysis.ts / constants.ts `node --check` 通过
- [ ] detect_env.py `--force` 全量检测跑通（packages + ida_pro + tools）
- [ ] Plugin 加载后环境信息段注入正常（IDA/tools/compiler/packages）
- [ ] binary-analysis.md agent prompt 展开后 < 450 行

### 架构验收
- [ ] 依赖方向: detect_env.py 不反向引用 Plugin/agent（单向）
- [ ] 无循环依赖
- [ ] 工具声明单一来源（EXTERNAL_TOOLS），不再散落 config.json + 代码两处
- [ ] `Dependency` dataclass 统一 python/tool 元数据结构

## §5 与现有需求文档的关系

- `2026-04-22-environment-dependency-hardening.md`: 本需求在其 env_cache.json 机制基础上扩展（新增 ida_pro.idat_path、tools 字段）。env_cache.json 的 venv_python/compiler/packages 结构不变
- `2026-04-29-directory-and-plugin-rename.md`: 已完成（数据目录已是 bw-security-analysis）。本需求复用该目录放 env_cache.json
- `2026-04-29-mobile-analysis-agent.md`: 引入了 config.json 的 tools 字段结构（apktool/jadx/adb）。本需求将这些 tools 收口到 EXTERNAL_TOOLS，删除 config.json 依赖。该历史文档不修改（历史归档）
- 本需求**不兼容**旧 config.json，现有用户需按 `.ai_env` 重新配置 IDA_PRO_HOME（detect_env 自动生成模板引导）
