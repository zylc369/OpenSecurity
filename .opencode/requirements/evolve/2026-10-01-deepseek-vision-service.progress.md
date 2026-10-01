# DeepSeek 视觉识别服务 — 执行台账

- 需求: 2026-10-01-deepseek-vision-service.md
- 状态: **已实施、已验证、生产已生效**（控制台 15:40 重启加载; opencode 侧 MCP 注册待用户重启 opencode）

## 步骤进度（§3.1）

| 步骤 | 状态 | 验证证据 |
|---|---|---|
| 1. services/vision_service.py | ✅ | compile ✓; pyright 0/0/0（修 2 轮: resp.json Any 收口 + isinstance 收窄 Unknown → cast 模式）; 嗅探冒烟 9/9（PNG/JPEG/GIF87a/GIF89a/WEBP/BMP/文本/空/RIFF非WEBP） |
| 2. routes/vision.py + server.py 挂载 | ✅ | compile ✓; pyright 0/0/0; TestClient 探针 10/10（422×9 + 合法请求→服务层 503 证明 BeforeValidator→VisionImage 全链） |
| 3. mcp-servers/vision/server.py | ✅ | compile ✓; pyright 0/0/0（修 1 轮: AfterValidator 误从 typing 导入）; import 冒烟: FastMCP name=vision、工具 analyze_image、schema minItems=1/maxItems=4、双门槛描述命中 |
| 4. mcp-manager.ts + ocr 描述 | ✅ | bun build exit=0; grep MCP_SERVERS 含 vision; ocr 描述含 analyze_image 指引 |
| 5. test_control 路由契约矩阵 | ✅ | 13 类 422 + 形状断言 + 无 key 503; **修 1 个真 bug: tests.test_control import 时把 OPENSECURITY_AI_ENV 重设为含 key 副本 → 子进程 import 后再覆盖 + ConfigManager._reset_for_tests()**（首跑真打了 DeepSeek 被上游 400 拒——顺带发现上游校验图片真实可解码性） |
| 6. test_control 服务级 mock 上游 | ✅ | payload 构造（model/max_tokens/text块/image_url data URL/Bearer）+ 多图 3 块 + usage/model 缺省回退 + 空白content/content为list/缺choices/body非dict → 502 + 401/429 透传 + ReadTimeout → 504 + _to_int 边界（bool 排除）; pyright 修 1 处（url[:40] object 索引 → str() 包裹） |
| 7. e2e 真链路 + live 验证 | ✅ | 控制台 15:40:01 execv 自重启（/api/system/restart）→ health 2 次探测 OK; `test_e2e_real.py vision` 5s 全过: ①IPC→控制台→DeepSeek 200，语义答案含"红"+"A"，model=deepseek-flash，tokens>0 ②生产 422 抽样 ×2 ③壳 MCP 直调真答案 ④壳"文件不存在"错误文案; TCP 公口 9776 探针: 空 images→422、坏 b64→422 detail 干净 |
| 8. 收尾 | ✅ | 本文件; pyright backend 0/0/0 + mcp-servers 0/0/0; test_control **97/97**; config_manager.py 零改动（git diff 0 行）; 文档字节扫描 OK |

## 最终验证汇总

- `python tests/test_control.py`: **97/97**（存量 95 零回归 + 新增 2）
- `python tests/test_e2e_real.py vision`: **1/1**（真 key 真模型，成本≈2 次 flash 调用）
- basedpyright: backend **0/0/0**、mcp-servers **0/0/0**
- 生产实例: 控制台已加载新路由（live 探针证实）; MCP 壳经 mcp_shell_tool 全链实证
- 改动清单: M server.py / M tests/test_control.py / M tests/test_e2e_real.py / M mcp-servers/ocr/server.py / M plugins/lib/mcp-manager.ts; 新增 routes/vision.py、services/vision_service.py、mcp-servers/vision/、需求文档、本台账

## Phase 3 审计记录（需求文档）

- 2 轮修复: §5 引用含糊"如存"（已核实 2026-08-20-ipc-no-port-files.md 实存）; 步骤 5 预估 220 行超 200 上限 → 拆 5/6 两步。纯审计轮零问题。

## Phase 6 审计记录（实现）

- 第 1 轮发现 2 项: ①§4 验收"MCP 壳错误文案"未被自动测试覆盖 → 扩展 e2e 第 4 段断言 ②progress.md/需求状态未落盘 → 本轮补齐。
- 第 2 轮（修复后重查）: _reject_blank 出现 3 处判定——backend 2 处（events.py/vision.py）+ MCP 壳 1 处; 壳与后端物理隔离（独立进程/PYTHONPATH 不含 backend）不可复用 → 实际可抽象 2 处 < 3 次门槛，不抽象（判定记录于此）。
- 纯审计轮: 零问题。

## 关键实现事实（维护参照）

- **DeepSeek 上游会校验图片真实可解码**（魔数+零填充假图 → 400 "unsupported image...formats: webp, png..."）——契约层魔数嗅探是格式白名单，不是合法性保证; e2e/测试必须用真图（PIL 生成）。
- pyright 严格模式处理 `resp.json()`: `typing.cast("object", ...)` 杀 reportAny → isinstance 收窄产物（dict[Unknown,...]）需再 cast 到 `dict[object, object]`。
- BeforeValidator + ConfigDict(arbitrary_types_allowed=True) 可在 pydantic 请求模型里把 b64 str 定型为 dataclass 实例（VisionImage），422 detail 结构与 FastAPI 默认一致。
- 测试子进程若 import tests.test_control，其模块级 env 设置会覆盖外部注入的 OPENSECURITY_AI_ENV——必须 import 后覆盖 + ConfigManager._reset_for_tests()。
- 控制台自重启: `POST /api/system/restart`（1.5s 后 execv，PID 保留）; MCP 壳对新实例自愈（_CONTROL 缓存清空重解析）。
- opencode 重启后 vision MCP 自动注册（mcp-manager MCP_SERVERS）; 未重启前壳逻辑可经 mcp_shell_tool 直调验证。

## 活体验证（15:50 opencode 重启后）

- **MCP 注册**: plugin_debug.log `15:50:41 [McpManager] vision 注册成功`（新进程 5/5: knowledge/events/ocr/vision/proxy）。
- **agent 实调**（全生产链: 本 agent 工具调用 → opencode MCP → 薄壳 → IPC → 控制台 → deepseek-flash）:
  - 单图语义题（无文字标签柱状图——OCR 无法回答）: "三根柱子，最高蓝色，最矮红色" **全对**（412 tokens, 1.6s）。
  - 双图对比: 黄/蓝背景正确识别 + 冷暖色调对比分析（841 tokens, 2.5s）。
  - 返回结构化 JSON（text/model/usage/latency_ms）✓。

## 待办 / 生效条件

- [x] **用户重启 opencode** → vision 工具对 agent 生效（15:50 完成，agent 实调通过）
- [ ] 提交（用户执行）
