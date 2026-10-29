# 需求: pyright 静态类型检查引入（一期）

> 状态: 已实施（见 §6 实施结果）
> 日期: 2026-09-29
> 来源: pending-items #4（控制台 OOP 重构期的 #6/#8/#12 三 bug 均属
> "运行时才解析的名称引用"类，人工 AST 契约规则是逐个 chasing，
> 类型检查器是一次性根治）

## §1 背景与目标

**痛点**: #6（`_is_dev` 类当谓词恒真）、#8（staticmethod 引 self）、
#12（CLI 入口裸调用 NameError）三 bug 同族——静态可抓但靠人工复盘发现。

**一期目标**: 落地 pyright 配置 + 消灭最高价值的 `reportUndefinedVariable`
族（运行时必炸的真 bug）+ 回归全绿。注解完备性（Unknown/Any 类 1400+）
与类型流精确性（ArgumentType 68）留二期。

**工具形态**: 全局已装 basedpyright 1.39.9（pyright 分支，CLI 兼容），
零新依赖。

## §2 技术方案

### §2.1 配置（`.opencode/control/backend/pyrightconfig.json`）

- 范围: services/ + server.py + routes/（tests 排除; mcp-servers 二期）
- basic 档 + 显式关闭注解完备性规则 14 条（reportUnknown* / reportAny /
  reportUnannotated* / reportMissingTypeArgument 等）
- 保留 bug 类规则: UndefinedVariable / AttributeAccessIssue / ArgumentType /
  ReturnType / ImportCycles / ConstantRedefinition 等

### §2.2 一期修复清单（UndefinedVariable 20 → 0，实修 8 文件）

**族系一: Python 类命名空间盲区**（类体绑定的名字在方法内不可裸访问——
类作用域不在函数名字查找链）:
- `model_assets.py` / `model_loader.py` / `model_lifecycle.py` /
  `ocr_engines.py`: 类体 `logger = logging.getLogger(...)` 绑定 → 方法内
  裸 `logger` / `self.logger` 混用。修复: 每文件一个模块级 logger，
  `self.logger` 全改裸名（24 处）。运行时影响: 异常处理器内的
  logger 调用自身 NameError 覆盖原异常。
- `model_assets.py:316-324`: `target=_download_worker` 等三处裸名引用
  同类方法 → `self._download_worker`（Thread target 参数立即求值，
  触发下载即 NameError）。
- `docker_build_toolbox.py`: 5 处裸名调用同类 `@staticmethod` →
  `ToolboxBuilder._run_logged(...)` 限定。

**族系二: 幽灵名字**:
- `routes/proxy.py:45`: `return relay_port()` → 名字不存在（真名
  `ProxyRelay.relay_port()`）。**被 except 吞的真 bug**: 每次调用
  NameError → except → 回落默认段——端口顺延场景返回错端口。
- `remote_link.py:40`: 返回注解 `RemoteTunables` → 实为 ConfigManager
  嵌套类，改 `"ConfigManager.RemoteTunables"` + 顶层 import。
- `deps.py` ×3: `ModelAssetStatus` 注解引用未 import（`__future__`
  注解化不求值故未炸）→ 补 import。
- `server.py:38`: 字符串注解引用 asyncio 未 import → 补 import。
- `config_manager.py:512`: 嵌套函数注解 `-> ConfigField` 裸名 →
  `"ConfigManager.ConfigField"`。

## §3 实现规范

### 改动范围表

| 文件 | 改动 |
|---|---|
| `pyrightconfig.json`（新增） | basic 档 + 噪音规则关闭 |
| `services/model_assets.py` | logger 模块级化 + worker 裸名 ×3 |
| `services/model_loader.py` | logger 模块级化 |
| `services/model_lifecycle.py` | logger 模块级化 |
| `services/ocr_engines.py` | logger 两处类体 → 模块级一份 |
| `services/docker_build_toolbox.py` | 5 处 staticmethod 限定调用 |
| `routes/proxy.py` | relay_port 修正 |
| `routes/deps.py` | ModelAssetStatus import |
| `services/remote_link.py` / `server.py` / `config_manager.py` | 注解修正 |

### §3.1 实施步骤（实际执行顺序）

