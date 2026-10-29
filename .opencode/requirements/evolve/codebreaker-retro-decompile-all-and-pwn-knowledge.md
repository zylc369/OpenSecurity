# 需求: CodeBreaker 复盘进化 — 批量反编译查询 + pwn 技法沉淀 + 调用陷阱提醒

## §1 背景与目标

**来源**: 2026-10-02 CodeBreaker（SunshineCTF pwn 题）复盘。任务成功（远程 flag），但过程暴露三个可进化点。

**痛点数据**:
1. 逐函数 idat 轮询: 全程 **21 次 idat 进程启动**（单函数 decompile×11、read_data×8），每次加载 IDA+DB 约 8s，逆向前期约 60% 时间耗在进程启动等待。57 函数的小二进制本应 1-2 次拿全量
2. 知识缺口: 本次从零摸索的 5 条 pwn 技法（free-先于-refcount UAF / tcache count 账目 / 自定义加密协议还原 / EXEC·DUMP 审计模式 / system 阻塞回显消失）全部未沉淀 MD 知识库（仅记忆库 #7300，非权威全文）
3. 调用陷阱三连: ①shell 算术 `$((0x2040+64))` 产出 10 进制串被 `int(x,16)` 误解析（4 次读到全 FF）; ②`IDA_PATTERN=".*"` 是 glob 语义致 functions 只匹配点开头函数; ③python 块缓冲致 2 次假超时（60s/90s）

**预期收益**: 同类任务 idat 启动 21→2 次左右（速度 >30%）; 下次加密协议/UAF 类题直接命中技法（准确度+轮次）; 陷阱提醒归零同类弯路。

**复盘认知修正**（调查后）: read_data 大 size 仅 bytes 模式已支持（read_bytes_at 任意长度）; 默认 auto 模式的 bytes 回退钳 `min(size_hint, 64)`（_utils.py read_data_auto），本次传参 64 与钳制恰好同值未暴露差异。templates.md 的 query.py 路径全部正确（本次未先读 templates.md 属执行纪律）。故原候选 C 缩水为文档提醒（含 bytes 模式前提）、D 取消。

## §2 技术方案

### 2.1 B: query.py 新增 `decompile_all` 查询

- 新增 `_query_decompile_all()`: 遍历 `idautils.Functions()`，对每个函数反编译（复用现有单函数反编译路径: thunk 追踪 + hexrays 失败回退反汇编），输出到单文件 JSON
- 可选过滤: `IDA_PATTERN`（glob 语义，与 functions 查询一致）跳过不匹配函数; `IDA_SKIP_PLT=1`（默认 1）跳过 PLT stub/thunk/导入占位（判定: 函数名以 `.` 开头 / func.flags 含 FUNC_THUNK / 函数位于 .plt·.plt.sec·.plt.got·.init·.fini·extern 段——stripped 二进制的 PLT 条目命名为 sub_XXXX、extern 段导入符号呈 8 字节伪函数，仅靠名字与 flag 判不住）; stub/占位反编译无信息量，徒增体积
- 输出结构: `{"functions": [{"name", "addr", "size", "source", "source_type", "failed?"}], "total", "decompiled_count", "fallback_count", "failed_count", "truncated"}`; 上限保护 `IDA_MAX_FUNCS`（默认 400，超出截断并标注）
- 单函数失败不中断整体（catch 后记 `"failed": "原因"` 继续）
- JSON 写文件不进上下文，AI 后续用 Read/Grep 按需检索函数源码——把 N 次 idat 启动变 1 次 + 纯文件操作
- 放 query.py 内（复用文件内 `_resolve_func_with_thunk`/`_generate_disassembly`），**不动 _analysis.py**（规避高风险表: _analysis.py 改动需 query 全类型+initial_analysis 端到端回归）

### 2.2 B-prompt 同步: agents/binary-analysis.md 查询类型表加一行

| `decompile_all` | 批量反编译全部函数到单文件（Read/Grep 离线检索，替代逐函数轮询） | `IDA_PATTERN` `IDA_SKIP_PLT` `IDA_MAX_FUNCS` |

### 2.3 A: pwn-methodology.md 增补 5 条技法

按该文件既有风格: 4 条进 §4 卡点突破表（每条一行紧凑格式），加密协议还原因内容多单独小节（§5）。内容遵守知识编写规范（零来源叙事、双键、可操作）。

### 2.4 C+E: templates.md 增补"调用陷阱"节

4 条提醒: ①地址参数必须 0x 前缀（shell 算术展开产出 10 进制会被按 16 进制误解析，拼接用 `printf '0x%x'`）; ②IDA_PATTERN 是 glob 不是正则; ③read_data 的 IDA_READ_SIZE 可传任意大小（如 256/4096，勿默认 64 分段）; ④长跑/交互式 python 一律 `$PYTHON_CMD -u`（块缓冲会伪装成挂起/超时）。

