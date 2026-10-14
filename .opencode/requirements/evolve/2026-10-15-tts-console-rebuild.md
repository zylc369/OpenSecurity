# TTS 控制台交互重建(听书深度测试台)

> 状态: 执行中(用户授权连续执行)
> 确认链: 对话逐项确认(方案 1-6 + 断句规则 + 质检方案 A + Legado 段级模式 + 默认音色 .ai_env)

## §1 背景与目标

**来源**: 用户裁决——手机直测太绕;移除旧 TTS 管理交互(VoiceSection),新建 TTS 管理页先做本地深度测试,通过后服务手机(手机端 Legado 已可直接对接现有 /api/tts,前端测试台与手机打同一接口同一模式)。

**核心方案**(对话确认):
1. 段级协议(Legado 业内标准): 客户端分段+段级 HTTP+整段音频返回;服务端无状态;/api/tts 保留为唯一合成接口(不做 SSE)
2. 暂停/停止/起点全在客户端(前端播放器管理)
3. 预取后续段(2-3 并发 in-flight,服务端锁天然串行)
4. 质检方案 A: 段级请求走现有质量门(N 版重试 max_attempts=4——服务端已有,零改动)
5. 断句规则: 强断点=换行/。！？…!?./(防小数点: . 前后皆数字不切);句内符号(，、；：——)不切;单句>600字逗号兜底;贪心合并目标段 ~300 字;引号内句末标点合法断点(不做引号配对保护)
6. 默认音色: config_manager 新 key TTS_DEFAULT_VOICE(.ai_env 持久化,不入配置 TAB——surfaces 限定);voice_library.default_voice() 配置优先回退第一内置;PUT /api/tts/voices/default;GET /voices 加 is_default

**预期收益**: 本地深度测试台(流式接力试听/自定义文/txt 起点)验证通过即具备服务手机的信心;TTS 默认音色持久化。

## §2 技术方案

### 2.1 后端(轻量)
- config_manager: Keys.TTS_DEFAULT_VOICE + ConfigField(surfaces=[Surface.HIDDEN]——存储态,不入配置 TAB,专用端点管理)
- voice_library.default_voice(): TTS_DEFAULT_VOICE 配置值(音色存在才用) > 第一个 builtin
- routes/tts.py: PUT /voices/default(校验音色存在→set_one→返回);GET /voices 的条目加 is_default
- /api/tts 不动(段级+质量门+缓存已有)

### 2.2 前端(主体)
- **segmentText.ts**(纯函数): 断句+贪心分段(规则见 §1.5)——独立模块供 vitest
- **useTtsPlayer.ts**(播放器 hook): 段队列/预取(≤3 in-flight,AbortController)/Audio 顺序播放(onended 链)/pause/resume/stop/单实例(新播停旧)/状态(segIndex/segTotal/buffered/elapsed)
- **TtsSection.tsx**: 音色列表(antd Table expandable;默认徽标 Tag/设默认按钮)+展开三通道:
  a. 默认文案(128 字固定测试文案,含对话引号/拟声/叹号/省略号/问号全覆盖)
  b. 自定义文字 TextArea(≤2000)
  c. txt 文件选择+起始索引 InputNumber(0 起,默认 0;实时预览"从第 N 字: 「前 20 字…」共 M 字·约 K 段")
  - 播放器条: 状态(第 N/M 段·缓冲 X·当前段进度)+暂停/恢复+停止
  - 上传音色(旧功能迁移,右上角按钮+Modal)
- App.tsx: VoiceSection → TtsSection;删旧组件;api client: ttsSetDefault
- 零新依赖(fetch+Audio 原生)

## §3 实现规范
- 后端 dataclass/类型注解/pyright 0/0/0;前端 tsc strict + vitest;**dist 必须重新构建提交**(CI dist 新鲜度门禁)
- 分段器为纯函数(可测);播放器 hook 状态用 ref 管理并发安全(单实例)

### §3.1 实施步骤

```
1. 后端三件: config key + default_voice 逻辑 + PUT 端点 + is_default
  - 文件: services/config_manager.py, services/voice_library.py, routes/tts.py
  - 预估: ~80 行
  - 验证点: pytest(test_voice_library 新用例: 配置优先/回退/无效配置回退);curl PUT+GET voices 实测
2. 前端分段器 segmentText.ts + vitest 单测
  - 文件: control/frontend/src/utils/segmentText.ts, tests
  - 预估: ~150 行
  - 验证点: vitest 断句规则全用例(换行/句末/省略号/小数点/贪心/超长兜底)
3. 前端播放器 hook useTtsPlayer.ts
  - 文件: control/frontend/src/hooks/useTtsPlayer.ts
  - 预估: ~180 行
  - 验证点: tsc 通过;手工冒烟(步骤 5 集成后真实验证)
4. 前端 TtsSection.tsx(列表+三通道+播放器 UI+上传迁移)
  - 文件: control/frontend/src/sections/TtsSection.tsx
  - 预估: ~280 行(超 200 → 拆 4a 列表+三通道表单 / 4b 播放器集成+上传)
  - 验证点: tsc 通过;页面渲染;三通道交互可用
5. 集成: App.tsx 替换 + api client + 删旧 VoiceSection + npm run build(dist 提交)
  - 文件: App.tsx, api/client.ts, 删 VoiceSection.tsx, dist/
  - 预估: ~60 行(不含 dist 产物)
  - 验证点: tsc/vitest 全绿;dist 新鲜;本地起服冒烟试听
6. 回归+推送: pytest 全量/pyright/前端三项/build/commit/push/CI 绿
  - 验证点: 全绿+CI success
7. 台账与文档收口
  - 文件: 本文档状态 + progress 台账
```

## §4 验收标准
- [ ] PUT /voices/default 持久化(.ai_env 重启后仍生效)且 voices 列表 is_default 正确
- [ ] 分段器: 句子不劈开(切点仅句末);小数点不误切;超长句逗号兜底;段均值 ~300±100
- [ ] 试听三通道(a 默认文案/b 自定义/c txt+索引)全部可用
- [ ] 流式接力: 首段 ~3s 内出声;缓冲数持续>0;段间衔接无明显断裂
- [ ] 暂停/恢复/停止全可用;停止后可立即开新试听(无残留播放)
- [ ] 单实例: 新试听自动停旧
- [ ] c 通道索引预览正确(字符位置/总字数/段数)
- [ ] pytest 全量绿(存量 3 问题除外)/pyright 0/0/0/tsc strict/vitest/dist 新鲜/CI 绿

## §5 与现有需求文档关系
- 2026-10-14-tts-quality-gate.md: 前置(质量门已生产化——本任务段级请求直接复用)
- 2026-10-13-tts-cosyvoice3-plus.progress.md: 台账延续
