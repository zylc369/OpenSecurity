# 需求文档：远程 TTS 链路精简批（质检去重 / 预热可信化 / STUN 日志）

> 状态: Phase 2 草稿
> 来源: 2026-10-17 远程链路 12s 复盘（质检冷加载 4s + 重复质检 1s/段 + 预热假命中）

---

## §1 背景与目标

### 1.1 背景

1. **主控对远程结果重复质检**：节点处理 `/api/tts` 走完整本地链路（含质检+不合格
   派生种子重试，节点日志"交付: 第 1 版（首版通过）"）；主控 `use_remote` 分支又对
   同一 wav 执行一遍同代码同模型的质检——复核结果近乎必然一致，属无依据冗余。
   实测代价：首段冷加载 4s（funasr 1GB 首次加载）+ 每段 ~1s。
2. **TTS 预热假命中**：`_warm_remote_tts` 用固定文本 `"好。"` 经普通缓存路径；
   若该文本命中节点缓存（1ms 返回），预热并未真正烧模型，但主控照样打印
   "节点 TTS 预热完成"——假信号（节点日志"缓存命中, 直接返回（1ms）"实锤）。
3. **STUN 失败日志空错误**：`logger.warning("STUN 探测失败: %s", e)` 在
   `asyncio.TimeoutError`（str 为空）时输出"STUN 探测失败: "——掩盖失败类型
   （排查时误以为无信息；实际是偶发超时，自愈）。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| G1 | 移除主控对远程结果的重复质检（保留网络失败 fallback） | 代码审查 + 回归全绿 + 远程路径日志无质检段 |
| G2 | 预热可信化：预热请求强制穿透缓存（真烧模型） | 单测：payload 含 no_cache；节点侧 no_cache 跳过缓存读写 |
| G3 | STUN 失败日志可读（`%r`） | 代码审查（一行） |

### 1.3 非目标

- 节点侧质检机制不动（含重试闭环——它是功能而非冗余）
- 不做"质检开关"（用户拍板：有问题就消除，不加配置项）
- STUN 偶发超时不追修（自愈；仅改日志格式）

---

## §2 技术方案

### 2.1 P2：移除主控重复质检（`services/tts_service.py`）

`use_remote` 分支（现 L359-387 段）改动：

- **删除**：`q = self._qc_check(wav, text, voice_asset)` 及其后整个质检判定/
  不合格 fallback（`note_request_failure("tts-qc: ...")` 块）。
- **保留**：`wav = client.tts_synth(...)`；成功即返回
  `TtsResult(source="remote")`；`except RemoteUnavailable` 网络失败 fallback 不变。
- **保留**：`_qc_check` 方法本体（本地路径 `_synth_qc_local` 的重试循环仍在用）。
- 注释说明"质检在节点侧完整执行（生产自检含重试）；主控不重复复核"。
- **附带收益**：该分支日志"远程合成完成 Xms"自本次起为纯远程耗时
  （此前混入主控质检时间，曾误导排查）。

### 2.2 P3：预热可信化（no_cache 贯通）

**协议字段**：`/api/tts` 请求体加 `no_cache: bool = False`（可选，默认 false——
旧调用方零影响）。

| 层 | 文件 | 改动 |
|----|------|------|
| 路由 | `routes/tts.py` | `TtsRequest` 加 `no_cache: bool = False`；传入 `svc.synthesize(..., no_cache=req.no_cache)` |
| 服务 | `services/tts_service.py` | `synthesize(..., no_cache: bool = False)`；缓存读（L343 段）与本地写（L402 段）以 `if not no_cache:` 包裹（跳过缓存读写——强制真合成） |
| 客户端 | `services/remote_client.py` | `tts_synth(..., no_cache: bool = False)`；payload 加 `"no_cache": no_cache`（P2P 与 HTTP 分支共用 payload 一处） |
| 预热 | `services/remote_link.py` | `_warm_remote_tts`：`client.tts_synth("好。", "", 1.0, no_cache=True)` |
| 节点 | （同代码——无需单独改） | gateway 转发 payload 原样到节点 backend；节点 `TtsRequest` 解析 no_cache 后走同一 `synthesize` |

