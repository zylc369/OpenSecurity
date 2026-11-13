# 待办（暂存）: TTS 独立 venv（.venv-tts 落地）

## 背景

venv 单环境共管的依赖冲突已发生两起（2026-11-01 环境破坏事件）：
- soundfile 被混入旧版 0.9.0.post1 → 炸掉 bge-m3 加载链（transformers/datasets
  音频模块连带 import）+ 本地 TTS 合成
- antlr4-runtime 4.13.2 混入 → funasr/hydra/omegaconf（TTS 质检链）import 即炸

当前取舍：antlr 锁 4.9.3（python-fx/qiling 侧让位）; soundfile 已钉扎 >=0.13.1。

## 方案（触发条件出现时执行）

**架构口子已存在**：tts_worker.py 本就是独立进程（stdin/stdout 行协议），
文档头早已设想"独立 venv .venv-tts"，仅未落地。

- TTS 推理 + funasr 质检整体挪进 worker 的独立 venv（质检目前在主进程
  _synth_qc_local——需一并进程化）
- 主 venv 只留调度壳（TtsService 路由/缓存/远程优先）
- 安装链拆分：worker venv 依赖独立清单（mlx_audio_plus/funasr/soundfile 等）

## 触发条件（满足其一即执行）

1. funasr/hydra 升级到只支持 antlr>=4.13，而主控其他链锁死 4.9
2. TTS 依赖继续膨胀，开始挤压主控环境稳定性
3. 再次发生 TTS 链依赖破坏主控环境的事件

## 成本预估

中：worker venv 创建 + 依赖清单拆分 + 质检进程化（音频回传）+ 启动链适配。
