# macOS 本地常驻进程崩溃排查

> 适用：macOS 上本地常驻进程（Python/Node/Rust 等）运行期死亡的排查。
> 核心原则：**进程死亡后第一优先查系统崩溃报告，再查业务日志**——崩溃报告的信息密度远高于业务日志（后者往往戛然而止无任何线索）。

## 1. 触发条件（什么时候用本文档）

- 常驻进程运行期消失：IPC socket 突然 Connection refused、健康检查不可达、心跳丢失
- "重启后又崩"型复发性故障
- 进程无 Python traceback、业务日志停在最后一条正常记录（native 崩溃不走解释器的异常路径）

## 2. 第一步：查崩溃报告

```bash
ls -lat ~/Library/Logs/DiagnosticReports/*.ips | head
```

- 命名：`<进程名>-<日期>-<时分秒>.ips`，时间即死亡时刻
- **对应时刻有 .ips** → native 崩溃，进入 §3 解析
- **无 .ips** → 排除 native 崩溃：SIGKILL（外部强杀，无报告）或进程自身退出逻辑（自杀/reaper），转业务日志找退出原因

## 3. .ips 解析

文件结构：第一行元数据 JSON + 换行后崩溃体 JSON。关键字段：

| 字段 | 含义 |
|---|---|
| `exception` | 类型与信号（`EXC_BAD_ACCESS`/`SIGSEGV`=非法内存访问；`SIGABRT`=abort） |
| `termination` | 终止者（`byProc` 谁发的信号、namespace/code） |
| `faultingThread` | 故障线程索引 |
| `threads[]` + `usedImages[]` | **全部**线程栈与镜像表（符号化靠 imageIndex 查 usedImages） |

Python 解析骨架：

```python
import json, pathlib
p = pathlib.Path.home()/"Library/Logs/DiagnosticReports/<报告名>.ips"
meta, body = p.read_text(errors="replace").split("\n", 1)
c = json.loads(body)
print(c["exception"], c["termination"], "fault:", c["faultingThread"])
imgs = c["usedImages"]
for ti, th in enumerate(c["threads"]):
    for f in th["frames"][:10]:
        img = imgs[f["imageIndex"]]
        print(ti, img.get("name"), f.get("symbol", ""))
```

## 4. 死因分类判定表

| 签名 | 判定 | 下一步方向 |
|---|---|---|
| `SIGKILL`（code 9）且无 .ips | 外部强杀 | OOM（查内存压力/`memory_pressure`）、人为 kill |
| `SIGTERM/SIGHUP` | 外部优雅终止 | 谁 kill 的（launchd/脚本/终端挂断）；进程日志应有信号处理记录 |
| `SIGSEGV/SIGABRT` + native 帧 | native 崩溃 | §5 全线程栈分析定位到库与调用方 |
| exit 0 无业务日志 | 自身退出逻辑 | 查进程内空闲自杀/心跳表清空等 reaper 逻辑 |

## 5. 数据竞争识别（全线程栈对比）

**不要只看 faultingThread**：遍历全部线程栈。并发 bug 的两个指纹：

1. **多线程同处同一 native 库的内部实现**：如两个线程同时位于 `libtorch_cpu.dylib` 的 MPS 内核（一个在 `arange_mps_out`、另一个在 `mps_copy_`）——共享状态无保护并发的直接证据
2. **两线程栈逐帧完全相同**：同代码路径同时执行，典型在共享缓存/查找表的读写上竞争（如 `MetalShaderLibrary` 的 unordered_map）

定位回 Python 层：按线程栈顶部的 Python 帧（`_PyEval_EvalFrameDefault` 上方的 `torch::`/模块符号）反查调用业务模块。

## 6. 常见 native 崩溃源速查（macOS + Apple Silicon）

| 库/框架 | 约束 | 崩溃形态 |
|---|---|---|
| PyTorch MPS 后端 | 多线程并发推理数据竞争（MetalShaderLibrary kernel 缓存无锁）；**跨模型实例同样危险**（后端状态是进程级的） | SIGSEGV，栈在 `AGXMetal*`/`libtorch_cpu.dylib` 的 `at::native::mps::*` |
| MLX | Metal stream 是 thread-local——模型在 A 线程加载、B 线程使用直接报错/崩溃 | `RuntimeError: There is no Stream(gpu, N)` 或 SIGSEGV |
| libomp 重复初始化 | 同进程多份 libomp（numpy/torch/faiss 混链） | `OMP: Error #15`（多为警告，部分场景 abort） |

修复模式对照：

| 约束类型 | 正确修复 | 错误修复 |
|---|---|---|
| 可并发但需互斥（torch/MPS） | 互斥锁包在模型访问出口（调用方拿到的对象自带锁） | 散落在各调用点手动持锁（漏一处即复发） |
| 绑定线程（MLX） | 专职常驻线程 + FIFO 队列（锁只保证互斥、不保证同线程，不够） | 用互斥锁（同线程约束无法用锁表达） |

## 7. OpenSecurity 控制台专属绑定

- 死亡指纹：MCP（events/knowledge）`Connection refused` + plugin 报"控制台不可用"
- 日志三角：`~/bw-security-analysis/logs/{control.log, control-stderr.log, control-stdout.log}`（stderr 含 Python traceback 与资源警告；control.log 为业务日志）
- 同参重启（与 plugin spawn 参数一致）：

```bash
cd <项目根> && nohup env OPENCODE_ROOT=<项目 .opencode 路径> \
  DATA_DIR=$HOME/bw-security-analysis HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  <DATA_DIR>/.venv/bin/python <OPENCODE_ROOT>/control/backend/server.py \
  >> <DATA_DIR>/logs/control-stdout.log 2>> <DATA_DIR>/logs/control-stderr.log & disown
```

- 控制台进程内三类模型的串行约束（违者即 §6 形态崩溃）：
  - BGE-M3 / BGE-Reranker（torch/MPS）：必须经 `model_loader` 的 `LockedEmbedder`/`LockedReranker`（一把 `_infer_lock`，跨两模型互斥）
  - GLM-OCR（MLX）：必须经 `ocr_engines` 的 `_MlxWorker` 专职线程（thread-local 约束）
  - 两框架（torch × MLX）互相并发安全（各自 Metal 资源独立），无需跨框架互斥
