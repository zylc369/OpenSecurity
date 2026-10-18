# 需求文档：远程日志查询接口（节点 grep 语义 + 主控转发）

> 状态: Phase 2 草稿
> 来源: 2026-10-18 排查"节点首段 11.8s"卡在"节点日志无远程渠道"（只能人工去 MacMini tail）；用户点名要求通用日志查询能力

---

## §1 背景与目标

### 1.1 背景

1. **远程节点日志无查询渠道**：主控 UI 与 API 均无"读节点日志"能力；
   排查节点侧问题（预热时序、合成耗时、重启行为）只能人工登录节点 `grep`/`tail`，
   agent 无法自助完成"重启节点 → 触发试听 → 两端日志并排分析"的闭环。
2. **日志查询的本质是 grep 不是数据库查询**：调用方（主控/agent）需要的形态是
   "指定日志文件 + 查询条件 + 条数"——等价于 `grep -E "条件" 文件 | tail -n N`。
   分级/时间窗/offset/order 等数据库式参数属于过度设计（条件里带时间片段即可）。
3. **主控 → 节点必须走远程链路**：节点 `192.168.3.3:9776` 直连在现网受
   AP 隔离阻断且不符合架构（唯一通道 = P2P/中继 transport）；转发须复用
   `RemoteConsoleClient`（`_post_json`）。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| G1 | 节点侧新增 `POST /api/logs/query`（grep + limit 语义） | 单测：模式匹配/反向读/跨 chunk/坏字节容错/文件名校验全通过 |
| G2 | 主控侧新增 `POST /api/remote/node-logs/query`（`node=local` 查本机、`node=remote` 经远程链路转发节点） | 转发测试断言目标路径与 payload；e2e 实测两端各查一次 |
| G3 | agent 自动排查闭环就绪（重启远程节点 + 试听 + 拉两端日志 全自助） | e2e：`update-restart` → `node-logs/query` 拉到重启前后日志 |
| G4 | 不引入配置项、不新增数据库式参数（分级/时间窗/offset/order） | 代码审查：请求模型仅 file/pattern/is_regex/limit |

### 1.3 非目标

- 前端 UI（"远程资源"卡日志抽屉）——接口就绪后按需追加
- 日志文件清单端点——本次不做（文件名由调用方明确指定）
- 日志写入/轮转/清理机制改动——只读查询，不动写入侧
- 主控本地日志无须新端点：agent 侧已有文件直读；但 `node=local` 分支复用同一
  查询实现（统一入口，零额外代码路径）

---

## §2 技术方案

### 2.1 数据流

```
调用方（agent / 前端 / curl）
  │
  ├─(查本机)─ POST /api/remote/node-logs/query (node=local，默认)
  │                │
  │                └→ services.log_query.query_log(...)   ← 同一实现
  │
  └─(查节点)─ POST /api/remote/node-logs/query?node=remote
                   │
                   └→ RemoteConsoleClient._post_json("/api/logs/query", body)  ← 远程链路（P2P/中继）
                            │
                            └→ [节点] POST /api/logs/query
                                        │
                                        └→ services.log_query.query_log(...)
```

### 2.2 请求/响应模型

**请求体（两端一致）**：

```jsonc
{
  "file": "remote-node.log",              // 日志**文件名**（非路径）；限定 OPENSECURITY_HOME/logs/ 目录内
  "pattern": "\\[tts\\]|预热|worker",      // 查询条件；空串 = 全部行（纯 tail 语义）
  "is_regex": true,                        // true=Python re 正则；false=字面量包含
  "limit": 200                             // 返回条数上限，1..5000
}
```

**响应体**：

```jsonc
{
  "file": "remote-node.log",
  "lines": ["2026-10-18 09:08:34,006 [INFO] ...", "..."],  // 最近 limit 条匹配，**时间正序**
  "more": false                             // 是否还有更早的匹配未返回（精确：limit+1 探测）
}
```

### 2.3 核心实现（`services/log_query.py`，新增）