1. 探底: basedpyright 全跑 → 261 error / 1474 warn 规则分布分析
2. 配置落地（basic 档）→ 74 error，UndefinedVariable 20 处定性
3. 族系一修复（logger 4 文件 + workers + staticmethod）
4. 族系二修复（proxy/remote_link/deps/server/config_manager）
5. 回归: pyright UndefinedVariable 清零 + test_control 87/87
   （发现 self.logger 被 logger 移动炸出 → 增补 3 文件统一修复后全绿）
6. 生产重启验证（白名单 spawn 4 键形态 ✓）

## §4 验收标准

**功能验收**:
- `cd backend && pyright` error=58（basedpyright 1.39.9 实测口径，全为
  类型流精确性，二期）; UndefinedVariable 0、PossiblyUnbound 0
- test_control 87/87（含此前被 logger bug 干扰的 /rerank E2E）

**回归验收**: 生产控制台重启正常（pid 4711，白名单 env 恰好 4 键:
HOME/OPENCODE_ROOT/OPENSECURITY_HOME/PATH）

**架构验收**: 零循环依赖新增; 修复均为局部改动无接口变更

## §5 与现有需求文档的关系

- bug #12 修复（本系列第一弹）的"契约扫描规则 3"是人工规则;
  本需求是机器化根治。规则 3 保留（防回归）。
- pending-items #4 勾选。

## §6 实施结果

**完成于 2026-09-29**。全部验收过:
- UndefinedVariable 20 → 0; error 261 → 68（剩余全为二期类型流精确性）
- test_control 87/87; 生产 4711 白名单 4 键
- 意外收获: `routes/proxy.py` 被吞 NameError（端口顺延错配 bug）、
  `model_assets` 下载 worker 三处必炸裸名——均为此前所有人工排查未发现

**二期候选**（未排期）: ArgumentType 30 / AttributeAccessIssue 16 等——**已实施并清零（2026-09-29，见文末"二期实施结果"）**
58 error 清零; mcp-servers 5 error 清零; 注解完备性规则逐档打开。

**增补 1（同日）**: PyCharm 真阳性暴露 pyright 流分析盲区——
`try: import httpx ... except (httpx.HTTPError,...)` 在 import 失败时
except 元组求值即 NameError（model_assets.py `_ocr_cache_state`
Ollama 分支，win/linux + httpx 缺失 → /api/models 500）。已修
（import 单独一层 try/except ImportError + 依赖缺失提示文案）并固化
**契约扫描规则 4**（AST 结构判定 except 引用是否仅由同 try 内 import
绑定）进 test_control"架构守护"用例——同形态回归由测试拦截，不再依赖
人工看 PyCharm 提醒。全仓扫描 0 残留; 规则 4 回退形态注入自证必抓。

**增补 2（同日）: 机制化 + mcp-servers 扩范围**

- 覆盖扩展: `mcp-servers/pyrightconfig.json` 落地（与 backend 同档配置，
  独立演化）; 契约扫描规则 4 的 scan_targets 扩至 mcp-servers
  （control_url.py + 4 个 server.py）。双重扫描 0 命中（代码干净，
  防线为常驻性质）。mcp-servers pyright 存量 5 error（注解完备性，二期）。
- 触发机制固化（"下次写 Python 自动用上"）:
  1. evolve agent prompt 规则 1 升级——.py 检查从 compile 升为
     compile + pyright 全量（有 config 目录自动生效; UndefinedVariable
     = 0 硬线，ArgumentType 新增须评估）;
  2. 领域 agent 侧——$SHARED_DIR/knowledge-base/idapython-conventions.md
     代码风格节新增两大陷阱条目（try 内 import + except 引用 /
     类体绑定 + 方法裸名——含防御形态），生成 IDAPython/分析脚本时
     必读该文件（触发条件已在各领域 prompt）。
- 回归: test_control 87/87（含规则 4 扩范围后全绿）; 生产 49826 正常。
  模式 K 再次实录: 测试挂 ipc_listener（生产占 sock），停生产后全绿——
  已是该模式第二次命中，端口隔离升为高优先待办（已由 #7 于 2026-09-29 闭环）。

