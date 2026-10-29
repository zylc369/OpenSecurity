# 需求: 节点 ffmpeg 依赖闭环（TTS 变速）+ detect_tools tags 维度

## §1 背景与目标

**来源**: 手机端（legado 定制引擎）传 `speed=0.8` 变速参数 → 节点 worker 合成成功后跑
ffmpeg atempo → `FileNotFoundError: 'ffmpeg'` → 503 直传手机，变速档合成失败。

**根因（四个断点）**:
1. 节点（MacMini）完全没有 ffmpeg（PATH 与 `$OPENSECURITY_HOME/bin` 均无）
2. detect_tools 的 ffmpeg 安装配方（UrlRecipe，静态构建直链）存在但触发链断: 唯一自动
   入口是主控 `.opencode/install.sh`（全量 install）; 节点引导链
   （remote_node.ensure_deps）只覆盖 pip 依赖 + 模型，无外部工具维度
3. worker `_atempo` 用裸 `"ffmpeg"` 走 subprocess PATH 查找——detect_tools 产物落
   `$OPENSECURITY_HOME/bin`（CMD_DIR），节点 server/worker PATH 未必含该目录
   （LaunchAgent 从安装时刻 environ 继承）→ 装了也可能调不到
4. ffmpeg 缺失无健康暴露: 仅 worker stderr 警告（tts_worker.py L256）+ 503 detail，
   主控远程页不可见，只能被动发现

**主控场景已闭环（本次不改）**: install.sh 全量装外部工具; UrlRecipe 幂等语义
"安装时 PATH 已有该工具则跳过"——主控 brew ffmpeg 场景正确跳过，which 可找到。

**预期收益**:
- 节点无人值守闭环: 引导链自动检测并安装 ffmpeg
- 手机端变速档（0.5-3.0）直跑节点成功，不再 503/主控兜底绕路
- 变速能力健康可见: 主控远程页显示节点 ffmpeg 可用性

## §2 技术方案

### 改动 1: detect_tools 补 tags 维度（对齐 detect_py_deps 的 DepTag 模式）

- 新增 `ToolTag` 枚举，首成员 `TTS_RUNTIME`（TTS 运行时场景）
- `ToolField` 加 `tags: tuple[ToolTag, ...] = ()` 字段（向后兼容默认空）
- `EXTERNAL_TOOLS` 新增 ffmpeg 条目: `tags=(ToolTag.TTS_RUNTIME,)`、agents 空列表
  （不绑定单一 agent，工具页 "all" 组可见）
- 新增 `tool_available(name: str) -> bool`: shutil.which → CMD_DIR 回落
  （工具检测唯一入口纪律: 全仓其他模块禁止直接 which 检测）
- 新增 `install_by_tags(tags: list[ToolTag], ...) -> list[InstallResult]`:
  按 ToolField.tags 圈选 names → 逐个 install_tool（复用现有单工具安装，
  幂等/force 语义不变）

### 改动 2: 节点引导链补 ffmpeg（remote_node.ensure_deps）

- tts 分支追加: `model_tags 含 "tts" 且 not tool_available("ffmpeg")`
  → `install_by_tags([ToolTag.TTS_RUNTIME])`
- 安装失败不 fail-fast（原速 TTS 仍可用）: 显式警告 + health 暴露 false

### 改动 3: worker ffmpeg 双路解析（tts_worker）

- 新增 `_ffmpeg_bin() -> str`: `shutil.which("ffmpeg")` 优先（brew/系统来源）
  → `$OPENSECURITY_HOME/bin/ffmpeg`（detect_tools 来源; worker 自包含，
  直接 os.environ 拼，不 import services）
- 两级皆缺: 报错信息指引安装途径（外部工具页 / install.sh / brew）
- `_atempo` 与启动检测（L256 警告处）统一改用 `_ffmpeg_bin()`

### 改动 4: ffmpeg 能力位上 health（两端贯通）

- 节点/主控 `/api/health` 载荷加 `ffmpeg_available: bool`（调 tool_available）
- `RemoteHealthInfo`（remote_client.py）加同名字段，节点 health 解析时透传
- 主控 TtsService 远程优先逻辑不改（无熔断——ffmpeg 修复后 503 场景消失，
  熔断属过度设计）

### 改动 5: 前端远程页展示（RemoteSection）

- 远程健康区显示"变速: 可用/不可用"（消费 remote_health.ffmpeg_available）

## §3 实现规范

### 改动范围表

| 文件 | 改动 | 预估行数 |
|---|---|---|
| services/detect_tools.py | ToolTag/ToolField.tags/ffmpeg 条目/tool_available/install_by_tags | ~80 |
| services/remote_node.py | ensure_deps 补 ffmpeg 检测+安装 | ~20 |
| scripts/tts_worker.py | _ffmpeg_bin + 调用点替换 | ~30 |
| routes/health.py | ffmpeg_available 字段 | ~8 |
| services/remote_client.py | RemoteHealthInfo 加字段+解析 | ~8 |
| frontend RemoteSection.tsx | 变速能力展示 | ~15 |
| tests/test_detect_tools_tags.py | 新测试 | ~90 |

### 编码规则

- 工具检测唯一入口: tool_available 收口在 detect_tools（grep 唯一性验证）
- worker 自包含: 不 import services（现有架构约束）
- ToolField 新字段带默认值（既有构造点零改动）
- install_by_tags 复用 install_tool（不重复实现下载/解压逻辑）
- 前端只读展示，无状态管理

