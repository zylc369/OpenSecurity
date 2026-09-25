# 音频模态攻击 — ASR 对抗样本与语音链注入

> 目标为语音/音频 AI 管线（ASR 转录、TTS 合成、语音助手）的攻击面分析时加载。覆盖: 转录文本跨解释器注入、ASR token 抑制绕过、可微分对抗音频、转写歧义消解。

## 触发条件

- 服务接受音频上传 → ASR（Whisper 系）转写 → 转写文本进入下游解释器（TTS 引擎的 SSML、shell、LLM prompt、模板渲染）
- 看到 `espeak-ng -m`、`<audio src=`、`<say-as`、`non_speech_tokens`、whisper `tiny/base/medium` 等标识
- 需要让 ASR 输出指定文本（对抗音频）或从含噪转写中恢复关键内容

## §1 生成内容跨解释器注入（ASR → TTS SSML）

**模式**: 上传的语音被转写后，转录文本被当作**标记语言**（非纯文本）交给下游——`espeak-ng -m` 把 `<audio src="x.wav"/>` 当 SSML 元素混入服务器本地音频文件并播报；同理适用于转录文本进 shell/模板/Prompt 的所有链路。

**审计三问**: ① 转写结果流向哪个解释器？② 该解释器有无标记/命令模式开关（如 `-m`）？③ 标记能否引用服务器本地资源（`<audio src>` 相对路径 → flag 文件常被 `entrypoint` 包装为 `$ICONDIR/flag.wav` 类固定名）。

**判据**: 直接朗读 `<audio .../>` 字面文本 = 下游未按标记解析；响应中混入非语音合成音频（服务器 wav 内容出现在回传音频里）= 注入成功。

## §2 Whisper 符号抑制与组合 BPE 绕过

Whisper 解码默认启用 `non_speech_tokens`（`suppress_tokens`）——**抑制独立符号 token**（`<`、`>`、`=`、引号等 standalone token 概率被置 -inf），因此逐符号朗读 payload 行不通。

**绕过**: 同一字节串可由**组合 BPE token** 拼出，组合 token 不在抑制集内。目标串 ` The HTML code."><audio src="flag.wav"/>` 的 tiny.en token 分解（前缀 ` The HTML code."` 用于闭合上游属性）:

| token id | 文本 | | token id | 文本 |
|---|---|---|---|---|
| 526 | `."` | | 2625 | `="` |
| 6927 | `><` | | 32109 | `flag` |
| 24051 | `audio` | | 13 | `.` |
| 12351 | ` src` | | 45137 | `wav` |
| | | | 26700 | `"/>` |

**方法**: 对目标 payload 用 `whisper.tokenizer.get_tokenizer(...).encode()` 求 id 序列 → 逐个检查是否落在该模型 `non_speech_tokens` 集内 → 全部不在 = 该 payload 可作为优化目标。换 payload 时重新分解（id 表随模型变）。

## §3 可微分对抗音频（让 ASR 输出指定文本）

**目标函数**: teacher-forced 交叉熵——`loss = CE(decoder(prefix + target[:-1], encoder(log_mel(audio))), target)`，对 16kHz 波形直接梯度下降（Adam，lr ~2e-3，~1e3 步，需 GPU）。

**必须包含的工程项**（缺一则本地成功远程失败）:
1. **16-bit 量化前向**: 波形最终以 int16 WAV 存储传输——优化时用 straight-through 估计 `quantized = audio + ((audio*32767).round()/32767 - audio).detach()`，让 loss 看到量化后的值
2. **真实解码路径**: mel 变换/长度/padding 与 `whisper.transcribe` 实际调用一致（`log_mel_spectrogram` + N_SAMPLES padding）
3. **种子音频**: 从合法语音（如目标服务的示例音频）出发而非噪声——分布内更稳

**验证**: 上传量化保存的 WAV → 远程转写 == 目标串。失败时优先查 mel padding 与 tokenizer 的 `no_timestamps` 前缀是否与远程解码一致。

## §4 转写歧义消解（听不清的字符如何定案）

回传音频中关键字符（flag hex 的 `B`/`D` 等）两个 ASR 引擎各执一词时的裁定流程:

1. **双引擎互补转写**: 大模型（`medium.en`）保重复字符计数可靠、快模型（`turbo`）辨单个发音差异更准——两版转写对齐后锁定分歧点
2. **候选合成**: 每个分歧候选用**服务端同款 TTS**（如 eSpeak NG，`en-us` + 服务端语速）合成本地参照音频
3. **最优对齐比对**: 与原始响应音频做互相关找 offset → 窗口去均值后算余弦相似度 + normalized RMSE——正确候选余弦 ≈0.9999+，错误候选 ≈0.1-0.2（数量级差异，无歧义空间）

## 参考

- Whisper `transcribe.py`（suppress_tokens 应用点）与 `tokenizer.py`（BPE 表）
- eSpeak NG `docs/markup.md`（`-m` SSML/HTML 支持与 `<audio src>` 行为）
