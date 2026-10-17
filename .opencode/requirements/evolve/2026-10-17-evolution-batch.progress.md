# 进化批次台账（锁拆分 → 惰性分段 → 抢速实测）

> 2026-10-17 | 需求: `2026-10-17-tts-lock-split.md` + `2026-10-17-tts-lazy-segmentation.md`

## 一、锁拆分（后端）—— ✅ 已完成

| 步骤 | 内容 | 验证 |
|---|---|---|
| 1 | 缓存细锁 `_cache_lock` + 质检串行锁 `TtsQC._check_lock`（拆锁前由大锁顺带串行——自审挖出的必要配套） | test_tts_service/tts_qc_flow 全过 |
| 2 | 本地信号量 `_local_sem(1)` 重构 `synthesize`（本地+fallback 统一入口）; `release`/`warmup(force_local)` 接入 | ★ 测试通过 |
| — | 新增 `test_tts_lock_split.py`: ①★慢远程（阻塞 2s）不阻塞本地（<1s 返回）②本地域并发峰=1 | 2 passed |
| 3 | 回归 | 快集 **225 passed** / test_control **97 passed** / pyright **0/0/0** |
| 4 | 真机 | 重启+冒烟: 首请求 14.6s（含 worker 冷启动）/ 音频 4.2s ✓ |

**测试基建三连修**（本批暴露→修复）:
1. link 单例补丁泄漏（`_mk_service` 用前 `_reset_for_tests`）
2. relayd 依赖全局远程态（error-facets 用例锁死本地路径）
3. tts_service 协议单测未隔离质检（假 wav 走真 ASR→calls 翻车→质检纯化）+ link 泄漏源
   stub（`_model_inference` 预热 / TTS / OCR 卸载——真调用会真起模型线程毒化进程）
4. ★ 测试上游接管（`get_instance` 桩对象——绕开前序文件遗留的类/单例绑定状态）

## 二、惰性分段（前端，含正文选词朗读）—— ⏳ 进行中

按 `2026-10-17-tts-lazy-segmentation.md` §3.1 七步：
1. ⏳ `scanSentence` 抽取 + `createSegmentFeeder` 实现（等价性单测）
2. ⏳ feeder 独立单测（惰性: 791 万字 next() 首调 <5ms）
3. ⏳ 播放器切换（数组→游标; 删 segTotal/totalSec）
4. ⏳ UI 简化（"已读 N 段"）
5. ⏳ 正文阅读视图（窗口化渲染）
6. ⏳ 选中文字→右键→朗读
7. ⏳ 全量回归 + 真机 + 提交

## 三、抢速量化实测 —— ⏳ 待做（所有代码改完后）

- 方法: 并发 embedding 循环 + TTS 合成, 量 RTF 退化幅度