### §3.1 实施步骤拆分

步骤 1. detect_tools tags 维度 + ffmpeg 条目 + tool_available
  - 文件: services/detect_tools.py
  - 预估行数: ~80
  - 验证点: `python -c` 导入无错; `tool_available("ffmpeg")` 主控返回 True
    （brew 在 PATH）; ffmpeg 条目出现在 EXTERNAL_TOOLS（长度 +1）
  - 依赖: 无

步骤 2. detect_tools install_by_tags 安装入口
  - 文件: services/detect_tools.py
  - 预估行数: ~30
  - 验证点: `install_by_tags([TTS_RUNTIME])` 幂等语义正确（主控 PATH 有 ffmpeg
    → UrlRecipe PATH 跳过分支生效，不重复下载——读 _already/PATH 幂等代码确认）
  - 依赖: 步骤 1

步骤 3. worker 双路解析
  - 文件: scripts/tts_worker.py
  - 预估行数: ~30
  - 验证点: 语法检查; 单测 mock which=None + OPENSECURITY_HOME 指向 tmp
    → _ffmpeg_bin 返回 CMD_DIR 路径; 两级皆缺抛 RuntimeError 含指引文案
  - 依赖: 无

步骤 4. 节点引导链补 ffmpeg
  - 文件: services/remote_node.py
  - 预估行数: ~20
  - 验证点: 语法检查; 代码 review——只在 model_tags 含 tts 分支追加，
    默认安全组路径行为不变; 安装失败路径只警告不抛
  - 依赖: 步骤 1、2

步骤 5. health 能力位（节点源头 + remote_client 透传）
  - 文件: routes/health.py、services/remote_client.py
  - 预估行数: ~16
  - 验证点: 主控 GET /api/health 响应含 ffmpeg_available=true;
    RemoteHealthInfo dataclass 编译无错
  - 依赖: 步骤 1

步骤 6. 前端远程页展示
  - 文件: frontend/src/sections/RemoteSection.tsx
  - 预估行数: ~15
  - 验证点: tsc 0 错误; vitest 全绿; 展示逻辑读 remote_health?.ffmpeg_available
  - 依赖: 步骤 5（字段类型同步 frontend types 如需）

步骤 7. 新测试 + 全量回归
  - 文件: tests/test_detect_tools_tags.py（tool_available 回落/tags 圈选/
    install_by_tags 过滤逻辑）; tests/test_tts_worker_speed.py 补 _ffmpeg_bin 用例
  - 预估行数: ~90
  - 验证点: backend pytest 全绿（294 基线 + 新增）; 前端 vitest 全绿
  - 依赖: 步骤 1、2、3

步骤 8. 部署 + 端到端验证
  - 动作: 提交推送 → 主控重启 → 节点 update-restart（触发引导链自动装 ffmpeg）
    → 节点 health ffmpeg_available=true → 全新文本 speed=0.8/1.5/3.0 三档
    /api/tts 全部成功且主控日志无 "fallback 本地"
  - 验证点: 节点 CMD_DIR 出现 ffmpeg（health 确认）; 变速档远程直跑;
    若节点安装失败（网络）→ 健康位 false + 警告日志可诊断
  - 依赖: 步骤 1-6 全部

## §4 验收标准

### 功能验收
1. 节点 update-restart 后: 引导链自动安装 ffmpeg（CMD_DIR 产物存在），
   节点 /api/health 返回 ffmpeg_available=true
2. 手机端同款请求（网关 /tts speed=0.8）: 节点直跑成功，无 503，
   主控日志无 "fallback 本地"（远程变速直通）
3. 主控远程页显示节点"变速: 可用"
4. worker 双路解析: which 命中优先（主控 brew 场景回归不变）; CMD_DIR 场景
   （OPENSECURITY_HOME 注入 + which 未命中）正确回落
5. detect_tools: ffmpeg 出现在工具扫描表（all 组）; install_by_tags 幂等

### 回归验收
1. backend pytest 全绿（294 基线 + 新增用例）
2. 前端 vitest 全绿 + tsc 0 错误
3. 主控现有 atempo 变速（speed≠1 全档）行为不变
4. 节点默认安全组（model_tags 不含 tts）引导路径行为不变
5. /api/health 既有字段与消费方（boot_token 轮询/code_stale）不受影响

### 架构验收
1. 工具检测唯一入口: 全仓 grep "shutil.which" 仅 detect_tools 与 worker
   _ffmpeg_bin（双路解析属 worker 自包含例外，与 tts_worker 既有 which
   使用一致）——无新增散落检测
2. worker 不 import services（自包含约束保持）
3. tags 维度与 detect_py_deps.DepTag 模式对齐（枚举+字段+圈选安装）
4. 依赖方向不变: routes → services; worker 独立

## §5 与现有需求文档的关系

- `2026-10-19-mobile-custom-tts.md`（手机端定制 TTS）: 本需求补全其服务端
  变速档依赖（该文档的 CustomTtsVoiceParams.speed 0.5-3.0 服务端语义至此
  全链路真实可用）; 手机端代码零改动
- `auto-install-external-tools.md`（外部工具自动安装）: 本需求的 install_by_tags
  是其 tags 化演进; install.sh 全量入口不变
- 无冲突: 不改 install.py（Python 包专用）、不改 TtsService 路由逻辑
