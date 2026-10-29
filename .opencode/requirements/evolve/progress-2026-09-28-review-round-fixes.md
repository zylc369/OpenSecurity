# 进度: 代码评审轮修复（IPC 契约同步 / E2E 沙箱隔离 / 陈旧测试）

> 来源: 用户发起 review（对 4 commits: `b10ee0f` / `0aa841c` / `f24ceba` / `2f829c1` 的评审报告）
> 范围: 评审发现 7 项的逐项核实与修复 + 修复过程中新发现 4 项（全量回归暴露）

## 评审发现处理表

| # | 严重度 | 发现 | 核实结论 | 处理 |
|---|--------|------|----------|------|
| 1 | 中 | `test/control/test_embed_client.py` 2 用例失败（control_url 改读注入 env 后测试未同步） | 实测复现 2 failed（`RuntimeError: OPENSECURITY_CONTROL_IPC 未注入`） | 按新契约重写：注入 env 正例 / 缺失 env 负例（RuntimeError）/ sock 缺失返 None / 端口文件无关性；8 passed |
| 2 | 中 | Windows CI workflow 注入废弃 `DATA_DIR`、缺 `OPENSECURITY_CONTROL_IPC`；被编码错误掩盖 | gh 日志实锤：`UnicodeEncodeError`（首个中文 print，cp1252），env dump 显示 `DATA_DIR: D:\a\_temp` | workflow 改 `OPENSECURITY_CONTROL_IPC`（与 `config_manager.IPC_WINDOWS_PIPE` 逐字一致）+ `PYTHONUTF8: "1"` |
| 3 | 低→中 | `persistence.ts` resume 直读 → 控制台不可用时静默跳过 | 判定为设计内 fail-closed（需求 §2.3"低频要新鲜——直读"+ 9/14 事故教训方向） | 行为不改；`persistence.ts` 调用点注释 + 需求文档 §6 第 6 条明示语义 |
| 4 | 低 | 退役注释残留（events/knowledge/ocr ×server.py + `mcp-manager.ts` 自相矛盾） | 确认（"读端口文件"已退役；"编译期常量地址"与"环境变量注入"矛盾） | 4 个 server.py 统一 "IPC 发现：control_url.py（读注入的 IPC 地址，事实来源）…"；mcp-manager 注释/日志与注入实现对齐 |
| 5 | 低 | SWR 测试断言无法证明"后台刷新成功"（长度相等失败/成功都可过） | 确认；且冷启动时用例整体跳过（自举控制台在单飞用例中、晚于 config 用例） | 加"缓存对象引用被替换"硬断言（失败路径保留旧对象）；bun 二次运行实测该断言真跑并通过 |
| 6 | 低 | `test/control/conftest.py` 隔离强度下降（会读真实 `.ai_env`） | 实锤：真实 `.ai_env` `CONTROL_FRONTEND_DEV=1` → 沙箱 console `is_dev_mode=True`（推导 `ai_env_path` 指向真实 `.opencode/.ai_env`）；且 600s 超时根因即此（dev 态拉 vite/代理慢） | 沙箱 `OPENCODE_ROOT` + stub `.ai_env`（文件写 `CONTROL_FRONTEND_DEV=0`）+ **PATH 剥离宿主 OpenSecurity bin** |
| 7 | 提示 | 工作区未清（untracked/staged） | 确认 | 清单见下方"遗留"，待用户决定提交 |

## 修复过程中新发现（全量回归暴露）