**语义**：no_cache=True 时，本次合成不读缓存、不写缓存（真跑模型）；
后续同文本请求仍按缓存语义（1ms）——预热的目的（烧模型）达成且不污染缓存行为。

### 2.3 P4：STUN 日志可读（`services/remote_gateway.py`）

`_stun_probe` 的 `except (OSError, asyncio.TimeoutError) as e:` 分支：
`logger.warning("STUN 探测失败: %s", e)` → `logger.warning("STUN 探测失败: %r", e)`
（TimeoutError 显示为 `TimeoutError()`——可辨识；OSError 显示完整 repr）。

---

## §3 实现规范

### 3.1 实施步骤

**步骤 1. P2 质检去重**
- 文件: `services/tts_service.py`（删 ~20 行，注释 +3 行）
- 预估行数: ~25
- 验证点: `pytest tests/test_tts_service.py tests/test_tts_qc_flow.py tests/test_tts_lock_split.py -q` 全过；代码审查确认 `_qc_check` 仅本地路径引用。
  **既有测试更新预案**：若 `test_tts_qc_flow.py` 等断言了"远程质检不合格→fallback"
  行为——按新语义更新断言（业务变更，允许并应当更新测试）
- 依赖: 无

**步骤 2. P3 no_cache 贯通（四文件）**
- 文件: `routes/tts.py`（~4 行）、`services/tts_service.py`（~10 行）、
  `services/remote_client.py`（~4 行）、`services/remote_link.py`（~2 行）
- 预估行数: ~20
- 验证点: 新增单测——① `remote_client.tts_synth(no_cache=True)` 的 payload 含
  `no_cache: True`（mock transport 捕获 payload，参照 test_remote_client 现有模式）；
  ② `synthesize(no_cache=True)` 不读不写缓存（mock `_synth_qc_local` 返回固定 wav，
  两次调用同文本均未命中——`cached=False` 且 `_cache` 为空）；现有 tts/remote 测试全过
- 依赖: 无

**步骤 3. P4 STUN 日志**
- 文件: `services/remote_gateway.py`（1 行）
- 预估行数: 1
- 验证点: `pytest tests/test_remote_relayd.py -q`（含 gateway STUN 用例）全过
- 依赖: 无

**步骤 4. 回归**
- 文件: 无代码
- 验证点: 后端快集全绿；pyright 0/0/0
- 依赖: 全部

### 3.2 改动文件清单

| 文件 | 类型 | 预估行数 | 步骤 |
|------|------|---------|------|
| `services/tts_service.py` | 修改 | ~35（P2+P3） | 1/2 |
| `routes/tts.py` | 修改 | ~4 | 2 |
| `services/remote_client.py` | 修改 | ~4 | 2 |
| `services/remote_link.py` | 修改 | ~2 | 2 |
| `services/remote_gateway.py` | 修改 | ~1 | 3 |
| `tests/test_tts_no_cache.py` | 新增 | ~70 | 2 |

### 3.3 编码规则

- 缓存跳过逻辑注释明确"预热专用（强制真合成）；不影响普通请求缓存语义"
- 删质检的注释说明"节点侧生产自检含重试闭环"（防后人误加回）

---

## §4 验收标准

### 4.1 功能验收

- [ ] 远程 TTS 路径日志不含"质检"字样（grep 验证）；本地路径质检行为不变
- [ ] `tts_synth(no_cache=True)` payload 含字段；节点 `synthesize` 跳过缓存读写
- [ ] STUN 失败日志显示异常类型（`TimeoutError()`）

### 4.2 回归验收

- [ ] `pytest tests -m "not slow"` 全绿
- [ ] `cd backend && pyright` → 0 errors
- [ ] 前端无需改动（协议字段向后兼容；`/api/tts` 前端调用不传 no_cache）

### 4.3 架构验收

- [ ] 无新增裸 dict 接口；`no_cache` 为强类型 bool 参数
- [ ] `/api/tts` 字段向后兼容（默认 false）

---

## §5 与现有需求文档的关系

- 与 `2026-10-17-p2p-direct-upgrade.md` 同批（远程链路修复），无相互依赖
- 与 `2026-10-17-tts-lock-split.md`：不触碰锁结构（synthesize 缓存段包裹新条件不影响锁语义）