## §3 实现规范

改动范围表:

| 文件 | 改动 | 行数预估 |
|------|------|---------|
| `$SHARED_DIR/query.py` | 新增 `_query_decompile_all` + handler 注册 + docstring | ~70 行（含注释） |
| `$SHARED_DIR/knowledge-base/templates.md` | 新增"调用陷阱"节 | ~10 行 |
| `$SHARED_DIR/knowledge-base/pwn-methodology.md` | §4 表 4 行 + §5 小节 ~18 行 | ~25 行 |
| `agents/binary-analysis.md` | 查询类型表 +1 行 | 1 行 |
| `$AGENT_DIR/knowledge-base/architecture-map.md` | "查询操作（13 种）"→"（14 种）" | 1 行 |

编码规则: 遵循 script-generation.md（双引号/中文日志/JSON 输出/禁 import idc·idaapi）; 知识内容遵循 knowledge-writing-guide.md。

### §3.1 实施步骤拆分

步骤 1. query.py 新增 decompile_all 查询
  - 文件: `$SHARED_DIR/query.py`
  - 预估行数: ~70（新增函数 ~55 + docstring 5 + handler 表 1 + 常量 2）
  - 验证点: ①`python -c compile` 语法过; ②idat 端到端: 在既有 code_breaker.i64 上跑 `IDA_QUERY=decompile_all`，断言 JSON 含 main/sub_1670/sub_1900 用户函数、`total == 13 且 decompiled_count == 13 且 fallback_count == 0`（该二进制用户函数实测 13 个: main/start/sub_1260/12D0/1300/1340/1390/13A0/13F0/1450/1510/1670/1900）、无 .plt 段与 extern 段噪音（sub_1020、free@extern 类不出现）、单 JSON 可被 grep 定位函数名; ③回归: 改动前先取基线（跑 `IDA_QUERY=decompile IDA_FUNC_ADDR=0x11C0` 存档）; 改动后**用全新 i64**（从原始二进制重跑 initial_analysis 生成副本）跑同查询 diff source 字段一致——不可在 decompile_all 跑过的共享 i64 上直接 diff: hexrays 反编译存在类型学习副作用（批量反编译会把类型推断写回 i64，如全局被学习为函数指针、被调函数签名被修正），该差异是 hexrays 行为不是代码回归
  - 依赖: 无

步骤 2. agent prompt + architecture-map 同步
  - 文件: `agents/binary-analysis.md`、`$AGENT_DIR/knowledge-base/architecture-map.md`
  - 预估行数: 2
  - 验证点: 表格行格式与既有行一致; prompt 总行数 < 450（现 273 + 1）; architecture-map "查询操作（13 种）" 改为 "（14 种）"; grep 全库无残留 "13 种" 旧表述
  - 依赖: 步骤 1

步骤 3. pwn-methodology.md 增补 5 条技法
  - 文件: `$SHARED_DIR/knowledge-base/pwn-methodology.md`
  - 预估行数: ~25
  - 验证点: knowledge-writing-guide §7 自检清单逐条过; grep 断言无来源叙事词（SunshineCTF/CodeBreaker/本次/实测）; 技术值抽查（safe-linking 公式、glibc 2.34 key 随机化、counter 公式）与本次验证一致
  - 依赖: 无

步骤 4. templates.md 增补调用陷阱节
  - 文件: `$SHARED_DIR/knowledge-base/templates.md`
  - 预估行数: ~10
  - 验证点: 自包含（不依赖主 prompt 上下文可理解）; 4 条提醒每条含具体示例
  - 依赖: 无

## §4 验收标准

**功能验收**:
- decompile_all 一次 idat 调用产出全函数源码单文件，断言见步骤 1 验证点
- agent prompt 表含新行，格式一致
- pwn-methodology 5 条技法落盘且过自检
- templates.md 4 条陷阱落盘

**回归验收**:
- decompile 单函数查询输出与改动前逐字节一致（同 i64 同函数 diff）
- query.py 其余 12 种查询类型: 抽 entry_points/functions/strings/read_data 冒烟（handler 表未动既有项，冒烟防意外）

**架构验收**:
- 依赖方向不变（query.py 未反向引用，_analysis.py/_base.py/_utils.py 零改动）
- 归属合规（脚本改动在 $SHARED_DIR 根，知识在 knowledge-base/，prompt 在 agents/）
- 无 docs/ 目录引用、无来源叙事词残留

## §5 与现有需求文档的关系

- 复用 script-generation.md 脚本骨架与编码规则，不修改它
- 不与 requirements/evolve/ 现有文档冲突（均为独立主题）
- 记忆库 #7300 已含同源知识，本次 MD 沉淀为权威全文（记忆库条目不引用、不迁移）
