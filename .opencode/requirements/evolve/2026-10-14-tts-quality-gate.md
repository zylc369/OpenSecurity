# TTS 质量门生产化 + plus 服务链收尾

> 状态: 已完成(Phase 5 步骤 1-6 全过)
> 前置: 2026-10-13-tts-cosyvoice3-plus.md（plus 回归/RAS patch/泄漏前缀修复——均已完成并验证）

## §1 背景与目标

**来源**: 2026-10-14 TTS 听书质量攻坚复盘——用户耳朵承担了全部质量验收（12+ 版本人肉试听），三类缺陷（参考泄漏/重复/错字）均由用户首次发现；机器质检缺失是根因之一。泄漏（ref_text 加 system 前缀）与 RAS 采样缺陷已在 worker 修复并验证；ASR 回验原型（tts_qc.py, Paraformer）已验证区分度（1 过 2 拦，拦下版本含真实错音）。

**痛点**: ①质检原型有 5 项短板（见 §2.1）②质检未接入服务生产路径 ③模型资产仍是 torch 时代配置（与 plus 引擎不匹配）④torch 安装链死代码残留。

**预期收益**: TTS 交付文本缺陷趋零（N 版重试+兜底）;每段 ~18-22s 端到端（质检仅 +2s）;资产/代码与 plus 引擎一致;回归测试全绿。

## §2 技术方案

### 2.1 tts_qc.py 生产化（5 短板修复）

1. **泄漏切除精化**: 前缀修复后泄漏不再产生——切除逻辑保留为兜底，但改用 Paraformer 时间戳（sentence_info）定位切点，替代按拼音比例近似切文本
2. **分句级定位**: Paraformer 返回时间戳——比对降到句级（按原文句号/问号/叹号切句，逐句对齐转写拼音，报告错在哪个句——QcResult.bad_sentences 列表
3. **原文自重复豁免**: 重复检测前检查原文拼音自身是否含该 8-gram 重复——含则跳过（诗歌复沓不误报）
4. **多音字分词拼音**: lazy_pinyin 加分词模式（pypinyin seg 词典——"银行"选对读音 yín háng 而非 yín xíng）。注意: 分词只影响多音字**选音**，比对口径仍是不带调拼音（声母+韵母），两件事分开
5. **阈值配置化**: QcConfig dataclass（per_limit/coverage_min/repeat_ngram/max_attempts——服务侧可调，默认值经实测校准（per_limit=0.10）

### 2.2 TtsService 质量门接入

- **懒加载**: QC 单例首次合成才初始化（Paraformer ~1GB 不进启动内存）
- **N 版重试**: _synth_local 生成→质检→不合格重试（上限 QcConfig.max_attempts=4;全不合格取 PER 最小者交付+warning 日志（兜底不空手）
- **质检范围**: 与远程路由共存——synthesize() 远程命中时节点 wav 同样过质检（不合格→note_request_failure+fallback 本地循环，不在远程重试）;远程不可用走既有 fallback 路径不变
- **ref_text 传递**: 质检需要参考逐字稿（泄漏兜底检测——VoiceAsset 已有 ref_text 字段直传

### 2.3 资产与死代码正向清理（不回退 git 历史）

- model_assets.py: 恢复 cosyvoice3-8bit TtsAsset（files=config.json/model.safetensors/tokenizer.json/tokenizer_config.json/README.md, tags=[TTS]）;删除 cosyvoice3-torch 资产条目及目录探测分支;TtsAsset.cache_state 对齐 8bit 目录
- 删除 scripts/install_tts_torch.sh（torch 安装链死代码——自愈已改 uv 直装 plus 依赖）
- install_tts_deps.sh / requirements-tts.txt 若存在残留一并核查清理

### 2.4 架构影响

- 无接口签名破坏（tts_qc.py 新模块、tts_service 内部逻辑、model_assets 数据条目）
- QcResult/QcConfig 均为 frozen dataclass（规则 9）
- 不涉及 agent prompt/Plugin/JSON 输出格式——无高风险改动表项

## §3 实现规范

- 改动范围: scripts/tts_qc.py（重写增强）、services/tts_service.py（质检接入）、services/model_assets.py（资产条目）、删除 scripts/install_tts_torch.sh、tests/（新增 test_tts_qc.py + 适配存量）
- 编码: 类型注解全量;禁裸 dict 业务数据;pyright 0/0/0;每步后语法检查
- 模型资产 id 命名沿用 cosyvoice3-8bit

### §3.1 实施步骤

