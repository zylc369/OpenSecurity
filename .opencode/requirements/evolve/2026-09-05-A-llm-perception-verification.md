# 需求A：LLM 感知结果交叉验证规则
## §1 背景与目标
来源：COMPFEST 18 复盘（19 轮）。glm-ocr 幻觉 "1603115" 驱动 8 轮分析/30+ 错误提交；whisper base 对音乐幻觉。目标：建立 OCR/ASR 结果的强制交叉验证协议，杜绝 vision-LLM 自洽幻觉被采信。
## §2 技术方案
新增 `$OPENCODE_ROOT/web-analysis/knowledge-base/llm-perception-verification.md`（自包含）；web-analysis.md prompt 增 3-5 行触发规则（何时 Read 该文档）。内容骨架：幻觉签名三特征（双经典引擎零检出/裁剪后不可读/位置矛盾）、强制流程（未交叉验证不得作结论）、像素终裁法（帧间差异图）、ASR 规则（大模型空输出≠漏检）。素材：知识库 id 3938。
## §3 实现规范
### §3.1 步骤
1. 撰写知识文档（~120 行，含可执行检查步骤与成功/失败判据）。验证：自包含可独立理解，无 docs/ 引用。
2. web-analysis.md prompt 加触发规则段（插入位置：现有 OCR/媒体分析相关章节之后；无该章节则插入分析方法论章节末尾）。验证：`grep -c "llm-perception-verification" agents/web-analysis.md` ≥1；展开行数 <450（Phase 4.5 复核）。
## §4 验收标准
功能：新 OCR 结果按文档流程可复现幻觉判定。回归：①A_0050 帧（已知幻觉案例）按流程得出"幻觉"结论；②audio_late.wav（已知音乐案例）按 ASR 规则得出"非语音、拒绝转写"。架构：置于 web-analysis/knowledge-base/（通用性不足时升 shared）。
## §5 关系
独立新增；与 id 3938 记忆库条目互补（知识库为权威全文）。
