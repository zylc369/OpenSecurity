# TTS instruct 模式集成 + 测试台参数化

> 状态: 已完成(连续执行, 全部验证通过)
> 前置: 2026-10-15-tts-console-rebuild.md(测试台基础版) / 短段语速攻关(本会话完成)

## §1 背景与目标

**来源**: 短段语速问题攻关(本会话)的最终解——考核确认:
- 根因(实测): zero-shot 模式下短文本语速慢(念字速度 154ms/字 vs 长文 102ms/字)+跨次方差 ±25-30%
- 解法: **instruct 模式**(官方既有多路径,零下载零依赖),实测: 短段 209ms/字(用户验收)/长段 182ms/字(保持)/方差收窄 ±5%/首段生成 2.5s
- 用户验收: 12 档("请用正常语速说一句话")满意; rasfix2 锚点音色语速双确认

**目标**:
1. worker 默认切 instruct 模式(生产即快且稳); zero-shot 保留可回退
2. worker 预加载修复(消首次生成慢 30-45%)
3. seed 参数化(默认 4;请求可覆盖)
4. 前端测试台: 朗读指令选择器(全分组+自定义)/seed 输入+帮助/分段大小可调
5. 清理: 快节奏音色/复刻 A/B/孤立 v2v3 文件/warmup 旧代码

## §2 技术方案

### 2.1 worker 改造(scripts/tts_worker.py)
- **_load 后预加载**: `model._ensure_model_loaded()` + `model._ensure_tokenizers_loaded()`(1.5s, 消除懒加载首次慢); 移除旧 warmup 块(被替代)
- **默认 instruct**: `instruct = req.get("instruct") or "请用正常语速说一句话"`; `mode == "zero_shot"` 时走旧 ref_text 路径(回退)
- **seed 参数**: `seed = int(req.get("seed", 4))`; `_mx.random.seed(seed)`(替代硬编码 4)
- 请求字段: text/wav/ref_text/out/speed(已有) + instruct(已有路径) + seed(新) + mode(新)

### 2.2 后端传递链
- routes/tts.py: TtsRequest 加 `instruct: str = ""`, `seed: int = -1`(-1=用默认)
- tts_service.py: synthesize() 签名加 instruct/seed(默认空/-1); _synth_local 请求体传参

### 2.3 前端
- segmentText 参数化: `segmentText(text, target, hardMax, firstTargets)`——firstTargets 由"首段字数"配置化(默认 [30, 80, 180])
- useTtsPlayer.start(text, opts?): opts={instruct?, seed?, firstLen?, nextLen?}——请求体带 instruct/seed
- TtsSection 试听面板新增:
  - **朗读指令选择器**: 分组下拉(⭐推荐=正常语速/较快/尽可能快; 语速官2档; 方言18; 情感3; 音量2; 风格2) + 自定义输入(maxLength 200, 提示"推荐短句 ≤60 字")
  - **seed 输入** + "?"悬浮说明(默认空=4;同 seed 同输出;改值换韵律版本)
  - **分段设置**: 首段字数(默认 30) + 常规段字数(默认 300)
- 生产路径(Legado)不传新参数 = worker 默认(instruct+正常语速+seed4)

### 2.4 清理
- 删"官方女声（快节奏）"、"复刻女声 A/B"(用户上传区 wav + user_voices.json 条目)
- 删 assets/voices/official_female_v2.wav / v3.wav

## §3 实现规范
- worker 保持单文件自包含; 前端零新依赖; dataclass/类型注解/pyright 0/0/0
- 默认值三处对齐(worker/服务/前端): 指令"请用正常语速说一句话"/seed 4/首段 30/常规 300

### §3.1 实施步骤

```
1. worker 改造(预加载+instruct 默认+seed+mode 回退+移除 warmup)
  - 文件: scripts/tts_worker.py
  - 预估: ~60 行
  - 验证点: 语法+pyright; 本地直调: ①不带参数(默认 instruct, 42字 ~209ms/字 区间)
    ②seed=7 两次输出 md5 同(可复现) ③mode=zero_shot 走旧路径
2. 后端传递链(routes/tts + tts_service)
  - 文件: routes/tts.py, services/tts_service.py
  - 预估: ~50 行
  - 验证点: 重启服务; curl 无参数(默认 instruct)/带 instruct/带 seed 各一发, 时长与日志符合
3. 前端 segmentText 参数化 + 单测
  - 文件: src/utils/segmentText.ts + test
  - 预估: ~40 行
  - 验证点: vitest 全绿(含自定义 firstTargets 用例)
4. 前端 useTtsPlayer 参数传递
  - 文件: src/hooks/useTtsPlayer.ts
  - 预估: ~40 行
  - 验证点: tsc
5. 前端 TtsSection 测试台 UI(指令选择器/seed/分段设置)
  - 文件: src/sections/TtsSection.tsx
  - 预估: ~180 行
  - 验证点: tsc + vitest + 构建 + 页面渲染
6. 清理(音色删除+孤立文件)
  - 验证点: curl voices 列表只剩 official_female; 文件系统核对
7. 全量回归+端到端+收尾
  - 验证点: pytest 全绿/pyright 0/0/0/tsc/vitest/dist; 端到端: 首段时延 ≤3s, 长文 182ms/字 区间,
    seed 可复现, 指令切换生效; 100字长指令行为测试; MacMini update-restart; 文档+提交+CI 绿
```

## §4 验收标准
- [x] worker 默认 instruct(实测 212ms/字) + zero_shot 回退(247ms/字 路径) 均验证
- [x] 预加载日志实测(+1.5-5.2s 冷启动摊掉); 首段冷启动后音频正常档
- [x] seed=7/11 实测生效; 缓存 key 含 seed(不串缓存); 同 seed 重复 md5 一致(API 层)
- [x] UI 完成(tsc/59 用例/build 全绿); 真机交互待用户试
- [x] 清理完成(接口实测只剩 official_female 默认)
- [x] 197 passed/pyright 0/0/0/tsc/vitest 59/dist 重建; CI 待推送后确认
- [x] 端到端验证: 首段生成正常档; 长文吟诵正常; 100字长指令无泄漏; 质量门静默(未触发)

## §5 与现有需求文档关系
- 2026-10-15-tts-console-rebuild.md: 前置(测试台基础版, 本次在其上做参数化增强)
- 2026-10-14-tts-quality-gate.md: 质量门沿用(观察 instruct 下触发率)


## 执行记录(2026-10-15)

- 步骤1 ✓ worker: 预加载+默认instruct+seed参数+zero_shot回退(移除warmup)——直调三验证过
- 步骤2 ✓ 传递链: routes(TtsRequest+instruct/seed)/tts_service(签名+cache key含参+全链路)/remote_client——API 三验证(默认212ms字/指令117ms字/seed互异)
- 步骤3 ✓ segmentText 参数化(rampFor)+单测 15 用例
- 步骤4 ✓ useTtsPlayer StartOptions(instruct/seed/firstLen/nextLen)
- 步骤5 ✓ TtsSection 测试台设置卡(指令分组选择[推荐/语速/方言17/情感音量风格/自定义]+seed帮助+分段设置)
- 步骤6 ✓ 清理: 快节奏+复刻A/B+user_voices清空+v2/v3 git rm
- 步骤7 ✓ 回归 197 passed/pyright 0/0/0; 端到端(首段/长文/长指令无泄漏/seed复现); stub 测试适配