**强类型（规则 9）**：

```python
@dataclass(frozen=True)
class LogQueryResult:
    file: str
    lines: list[str]
    more: bool

_READ_CHUNK = 256 * 1024  # 反向读取块大小（测试可 monkeypatch）

def query_log(log_dir: Path, file: str, pattern: str, is_regex: bool, limit: int) -> LogQueryResult:
    """从日志文件尾部反向读取，返回最近 limit 条匹配行（时间正序）。"""
```

**读取算法（反向 chunk 扫描，从文件尾部向前）**：
1. `seek(0, 2)` 取文件大小；循环从尾部读块 `[pos-CHUNK, pos)` 并前移 `pos`。
2. 每块处理：`(本块 + 上一轮残片).split(b"\n")`——**本块（更早字节）在前、残片
   （更晚字节）在后**，跨块断行由此还原；`parts[0]` 为"可能与更早块相连"的新
   **残片**（本轮不参与匹配），`parts[1:]` 为完整行（时间从旧到新）。
3. 对 `parts[1:]` **反向迭代（新→旧）**逐行匹配：正则编译一次放循环外
   （`re.compile(pattern).search`）；`is_regex=false` 用 `pattern in line`；
   空 pattern 恒真。命中即收集（丢弃空串段——含尾空段与裸空行）。
4. 残片保留到下一轮（更早块）拼接；当 `pos==0` 读取的文件首块拼接后，
   `parts[0]` 即完整首行 → 参与匹配后结束。
5. 停止条件：收集到 **limit + 1** 条命中 → 第 limit+1 条为 `more=True` 证据
   （丢弃该条，只返回前 limit 条）；自然读到文件头 → `more=False`。
6. 输出：`matched[:limit]` 反转为时间正序。每行
   `decode("utf-8", errors="replace")` 后 `rstrip("\r")`（坏字节/CRLF 容错）；
   单行超 chunk 由拼接链多轮还原，不设行长上限。
7. `_READ_CHUNK` 以**模块级常量**形式在函数体内读取（测试 monkeypatch 缩小
   块大小即可驱动跨块路径）。

**安全与校验（`query_log` 内单点强制）**：
- `file` 必须 `Path(file).name == file` 且 `file not in (".", "..")`，
  字符集 `^[A-Za-z0-9._-]{1,128}$` → 拒绝任何路径形态（防目录穿越）。
- `(log_dir / file).resolve()` 的父目录必须 == `log_dir.resolve()`（防 symlink 逃逸）。
- 目标不存在或非普通文件 → 拒绝。
- `is_regex=true` 且 pattern 非法 → 拒绝。
- `limit` 由 pydantic 约束 `1..5000`；`pattern` 长度 ≤ 1000。

**异常契约（services 层不依赖 web 框架）**：
- `query_log` 抛标准异常：文件名非法 → `ValueError`；正则非法 → `re.error`；
  文件不存在/非普通文件 → `FileNotFoundError`。
- 两个调用方（`routes/logs.py`、`routes/remote.py` local 分支）**统一**映射：
  `ValueError`/`re.error` → `422`；`FileNotFoundError` → `404`；detail 文案见 §2.6。

### 2.4 节点侧路由（`routes/logs.py`，新增）

```python
router = APIRouter(prefix="/api/logs", tags=["logs"])

class LogQueryRequest(BaseModel):
    file: str = Field(min_length=1, max_length=128)
    pattern: str = Field(default="", max_length=1000)
    is_regex: bool = True
    limit: int = Field(default=200, ge=1, le=5000)

@router.post("/query")
async def query_logs(req: LogQueryRequest) -> LogQueryResult:
    """日志查询（grep + limit 语义；文件名限定日志目录）。"""
    try:
        return await asyncio.to_thread(
            query_log, Path(RuntimePaths.LOGS_DIR), req.file, req.pattern, req.is_regex, req.limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"日志文件不存在: {req.file}")
    except (ValueError, re.error) as e:
        raise HTTPException(status_code=422, detail=str(e))
```

