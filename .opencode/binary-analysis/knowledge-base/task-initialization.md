# 任务初始化流程

> **按Step顺序执行，不可跳过，不可省略任何步骤。**

---

## Step 1：创建任务目录（强制 — 第一步）

**为什么必须用脚本**：任务目录命名规范为 `YYYYMMDD_HHMMSS_XXXX`（时间戳 + 4 位随机 hex），同时注册 sessionID → task_dir 映射用于压缩恢复。手动创建会违反命名规范且丢失映射。

**规则**：
- **禁止**使用 `workdir` 参数
- **禁止**在项目根目录下创建任何文件
- **禁止**手动 `mkdir` 创建任务目录

**命令**：

```
$PYTHON_CMD "$SHARED_DIR/scripts/create_task_dir.py"
```

`$PYTHON_CMD` 和 `$SHARED_DIR` 由 Plugin 注入到上下文中，不是 shell 环境变量——执行时替换为实际路径。

**`--max-duration` 参数（可选）**：

如果用户指定了最大持续分析时间（如"分析 2 小时"），需要传入 `--max-duration` 参数：

```
$PYTHON_CMD "$SHARED_DIR/scripts/create_task_dir.py" --max-duration 2
```

- 单位：小时（浮点数，如 `0.5` 表示 30 分钟）
- 范围：(0, 24]
- 默认：6 小时（不传时使用默认值）
- 作用：超过此时间后，安全分析 Agent 不再自动恢复空闲 session
- 存储位置：`$TASK_DIR/.persistence.json` 的 `max_duration_hours` 字段

---

## Step 2：环境检测（强制 — 第二步）

检测逆向分析所需的工具链和依赖包。

**命令**：

```
$PYTHON_CMD "$SHARED_DIR/scripts/detect_env.py" --output "$TASK_DIR/env.json"
```

- 成功 → 继续
- **失败 → 停下来告知用户，禁止继续**
- 环境检测结果缓存 24h 到 `~/bw-security-analysis/env_cache.json`，无需每次重新检测
- 可用 `--force` 强制重新检测

> **注意**：`$PYTHON_CMD` 是 venv Python 绝对路径，由 Plugin 在启动时保证可用，无需手动赋值。

---

## 变量总结

初始化完成后，以下变量必须已初始化：

| 变量 | 来源 | 用途 |
|------|------|------|
| `$TASK_DIR` | Step 1 create_task_dir.py | 任务工作目录 |

其他变量（`$AGENT_DIR`、`$SHARED_DIR`、`$IDAT`、`$PYTHON_CMD`）由 Plugin 在每轮注入，不在此流程中初始化。