```
1. tts_qc.py 核心重构: QcConfig 配置化 + 分词拼音 + 原文自重复豁免
  - 文件: scripts/tts_qc.py
  - 预估行数: ~120
  - 验证点: 语法 OK;"银行"拼音=yinhang(非 yinxing);含自重复原文豁免用例通过
  - 依赖: 无

2. tts_qc.py 分句级定位 + 时间戳泄漏切除
  - 文件: scripts/tts_qc.py
  - 预估行数: ~90
  - 验证点: prefixfix_2.wav 质检报告含 bad_sentences（定位到具体句）;语法 OK
  - 依赖: 1

3. TtsService 质量门接入（懒加载+N 版重试+兜底+远程质检）
  - 文件: services/tts_service.py
  - 预估行数: ~80
  - 验证点: 语法 OK;mock 质检永不通过时恰好尝试 max_attempts 次且交付最后一次;mock 远程 wav 质检不合格→fallback 本地循环
  - 依赖: 2

4. model_assets 8bit 资产恢复 + torch 退役 + 死代码删除
  - 文件: services/model_assets.py, 删 scripts/install_tts_torch.sh
  - 预估行数: ~60
  - 验证点: 资产列表含 cosyvoice3-8bit 无 cosyvoice3-torch;grep install_tts_torch 零残留
  - 依赖: 无

5. 测试: 新增 test_tts_qc.py + 适配存量 test_tts_service/test_model_tags
  - 文件: tests/test_tts_qc.py, tests/test_tts_service.py, tests/test_model_tags.py
  - 预估行数: ~150
  - 验证点: pytest 全绿
  - 依赖: 1-4

6. 端到端验证 + 回归 + 收尾
  - 文件: 无新文件（运行验证）;progress.md 更新;git commit+push
  - 预估行数: ~30（文档
  - 验证点: 真实合成一段→质检通过→wav 可放;pyright 0/0/0;pytest 全绿;push 成功
  - 依赖: 5
```

## §4 验收标准

**功能验收**:
- [x] prefixfix 样本质检: 通过版 ok=True、拦版含 bad_sentences 定位
- [x] 服务端到端: synthesize() 返回的 wav 均过质检（不合格已重试/兜底）——e2e_qc.wav 200 OK
- [x] 资产页: 8bit 资产可见可下载，torch 资产不出现——registry 实测 cached=True 1.31GB

**回归验收**:
- [x] pytest 全绿（197 passed; 3 存量问题 stash 验证非本次引起）
- [x] pyright 0 error/0 warning
- [x] worker 生命周期不受影响（孤儿自杀/空闲释放路径未动——仅 ref_text 前缀拼接新增）

**架构验收**:
- [x] 无裸 dict 业务数据（QcResult/QcConfig dataclass）
- [x] 死代码零残留（源码 grep=0）
- [x] git 历史不回退（正向清理 commit 23e4f51）

## §5 与现有需求文档的关系

- **2026-10-13-tts-cosyvoice3-plus.md**: 前置——plus 引擎回归/RAS patch/泄漏修复均由其覆盖并完成;本文档是其质量保障与服务链收尾的续篇
- 台账: 沿用 2026-10-13-tts-cosyvoice3-plus.progress.md（不新建——同一战役连续记录）


## 执行记录(2026-10-14)

- 步骤1 ✓ tts_qc 重构(QcConfig/QcResult/分词拼音 yinhang/自重复豁免多窗口 8-12)
- 步骤2 ✓ 句级定位(bad_sentences; prefixfix_2/3 定位到句, prefixfix_1 全文 7% 通过含 1 个 ASR 弱点句——全文口径设计正确)
- 步骤3 ✓ TtsService 质量门(懒加载 Paraformer/N 版重试 max_attempts=4/兜底 PER 最小/远程质检不合格 fallback 本地/QC 缺失退化放行)——mock 三验证点过
- 步骤4 ✓ 资产 8bit 恢复(repo=mlx-community/Fun-CosyVoice3-0.5B-2512-8bit, cached=True 1.31GB)+torch 资产退役+install_tts_torch.sh/deps.sh/requirements-tts.txt 删除+remote_node 对齐 plus(uv 直装+import 探测)+死代码零残留
- 步骤5 ✓ test_tts_qc.py 新增 10 用例+test_model_tags 适配 8bit; 197 passed
- 步骤6 ✓ 端到端 POST /api/tts 200(410KB wav 15.9s 含冷启动; 缓存命中 2.4ms; Paraformer 懒加载日志证实); pyright 0/0/0(修 2 处: 局域网分支 urllib.request 误删+QcResultT 类型化); 197 passed

## 存量问题(非本次引起, stash 验证过)

- test_proxy_mcp::test_mcp_status_call_shape 环境性失败(JSONDecode——本地 proxy MCP 状态)
- test_integration/test_e2e_real 的 def test(name) 装饰器被 pytest 误收集(fixture 'name' not found)

## 待用户验收

- 服务链产物试听: /var/folders/.../e2e_qc.wav(服务端合成+质检通过版)
- prefixfix_1(过)/2(拦: 汤子们 t/k)/3(拦: 嘿那 h/x) 三版耳朵终审——校准质检阈值可信度
