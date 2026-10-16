# TTS 流式调研存档（延后处理）

> **状态**: 暂存。触发条件: 决定推进流式 / 评估"段间连续性"替代方案时取用。
> **日期**: 2026-10-16 | **相关**: TTS 听书段式方案（zero-shot + 首段 20 + 常规段 80）

## 一、结论速览

MLX 版 CosyVoice3（mlx-audio-plus 0.1.8）的流式能力处于**半成品**状态：

- **synthesize_streaming 存在且能跑**（音质可用——已试听验收），但 **generate() 主入口未接线**（`stream` 参数为空开关）
- **性能缺陷（致命）**：每块对"累积全量"重推 flow + vocoder（`mel_cache` 全量拼接 + 全量解码; `flow_cache` 恒返回 None）→ 计算量 O(n²) → **长文生成慢于播放 → 断流**
- 社区/上游：PR #1（hsoftxl, 2026-01）给流式做改进被 closed（流程原因: 无描述/中文注释）; 维护者回复"开 issue 描述问题会尝试解决"; 上游 Blaizzy/mlx-audio 无相关议题 → **生态内无人推进**

## 二、关键实测数据

| 配置 | 首块就绪 | 全程 RTF | 适用性 |
|---|---|---|---|
| chunk_size=25（1s 音频/块） | 3.90s | 2.56 | 不可用 |
| chunk_size=50 | 1.22s | 1.17 | 勉强 |
| chunk_size=100（4s 音频/块） | 1.50s | 0.70（118 字） | **短文本可用** |
| chunk_size=100（326 字长文） | 1.51s | 1.22 总量; **末段瞬时 RTF 2.4** | **长文断流** |

长文块间隔曲线（326 字, chunk=100）: 1.6s → 3.7s（前 5 块）→ 4.1~9.4s（第 6 块起超过 4s 音频时长 → 播放追平生成 → 断流）

对照: 段式整段合成 RTF ≈ 0.28-0.42。

## 三、根因（代码级, 可按行核对）

`synthesize_streaming`（cosyvoice3.py L498-666）流式循环内:

```python
mel_cache = concat([mel_cache, mel_new])       # 累积全量
audio = self.mel_to_audio(mel_cache, ...)       # 对全量重跑 vocoder
# flow: tokens_to_mel(chunk_tokens=speech_tokens[:end_idx])  # 全量 token 重跑 flow
```

- `tokens_to_mel` 返回 `(mel, flow_cache)` 但 **flow_cache 恒为 None**（flow.py inference 无 cache 入参/出参利用）
- 官方 PyTorch 版为真增量（chunk cache），MLX 移植未跟进 → 上游注释"Bi-streaming (150ms latency)"仅为框架声明

## 四、可选路线（决策未定）

| 路线 | 内容 | 量级 |
|---|---|---|
| A | worker 层自研流式编排: LLM 增量（本为 Generator）→ 按块单独过 flow/vocoder（含边界处理），**不累积全量** | POC 1-2 天; 音质边界风险 |
| B | 换回官方 PyTorch 栈（官方 bi-streaming 成熟） | 大（重装栈） |
| C | 混合（流式开头+段式接管） | 中, 收益模糊 |
| D | 搁置（现行段式已验收） | 0 |

**前置判断依据**: 流式三卖点中"首响/断档"段式已基本拿到（首段 2.2s、缓冲等待 0-2ms）;**唯一真增量 = 段间连续性**（无段=无接缝漂移）。决策前先做同文本段式 vs 流式盲听（材料见资产目录）。

## 五、资产与脚本

- 音频（持久）: `~/bw-security-analysis/tts-experiments/streaming/`
  - `盲听A.wav` = 流式版 326 字（52.1s）| `盲听B.wav` = 段式版 326 字（74.6s）
- 实验脚本（同目录）: `stream_probe.py` / `stream_probe2.py`（chunk_size 参数化）/ `stream_probe3.py`（长文逐块计时）
  - 用法: `CHUNK=100 python stream_probe3.py`（需主 venv + 模型目录）
  - 关键实现: 复刻 generate() 前处理（tokenize/参考 mel/speaker embedding）后直调 `model._model.synthesize_streaming`
- 流式首响参考: 118 字 chunk=100 → 首块 1.5s（对比段式首段 20 字 ≈ 2.2s）

## 六、决策记录

- 2026-10-16: 用户决定**暂存延后**（先处理更高优先级的段间停顿问题——见下）
- 触发条件: ①段式方案出现"连续性"无法满足的场景 ②上游修复流式性能 ③决定评估路线 A

## 附: 同期发现的段间停顿问题（优先处理）

段式拼接的接缝停顿实测（4 段 [24,94,100,108]）:

| 接缝 | 段尾静音 + 下段头静音 | 合计停顿 |
|---|---|---|
| seg0→1 | 0.14 + 0.43 | 0.57s |
| seg1→2 | 0.14 + 0.70 | 0.84s |
| seg2→3 | 0.26 + 0.58 | 0.84s |

每段音频自带头静音 0.43-0.87s / 尾静音 0.14-0.26s（模型生成特性）。修复方向: worker 生成后端"头尾静音整理"（头留 ~0.2s / 尾留 ~0.12s）→ 接缝停顿降至 ~0.3s（自然换气）。