（文件 IO 一律 `asyncio.to_thread`——同 `_forward_get` 的线程域约束：大文件反向读
可能扫几十 MB，禁在事件循环内同步执行。）

`server.py` 路由注册段追加 `logs`（import 与 `include_router` 各一行）。

### 2.5 主控转发端点（`routes/remote.py`，追加）

```python
class NodeLogsQueryReq(BaseModel):   # 字段与约束同 2.4 的 LogQueryRequest
    file: str = Field(min_length=1, max_length=128)
    pattern: str = Field(default="", max_length=1000)
    is_regex: bool = True
    limit: int = Field(default=200, ge=1, le=5000)

@router.post("/node-logs/query")
async def query_node_logs(req: NodeLogsQueryReq, node: str = Query(default="local")) -> JSONResponse:
    """日志查询（local=本机 / remote=经远程链路转发节点）。"""
    client = _forward_or_local(node)
    if client is not None:
        return JSONResponse(content=await _forward_call(
            client._post_json, "/api/logs/query", req.model_dump()))
    try:
        result = await asyncio.to_thread(
            query_log, Path(RuntimePaths.LOGS_DIR), req.file, req.pattern, req.is_regex, req.limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"日志文件不存在: {req.file}")
    except (ValueError, re.error) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return JSONResponse(content=asdict(result))
```

- 复用既有 `_forward_or_local`（409/502 错误语义与其它端点一致）。
- 节点不可达时由 `_forward_call` 统一转 `502 转发失败: ...`。

### 2.6 错误码总表

| 场景 | HTTP | detail |
|------|------|--------|
| file 非法（含路径成分/字符集外/超长） | 422 | `非法文件名: <file>` |
| 文件不存在/非普通文件 | 404 | `日志文件不存在: <file>` |
| 正则编译失败 | 422 | `非法正则: <e>` |
| limit/pattern 越界 | 422 | pydantic 标准报错 |
| 远程节点不可达 | 502 | `转发失败: <e>` |

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 类型 | 改动 |
|------|------|------|
| `services/log_query.py` | 新增 | `LogQueryResult` + `query_log()` 反向读实现（~130 行） |
| `routes/logs.py` | 新增 | `POST /api/logs/query` 薄路由（~55 行） |
| `routes/remote.py` | 修改 | 追加 `NodeLogsQueryReq` + `POST /node-logs/query`（~50 行） |
| `server.py` | 修改 | 路由注册（import + include，2 行） |
| `tests/test_logs_query.py` | 新增 | 核心查询单测（~170 行） |
| `tests/test_remote_logs_forward.py` | 新增 | 转发端点测试（~140 行） |

### 3.1 实施步骤拆分

1. **核心实现 `services/log_query.py`**
   - 文件: 新建 `services/log_query.py`
   - 预估行数: +130
   - 验证点: `python -c compile` + pyright 零新增告警 + 直接调用 `query_log()` 实测
     查主控 `control.log` 的 `\[tts\]`（返回最近 N 条、正序、more 标志正确）
   - 依赖: 无
2. **节点路由 `routes/logs.py` + 注册**
   - 文件: 新建 `routes/logs.py`；修改 `server.py`
   - 预估行数: +55
   - 验证点: compile + pyright + `python -c "from routes import logs"` 可导入 +
     asyncio 直调路由函数（tmp 目录）返回 `LogQueryResult`
   - 依赖: 1
3. **转发端点 `routes/remote.py`**
   - 文件: 修改 `routes/remote.py`
   - 预估行数: +50
   - 验证点: compile + pyright + fake client 断言转发路径 `/api/logs/query` 与
     payload 字段（详见步骤 5）
   - 依赖: 1、2
4. **核心单测 `tests/test_logs_query.py`**
   - 文件: 新建 `tests/test_logs_query.py`
   - 预估行数: +170
   - 验证点: pytest 全绿（用例清单见 §4）
   - 依赖: 1
