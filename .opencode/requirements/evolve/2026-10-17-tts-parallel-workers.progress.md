# TTS 本地合成双 worker 并行（B） —— 执行进度

需求文档: `2026-10-17-tts-parallel-workers.md`
状态: ✅ 代码全部完成（Phase 2-6）；真机吞吐验收待节点部署（步骤 4 待办）

## 步骤进度

- [x] 步骤 1. TtsWorkerPool + 单测（tests/test_tts_worker_pool.py，5 例）
- [x] 步骤 2. TtsService 接线（Semaphore(2) + 池替换 + docstring 更新）
- [x] 步骤 3. 服务级并发单测（两并发 synthesize 真并行）
- [ ] 步骤 4. 真机吞吐验收（待节点 git pull + 重启后补测：并发两段 ≈ max 非 sum；内存 <15G）
- [x] 步骤 5. 回归（后端 248 passed / pyright 0 / 前端 90 passed）

## 验证点执行记录

- 步骤 1: 池 5 例全过——真并发（峰值分发双桩）/ 第三请求排队 / alive+shutdown /
  接口 mock 兼容（实例级 patch request 与既有测试模式一致）
- 步骤 2: 现有 tts 系全过（fixture 适配：删除 `_worker._ensure` patch——
  池层 request 已被替换，不再触及 client 内部）
- 步骤 3: 服务级并发实证（两并发 synthesize 总耗时 < 串行和）
- 语义更新（业务变更）：`test_local_semaphore_serializes`（容量 1）→
  `test_local_semaphore_concurrency_capacity`（容量=池大小 2；并发峰=2 + 超容排队）
- 步骤 5: 后端全量 248 passed（243+5）/ pyright 0/0/0 / 前端 90 passed

## Phase 记录

- [x] Phase 2 需求文档
- [x] Phase 3 审计（2 轮 + 纯审计；补 1 处 docstring 同步说明）
- [x] Phase 4 执行计划（2 文件，1→2→3；4 待部署；5 收尾）
- [x] Phase 4.5 Prompt 瘦身检查（不适用）
- [x] Phase 5 实施（步骤 1-3、5）
- [x] Phase 6 实现审计（2 轮 + 纯审计：接口兼容核对——`svc._worker` 全部消费点
  [request/alive/shutdown] 池同名覆盖；异常路径归还槽位核对；测试语义更新 1 处）
