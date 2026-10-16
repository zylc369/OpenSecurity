# 模型生命周期策略化 + 手动加载/卸载（含远程节点 TTS 预载常驻）

> 状态: Phase 2 需求文档 | 日期: 2026-10-16 | 依赖: 无（独立增量）

## §1 背景与目标

**痛点（现状散装）**：
1. **策略分散**：GLM-OCR 空闲释放写死 600s（`ocr_service.py`）;CosyVoice3 独立 watchdog + `TTS_WORKER_IDLE_SEC` 环境变量（1800s）;bge-m3/reranker 无空闲释放（常驻）;预载名单写死在 `server.py` 步骤 5 的三分支逻辑里
2. **节点场景缺口**：远程节点（CONTROL_API_KEY 模式）预载仅三模型（embedder/reranker/OCR）——**CosyVoice3 不预载**（节点首请求冷启动 ~6s）且 30 分钟空闲释放（听书场景反复冷启动）
3. **手动控制缺口**：模型块只有 OCR 有"释放"按钮（`/api/ocr/release`）——既无通用"加载"，其他模型也无"卸载"

**目标**：
- 空闲释放策略收敛为**代码内常量表**（单一权威，改需求直接改代码）——**不引入配置层/配置文件**
- 场景差异通过**启动参数**传递（`--model-preload` / `--model-idle-sec`，按模型、支持多值）
- 模型块新增通用**加载/卸载**按钮（`POST /api/models/{id}/load|unload`）
- 默认行为**严格守恒**（主控/CI 不加参数 = 完全现状）

**用户已确认的设计裁决**：不做动态配置层;策略"想改直接改代码";启动参数为唯一场景差异入口。

## §2 技术方案

### 2.1 新增 `services/model_policy.py`（策略单一权威）

```python
"""模型生命周期策略表（唯一权威; 启动参数可覆盖空闲释放值）。"""
from __future__ import annotations

# 空闲释放秒数: None=常驻(不释放); 正数=空闲该秒数后释放
DEFAULT_RELEASE_SEC: dict[str, float | None] = {
    "bge-m3": None,
    "bge-reranker-v2-m3": None,
    "glm-ocr": 600.0,
    "cosyvoice3-8bit": 1800.0,
}

_known_ids: frozenset[str] = frozenset(DEFAULT_RELEASE_SEC)
_overrides: dict[str, float | None] = {}

def known_ids() -> frozenset[str]: ...
def apply_idle_override(model_id: str, sec: float) -> None:
    """0 → None(常驻); 负数/未知 id → ValueError(fail fast)。"""
def release_sec_of(model_id: str) -> float | None: ...
```

要点：
- **`0 = 常驻`（None）** 映射在 `apply_idle_override` 内完成（命令行语义直观）
- 未知 id / 非法值在**解析期**抛 `ValueError`——server.py 捕获后 `SystemExit(2)`（启动即失败，防拼错静默失效）
- 模块级 dict 为运行期单例状态（进程生命周期内不变——无锁需求）

### 2.2 `server.py`：启动参数 + 预载扩展

在 `main()` 中**日志初始化之后、IPC/服务实例化之前**解析（fail fast 且日志可查）：

```python
parser = argparse.ArgumentParser(add_help=True)
parser.add_argument("--model-preload", action="append", default=[],
                    help="启动即预载的模型 id（可重复/逗号分隔）")
parser.add_argument("--model-idle-sec", action="append", default=[],
                    help="空闲释放秒数 id=sec（0=常驻; 可重复/逗号分隔）")
args = parser.parse_args()
# flatten: 每项按 "," 拆分; --model-idle-sec 每项按 "=" 拆
```

- `--model-preload` 值：未知 id → `parser.error(...)`（打印已知 id 列表; argparse 标准 exit 2）
- `--model-idle-sec`：`id=sec` 格式校验;`sec` 数值解析（int/float）;`0`→常驻映射;未知 id/非法值 → `parser.error(...)`
- 解析完成后调 `model_policy.apply_idle_override(...)` 逐项注入

**步骤 5 预载改造**：原三分支逻辑保留，末尾追加显式预载集合：

```python
_preload_ids: list[str] = []          # 三分支逻辑产出（node→三项; remote→空; normal→embedder）
for mid in _explicit_preload_ids(args):   # 命令行显式清单
    if mid not in _preload_ids:
        _preload_ids.append(mid)
for mid in _preload_ids:
    _preload_model_by_id(mid)          # daemon 线程后台执行（不阻塞启动）
```

预载执行：**单个 daemon 线程串行跑完全部预载项**（与现有 `preload_all_models_background` 同构——不阻塞启动;失败逐项捕获日志不致命）。

