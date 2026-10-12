# EV-2026-10-13-TTS-COSYVOICE3 进度台账（已完成）

> 需求文档: 2026-10-13-tts-cosyvoice3-plus.md
> 模式: 用户授权无人值守全流程执行（2026-10-13 晨完成）

## Phase 记录
- Phase 2 需求文档: ✓（238 行; §1-§5 + 12 实施步骤）
- Phase 3 审计: ✓ 2 轮修复（instruct 定位/ffmpeg 检测/音色双源/步骤4拆分/worker 生命周期）+ 纯审计 7/7 绿
- Phase 4 执行计划: ✓（架构单向; 12 步无合并）
- Phase 4.5 瘦身: 跳过（不改 agent prompt）
- Phase 5 执行: ✓（见下）
- Phase 6 审计: ✓ 轮1（补静音检测单测）轮2（worker stderr 继承）+ StubTransport 签名 + 错误面用例解耦 → 纯审计零问题
  （语法全检/pyright 0-0-0/grep 双断言/md 字节扫描/pytest 165 passed）

## §3.1 步骤完成状态
| 步骤 | 状态 | 证据 |
|------|------|------|
| 1. tags 体系 | ✓ | filter_by_tags 四语义用例; --model-tags CLI; skip_tts 删 |
| 2. CosyVoice3Asset | ✓ | /api/models 含 cosyvoice3-8bit 无 kokoro; cache_state 目录检测 |
| 3. 音色库 | ✓ | test_voice_library 6 用例（上传/校验/双源）; 官方女声 326KB 入 git |
| 4a. tts_worker.py | ✓ | 协议冒烟（错误路径明确响应）; 静音检测单测 3 分支 |
| 4b. 依赖+安装 | ✓ | .venv-tts 建成; import 链通; requirements 固化（webrtcvad/mlx-lm 坑注释） |
| 5. TtsService 改造 | ✓ | test_tts_service 6 用例; kokoro 引擎代码零残留 |
| 6. 路由+远程参数 | ✓ | voices 端点双源+available; upload 端点; tts_synth 已透传 |
| 7. Kokoro 全清 | ✓ | grep 业务残留 0; 本机缓存删; venv 包卸载; cleanup_kokoro.sh 沉淀 |
| 8. 前端 | ✓ | npm build 过; 模型页 tag 分组; VoiceSection（列表/试听/上传） |
| 9. 测试收口 | ✓ | 165 passed（存量 proxy 污染除外——见"遗留"）; pyright 0-0-0 |
| 10. 本机端到端 | ✓ | 真模型 32.8s→WAV 24kHz; 缓存 0.02s 字节一致; speed 0.9 atempo 生效 |
| 11. MacMini 部署 | ◐ 代码全就绪/物理网络阻塞 | 见"节点部署阻塞分析" |
| 12. 台账收口 | ✓ 本文件 |

## 节点部署阻塞分析（用户醒来后处理）
代码/通道全部就绪（节点已拉到 b73f570 含全部能力），仅模型文件传输被物理网络阻塞:
1. **局域网直连不可达**: MacBook↔MacMini 互 ping 100% 丢包（AP 隔离或 VLAN;
   P2P 一直走外网打洞所以此前未暴露）
2. **VPS ssh 凭据失联**: relayd 部署时的免密 key 已不在 ~/.ssh（只有 gitee/github）
3. **wire 中继吞吐不足**: P2P 打洞夜间失败落中继（经 VPS），512KB 分片 25 分钟零
   进展（外推 >24h，不可行）

**已就绪的重试通道**（任一条件满足即成功）:
- 白天打洞成功时（transport=p2p 直连）: `POST /api/remote/models-push/cosyvoice3-8bit` 一键推送
- 用户提供 VPS ssh 凭据: VPS 中转（http.server 8899 + lan_model_source）
- 用户解除 AP 隔离/确认同网段: 局域网直传（http.server + lan_model_source）
- 节点依赖自愈: TtsWorkerClient._bootstrap_venv（首请求自动跑 install_tts_deps.sh, 2-4min）

## 遗留（不阻塞本次验收）
1. **存量测试隔离缺陷**: test_config_manager → proxy_mcp → proxy_routes 跨文件全局状态
   污染链（stash 对照实锤与本次无关; 单独工作项修复）
2. 音色切换端到端: 当前音色库存量仅 1（official_female）; 用户上传男声后可实测
3. test_e2e_real/test_integration 需真环境标记（存量 skip 语义）
4. 方言 instruct: worker 协议已支持 instruct 字段（面向未来），/api/tts 未暴露（YAGNI）

## 本轮教训（沉淀候选）
- python 行号切片替换在多次编辑后必错位 → 大段替换用 Edit 工具精确匹配
- frozen dataclass 字段不可赋值 → dataclasses.replace
- pyright 行级 ignore 必须与报错同行（import 行的报错在 import 行）
- 无存根生态（librosa/soundfile/mlx）单独文件 pyright exclude（scripts/ 天然不在
  include——worker 无需处理）
- 测试环境依赖宿主状态（"干净环境大概率无模型"）→ 用例必须自造环境（tmp monkeypatch）