5. **转发测试 `tests/test_remote_logs_forward.py`**
   - 文件: 新建 `tests/test_remote_logs_forward.py`
   - 预估行数: +140
   - 验证点: pytest 全绿（local 分支走本机实现 / remote 分支走 fake client）
   - 依赖: 2、3
6. **全量回归 + 收尾**
   - 文件: 无代码改动
   - 预估行数: 0
   - 验证点: `pytest tests/ -q` 全绿 + pyright 0/0/0 + `git status` 干净 +
     e2e（用户"更新并重启"节点后，实测两端查询并完成 11.8s 自查）
   - 依赖: 4、5

---

## §4 验收标准

### 功能验收

- [ ] `POST /api/logs/query`（本机起服务或直调）返回符合 grep 语义：`pattern`
      匹配、`limit` 截断、`more` 精确、时间正序
- [ ] 字面量模式（`is_regex=false`）对含正则元字符的条件按原样匹配
- [ ] 空 `pattern` 返回文件最后 `limit` 行
- [ ] `file` 传 `../`、绝对路径、子路径、空串一律 422；不存在文件 404
- [ ] `POST /api/remote/node-logs/query?node=remote` 经远程链路返回节点日志
      （不依赖 `192.168.3.3:9776` 直连）
- [ ] e2e 闭环：agent 可用三件套（`update-restart` + TTS 合成 + `node-logs/query`）
      独立完成"重启 → 试听 → 日志比对"

### 单测用例清单（test_logs_query.py）

1. 基础：小文件多行匹配 + limit 截断 + 正序
2. 跨块：文件 > `_READ_CHUNK`（monkeypatch 缩小 chunk），匹配跨越块边界
3. 单行超 chunk（>1 块）：长行完整还原
4. 正则 vs 字面量（`[tts]` 字面量含 `[` 不炸）
5. 空 pattern = tail 语义（结果不含尾空段/裸空行）
6. more 标志：有更多匹配 → True；恰好耗尽 → False
7. UTF-8/中文行 + 坏字节（`errors=replace` 不抛）
8. 文件名校验矩阵：`..` / `a/b` / `/abs` / `.` / 空 / 非法字符 → 拒绝
9. 404（不存在）；空文件返回空列表

### 转发测试用例清单（test_remote_logs_forward.py）

1. `node=local`：monkeypatch `RuntimePaths.LOGS_DIR` → tmp 目录，直调路由函数 →
   返回本机查询结果（与 `query_log` 直接调用一致）
2. `node=remote`：fake client 捕获 `_post_json("/api/logs/query", payload)` →
   断言转发路径与 payload 四字段（file/pattern/is_regex/limit）
3. `node=remote` 未配置远程连接 → `409`（`_forward_or_local` 既有语义）
4. fake client 抛异常 → `502` 转发失败
5. local 分支异常映射：`ValueError` → 422、`FileNotFoundError` → 404

### 回归验收

- [ ] 既有测试全绿（`pytest tests/ -q`）
- [ ] pyright 0 error / 0 warning（新增） / 0 information
- [ ] 既有 remote 端点行为不变（`update-restart`/`health` 转发回归通过）

### 架构验收

- [ ] 请求/响应全强类型（pydantic + frozen dataclass），无裸 dict 跨层
- [ ] 查询实现单点（`services/log_query.py`），路由与转发均薄封装、零重复逻辑
- [ ] 无新增配置项、无 `docs/` 引用、无魔法值（文件名/条数均由调用方显式传递）

---

## §5 与现有需求文档的关系

- **无冲突**：新增只读查询能力，不改 TTS/远程链路既有行为。
- **互补**：`2026-10-17-p2p-direct-upgrade.md` 提供远程链路（本需求的传输层）；
  `2026-10-17-tts-*` 系列的排查遗留问题（节点 11.8s 冷窗验证）依赖本接口闭环。
- **后续可选**（不在本需求范围）：前端日志抽屉、日志文件清单端点。