`_preload_model_by_id(model_id)` 分发（新函数，放 server.py 或 model_loader 侧）：
- `bge-m3` → `ModelInferenceService.get_instance().get_embedder()`
- `bge-reranker-v2-m3` → `.get_reranker()`
- `glm-ocr` → `OcrService.get_instance().warm_up_sync()`
- `cosyvoice3-8bit` → `TtsService.get_instance().warmup()`

### 2.3 `services/tts_service.py`：策略接入 + 公开 warmup

- 删 `WORKER_IDLE_SEC = float(os.environ.get("TTS_WORKER_IDLE_SEC", "1800"))`
- `_ensure_idle_watchdog` 启动时读一次 `model_policy.release_sec_of("cosyvoice3-8bit")`（该时机晚于启动参数注入）：
  - `None` → **不启动 watchdog**（常驻）
  - 正数 → 原 60s 周期检查逻辑（阈值取该值）
- 新增公开方法：
  ```python
  def warmup(self) -> None:
      """预热: spawn worker + 极短合成确保模型+质检链路就绪（节点预载用）。"""
  ```
  实现：`self.synthesize("好。")`（走完整链路含 QC;结果入缓存无害）;异常不抛出（日志告警——预载失败不致命）

### 2.4 `services/ocr_service.py`

- `IDLE_RELEASE_SEC = 600`（L42 硬编码）→ `idle_timeout_sec=model_policy.release_sec_of("glm-ocr")`（构造处 L120）
- `st.idle_release_sec`（状态上报，L72）同步改读策略值;`routes/ocr.py` 的 `OcrReleaseResult.idle_release_sec` 类型 `int` → `int | None`（常驻场景 null;前端倒计时行已有 `idle_timeout_sec != null` 判空 ✓）

### 2.5 `services/model_loader.py`

新增单模型释放（供 unload API 使用，避免 `release_all_local` 连带释放）：

```python
def release_embedder(self) -> None: ...
def release_reranker(self) -> None: ...
```

### 2.6 `routes/models.py`：加载/卸载 API

```python
@router.post("/{model_id}/load")    # → {"ok": True, "model_id": ..., "loaded": True}
@router.post("/{model_id}/unload")  # → {"ok": True, "model_id": ..., "loaded": False}
```

- 分发映射（未知 id → 404）：

| model_id | load | unload |
|---|---|---|
| bge-m3 | `ModelInferenceService.get_instance().get_embedder()` | `.release_embedder()` |
| bge-reranker-v2-m3 | `.get_reranker()` | `.release_reranker()` |
| glm-ocr | `OcrService.get_instance().warm_up_sync()` | `.release_sync()` |
| cosyvoice3-8bit | `TtsService.get_instance().warmup()` | `TtsService.get_instance().release()` |

- 同步阻塞返回（加载最长约 10s——手动操作场景可接受;前端按钮 loading 态）
- 旧 `/api/ocr/release` 路由**保留不动**（兼容）

### 2.7 `services/remote_node.py`：节点参数注入

```python
# 模块级常量（节点场景差异的唯一落点; 想改改这一行）:
NODE_SERVER_ARGS: list[str] = [
    "--model-preload", "cosyvoice3-8bit",
    "--model-idle-sec", "cosyvoice3-8bit=0",   # 0=常驻（不空闲释放）
]
```

Popen（L388）`[sys.executable, "-u", "server.py"]` → `[sys.executable, "-u", "server.py", *NODE_SERVER_ARGS]`。
（`launch_cmd`（L433，`--check` 计划展示）同步带参数，保持展示与实际一致。）

**重启链路无需改动**（已核实）：主控重启 `restart.py` L132 已透传 `sys.argv[1:]`;节点重启走 `remote_node.py` 完整启动链（重新经上述 Popen）——两条路径参数均保留。

### 2.8 前端：`ModelsSection.tsx` + `App.tsx`

- `ModelBlock` 新增按钮（`m.cached && dl.status !== "downloading"` 时显示）：
  - 未加载（`!m.loaded`）→ `加载`（type="primary" ghost;loading 态）
  - 已加载（`m.loaded`）→ `卸载`（type="text" danger）
  - 点击 → `POST /api/models/{id}/load|unload` → 成功 `message.success` + 刷新列表 → 失败 `message.error`
- `ModelsSection` Props 增 `onLoadModel(id)` / `onUnloadModel(id)`;`App.tsx` 接线（fetch + 复用现有 models 刷新回调）
- OCR 旧释放按钮保留（或复用新卸载逻辑——最小改动：保留）

