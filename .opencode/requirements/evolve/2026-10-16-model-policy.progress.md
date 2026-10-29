# 模型生命周期策略化 + 手动加载/卸载 —— 实施台账

> 需求: `2026-10-16-model-policy-and-manual-load.md` | 实施: 2026-10-16（Phase 2-6 连续执行）

## 实施进度（9 步全完成）

| 步 | 内容 | 状态 | 验证证据 |
|---|---|---|---|
| 1 | `model_policy.py` + 单测 | ✅ | pytest 7 passed; pyright 0 |
| 2 | `server.py` argparse+fail fast+预载扩展 | ✅ | `--help`/非法 id 冒烟; 带参启动日志实证 |
| 3 | `tts_service` 策略接入+warmup | ✅ | pyright 0; env 残留 grep=0 |
| 4 | `ocr_service` 策略接入+类型链 | ✅ | pyright 0; OcrStatus/OcrReleaseResult/model_assets 类型同步 |
| 5 | `model_loader` 单释放接口 | ✅ | pyright 0 |
| 6 | `routes/models` load/unload | ✅ | E2E: TTS load 13.8s(完整预热)/unload/404 |
| 7 | 前端按钮+App 接线 | ✅ | tsc/vitest 65/build |
| 8 | `remote_node` NODE_SERVER_ARGS | ✅ | grep 三处引用(定义/Popen/launch_cmd); pyright 0 |
| 9 | E2E 回归+收尾 | ✅ | 默认守恒(bge 后台预载/tts 懒/ocr 600); 带参全链路(预载+常驻); 重构后冒烟 |

## 审计记录

- **需求审计**（Phase 3）: 轮1 修 7 处（骨架/argparse 位置/预载线程/重启链路/OCR 类型/watchdog 读取时机/tests 目录）; 轮2 干净; 纯审计轮零问题
- **实现审计**（Phase 6）: 轮1 修 3 处（分发抽 `model_ops` 消重复/TTS load 就绪校验/remote_node 参数断言）; 轮2 修 1 处（删薄包装层）; 纯审计轮零问题
- **顺带拦截**（非本需求引入）: `model_assets` 类型链 2 处; `test_control` reaper 测试适配策略表; `test_remote_relayd` stub 缺 `mode` 参数（mode 批次遗漏测试同步——本轮首度全量拦截）

## 全量回归

- pyright 0/0/0; backend pytest 全过（约束内; `test_integration`/`test_e2e_real` 收集期 2 个存量 error 为 pytest 误收集已知项）; frontend tsc + vitest 65 + build
- 默认守恒实测: bge-m3 后台预载 True / TTS 懒加载 / OCR idle=600.0
- 带参实测: `--model-preload cosyvoice3-8bit --model-idle-sec cosyvoice3-8bit=0` → 日志"启动参数生效"+预载日志+`loaded=True`

## 遗留

- MacMini 节点部署: `git pull` 最新代码后 `./start-remote-node.sh`——`NODE_SERVER_ARGS` 自动生效（节点不可达期间以本地参数拼装审查替代）
- TTS 空闲阈值不上报 UI（现状保持; OCR 有倒计时行）
- `TTS_WORKER_IDLE_SEC` 环境变量已废弃（全库零引用）

## 文件清单

- **新增**: `services/model_policy.py`、`services/model_ops.py`、`tests/test_model_policy.py`、`requirements/evolve/2026-10-16-model-policy-and-manual-load.md`（需求）、本台账
- **修改**: `server.py`、`services/{tts_service,ocr_service,model_loader,model_assets,remote_node}.py`、`routes/{models,ocr}.py`、`tests/{test_control,test_remote_relayd}.py`、`frontend/src/{sections/ModelsSection.tsx,App.tsx}`

## 附加批次（2026-10-17 凌晨）: code review 修复

- #7 TTS 空闲 watchdog one-shot 不重排（1800s 永不触发）→ 链式重排; 实测 `--model-idle-sec cosyvoice3-8bit=70` 120s 触发释放 ✓
- #8 节点在线时"加载 TTS"误报 500（warmup 走远程、engine_loaded=False）→ `TtsService.ready`（本地或远程就绪）统一判定, model_ops/model_assets 消费
- #9 `--model-idle-sec bge-m3=…` 校验通过但不生效 → bge/reranker 接入 ManagedModel reaper; 实测 70s 阈值触发卸载 ✓
- #3 重试派生子种子（worker 静音重试 + 服务端质检重试）——同 seed 输出实测仅 ±1 LSB 浮点抖（等效可复现）, 原重试产同版无效
- #4 mode/注释同步 6 处（routes/tts、segmentText、useTtsPlayer）