**增补 3（外部 review 修复）**:
1. 规则 4 覆盖面缺口（中）: 原实现只遍历作用域直接子语句——try 嵌套在
   if/for/while/with 内全部漏检（lazy import 最常见形态）、TryStar
   （except*）不覆盖。重写为 ast.walk 单遍全量（递归覆盖全部嵌套 +
   TryStar），6 形态回归样本全抓、零重复。已知保守边界: 跨 try 绑定
   （第一层 except ImportError 吞失败 + 第二层 except 引用）不判定——
   与推荐防御形态结构相同，无法区分，接受。
2. remote_link.py 顶层重复 import ConfigManager 删除（F811）。
3. 基线数字修正: §4/§6 的 error=68 更正为实测 58（注解分布变化源于
   修复过程中的类型流演进; 统计口径 basedpyright 1.39.9）。
4. E402 统一: 4 个文件的模块级 logger 从 import 块中间移到块尾
   （与 server.py 风格对齐，消除 noqa 不一致）。
- 回归: test_control 87/87; pyright 58 error 维持。

**环境备注**: 测试 E2E 用例与生产共享 9776 端口与 sock 路径——生产
存活时跑 test_control 的 E2E 用例会 ReadTimeout（历史靠"生产恰好死"
通过）。临时处置: 跑全量前停生产。根治（端口隔离）待三期测试基建。
——**后续修正（2026-09-29，#7 完成）**: 端口本就随机隔离（此前"共用
9776"判断有误）; sock/.ai_env/测试数据已全部沙箱化; 全量 93/93 全程
生产不停机——本段"停生产"处置已废弃。

---

## 二期实施结果（2026-09-29 完成）

### 范围收敛（三线全清）

- **backend 收尾 57 → 0**: 逐文件类型流修复（Optional/联合收窄、overload
  化、库 stub 适配）。期间发现并修复三处真实隐患:
  ① `model_assets._is_cached` 返回 frozen dataclass 但两处调用按 tuple 解包
  （TypeError 隐患）; ② `detect_tools._install_tree` 的 UrlRecipe 分支错误
  路径引用 `r.entry`（AttributeError 隐患）; ③ `_place_from_archive` 形参经
  联合收窄暴露各 Recipe 类字段差异（`bins` 仅部分类拥有 → 收窄为
  `ReleaseRecipe | UrlRecipe`）。
- **mcp-servers 纳入 5 → 0**: PyHANDLE → int 归一（CreateFile 入口一处收口）、
  返回类型收窄、`_CONTROL` dict 注解。
- **tests 纳入 51 → 0**: `_fresh` 返回注解（`-> object` 病灶）、
  `ControlProcess.client` property 收口（`_client` + getter 断言）、42 处
  动态 patch/fake 场景行级豁免、Optional 收窄断言化。

### 注解第一档打开

- `reportMissingParameterType: error`（产品范围硬线）; 48 个参数注解补全
  （含 `InstallRecipe` 联合类型别名抽取）。
- tests 目录文件级豁免（测试 helper 无注解属合理实践）: 17 个测试文件头部
  `# pyright: reportMissingParameterType=false`。

### 稳态与回归

- 全量 test_control **93/93**; 其他族全绿（oop_singletons 6 / remote_link 9 /
  config_manager 5 / model_lifecycle 14 / integration 6 / pytest 47 等）;
  生产全程无损。
- 现行硬线: `basedpyright`（backend 含 tests，71 文件）**0 error / 0 warning**。

### 后续候选（未排期）

- unknown/Any 类规则逐档（reportUnknownParameterType / reportUnknownMemberType
  / reportAny——当前 none）;
- 注解档位继续收紧后的类型流精确性复审。

### 三期实施结果（2026-09-30 完成，需求: 2026-09-30-pyright-unknown-any-tier.md）

- **六规则正式开启**（backend + mcp 双配置）: reportUnknown{Parameter,Variable,
  Argument,Member}Type / reportAny / reportMissingTypeArgument 全部 error。
- **终态**: backend **0 error / 0 warning（71 文件）**; mcp-servers
  **0/0（5 文件）**; 前端 tsc strict 0 error + 显式 any 0 处。
- **实施形态（用户两次方向裁定）**: 模型替代 dict（规则 9 机械化——
  dataclass 响应模型族 + 解析边界 TypedDict + 库类型直用 + 显式子集签名
  替代 Any 转发）; 全家族测试绿（含 104 处 tests 侧修复）。
- 教训与过程详见需求文档执行进度节。