| # | 问题 | 根因 | 处理 |
|---|------|------|------|
| E1 | `test_control_backend::TestHealthLogic` 失败（`AttributeError: get_embedder`） | `model_loader` 已 OOP 化（控制台重构 - 1），模块级 API 不存在 | 改 `ModelInferenceService.get_instance().get_embedder()/is_models_ready()`；3/3 |
| E2 | `test_frontend::test_api_config_meta` 失败（期望 `deepseek-v4-flash`，实际 `deepseek-flash`） | 测试期望自 12f7e59 起陈旧；后端常量 + 真实 `.ai_env` + `graphiti_config` 兜底三处一致为 `deepseek-flash` | 测试对齐后端真值（e2e tooltip 断言同步）；后端不动 |
| E3 | e2e `test_tools_hint_truncated_with_tooltip` 失败 | ① 宿主 bin 泄漏（GoReSym 被 `shutil.which` 判"可用"→提示列渲染"—"）② 提示文案已改为通用 `_AUTO_HINT`（"mandiant"断言陈旧）③ 超宽表格 hint 列中心在视口外（x=1483>1440），hover 不命中 | conftest PATH 隔离 + 测试：显式 `scroll_into_view_if_needed` + tooltip 目标改为 `.ant-typography` + 断言对齐（截断 836>240、tooltip ~30ms 可见） |
| E4 | e2e `test_config_deepseek_grouped_half_width` 悬停竞态（全量文件级必挂、单跑必过） | 前序用例残留横向滚动（`scrollX=209`）→ `hover()` 内部滚动把目标停在视口边缘（`[152, 9251]`），mouseenter 永不命中（3s 不可见实锤） | 测试：显式 `scroll_into_view_if_needed` + 稳定等待再悬浮（修复后 128ms 可见；两用例最小复现从 2/2 挂 → 2/2 过） |

## 验证矩阵

- **test/control 全量: 57/57**（连跑 2 次全绿；含 E2E 34 项。此前 600s 超时 → 修复后 ~76s）
- bun `test-control.ts`: 冷启动 11/11；二次运行（诊断用）中 SWR 引用断言真跑通过
- `bun build`: mcp-manager / persistence OK；4× mcp `server.py` py_compile OK
- `windows-ipc.yml`: YAML 解析 OK；IPC 值与 `IPC_WINDOWS_PIPE` 逐字一致（36 字符、双反斜杠前缀）
- test/deps: 22 passed（复跑）
- 生产资源未扰动（控制台 60468 / vite 87607 全程在）；所有测试沙箱目录与进程已清理

## 决策记录

1. **#3 保持 fail-closed，不改行为**：与 §2.3 设计（"低频要新鲜——直读"）及 2026/9/14 事故教训（禁止 stale 配置驱动决策）一致；以"文档 + 调用点注释"明示，不动代码。
2. **E2 以后端为真值**：`.ai_env`（用户实配）、`graphiti_config` 兜底、ConfigField 提示三处一致 `deepseek-flash`；测试期望属重命名遗留。
3. **沙箱 PATH 隔离（E3 修复的组成部分）**：宿主已装工具不得泄漏为"可用"——工具可用性由沙箱（空 bin）决定，安装提示类断言状态确定化。
4. **E3/E4 测试侧健壮化**：显式滚动 + 稳定等待是 Playwright 长页面 hover 的标准姿势；UI 行为本身在隔离/probe 中均即时（30–128ms 可见），非产品缺陷。
5. **回归口径更新**：repo 级 `test/control` 纳入常规全量回归（本轮起）；此前各轮只跑 `.opencode/control/backend/tests`，导致契约变更消费方漏测。

## 遗留

- 工作区收尾（2026-09-29 更新）: 本轮修改已随 `8b24dd0` 入库；当前 untracked: `pending-items.md`（被 config-cache-ttl §5 引用，建议入库）、`docs/分析/web/分析-Planetary-Probe.md`。
- Windows CI 需 push 后验证（本地无 Windows 环境）；`pending-items.md` #5 已加进展注记。
  → **已闭环（2026-09-29）**: 后续提交（f6d29e8/0e66607）接力修复 Windows 实现层问题后，
  run `36510505269` **success**——管道监听 / Python httpx 管道往返 / 管道互斥 / Bun
  node:http socketPath 往返四项全过；详细迭代见 pending-items §5。
- 观察（非本轮回归）: 1440 视口下页面存在 ≈209px 横向滚动（布局宽度 ≥1649px）——E2E 已适配；如介意布局可另立需求。
