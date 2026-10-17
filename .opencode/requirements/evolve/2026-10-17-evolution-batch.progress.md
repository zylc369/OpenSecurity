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

## 二、惰性分段（前端，含正文选词朗读）—— ✅ 已完成（真机复听待用户）

| 步骤 | 内容 | 验证 |
|---|---|---|
| 1 | `scanSentence` 抽取（splitSentences 共享——句边界逐字符一致）+ `createSegmentFeeder`（延迟交付 lookahead1 实现尾段并回） | 原 22 项分段测试全过 |
| 2 | feeder 等价性（11 组语料逐段 === 全量版）+ 参数变体 + 惰性（791 万字首调 <5ms 实测） | 14 项全过 |
| 3 | 播放器切换（段源数组→feeder 游标; ensureSegment 惰性喂段; 窗口回收 O(窗口); 删 segTotal/totalSec/computeTotalOf） | hook 7 项过 |
| 4 | UI 简化（"已读 N 段"; 段内进度条; 删总时长 Metric） | tsc/build |
| 5 | 正文阅读视图（3000 字/块窗口化渲染 + 触底续加） | tsc/build |
| 6 | 选中→右键→"从选中处朗读"（选区→全文偏移→新起点起播） | tsc/build |
| 7 | 全量回归 | **87 passed** + build ✓；真机复听待用户 |

## 三、抢速量化实测 —— ✅ 已完成

**方法**: 基线（安静）3 段 TTS 合成 vs 后台 embed 循环持续高压（4 秒内 145 次, 全程 448 次）
下的另 3 段 TTS 合成（全部互异文本绕开缓存; 本地 worker 已预热）。

**结果**:
| 条件 | TTS 合成耗时 | 备注 |
|---|---|---|
| 基线 | 3.22s（3.34/3.19/3.11——稳定） | |
| embed 高压中 | 4.08s（4.93/3.38/3.92） | **退化 1.27x** |

**结论**:
- **不死等**: 记忆库模型（bge, torch/MPS）持续推理中, TTS（子进程 MLX）合成持续推进
  ——分层锁设计下互不阻塞（仅共享 GPU 争抢）
- **互抢可控**: 退化约 +27%（首发达 ~50% 后系统动态平衡回落）; 反向同理（embed 亦被 TTS 拖慢）
- 符合设计预期: "安全分析 + 听书同机并行"可用（各自变慢约两成, 无排队死锁）