### 2.9 架构影响

- 新模块 `model_policy.py` 被 server / tts_service / ocr_service import——单向、无循环
- 接口变更：`/api/models` 增两路由（纯增量）;`TTS_WORKER_IDLE_SEC` 环境变量**废弃**（已核实：全库仅 `tts_service.py` 一处引用、无部署脚本依赖——安全删除）
- **默认守恒**：不加启动参数时，各模型预载/释放行为与改造前逐项一致

## §3 实施步骤拆分

1. **新建 `services/model_policy.py` + 单测**
   - 文件: `services/model_policy.py`（新）、`backend/tests/test_model_policy.py`（新; tests 目录已存在）
   - 预估: 60 行
   - 验证点: pytest 通过（默认值表/override 生效/0→None/未知 id ValueError/非法值 ValueError）
   - 依赖: 无

2. **server.py 启动参数 + 预载扩展**
   - 文件: `server.py`
   - 预估: 70 行
   - 验证点: `python server.py --help` 含两参数;非法 id 启动报错退出（快速本地跑）;语法+pyright
   - 依赖: 步骤 1

3. **tts_service.py 策略接入 + warmup**
   - 文件: `services/tts_service.py`
   - 预估: 50 行
   - 验证点: pyright;grep 确认 `TTS_WORKER_IDLE_SEC` 零残留;watchdog None 分支代码审查
   - 依赖: 步骤 1

4. **ocr_service.py 策略接入**
   - 文件: `services/ocr_service.py`
   - 预估: 15 行
   - 验证点: pyright;默认 600 行为不变（重启后 /api/ocr 状态 idle_release_sec=600）
   - 依赖: 步骤 1

5. **model_loader.py 单模型释放**
   - 文件: `services/model_loader.py`
   - 预估: 20 行
   - 验证点: pyright
   - 依赖: 无

6. **routes/models.py load/unload API**
   - 文件: `routes/models.py`
   - 预估: 80 行
   - 验证点: 重启服务后 curl 四模型 load/unload 各一次（观察 loaded 状态翻转+内存变化）;未知 id 404
   - 依赖: 步骤 3/4/5

7. **前端按钮 + App 接线**
   - 文件: `frontend/src/sections/ModelsSection.tsx`、`frontend/src/App.tsx`
   - 预估: 60 行
   - 验证点: tsc + vitest + build;人工交互（按钮出现/loading/刷新）
   - 依赖: 步骤 6

8. **remote_node.py 节点参数注入**
   - 文件: `services/remote_node.py`
   - 预估: 12 行
   - 验证点: 单测/代码审查确认 Popen 参数列表含 `NODE_SERVER_ARGS`;`--check` 输出含参数
   - 依赖: 步骤 2

9. **端到端回归 + 提交**
   - 无参数重启主控：models 状态与改造前一致（bge/reranker loaded、OCR 600 idle、TTS lazy）;load/unload API 实测;pyright 0/0/0;前端全绿
   - 验证点: 逐项勾选;progress.md 收口;提交

## §4 验收标准

**功能验收**：
- [ ] `server.py --help` 显示 `--model-preload` / `--model-idle-sec`;非法 id/值启动即报错
- [ ] 不带参数重启：各模型加载/释放行为与改造前一致（默认守恒）
- [ ] `POST /api/models/{id}/load` 四模型各验证成功（loaded:true）;`unload` 释放（loaded:false）
- [ ] 前端模型块出现"加载/卸载"按钮，点击生效并刷新状态
- [ ] 节点启动参数拼装正确（`NODE_SERVER_ARGS` 进入 Popen argv——单测/审查）
- [ ] `TTS_WORKER_IDLE_SEC` 环境变量零残留（grep）

**回归验收**：
- [ ] `pyright` 0/0/0;backend pytest 全过;前端 tsc + vitest + build 全过
- [ ] OCR 旧 `/api/ocr/release` 路由行为不变
- [ ] TTS 常规合成链路不受影响（重启后合成一次验证）

**架构验收**：
- [ ] 策略值仅存在于 `model_policy.py` 一处（OCR/TTS 无重复常量）
- [ ] 无新增配置文件/配置项（不引入配置层——按裁决）
- [ ] `remote_node.py` 节点差异仅 `NODE_SERVER_ARGS` 一处

## §5 与现有需求文档的关系

- 独立增量需求，不依赖「TTS instruct 集成」「流式归档」两组文档
- 变更点：`TTS_WORKER_IDLE_SEC` 环境变量废弃 → 策略表（涉及 TTS 文档/注释同步）
- 与「流式归档」的关系：无（流式延后，本需求不触及）
